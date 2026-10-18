# Session Dashboard v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local browser dashboard showing every live Claude Code session's state (🟥🟨🟦🟩⬜), its subagent tree and timeline, and a 5h usage estimate.

**Architecture:** Python stdlib package `dashboard/` reads what Claude Code already writes to disk
(`claude agents --json`, session transcripts, `subagents/*.meta.json`) plus one tiny hook log for
permission prompts. Pure functions turn that into a JSON snapshot; `http.server` serves it at
`/api/state` and a vanilla-JS page polls it every 3 s.

**Tech Stack:** Python 3.11 stdlib only, pytest for tests, vanilla HTML/CSS/JS. No new deps.

**Spec:** `docs/superpowers/specs/2026-10-18-session-dashboard-revised-design.md`

## Spike findings (Task 0, done 2026-10-18 — `claude -p` with a logging `--settings` file)
- `subagents/agent-<id>.meta.json` next to each session transcript holds `agentType`, `description`,
  `toolUseId`, `parentAgentId` (absent ⇒ spawned by main), `spawnDepth`, `requestShape`
  (`foreground`/`background`), `finished`. **The tree comes from these files, not hooks.**
- Hook payloads: tool events inside a subagent carry `agent_id`/`agent_type`; `PreToolUse` on `Agent`
  carries the spawner's `agent_id`. Not needed given meta.json.
- Assistant records carry `message.usage` (`input_tokens`, `cache_creation_input_tokens`,
  `cache_read_input_tokens`, `output_tokens`), `message.model`, `message.id`, `timestamp`.
- 5h rejections: assistant record with `quotaLimits: {status: "rejected", rateLimitType: "five_hour",
  resetsAt: <epoch s>}` ⇒ window was `[resetsAt − 5h, resetsAt)`.
- `claude agents --json` → list of `{pid, cwd, kind, startedAt (ms), sessionId, name, status: busy|idle}`.

## Global Constraints
- Stdlib only at runtime; pytest is the only dev dependency.
- Server binds `127.0.0.1` only. Default port `8765` (`--port`).
- All readers take `claude_dir: Path` (default `~/.claude`) so tests run against fixture trees.
- Context limit: env `CLAUDE_CONTEXT_LIMIT`, default `200000` (same convention as `context-meter.js`).
- Parked threshold: idle > 30 min. Strip label: "this machine only". No notifications of any kind.
- Malformed JSONL lines are skipped, never fatal (files are appended live; last line may be partial).
- Hook log: `~/.claude/dashboard/events.jsonl`, written by a shell one-liner: one `{"ts", "e": <raw payload>}` per line.

## Review Focus
1. Transcript's last line is half-written → reader skips it, no 500 (Task 2 test `test_partial_last_line`).
2. `claude` missing or `agents --json` times out → page shows an error banner, not a blank page (Task 5 test `test_discovery_failure_reported`).
3. Session whose transcript doesn't exist yet (just started) → shown as busy/idle with "no transcript" (Task 5 test `test_session_without_transcript`).
4. Killed session leaves `finished: false` meta files → only live sessions count outstanding subagents; dead sessions aren't listed at all (Task 3 test `test_outstanding_counts_only_unfinished`).
5. No rejections on record → 5h strip shows usage and burn rate, ceiling "unknown" (Task 4 test `test_no_ceiling_samples`).

---

## File Structure
```
dashboard/
  __main__.py      CLI: python -m dashboard [--port] [--claude-dir]
  discovery.py     run `claude agents --json` → list[LiveSession]
  transcripts.py   iter_records(path), session summary (context, last action, last activity)
  subagents.py     meta.json → SubagentNode tree with runtime/tokens/status
  status.py        classify() → State; permission_pending()
  usage.py         5h block, weighted tokens, ceiling samples, projection
  snapshot.py      build_snapshot() → dict for /api/state
  server.py        http.server handler: /, /static/*, /api/state
  install.py       add/remove the hook in a settings.json
  static/index.html, app.js, style.css
tests/  conftest.py (fixture claude_dir builder) + test_<module>.py
```

