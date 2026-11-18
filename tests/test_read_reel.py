"""skills/reel/scripts/read_reel.py, which prints a reel as text for an agent that can't
watch it: it rebuilds each step as the player does, says how a run ended and which lines ran,
lists the steps with their links and what they printed, and turns what it can't read into one
line."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from hypothesis import given
from hypothesis import strategies as st
from strategies import state_sequences

from runreel.reel import write_reel
from runreel.trace import State, encode, iter_states, record

ROOT = Path(__file__).parent.parent
READ_REEL = ROOT / "skills" / "reel" / "scripts" / "read_reel.py"
GOLDEN = Path(__file__).parent / "fixtures" / "golden"


def test_read_reel_needs_only_python_3_8_and_the_standard_library() -> None:
    tree = ast.parse(READ_REEL.read_text(encoding="utf-8"), feature_version=(3, 8))
    imported = {
        name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for name in (
            [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
        )
    }
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported


def read_reel() -> ModuleType:
    spec = importlib.util.spec_from_file_location("read_reel", READ_REEL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode, before = True, sys.dont_write_bytecode  # keep the skill folder clean
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


@pytest.mark.parametrize("golden", sorted(GOLDEN.glob("*/*.json")), ids=lambda p: p.stem)
def test_read_reel_rebuilds_each_state_as_runreel_does(golden: Path) -> None:
    steps = json.loads(golden.read_text(encoding="utf-8"))["steps"]
    rebuilt = [json.loads(json.dumps(state)) for state in read_reel().states(steps)]
    expected = [json.loads(json.dumps(state)) for state in iter_states(steps)]
    assert rebuilt == expected


@given(state_sequences(), st.integers(min_value=1, max_value=6))
def test_read_reel_decodes_any_run_as_runreel_does(states: list[State], key_every: int) -> None:
    """Random runs reach the edits real examples rarely make: several at once, deleted
    variables and fields, items past the size cap, keyframes."""
    steps = json.loads(json.dumps(encode(states, key_every=key_every)))
    rebuilt = [json.dumps(state, sort_keys=True) for state in read_reel().states(steps)]
    assert rebuilt == [json.dumps(state, sort_keys=True) for state in iter_states(steps)]


EDITS = """\
def edits():
    a = list(range(20))
    a.insert(1, -1); a.pop()
    b = list(range(201))
    b.pop()
    return len(a) + len(b)
"""


def test_read_reel_applies_several_edits_and_the_size_cap_as_runreel_does(tmp_path: Path) -> None:
    (tmp_path / "edits.py").write_text(EDITS)
    steps = json.loads(json.dumps(record(tmp_path / "edits.py", "edits()")["steps"]))
    patches = [entry for step in steps for entry in step.get("heap", {}).values()]
    assert any(len(patch.get("ops", [])) >= 2 for patch in patches)  # an insert and a pop
    assert any(patch.get("more") == 0 for patch in patches)  # back under the 200 items shown
    rebuilt = [json.dumps(state, sort_keys=True) for state in read_reel().states(steps)]
    assert rebuilt == [json.dumps(state, sort_keys=True) for state in iter_states(steps)]


PROGRAM = """\
def total(xs):
    s = 0
    for x in xs:
        s += x
    print("sum", s)
    return s
"""


@pytest.fixture
def reel(tmp_path: Path) -> Path:
    (tmp_path / "add.py").write_text(PROGRAM)
    trace = record(tmp_path / "add.py", "total([1, 2, 3])")
    return write_reel(trace, tmp_path / "add.reel.html", player="")


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(READ_REEL), *args], capture_output=True, text=True, check=False
    )


def rows(listing: str) -> list[str]:
    """The lines of a --steps listing after its column headings."""
    lines = listing.splitlines()
    return lines[
        next(i for i, line in enumerate(lines) if line.split()[:2] == ["step", "link"]) + 1 :
    ]


def test_read_reel_says_how_the_run_ended_and_which_lines_ran(reel: Path) -> None:
    done = run(str(reel))
    assert done.returncode == 0, done.stderr
    assert "records the call total([1, 2, 3]) in add.py" in done.stdout
    assert reel.resolve().as_uri() in done.stdout
    assert "steps · result 6" in done.stdout
    assert "It printed:\nsum 6\n" in done.stdout
    assert ">    3     4      for x in xs:" in done.stdout  # three items, then the end of them
    assert ">    4     3          s += x" in done.stdout


def test_read_reel_lists_the_steps(reel: Path) -> None:
    done = run(str(reel), "--steps")
    assert done.returncode == 0, done.stderr
    listed = rows(done.stdout)
    assert listed[0].split()[:3] == ["1", "0", "1"]
    assert any("prints 'sum 6\\n'" in row for row in listed)
    assert listed[-1] == "The reel ends here: 12 steps · result 6"
    some = rows(run(str(reel), "--steps", "2-3").stdout)
    assert [row.split()[0] for row in some[:-1]] == ["2", "3"]
    assert some[-1] == "… 9 more steps: list them with --steps 4-12"
    assert (
        rows(run(str(reel), "--steps", "1-11").stdout)[-1]
        == "… 1 more step: list it with --steps 12"
    )
    assert run(str(reel), "--printed").stdout == "sum 6\n"


LINES = """\
def helper(xs, k):
    xs.append(k)
    return len(xs)


