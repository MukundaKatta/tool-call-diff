"""Compute a structured diff between two lists of normalized tool calls.

The diff is computed with stdlib difflib.SequenceMatcher on a signature
sequence of (tool_name, args_hash). That gives us classic edit blocks:
equal, replace, insert, delete. We map those into four buckets:

* added_calls   -- present in candidate, absent in baseline
* removed_calls -- present in baseline, absent in candidate
* changed_args  -- same tool at corresponding position, different args_hash
* reordered     -- same (tool, args_hash) signature appears in both runs
                   but at different positions

Aggregate metrics (cost, step count, latency) are computed independently
from the raw call lists, not from the diff. That keeps the headline
numbers honest even when the per-position diff is noisy.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .parse import ToolCall, parse_file


@dataclass
class ChangedArg:
    tool: str
    position: int
    args_hash_before: str
    args_hash_after: str


@dataclass
class Reorder:
    tool: str
    args_hash: str
    baseline_pos: int
    candidate_pos: int


@dataclass
class AddedCall:
    tool: str
    args_hash: str
    position: int  # position in the candidate run


@dataclass
class RemovedCall:
    tool: str
    args_hash: str
    position: int  # position in the baseline run


@dataclass
class RunDiff:
    baseline: list[ToolCall]
    candidate: list[ToolCall]

    # Top-line booleans and deltas
    tool_sequence_match: bool = True
    cost_delta_usd: float = 0.0
    steps_delta: int = 0
    latency_delta_ms: int | None = None

    # Granular changes
    added_calls: list[AddedCall] = field(default_factory=list)
    removed_calls: list[RemovedCall] = field(default_factory=list)
    changed_args: list[ChangedArg] = field(default_factory=list)
    reordered: list[Reorder] = field(default_factory=list)

    # Internal: maps a paired candidate position (equal or changed-args row) to
    # its corresponding baseline position. Used by the renderer to anchor
    # deletions and recover the baseline arg preview. Not part of the public API.
    _cpos_to_bpos: dict[int, int] = field(default_factory=dict, repr=False)

    def render(self, **kwargs: Any) -> str:
        # Delayed import so render is optional / swappable.
        from .render import render_diff

        return render_diff(self, **kwargs)

    def is_empty(self) -> bool:
        """True when nothing about the candidate moved versus the baseline."""
        return (
            self.tool_sequence_match
            and not self.added_calls
            and not self.removed_calls
            and not self.changed_args
            and not self.reordered
            and self.cost_delta_usd == 0.0
            and self.steps_delta == 0
        )


def _signature(c: ToolCall) -> tuple[str, str]:
    return (c.tool, c.args_hash)


def _sum_cost(calls: list[ToolCall]) -> float:
    return sum(c.usd for c in calls)


def _sum_latency(calls: list[ToolCall]) -> int | None:
    """Return total latency in ms, or None if no calls have latency."""
    pieces = [c.latency_ms for c in calls if c.latency_ms is not None]
    if not pieces:
        return None
    return int(sum(pieces))


def _classify(baseline: list[ToolCall], candidate: list[ToolCall]) -> RunDiff:
    b_sigs = [_signature(c) for c in baseline]
    c_sigs = [_signature(c) for c in candidate]

    diff = RunDiff(baseline=baseline, candidate=candidate)
    matcher = difflib.SequenceMatcher(a=b_sigs, b=c_sigs, autojunk=False)
    opcodes = matcher.get_opcodes()

    # Walk opcodes. For replace blocks of equal length, classify per-pair as
    # changed_args if the tool names match, else add+remove.
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for off in range(i2 - i1):
                diff._cpos_to_bpos[j1 + off] = i1 + off
            continue
        if tag == "insert":
            for j in range(j1, j2):
                cc = candidate[j]
                diff.added_calls.append(
                    AddedCall(tool=cc.tool, args_hash=cc.args_hash, position=j)
                )
            continue
        if tag == "delete":
            for i in range(i1, i2):
                bc = baseline[i]
                diff.removed_calls.append(
                    RemovedCall(tool=bc.tool, args_hash=bc.args_hash, position=i)
                )
            continue
        # tag == "replace"
        b_chunk = baseline[i1:i2]
        c_chunk = candidate[j1:j2]
        common = min(len(b_chunk), len(c_chunk))
        for k in range(common):
            bc = b_chunk[k]
            cc = c_chunk[k]
            if bc.tool == cc.tool and bc.args_hash != cc.args_hash:
                diff.changed_args.append(
                    ChangedArg(
                        tool=bc.tool,
                        position=j1 + k,
                        args_hash_before=bc.args_hash,
                        args_hash_after=cc.args_hash,
                    )
                )
                diff._cpos_to_bpos[j1 + k] = i1 + k
            else:
                diff.removed_calls.append(
                    RemovedCall(tool=bc.tool, args_hash=bc.args_hash, position=i1 + k)
                )
                diff.added_calls.append(
                    AddedCall(tool=cc.tool, args_hash=cc.args_hash, position=j1 + k)
                )
        # Extras on the longer side become pure inserts or deletes.
        if len(c_chunk) > common:
            for k in range(common, len(c_chunk)):
                cc = c_chunk[k]
                diff.added_calls.append(
                    AddedCall(tool=cc.tool, args_hash=cc.args_hash, position=j1 + k)
                )
        if len(b_chunk) > common:
            for k in range(common, len(b_chunk)):
                bc = b_chunk[k]
                diff.removed_calls.append(
                    RemovedCall(tool=bc.tool, args_hash=bc.args_hash, position=i1 + k)
                )

    # Reordered: any signature that appears in BOTH runs but with different
    # positions, and is not already explained by add/remove. We compute this
    # by checking for sigs that appear in added_calls AND removed_calls with
    # the same (tool, args_hash). Those are the "shuffled" rows.
    removed_by_sig: dict[tuple[str, str], list[int]] = {}
    for r in diff.removed_calls:
        removed_by_sig.setdefault((r.tool, r.args_hash), []).append(r.position)
    added_by_sig: dict[tuple[str, str], list[int]] = {}
    for a in diff.added_calls:
        added_by_sig.setdefault((a.tool, a.args_hash), []).append(a.position)

    reordered: list[Reorder] = []
    consumed_removed: set[tuple[tuple[str, str], int]] = set()
    consumed_added: set[tuple[tuple[str, str], int]] = set()
    for sig, removed_positions in removed_by_sig.items():
        added_positions = added_by_sig.get(sig, [])
        pairs = min(len(removed_positions), len(added_positions))
        for k in range(pairs):
            bpos = removed_positions[k]
            cpos = added_positions[k]
            reordered.append(
                Reorder(
                    tool=sig[0], args_hash=sig[1], baseline_pos=bpos, candidate_pos=cpos
                )
            )
            consumed_removed.add((sig, bpos))
            consumed_added.add((sig, cpos))

    # Strip the reordered pairs out of added/removed so each row is in
    # exactly one bucket.
    if reordered:
        diff.reordered = reordered
        diff.removed_calls = [
            r
            for r in diff.removed_calls
            if ((r.tool, r.args_hash), r.position) not in consumed_removed
        ]
        diff.added_calls = [
            a
            for a in diff.added_calls
            if ((a.tool, a.args_hash), a.position) not in consumed_added
        ]

    diff.tool_sequence_match = b_sigs == c_sigs
    diff.cost_delta_usd = round(_sum_cost(candidate) - _sum_cost(baseline), 6)
    diff.steps_delta = len(candidate) - len(baseline)

    b_lat = _sum_latency(baseline)
    c_lat = _sum_latency(candidate)
    if b_lat is not None and c_lat is not None:
        diff.latency_delta_ms = c_lat - b_lat
    else:
        diff.latency_delta_ms = None

    return diff


def diff_runs(
    baseline: str | Path | list[ToolCall],
    candidate: str | Path | list[ToolCall],
    session_key: str | None = "session_id",
) -> RunDiff:
    """Compare two runs.

    baseline and candidate can be either a path to a JSONL file or a
    pre-built list of ToolCall objects (useful for tests).
    """
    if isinstance(baseline, (str, Path)):
        b_calls = parse_file(baseline, session_key=session_key)
    else:
        b_calls = list(baseline)
    if isinstance(candidate, (str, Path)):
        c_calls = parse_file(candidate, session_key=session_key)
    else:
        c_calls = list(candidate)
    return _classify(b_calls, c_calls)
