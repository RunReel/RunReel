"""Turn live Python values into trace values.

Numbers, strings, booleans and None stay inline. Anything else becomes a heap object, referred
to as {"ref": id}, with an id that is stable for the whole run and never reused. Unchanged
containers come back as the very object sent last time, so the encoder can skip them by
identity instead of comparing them item by item.

heap() runs at every step for every object the program can reach, so most of a recording's
time goes there. Whether an object changed is checked in place, without copying it, and a step
where nothing in the heap changed gets back the previous step's heap.

Reading an object never runs the program's own code, so recording can't change what the
program does: a container whose class redefines how it's read (its __len__, __iter__, keys or
values) is read through the built-in type's methods, and fields come straight from where they
are stored, without properties or a custom __getattribute__ running.
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
# run, so keeping them would make two recordings of the same program differ. Only an address
# that ends a <...> form counts, so text such as b"jump at 0x1f" is left alone.
_ADDRESS = re.compile(r" at 0x[0-9a-fA-F]+(?=>)")


def without_addresses(text: str) -> str:
    """text with the memory addresses taken out of the printed forms in it."""
    return _ADDRESS.sub("", text)


_INF: Value = {"inf": 1}
_NEG_INF: Value = {"inf": -1}
_NAN: Value = {"nan": 1}
_SEQS = (list, tuple, set, frozenset, deque)
_CONTAINERS = (*_SEQS, dict)
_READERS = ("__len__", "__iter__", "keys", "values")  # what reading a container calls
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
        self._through: dict[type, type | None] = {}  # see _reader()
        self._plain: dict[type, bool] = {}  # see _check()

    def value(self, x: object) -> Value:
        """The trace value of x. An object is also queued for the next heap()."""
        t = type(x)  # exact types: subclasses such as IntEnum become objects
        if x is None or t is bool:
            return cast(Value, x)
        if t is int:
            n = cast(int, x)
            if -SAFE_INT <= n <= SAFE_INT:
                return n
            try:
                return {"bigint": str(n)}
            except ValueError:  # too long for Python to print: see sys.set_int_max_str_digits
                return self._ref(x)
        if t is float:
            f = cast(float, x)
            if not math.isfinite(f):
                return _NAN if math.isnan(f) else _INF if f > 0 else _NEG_INF
            # A JSON reader in the browser turns 1.0 into 1, and writes 1e-05 as 0.00001, so a
            # float it would print differently from Python keeps Python's text.
            text = repr(f)
            return {"float": text} if text.endswith(".0") or "e" in text else f
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
        size, parts = _parts(x, kind, self.max_items, self._reader(type(x)))
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
        check = self._check(x, kind)
        self._sent[oid] = _Sent(type(x), size, parts, obj, children, check, first, second)
        return obj

    def _check(self, x: object, kind: Kind) -> str:
        """How heap() can tell, in place, that x hasn't changed: "frozen" if it can't change,
        "items", "map" or "dict" to compare what it holds now with what was sent, or "" if
        only rebuilding its parts can tell without running the program's code, as for a
        container that redefines how it's read, slots or a custom __getattribute__."""
        cls = type(x)
        if kind == "seq":
            return "frozen" if cls in (tuple, frozenset) else "" if self._reader(cls) else "items"
        if kind == "map":
            return "" if self._reader(cls) else "map"
        if issubclass(cls, tuple):
            return "frozen"  # a namedtuple, whose fields are its items
        if cls not in self._plain:
            ours = cls.__mro__[:-1]  # everything but object
            self._plain[cls] = not _slots(cls) and not any(
                "__getattribute__" in vars(k) for k in ours
            )
        return "dict" if self._plain[cls] else ""

    def _reader(self, cls: type) -> type | None:
        """The built-in class to read a container of cls through, if cls redefines in Python
        how it's read, or None to read it as it is. Kept per run, not for good, so the
        program's classes don't outlive it."""
        if cls not in self._through:
            self._through[cls] = _through(cls)
        return self._through[cls]

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
    """What x becomes in the heap, decided from its class, never by asking x itself."""
    cls = type(x)
    if issubclass(cls, dict):
        return "map"
    if issubclass(cls, tuple) and hasattr(cls, "_fields"):
        return "obj"  # a namedtuple reads better as named fields
    if issubclass(cls, _SEQS):
        return "seq"
    if issubclass(cls, _OPAQUE):
        return "repr"
    # A __dict__ descriptor is what makes x.__dict__ work. __dictoffset__ can be set when it
    # doesn't, as for asyncio's futures, which are clearer shown printed.
    if any("__dict__" in vars(klass) for klass in cls.__mro__) or _slots(cls):
        return "obj"
    return "repr"


def _parts(x: Any, kind: Kind, limit: int, through: type | None) -> tuple[int, list[object]]:
    """The size of x and the live values that make up its shown part. through, if given, is the
    built-in class to read a container through, so its own redefinitions don't run."""
    if kind == "obj":
        names, values = _fields(x)
        return len(names), [*names, *values]
    if kind == "map":
        if through is None:
            return len(x), [*islice(x.keys(), limit), *islice(x.values(), limit)]
        return dict.__len__(x), [*islice(dict.keys(x), limit), *islice(dict.values(x), limit)]
    if through is None:
        return len(x), list(islice(x, limit))
    base: Any = through  # list, tuple, set, frozenset or deque
    return base.__len__(x), list(islice(base.__iter__(x), limit))


def _fields(x: Any) -> tuple[list[str], list[object]]:
    """An object's field names and values, read from where they're stored: a namedtuple's
    items, then the instance's __dict__ and its slots."""
    cls = type(x)
    if issubclass(cls, tuple):  # a namedtuple
        names = list(getattr(cls, "_fields"))  # noqa: B009
        return names, [tuple.__getitem__(x, i) for i in range(len(names))]
    try:
        stored: dict[str, object] = object.__getattribute__(x, "__dict__")
    except AttributeError:
        stored = {}
    names, values = list(stored), list(stored.values())
    for name in _slots(cls):
        slot = _slot(cls, name)
        if name in stored or slot is None:
            continue
        try:
            values.append(slot.__get__(x, cls))
        except AttributeError:
            continue  # not set
        names.append(name)
    return names, values


def _through(cls: type) -> type | None:
    """The built-in container class to read cls through if a Python class in its hierarchy
    redefines how it's read; None if its reading is all built in."""
    for klass in cls.__mro__:
        if klass in _CONTAINERS:
            return None
        defined = vars(klass)
        if any(isinstance(defined.get(name), types.FunctionType) for name in _READERS):
            return next(base for base in cls.__mro__ if base in _CONTAINERS)
    return None


def _slot(cls: type, name: str) -> types.MemberDescriptorType | None:
    """The descriptor that stores slot name, from the class that declared it."""
    for klass in cls.__mro__:
        found = vars(klass).get(name)
        if isinstance(found, types.MemberDescriptorType):
            return found
    return None


def _digits(n: int) -> str:
    """An int too long to print, described by its number of digits."""
    bits = abs(n).bit_length()
    digits = int(bits * math.log10(2)) + 1
    if bits > 3_000_000:  # counting exactly would take a while
        return f"<int with about {digits:,} digits>"
    if 10 ** (digits - 1) > abs(n):
        digits -= 1
    return f"<int with {digits:,} digits>"


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
        text = _digits(x) if type(x) is int else f"<{type(x).__name__} object>"
    text = without_addresses(text)
    return text if len(text) <= MAX_REPR else text[:MAX_REPR] + "…"
