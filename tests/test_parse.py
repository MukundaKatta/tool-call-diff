"""Parser tests across the four supported JSONL shapes."""

from __future__ import annotations

import json

from tool_call_diff.parse import parse_lines


def _jsonl(records: list[dict]) -> list[str]:
    return [json.dumps(r) for r in records]


def test_agenttrace_shape():
    lines = _jsonl([
        {"kind": "session_open", "session_id": "s1", "ts": 1.0},
        {
            "kind": "tool_ok",
            "tool": "search",
            "args": {"q": "claude"},
            "cost_usd": 0.001,
            "latency_ms": 120,
            "parent_span_id": "p1",
            "session_id": "s1",
        },
        {
            "kind": "tool_ok",
            "tool": "fetch",
            "args": {"url": "https://example.com"},
            "cost_usd": 0.0005,
            "latency_ms": 80,
            "session_id": "s1",
        },
    ])
    calls = parse_lines(lines)
    assert [c.tool for c in calls] == ["search", "fetch"]
    assert calls[0].usd == 0.001
    assert calls[0].latency_ms == 120
    assert calls[0].position == 0
    assert calls[1].position == 1


def test_agentleash_shape():
    lines = _jsonl([
        {
            "ts": 1.0,
            "session_id": "abc12",
            "kind": "tool_ok",
            "tool": "locus.payments.charge",
            "args_hash": "aeff9a9e",
            "usd": 4.99,
            "error": None,
            "extra": {"latency_ms": 12},
        },
        {
            "ts": 1.1,
            "session_id": "abc12",
            "kind": "tool_denied",  # NOT counted as a tool call.
            "tool": "locus.payments.charge",
            "args_hash": "84f50ae9",
            "usd": 0.0,
            "error": "args invalid",
        },
    ])
    calls = parse_lines(lines)
    assert len(calls) == 1
    assert calls[0].tool == "locus.payments.charge"
    assert calls[0].args_hash == "aeff9a9e"
    assert calls[0].usd == 4.99
    assert calls[0].latency_ms == 12


def test_agentsnap_shape():
    lines = _jsonl([
        {
            "name": "snap-1",
            "session_id": "snap-1",
            "steps": [
                {"kind": "tool_ok", "tool": "search", "args": {"q": "x"}, "usd": 0.01},
                {"kind": "tool_ok", "tool": "answer", "args": {"len": 42}, "usd": 0.0},
            ],
        }
    ])
    calls = parse_lines(lines)
    assert [c.tool for c in calls] == ["search", "answer"]
    assert calls[0].session_id == "snap-1"


def test_agent_step_log_shape():
    lines = _jsonl([
        {"step": "tool_ok", "tool": "ping", "args": {"host": "a"}, "session_id": "r1"},
        {"step": "tool_ok", "tool": "ping", "args": {"host": "b"}, "session_id": "r1"},
    ])
    calls = parse_lines(lines)
    assert [c.tool for c in calls] == ["ping", "ping"]
    assert calls[0].args_hash != calls[1].args_hash


def test_session_filter_picks_first_session():
    lines = _jsonl([
        {"kind": "tool_ok", "tool": "a", "session_id": "s1", "args": {"x": 1}},
        {"kind": "tool_ok", "tool": "b", "session_id": "s2", "args": {"x": 2}},
        {"kind": "tool_ok", "tool": "c", "session_id": "s1", "args": {"x": 3}},
    ])
    calls = parse_lines(lines, session_key="session_id")
    assert [c.tool for c in calls] == ["a", "c"]


def test_session_filter_disabled():
    lines = _jsonl([
        {"kind": "tool_ok", "tool": "a", "session_id": "s1"},
        {"kind": "tool_ok", "tool": "b", "session_id": "s2"},
    ])
    calls = parse_lines(lines, session_key=None)
    assert [c.tool for c in calls] == ["a", "b"]


def test_blank_and_invalid_lines_are_skipped():
    lines = ["", "not json", json.dumps({"kind": "tool_ok", "tool": "x"})]
    calls = parse_lines(lines)
    assert len(calls) == 1


def test_hash_is_stable_across_key_order():
    a = [json.dumps({"kind": "tool_ok", "tool": "t", "args": {"x": 1, "y": 2}})]
    b = [json.dumps({"kind": "tool_ok", "tool": "t", "args": {"y": 2, "x": 1}})]
    assert parse_lines(a)[0].args_hash == parse_lines(b)[0].args_hash


def test_denied_calls_are_dropped():
    lines = _jsonl([
        {"kind": "tool_ok", "tool": "a"},
        {"kind": "budget_denied", "tool": "a"},
        {"kind": "egress_denied", "tool": None, "url": "x"},
    ])
    calls = parse_lines(lines)
    assert len(calls) == 1
