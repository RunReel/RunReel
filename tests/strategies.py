"""Hypothesis strategies that generate realistic runs: each state is a random edit of the last."""

from __future__ import annotations

import copy

from hypothesis import strategies as st

from runreel.trace import Event, HeapObject, State, Value

EVENTS: list[Event] = ["call", "line", "return", "exception"]
NAMES = ["a", "b", "i", "j", "lo", "hi", "best", "node"]
FIELDS = ["val", "left", "right", "next"]
OPS = [
    "push",
    "pop",
    "set",
    "del",
    "new",
    "replace",
    "item",
    "grow",
    "shrink",
    "more",
    "field",
    "gc",
]

values: st.SearchStrategy[Value] = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53) + 1, max_value=2**53 - 1),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=6),
    st.sampled_from([{"inf": 1}, {"inf": -1}, {"nan": 1}]),
    st.integers(min_value=2**53, max_value=2**70).map(lambda n: {"bigint": str(n)}),
    st.integers(min_value=0, max_value=30).map(lambda i: {"ref": i}),
)


def _seq(cls: str, items: list[Value], more: int) -> HeapObject:
    obj: HeapObject = {"t": "seq", "cls": cls, "items": items}
    if more:
        obj["more"] = more
    return obj


def _map(items: list[list[Value]], more: int) -> HeapObject:
    obj: HeapObject = {"t": "map", "cls": "dict", "items": items}
    if more:
        obj["more"] = more
    return obj


def _obj(fields: dict[str, Value]) -> HeapObject:
    return {"t": "obj", "cls": "Node", "fields": fields}


def _repr(v: str) -> HeapObject:
    return {"t": "repr", "cls": "function", "v": v}


pairs = st.tuples(values, values).map(list)
heap_objects: st.SearchStrategy[HeapObject] = st.one_of(
    st.builds(
        _seq,
        st.sampled_from(["list", "tuple", "deque"]),
        st.lists(values, max_size=6),
        st.integers(0, 3),
    ),
    st.builds(_map, st.lists(pairs, max_size=4), st.integers(0, 2)),
    st.builds(_obj, st.dictionaries(st.sampled_from(FIELDS), values, max_size=3)),
    st.builds(_repr, st.text(max_size=8)),
)


@st.composite
def state_sequences(draw: st.DrawFn) -> list[State]:
    """A run of 1-12 states. Edits push and pop frames, change locals and change objects."""
    state: State = {
        "ev": "call",
        "line": 1,
        "stack": [{"fid": 1, "fn": "f", "line": 1, "locals": {}}],
        "heap": {},
    }
    next_fid, next_oid = 2, 0
    states: list[State] = []
    for _ in range(draw(st.integers(1, 12))):
        for _ in range(draw(st.integers(0, 4))):
            op = draw(st.sampled_from(OPS))
            top = state["stack"][-1]["locals"]
            containers = sorted(k for k, o in state["heap"].items() if o["t"] in ("seq", "map"))
            nodes = sorted(k for k, o in state["heap"].items() if o["t"] == "obj")
            if op == "push":
                fn = draw(st.sampled_from(["f", "g", "h"]))
                state["stack"].append({"fid": next_fid, "fn": fn, "line": 1, "locals": {}})
                next_fid += 1
            elif op == "pop" and len(state["stack"]) > 1:
                state["stack"].pop()
            elif op == "set":
                top[draw(st.sampled_from(NAMES))] = draw(values)
            elif op == "del" and top:
                del top[draw(st.sampled_from(sorted(top)))]
            elif op == "new":
                state["heap"][next_oid] = draw(heap_objects)
                next_oid += 1
            elif op == "replace" and state["heap"]:
                state["heap"][draw(st.sampled_from(sorted(state["heap"])))] = draw(heap_objects)
            elif op == "gc" and state["heap"]:
                del state["heap"][draw(st.sampled_from(sorted(state["heap"])))]
            elif op in ("item", "grow", "shrink", "more") and containers:
                obj = state["heap"][draw(st.sampled_from(containers))]
                items = obj["items"]
                item = draw(values) if obj["t"] == "seq" else draw(pairs)
                if op == "item" and items:
                    items[draw(st.integers(0, len(items) - 1))] = item
                elif op == "grow":  # anywhere, so splices in the middle get tested
                    items.insert(draw(st.integers(0, len(items))), item)
                elif op == "shrink" and items:
                    del items[draw(st.integers(0, len(items) - 1))]
                elif op == "more":
                    more = draw(st.integers(0, 3))
                    if more:
                        obj["more"] = more
                    else:
                        obj.pop("more", None)
            elif op == "field" and nodes:
                fields = state["heap"][draw(st.sampled_from(nodes))]["fields"]
                name = draw(st.sampled_from(FIELDS))
                if name in fields and draw(st.booleans()):
                    del fields[name]
                else:
                    fields[name] = draw(values)
        state["ev"] = draw(st.sampled_from(EVENTS))
        state["line"] = draw(st.integers(1, 40))
        state["stack"][-1]["line"] = state["line"]
        state.pop("ret", None)
        state.pop("exc", None)
        if state["ev"] == "return":
            state["ret"] = draw(values)
        elif state["ev"] == "exception":
            state["exc"] = draw(st.text(max_size=10))
        states.append(copy.deepcopy(state))
    return states
