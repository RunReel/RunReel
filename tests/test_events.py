from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from runreel.trace import State, Trace, iter_states, record

ROOT = Path(__file__).parent.parent
PROGRAMS = Path(__file__).parent / "fixtures" / "programs"
SEARCH = (ROOT / "examples" / "binary_search.py", "binary_search([1, 3, 4, 7, 9, 11, 15], 9)")

# Programs that exercise every kind of event: generators (send, throw, close, yield from),
# exceptions caught, re-raised and escaping, methods called from C, one-line loops,
# comprehensions, asyncio, a second thread, a script reading input, and both filters.
CASES: dict[str, tuple[Path, str | None, dict[str, Any]]] = {
    "binary search": (*SEARCH, {}),
    "BST insert": (ROOT / "examples" / "bst_insert.py", "build([5, 3, 8, 1, 4])", {}),
    "Dijkstra": (ROOT / "examples" / "dijkstra.py", "dijkstra(G, 0)", {}),
    "reference sample": (ROOT / "tests" / "fixtures" / "front.py", "front([3, -1], [])", {}),
    "generators": (PROGRAMS / "generators.py", "main()", {}),
    "errors": (PROGRAMS / "errors.py", "main()", {}),
    "objects": (PROGRAMS / "objects.py", "main()", {}),
    "loops": (PROGRAMS / "loops.py", "main()", {}),
    "asyncio": (PROGRAMS / "tasks.py", "main()", {}),
    "threads": (PROGRAMS / "threads.py", "main()", {}),
    "script": (PROGRAMS / "script.py", None, {"stdin": "2\n7 3 9\n"}),
    "truncated": (ROOT / "examples" / "dijkstra.py", "dijkstra(G, 0)", {"max_steps": 20}),
    "selected lines": (*SEARCH, {"lines": range(3, 5)}),
}


def states(trace: Trace) -> list[State]:
    return list(iter_states(trace["steps"]))


@pytest.mark.parametrize("name", CASES)
def test_both_backends_record_the_same_steps(name: str) -> None:
    if sys.version_info < (3, 12):
        pytest.skip("sys.monitoring needs Python 3.12+")
    path, call, options = CASES[name]
    by_settrace = record(path, call, backend="settrace", **options)
    by_monitoring = record(path, call, backend="monitoring", **options)
    assert comparable(by_monitoring) == comparable(by_settrace)


def comparable(trace: Trace) -> str:
    # Printed forms of functions include memory addresses, which differ between runs.
    return re.sub(r" at 0x[0-9a-f]+", " at 0x…", json.dumps(trace, sort_keys=True))


def test_the_corpus_really_exercises_the_events() -> None:
    errors = record(PROGRAMS / "errors.py", "main()")
    assert errors["error"] == "ValueError: negative: -9"
    assert sum(s["ev"] == "exception" for s in states(errors)) >= 4
    generators = states(record(PROGRAMS / "generators.py", "main()"))
    resumed = [s for s in generators if s["ev"] == "call" and s["stack"][-1]["fn"] == "count_up"]
    assert len(resumed) > 5  # every resumption after a yield is a call
    loops = [s["line"] for s in states(record(PROGRAMS / "loops.py", "main()"))]
    assert loops.count(3) == 4 and loops.count(5) >= 3  # one-line loops: a step per pass


def test_only_the_recording_thread_is_recorded() -> None:
    trace = record(PROGRAMS / "threads.py", "main()")
    names = {frame["fn"] for state in states(trace) for frame in state["stack"]}
    assert names == {"main", "start", "finish"}  # never "work", which runs in the other thread


def test_monitoring_is_used_when_available_and_cleaned_up(tmp_path: Path) -> None:
    if sys.version_info < (3, 12):
        pytest.skip("sys.monitoring needs Python 3.12+")
    else:
        program = tmp_path / "probe.py"
        program.write_text(
            "import sys\n\ndef tool():\n"
            "    return sys.monitoring.get_tool(3) or sys.monitoring.get_tool(4)\n"
        )
        before = [sys.monitoring.get_tool(t) for t in range(6)]
        assert record(program, "tool()")["result"] == "runreel"
        assert [sys.monitoring.get_tool(t) for t in range(6)] == before


def test_settrace_takes_over_when_no_tool_id_is_free() -> None:
    if sys.version_info < (3, 12):
        pytest.skip("sys.monitoring needs Python 3.12+")
    else:
        expected = record(*SEARCH)
        for tool in (3, 4):
            sys.monitoring.use_tool_id(tool, "someone else")
        try:
            assert record(*SEARCH) == expected
            with pytest.raises(RuntimeError, match=r"no free sys\.monitoring tool id"):
                record(*SEARCH, backend="monitoring")
        finally:
            for tool in (3, 4):
                sys.monitoring.free_tool_id(tool)


def test_the_monitoring_backend_needs_python_3_12() -> None:
    if sys.version_info >= (3, 12):
        pytest.skip("only older Pythons lack sys.monitoring")
    with pytest.raises(ValueError, match=r"3\.12"):
        record(*SEARCH, backend="monitoring")


def test_an_unknown_backend_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown backend"):
        record(*SEARCH, backend="fast")  # type: ignore[arg-type]


def test_a_tracer_that_was_already_running_is_restored() -> None:
    def other(frame: object, event: str, arg: object) -> None:
        return None

    sys.settrace(other)
    try:
        record(*SEARCH, backend="settrace")
        assert sys.gettrace() is other
        record(*SEARCH)  # sys.monitoring on 3.12+, which leaves sys.settrace alone
        assert sys.gettrace() is other
    finally:
        sys.settrace(None)
