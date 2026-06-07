"""Tests for the ASCII renderer."""

from __future__ import annotations

from tool_call_diff.diff import diff_runs
from tool_call_diff.parse import ToolCall


def _c(
    tool: str,
    args_hash: str,
    position: int,
    usd: float = 0.0,
    preview: str | None = None,
):
    return ToolCall(
        tool=tool,
        args_hash=args_hash,
        position=position,
        usd=usd,
        args_preview=preview,
    )


def test_identical_renders_only_equals_and_summary():
    a = [_c("x", "h", 0, usd=0.01, preview="{q=hi}")]
    b = [_c("x", "h", 0, usd=0.01, preview="{q=hi}")]
    out = diff_runs(a, b).render()
    body = out.splitlines()
    # Every call line is = ...
    assert body[0].startswith("= ")
    # Summary present.
    assert any(line.startswith("cost: ") for line in body)
    assert any(line.startswith("steps: ") for line in body)
    assert any("tool sequence: identical" in line for line in body)


def test_added_line_uses_plus_marker():
    a = [_c("x", "h", 0)]
    b = [_c("x", "h", 0), _c("y", "h2", 1)]
    out = diff_runs(a, b).render()
    assert any(line.startswith("+ ") and "y" in line for line in out.splitlines())


def test_removed_line_uses_minus_marker():
    a = [_c("x", "h", 0), _c("y", "h2", 1)]
    b = [_c("x", "h", 0)]
    out = diff_runs(a, b).render()
    assert any(line.startswith("- ") and "y" in line for line in out.splitlines())


def test_changed_args_uses_tilde_marker_with_was_and_now():
    a = [_c("search", "h-old", 0, preview="{q=old}")]
    b = [_c("search", "h-new", 0, preview="{q=new}")]
    out = diff_runs(a, b).render()
    lines = out.splitlines()
    assert any(line.startswith("~ ") and "(was)" in line for line in lines)
    assert any(line.startswith("~ ") and "(now)" in line for line in lines)


def test_no_summary_skips_footer():
    a = [_c("x", "h", 0)]
    b = [_c("x", "h", 0)]
    out = diff_runs(a, b).render(show_summary=False)
    assert "cost:" not in out
    assert "steps:" not in out


def test_summary_reports_signed_deltas():
    a = [_c("x", "h", 0, usd=0.10)]
    b = [_c("x", "h", 0, usd=0.07)]
    out = diff_runs(a, b).render()
    assert "(-0.0300)" in out or "(-0.0300" in out


def test_changed_args_was_line_shows_baseline_preview():
    # The (was) line must show the OLD args preview, not the new one or a hash.
    a = [_c("search", "h-old", 0, preview="{q=old}")]
    b = [_c("search", "h-new", 0, preview="{q=new}")]
    body = diff_runs(a, b).render(show_summary=False).splitlines()
    was_line = next(line for line in body if line.startswith("~ ") and "(was)" in line)
    now_line = next(line for line in body if line.startswith("~ ") and "(now)" in line)
    assert "{q=old}" in was_line
    assert "{q=new}" in now_line


def test_reorder_marker_lands_at_candidate_position():
    # baseline [x, a] -> candidate [a, x]: 'a' moved to the front, so the move
    # marker must be the FIRST body line, in candidate order.
    a = [_c("x", "hx", 0, preview="X"), _c("a", "ha", 1, preview="A")]
    b = [_c("a", "ha", 0, preview="A"), _c("x", "hx", 1, preview="X")]
    body = [
        line
        for line in diff_runs(a, b).render(show_summary=False).splitlines()
        if line.strip()
    ]
    assert body[0].startswith("^ ") and "a" in body[0]
    assert body[1].startswith("= ") and "x" in body[1]


def test_removed_row_is_anchored_in_the_middle():
    # baseline [a, b, c] -> candidate [a, c]: the removed 'b' should sit between
    # 'a' and 'c', not get dumped at the end.
    a = [
        _c("a", "h1", 0, preview="A"),
        _c("b", "h2", 1, preview="B"),
        _c("c", "h3", 2, preview="C"),
    ]
    b = [_c("a", "h1", 0, preview="A"), _c("c", "h3", 1, preview="C")]
    body = [
        line
        for line in diff_runs(a, b).render(show_summary=False).splitlines()
        if line.strip()
    ]
    assert body[0].startswith("= ") and "a" in body[0]
    assert body[1].startswith("- ") and "b" in body[1]
    assert body[2].startswith("= ") and "c" in body[2]


def test_every_candidate_call_appears_exactly_once():
    # A messy mix of reorder + insert + delete must still render each candidate
    # row once and only once (no lost or duplicated rows).
    a = [_c("a", "h1", 0, preview="A"), _c("b", "h2", 1, preview="B")]
    b = [
        _c("b", "h2", 0, preview="B"),
        _c("new", "hN", 1, preview="N"),
        _c("a", "h1", 2, preview="A"),
    ]
    body = [
        line
        for line in diff_runs(a, b).render(show_summary=False).splitlines()
        if line.strip()
    ]
    markers = sorted(line[0] for line in body)
    # Exactly: one '^' (b moved), one '+' (new), one '=' (a). No '-' (nothing
    # was deleted; a just moved).
    assert markers == ["+", "=", "^"]
