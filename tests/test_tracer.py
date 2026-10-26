from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from test_codec import canonical, load_states
from test_schema import VALIDATOR

from runreel.trace import State, Trace, dumps, iter_states
from runreel.trace.tracer import ExitedWhileLoading, record

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


def test_runs_the_file_the_way_python_does(tmp_path: Path) -> None:
    # Its folder comes first on sys.path and sys.argv is the file and its arguments, then
    # both are put back, and the module it imported from its folder is forgotten.
    (tmp_path / "helper.py").write_text("def twice(x):\n    return 2 * x\n")
    path = program(tmp_path, "import sys\nimport helper\n\nprint(sys.argv, helper.twice(21))\n")
    argv, search = sys.argv[:], sys.path[:]
    trace = record(path, args=["--n", "5"])
    assert "".join(text for _, text in trace.get("stdout", [])) == f"{[str(path), '--n', '5']} 42\n"
    assert "error" not in trace
    assert sys.argv == argv and sys.path == search
    assert "helper" not in sys.modules


def test_a_call_can_use_the_files_next_to_it(tmp_path: Path) -> None:
    (tmp_path / "helper.py").write_text("SCALE = 3\n")
    path = program(tmp_path, "import helper\n\ndef f(x):\n    return x * helper.SCALE\n")
    assert record(path, "f(2)")["result"] == 6
    assert "helper" not in sys.modules


def test_only_the_programs_own_modules_are_forgotten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "helper.py").write_text("")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "part.py").write_text("")
    site = tmp_path / "venv" / "site-packages"  # a library that happens to live under the folder
    site.mkdir(parents=True)
    (site / "library.py").write_text("")
    monkeypatch.syspath_prepend(str(site))
    try:
        record(program(tmp_path, "import helper, library, pkg.part\n"))
        assert {"helper", "pkg", "pkg.part"}.isdisjoint(sys.modules)
        assert "library" in sys.modules
    finally:
        sys.modules.pop("library", None)


def test_exiting_while_the_file_loads_for_a_call_is_an_error(tmp_path: Path) -> None:
    path = program(tmp_path, "import sys\nsys.exit(3)\n\ndef f():\n    return 1\n")
    with pytest.raises(ExitedWhileLoading, match=r"exited while loading \(sys\.exit\(3\)\)"):
        record(path, "f()")


def test_anything_the_program_raises_is_its_error(tmp_path: Path) -> None:
    path = program(
        tmp_path,
        "import asyncio\n\nclass Abort(BaseException):\n    pass\n\n"
        "def f(error):\n    raise error\n",
    )
    assert record(path, "f(Abort('given up'))")["error"] == "Abort: given up"
    trace = record(path, "f(asyncio.CancelledError())")
    assert trace["error"] == "CancelledError" and "stopped" not in trace


def test_the_result_and_error_are_described_after_recording_stops(tmp_path: Path) -> None:
    # So the program's own __repr__ and __str__ add no steps, and a broken one falls back.
    path = program(
        tmp_path,
        "class Shown:\n    def __repr__(self):\n        return 'shown'\n\n"
        "class Broken:\n    def __repr__(self):\n        raise ValueError\n\n"
        "class Oops(Exception):\n    def __str__(self):\n        return 'oops'\n\n"
        "class Mute(Exception):\n    def __str__(self):\n        raise ValueError\n\n"
        "def nothing():\n    return None\n\n"
        "def fail(error):\n    raise error\n",
    )
    shown, broken = record(path, "nothing() or Shown()"), record(path, "nothing() or Broken()")
    oops, mute = record(path, "fail(Oops())"), record(path, "fail(Mute())")
    assert (shown["result"], broken["result"]) == ("shown", "<Broken object>")
    assert (oops["error"], mute["error"]) == ("Oops: oops", "Mute")
    for trace in (shown, broken, oops, mute):
        called = {frame["fn"] for state in states(trace) for frame in state["stack"]}
        assert called <= {"nothing", "fail"}


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


def test_recording_the_same_program_twice_gives_the_same_trace(tmp_path: Path) -> None:
    # A lambda and a generator kept in variables: their printed forms would otherwise carry
    # memory addresses, which change from run to run.
    text = (
        "def make():\n"
        "    return lambda x: x + 1\n"
        "\n"
        "def numbers():\n"
        "    yield 1\n"
        "\n"
        "def main():\n"
        "    add = make()\n"
        "    gen = numbers()\n"
        "    first = next(gen)\n"
        "    return add(first)\n"
    )
    path = program(tmp_path, text)
    first, second = dumps(record(path, "main()")), dumps(record(path, "main()"))
    assert " at 0x" not in first
    assert "<function make.<locals>.<lambda>>" in first and "<generator object numbers>" in first
    assert first == second
