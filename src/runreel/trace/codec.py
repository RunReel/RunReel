"""Encode a run's states as keyframes plus deltas, and rebuild the state at any step.

A keyframe is a delta from the empty state, so one function, _apply, decodes both. A changed
object is sent as a patch when that is shorter than sending the whole object again.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Iterable, Iterator, Sequence
from itertools import compress, count
from operator import is_not
from typing import Any, cast

from runreel.trace.model import (
    Frame,
    FramePatch,
    HeapObject,
    ObjectPatch,
    State,
    Step,
    Trace,
    Value,
)

KEY_EVERY = 100
MAX_EDITS = 16  # a list diff stops looking past this many removed plus inserted items
SMALL_STRETCH = 8  # a changed stretch this short is sent as one splice, without a diff


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
    heap: dict[str, HeapObject | ObjectPatch] = {}
    for oid in sorted(cur["heap"]):
        obj, old = cur["heap"][oid], prev["heap"].get(oid)
        entry = obj if old is None else _heap_entry(old, obj)
        if entry is not None:
            heap[str(oid)] = entry
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
    changed, removed = _changes(old["locals"] if old else {}, new["locals"])
    if changed:
        patch["set"] = changed
    if removed:
        patch["del"] = removed
    return patch


def _heap_entry(old: HeapObject, new: HeapObject) -> HeapObject | ObjectPatch | None:
    """What to send for an object that already existed: nothing if it hasn't changed, else a
    patch if that is shorter than the whole object, else the object."""
    if old is new:  # a tracer that reuses unchanged objects makes this the common case
        return None
    if new["t"] == "repr" or (old["t"], old["cls"]) != (new["t"], new["cls"]):
        return None if _same(old, new) else new
    patch: ObjectPatch = {}
    if new["t"] == "obj":
        changed, removed = _changes(old["fields"], new["fields"])
        if changed:
            patch["set"] = changed
        if removed:
            patch["del"] = removed
        count = len(new["fields"])
    else:
        ops = _item_ops(old["items"], new["items"])
        if ops:
            patch["ops"] = ops
        if old.get("more", 0) != new.get("more", 0):
            patch["more"] = new.get("more", 0)
        count = len(new["items"])
    if not patch:
        return None
    # Each item or field adds at least two bytes to the object (itself and a comma), so the
    # object is only sized exactly when that lower bound doesn't settle the choice.
    size = _size(patch)
    return patch if size < 2 * count or size < _size(new) else new


def _changes(old: dict[str, Value], new: dict[str, Value]) -> tuple[dict[str, Value], list[str]]:
    """The names in new that are new or changed, and the names in old that are gone."""
    changed = {k: v for k, v in new.items() if k not in old or not _same(old[k], v)}
    return changed, [k for k in old if k not in new]


def _item_ops(old: list[Any], new: list[Any]) -> list[list[Any]]:
    """Ops that turn the old items into the new: the fewest edits or one splice of the
    stretch that changed, whichever is shorter. Matching items at both ends are skipped."""
    lo = _matching(old, new)
    hi = _matching(old[lo:][::-1], new[lo:][::-1])
    a, b = old[lo : len(old) - hi], new[lo : len(new) - hi]
    if not a and not b:
        return []
    splice: list[list[Any]] = [[lo, b[0]]] if len(a) == len(b) == 1 else [[lo, len(a), b]]
    # Diffing a short stretch could save only a few bytes, so it isn't worth the time.
    runs = None if len(a) + len(b) <= SMALL_STRETCH else _myers(a, b)
    if runs is None or len(runs) == 1:  # a single run is the whole stretch, so it is the splice
        return splice
    ops: list[list[Any]] = [
        [lo + x0, b[y0]] if x1 - x0 == y1 - y0 == 1 else [lo + x0, x1 - x0, b[y0:y1]]
        for x0, x1, y0, y1 in runs
    ]
    # Each item in the splice costs at least two bytes, the same bound as in _heap_entry.
    size = _size(ops)
    return ops if size < 2 * len(b) or size < _size(splice) else splice


def _myers(a: list[Any], b: list[Any]) -> list[list[int]] | None:
    """Myers' diff: the fewest removals plus insertions that turn a into b, or None if that
    takes more than MAX_EDITS. Edits with no kept item between them form one run
    [x0, x1, y0, y1], which replaces a[x0:x1] with b[y0:y1].

    Picture a grid with a along the top and b down the side. A diagonal move keeps an item and
    is free; a move right removes an item and a move down inserts one. Diagonal k is where
    x - y == k. In round d, v[k] is how far right a path with d edits gets on diagonal k. The
    first round that reaches the bottom-right corner has the fewest edits, and the v saved
    from each round lead the path back.
    """
    n, m = len(a), len(b)
    if abs(n - m) > MAX_EDITS:
        return None
    v = {1: 0}
    rounds: list[dict[int, int]] = []
    for d in range(MAX_EDITS + 1):
        rounds.append(v.copy())
        for k in range(-d, d + 1, 2):
            # Extend whichever neighbour got further: down from k + 1 or right from k - 1.
            down = k == -d or (k != d and v[k - 1] < v[k + 1])
            x = v[k + 1] if down else v[k - 1] + 1
            y = x - k
            if x < n and y < m and _same(a[x], b[y]):  # most snakes are empty: check one first
                x += 1 + _matching(a[x + 1 :], b[y + 1 :])
                y = x - k
            v[k] = x
            if x >= n and y >= m:
                return _runs(rounds, n, m)
    return None


def _runs(rounds: list[dict[int, int]], n: int, m: int) -> list[list[int]]:
    """Walk Myers' path back from the corner, joining edits that have no kept item between."""
    runs: list[list[int]] = []
    x, y = n, m
    for d in range(len(rounds) - 1, 0, -1):
        v, k = rounds[d], x - y
        down = k == -d or (k != d and v[k - 1] < v[k + 1])
        px = v[k + 1] if down else v[k - 1]
        py = px - (k + 1 if down else k - 1)
        ex, ey = (px, py + 1) if down else (px + 1, py)  # where this edit ends
        if runs and runs[-1][0] == ex and runs[-1][2] == ey:
            runs[-1][0], runs[-1][2] = px, py
        else:
            runs.append([px, ex, py, ey])
        x, y = px, py
    return runs[::-1]