### Task 1: Status model
**Files:** Create `dashboard/status.py`, `tests/test_status.py`
**Produces:** `class State(StrEnum): APPROVAL="approval", YOUR_TURN="your_turn", WAITING="waiting", WORKING="working", PARKED="parked"`;
`classify(busy: bool, outstanding: int, idle_seconds: float, approval_pending: bool) -> State`;
`PARKED_AFTER_S = 1800`; `SORT_ORDER = [APPROVAL, YOUR_TURN, WAITING, WORKING, PARKED]`;
`approval_pending(last_prompt_ts: float | None, last_activity_ts: float) -> bool` (prompt newer than any transcript write).
- [ ] Tests: approval beats everything; busy → WORKING; idle+outstanding>0 → WAITING; idle 0 outstanding ≤1800 s → YOUR_TURN; >1800 s → PARKED; `approval_pending(None, x)` False; prompt after activity True, before False.
- [ ] Implement, run `pytest tests/test_status.py -v` → PASS, commit.

### Task 2: Transcript reader
**Files:** `dashboard/transcripts.py`, `tests/conftest.py`, `tests/test_transcripts.py`
**Produces:** `iter_records(path: Path) -> Iterator[dict]` (skips bad lines);
`find_transcript(claude_dir, session_id) -> Path | None` (glob `projects/*/<sid>.jsonl`);
`@dataclass SessionSummary(context_tokens: int, model: str | None, last_action: str, last_activity: float)`;
`summarize(path: Path) -> SessionSummary` — reads only the last 512 KB.
`last_action`: last assistant `tool_use` → `"<name>: <short input>"` (Bash command / file_path / description, 60 chars) or the last text block's first line. Context = input + cache_creation + cache_read of the last assistant usage.
conftest: `make_claude_dir(tmp_path)` helper with `add_session(sid, records)`, `add_subagent(sid, aid, meta, records)`.
- [ ] Tests: context from last usage; tool_use action string; text action; `test_partial_last_line`; `find_transcript` hit/miss.
- [ ] Implement, PASS, commit.

### Task 3: Subagent tree
**Files:** `dashboard/subagents.py`, `tests/test_subagents.py`
**Produces:** `@dataclass SubagentNode(agent_id, agent_type, description, parent_id: str | None, depth: int, background: bool, finished: bool, started: float, last_activity: float, tokens: int, children: list)`;
`load_subagents(transcript: Path) -> list[SubagentNode]` (roots; reads `<transcript stem>/subagents/*.meta.json` + sibling jsonl for timestamps/tokens);
`outstanding(nodes) -> int` (unfinished, any depth); `max_depth(nodes) -> int`; `is_specialist(t) = t not in {"general-purpose", "Explore", "Plan", "claude"}`.
- [ ] Tests: nesting via parentAgentId; `test_outstanding_counts_only_unfinished`; missing jsonl tolerated (started = meta mtime); max_depth.
- [ ] Implement, PASS, commit.

### Task 4: 5h usage estimate
**Files:** `dashboard/usage.py`, `tests/test_usage.py`
**Produces:** `weighted(usage: dict, model: str) -> float` = model factor × (input + 1.25·cache_creation + 0.1·cache_read + 5·output), factor opus 1, sonnet 0.6, haiku 0.2, else 1;
`collect(claude_dir, since: float) -> list[tuple[float, float, str]]` (ts, weight, msg_id) over `projects/**/*.jsonl` with mtime ≥ since, deduped on `message.id`, file results cached by (path, mtime, size);
`block_start(ts_list, now) -> float | None` (ccusage rule: block starts at first activity floored to the hour; new block when activity after start+5h);
`ceiling_samples(claude_dir) -> list[float]` (weighted usage in `[resetsAt−5h, rejection ts]` for each five_hour rejection; cached to `~/.claude/dashboard/ceilings.json` keyed by rejection ts);
`estimate(claude_dir, now) -> dict(used, block_start, block_end, burn_per_min (last 30 min), ceiling_median | None, ceiling_lo, ceiling_hi, minutes_left | None, label="this machine only")`.
- [ ] Tests: weights; dedupe; block start rollover; ceiling from a fixture rejection; `test_no_ceiling_samples`.
- [ ] Implement, PASS, commit.

