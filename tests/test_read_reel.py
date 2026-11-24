"""skills/reel/scripts/read_reel.py, which prints a reel as text for an agent that can't
watch it: it rebuilds each step as the player does, says how a run ended and which lines ran,
lists the steps with what changed at each, and turns what it can't read into one line."""

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
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from strategies import state_sequences

from runreel.reel import write_reel
from runreel.trace import State, encode, iter_states, record
from runreel.trace.model import Event, Frame, Source, Trace
from runreel.trace.serialize import MAX_OBJECTS

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
    assert listed[0].split()[:3] == ["1", "0", "1"] and "call total(xs=[1, 2, 3])" in listed[0]
    assert any("s=6" in row for row in listed)
    assert any("prints 'sum 6\\n'" in row for row in listed)
    assert "returns 6" in listed[-2]
    assert listed[-1] == "The reel ends here: 12 steps · result 6"
    some = rows(run(str(reel), "--steps", "2-3").stdout)
    assert [row.split()[0] for row in some[:-1]] == ["2", "3"]
    assert some[-1] == "… 9 more steps: list them with --steps 4-12"
    assert (
        rows(run(str(reel), "--steps", "1-11").stdout)[-1]
        == "… 1 more step: list it with --steps 12"
    )
    assert run(str(reel), "--printed").stdout == "sum 6\n"


CHANGES = """\
def changes(n):
    dp = [[0, 0], [0, 0]]
    dist = {0: 0}
    seen = set()
    out = []
    for i in range(1, n):
        dp[i][i - 1] = 5
        dist[i] = 7
        seen.add(i)
        out.append(9)
    del dist[0]
    out = sorted(out)
    return out
"""


def test_read_reel_names_the_items_that_changed(tmp_path: Path) -> None:
    """A change in place names the item, so a table filling up can be followed; a name bound
    to a new object shows the object."""
    (tmp_path / "changes.py").write_text(CHANGES)
    trace = record(tmp_path / "changes.py", "changes(2)")
    reel = write_reel(trace, tmp_path / "changes.reel.html", player="")
    # The changes column starts after the step, link, line and code columns.
    changed = ", ".join(row[54:] for row in rows(run(str(reel), "--steps").stdout))
    for note in [
        "dp[1][0]=5",
        "dist[1]=7",
        "seen |= {1}",
        "out.append(9)",
        "del dist[0]",
        "out=[9]",
    ]:
        assert note in changed, note


SCRIPT = """\
total = 0


class Node:
    def __init__(self, val, next=None):
        self.val = val
        self.next = next


def fill(a, i):
    if i == len(a):
        return a
    a[i] = i * i
    return fill(a, i + 1)


def evens(n):
    for i in range(n):
        if i % 2 == 0:
            yield i


def check(x):
    if x < 0:
        raise ValueError("negative")
    return x


def bump():
    global total
    total += 1


def main():
    fill([0, 0, 0], 0)
    out = list(evens(4))
    try:
        check(-1)
    except ValueError:
        pass
    head = Node(1, Node(2, Node(3, Node(4))))
    head.next.next.next.val = 40
    seen = set(range(60))
    seen.add(100)
    bump()
    return out


main()
"""


def test_read_reel_says_what_each_step_did_where_it_did_it(tmp_path: Path) -> None:
    """Each change shows once, at the step that made it, however deep it is or whichever
    call made it, and calls, yields, exceptions and class bodies are told apart."""
    (tmp_path / "script.py").write_text(SCRIPT)
    reel = write_reel(record(tmp_path / "script.py"), tmp_path / "script.reel.html", player="")
    listing = run(str(reel), "--steps", "1-5000").stdout
    changed = "\n".join(row[54:] for row in rows(listing))
    assert "runs the body of class Node" in changed and "__module__" not in changed
    assert changed.count("a[1]=1") == 1 and changed.count("a[2]=4") == 1  # not again on return
    assert "yields 0" in changed and "resumes evens" in changed and "yields 2" in changed
    assert "leaves because of the exception" in changed
    assert "head.next.next.next.val=40" in changed
    assert "seen |= {100}" in changed and "seen -=" not in changed  # 61 items, all kept
    assert "total=1 (in <module>)" in changed


