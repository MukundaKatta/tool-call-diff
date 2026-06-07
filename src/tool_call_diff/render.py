"""Render a RunDiff as a git-style ASCII block.

We walk the candidate run in order so the reader sees what the new run looks
like, interleaving removed (baseline-only) rows where they used to sit. Each
line starts with a status marker:

  =   identical at this position
  -   removed (was in baseline, not in candidate)
  +   added (only in candidate)
  ~   args changed (same tool, different args)
  ^   same call moved to a different position
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .diff import RunDiff


def _fmt_call(tool: str, args_hash: str, args_preview: str | None) -> str:
    body = args_preview if args_preview else f"hash={args_hash}"
    return f"{tool:<24}{body}"


def render_diff(diff: "RunDiff", show_summary: bool = True) -> str:
    """Render the diff. Output is plain ASCII so it pipes safely anywhere.

    The body is rendered in candidate order, since the reader cares about what
    the new run looks like. Removed rows (baseline-only) are flushed in baseline
    order at the point their preceding baseline neighbour was last emitted, so a
    deletion still shows up roughly where it used to be. Each call appears on
    exactly one body line.
    """

    # Index granular changes by candidate position for fast lookup.
    changed_by_cpos: dict[int, tuple[str, str]] = {}
    for ch in diff.changed_args:
        changed_by_cpos[ch.position] = (ch.args_hash_before, ch.args_hash_after)
    added_cpos = {a.position for a in diff.added_calls}
    reordered_by_cpos = {r.candidate_pos: r for r in diff.reordered}

    # Removed rows grouped by the baseline position they sit at, so we can flush
    # them in baseline order interleaved with the candidate walk.
    removed_by_bpos = {r.position: r for r in diff.removed_calls}
    removed_positions = sorted(removed_by_bpos)
    removed_idx = 0

    lines: list[str] = []
    b_len = len(diff.baseline)
    c_len = len(diff.candidate)

    def _flush_removed_up_to(bpos_limit: int) -> None:
        """Emit any pending removed rows with baseline position < bpos_limit."""
        nonlocal removed_idx
        while (
            removed_idx < len(removed_positions)
            and removed_positions[removed_idx] < bpos_limit
        ):
            bc = diff.baseline[removed_positions[removed_idx]]
            lines.append(f"- {_fmt_call(bc.tool, bc.args_hash, bc.args_preview)}")
            removed_idx += 1

    cpos_to_bpos = diff._cpos_to_bpos

    for c_i in range(c_len):
        cc = diff.candidate[c_i]
        # Reordered: this candidate slot holds a call that moved here. Flush any
        # removed rows that came before its baseline origin first.
        if c_i in reordered_by_cpos:
            r = reordered_by_cpos[c_i]
            _flush_removed_up_to(r.baseline_pos)
            lines.append(
                f"^ {r.tool:<24}moved from pos {r.baseline_pos} -> {r.candidate_pos}"
            )
            continue
        # Pure addition: candidate-only call.
        if c_i in added_cpos:
            lines.append(f"+ {_fmt_call(cc.tool, cc.args_hash, cc.args_preview)}")
            continue
        # Args change at this paired position (same tool, different args).
        if c_i in changed_by_cpos:
            before_hash, _after_hash = changed_by_cpos[c_i]
            bpos = cpos_to_bpos.get(c_i)
            if bpos is not None:
                _flush_removed_up_to(bpos)
                before_preview = diff.baseline[bpos].args_preview
            else:
                before_preview = None
            lines.append(f"~ {_fmt_call(cc.tool, before_hash, before_preview)}  (was)")
            lines.append(
                f"~ {_fmt_call(cc.tool, cc.args_hash, cc.args_preview)}  (now)"
            )
            continue
        # Equal row: flush removals that belong before this baseline slot, then
        # emit the unchanged call.
        bpos = cpos_to_bpos.get(c_i, c_i)
        _flush_removed_up_to(bpos)
        lines.append(f"= {_fmt_call(cc.tool, cc.args_hash, cc.args_preview)}")

    # Flush any remaining removed rows (deletions at the tail of the baseline).
    _flush_removed_up_to(b_len + 1)

    if show_summary:
        lines.append("")
        b_cost = sum(c.usd for c in diff.baseline)
        c_cost = sum(c.usd for c in diff.candidate)
        cost_arrow = f"{b_cost:.4f} -> {c_cost:.4f} USD ({diff.cost_delta_usd:+.4f})"
        lines.append(f"cost: {cost_arrow}")
        lines.append(
            f"steps: {len(diff.baseline)} -> {len(diff.candidate)} ({diff.steps_delta:+d})"
        )
        if diff.latency_delta_ms is not None:
            b_lat = sum(c.latency_ms or 0 for c in diff.baseline)
            c_lat = sum(c.latency_ms or 0 for c in diff.candidate)
            lines.append(
                f"latency: {int(b_lat)} -> {int(c_lat)} ms ({diff.latency_delta_ms:+d})"
            )
        if diff.tool_sequence_match:
            lines.append("tool sequence: identical")
        else:
            lines.append("tool sequence: changed")

    return "\n".join(lines)
