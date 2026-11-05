"""Record a run of a Python file as a trace: one state per call, line, return or exception.

Only code from the user's file is traced. Library and built-in calls aren't stepped through,
but their effects show up in the next state. A "line" state is taken just before that line
runs. The events come from sys.monitoring on Python 3.12+ and sys.settrace before (events.py),
and deadline.py stops a program that runs too long.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import sys
import types
from collections.abc import Callable, Collection, Iterator, Sequence
from pathlib import Path
from types import FrameType
from typing import Any, cast

from runreel.trace.codec import encode
from runreel.trace.deadline import Deadline, TimeUp
from runreel.trace.events import Backend, open_source
from runreel.trace.model import Event, Frame, State, Trace, Value
from runreel.trace.serialize import Serializer

MAX_STEPS = 5000
TIMEOUT = 60.0  # seconds
_RESUMABLE = inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR
_HIDDEN_AT_TOP_LEVEL = (types.ModuleType, types.FunctionType, types.BuiltinFunctionType, type)


def record(
    path: str | Path,
    call: str | None = None,
    *,
    lines: Collection[int] | None = None,
    max_steps: int = MAX_STEPS,
    args: Sequence[str] = (),
    stdin: str = "",
    backend: Backend = "auto",
    timeout: float | None = TIMEOUT,
) -> Trace:
    """Run the file and record it.

    With call, the file is loaded as a module (its __main__ block doesn't run) and only the
    call, such as "dijkstra(G, 0)", is traced. Without it, the file runs as a script. With
    lines, only states on those lines are kept. After max_steps states the trace is marked
    truncated and the program carries on untraced. The program reads stdin as its input, never
    the terminal, so it can't stop and wait; sys.stdin.buffer works for fast reads.

    The file runs as `python path *args` would run it: sys.argv is [path, *args], and the
    file's folder comes first on sys.path, so it can import the files next to it. Both are put
    back afterwards, and the modules it imported from its folder are forgotten. With call, a
    sys.exit() while the file loads raises ExitedWhileLoading, since the call never ran.

    Whatever the program raises becomes the trace's error, even a BaseException such as
    asyncio's CancelledError. The result and the error are described after recording stops,
    so the program's own __repr__ or __str__ adds no steps.

    timeout is a time limit in seconds for the whole run, recorded or not (None for no limit).
    When it runs out, or on Ctrl+C, the program is stopped, and the trace keeps what was
    recorded, with "stopped" saying why. The time limit only works on the main thread.

    backend picks the event source; "auto" uses sys.monitoring when it can. Both record the
    same steps, so this only matters for testing and for working around a problem.
    """
    file = Path(path).resolve()
    text = file.read_text(encoding="utf-8")
    code = compile(text, str(file), "exec")
    name = "__main__" if call is None else "__runreel__"
    module = types.ModuleType(name)
    module.__file__ = str(file)
    recorder = _Recorder(str(file), lines, max_steps)
    source = open_source(recorder, backend)
    recorder.stop = source.stop
    deadline = Deadline(timeout, source.stop)
    recorder.check = deadline.check
    output = _Output(recorder)
    trace: Trace = {
        "schema": 1,
        "language": "python",
        "source": {"file": file.name, "text": text, "entry": call or ""},
        "steps": [],
    }
    saved = sys.modules.get(name)
    sys.modules[name] = module  # dataclasses and pickling look the module up by name
    saved_argv, saved_path, imported = sys.argv, sys.path[:], set(sys.modules)
    sys.argv = [str(path), *args]
    sys.path.insert(0, str(file.parent))
    try:
        # A stop from the deadline ends the with block early, and its exit swallows the stop.
        with contextlib.redirect_stdout(output), _input(stdin), deadline:
            entry = None
            if call is not None:
                try:
                    exec(code, module.__dict__)  # define the functions, untraced
                except SystemExit as exit:
                    raise ExitedWhileLoading(exit.code) from None
                entry = compile(call, "<runreel call>", "eval")
            source.start()
            returned: object = None
            failure: BaseException | None = None
            finished = False
            try:
                if entry is None:
                    exec(code, module.__dict__)
                else:
                    returned = eval(entry, module.__dict__)
                    finished = True
            except (TimeUp, KeyboardInterrupt):
                raise  # a stop, which the deadline's exit deals with
            except BaseException as error:
                failure = error
            finally:
                source.close()
            # Only now that recording has stopped can the program's __repr__ or __str__ run.
            if isinstance(failure, SystemExit):
                if failure.code not in (None, 0):
                    trace["error"] = f"SystemExit: {failure.code}"
            elif failure is not None:
                trace["error"] = _describe(failure)
            elif finished:
                trace["result"] = recorder.result(returned)
    finally:
        sys.argv = saved_argv
        sys.path[:] = saved_path
        _forget_imports(file.parent, imported)
        if saved is None:
            del sys.modules[name]
        else:
            sys.modules[name] = saved
    trace["steps"] = encode(recorder.states)
    if output.chunks:
        trace["stdout"] = output.chunks
    if recorder.truncated:
        trace["truncated"] = True
    if deadline.stopped:
        trace["stopped"] = deadline.stopped
    return trace


class ExitedWhileLoading(Exception):
    """The file called sys.exit() while it was loaded for a call, so the call never ran."""

    def __init__(self, code: object) -> None:
        super().__init__(f"exited while loading (sys.exit({'' if code is None else repr(code)}))")
        self.code = code


def _forget_imports(folder: Path, before: set[str]) -> None:
    """Forget the modules the program imported from its own folder, so the next run imports
    them afresh and they can't stand in for other modules of the same name. Only modules found
    in that folder itself go: a library that happens to live somewhere under it stays."""
    for name in set(sys.modules) - before:
        location = getattr(sys.modules.get(name), "__file__", None)
        if not location:
            continue
        found = Path(location).resolve()
        if found.parent == folder or found.is_relative_to(folder / name.partition(".")[0]):
            del sys.modules[name]


class _Recorder:
    def __init__(self, file: str, lines: Collection[int] | None, max_steps: int) -> None:
        self.file, self.max_steps = file, max_steps
        self.lines = None if lines is None else frozenset(lines)
        self.states: list[State] = []
        self.serializer = Serializer()
        self.truncated = False
        self.stop: Callable[[], None] = lambda: None  # set to the event source's stop()
        self.check: Callable[[], None] = lambda: None  # set to the deadline's check()
        self._fids: dict[int, int] = {}  # id() of a live frame -> its call id
        self._frames: dict[int, FrameType] = {}  # keeps those frames alive, so id() isn't reused
        self._next_fid = 1
        # call id -> the frame as last sent, and the objects its variables refer to
        self._kept: dict[int, tuple[Frame, list[object]]] = {}
        self._ran: set[int] = set()  # id() of each frame that has run since the last step

    def result(self, value: object) -> Value:
        """The call's return value. It is a heap object only if some state already showed it."""
        result = self.serializer.value(value)
        shown = self.states[-1]["heap"] if self.states else {}
        if isinstance(result, dict) and "ref" in result and result["ref"] not in shown:
            try:
                return repr(value)[:200]
            except Exception:
                return f"<{type(value).__name__} object>"  # its __repr__ failed
        return result

    def step(self, frame: FrameType, event: str, line: int, value: object = None) -> None:
        """Record the state as the event in frame happens at line. value is the returned
        value or the exception."""
        self.check()  # a stop that arrived while RunReel was busy lands here
        self._ran.add(id(frame))
        if self.lines is not None and line not in self.lines:
            self._ran.add(id(self._next_to_run(frame, event)))
            return
        if len(self.states) >= self.max_steps:
            self.truncated = True
            self.stop()
            return
        stack: list[FrameType] = []
        f: FrameType | None = frame
        while f is not None:
            if f.f_code.co_filename == self.file:
                stack.append(f)
            f = f.f_back
        frames = [self._frame(f, line if f is frame else f.f_lineno) for f in reversed(stack)]
        state: State = {"ev": cast(Event, event), "line": line, "stack": frames, "heap": {}}
        if event == "return":
            state["ret"] = self.serializer.value(value)
        elif event == "exception":
            state["exc"] = _describe(cast(BaseException, value))
        state["heap"] = self.serializer.heap()
        self.states.append(state)
        self._ran = {id(self._next_to_run(frame, event))}

    def done(self, frame: FrameType) -> None:
        """A call has returned or unwound: forget its frame, unless it can resume (a generator
        or coroutine keeps its call id from one resumption to the next)."""
        if not frame.f_code.co_flags & _RESUMABLE:
            fid = self._fids.pop(id(frame), 0)
            self._frames.pop(fid, None)
            self._kept.pop(fid, None)

    def _frame(self, f: FrameType, line: int) -> Frame:
        """f as a trace frame. One that hasn't run since it was last sent is sent again as it
        was, so a deep stack costs little per step: only a frame that runs can change its own
        variables, except a closure's, through its cells, and module level's, through global."""
        fid = self._fid(f)
        code = f.f_code
        kept = self._kept.get(fid)
        if (
            kept is not None
            and id(f) not in self._ran
            and not (code.co_cellvars or code.co_freevars)
            and code.co_name != "<module>"
        ):
            sent, objects = kept
            for x in objects:
                self.serializer.value(x)  # so this step's heap still has them
            return sent
        shown, objects = self._locals(f)
        sent = {"fid": fid, "fn": code.co_name, "line": line, "locals": shown}
        self._kept[fid] = (sent, objects)
        return sent

    def _next_to_run(self, frame: FrameType, event: str) -> FrameType | None:
        """The frame that runs on after this event: the same one, or after a return the nearest
        frame of the user's file below it."""
        if event != "return":
            return frame
        f = frame.f_back
        while f is not None and f.f_code.co_filename != self.file:
            f = f.f_back
        return f

    def _fid(self, frame: FrameType) -> int:
        fid = self._fids.get(id(frame))
        if fid is None:
            fid, self._next_fid = self._next_fid, self._next_fid + 1
            self._fids[id(frame)] = fid
            self._frames[fid] = frame
        return fid

    def _locals(self, frame: FrameType) -> tuple[dict[str, Value], list[object]]:
        """The frame's variables as trace values, and the objects among them."""
        top_level = frame.f_code.co_name == "<module>"
        shown: dict[str, Value] = {}
        objects: list[object] = []
        for name, value in frame.f_locals.items():
            if name.startswith(".") or (top_level and _hidden_at_top_level(name, value)):
                continue  # ".0" is a comprehension's hidden iterator
            shown[name] = sent = self.serializer.value(value)
            if isinstance(sent, dict) and "ref" in sent:
                objects.append(value)
        return shown, objects


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
    try:
        text = str(error)
    except Exception:
        text = ""  # its __str__ failed, so the type's name has to do
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
