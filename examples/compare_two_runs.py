"""Compare two real agent runs and print the diff.

Scenario: a research agent answered a question once with a vague prompt
(baseline), then again after the prompt was tightened to ask for a date
specifically (candidate). Did the change help?

Run::

    python examples/compare_two_runs.py
"""

from __future__ import annotations

import pathlib

from tool_call_diff import diff_runs


def main() -> None:
    root = pathlib.Path(__file__).parent
    diff = diff_runs(
        baseline=str(root / "baseline.jsonl"),
        candidate=str(root / "candidate.jsonl"),
    )

    print(diff.render())
    print()
    print(f"tool_sequence_match: {diff.tool_sequence_match}")
    print(f"cost_delta_usd:     {diff.cost_delta_usd:+.4f}")
    print(f"steps_delta:        {diff.steps_delta:+d}")
    if diff.latency_delta_ms is not None:
        print(f"latency_delta_ms:   {diff.latency_delta_ms:+d}")
    print(f"added_calls:        {len(diff.added_calls)}")
    print(f"removed_calls:      {len(diff.removed_calls)}")
    print(f"changed_args:       {len(diff.changed_args)}")
    print(f"reordered:          {len(diff.reordered)}")


if __name__ == "__main__":
    main()
