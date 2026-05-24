"""diff_runs behavior across the common change patterns."""

from __future__ import annotations

from tool_call_diff.diff import diff_runs
from tool_call_diff.parse import ToolCall


def _c(tool: str, args_hash: str, position: int, usd: float = 0.0, latency: float | None = None):
    return ToolCall(
        tool=tool,
        args_hash=args_hash,
        position=position,
        usd=usd,
        latency_ms=latency,
    )


def test_identical_runs_are_empty():
    a = [_c("search", "h1", 0, usd=0.01), _c("answer", "h2", 1, usd=0.0)]
    b = [_c("search", "h1", 0, usd=0.01), _c("answer", "h2", 1, usd=0.0)]
    diff = diff_runs(a, b)
    assert diff.tool_sequence_match is True
    assert diff.added_calls == []
    assert diff.removed_calls == []
    assert diff.changed_args == []
    assert diff.reordered == []
    assert diff.steps_delta == 0
    assert diff.cost_delta_usd == 0.0
    assert diff.is_empty()


def test_added_tool_lands_in_added_calls():
    a = [_c("search", "h1", 0), _c("answer", "h2", 1)]
    b = [_c("search", "h1", 0), _c("verify", "h3", 1), _c("answer", "h2", 2)]
    diff = diff_runs(a, b)
    assert len(diff.added_calls) == 1
    assert diff.added_calls[0].tool == "verify"
    assert diff.added_calls[0].position == 1
    assert diff.removed_calls == []
    assert diff.steps_delta == 1
    assert diff.tool_sequence_match is False


def test_removed_tool_lands_in_removed_calls():
    a = [_c("search", "h1", 0), _c("summarize", "h2", 1), _c("answer", "h3", 2)]
    b = [_c("search", "h1", 0), _c("answer", "h3", 1)]
    diff = diff_runs(a, b)
    assert len(diff.removed_calls) == 1
    assert diff.removed_calls[0].tool == "summarize"
    assert diff.removed_calls[0].position == 1
    assert diff.added_calls == []
    assert diff.steps_delta == -1


def test_same_tool_different_args_lands_in_changed_args():
    a = [_c("search", "h-old", 0)]
    b = [_c("search", "h-new", 0)]
    diff = diff_runs(a, b)
    assert len(diff.changed_args) == 1
    ch = diff.changed_args[0]
    assert ch.tool == "search"
    assert ch.args_hash_before == "h-old"
    assert ch.args_hash_after == "h-new"
    assert diff.added_calls == []
    assert diff.removed_calls == []


def test_reorder_is_detected():
    a = [_c("a", "h1", 0), _c("b", "h2", 1), _c("c", "h3", 2)]
    b = [_c("b", "h2", 0), _c("a", "h1", 1), _c("c", "h3", 2)]
    diff = diff_runs(a, b)
    assert len(diff.reordered) >= 1
    moved_tools = {r.tool for r in diff.reordered}
    assert "a" in moved_tools or "b" in moved_tools
    # The reordered rows should NOT also be in added/removed.
    for r in diff.reordered:
        for ac in diff.added_calls:
            assert not (ac.tool == r.tool and ac.args_hash == r.args_hash)
        for rc in diff.removed_calls:
            assert not (rc.tool == r.tool and rc.args_hash == r.args_hash)


def test_cost_delta_signs_correctly():
    a = [_c("x", "h", 0, usd=0.10)]
    b = [_c("x", "h", 0, usd=0.07)]
    diff = diff_runs(a, b)
    assert diff.cost_delta_usd == -0.03


def test_steps_delta_signs_correctly():
    a = [_c("x", "h", 0), _c("y", "h2", 1)]
    b = [_c("x", "h", 0)]
    diff = diff_runs(a, b)
    assert diff.steps_delta == -1


def test_latency_delta_when_both_have_latency():
    a = [_c("x", "h", 0, latency=100), _c("y", "h2", 1, latency=50)]
    b = [_c("x", "h", 0, latency=80), _c("y", "h2", 1, latency=40)]
    diff = diff_runs(a, b)
    assert diff.latency_delta_ms == -30


def test_latency_delta_none_when_missing():
    a = [_c("x", "h", 0)]
    b = [_c("x", "h", 0)]
    diff = diff_runs(a, b)
    assert diff.latency_delta_ms is None


def test_diff_from_jsonl_files(tmp_path):
    import json

    base = tmp_path / "baseline.jsonl"
    cand = tmp_path / "candidate.jsonl"
    base.write_text(
        "\n".join(
            [
                json.dumps({"kind": "tool_ok", "tool": "search", "args": {"q": "a"}, "session_id": "s1", "usd": 0.01}),
                json.dumps({"kind": "tool_ok", "tool": "answer", "args": {"len": 100}, "session_id": "s1", "usd": 0.0}),
            ]
        )
    )
    cand.write_text(
        "\n".join(
            [
                json.dumps({"kind": "tool_ok", "tool": "search", "args": {"q": "a"}, "session_id": "s1", "usd": 0.01}),
                json.dumps({"kind": "tool_ok", "tool": "verify", "args": {"k": 1}, "session_id": "s1", "usd": 0.002}),
                json.dumps({"kind": "tool_ok", "tool": "answer", "args": {"len": 100}, "session_id": "s1", "usd": 0.0}),
            ]
        )
    )
    diff = diff_runs(str(base), str(cand))
    assert diff.steps_delta == 1
    assert any(a.tool == "verify" for a in diff.added_calls)
