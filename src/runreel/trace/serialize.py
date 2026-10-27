"""Turn live Python values into trace values.

Numbers, strings, booleans and None stay inline. Anything else becomes a heap object, referred
to as {"ref": id}, with an id that is stable for the whole run and never reused. Unchanged
containers come back as the very object sent last time, so the encoder can skip them by
identity instead of comparing them item by item.

heap() runs at every step for every object the program can reach, so most of a recording's
time goes there. Whether an object changed is checked in place, without copying it, and a step
where nothing in the heap changed gets back the previous step's heap.
"""

from __future__ import annotations

import math
import re
import types
from collections import deque
from dataclasses import dataclass
from itertools import islice
from operator import is_
from typing import Any, Literal, cast

from runreel.trace.model import HeapObject, Value

MAX_ITEMS = 200  # items shown per collection; the rest are counted in "more"
MAX_OBJECTS = 1000  # objects shown per step; any further ones become placeholders
MAX_STR = 1000  # characters kept of a string
MAX_REPR = 200  # characters kept of an object's printed form
SAFE_INT = 2**53 - 1  # larger integers lose precision in JavaScript, so they are tagged
# Memory addresses in printed forms, as in "<function f at 0x7f3a2c1b>". They change on every
# run, so keeping them would make two recordings of the same program differ.
_ADDRESS = re.compile(r" at 0x[0-9a-fA-F]+")

_INF: Value = {"inf": 1}
_NEG_INF: Value = {"inf": -1}
_NAN: Value = {"nan": 1}
_SEQS = (list, tuple, set, frozenset, deque)
_OPAQUE = (
    type,
    types.ModuleType,
    types.FunctionType,
    types.BuiltinFunctionType,
    types.MethodType,
    types.CodeType,
    types.FrameType,
    types.GeneratorType,
)

Kind = Literal["seq", "map", "obj", "repr"]


@dataclass(slots=True)
class _Sent:
    """What an object looked like when it was last sent, to spot that it hasn't changed."""

    cls: type
    size: int
    parts: list[object]  # the live items; or the keys, then the values; or names, then values
    obj: HeapObject
    children: list[object]  # objects it refers to, so they stay in the heap
    check: str  # how heap() tells in place that it hasn't changed: see Serializer._check()
    first: list[object]  # parts split in two, so checking needs no slicing: the items, keys or
    second: list[object]  # names first, then the values (if any)


