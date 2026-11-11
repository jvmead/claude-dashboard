# Claude Session Dashboard

A small local web page that answers one question at a glance: **which Claude Code session needs me
right now, and why?** Keep it open in a side window while you work elsewhere. It never notifies;
you look when you want to.

| State | Meaning |
|---|---|
| 🟥 needs approval | a permission prompt is waiting |
| 🟨 your turn | idle and nothing running: it asked something or finished |
| 🟦 waiting n/m | idle, but its own subagents are still running |
| 🟩 working | busy |
| ⬜ parked | idle for more than 30 minutes |

Click a session to open its timeline for the last 20 minutes: when the parent was active, one lane
per subagent, indented by spawn depth, with type, specialist or general, description, runtime and
whether it has finished. The strip at the top also shows where you are in the 5-hour and weekly usage
windows. It uses the real numbers from `~/.claude/dashboard/usage.json` when a status line script
writes them there, from the `rate_limits` field Claude Code passes it, and falls back to an estimate
from local transcripts otherwise.

## Run

```bash
python -m dashboard            # http://127.0.0.1:8765
python -m dashboard --port 9000
```

Python 3.11+, standard library only. It listens on localhost only.

`--open` also opens a browser tab. If the port is already taken it assumes the dashboard is running
and only opens the tab, so it is safe to call repeatedly. To start it with VS Code (WSL remote), put
this in `~/.vscode-server/server-env-setup`, which the VS Code server sources when it starts:

```bash
(cd ~/projects/claude-dashboard && setsid python -m dashboard --open \
    >/tmp/claude-dashboard.log 2>&1 < /dev/null &)
```

Use the absolute path to your Python if `python` isn't on the server's `PATH`.

To detect permission prompts (🟥), install the hook once:

```bash
python -m dashboard.install               # adds it to ~/.claude/settings.json
python -m dashboard.install --uninstall
```

The hook appends one line per event to `~/.claude/dashboard/events.jsonl`: each permission prompt,
plus the `PostToolUse`, `Stop`, `SubagentStop` and `UserPromptSubmit` events that answer it. A
session shows 🟥 while its last logged event is a prompt. The hook doesn't change how the prompt
behaves.

## How it works

Nearly everything comes from files Claude Code already writes. Only one hook is needed.

```
claude agents --json ──────────────┐  live sessions: busy / idle
~/.claude/projects/*/<sid>.jsonl ──┤  last action, context size, activity times
  <sid>/subagents/*.meta.json ─────┤  subagent tree (parentAgentId, spawnDepth, finished)
  <sid>/subagents/*.jsonl ─────────┤  subagent runtime and tokens
~/.claude/dashboard/events.jsonl ──┘  permission prompts and what answered them (the only hook)
          │
     snapshot.py  →  /api/state  →  static/app.js (polls every 3 s)
```

| Module | Job |
|---|---|
| `status.py` | the five states, as a pure function |
| `transcripts.py` | incremental JSONL reader: after the first read, each refresh parses only the bytes appended since |
| `subagents.py` | builds the tree from `meta.json` files |
| `usage.py` | 5-hour block, weighted tokens, ceiling inferred from past rejections, weekly pace threshold |
| `snapshot.py` | joins the above into one JSON document |
| `server.py` | `http.server`, whitelisted assets, snapshot cached for 2 s |

### The 5-hour estimate is an estimate

No usage limit is stored locally. Each past `five_hour` rejection gives one sample of the limit: the
weighted usage from the window's start up to the rejection. The strip shows current usage against
those samples, and a time-left range at the current burn rate. Usage from claude.ai, the desktop app
or other machines is invisible to it, which is why it is labelled "this machine only". Token weights
(cache reads are cheap, output is dear, Haiku costs less than Opus) are rough ratios from list
prices. They have not been fitted to the samples.

### Weekly pace colours

When the real numbers are available, the weekly figure is coloured by how far ahead of an even
spend you are. The window is the 7 days before `resets_at`, so the scheme follows whenever your
own week resets. The budget is split evenly over the Monday to Friday days in that window, 20% each.
The figure turns yellow halfway through today's share, orange 5 points above that and red 8 above.
Days off hold the last working day's threshold. Hover over the figure to see today's values.

| Reset | Day 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| Tuesday | 10 | 30 | 50 | 70 | 70 | 70 | 90 |
| Monday | 10 | 30 | 50 | 70 | 90 | 90 | 90 |

A day here is a 24-hour block counted from the reset, labelled by the weekday it starts on, so a
reset in the middle of the day puts Friday evening and Saturday morning in the same block. The pace
is fixed. It does not re-plan from what you have already used. The working days are the `WORKDAYS`
constant in `usage.py`.

### Peak hours

The strip starts with `peak · ends 2h56` (orange) or `off-peak · peak in 5h`. Peak is Anthropic's
weekday window of 05:00 to 11:00 US Pacific, announced in March 2026, when 5-hour limits drain faster.
Weekly limits are not affected. The window is `PEAK_HOURS_PT` in `usage.py`. US daylight saving is
coded by hand because Windows Python has no timezone database without `tzdata`, so the window
moves correctly in UTC and in local time. Anthropic may change or drop the rule; check before
trusting the flag.

## Known issues (v1)

- Dismissing a permission prompt with Esc leaves 🟥 until you send the next message, because Claude
  Code fires no `Stop` hook on an interrupt.
- With parallel tool calls in one turn, a sibling call finishing can clear 🟥 while a prompt is still open.
- A session with no transcript never shows as parked.
- The hook log is re-read in full on every poll.
- The server doesn't check the `Host` header, so DNS rebinding isn't blocked. It binds to localhost only.
- Durations under a minute show as "now".

## Develop

```bash
python -m pytest        # 56 tests, no network
ruff check dashboard tests
```

Design notes: `docs/superpowers/specs/2026-10-18-session-dashboard-revised-design.md`.
Plan: `docs/superpowers/plans/2026-10-18-session-dashboard-v1.md`.
