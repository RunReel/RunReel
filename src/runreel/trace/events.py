"""Where a recording's events come from: sys.monitoring on Python 3.12+, sys.settrace before.

Both sources turn the interpreter's events into four kinds of step for the recorder: "call",
"line", "return" and "exception". On 3.12+ CPython itself builds sys.settrace out of
sys.monitoring events (Python/legacy_tracing.c), and the monitoring source copies that mapping,
so the two sources record exactly the same steps. The monitoring one is faster because code from
other files is switched off the first time it runs, instead of being asked about on every call.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from types import CodeType, FrameType
from typing import Any, Literal, Protocol

Backend = Literal["auto", "monitoring", "settrace"]


class Recorder(Protocol):
    """What a source feeds: the recorder in tracer.py."""

    file: str
    truncated: bool

    def step(self, frame: FrameType, event: str, line: int, value: object = None) -> None:
        """Record one state. value is the returned value or the exception, if any."""

    def done(self, frame: FrameType) -> None:
        """A call has returned or unwound."""


class Source(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None:
        """Stop delivering events, for example when the step limit is reached. Does nothing
        before start(), since a run can be stopped while the file is still loading."""

    def close(self) -> None:
        """Undo everything start() did. Safe to call after stop(), or without start()."""


def open_source(recorder: Recorder, backend: Backend = "auto") -> Source:
    """sys.monitoring when it's available and has a free tool id, else sys.settrace."""
    if backend not in ("auto", "monitoring", "settrace"):
        raise ValueError(f"unknown backend {backend!r}")
    if sys.version_info >= (3, 12):
        if backend != "settrace":
            tool = Monitoring.free_tool()
            if tool is not None:
                return Monitoring(recorder, tool)
            if backend == "monitoring":
                raise RuntimeError("no free sys.monitoring tool id: 3 and 4 are both in use")
    elif backend == "monitoring":
        raise ValueError("the monitoring backend needs Python 3.12 or newer")
    return Settrace(recorder)


class Settrace:
    """sys.settrace: the source on 3.10 and 3.11, and the fallback when no tool id is free."""

    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder
        self.started = False
        self.previous: Callable[..., Any] | None = None

    def start(self) -> None:
        self.previous = sys.gettrace()
        self.started = True
        sys.settrace(self.on_call)

    def stop(self) -> None:
        if self.started:
            sys.settrace(None)

    def close(self) -> None:
        if self.started:  # whatever was tracing before (a debugger, coverage) carries on
            sys.settrace(self.previous)

    def on_call(self, frame: FrameType, event: str, arg: object) -> Any:
        """The global hook, asked about every new frame: trace the user's file, skip the rest."""
        if self.recorder.truncated or frame.f_code.co_filename != self.recorder.file:
            return None
        self.recorder.step(frame, "call", frame.f_lineno)
        return self.on_event

    def on_event(self, frame: FrameType, event: str, arg: Any) -> Any:
        """The per-frame hook. Returning None stops tracing that frame."""
        recorder = self.recorder
        if recorder.truncated:
            return None
        if event == "line":
            recorder.step(frame, "line", frame.f_lineno)
        elif event == "return":
            recorder.step(frame, "return", frame.f_lineno, arg)
            recorder.done(frame)
        elif event == "exception":
            recorder.step(frame, "exception", frame.f_lineno, arg[1])
        return self.on_event


