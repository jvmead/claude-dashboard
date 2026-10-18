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
whether it has finished. The strip at the top also estimates where you are in the 5-hour usage window.

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

The hook appends each prompt event as one line to `~/.claude/dashboard/events.jsonl`. It doesn't
change how the prompt behaves.

## How it works

Nearly everything comes from files Claude Code already writes. Only one hook is needed.

```
claude agents --json ──────────────┐  live sessions: busy / idle
~/.claude/projects/*/<sid>.jsonl ──┤  last action, context size, activity times
  <sid>/subagents/*.meta.json ─────┤  subagent tree (parentAgentId, spawnDepth, finished)
  <sid>/subagents/*.jsonl ─────────┤  subagent runtime and tokens
~/.claude/dashboard/events.jsonl ──┘  permission prompts (the only hook)
          │
     snapshot.py  →  /api/state  →  static/app.js (polls every 3 s)
```

| Module | Job |
|---|---|
| `status.py` | the five states, as a pure function |
| `transcripts.py` | incremental JSONL reader: after the first read, each refresh parses only the bytes appended since |
| `subagents.py` | builds the tree from `meta.json` files |
| `usage.py` | 5-hour block, weighted tokens, ceiling inferred from past rejections |
| `snapshot.py` | joins the above into one JSON document |
| `server.py` | `http.server`, whitelisted assets, snapshot cached for 2 s |

### The 5-hour estimate is an estimate

No usage limit is stored locally. Each past `five_hour` rejection gives one sample of the limit: the
weighted usage from the window's start up to the rejection. The strip shows current usage against
those samples, and a time-left range at the current burn rate. Usage from claude.ai, the desktop app
or other machines is invisible to it, which is why it is labelled "this machine only". Token weights
(cache reads are cheap, output is dear, Haiku costs less than Opus) are rough ratios from list
prices. They have not been fitted to the samples.

## Known issues (v1)

- 🟥 *needs approval* rarely shows. The hook stamps whole seconds and is compared with a
  nanosecond transcript mtime, so a prompt usually looks older than the transcript write it caused.
- One vanished file or malformed record fails the whole snapshot, and the page then says "server
  unreachable".
- Stale `meta.json` files with no `finished` key can keep a resumed session at 🟦.
- The burn rate isn't always shown in the strip.

## Develop

```bash
python -m pytest        # 52 tests, no network
ruff check dashboard tests
```

Design notes: `docs/superpowers/specs/2026-10-18-session-dashboard-revised-design.md`.
Plan: `docs/superpowers/plans/2026-10-18-session-dashboard-v1.md`.
