from __future__ import annotations

import json
import sys
from pathlib import Path

from test_codec import canonical, load_states
from test_schema import VALIDATOR

from runreel.trace import State, Trace, dumps, iter_states
from runreel.trace.tracer import record

FIXTURES = Path(__file__).parent / "fixtures"


def states(trace: Trace) -> list[State]:
    return list(iter_states(trace["steps"]))


def program(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "prog.py"
    path.write_text(text, encoding="utf-8")
    return path


def test_reproduces_the_hand_written_reference_states() -> None:
    trace = record(FIXTURES / "front.py", "front([3, -1], [])")
    assert canonical(states(trace)) == canonical(load_states("sample-states.json"))
    assert trace["result"] == {"ref": 1}
    VALIDATOR.validate(json.loads(dumps(trace)))


def test_lines_keeps_only_the_selected_lines(tmp_path: Path) -> None:
    text = "def f(n):\n    s = 0\n    for i in range(n):\n        s += i\n    return s\n"
    trace = record(program(tmp_path, text), "f(3)", lines=range(3, 5))
    shown = [(s["ev"], s["line"]) for s in states(trace)]
    assert shown == [("line", 3), ("line", 4)] * 3 + [("line", 3)]
    assert trace["result"] == 3


def test_stops_recording_at_max_steps_but_finishes_the_run(tmp_path: Path) -> None:
    path = program(
        tmp_path, "def f():\n    n = 0\n    while n < 1000:\n        n += 1\n    return n\n"
    )
    trace = record(path, "f()", max_steps=10)
    assert len(trace["steps"]) == 10
    assert trace["truncated"] is True
    assert trace["result"] == 1000
    assert sys.gettrace() is None


def test_records_an_exception(tmp_path: Path) -> None:
    path = program(tmp_path, "def f(a):\n    return a[5]\n")
    trace = record(path, "f([1])")
    assert trace["error"] == "IndexError: list index out of range"
    assert "result" not in trace
    assert next(s for s in states(trace) if s["ev"] == "exception")["exc"] == trace["error"]


def test_captures_printed_text_with_its_step(tmp_path: Path) -> None:
    path = program(tmp_path, "def f():\n    x = 1\n    print('a', x)\n    print('b')\n")
    trace = record(path, "f()")
    lines = [s["line"] for s in states(trace)]
    assert trace["stdout"] == [[lines.index(3), "a 1\n"], [lines.index(4), "b\n"]]


def test_a_script_runs_as_main_and_hides_imports_and_functions(tmp_path: Path) -> None:
    text = (
        "import math\n\ndef sq(x):\n    return x * x\n\nif __name__ == '__main__':\n    r = sq(3)\n"
    )
    trace = record(program(tmp_path, text))
    last = states(trace)[-1]
    assert trace["source"]["entry"] == ""
    assert last["stack"][0]["fn"] == "<module>"
    assert last["stack"][0]["locals"] == {"r": 9}


def test_ids_survive_python_reusing_addresses(tmp_path: Path) -> None:
    # Each list dies before the next is made, so CPython may hand out the same address again.
    text = "def f():\n    for i in range(3):\n        x = [i]\n        del x\n"
    trace = record(program(tmp_path, text), "f()")
    lists = {oid for s in states(trace) for oid, obj in s["heap"].items() if obj["cls"] == "list"}
    assert len(lists) == 3


def test_the_program_reads_the_given_input(tmp_path: Path) -> None:
    lines = program(tmp_path, "n = int(input())\nm = int(input())\ntotal = n + m\n")
    assert states(record(lines, stdin="3\n4\n"))[-1]["stack"][0]["locals"]["total"] == 7
    fast = program(tmp_path, "import sys\ntotal = sum(map(int, sys.stdin.buffer.read().split()))\n")
    assert states(record(fast, stdin="3 4\n5\n"))[-1]["stack"][0]["locals"]["total"] == 12


def test_without_input_reading_fails_instead_of_waiting(tmp_path: Path) -> None:
    trace = record(program(tmp_path, "x = input()\n"))
    assert trace["error"] == "EOFError: EOF when reading a line"
