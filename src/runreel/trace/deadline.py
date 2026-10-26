"""Stop the program when its time limit runs out or Ctrl+C is pressed, and keep the trace.

Both stops arrive as SIGINT, the signal Ctrl+C sends. When time runs out, a watchdog thread sends
SIGINT to the main thread, which also wakes a blocking call such as time.sleep(), and the handler
raises TimeUp into the program instead of KeyboardInterrupt. TimeUp is a BaseException, so
`except Exception` in the program can't swallow it. After the first stop lands, the program gets a
moment to run its finally blocks, and then the watchdog sends again until the run ends. A loop that
catches everything with a bare `except:` only stops when a send lands outside its try, which can
take a few seconds; on Python 3.10, which never handles a signal just before a try, it can't be
stopped at all (Ctrl+C can't stop it there either).

A stop is only raised in the program's code, never in RunReel's own. A signal that arrives while
RunReel is setting up, recording a step or capturing output is held, and raised at the program's
next step or by the next send. So a step is never left half recorded, and a signal that arrives
during setup or after the run can't escape as a stray KeyboardInterrupt.
"""

from __future__ import annotations

import _thread
import signal
import threading
import time
from collections.abc import Callable
from types import FrameType, TracebackType
from typing import Literal, NoReturn

Stop = Literal["timeout", "interrupt"]
POLL = 0.1  # seconds between the watchdog's checks
RESEND = 0.01  # seconds between sends once time is up, so a loop that catches TimeUp stops soon
GRACE = 1.0  # seconds a program gets, once its first stop has landed, before the next send


class TimeUp(BaseException):
    """Raised into the program when its time limit runs out."""


class Deadline:
    """The program's time limit, and what Ctrl+C does, for one run.

    Wrap the run in it: from the end of `with deadline:` to the start of its exit a stop can be
    raised into the program, and the exit swallows the stop, so the run's trace is kept. The
    recorder calls check() before each step, and stopped says how the program was stopped.

    Signals can only be handled on the main thread, so anywhere else (or without threads, as in
    Pyodide) there is no time limit, though a KeyboardInterrupt still ends the run cleanly.
    """

    def __init__(self, seconds: float | None, stop_recording: Callable[[], None]) -> None:
        self.seconds = seconds
        self.stop_recording = stop_recording
        self.stopped: Stop | None = None
        self.running = False  # inside the with block: the program's code may be running
        self.over = False  # the run has ended; a late signal is dropped
        self.timed_out = False
        self.held: type[BaseException] | None = None  # a stop waiting to land in the program
        self.armed = False
        self.sent = False
        self.landed: float | None = None  # when the first stop landed, by time.monotonic()
        self.handler = self.on_signal  # one bound method, so the watchdog can recognise it
        self.lock = threading.Lock()
        self.finished = threading.Event()
        self.main = threading.get_ident()

    def __enter__(self) -> Deadline:
        previous = signal.getsignal(signal.SIGINT)
        if previous is None:
            return self  # installed from C, so it couldn't be put back afterwards
        try:
            signal.signal(signal.SIGINT, self.handler)
        except ValueError:
            return self  # not the main thread
        self.previous = previous
        watchdog = threading.Thread(target=self.watch, name="runreel-deadline", daemon=True)
        try:
            watchdog.start()  # a signal now finds running False, so it is held
        except RuntimeError:  # no threads, as in Pyodide
            signal.signal(signal.SIGINT, self.previous)
        else:
            self.armed = True
        self.running = True
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self.running, self.over, self.held = False, True, None
        if self.armed:
            with self.lock:
                self.finished.set()  # the watchdog sends nothing from here on
            if self.sent:
                time.sleep(0.05)  # a signal still on its way lands while it is dropped
            signal.signal(signal.SIGINT, self.previous)
        if kind is not None and issubclass(kind, (TimeUp, KeyboardInterrupt)):
            self.stopped = self.stopped or "interrupt"  # Ctrl+C that came some other way
            return True
        return False

    def check(self) -> None:
        """Raise a held stop. The recorder calls this before each step."""
        if self.held is not None and self.running:
            self.deliver(self.held)

    def on_signal(self, signum: int, frame: FrameType | None) -> None:
        """The SIGINT handler: raise the stop in the program, or hold it until it can be."""
        if self.over:
            return
        stop = self.held or (TimeUp if self.timed_out else KeyboardInterrupt)
        if self.running and frame is not None and not _runreel(frame):
            self.deliver(stop)
        self.held = stop

    def deliver(self, stop: type[BaseException]) -> NoReturn:
        """Stop recording and raise the stop where the program is."""
        self.held = None
        if self.landed is None:
            self.landed = time.monotonic()
        self.stopped = self.stopped or ("timeout" if stop is TimeUp else "interrupt")
        self.stop_recording()
        if stop is TimeUp:
            raise TimeUp(f"the {self.seconds:g} s time limit ran out")
        raise stop

    def watch(self) -> None:
        """The watchdog thread: notice when time is up, then send SIGINT until the run ends."""
        end = None if self.seconds is None else time.monotonic() + self.seconds
        while not self.finished.wait(RESEND if self.timed_out else POLL):
            now = time.monotonic()
            if end is not None and now >= end:
                self.timed_out = True
            with self.lock:
                if self.finished.is_set() or not (self.timed_out or self.held):
                    continue
                if self.landed is not None and now - self.landed < GRACE:
                    continue  # let the finally blocks run
                if signal.getsignal(signal.SIGINT) is not self.handler:
                    continue  # the program installed its own handler: leave Ctrl+C to it
                self.sent = True
                if hasattr(signal, "pthread_kill"):
                    signal.pthread_kill(self.main, signal.SIGINT)  # wakes a blocking call too
                else:
                    _thread.interrupt_main()  # Windows


def _runreel(frame: FrameType) -> bool:
    """Whether frame is running RunReel's own code."""
    name = str(frame.f_globals.get("__name__"))
    return name == "runreel" or name.startswith("runreel.")