def _matching(xs: list[Any], ys: list[Any]) -> int:
    """How many items match at the start of xs and ys. Pairs that are the same object are
    skipped in C; only the others are compared with _same, one at a time."""
    for i in compress(count(), map(is_not, xs, ys)):
        if not _same(xs[i], ys[i]):
            return i
    return min(len(xs), len(ys))


def _size(data: object) -> int:
    """Bytes of data's JSON as dumps writes it."""
    return len(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode())


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
            _apply_patch(state["heap"][int(oid)], entry)
    for gone in step.get("gc", []):
        del state["heap"][gone]
    if "ret" in step:
        state["ret"] = step["ret"]
    if "exc" in step:
        state["exc"] = step["exc"]


def _apply_patch(obj: HeapObject, patch: ObjectPatch) -> None:
    """Edit an object in place. Ops index the items as they were, so they run back to front."""
    for op in reversed(patch.get("ops", [])):
        if len(op) == 2:
            obj["items"][op[0]] = op[1]
        else:
            start, count, items = op
            obj["items"][start : start + count] = items
    if "set" in patch:
        obj["fields"].update(patch["set"])
    for name in patch.get("del", []):
        del obj["fields"][name]
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
    if a is b:
        return True
    if type(a) is not type(b):
        return False
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(map(_same, a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(v, b[k]) for k, v in a.items())
    if isinstance(a, float) and isinstance(b, float):
        return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)
    return a == b
