from __future__ import annotations

import json
import math
from collections import deque, namedtuple
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from runreel.trace.model import HeapObject, Value
from runreel.trace.serialize import MAX_STR, Serializer


def snapshot(*roots: object, **options: int) -> tuple[list[Value], dict[int, HeapObject]]:
    serializer = Serializer(**options)
    values = [serializer.value(root) for root in roots]
    return values, serializer.heap()


def test_scalars_stay_inline_and_special_numbers_are_tagged() -> None:
    values, heap = snapshot(None, True, 7, -2.5, "hi", math.inf, -math.inf, math.nan, 2**60)
    assert values == [
        None,
        True,
        7,
        -2.5,
        "hi",
        {"inf": 1},
        {"inf": -1},
        {"nan": 1},
        {"bigint": str(2**60)},
    ]
    assert heap == {}


def test_long_strings_are_cut() -> None:
    (value,), _ = snapshot("x" * (MAX_STR + 5))
    assert value == "x" * MAX_STR + "…"


def test_containers_become_heap_objects() -> None:
    values, heap = snapshot([1, 2], (3,), {4}, deque([5]), {"k": [6]})
    assert values == [{"ref": 1}, {"ref": 2}, {"ref": 3}, {"ref": 4}, {"ref": 5}]
    assert heap == {
        1: {"t": "seq", "cls": "list", "items": [1, 2]},
        2: {"t": "seq", "cls": "tuple", "items": [3]},
        3: {"t": "seq", "cls": "set", "items": [4]},
        4: {"t": "seq", "cls": "deque", "items": [5]},
        5: {"t": "map", "cls": "dict", "items": [["k", {"ref": 6}]]},
        6: {"t": "seq", "cls": "list", "items": [6]},
    }


def test_shared_objects_and_cycles_get_one_id() -> None:
    inner: list[Any] = []
    outer = [inner, inner]
    outer.append(outer)
    values, heap = snapshot(outer, inner)
    assert values == [{"ref": 1}, {"ref": 2}]
    assert heap == {
        1: {"t": "seq", "cls": "list", "items": [{"ref": 2}, {"ref": 2}, {"ref": 1}]},
        2: {"t": "seq", "cls": "list", "items": []},
    }


def test_instances_namedtuples_and_slots_become_fields() -> None:
    class Node:
        def __init__(self) -> None:
            self.val, self.next = 1, None

    class Slotted:
        __slots__ = ("x", "y")

        def __init__(self) -> None:
            self.x = 2  # y is never set, so it isn't shown

    Point = namedtuple("Point", "x y")
    _, heap = snapshot(Node(), Slotted(), Point(3, 4), len)
    assert heap == {
        1: {"t": "obj", "cls": "Node", "fields": {"val": 1, "next": None}},
        2: {"t": "obj", "cls": "Slotted", "fields": {"x": 2}},
        3: {"t": "obj", "cls": "Point", "fields": {"x": 3, "y": 4}},
        4: {"t": "repr", "cls": "builtin_function_or_method", "v": "<built-in function len>"},
    }


def test_caps_count_what_is_left_out() -> None:
    _, heap = snapshot(list(range(10)), {i: i for i in range(10)}, max_items=3)
    assert heap[1] == {"t": "seq", "cls": "list", "items": [0, 1, 2], "more": 7}
    assert heap[2] == {"t": "map", "cls": "dict", "items": [[0, 0], [1, 1], [2, 2]], "more": 7}
    _, heap = snapshot([[1], [2], [3]], max_objects=2)
    assert heap[3] == {"t": "repr", "cls": "list", "v": "(not shown: over 2 objects)"}


def test_ids_stay_stable_and_unchanged_objects_are_reused() -> None:
    serializer = Serializer()
    a, b = [1, 2], {"x": 1}
    serializer.value(a), serializer.value(b)
    first = serializer.heap()
    serializer.value(b), serializer.value(a)  # a different order must not change the ids
    second = serializer.heap()
    assert second[1] is first[1] and second[2] is first[2]
    a.append(3)
    b["x"] = 2
    serializer.value(a), serializer.value(b)
    third = serializer.heap()
    assert third[1] == {"t": "seq", "cls": "list", "items": [1, 2, 3]}
    assert third[2] == {"t": "map", "cls": "dict", "items": [["x", 2]]}
    assert serializer.value(a) is serializer.value(a)  # one {"ref": id} object per id