NARRATED = """\
from collections import OrderedDict

KEEP = []


def register(cls):
    return cls


@register
class Shape:
    side = 1

    def __init__(self, side):
        self.side = side


def count():
    i = 0
    while True:
        got = yield i
        i += 1


def letters():
    yield "a"
    yield "b"


def inner():
    yield 1


def outer():
    yield from inner()


def risky(xs):
    try:
        return xs[5]
    finally:
        xs.append(0)


def fib(n):
    calls = 0

    def go(k):
        nonlocal calls
        calls += 1
        return k if k < 2 else go(k - 1) + go(k - 2)

    return go(n), calls


def take(xs, ys, last):
    return len(xs) + len(ys) + last


def main():
    dp = [[0] * 3] * 4
    dp[1][1] = 5
    a = [6, 5, 4, 3, 2, 1]
    a.sort()
    b = sorted(a)
    flags = [0, 0]
    flags[0] = False
    d = {1: 10, 2: 20}
    d[1] = d.pop(1)
    od = OrderedDict(d)
    od.move_to_end(2)
    big = list(range(1000))
    big.append(1)
    stack = [1, 2]
    g = count()
    next(g)
    g.send(stack.pop())
    h = letters()
    KEEP.append(h)
    first = next(h)
    total = take(list(range(30)), list(range(30)), stack.pop())
    out = list(outer())
    try:
        risky([1])
    except IndexError:
        pass
    shape = Shape(2)
    return fib(3)


main()
"""


