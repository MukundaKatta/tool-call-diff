"""Read a JSONL agent audit log and return normalized tool-call records.

We deliberately only surface rows that look like tool calls. Session-open,
session-close, denied, and budget rows are ignored for the diff because
they do not represent work the agent actually completed. The user can still
see them via trace-tree if they want the full picture.

Recognized shapes (same family as trace-tree):

* agenttrace: kind, tool, latency_ms, cost_usd, parent_span_id, session_id
* agentleash: ts, session_id, kind, tool, args_hash, usd, error
* agentsnap: a single object with a steps list
* agent-step-log: per-step rows with step instead of kind
* generic: anything with a tool field and an OK-ish kind
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_KIND_KEYS = ("kind", "event", "type", "step", "name")
_TOOL_KEYS = ("tool", "tool_name", "function")
_USD_KEYS = ("usd", "cost_usd", "cost", "price_usd")
_LATENCY_KEYS = ("latency_ms", "duration_ms", "elapsed_ms", "ms")
_SESSION_KEYS = ("session_id", "run_id", "trace_id", "session")
_ARGS_KEYS = ("args", "arguments", "input", "params")

# Kinds we treat as "the agent actually ran this tool." Anything else
# (denied, budget_denied, egress_denied, session_open, parse_error) is
# skipped at extract time.
_OK_KINDS = {"tool_ok", "tool", "tool_call", "call", "step", "ok"}


@dataclass
class ToolCall:
    """One completed tool call. The diff operates on a list of these."""

    tool: str
    args_hash: str
    position: int
    session_id: str | None = None
    usd: float = 0.0
    latency_ms: float | None = None
    args_preview: str | None = None  # short string for rendering
    raw: dict[str, Any] = field(default_factory=dict)


def _first(d: dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return str(v)


def _hash_args(args: Any) -> str:
    """Stable short hash of an args payload. Sorted JSON keys for determinism."""
    if args is None:
        return "none"
    try:
        canonical = json.dumps(args, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        canonical = repr(args)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


def _args_preview(args: Any) -> str | None:
    """A short readable snippet of args for the rendered diff."""
    if args is None:
        return None
    try:
        s = json.dumps(args, default=str, separators=(",", "="))
    except (TypeError, ValueError):
        s = str(args)
    if len(s) > 60:
        return s[:57] + "..."
    return s


def _looks_like_tool_call(record: dict[str, Any]) -> bool:
    kind = _to_str(_first(record, _KIND_KEYS)) or ""
    tool = _to_str(_first(record, _TOOL_KEYS))
    if not tool:
        return False
    if kind.lower() in _OK_KINDS:
        return True
    # Some logs do not carry a kind at all but do carry a tool. Treat as OK.
    if not kind:
        return True
    return False


def _explode_agentsnap(record: dict[str, Any]) -> list[dict[str, Any]]:
    """A single agentsnap doc with a steps list becomes one record per step."""
    out: list[dict[str, Any]] = []
    session = _to_str(_first(record, _SESSION_KEYS)) or _to_str(record.get("name"))
    steps = record.get("steps")
    if not isinstance(steps, list):
        return out
    for s in steps:
        if not isinstance(s, dict):
            continue
        merged = dict(s)
        if session and not _first(merged, _SESSION_KEYS):
            merged["session_id"] = session
        out.append(merged)
    return out


def _extract_one(record: dict[str, Any], position: int) -> ToolCall | None:
    if not _looks_like_tool_call(record):
        return None
    tool = _to_str(_first(record, _TOOL_KEYS))
    if not tool:
        return None
    # args_hash, if pre-computed, wins. Otherwise derive from args body.
    args_hash = _to_str(record.get("args_hash"))
    args_val: Any = None
    for k in _ARGS_KEYS:
        if k in record and record[k] is not None:
            args_val = record[k]
            break
    if not args_hash:
        args_hash = _hash_args(args_val)
    usd = _to_float(_first(record, _USD_KEYS)) or 0.0
    latency = _to_float(_first(record, _LATENCY_KEYS))
    if latency is None and isinstance(record.get("extra"), dict):
        latency = _to_float(_first(record["extra"], _LATENCY_KEYS))
    return ToolCall(
        tool=tool,
        args_hash=args_hash,
        position=position,
        session_id=_to_str(_first(record, _SESSION_KEYS)),
        usd=usd,
        latency_ms=latency,
        args_preview=_args_preview(args_val),
        raw=record,
    )


def parse_lines(
    lines: Iterable[str], session_key: str | None = "session_id"
) -> list[ToolCall]:
    """Parse a JSONL stream into tool calls.

    If session_key is provided and the log has multiple sessions, only the
    first session encountered is returned. This keeps run-to-run diffs honest.
    Pass session_key=None to keep all rows in order.
    """
    raw_records: list[dict[str, Any]] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("steps"), list):
            raw_records.extend(_explode_agentsnap(obj))
        elif isinstance(obj, dict):
            raw_records.append(obj)

    if session_key:
        # Pick the first session id seen and filter to it.
        chosen: str | None = None
        for r in raw_records:
            sid = _to_str(r.get(session_key)) or _to_str(_first(r, _SESSION_KEYS))
            if sid:
                chosen = sid
                break
        if chosen is not None:
            filtered: list[dict[str, Any]] = []
            for r in raw_records:
                sid = _to_str(r.get(session_key)) or _to_str(_first(r, _SESSION_KEYS))
                if sid == chosen or sid is None:
                    filtered.append(r)
            raw_records = filtered

    calls: list[ToolCall] = []
    pos = 0
    for r in raw_records:
        c = _extract_one(r, pos)
        if c is not None:
            calls.append(c)
            pos += 1
    return calls


def parse_file(
    path: str | Path, session_key: str | None = "session_id"
) -> list[ToolCall]:
    """Read a .jsonl file and return tool calls in order."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        return parse_lines(fh, session_key=session_key)
