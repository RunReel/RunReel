from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema  # type: ignore[import-untyped]  # ships no type stubs
from hypothesis import given, settings
from strategies import state_sequences

from runreel.trace import State, Trace, dumps, encode

ROOT = Path(__file__).parent.parent
SCHEMA: dict[str, Any] = json.loads(
    (ROOT / "schema" / "trace-v1.schema.json").read_text(encoding="utf-8")
)
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def test_schema_is_valid_json_schema() -> None:
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_sample_trace_matches_schema() -> None:
    VALIDATOR.validate(json.loads((ROOT / "tests/fixtures/sample-trace.json").read_text()))


@settings(max_examples=100)
@given(state_sequences())
def test_encoded_traces_match_schema(states: list[State]) -> None:
    trace: Trace = {
        "schema": 1,
        "language": "python",
        "source": {"file": "x.py", "text": "", "entry": "f()"},
        "steps": encode(states, key_every=3),
    }
    VALIDATOR.validate(json.loads(dumps(trace)))
