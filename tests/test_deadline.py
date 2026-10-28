"""The time limit and Ctrl+C. The tests that send signals run the recording in a Python of its
own, so a stray SIGINT or a run that never stops can't take the test session down with it."""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import textwrap
import threading
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import Any

import pytest

from runreel.trace import record
from runreel.trace.deadline import Deadline

BACKENDS = ["settrace"] + (["monitoring"] if sys.version_info >= (3, 12) else [])
posix = pytest.mark.skipif(not hasattr(signal, "pthread_kill"), reason="needs POSIX signals")

# Records argv[1] with --call argv[2] and the options in argv[3], then reports on the run and
# on whether everything the recording touched was put back.
RECORD = """
import json, signal, sys, time
from runreel.trace import iter_states, record

def clean():
    tools = [sys.monitoring.get_tool(t) for t in (3, 4)] if sys.version_info >= (3, 12) else []
    return (signal.getsignal(signal.SIGINT) is signal.default_int_handler
            and sys.gettrace() is None and not any(tools))

start = time.perf_counter()
trace = record(sys.argv[1], sys.argv[2] or None, **json.loads(sys.argv[3]))
took = time.perf_counter() - start
print(json.dumps({
    "stopped": trace.get("stopped"), "truncated": trace.get("truncated", False),
    "steps": len(trace["steps"]), "took": took, "stdout": trace.get("stdout", []),
    "error": trace.get("error"), "clean": clean(),
}))
"""


