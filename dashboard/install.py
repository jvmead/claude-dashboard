"""Add/remove the permission-prompt hook in a Claude Code settings.json.

python -m dashboard.install [--uninstall] [--settings ~/.claude/settings.json]
"""
import argparse
import json
import os
from pathlib import Path

# Raw payload, newlines stripped (JSON strings can't hold literal ones, so this is lossless),
# wrapped with a receive time, appended in a single write so concurrent sessions don't interleave.
HOOK_CMD = ("mkdir -p ~/.claude/dashboard && p=$(tr -d '\\n') && "
            "printf '{\"ts\":%s,\"e\":%s}\\n' \"$(date +%s)\" \"$p\" >> ~/.claude/dashboard/events.jsonl")
EVENTS = {"Notification": "permission_prompt", "PermissionRequest": "*"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)  # atomic: a crash never leaves half a settings file


def _ours(entry: dict) -> bool:
    return any(h.get("command") == HOOK_CMD for h in entry.get("hooks", []))


def is_installed(path: Path) -> bool:
    try:
        hooks = _load(path).get("hooks", {})
    except (OSError, ValueError):
        return False
    return any(_ours(e) for event in EVENTS for e in hooks.get(event, []))


def install(path: Path) -> None:
    data = _load(path)
    hooks = data.setdefault("hooks", {})
    for event, matcher in EVENTS.items():
        entries = hooks.setdefault(event, [])
        if not any(_ours(e) for e in entries):
            entries.append({"matcher": matcher, "hooks": [{"type": "command", "command": HOOK_CMD}]})
    _save(path, data)


def uninstall(path: Path) -> None:
    data = _load(path)
    hooks = data.get("hooks", {})
    for event in EVENTS:
        kept = [e for e in hooks.get(event, []) if not _ours(e)]
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    _save(path, data)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--uninstall", action="store_true")
    p.add_argument("--settings", type=Path, default=Path.home() / ".claude" / "settings.json")
    args = p.parse_args()
    (uninstall if args.uninstall else install)(args.settings)
    print(f"{'Removed' if args.uninstall else 'Installed'} dashboard hook in {args.settings}")


if __name__ == "__main__":
    main()
