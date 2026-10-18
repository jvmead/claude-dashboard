from dashboard.subagents import is_specialist, load_subagents, max_depth, outstanding
from tests.conftest import assistant

U = {"input_tokens": 10, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 1000,
     "output_tokens": 20}


def meta(desc, parent=None, finished=True, depth=1, kind="general-purpose"):
    m = {"agentType": kind, "description": desc, "toolUseId": "t", "spawnDepth": depth,
         "requestShape": "foreground", "finished": finished}
    if parent:
        m["parentAgentId"] = parent
    return m


def tree(claude_dir):
    p = claude_dir.add_session("s1", [])
    claude_dir.add_subagent("s1", "a", meta("outer"), [
        assistant("2026-10-18T10:00:00Z", usage=U, msg_id="x1"),
        assistant("2026-10-18T10:00:00Z", usage=U, msg_id="x1"),  # same message, streamed twice
        assistant("2026-10-18T10:02:00Z", usage=U, msg_id="x2")])
    claude_dir.add_subagent("s1", "b", meta("inner", parent="a", finished=False, depth=2,
                                            kind="python-pro"))
    claude_dir.add_subagent("s1", "c", meta("side", finished=False))
    return load_subagents(p)


def test_nesting_via_parent_agent_id(claude_dir):
    roots = tree(claude_dir)
    assert sorted(n.agent_id for n in roots) == ["a", "c"]
    outer = next(n for n in roots if n.agent_id == "a")
    assert [c.agent_id for c in outer.children] == ["b"]
    assert outer.children[0].depth == 2 and outer.children[0].parent_id == "a"


def test_runtime_and_tokens_from_transcript(claude_dir):
    outer = next(n for n in tree(claude_dir) if n.agent_id == "a")
    assert outer.last_activity - outer.started == 120
    assert outer.tokens == 2 * 35  # deduped on message id, cache reads excluded


def test_missing_transcript_tolerated(claude_dir):
    side = next(n for n in tree(claude_dir) if n.agent_id == "c")
    assert side.tokens == 0 and side.started > 0


def test_outstanding_counts_only_unfinished(claude_dir):
    assert outstanding(tree(claude_dir)) == 2


def test_max_depth(claude_dir):
    assert max_depth(tree(claude_dir)) == 2
    assert max_depth([]) == 0


def test_specialist():
    assert is_specialist("python-pro")
    assert not is_specialist("general-purpose")
