"""Render a RunDiff as a git-style ASCII block.

We walk the two call lists in lockstep so the reader can see exactly where
the runs diverge. Each line starts with a status marker:

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
    """Render the diff. Output is plain ASCII so it pipes safely anywhere."""

    # Index granular changes by position for fast lookup.
    changed_by_cpos: dict[int, tuple[str, str]] = {}
    for ch in diff.changed_args:
        changed_by_cpos[ch.position] = (ch.args_hash_before, ch.args_hash_after)
    added_cpos = {a.position for a in diff.added_calls}
    removed_bpos = {r.position for r in diff.removed_calls}
    reordered_by_bpos = {r.baseline_pos: r for r in diff.reordered}
    reordered_by_cpos = {r.candidate_pos: r for r in diff.reordered}

    lines: list[str] = []
    b_i = 0
    c_i = 0
    b_len = len(diff.baseline)
    c_len = len(diff.candidate)

    while b_i < b_len or c_i < c_len:
        # Emit pure removals first if the baseline pointer is on a removed row.
        if b_i < b_len and b_i in removed_bpos and b_i not in reordered_by_bpos:
            bc = diff.baseline[b_i]
            lines.append(f"- {_fmt_call(bc.tool, bc.args_hash, bc.args_preview)}")
            b_i += 1
            continue
        # Emit pure additions if the candidate pointer is on an added row.
        if c_i < c_len and c_i in added_cpos and c_i not in reordered_by_cpos:
            cc = diff.candidate[c_i]
            lines.append(f"+ {_fmt_call(cc.tool, cc.args_hash, cc.args_preview)}")
            c_i += 1
            continue
        # Args change at this paired position.
        if (
            b_i < b_len
            and c_i < c_len
            and c_i in changed_by_cpos
            and diff.baseline[b_i].tool == diff.candidate[c_i].tool
        ):
            bc = diff.baseline[b_i]
            cc = diff.candidate[c_i]
            lines.append(f"~ {_fmt_call(bc.tool, bc.args_hash, bc.args_preview)}  (was)")
            lines.append(f"~ {_fmt_call(cc.tool, cc.args_hash, cc.args_preview)}  (now)")
            b_i += 1
            c_i += 1
            continue
        # Reordered: a row whose signature is the same but moved.
        if b_i < b_len and b_i in reordered_by_bpos:
            r = reordered_by_bpos[b_i]
            lines.append(
                f"^ {r.tool:<24}moved from pos {r.baseline_pos} -> {r.candidate_pos}"
            )
            b_i += 1
            # Skip the matching candidate slot when we get there.
            continue
        if c_i < c_len and c_i in reordered_by_cpos and not (
            b_i < b_len and b_i in reordered_by_bpos
        ):
            # The baseline side already emitted the move marker; just advance.
            c_i += 1
            continue
        # Equal row.
        if b_i < b_len and c_i < c_len:
            cc = diff.candidate[c_i]
            lines.append(f"= {_fmt_call(cc.tool, cc.args_hash, cc.args_preview)}")
            b_i += 1
            c_i += 1
            continue
        # Tail flush.
        if b_i < b_len:
            bc = diff.baseline[b_i]
            lines.append(f"- {_fmt_call(bc.tool, bc.args_hash, bc.args_preview)}")
            b_i += 1
            continue
        if c_i < c_len:
            cc = diff.candidate[c_i]
            lines.append(f"+ {_fmt_call(cc.tool, cc.args_hash, cc.args_preview)}")
            c_i += 1
            continue

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
