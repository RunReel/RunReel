from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from test_schema import VALIDATOR

from runreel.trace import dumps
from runreel.trace.tracer import record

ROOT = Path(__file__).parent.parent
GOLDEN = Path(__file__).parent / "fixtures" / "golden"
EXAMPLES = {
    "binary_search": "binary_search([1, 3, 4, 7, 9, 11, 15], 9)",
    "bst_insert": "build([5, 3, 8, 1, 4])",
    "dijkstra": "dijkstra(G, 0)",
}


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_matches_its_golden_trace(name: str) -> None:
    trace = record(ROOT / "examples" / f"{name}.py", EXAMPLES[name])
    VALIDATOR.validate(json.loads(dumps(trace)))
    expected = json.dumps(trace, indent=1, ensure_ascii=False) + "\n"
    golden = GOLDEN / f"{name}.json"
    if os.environ.get("RUNREEL_UPDATE_GOLDEN"):
        golden.parent.mkdir(exist_ok=True)
        golden.write_text(expected, encoding="utf-8")
    assert golden.read_text(encoding="utf-8") == expected
