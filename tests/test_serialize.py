from __future__ import annotations

import math
from collections import deque, namedtuple
from typing import Any

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
