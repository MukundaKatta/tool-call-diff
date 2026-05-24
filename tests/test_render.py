"""Tests for the ASCII renderer."""

from __future__ import annotations

from tool_call_diff.diff import diff_runs
from tool_call_diff.parse import ToolCall


def _c(tool: str, args_hash: str, position: int, usd: float = 0.0, preview: str | None = None):
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
