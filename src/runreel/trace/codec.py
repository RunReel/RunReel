"""Encode a run's states as keyframes plus deltas, and rebuild the state at any step.

A keyframe is a delta from the empty state, so one function, _apply, decodes both.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Iterable, Iterator, Sequence
from typing import cast

from runreel.trace.model import Frame, FramePatch, HeapObject, ItemPatch, State, Step, Trace

KEY_EVERY = 100


def encode(states: Iterable[State], *, key_every: int = KEY_EVERY) -> list[Step]:
    """Turn full states into steps: a keyframe every `key_every` steps, deltas in between.

    The states must not be changed afterwards, because the steps share their objects.
    """
    if key_every < 1:
        raise ValueError("key_every must be at least 1")
    steps: list[Step] = []
    prev = _empty_state()
    for i, cur in enumerate(states):
        key = i % key_every == 0
        steps.append(_diff(_empty_state() if key else prev, cur, key=key))
        prev = cur
    return steps


def iter_states(steps: Sequence[Step]) -> Iterator[State]:
    """Yield the full state after each step, in order."""
    state = _empty_state()
    for i, step in enumerate(steps):
        if i == 0 and not step.get("key"):
            raise ValueError("the first step must be a keyframe")
        _apply(state, step)
        yield copy.deepcopy(state)


def state_at(steps: Sequence[Step], n: int) -> State:
    """Rebuild the state after step n by replaying from the nearest keyframe at or before it."""
    if not 0 <= n < len(steps):
        raise IndexError(f"step {n} is out of range for {len(steps)} steps")
    k = n
    while not steps[k].get("key"):
        if k == 0:
            raise ValueError("the first step must be a keyframe")
        k -= 1
    state = _empty_state()
    for step in steps[k : n + 1]:
        _apply(state, step)
    return state


def dumps(trace: Trace) -> str:
    """Serialise a trace as compact JSON. Raises on NaN or infinity, which must be tagged."""
    return json.dumps(trace, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _empty_state() -> State:
    return {"ev": "line", "line": 0, "stack": [], "heap": {}}


def _diff(prev: State, cur: State, *, key: bool) -> Step:
    """The step that turns prev into cur: only the frames, locals and objects that changed."""
    step: Step = {"ev": cur["ev"], "line": cur["line"]}
    if key:
        step["key"] = True
    fids = [frame["fid"] for frame in cur["stack"]]
    if fids != [frame["fid"] for frame in prev["stack"]]:
        step["stack"] = fids
    old_frames = {frame["fid"]: frame for frame in prev["stack"]}
    frames: dict[str, FramePatch] = {}
    for depth, frame in enumerate(cur["stack"]):
        top_line = cur["line"] if depth == len(cur["stack"]) - 1 else None
        patch = _frame_patch(old_frames.get(frame["fid"]), frame, top_line)
        if patch:
            frames[str(frame["fid"])] = patch
    if frames:
        step["frames"] = frames
    heap: dict[str, HeapObject | ItemPatch] = {}
    for oid in sorted(cur["heap"]):
        obj, old = cur["heap"][oid], prev["heap"].get(oid)
        if old is None:
            heap[str(oid)] = obj
        elif not _same(old, obj):
            heap[str(oid)] = _heap_entry(old, obj)
    if heap:
        step["heap"] = heap
    gone = sorted(oid for oid in prev["heap"] if oid not in cur["heap"])
    if gone:
        step["gc"] = gone
    if "ret" in cur:
        step["ret"] = cur["ret"]
    if "exc" in cur:
        step["exc"] = cur["exc"]
    return step


def _frame_patch(old: Frame | None, new: Frame, top_line: int | None) -> FramePatch:
    """What changed in one frame. A line is sent only if the decoder couldn't infer it."""
    patch: FramePatch = {}
    if old is None:
        patch["fn"] = new["fn"]
    inferred = top_line if top_line is not None else old["line"] if old else None
    if new["line"] != inferred:
        patch["line"] = new["line"]
    before = old["locals"] if old else {}
    changed = {k: v for k, v in new["locals"].items() if k not in before or not _same(before[k], v)}
    if changed:
        patch["set"] = changed
    removed = [k for k in before if k not in new["locals"]]
    if removed:
        patch["del"] = removed
    return patch