def test_an_unchanged_object_still_keeps_what_it_refers_to() -> None:
    serializer = Serializer()
    outer = [[1]]
    serializer.value(outer)
    serializer.heap()
    serializer.value(outer)
    assert set(serializer.heap()) == {1, 2}


def test_a_field_renamed_with_the_same_value_is_not_mistaken_for_unchanged() -> None:
    class Box:
        pass

    box = Box()
    box.a = 1  # type: ignore[attr-defined]
    serializer = Serializer()
    serializer.value(box)
    serializer.heap()
    del box.a  # type: ignore[attr-defined]
    box.b = 1  # type: ignore[attr-defined]
    serializer.value(box)
    assert serializer.heap()[1] == {"t": "obj", "cls": "Box", "fields": {"b": 1}}


def test_a_step_where_nothing_changed_gets_the_same_heap_back() -> None:
    serializer = Serializer()
    rows = [{"n": i} for i in range(3)]
    serializer.value(rows)
    first = serializer.heap()
    serializer.value(rows[1])  # reached another way too, as by a loop variable
    serializer.value(rows)
    assert serializer.heap() is first
    rows[2]["n"] = -1
    serializer.value(rows)
    changed = serializer.heap()
    assert changed is not first and changed[1] is first[1] and changed[4] is not first[4]


def test_values_that_are_equal_but_not_the_same_still_count_as_changes() -> None:
    serializer = Serializer()
    row: dict[str, object] = {"n": 1}
    nested: list[Any] = [0, [2]]
    serializer.value(row), serializer.value(nested)
    serializer.heap()
    row["n"] = 1.0  # equal to 1, but it has to be sent as 1.0
    nested[1] = list(nested[1])  # an equal copy is another object, with an id of its own
    serializer.value(row), serializer.value(nested)
    heap = serializer.heap()
    assert type(heap[1]["items"][0][1]) is float
    assert heap[2]["items"] == [0, {"ref": 4}]


def test_an_object_whose_class_changes_is_sent_again() -> None:
    class Before:
        pass

    class After:
        pass

    thing: object = Before()
    serializer = Serializer()
    serializer.value(thing)
    serializer.heap()
    thing.__class__ = After
    serializer.value(thing)
    assert serializer.heap()[1]["cls"] == "After"


Pair = namedtuple("Pair", "a b")


class Box:
    extra: object  # set and deleted by the edits below

    def __init__(self, value: object) -> None:
        self.value = value


class Slotted:
    __slots__ = ("extra", "value")
    extra: object
    value: object

    def __init__(self, value: object) -> None:
        self.value = value


class Guarded(Box):
    def __getattribute__(self, name: str) -> object:
        return object.__getattribute__(self, name)


class Shadowed(Box):
    @property
    def value(self) -> object:  # type: ignore[override]  # shadows __dict__["value"]
        return ("seen through a property", self.__dict__["value"])

    def __init__(self, value: object) -> None:
        self.__dict__["value"] = value


SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(-2, 2),
    st.sampled_from([1.0, 0.0, -0.0, 2.5, math.inf, math.nan, "a", "ab"]),
)
NESTED = st.recursive(
    SCALARS,
    lambda inner: st.one_of(
        st.lists(inner, max_size=4),
        st.dictionaries(st.sampled_from(["k", "j", 1, 2]), inner, max_size=4),
        st.tuples(inner, inner),
        st.frozensets(st.integers(0, 5), max_size=3),
        st.sets(st.integers(0, 5), max_size=3),
        st.builds(Pair, inner, inner),
        st.builds(Box, inner),
        st.builds(Slotted, inner),
        st.builds(Guarded, inner),
        st.builds(Shadowed, inner),
    ),
    max_leaves=12,
)


def mutable(root: object) -> list[Any]:
    """Every object reachable from root that an edit can change, in a fixed order."""
    found: list[Any] = []
    stack, seen = [root], set()
    while stack:
        x = stack.pop()
        if id(x) in seen:
            continue
        seen.add(id(x))
        if isinstance(x, (list, dict, set, Box, Slotted)):
            found.append(x)
        if isinstance(x, dict):
            stack.extend(x.values())
        elif isinstance(x, (list, tuple)):
            stack.extend(x)
        elif isinstance(x, Box):
            stack.append(x.__dict__["value"])
        elif isinstance(x, Slotted):
            stack.append(x.value)
    return found