def test_read_reel_tells_apart_what_looks_alike(tmp_path: Path) -> None:
    """Rows that are one list, a list changed in place or replaced, False and 0, a dict's
    keys moving, a generator resumed or never resumed, an exception leaving through finally,
    a yield from ending, a decorated class and a closure's shared variable."""
    (tmp_path / "narrated.py").write_text(NARRATED)
    trace = record(tmp_path / "narrated.py")
    reel = write_reel(trace, tmp_path / "narrated.reel.html", player="")
    listing = run(str(reel), "--steps", "1-5000").stdout
    changed = "\n".join(row[54:] for row in rows(listing))
    for note in [
        "dp=[[0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]] (dp[0], dp[1], dp[2] and 1 more are",
        "dp[0][1]=5, dp[1][1]=5, dp[2][1]=5 (dp[0], dp[1], dp[2] and 1 more are the same list)",
        "a[:]=[1, 2, 3, 4, 5, 6]",
        "b=[1, 2, 3, 4, 5, 6]",
        "flags[0]=False",
        "d[1] moved to the end",
        "od.move_to_end(2)",
        "len(big)=1001",
        "resumes count, del stack[1] (in main)",
        "yields 'a'",  # never resumed, so it stays a yield
        "xs.append(0), leaves because of the exception",  # through the finally block
        "runs the body of class Shape",
        "__init__=<function Shape.__init__>",
        "call go(k=3)",
    ]:
        assert note in changed, note
    assert "returns 'a'" not in changed and "raises StopIteration" not in changed
    assert "__module__" not in changed
    assert any("call take(" in row and "del stack[0] (in main)" in row for row in rows(listing))
    assert "(in fib)" not in changed  # calls shows once, for the running call
    assert listing.count("calls=1") == 1


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
    shows it; a call first seen mid-way shows its variables."""
    (tmp_path / "lines.py").write_text(LINES)
    for lines in [{2}, {1, 2}]:
        trace = record(tmp_path / "lines.py", "outer(3)", lines=lines)
        reel = write_reel(trace, tmp_path / "lines.reel.html", player="")
        assert "recorded with --lines" in run(str(reel)).stdout, lines
    first = rows(run(str(reel), "--steps").stdout)[0]
    assert "call helper(xs=[], k=0)" in first
    trace = record(tmp_path / "lines.py", "outer(3)", lines={2})
    reel = write_reel(trace, tmp_path / "lines.reel.html", player="")
    assert "in helper, xs=[], k=0" in rows(run(str(reel), "--steps").stdout)[0]


HIDDEN = {"t": "repr", "cls": "list", "v": f"(not shown: over {MAX_OBJECTS} objects)"}


def test_read_reel_skips_objects_coming_into_view_past_the_cap(tmp_path: Path) -> None:
    """Past the object cap an object is a placeholder at some steps and itself at others,
    which is no change; a real change involving one still shows, with … for it, even as a
    set's item or a dict's key."""

    def state(ev: Event, line: int, heap: dict[int, Any]) -> State:
        frame: Frame = {"fid": 1, "fn": "f", "line": line, "locals": {"xs": {"ref": 1}}}
        frame["locals"].update({"d": {"ref": 3}, "s": {"ref": 5}})
        return {"ev": ev, "line": line, "stack": [frame], "heap": heap}

    xs = {"t": "seq", "cls": "list", "items": [{"ref": 2}]}
    before = {"t": "seq", "cls": "set", "items": [{"ref": 6}]}
    states = [
        state(
            "call",
            1,
            {1: xs, 2: HIDDEN, 3: {"t": "map", "cls": "dict", "items": []}, 5: before, 6: HIDDEN},
        ),
        state(
            "line",
            2,
            {
                1: xs,
                2: {"t": "seq", "cls": "list", "items": [5]},
                3: {"t": "map", "cls": "dict", "items": [[1, {"ref": 4}]]},
                4: HIDDEN,
                5: {"t": "seq", "cls": "set", "items": [{"ref": 6}, {"ref": 7}]},
                6: HIDDEN,
                7: HIDDEN,
            },
        ),
    ]
    source: Source = {"file": "f.py", "text": "def f(xs, d):\n    d[1] = []\n", "entry": "f()"}
    trace: Trace = {"schema": 1, "language": "python", "source": source, "steps": encode(states)}
    reel = write_reel(trace, tmp_path / "hidden.reel.html", player="")
    second = rows(run(str(reel), "--steps").stdout)[1]
    assert second[54:] == "d[1]=…, s |= {…}"


def test_read_reel_reads_code_newer_than_its_python() -> None:
    """A file this Python can't parse is read from its tokens, leaving strings and comments
    out, and past where those fail, from its text."""
    newer = (
        "@deco\n"
        "def f(a, b=g(1, c), *args, k: list[int] = [], **kw):\n"
        '    yield "yield"  # yield\n'
        "    h = lambda q, r=1: q\n"
        "    return a +\n"
    )
    source = read_reel().Source(newer)
    assert not source.parsed
    assert source.parameters(1, "f") == source.parameters(2, "f") == {"a", "b", "args", "k", "kw"}
    assert source.parameters(4, "<lambda>") == {"q", "r"}
    assert source.yields_on(3, "") == 1 and not source.yields_on(4, "")
    text = read_reel().Source("match = (\n")
    assert not text.parsed and text.parameters(1, "f") is None
    assert text.yields_on(3, "    got = yield i") and text.hands_over_on(4, "await job()")
    assert not text.yields_on(5, "    return yield_count") and not text.yields_on(6, "s = 'yield'")


FLOW = """\
import asyncio
from contextlib import suppress

KEEP = []


class Node:
    def __init__(self, val, next=None):
        self.val = val
        self.next = next


def counted(n):
    for i in range(n):
        yield i
    return n


async def ticks(n):
    for i in range(n):
        await asyncio.sleep(0)
        yield i * 10


async def consume():
    got = [v async for v in ticks(2)]
    lock = asyncio.Lock()
    async with lock:
        got.append(1)
    return got


def drop(d):
    with suppress(KeyError): del d["x"]


def closer():
    try:
        yield 1
    finally:
        print("closed")


def two():
    yield 1; yield 2


def reverse(head):
    prev, cur = None, head
    while cur:
        cur.next, prev, cur = prev, cur, cur.next
    return prev


