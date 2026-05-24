"""tool-call-diff: compare two agent runs from JSONL audit logs.

Quick use::

    from tool_call_diff import diff_runs

    diff = diff_runs("runs/baseline.jsonl", "runs/new_prompt.jsonl")
    print(diff.render())

Programmatic::

    diff.tool_sequence_match  # bool
    diff.cost_delta_usd       # float (candidate - baseline)
    diff.steps_delta          # int
    diff.latency_delta_ms     # int or None
    diff.added_calls
    diff.removed_calls
    diff.changed_args
    diff.reordered
"""

from __future__ import annotations

from .diff import (
    AddedCall,
    ChangedArg,
    Reorder,
    RemovedCall,
    RunDiff,
    diff_runs,
)
from .parse import ToolCall, parse_file, parse_lines
from .render import render_diff

__all__ = [
    "AddedCall",
    "ChangedArg",
    "Reorder",
    "RemovedCall",
    "RunDiff",
    "ToolCall",
    "diff_runs",
    "parse_file",
    "parse_lines",
    "render_diff",
    "__version__",
]

__version__ = "0.1.0"
