# Claude Code Session Dashboard — Design

**Status:** Tabled 2026-07-06 (design approved, implementation not started). Resume from here.

## Goal
Local web dashboard to monitor and manage Claude Code sessions on this WSL2 machine.

## Environment facts (verified 2026-07-06)
- Sessions stored at `~/.claude/projects/<cwd-with-/-as-->/<session-uuid>.jsonl`.
- Token/context usage: last `assistant` line's `message.usage` → `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` ≈ context occupancy. Compare vs model window (e.g. 200k).
- Last activity: transcript file mtime and/or last line `timestamp`.
- Resume CLI: `claude -r <session-id>` (resume specific), `-c` (continue most recent), `-n <name>` (display name), `--fork-session`.
- Live processes present as bare `claude` in the process table. `lsof` does NOT keep the `.jsonl` open, so map `/proc/<pid>/cwd` → project dir → newest `.jsonl` in that dir. Memory via `VmRSS` in `/proc/<pid>/status`.
- WSL2. `tmux` and `screen` installed. `wt.exe` reachable. User normally runs sessions in the VS Code integrated terminal (bare processes).

## Key decisions
- **Session model:** dashboard OWNS new/resumed sessions via named tmux sessions (reliable liveness/attach on WSL). It also MONITORS external (VS Code) sessions read-only — it can show status but cannot attach to a bare process. Hybrid by nature.
- **Launch target:** new detached tmux session; user attaches separately (`tmux attach -t <name>`).
- **Priority:** monitoring-first; launch/resume functional but minimal.
- **Approach A** chosen: poll + parse, tmux-owned launches. (B: websocket/inotify — deferred. C: hooks as event source — deferred.)

## Stack
FastAPI + uvicorn serving static `index.html` + vanilla JS. No build step. `localhost:8765`. Polling every 2–3 s.

## Backend modules (one job each)
| File | Responsibility |
|---|---|
| `config.py` | Paths, poll interval, model context sizes |
| `models.py` | `Session` pydantic model + `Status` enum |
| `transcript.py` | Parse one `.jsonl`: cwd, name/title, last `usage`→tokens, last-activity ts |
| `processes.py` | Scan `/proc` for live `claude` procs; RSS memory; `cwd`→project dir |
| `tmux.py` | List/create/resume tmux sessions; `capture-pane` for prompt detection |
| `registry.py` | JSON binding tmux-session ↔ claude-session-id ↔ dir (for launches) |
| `discovery.py` | Merge transcripts + processes + tmux → unified `Session` list |
| `status.py` | Derive `running / idle / waiting-for-input / stopped` |
| `app.py` | FastAPI routes + static mount |

## Status derivation
- `stopped` = no live process.
- tmux-owned: `tmux capture-pane` — empty prompt box ⇒ `waiting-for-input`, active spinner/tool output ⇒ `running`, recent-but-idle ⇒ `idle`.
- external (VS Code): coarser heuristic (live proc + transcript mtime + last line role). Precision difference is expected and acceptable.

## API
- `GET /api/sessions` — unified list (dir, status, tokens, memory, last activity).
- `POST /api/sessions/launch` `{directory, name?}` — create detached tmux session running `claude` in dir.
- `POST /api/sessions/{id}/resume` — resume dead session in new tmux session (`claude -r <id>`).
- Launch/resume return the `tmux attach -t <name>` command; UI offers one-click-copy. "Live" badge for anything already running.

## Scope
- **v1:** session list (dir, status, tokens, memory, last activity), 2–3 s polling auto-refresh, launch-new-in-tmux form (dir + optional name), resume-dead-in-tmux, copy-attach-command UX.
- **v2 (deferred):** websocket/inotify push, in-browser terminal attach (ttyd/xterm.js), focusing external VS Code terminals, per-session cost graphs, hook-based status.
- **Out of scope:** managing non-Claude processes; auth/multi-user; remote access.

## Testing
pytest — `transcript.py` and `status.py` are pure functions, easy to cover. Target 80%+ on those.

## Open follow-ups when resumed
- New-session UUID isn't known at launch time; bind lazily via newest `.jsonl` in the project dir after start, store in `registry.py`.
- Ambiguity when 2+ sessions share one cwd for external procs (newest-mtime heuristic only).