class Serializer:
    """Serialises the values of one run. Call value() for each root, then heap() once per step."""

    def __init__(self, *, max_items: int = MAX_ITEMS, max_objects: int = MAX_OBJECTS) -> None:
        self.max_items, self.max_objects = max_items, max_objects
        self._ids: dict[int, int] = {}  # id() of a live object -> its trace id
        self._kept: list[object] = []  # holds every object seen, so id() is never reused
        self._refs: dict[int, Value] = {}  # one {"ref": id} per id, reused every time
        self._sent: dict[int, _Sent] = {}
        self._pending: list[object] = []
        self._last: dict[int, HeapObject] = {}  # the heap returned last time
        self._made = 0  # heap objects made so far, rather than reused
        self._shadowed: dict[type, frozenset[str] | None] = {}  # see _check()

    def value(self, x: object) -> Value:
        """The trace value of x. An object is also queued for the next heap()."""
        t = type(x)  # exact types: subclasses such as IntEnum become objects
        if x is None or t is bool:
            return cast(Value, x)
        if t is int:
            n = cast(int, x)
            return n if -SAFE_INT <= n <= SAFE_INT else {"bigint": str(n)}
        if t is float:
            f = cast(float, x)
            if math.isfinite(f):
                return f
            return _NAN if math.isnan(f) else _INF if f > 0 else _NEG_INF
        if t is str:
            s = cast(str, x)
            return s if len(s) <= MAX_STR else s[:MAX_STR] + "…"
        return self._ref(x)

    def heap(self) -> dict[int, HeapObject]:
        """Every object queued since the last call, plus everything those objects refer to.

        An object that hasn't changed comes back as the very object sent last time, and if
        nothing has, so does the whole heap: don't change the dict this returns.
        """
        heap: dict[int, HeapObject] = {}
        pending, ids, sent_of, cap = self._pending, self._ids, self._sent.get, self.max_objects
        made, i = self._made, 0
        while i < len(pending):
            x: Any = pending[i]
            i += 1
            oid = ids[id(x)]
            if oid in heap:
                continue
            if len(heap) >= cap:
                heap[oid] = self._skip(x)
                continue
            sent, cls = sent_of(oid), type(x)
            if sent is not None and cls is sent.cls:
                # Written out rather than called, since it runs for every object at every step.
                check = sent.check
                if check == "frozen":
                    same = True
                elif check == "items":
                    same = len(x) == sent.size and all(map(is_, x, sent.first))
                elif check == "map":
                    same = (
                        len(x) == sent.size
                        and all(map(is_, x.keys(), sent.first))
                        and all(map(is_, x.values(), sent.second))
                    )
                elif check == "dict":
                    fields = x.__dict__
                    same = (
                        len(fields) == sent.size
                        and all(map(is_, fields.keys(), sent.first))
                        and all(map(is_, fields.values(), sent.second))
                    )
                else:
                    same = False
                if same:
                    pending.extend(sent.children)
                    heap[oid] = sent.obj
                    continue
            heap[oid] = self._object(x, oid)
        self._pending = []
        if self._made == made and heap.keys() == self._last.keys():
            return self._last
        self._last = heap
        return heap

    def _skip(self, x: object) -> HeapObject:
        self._made += 1  # not the object it stood for last time, so the heap can't be reused
        return {
            "t": "repr",
            "cls": type(x).__name__,
            "v": f"(not shown: over {self.max_objects} objects)",
        }

    def _ref(self, x: object) -> Value:
        oid = self._ids.get(id(x))
        if oid is None:
            self._kept.append(x)
            oid = len(self._kept)
            self._ids[id(x)] = oid
            self._refs[oid] = {"ref": oid}
        self._pending.append(x)
        return self._refs[oid]

    def _object(self, x: object, oid: int) -> HeapObject:
        kind = _kind(x)
        if kind == "repr":
            self._made += 1
            return {"t": "repr", "cls": type(x).__name__, "v": _repr(x)}
        size, parts = _parts(x, kind, self.max_items)
        sent = self._sent.get(oid)
        if (
            sent is not None
            and sent.cls is type(x)
            and sent.size == size
            and len(sent.parts) == len(parts)
            and all(map(is_, sent.parts, parts))
        ):
            self._pending.extend(sent.children)  # unchanged, though heap() couldn't tell in place
            return sent.obj
        start = len(self._pending)
        obj = self._build(x, kind, size, parts)
        self._made += 1
        half = len(parts) // 2 if kind == "map" else size if kind == "obj" else len(parts)
        first, second, children = parts[:half], parts[half:], self._pending[start:]
        check = self._check(x, kind, first)
        self._sent[oid] = _Sent(type(x), size, parts, obj, children, check, first, second)
        return obj

    def _check(self, x: object, kind: Kind, names: list[object]) -> str:
        """How heap() can tell, in place, that x hasn't changed: "frozen" if it can't change,
        "items", "map" or "dict" to compare what it holds now with what was sent, or "" if
        only rebuilding its parts can tell, as for slots, a custom __getattribute__ or a
        property named like one of its fields."""
        cls = type(x)
        if kind == "seq":
            return "frozen" if cls in (tuple, frozenset) else "items"
        if kind == "map":
            return "map"
        if isinstance(x, tuple):
            return "frozen"  # a namedtuple, whose fields are its items
        if cls not in self._shadowed:
            self._shadowed[cls] = _shadowed(cls)
        shadowed = self._shadowed[cls]
        return "dict" if shadowed is not None and shadowed.isdisjoint(names) else ""

    def _build(self, x: object, kind: Kind, size: int, parts: list[object]) -> HeapObject:
        cls = type(x).__name__
        if kind == "obj":
            names, values = parts[:size], parts[size:]
            fields = {str(k): self.value(v) for k, v in zip(names, values, strict=True)}
            return {"t": "obj", "cls": cls, "fields": fields}
        if kind == "map":
            half = len(parts) // 2
            pairs = zip(parts[:half], parts[half:], strict=True)
            obj: HeapObject = {
                "t": "map",
                "cls": cls,
                "items": [[self.value(k), self.value(v)] for k, v in pairs],
            }
        else:
            obj = {"t": "seq", "cls": cls, "items": [self.value(item) for item in parts]}
        if size > len(obj["items"]):
            obj["more"] = size - len(obj["items"])
        return obj


def _kind(x: object) -> Kind:
    if isinstance(x, dict):
        return "map"
    if isinstance(x, tuple) and hasattr(type(x), "_fields"):
        return "obj"  # a namedtuple reads better as named fields
    if isinstance(x, _SEQS):
        return "seq"
    if isinstance(x, _OPAQUE):
        return "repr"
    if hasattr(x, "__dict__") or _slots(type(x)):
        return "obj"
    return "repr"


def _parts(x: Any, kind: Kind, limit: int) -> tuple[int, list[object]]:
    """The size of x and the live values that make up its shown part, without calling user code."""
    if kind == "map":
        return len(x), [*islice(x.keys(), limit), *islice(x.values(), limit)]
    if kind == "obj":
        names = _field_names(x)
        return len(names), [*names, *(getattr(x, name) for name in names)]
    return len(x), list(islice(x, limit))


def _field_names(x: Any) -> list[str]:
    if isinstance(x, tuple):
        return list(getattr(type(x), "_fields"))  # noqa: B009  # a namedtuple
    names = list(getattr(x, "__dict__", {}))
    names += [name for name in _slots(type(x)) if name not in names and hasattr(x, name)]
    return names


def _shadowed(cls: type) -> frozenset[str] | None:
    """The names that getattr() finds on cls before an instance's __dict__ (its data
    descriptors), or None if its instances can't be read through __dict__ at all."""
    if _slots(cls) or any("__getattribute__" in vars(klass) for klass in cls.__mro__[:-1]):
        return None
    return frozenset(
        name
        for klass in cls.__mro__
        for name, attr in vars(klass).items()
        if hasattr(type(attr), "__set__") or hasattr(type(attr), "__delete__")
    )


def _slots(cls: type) -> list[str]:
    names: list[str] = []
    for klass in cls.__mro__:
        slots = klass.__dict__.get("__slots__", ())
        names += [slots] if isinstance(slots, str) else [s for s in slots if s != "__dict__"]
    return names


def _repr(x: object) -> str:
    try:
        text = repr(x)
    except Exception:
        text = f"<{type(x).__name__} object>"
    text = _ADDRESS.sub("", text)
    return text if len(text) <= MAX_REPR else text[:MAX_REPR] + "…"