### Task 5: Discovery + snapshot
**Files:** `dashboard/discovery.py`, `dashboard/snapshot.py`, tests for both
**Produces:** `@dataclass LiveSession(pid, cwd, session_id, name, busy: bool, started: float)`;
`list_sessions(runner=subprocess.run) -> list[LiveSession]` raises `DiscoveryError` on missing binary / timeout (10 s) / bad JSON;
`read_prompts(claude_dir) -> dict[str, float]` — per session, ts of the last `Notification` (`notification_type == "permission_prompt"`) or `PermissionRequest` line in the hook log (lines are `{"ts": <epoch s>, "e": <raw payload>}`);
`build_snapshot(claude_dir, sessions, now) -> dict` = `{now, error, usage, sessions: [{session_id, name, cwd, state, last_action, context_tokens, context_pct, idle_s, age_s, outstanding, total_subagents, max_depth, specialists, generals, tokens_last_hour, subagents: [tree as dicts], parent_busy_segments: [[t0,t1]...] (last 20 min, gaps > 60 s split)}]}` sorted by `SORT_ORDER` then idle time.
- [ ] Tests: `test_discovery_failure_reported` (snapshot `error` set, sessions empty); `test_session_without_transcript`; sorting; approval state from a hook-log line.
- [ ] Implement, PASS, commit.

### Task 6: Server + UI
**Files:** `dashboard/server.py`, `dashboard/__main__.py`, `dashboard/static/*`, `tests/test_server.py`
**Produces:** `make_server(port, claude_dir, sessions_fn) -> ThreadingHTTPServer`; snapshot computed at most once per 2 s (cached).
UI per spec Layout: strip of pills (colour by state) + 5h figure "≈Xm left (this machine only)"; list rows (state, name, last action, ctx %, idle); click toggles inline timeline (parent lane busy segments, one lane per subagent indented by depth, ✓/● status, specialist/general label, description); footer max depth / specialists / generals / tokens last hour. Open rows kept in `localStorage` (try/catch). Error banner when `error` set. Dark/light via `prefers-color-scheme`.
- [ ] Test: server on port 0 with a fake `sessions_fn`; GET `/api/state` → 200 JSON with `sessions`; GET `/` → 200 HTML; unknown path → 404.
- [ ] Manual: `python -m dashboard`, open in browser, compare to `docs/mockups/combined-v1.html`.
- [ ] Commit.

### Task 7: Hook install + docs
**Files:** `dashboard/install.py`, `tests/test_install.py`, `README.md`
**Produces:** `HOOK_CMD` = shell one-liner: `mkdir -p ~/.claude/dashboard && { printf '{"ts":%s,"e":' "$(date +%s)"; tr -d '\n'; echo '}'; } >> ~/.claude/dashboard/events.jsonl` (raw payloads never contain literal newlines, so stripping them is lossless);
`install(settings: Path)` adds it under `Notification` (matcher `permission_prompt`) and `PermissionRequest` (matcher `*`), idempotent; `uninstall(settings)` removes only entries with that command. CLI `python -m dashboard.install [--uninstall] [--settings PATH]`.
- [ ] Tests: idempotent install; uninstall leaves other hooks intact.
- [ ] Apply to live config via worktree `~/.claude-wt/dashboard-hook` on `feat/dashboard-hook` (self-config rule); verify a fresh `claude -p` session with that config logs nothing breaking; merge only after James's go-ahead.
- [ ] README: what it is, run, install hook, design notes. Commit.