def edit(x: Any, op: int, where: int, new: object) -> None:
    """One change to x of the kinds a program makes, including ones that keep its size and
    even its values by ==, which only an identity check can see."""
    if isinstance(x, list):
        if op == 0 or not x:
            x.append(new)
        elif op == 1:
            x.pop(where % len(x))
        elif op == 2:
            x[where % len(x)] = new
        elif op == 3:
            x[0], x[-1] = x[-1], x[0]
        elif op == 4:
            x.extend(range(250))  # past the 200 items shown
        elif op == 5:  # equal by ==, but another type: 1, then 1.0, then True, then 1
            x[0] = 1.0 if type(x[0]) is int else True if type(x[0]) is float else 1
        else:
            x[0] = list(x[0]) if isinstance(x[0], list) else -0.0  # an equal copy
    elif isinstance(x, dict):
        if op == 0 or not x:
            x["k"] = new
        elif op == 1:
            del x[next(iter(x))]
        elif op == 2:
            key = next(iter(x))
            x["renamed" if key != "renamed" else "k"] = x.pop(key)  # same value, new key
        elif op == 3:
            key = next(iter(x))
            x[key] = x.pop(key)  # same keys and values, new order
        elif op == 4:
            x.update((n, n) for n in range(300))
        else:
            x[1] = True if x.get(1) is not True else 1
    elif isinstance(x, set):
        (x.add if op % 2 else x.discard)(where)
    elif isinstance(x, Shadowed):
        x.__dict__["value"] = new
    elif isinstance(x, Box):
        if op < 3:
            x.value = new
        elif op < 5:
            x.extra = new
        elif hasattr(x, "extra"):
            del x.extra
    elif isinstance(x, Slotted):
        if op < 3:
            x.value = new
        else:
            x.extra = new


def canonical(value: Value, heap: dict[int, HeapObject]) -> str:
    """value and heap with each id replaced by the order it's first reached in, so two
    serializers that numbered the same objects differently can be compared."""
    order: dict[int, int] = {}
    reached: list[int] = []

    def renamed(v: Any) -> Any:
        if isinstance(v, dict) and "ref" in v:
            if v["ref"] not in order:
                order[v["ref"]] = len(order)
                reached.append(v["ref"])
            return {"ref": order[v["ref"]]}
        if isinstance(v, list):  # a map's [key, value] pair
            return [renamed(item) for item in v]
        return v

    root = renamed(value)
    objects = []
    for oid in reached:  # grows as it's walked, until everything reachable has been seen
        obj: dict[str, Any] = dict(heap[oid])
        if "items" in obj:
            obj["items"] = renamed(obj["items"])
        if "fields" in obj:
            obj["fields"] = {name: renamed(v) for name, v in obj["fields"].items()}
        objects.append(obj)
    assert len(objects) == len(heap)  # and nothing else is in the heap
    return json.dumps([root, objects], sort_keys=True)


@given(NESTED, st.data())
def test_checking_in_place_never_misses_a_change(tree: object, data: st.DataObject) -> None:
    # Compared at every step with a new serializer, which has nothing it could reuse.
    root = [tree]
    serializer = Serializer()

    def same_as_from_scratch() -> bool:
        fresh = Serializer()
        now = canonical(serializer.value(root), serializer.heap())
        return now == canonical(fresh.value(root), fresh.heap())

    assert same_as_from_scratch()
    for _ in range(data.draw(st.integers(0, 20))):
        target = data.draw(st.sampled_from(mutable(root)))
        edit(target, data.draw(st.integers(0, 6)), data.draw(st.integers(0, 6)), data.draw(NESTED))
        assert same_as_from_scratch()


def test_printed_forms_leave_out_memory_addresses() -> None:
    def outer() -> object:
        return lambda: None

    def numbers() -> object:
        yield 1

    values, heap = snapshot(outer, outer(), numbers(), iter([1]))
    printed = []
    for value in values:
        assert isinstance(value, dict)
        printed.append(heap[value["ref"]]["v"])
    assert printed[0].startswith("<function test_printed_forms_leave_out_memory_addresses.")
    assert printed[1].endswith(".outer.<locals>.<lambda>>")
    assert printed[2].endswith(".numbers>")
    assert printed[3] == "<list_iterator object>"
    assert not any(" at 0x" in text for text in printed)
