import json
import subprocess

import pytest

from dashboard.discovery import DiscoveryError, list_sessions

ROW = {"pid": 1, "cwd": "/p", "kind": "interactive", "startedAt": 1792348086180,
       "sessionId": "s1", "name": "proj-0a", "status": "busy"}


def runner(stdout="", exc=None, code=0):
    def run(*args, **kwargs):
        if exc:
            raise exc
        return subprocess.CompletedProcess(args, code, stdout=stdout, stderr="boom")
    return run


def test_parses_sessions():
    [s] = list_sessions(runner(json.dumps([ROW])))
    assert (s.session_id, s.name, s.cwd, s.busy, s.started) == ("s1", "proj-0a", "/p", True, 1792348086.18)


@pytest.mark.parametrize("run", [runner(exc=FileNotFoundError()),
                                 runner(exc=subprocess.TimeoutExpired("claude", 10)),
                                 runner("not json"),
                                 runner("[]", code=1)])
def test_failures_raise_discovery_error(run):
    with pytest.raises(DiscoveryError):
        list_sessions(run)
