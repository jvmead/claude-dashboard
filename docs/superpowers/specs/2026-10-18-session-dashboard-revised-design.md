# Claude Session Dashboard — Revised Design (draft)

**Status:** DRAFT, builder-check done 2026-10-18, awaiting James's approval. Supersedes the discovery/status
parts of `2026-07-06-claude-session-dashboard-design.md` (env facts there still useful).
Before approval: finish the open questions below, then run the brainstorming builder-check, then `writing-plans`.

## Intent
An always-open side window (browser) to glance at while coding elsewhere. Its #1 job: **show which
session needs James's input right now, and why**, so a quick green-light costs seconds, not a context
switch. Explicitly **no notifications**. Glance on demand only.

Second job: show what each session's subagents are doing, how deep, who is waiting on whom, and later
whether tracks are independent or coupled (see v2/v3). This ties to the batch-and-join rule
(`~/.claude/scripts/hooks/agent-batch-guard.js`, rationale in conversation `eed7de0c`, 2026-09-10).

## What changed since July
| July spec | Now | Why |
|---|---|---|
| `/proc` scan + tmux + registry for discovery | **`claude agents --json`** (pid, cwd, sessionId, name, `idle`/`busy`) | Native since Agent View (May 2026, v2.1.139+; installed 2.1.302). Solves same-cwd ambiguity. |
| tmux `capture-pane` status heuristics | **4-state model from hooks** (below) | `idle` alone can't tell "waiting on subagents" from "waiting on me". |
| Launch/resume sessions | **Dropped** | Agent View (`claude agents`) already dispatches/peeks/replies. |
| (assumed Agent View covers glancing) | **Agent View only shows *background* agents** | Tested 2026-10-18: interactive `claude agents` lists only sessions dispatched from it; normal terminal sessions appear only in `--json`, as bare `busy`/`idle`, with launch cwd (not current) and no subagents. So: reuse `--json` for discovery; the 4 states + subagent tree are ours. |
| — | Subagent tree + timeline, 5h estimate | New requirements. |

## Status model (core idea; 4 active states + parked)
| State | Meaning | Detection (checked against hooks docs 2026-10-18) |
|---|---|---|
| 🟥 needs approval | permission prompt pending | `Notification` hook, matcher `permission_prompt` (or `PermissionRequest` event), writes a state file; cleared by next `PostToolUse`/`Stop`. No popup |
| 🟨 your turn | asked a question / finished, waiting on James | `idle` and 0 outstanding subagents, idle ≤ 30 min |
| ⬜ parked | idle and untouched | as 🟨 but idle > 30 min; sorts last |
| 🟦 waiting n/m | blocked on its own subagents | `idle` and outstanding > 0 (batch-guard already counts per session) |
| 🟩 working | busy | `busy` from `claude agents --json` |

## Layout (chosen 2026-10-18; mockups in `docs/mockups/`)
- **Minimised = strip (E):** one coloured pill per session + 5h estimate. Usable as a header bar.
- **Expanded = strip on top + dense list (A):** one row per session (state, current action/question, context %, age), sorted 🟥🟨 first.
- **Click a row → inline swim-lane timeline (D)** for that session: parent lane (working vs waiting), one lane per subagent indented by depth, specialist/general label, scope, ✓/● status; footer with max depth, specialist/general counts, tokens across agents. Multiple rows can be open; each toggles.
- Guesses not yet confirmed: timeline covers ~last 20 min; expanded rows persist across refresh and close when the session ends.

## Glance content James asked for
Sessions open + what they're doing + context status · per-session background work, subagents, scope,
how many waiting on others · depth/structure, specialist vs general · per-session usage rate, 5h-window
position, projected time left.

## Scope
- **v1:** strip + list + expandable timeline; 4-state status; subagent tree (depth, type, runtime, tokens); 5h estimate.
- **v2:** rework `agent-batch-guard` → **scope-aware**: spawns declare write scopes; block only on overlap; read-only agents never wait; per-track joins/reviews instead of a global barrier (supersedes config-HANDOFF next action 3, "gate on write-capable only"). Dashboard shows independent vs coupled tracks; timeline as wave view.
- **v3:** drift detection: record actual writes per agent (post-write hook) vs declared scope; on overlap, block new spawns in the overlap and raise "tracks A+B converged on `foo/` → run as waves together, OK?" **at the next join point**.
- **Out:** notifications; pausing/re-syncing running agents mid-flight (not feasible); exact % of rate limit (no ceiling on disk).

