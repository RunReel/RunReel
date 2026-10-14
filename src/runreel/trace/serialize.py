"""Turn live Python values into trace values.

Numbers, strings, booleans and None stay inline. Anything else becomes a heap object, referred
to as {"ref": id}, with an id that is stable for the whole run and never reused. Unchanged
containers come back as the very object sent last time, so the encoder can skip them by
identity instead of comparing them item by item.
"""

from __future__ import annotations

import math
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


@dataclass
class _Sent:
    """What an object looked like when it was last sent, to spot that it hasn't changed."""

    size: int
    parts: list[object]  # the live items; or the keys, then the values; or names, then values
    obj: HeapObject
    children: list[object]  # objects it refers to, so they stay in the heap


class Serializer:
    """Serialises the values of one run. Call value() for each root, then heap() once per step."""

    def __init__(self, *, max_items: int = MAX_ITEMS, max_objects: int = MAX_OBJECTS) -> None:
        self.max_items, self.max_objects = max_items, max_objects
        self._ids: dict[int, int] = {}  # id() of a live object -> its trace id
        self._kept: list[object] = []  # holds every object seen, so id() is never reused
        self._refs: dict[int, Value] = {}  # one {"ref": id} per id, reused every time
        self._sent: dict[int, _Sent] = {}
        self._pending: list[object] = []

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
        """Every object queued since the last call, plus everything those objects refer to."""
        heap: dict[int, HeapObject] = {}
        pending, i = self._pending, 0
        while i < len(pending):
            x = pending[i]
            i += 1
            oid = self._ids[id(x)]
            if oid not in heap:
                heap[oid] = self._object(x, oid) if len(heap) < self.max_objects else self._skip(x)
        self._pending = []
        return heap

    def _skip(self, x: object) -> HeapObject:
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
            return {"t": "repr", "cls": type(x).__name__, "v": _repr(x)}
        size, parts = _parts(x, kind, self.max_items)
        sent = self._sent.get(oid)
        unchanged = sent and sent.size == size and len(sent.parts) == len(parts)
        if sent and unchanged and all(map(is_, sent.parts, parts)):
            self._pending.extend(sent.children)
            return sent.obj
        start = len(self._pending)
        obj = self._build(x, kind, size, parts)
        self._sent[oid] = _Sent(size, parts, obj, self._pending[start:])
        return obj

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
    return text if len(text) <= MAX_REPR else text[:MAX_REPR] + "…"
