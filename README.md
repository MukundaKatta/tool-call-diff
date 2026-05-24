# tool-call-diff

Diff two agent runs from JSONL audit logs. See exactly what your prompt change moved: tool order, cost, step count, or args.

Zero runtime dependencies. Python 3.10+. Stdlib only.

## Why

You changed your agent's system prompt. Or you swapped the model. Or you renamed a tool. Did the agent's behavior actually improve, or did it just rearrange the same six tool calls?

[`trace-tree`](https://github.com/MukundaKatta/trace-tree) shows you what happened in one run. `tool-call-diff` shows you what changed between two.

## Install

```bash
pip install tool-call-diff
```

## Quick start

```python
from tool_call_diff import diff_runs

diff = diff_runs(
    baseline="runs/baseline.jsonl",
    candidate="runs/new_prompt.jsonl",
)

print(diff.tool_sequence_match)  # bool
print(diff.cost_delta_usd)       # candidate - baseline
print(diff.steps_delta)          # int
print(diff.latency_delta_ms)     # int or None

print(diff.render())
```

Or from the CLI:

```bash
tool-call-diff runs/baseline.jsonl runs/candidate.jsonl
```

Sample output:

```
= search_web              {"q":"claude release"}
~ search_web              {"q":"claude release"}  (was)
~ search_web              {"q":"claude 4 release date"}  (now)
= fetch_url               {"url":"https://anthropic.com/news"}
- summarize               {"input_tokens":1850}
= final_answer            {"len":280}

cost: 0.0410 -> 0.0028 USD (-0.0382)
steps: 4 -> 3 (-1)
latency: 1820 -> 708 ms (-1112)
tool sequence: changed
```

The summary tells you the prompt change cut cost by 93%, removed one step, and saved over a second. The body shows exactly what changed.

## What it reads

Same JSONL shapes as [`trace-tree`](https://github.com/MukundaKatta/trace-tree):

- `agenttrace`: `kind`, `tool`, `latency_ms`, `cost_usd`, `parent_span_id`, `session_id`
- `agentleash`: `ts`, `session_id`, `kind`, `tool`, `args_hash`, `usd`, `error`
- `agentsnap`: single doc with a `steps` list
- `agent-step-log`: per-step rows with `step` instead of `kind`
- generic: anything with a tool field and an OK-ish kind

If your log has multiple sessions in one file, the parser keeps the first session by default. Pass `session_key=None` to disable that.

## Diff buckets

```python
diff.added_calls    # [{tool, args_hash, position}, ...] candidate-only
diff.removed_calls  # [{tool, args_hash, position}, ...] baseline-only
diff.changed_args   # [{tool, position, args_hash_before, args_hash_after}, ...]
diff.reordered      # [{tool, args_hash, baseline_pos, candidate_pos}, ...]
```

The algorithm runs `difflib.SequenceMatcher` over a normalized signature per call: `(tool_name, args_hash)`. Same-tool / different-args at the same position becomes `changed_args`. Same signature at a different position becomes `reordered`.

## CI gate

```bash
tool-call-diff baseline.jsonl candidate.jsonl --exit-on-change
```

Exits non-zero when anything moved. Useful as a prompt-regression gate next to [`agentsnap`](https://github.com/MukundaKatta/AgentSnap).

## Where it fits

- [`agenttrace`](https://github.com/MukundaKatta/agenttrace) and [`agentleash`](https://github.com/MukundaKatta/agentleash) write the JSONL logs.
- [`trace-tree`](https://github.com/MukundaKatta/trace-tree) renders a single run as a tree.
- [`agentsnap`](https://github.com/MukundaKatta/AgentSnap) snapshots a single run for regression testing.
- `tool-call-diff` compares two runs to show what your change did.

## License

MIT.
