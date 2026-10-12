"""Trace format v1: the JSON shapes shared by the tracer, the codec and the player.

A value is a JSON scalar or one of four tagged objects: {"ref": id} points to a heap
object, and {"inf": 1 | -1}, {"nan": 1} and {"bigint": "digits"} carry numbers that
JSON can't hold. The formal definition is schema/trace-v1.schema.json.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

SCHEMA_VERSION = 1

Event = Literal["call", "line", "return", "exception"]

Value = None | bool | int | float | str | dict[str, Any]


class Frame(TypedDict):
    """One call on the stack: its id, function name, current line and local variables."""

    fid: int
    fn: str
    line: int
    locals: dict[str, Value]


class _HeapObjectBase(TypedDict):
    t: Literal["seq", "map", "obj", "repr"]
    cls: str


class HeapObject(_HeapObjectBase, total=False):
    """An object that variables refer to. Which keys are present depends on t."""

    items: list[Any]  # seq: values; map: [key, value] pairs
    more: int  # number of items left out beyond the size cap (absent when 0)
    fields: dict[str, Value]  # obj only
    v: str  # repr only


class ItemPatch(TypedDict, total=False):
    """Changes to a seq or map: resize to len, overwrite [index, item] entries, set more."""

    len: int
    set: list[list[Any]]
    more: int


# "del" is a Python keyword, so this TypedDict uses the functional syntax.
FramePatch = TypedDict(
    "FramePatch",
    {"fn": str, "line": int, "set": dict[str, Value], "del": list[str]},
    total=False,
)


class _StepBase(TypedDict):
    ev: Event
    line: int


class Step(_StepBase, total=False):
    """What one step changed. A keyframe (key=True) is a delta from the empty state."""

    key: Literal[True]
    stack: list[int]
    frames: dict[str, FramePatch]
    heap: dict[str, HeapObject | ItemPatch]
    gc: list[int]
    ret: Value
    exc: str


class _StateBase(TypedDict):
    ev: Event
    line: int
    stack: list[Frame]
    heap: dict[int, HeapObject]


class State(_StateBase, total=False):
    """The full program state after one step, as the tracer records it."""

    ret: Value
    exc: str


class Source(TypedDict):
    file: str
    text: str
    entry: str


class _TraceBase(TypedDict):
    schema: Literal[1]
    language: Literal["python"]
    source: Source
    steps: list[Step]


class Trace(_TraceBase, total=False):
    """A whole run: the source, the steps, and what the run returned or printed."""

    result: Value
    error: str
    stdout: list[list[Any]]  # [step index, text]
    truncated: Literal[True]
