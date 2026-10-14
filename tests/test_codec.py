from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from strategies import state_sequences

from runreel.trace import State, Trace, Value, dumps, encode, iter_states, state_at
from runreel.trace.codec import MAX_EDITS, _myers

FIXTURES = Path(__file__).parent / "fixtures"


def canonical(data: object) -> str:
    """JSON text that tells 1, 1.0 and True apart, for exact comparisons."""
    return json.dumps(data, sort_keys=True)


def load_states(name: str) -> list[State]:
    states: list[State] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    for state in states:
        state["heap"] = {int(oid): obj for oid, obj in state["heap"].items()}
    return states


def list_state(items: list[Any]) -> State:
    return {
        "ev": "line",
        "line": 3,
        "stack": [{"fid": 1, "fn": "f", "line": 3, "locals": {"a": {"ref": 1}}}],
        "heap": {1: {"t": "seq", "cls": "list", "items": items}},
    }


def json_size(data: object) -> int:
    """Bytes of data as compact JSON, the way dumps writes a trace."""
    return len(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode())


def fewest_edits(a: list[int], b: list[int]) -> int:
    """Removals plus insertions that turn a into b, from the textbook longest common subsequence."""
    lcs = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            lcs[i + 1][j + 1] = lcs[i][j] + 1 if x == y else max(lcs[i][j + 1], lcs[i + 1][j])
    return len(a) + len(b) - 2 * lcs[-1][-1]


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


@given(state_sequences())
def test_patches_are_shorter_than_the_objects_they_stand_for(states: list[State]) -> None:
    for state, step in zip(states, encode(states, key_every=len(states)), strict=True):
        for oid, entry in step.get("heap", {}).items():
            if "t" not in entry:
                assert json_size(entry) < json_size(state["heap"][int(oid)])


N = list(range(100))


@pytest.mark.parametrize(
    ("after", "ops"),
    [
        pytest.param([*N[:10], 20, *N[11:20], 10, *N[21:]], [[10, 20], [20, 10]], id="swap"),
        pytest.param([*N[:5], 6, 5, *N[7:]], [[5, 2, [6, 5]]], id="adjacent-swap"),
        pytest.param([*N[1:], 100], [[0, 1, []], [100, 0, [100]]], id="queue"),
        pytest.param([*N[:50], -1, *N[50:]], [[50, 0, [-1]]], id="insert"),
        pytest.param([*N[:50], *N[51:]], [[50, 1, []]], id="remove"),
        pytest.param([*N, *range(100, 130)], [[100, 0, list(range(100, 130))]], id="extend"),
    ],
)
def test_a_list_change_sends_only_what_changed(after: list[int], ops: list[list[Any]]) -> None:
    delta = encode([list_state(N), list_state(after)])[1]
    assert delta == {"ev": "line", "line": 3, "heap": {"1": {"ops": ops}}}


def test_an_instance_sends_only_the_fields_that_changed() -> None:
    def node(**fields: Value) -> State:
        obj: Any = {"t": "obj", "cls": "Node", "fields": fields}
        return {"ev": "line", "line": 7, "stack": [], "heap": {1: obj}}

    delta = encode([node(val=5, left=None, right=None), node(val=5, left={"ref": 2})])[1]
    patch = {"set": {"left": {"ref": 2}}, "del": ["right"]}
    assert delta == {"ev": "line", "line": 7, "heap": {"1": patch}}


def test_a_queue_costs_under_100_bytes_per_step() -> None:
    # A BFS queue pops the front and pushes the back. Position patches cost 562 bytes a step.
    items, states = N, []
    for n in range(1000):
        items = [*items[1:], 100 + n]
        states.append(list_state(items))
    assert json_size(encode(states)) / len(states) < 100


@given(st.lists(st.integers(0, 3), max_size=12), st.lists(st.integers(0, 3), max_size=12))
def test_myers_finds_the_fewest_edits(a: list[int], b: list[int]) -> None:
    runs, least = _myers(a, b), fewest_edits(a, b)
    if least > MAX_EDITS:
        assert runs is None
    else:
        assert runs is not None
        assert sum(x1 - x0 + y1 - y0 for x0, x1, y0, y1 in runs) == least
        rebuilt = list(a)
        for x0, x1, y0, y1 in reversed(runs):
            rebuilt[x0:x1] = b[y0:y1]
        assert rebuilt == b


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
