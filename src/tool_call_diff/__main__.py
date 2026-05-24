"""CLI: tool-call-diff baseline.jsonl candidate.jsonl"""

from __future__ import annotations

import argparse
import sys

from .diff import diff_runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tool-call-diff",
        description=(
            "Diff two agent runs from JSONL audit logs. Shows tool sequence, "
            "cost, step count, and arg changes between a baseline and a candidate."
        ),
    )
    parser.add_argument("baseline", help="Path to baseline JSONL log.")
    parser.add_argument("candidate", help="Path to candidate JSONL log.")
    parser.add_argument(
        "--session-key",
        default="session_id",
        help="Field name that identifies a session/run. Pass empty string to disable filtering.",
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Skip the cost/steps/latency summary footer.",
    )
    parser.add_argument(
        "--exit-on-change",
        action="store_true",
        help="Exit non-zero when the diff is not empty. Useful in CI gates.",
    )
    args = parser.parse_args(argv)

    session_key = args.session_key or None
    diff = diff_runs(args.baseline, args.candidate, session_key=session_key)
    sys.stdout.write(diff.render(show_summary=not args.no_summary))
    sys.stdout.write("\n")

    if args.exit_on_change and not diff.is_empty():
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
