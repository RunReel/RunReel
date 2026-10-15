"""Record a run of a Python file as a trace: one state per call, line, return or exception.

Only code from the user's file is traced. Library and built-in calls aren't stepped through,
but their effects show up in the next state. A "line" state is taken just before that line
runs, as sys.settrace reports it.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import sys
import types
from collections.abc import Collection, Iterator
from pathlib import Path
from types import FrameType
from typing import Any, cast

from runreel.trace.codec import encode
from runreel.trace.model import Event, Frame, State, Trace, Value
from runreel.trace.serialize import Serializer

MAX_STEPS = 5000
_RESUMABLE = inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR
_HIDDEN_AT_TOP_LEVEL = (types.ModuleType, types.FunctionType, types.BuiltinFunctionType, type)


def record(
    path: str | Path,
    call: str | None = None,
    *,
    lines: Collection[int] | None = None,
    max_steps: int = MAX_STEPS,
    stdin: str = "",
) -> Trace:
    """Run the file and record it.

    With call, the file is loaded as a module (its __main__ block doesn't run) and only the
    call, such as "dijkstra(G, 0)", is traced. Without it, the file runs as a script. With
    lines, only states on those lines are kept. After max_steps states the trace is marked
    truncated and the program finishes untraced. The program reads stdin as its input, never
    the terminal, so it can't stop and wait; sys.stdin.buffer works for fast reads.
    """
    file = Path(path).resolve()
    text = file.read_text(encoding="utf-8")
    code = compile(text, str(file), "exec")
    name = "__main__" if call is None else "__runreel__"
    module = types.ModuleType(name)
    module.__file__ = str(file)
    recorder = _Recorder(str(file), lines, max_steps)
    output = _Output(recorder)
    trace: Trace = {
        "schema": 1,
        "language": "python",
        "source": {"file": file.name, "text": text, "entry": call or ""},
        "steps": [],
    }
    saved = sys.modules.get(name)
    sys.modules[name] = module  # dataclasses and pickling look the module up by name
    try:
        with contextlib.redirect_stdout(output), _input(stdin):
            entry = None
            if call is not None:
                exec(code, module.__dict__)  # define the functions, untraced
                entry = compile(call, "<runreel call>", "eval")
            sys.settrace(recorder.on_call)
            try:
                if entry is None:
                    exec(code, module.__dict__)
                else:
                    trace["result"] = recorder.result(eval(entry, module.__dict__))
            except SystemExit as exit:
                if exit.code not in (None, 0):
                    trace["error"] = f"SystemExit: {exit.code}"
            except Exception as error:
                trace["error"] = _describe(error)
            finally:
                sys.settrace(None)
    finally:
        if saved is None:
            del sys.modules[name]
        else:
            sys.modules[name] = saved
    trace["steps"] = encode(recorder.states)
    if output.chunks:
        trace["stdout"] = output.chunks
    if recorder.truncated:
        trace["truncated"] = True
    return trace


class _Recorder:
    def __init__(self, file: str, lines: Collection[int] | None, max_steps: int) -> None:
        self.file, self.max_steps = file, max_steps
        self.lines = None if lines is None else frozenset(lines)
        self.states: list[State] = []
        self.serializer = Serializer()
        self.truncated = False
        self._fids: dict[int, int] = {}  # id() of a live frame -> its call id
        self._frames: dict[int, FrameType] = {}  # keeps those frames alive, so id() isn't reused
        self._next_fid = 1

    def on_call(self, frame: FrameType, event: str, arg: Any) -> Any:
        """sys.settrace's global hook: trace frames from the user's file, ignore the rest."""
        if self.truncated or frame.f_code.co_filename != self.file:
            return None
        self._record(frame, event, arg)
        return self.on_event

    def on_event(self, frame: FrameType, event: str, arg: Any) -> Any:
        """The per-frame hook. Returning None stops tracing that frame."""
        if self.truncated:
            return None
        if event in ("line", "return", "exception"):
            self._record(frame, event, arg)
        if event == "return" and not frame.f_code.co_flags & _RESUMABLE:
            self._frames.pop(self._fids.pop(id(frame), 0), None)
        return self.on_event

    def result(self, value: object) -> Value:
        """The call's return value. It is a heap object only if some state already showed it."""
        result = self.serializer.value(value)
        shown = self.states[-1]["heap"] if self.states else {}
        if isinstance(result, dict) and "ref" in result and result["ref"] not in shown:
            return repr(value)[:200]
        return result

    def _record(self, frame: FrameType, event: str, arg: Any) -> None:
        if self.lines is not None and frame.f_lineno not in self.lines:
            return
        if len(self.states) >= self.max_steps:
            self.truncated = True
            sys.settrace(None)
            return
        stack: list[FrameType] = []
        f: FrameType | None = frame
        while f is not None:
            if f.f_code.co_filename == self.file:
                stack.append(f)
            f = f.f_back
        frames: list[Frame] = [
            {
                "fid": self._fid(f),
                "fn": f.f_code.co_name,
                "line": f.f_lineno,
                "locals": self._locals(f),
            }
            for f in reversed(stack)
        ]
        state: State = {
            "ev": cast(Event, event),
            "line": frame.f_lineno,
            "stack": frames,
            "heap": {},
        }
        if event == "return":
            state["ret"] = self.serializer.value(arg)
        elif event == "exception":
            state["exc"] = _describe(arg[1])
        state["heap"] = self.serializer.heap()
        self.states.append(state)

    def _fid(self, frame: FrameType) -> int:
        fid = self._fids.get(id(frame))
        if fid is None:
            fid, self._next_fid = self._next_fid, self._next_fid + 1
            self._fids[id(frame)] = fid
            self._frames[fid] = frame
        return fid

    def _locals(self, frame: FrameType) -> dict[str, Value]:
        top_level = frame.f_code.co_name == "<module>"
        shown: dict[str, Value] = {}
        for name, value in frame.f_locals.items():
            if name.startswith(".") or (top_level and _hidden_at_top_level(name, value)):
                continue  # ".0" is a comprehension's hidden iterator
            shown[name] = self.serializer.value(value)
        return shown


@contextlib.contextmanager
def _input(text: str) -> Iterator[None]:
    """Give the program text as its standard input, with a .buffer like the real one."""
    saved = sys.stdin
    sys.stdin = io.TextIOWrapper(io.BytesIO(text.encode()), encoding="utf-8")
    try:
        yield
    finally:
        sys.stdin = saved


def _hidden_at_top_level(name: str, value: object) -> bool:
    """Module-level names that aren't the program's data: dunders, imports, functions, classes."""
    return name.startswith("__") or isinstance(value, _HIDDEN_AT_TOP_LEVEL)


def _describe(error: BaseException) -> str:
    text = str(error)
    return f"{type(error).__name__}: {text}" if text else type(error).__name__


class _Output(io.TextIOBase):
    """Captures printed text as [step, text] pairs, joining writes made during the same step."""

    def __init__(self, recorder: _Recorder) -> None:
        self.recorder = recorder
        self.chunks: list[list[Any]] = []

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        step = max(len(self.recorder.states) - 1, 0)
        if self.chunks and self.chunks[-1][0] == step:
            self.chunks[-1][1] += text
        else:
            self.chunks.append([step, text])
        return len(text)
