"""Parse raw JSON traces into the normalized schema.

v0 supports one format (see examples/traces/*.json). Additional adapters
(LangSmith, OTel/openllmetry, OpenAI Responses) plug in here later — each one
is just `raw -> Trace`.
"""
from __future__ import annotations

import json
from pathlib import Path

from .schema import Expectations, Step, Trace


def load_trace(path: str | Path) -> Trace:
    raw = json.loads(Path(path).read_text())
    return parse_generic(raw)


def parse_generic(raw: dict) -> Trace:
    steps = []
    for i, s in enumerate(raw.get("steps", [])):
        steps.append(Step(index=i, **{k: v for k, v in s.items() if k != "index"}))
    exp = raw.get("expectations")
    return Trace(
        trace_id=raw.get("trace_id", "unknown"),
        app=raw.get("app"),
        steps=steps,
        expectations=Expectations(**exp) if exp else None,
        meta=raw.get("meta", {}),
    )