## Known constraints / risks
- **5h limit:** no ceiling stored locally; `quotaLimits` only appears at rejection (5 events on record). Plan: estimate ceiling from usage in the 5h before each rejection (weight cache reads down), show **estimate ± error band**, label it as such.
- **Subagent attribution:** ✅ per hooks docs, tool events fired inside a subagent carry `agent_id` + `agent_type`. **No parent id**: nesting must be inferred (the `Agent` tool call that spawns a child carries the *spawner's* `agent_id`). Confirm with a throwaway logging hook before building the tree.
- "How near completion" is only honest for agents spawned from a numbered plan; otherwise show runtime, not %.
- `lib/transcript.js` zero-usage blind spot (config-HANDOFF) affects context readings for rate-limited sessions.

## Prior art (2026-10-18 search)
- Native Agent View `claude agents` (attention grouping, no subagent tree / 5h).
- disler/claude-code-hooks-multi-agent-observability (hooks → Bun → SQLite → Vue/WebSocket).
- simple10/agents-observe (plugin; parent/subagent hierarchy, per-model tokens).
- zpankz agent-observability (hooks → JSONL files, no DB; swim lanes). Closest fit to existing hooks.
- Claude-Code-Usage-Monitor, claumon (80% CI projection), ccusage `blocks`. Reuse their 5h approach.
- None do declared scopes / coupled tracks / waves. That's the novel part.

## Decisions (2026-10-18)
- **Purpose:** personal + portfolio → tests, README, clean design.
- **Stack:** stdlib + JSONL: hooks append JSONL; Python stdlib `http.server` serves; vanilla JS polls. No new deps.
- **Location:** moved to `/home/jvmead/projects/claude-dashboard`.

## Builder-check answers (James, 2026-10-18)
- **Parked state:** a 🟨 session idle > 30 min turns ⬜ *parked*, sorts below active sessions, and
  reverts on any new event. No manual dismiss.
- **Nesting fallback:** if the logging hook shows the spawner can't be inferred reliably, v1 shows a
  flat subagent list ("depth unknown", no max-depth footer). Tree rebuild from subagent transcripts → v2.
- **5h estimate:** usage outside Claude Code on this machine (claude.ai, desktop, other devices) is
  invisible; the strip labels the estimate "this machine only". No correction attempted.
- **Raw log is the source of truth:** hooks store payloads verbatim and never filter fields, and the
  JSONL is kept (rotated, not truncated), so a later full subagent tree is a new *reader* over existing
  logs, not a hook change. Hooks only need revisiting if the tree needs an event we don't subscribe to;
  the logging spike should therefore subscribe to every subagent-related event (`SubagentStart`,
  `SubagentStop`, `Pre/PostToolUse` on `Agent`) from day one.

## Builder-check calls (Claude's, 2026-10-18; James to check)
- **Hooks live in this repo**, not `~/.claude/scripts`. Each hook is a one-line shell append of the raw
  payload to a JSONL file (`cat >> …`); all parsing happens in the Python server. No Python/Node start-up
  per tool event. `install.py` adds/removes the entries in `settings.json` (done via a `~/.claude`
  worktree + feat branch per self-config rules).
- **🟦 count comes from our own event log**, not the batch-guard's `/tmp/claude-agent-batch-<sid>.json`
  (that file resets lazily, updates only on spawn/stop, and changes format in v2).
- **No "scope" column in v1.** Real scopes are v2. v1 labels each subagent with its spawn `description`
  (from the `Agent` tool input); mockup's scope column is a v2 preview.
- **Per-session usage** in v1 = tokens over the last hour in the timeline footer. The strip keeps one
  global 5h figure.
- **Sessions started before the hooks are installed** show plain busy/idle from `claude agents --json`,
  marked "no hook data". No transcript heuristic.

## Open questions (resolved, kept for history)
1. **Purpose:** personal tool only, or also a portfolio piece for DS/quant-dev applications? (Sets stack and test bar.)
2. Stack: July chose FastAPI + vanilla JS + 2–3 s polling. Keep, or go stdlib/JSONL-watching per ponytail?
3. **Location:** repo is on `/mnt/c`, but it's a Linux-toolchain project → per Machine Layout should move to
   `/home/jvmead/projects/claude-dashboard` (remap memory slug). Only 1 commit, so cheap to move.
4. ~~Try `claude agents` first.~~ Done 2026-10-18, see "What changed" table.