if sys.version_info >= (3, 12):
    _mon = sys.monitoring
    _E = _mon.events
    # Ids 0-2 and 5 are set aside for debuggers, coverage, profilers and optimisers.
    _TOOL_IDS = (3, 4)
    # Code from the user's file gets these; every other code object only ever sees PY_START,
    # which switches it off. RAISE, PY_UNWIND and PY_THROW can only be set globally.
    _GLOBAL = _E.PY_START | _E.PY_THROW | _E.RAISE | _E.PY_UNWIND
    _LOCAL = _E.PY_RESUME | _E.PY_RETURN | _E.PY_YIELD | _E.LINE | _E.JUMP | _E.STOP_ITERATION

    class Monitoring:
        """sys.monitoring, with CPython's own settrace mapping:

        - call: PY_START, PY_RESUME and PY_THROW
        - line: LINE, plus a backward JUMP that stays on one line (a one-line loop going round)
        - return: PY_RETURN and PY_YIELD with their value, PY_UNWIND with None
        - exception: RAISE and STOP_ITERATION

        Only the thread that started recording is recorded, as with sys.settrace.
        """

        def __init__(self, recorder: Recorder, tool: int) -> None:
            self.recorder = recorder
            self.tool = tool
            self.started = False
            self.thread = threading.get_ident()
            self.codes: set[CodeType] = set()  # the user's code objects, with local events on
            self.lines: dict[tuple[CodeType, int], int | None] = {}  # (code, offset) -> line
            self.callbacks: dict[int, Callable[..., object]] = {
                _E.PY_START: self.on_start,
                _E.PY_RESUME: self.on_resume,
                _E.PY_THROW: self.on_throw,
                _E.LINE: self.on_line,
                _E.JUMP: self.on_jump,
                _E.PY_RETURN: self.on_return,
                _E.PY_YIELD: self.on_return,
                _E.PY_UNWIND: self.on_unwind,
                _E.RAISE: self.on_raise,
                _E.STOP_ITERATION: self.on_raise,
            }

        @staticmethod
        def free_tool() -> int | None:
            return next((tool for tool in _TOOL_IDS if _mon.get_tool(tool) is None), None)

        def start(self) -> None:
            _mon.use_tool_id(self.tool, "runreel")
            self.started = True
            for event, callback in self.callbacks.items():
                _mon.register_callback(self.tool, event, callback)
            _mon.restart_events()  # code switched off in an earlier recording may be the user's now
            _mon.set_events(self.tool, _GLOBAL)

        def stop(self) -> None:
            if not self.started:
                return
            _mon.set_events(self.tool, _E.NO_EVENTS)
            for code in self.codes:
                _mon.set_local_events(self.tool, code, _E.NO_EVENTS)

        def close(self) -> None:
            if not self.started:
                return
            self.stop()
            for event in self.callbacks:
                _mon.register_callback(self.tool, event, None)
            _mon.free_tool_id(self.tool)
            _mon.restart_events()  # leave no switched-off code behind for the next tool

        def ours(self, code: CodeType) -> bool:
            """Whether an event comes from the user's code on the recording thread."""
            return code in self.codes and threading.get_ident() == self.thread

        def on_start(self, code: CodeType, offset: int) -> object:
            if code.co_filename != self.recorder.file:
                return _mon.DISABLE  # never asked about this code again
            if threading.get_ident() != self.thread:
                return None
            if code not in self.codes:
                self.codes.add(code)
                _mon.set_local_events(self.tool, code, _LOCAL)
            frame = sys._getframe(1)
            self.recorder.step(frame, "call", frame.f_lineno)
            return None

        def on_resume(self, code: CodeType, offset: int) -> object:
            if self.ours(code):
                frame = sys._getframe(1)
                self.recorder.step(frame, "call", frame.f_lineno)
            return None

        def on_throw(self, code: CodeType, offset: int, exception: BaseException) -> object:
            # Same as on_resume, written out: calling it would make sys._getframe(1) this frame.
            if self.ours(code):
                frame = sys._getframe(1)
                self.recorder.step(frame, "call", frame.f_lineno)
            return None

        def on_line(self, code: CodeType, line: int) -> object:
            if threading.get_ident() == self.thread:
                self.recorder.step(sys._getframe(1), "line", line)
            return None

        def on_jump(self, code: CodeType, offset: int, target: int) -> object:
            # Only a backward jump within one line needs a step: any other jump lands on a
            # new line, which reports itself. Which kind a jump is never changes, so the rest
            # are switched off for good.
            if target > offset:
                return _mon.DISABLE
            line = self.line_at(code, target)
            if line is None or line != self.line_at(code, offset):
                return _mon.DISABLE
            if threading.get_ident() == self.thread:
                self.recorder.step(sys._getframe(1), "line", line)
            return None

        def on_return(self, code: CodeType, offset: int, value: object) -> object:
            if threading.get_ident() == self.thread:
                frame = sys._getframe(1)
                self.recorder.step(frame, "return", frame.f_lineno, value)
                self.recorder.done(frame)
            return None

        def on_unwind(self, code: CodeType, offset: int, exception: BaseException) -> object:
            if self.ours(code):
                frame = sys._getframe(1)
                self.recorder.step(frame, "return", frame.f_lineno, None)
                self.recorder.done(frame)
            return None

        def on_raise(self, code: CodeType, offset: int, exception: BaseException) -> object:
            if self.ours(code):
                frame = sys._getframe(1)
                self.recorder.step(frame, "exception", frame.f_lineno, exception)
            return None

        def line_at(self, code: CodeType, offset: int) -> int | None:
            key = (code, offset)
            if key not in self.lines:
                found = (line for start, end, line in code.co_lines() if start <= offset < end)
                self.lines[key] = next(found, None)
            return self.lines[key]