def main():
    out = [v for v in counted(2)]
    for v in counted(2):
        out.append(v)
    squares = [x * x for x in range(3)]
    drop({})
    head = reverse(Node(1, Node(2)))
    c = closer()
    next(c)
    c.close()
    t = two()
    KEEP.append(t)
    next(t)
    next(t)
    k = 5
    f, g = (lambda a: a + k), (lambda b: b + k)
    f(1), g(2)
    return asyncio.run(consume()), out, squares, head.val


main()
"""


def test_read_reel_follows_loops_awaits_and_comprehensions(tmp_path: Path) -> None:
    """The StopIteration that ends a loop, a yield from or an await is never told as raised,
    a swallowed exception isn't one leaving, a comprehension's variables are its own, and
    pointers into a list aren't called the same object."""
    (tmp_path / "flow.py").write_text(FLOW)
    reel = write_reel(record(tmp_path / "flow.py"), tmp_path / "flow.reel.html", player="")
    changed = "\n".join(row[54:] for row in rows(run(str(reel), "--steps", "1-5000").stdout))
    assert "StopIteration" not in changed and "StopAsyncIteration" not in changed
    assert "waits" in changed and "yields 0" in changed and "wrapped_value" not in changed
    if sys.version_info < (3, 15):  # later, the value an async generator yields isn't recorded
        assert "yields 10" in changed
    assert "raises KeyError" in changed and "leaves because" not in changed
    assert "is closed" in changed and "yields 2" in changed
    assert "call <lambda>(a=1)" in changed and "call <lambda>(b=2)" in changed
    assert "del x" not in changed and "are the same" not in changed
    if sys.version_info >= (3, 12):  # comprehensions run inside their function from 3.12
        assert "x=2 (in the comprehension)" in changed
    else:
        assert "call <listcomp>()" in changed


RISKY = """\
def risky(xs):
    try:
        return xs[5]
    finally:
        xs.append(0)


def outer():
    try:
        risky([1, 2])
    except IndexError:
        pass
    return 1
"""


def test_read_reel_says_when_lines_hide_whether_an_exception_left(tmp_path: Path) -> None:
    (tmp_path / "risky.py").write_text(RISKY)
    trace = record(tmp_path / "risky.py", "outer()", lines={3, 5})
    reel = write_reel(trace, tmp_path / "risky.reel.html", player="")
    last = rows(run(str(reel), "--steps").stdout)[-2]
    assert last.endswith("returns None, or leaves because of the exception")


VALUES = """\
from collections import deque


def values():
    q = deque([1, 2, 3])
    q.appendleft(0)
    q.popleft()
    q.rotate(1)
    fs = frozenset({1, 2})
    a = []
    a.append(a)
    message = "bad\\r\\x1b[2Jrow"
    pattern = "\\d"
    raise ValueError(message)
"""


@pytest.mark.filterwarnings("ignore:.*invalid escape sequence")  # the "\d" it records
def test_read_reel_writes_values_as_python_does_and_safely(tmp_path: Path) -> None:
    """Deque moves, frozensets and lists holding themselves read as in Python, and control
    characters in values or messages are written as escapes."""
    (tmp_path / "values.py").write_text(VALUES)
    reel = write_reel(record(tmp_path / "values.py", "values()"), tmp_path / "v.html", player="")
    done = run(str(reel), "--steps")
    assert not done.stderr  # not even the warning Python 3.12 gives for "\d"
    changed = "\n".join(row[54:] for row in rows(done.stdout))  # not the code column
    for note in ["q.appendleft(0)", "q.popleft()", "q.rotate(1)", "fs=frozenset({1, 2})"]:
        assert note in changed, note
    assert "a.append([[...]])" in changed and "\\r\\x1b[2Jrow" in changed
    assert "\x1b" not in done.stdout and "\r" not in done.stdout


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
    done = run(str(deep))  # too deep for some Pythons' JSON reader, and fine for others
    assert "Traceback" not in done.stderr and (done.returncode == 0 or "damaged" in done.stderr)
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
