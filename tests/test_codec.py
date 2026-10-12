from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from strategies import state_sequences

from runreel.trace import State, Trace, dumps, encode, iter_states, state_at

FIXTURES = Path(__file__).parent / "fixtures"


def canonical(data: object) -> str:
    """JSON text that tells 1, 1.0 and True apart, for exact comparisons."""
    return json.dumps(data, sort_keys=True)


def load_states(name: str) -> list[State]:
    states: list[State] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    for state in states:
        state["heap"] = {int(oid): obj for oid, obj in state["heap"].items()}
    return states


def sample_trace() -> Trace:
    return {
        "schema": 1,
        "language": "python",
        "source": {
            "file": "front.py",
            "text": (FIXTURES / "front.py").read_text(encoding="utf-8"),
            "entry": "front([3, -1], [])",
        },
        "steps": encode(load_states("sample-states.json"), key_every=4),
    }


def test_sample_trace_matches_golden_file() -> None:
    expected = json.dumps(sample_trace(), indent=2, ensure_ascii=False) + "\n"
    golden = FIXTURES / "sample-trace.json"
    if os.environ.get("RUNREEL_UPDATE_GOLDEN"):
        golden.write_text(expected, encoding="utf-8")
    assert golden.read_text(encoding="utf-8") == expected


def test_sample_trace_rebuilds_every_state() -> None:
    states = load_states("sample-states.json")
    steps = sample_trace()["steps"]
    assert canonical(list(iter_states(steps))) == canonical(states)
    for n, state in enumerate(states):
        assert canonical(state_at(steps, n)) == canonical(state)


@given(state_sequences(), st.integers(min_value=1, max_value=6))
def test_decoding_returns_exactly_the_encoded_states(states: list[State], key_every: int) -> None:
    steps = encode(states, key_every=key_every)
    assert canonical(list(iter_states(steps))) == canonical(states)
    assert canonical([state_at(steps, n) for n in range(len(steps))]) == canonical(states)


def test_a_swap_costs_two_items_not_the_whole_list() -> None:
    before: State = {
        "ev": "line",
        "line": 3,
        "stack": [{"fid": 1, "fn": "sort", "line": 3, "locals": {"a": {"ref": 1}}}],
        "heap": {1: {"t": "seq", "cls": "list", "items": list(range(100))}},
    }
    after = copy.deepcopy(before)
    after["heap"][1]["items"][10], after["heap"][1]["items"][20] = 20, 10
    delta = encode([before, after])[1]
    assert delta == {"ev": "line", "line": 3, "heap": {"1": {"set": [[10, 20], [20, 10]]}}}


def test_rejects_invalid_input() -> None:
    state: State = {"ev": "line", "line": 1, "stack": [], "heap": {}}
    steps = encode([state, state])
    with pytest.raises(ValueError):
        encode([state], key_every=0)
    with pytest.raises(ValueError):
        list(iter_states(steps[1:]))
    with pytest.raises(ValueError):
        state_at(steps[1:], 0)
    with pytest.raises(IndexError):
        state_at(steps, 2)


def test_dumps_refuses_untagged_infinity() -> None:
    trace = sample_trace()
    trace["result"] = float("inf")
    with pytest.raises(ValueError):
        dumps(trace)