def outer(n):
    xs = []
    for k in range(n):
        helper(xs, k)
    return xs
"""


def test_read_reel_notices_a_reel_recorded_with_lines(tmp_path: Path) -> None:
    """--lines isn't in the trace, but a call starting mid-way or a run ending on a line
    shows it."""
    (tmp_path / "lines.py").write_text(LINES)
    for lines in [{2}, {1, 2}]:
        trace = record(tmp_path / "lines.py", "outer(3)", lines=lines)
        reel = write_reel(trace, tmp_path / "lines.reel.html", player="")
        assert "recorded with --lines" in run(str(reel)).stdout, lines


def test_read_reel_reports_unwritable_output_and_odd_pages(tmp_path: Path, reel: Path) -> None:
    if os.name == "posix":  # >&- closes the output
        command = f"{shlex.quote(sys.executable)} {shlex.quote(str(READ_REEL))} {reel} >&-"
        closed = subprocess.run(command, shell=True, capture_output=True, text=True, check=False)
        assert closed.returncode == 1 and "Traceback" not in closed.stderr
    page = reel.read_text(encoding="utf-8")
    deep = tmp_path / "deep.html"
    deep.write_text(
        page.replace('"steps":', '"deep":' + "[" * 100_000 + "]" * 100_000 + ',"steps":', 1)
    )
    done = run(str(deep))
    assert done.returncode == 1 and "damaged" in done.stderr and "Traceback" not in done.stderr
    texty = tmp_path / "texty.html"
    texty.write_text(page.replace('"schema":1', '"schema":"1"', 1))
    assert "damaged" in run(str(texty)).stderr
    cut = tmp_path / "cut.html"
    cut.write_text(page[: page.index("</script>") + len("</script>")])
    done = run(str(cut))
    assert done.returncode == 0 and "won't play" in done.stderr
    if Path("/dev/full").exists():
        with Path("/dev/full").open("w") as full:
            done = subprocess.run(
                [sys.executable, str(READ_REEL), str(reel)],
                stdout=full,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        assert done.returncode == 1 and "can't write the output" in done.stderr
        assert "Traceback" not in done.stderr


def test_read_reel_numbers_lines_as_python_does(tmp_path: Path) -> None:
    """A form feed, allowed between functions, doesn't start a new line for Python."""
    (tmp_path / "ff.py").write_text("def f(x):\n    return x\n\x0c\ndef g(x):\n    return f(x)\n")
    reel = write_reel(record(tmp_path / "ff.py", "g(1)"), tmp_path / "ff.reel.html", player="")
    assert ">    5     2      return f(x)" in run(str(reel)).stdout


def test_read_reel_handles_damage_long_output_and_mistyped_options(
    tmp_path: Path, reel: Path
) -> None:
    page = reel.read_text(encoding="utf-8")
    cut = tmp_path / "cut.reel.html"
    cut.write_text(page[: page.index("</script>")])
    done = run(str(cut))
    assert done.returncode == 1 and "is cut short" in done.stderr
    broken = tmp_path / "broken.reel.html"
    broken.write_text(page.replace('"frames":{"1"', '"frames":{"99"', 1))
    done = run(str(broken), "--steps")
    assert done.returncode == 1 and "damaged" in done.stderr and "Traceback" not in done.stderr
    assert run("--steps", str(reel)).returncode == 0  # the path taken as the range
    assert run(str(reel), "--steps", "--printed").returncode == 2  # one or the other
    (tmp_path / "spin.py").write_text(
        "def spin(n):\n    t = 0\n    for i in range(n):\n        t += i\n    return t\n"
    )
    long = write_reel(record(tmp_path / "spin.py", "spin(2000)"), tmp_path / "spin.html", player="")
    reader = subprocess.Popen(
        [sys.executable, str(READ_REEL), str(long), "--steps", "1-5000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert reader.stdout and reader.stderr
    reader.stdout.read(100)
    reader.stdout.close()  # as head does once it has its lines
    assert reader.wait() == 0 and b"Traceback" not in reader.stderr.read()


def test_read_reel_refuses_what_it_cant_read(tmp_path: Path, reel: Path) -> None:
    page = tmp_path / "page.html"
    page.write_text("<html></html>")
    done = run(str(page))
    assert done.returncode == 1 and "isn't a RunReel reel" in done.stderr
    assert run(str(reel), "--steps", "5-2").returncode == 2
    assert run(str(reel), "--steps", "999").returncode == 2