def _heap_entry(old: HeapObject, new: HeapObject) -> HeapObject | ItemPatch:
    """A changed object: an item patch if it touches at most half the items, else the object."""
    if new["t"] in ("seq", "map") and (old["t"], old["cls"]) == (new["t"], new["cls"]):
        patch = _item_patch(old, new)
        if 2 * len(patch.get("set", [])) <= len(new["items"]):
            return patch
    return new


def _item_patch(old: HeapObject, new: HeapObject) -> ItemPatch:
    a, b = old["items"], new["items"]
    patch: ItemPatch = {}
    if len(a) != len(b):
        patch["len"] = len(b)
    changed = [[i, item] for i, item in enumerate(b) if i >= len(a) or not _same(a[i], item)]
    if changed:
        patch["set"] = changed
    if old.get("more", 0) != new.get("more", 0):
        patch["more"] = new.get("more", 0)
    return patch


def _apply(state: State, step: Step) -> None:
    """Apply one step to state in place. A keyframe first resets the state to empty."""
    if step.get("key"):
        state["stack"], state["heap"] = [], {}
    state["ev"], state["line"] = step["ev"], step["line"]
    state.pop("ret", None)
    state.pop("exc", None)
    if "stack" in step:
        by_fid = {frame["fid"]: frame for frame in state["stack"]}
        state["stack"] = [
            by_fid.get(fid) or {"fid": fid, "fn": "", "line": 0, "locals": {}}
            for fid in step["stack"]
        ]
    if state["stack"]:
        state["stack"][-1]["line"] = step["line"]
    by_fid = {frame["fid"]: frame for frame in state["stack"]}
    for fid, patch in step.get("frames", {}).items():
        frame = by_fid[int(fid)]
        if "fn" in patch:
            frame["fn"] = patch["fn"]
        if "line" in patch:
            frame["line"] = patch["line"]
        frame["locals"].update(patch.get("set", {}))
        for name in patch.get("del", []):
            del frame["locals"][name]
    for oid, entry in step.get("heap", {}).items():
        if "t" in entry:
            state["heap"][int(oid)] = _copy_object(cast(HeapObject, entry))
        else:
            _apply_item_patch(state["heap"][int(oid)], entry)
    for gone in step.get("gc", []):
        del state["heap"][gone]
    if "ret" in step:
        state["ret"] = step["ret"]
    if "exc" in step:
        state["exc"] = step["exc"]


def _apply_item_patch(obj: HeapObject, patch: ItemPatch) -> None:
    items = obj["items"]
    if "len" in patch:
        del items[patch["len"] :]
        items.extend([None] * (patch["len"] - len(items)))
    for i, item in patch.get("set", []):
        items[i] = item
    if "more" in patch:
        if patch["more"]:
            obj["more"] = patch["more"]
        else:
            obj.pop("more", None)


def _copy_object(obj: HeapObject) -> HeapObject:
    """A copy whose items or fields can be patched without changing the trace itself."""
    copied = obj.copy()
    if "items" in obj:
        copied["items"] = list(obj["items"])
    if "fields" in obj:
        copied["fields"] = dict(obj["fields"])
    return copied


def _same(a: object, b: object) -> bool:
    """Equality that tells 1, 1.0 and True apart (Python's == doesn't) and keeps 0.0's sign."""
    if type(a) is not type(b):
        return False
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(map(_same, a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(v, b[k]) for k, v in a.items())
    if isinstance(a, float) and isinstance(b, float):
        return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)
    return a == b