def run(tmp_path: Path, program: str, call: str | None = "f()", **options: Any) -> Any:
    path = tmp_path / "prog.py"
    path.write_text(textwrap.dedent(program), encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-c", RECORD, str(path), call or "", json.dumps(options)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


LOOP = """
def f():
    n = 0
    while True:
        n += 1
"""


@posix
@pytest.mark.parametrize("backend", BACKENDS)
def test_an_endless_loop_is_stopped_at_the_time_limit(tmp_path: Path, backend: str) -> None:
    report = run(tmp_path, LOOP, timeout=0.5, backend=backend)
    assert report["stopped"] == "timeout"
    assert report["truncated"] and report["steps"] == 5000  # it kept going after the step limit
    assert 0.5 <= report["took"] < 10
    assert report["error"] is None
    assert report["clean"]


@posix
@pytest.mark.parametrize("backend", BACKENDS)
def test_the_program_cant_swallow_the_stop_or_sleep_through_it(
    tmp_path: Path, backend: str
) -> None:
    program = """
    import time

    def f():
        while True:
            try:
                time.sleep(100)
            except Exception:
                pass
    """
    report = run(tmp_path, program, timeout=0.3, backend=backend)
    assert report["stopped"] == "timeout"
    assert report["took"] < 10
    assert report["clean"]


@posix
def test_a_loop_that_catches_everything_still_stops(tmp_path: Path) -> None:
    if sys.version_info < (3, 11):
        pytest.skip("Python 3.10 never handles a signal just before a try, so this loop can't stop")
    program = """
    def f():
        while True:
            try:
                for _ in range(10):
                    pass
            except:
                pass
    """
    report = run(tmp_path, program, timeout=0.3)
    assert report["stopped"] == "timeout"
    assert report["took"] < 40
    assert report["clean"]


@posix
def test_finally_blocks_run_and_their_output_is_kept(tmp_path: Path) -> None:
    program = """
    import time

    def f():
        try:
            while True:
                pass
        finally:
            time.sleep(0.3)  # tidying up takes a moment, and gets it
            print("cleaned up")
    """
    report = run(tmp_path, program, timeout=0.3)
    assert report["stopped"] == "timeout"
    assert [text for _, text in report["stdout"]] == ["cleaned up\n"]


@posix
@pytest.mark.parametrize("backend", BACKENDS)
def test_the_time_limit_can_cut_the_recording_short(tmp_path: Path, backend: str) -> None:
    report = run(tmp_path, LOOP, timeout=0.3, max_steps=10**7, backend=backend)
    assert report["stopped"] == "timeout"
    assert not report["truncated"] and report["steps"] > 0
    assert report["clean"]


@posix
@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("max_steps", [5000, 50])  # Ctrl+C while recording, and after
def test_ctrl_c_stops_the_run_and_keeps_the_trace(
    tmp_path: Path, backend: str, max_steps: int
) -> None:
    program = """
    import os, signal

    def f():
        n = 0
        while True:
            n += 1
            if n == 300:
                os.kill(os.getpid(), signal.SIGINT)  # what Ctrl+C in the terminal does
    """
    report = run(tmp_path, program, timeout=None, max_steps=max_steps, backend=backend)
    assert report["stopped"] == "interrupt"
    assert 0 < report["steps"] <= min(max_steps, 1000)
    assert report["clean"]


@posix
@pytest.mark.parametrize("backend", BACKENDS)
def test_a_file_stopped_while_loading_leaves_tracing_as_it_was(
    tmp_path: Path, backend: str
) -> None:
    path = tmp_path / "prog.py"
    path.write_text("while True:\n    pass\n\ndef f():\n    return 1\n")
    script = f"""
import json, sys
from runreel.trace import record

def outer(frame, event, arg):
    return None

sys.settrace(outer)  # a debugger or coverage, say
trace = record({str(path)!r}, "f()", timeout=0.3, backend={backend!r})
print(json.dumps([trace.get("stopped"), len(trace["steps"]), sys.gettrace() is outer]))
"""
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == ["timeout", 0, True]


@posix
def test_no_stray_interrupt_from_runs_that_end_right_at_the_time_limit() -> None:
    # Each run finishes just before or just after its time limit, which is when a signal can land
    # in RunReel's setup or teardown instead of the program, and escape as a KeyboardInterrupt.
    script = """
import signal, sys, tempfile, time
from pathlib import Path
from runreel.trace import record

source = "def f(n):\\n    s = 0\\n    for i in range(n):\\n        s += i\\n    return s\\n"
path = Path(tempfile.mkdtemp()) / "count.py"
path.write_text(source)
backends = ["settrace"] + (["monitoring"] if sys.version_info >= (3, 12) else [])
per_step = 1.0
for _ in range(3):  # time the recording itself, the fastest of three as the machine settles
    start = time.perf_counter()
    record(path, "f(300_000)", timeout=None, max_steps=20)
    per_step = min(per_step, (time.perf_counter() - start) / 300_000)
outcomes, strays = {}, 0
for i in range(30):
    # 0.03 to 0.5 s, around the limit, which lands between 0.1 and 0.2 s: wide enough that
    # some runs finish and some are stopped even if the timing above is off by a few times
    n = int(0.03 * (0.5 / 0.03) ** (i / 29) / per_step)
    backend = backends[i % len(backends)]
    try:
        trace = record(path, f"f({n})", timeout=0.1, max_steps=20, backend=backend)
        outcomes[trace.get("stopped")] = outcomes.get(trace.get("stopped"), 0) + 1
        for _ in range(100_000):
            pass  # a stray signal would land here
    except BaseException:
        strays += 1
restored = signal.getsignal(signal.SIGINT) is signal.default_int_handler
print(strays, restored, sorted(map(str, outcomes)))
"""
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr
    strays, restored, outcomes = done.stdout.split(" ", 2)
    assert (strays, restored) == ("0", "True")
    assert "None" in outcomes and "timeout" in outcomes  # runs ended on both sides of the limit


def raised(call: Callable[[], object]) -> str | None:
    """The stop that call raised, if any. Caught here, since a KeyboardInterrupt that got out
    would end the whole test session rather than fail one test."""
    try:
        call()
    except BaseException as stop:
        return type(stop).__name__
    return None


def test_a_stop_only_lands_in_the_programs_own_code() -> None:
    # The handler called directly, with frames from the program and from RunReel itself.
    recording: list[str] = []
    deadline = Deadline(1.0, lambda: recording.append("stopped"))
    runreel: dict[str, Any] = {"__name__": "runreel.trace.tracer"}
    exec("import sys\ndef frame():\n    return sys._getframe()\n", runreel)
    ours, program = runreel["frame"](), sys._getframe()

    def sigint(frame: FrameType) -> Callable[[], None]:
        return lambda: deadline.on_signal(signal.SIGINT, frame)

    assert raised(sigint(program)) is None  # still setting up: held
    deadline.running = True
    assert raised(sigint(ours)) is None  # RunReel is busy: still held
    assert deadline.held is KeyboardInterrupt and not recording
    assert raised(deadline.check) == "KeyboardInterrupt"  # the program's next step
    assert recording == ["stopped"] and deadline.stopped == "interrupt" and deadline.held is None

    deadline.timed_out = True
    assert raised(sigint(program)) == "TimeUp"  # in the program: lands at once
    assert deadline.stopped == "interrupt"  # the first stop is the one reported

    deadline.running, deadline.over = False, True
    assert raised(sigint(program)) is None  # the run is over: dropped
    assert deadline.held is None


def test_off_the_main_thread_there_is_no_time_limit(tmp_path: Path) -> None:
    path = tmp_path / "prog.py"
    path.write_text("def f():\n    return sum(range(10))\n")
    handler = signal.getsignal(signal.SIGINT)
    traces: list[Any] = []
    thread = threading.Thread(target=lambda: traces.append(record(path, "f()", timeout=0.1)))
    thread.start()
    thread.join()
    assert traces[0]["result"] == 45 and "stopped" not in traces[0]
    assert signal.getsignal(signal.SIGINT) is handler


def test_a_handler_the_program_installs_is_undone(tmp_path: Path) -> None:
    path = tmp_path / "prog.py"
    path.write_text("import signal\n\ndef f():\n    signal.signal(signal.SIGINT, signal.SIG_IGN)\n")
    handler = signal.getsignal(signal.SIGINT)
    trace = record(path, "f()")
    assert "stopped" not in trace and "error" not in trace
    assert signal.getsignal(signal.SIGINT) is handler
