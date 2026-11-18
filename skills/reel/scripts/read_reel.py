#!/usr/bin/env python3
"""Print a RunReel reel as text, for an agent that can't watch it play.

    python3 read_reel.py REEL                what ran, what it printed and how it ended
    python3 read_reel.py REEL --steps        every step, and what it printed
    python3 read_reel.py REEL --steps 40-60  only steps 40 to 60
    python3 read_reel.py REEL --printed      everything the program printed

Steps are numbered the way the reel's counter shows them, from 1. A link to a step counts
from 0: step N opens with #step=N-1 at the end of the reel's address. The script needs
Python 3.8 or later and nothing else, so it runs without RunReel installed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

FORMAT = 1  # the trace format this script reads
LISTED = 300  # steps listed when no range is given, as many as a reel is advised to have
ITEMS = 50  # items of a collection shown
WIDTH = 60  # characters shown of one value
SHOWN = 400  # characters of a value written before it's cut, so a huge one costs little
PRINTED = 2000  # characters of printed text shown in the overview
BIG = 10_000_000  # characters of trace past which memory matters more than speed
PLACEHOLDER = "(not shown:"  # how an object past the reel's limit of objects is written
RANGE = re.compile(r"(\d+)(?:-(\d+))?")
# Control characters, and those some tools take for line breaks, are written as escapes.
CONTROLS = {c: f"\\x{c:02x}" for c in [*range(0x20), 0x7F, *range(0x80, 0xA0)]}
CONTROLS.update({0x0A: "\\n", 0x0D: "\\r", 0x09: "\\t", 0x2028: "\\u2028", 0x2029: "\\u2029"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="read_reel.py", description="Print a reel as text.")
    parser.add_argument("reel", nargs="?", help="the reel's HTML file")
    which = parser.add_mutually_exclusive_group()
    which.add_argument(
        "--steps", nargs="?", const="", metavar="FROM-TO", help="list the steps, or only these"
    )
    which.add_argument("--printed", action="store_true", help="print all the program printed")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.reel is None and args.steps and not RANGE.fullmatch(args.steps):
        args.reel, args.steps = args.steps, ""  # --steps REEL: the path was taken as the range
    if args.reel is None:
        parser.error("give the reel's HTML file")
    if sys.stdout is None:  # the output was closed, so there's nowhere to write
        return 1
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure:
        reconfigure(errors="backslashreplace")  # a console that can't show a character gets \x..
    trace = load(args.reel)
    try:
        if args.printed:
            sys.stdout.write(printed(trace))
        elif args.steps is not None:
            first, last = wanted(args.steps, len(trace["steps"]), parser)
            list_steps(trace, first, last)
        else:
            overview(trace, args.reel)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError, RecursionError):
        sys.stdout.flush()
        sys.exit(f"read_reel.py: can't follow the trace in {args.reel}; it may be damaged")
    return 0


def load(path: str) -> dict[str, Any]:
    """The trace inside a reel, or exit with a message saying why there isn't one."""
    try:
        page = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        sys.exit(f"read_reel.py: can't read {path}: {error}")
    tag = 'id="runreel-trace">'
    start = page.find(tag)
    if start < 0:
        if 'content="RunReel"' in page:
            sys.exit(f"read_reel.py: {path} is cut short: its trace is missing")
        sys.exit(f"read_reel.py: {path} isn't a RunReel reel")
    end = page.find("</script>", start)
    if end < 0:
        sys.exit(f"read_reel.py: {path} is cut short: its trace doesn't end")
    plays = page.find("RunReelPlayer.mount(", end) >= 0  # the player starts after the trace
    text = page[start + len(tag) : end]
    del page  # a reel can be large, so keep only the trace while it's read
    try:
        if len(text) > BIG:  # share repeated numbers, such as the call ids of a deep stack
            numbers: dict[str, int] = {}
            trace = json.loads(text, parse_int=lambda s: numbers.setdefault(s, int(s)))
        else:
            trace = json.loads(text)
    except (ValueError, RecursionError, MemoryError):
        sys.exit(f"read_reel.py: the trace in {path} is damaged")
    del text
    if not isinstance(trace, dict) or type(trace.get("schema")) is not int:
        sys.exit(f"read_reel.py: the trace in {path} is damaged")
    if trace["schema"] != FORMAT:
        sys.exit(
            f"read_reel.py: {path} uses trace format {trace['schema']}, but this script"
            f" reads format {FORMAT}"
        )
    if not _well_formed(trace):
        sys.exit(f"read_reel.py: the trace in {path} is damaged")
    if not plays:
        print(
            f"read_reel.py: {path} is cut short after its trace, so it won't play in a"
            " browser; what follows is what it recorded",
            file=sys.stderr,
        )
    return trace


def _well_formed(trace: Any) -> bool:
    if not isinstance(trace, dict):
        return False
    source, steps, stdout = trace.get("source"), trace.get("steps"), trace.get("stdout", [])
    return (
        isinstance(source, dict)
        and all(isinstance(source.get(key), str) for key in ("file", "text", "entry"))
        and isinstance(steps, list)
        and bool(steps)
        and all(isinstance(s, dict) and isinstance(s.get("line"), int) for s in steps)
        and all(isinstance(s.get("ev"), str) for s in steps)
        and bool(steps[0].get("key"))
        and isinstance(stdout, list)
        and all(isinstance(p, list) and len(p) == 2 and isinstance(p[1], str) for p in stdout)
    )


def decode(
    steps: list[dict[str, Any]],
) -> Iterator[tuple[dict[str, Any], dict[str, Any], dict[int, Any], list[Any] | None]]:
    """Each step with the program's state after it, the way the player rebuilds it, and what
    the step changed as it was before: the old version of each object it changed or dropped,
    by id. A keyframe holds the whole state, so for one, the whole state before is given:
    every object, and the stack of calls. The state is updated in place, so read it before
    asking for the next step."""
    state: dict[str, Any] = {"stack": [], "heap": {}}
    for step in steps:
        old: dict[int, Any] = {}
        old_stack = None
        if step.get("key"):  # a keyframe holds everything, so start again from nothing
            old, old_stack = state["heap"], state["stack"]
            state = {"stack": [], "heap": {}}
        state["ev"], state["line"] = step["ev"], step["line"]
        state.pop("ret", None)
        state.pop("exc", None)
        if "stack" in step:
            by_fid = {frame["fid"]: frame for frame in state["stack"]}
            state["stack"] = [
                by_fid.get(fid) or {"fid": fid, "fn": "", "line": 0, "locals": {}}
                for fid in step["stack"]
            ]
        if state["stack"]:
            state["stack"][-1]["line"] = step["line"]
        by_fid = {frame["fid"]: frame for frame in state["stack"]}
        for fid, patch in step.get("frames", {}).items():
            frame = by_fid[int(fid)]
            if "fn" in patch:
                frame["fn"] = patch["fn"]
            if "line" in patch:
                frame["line"] = patch["line"]
            frame["locals"].update(patch.get("set", {}))
            for name in patch.get("del", []):
                del frame["locals"][name]
        heap = state["heap"]
        for key, entry in step.get("heap", {}).items():
            oid = int(key)
            if "t" in entry:  # a whole object, new or sent again
                if oid in heap:
                    old[oid] = heap[oid]
                heap[oid] = _copy(entry)
            else:  # changes to one
                old[oid] = _copy(heap[oid])
                _patch(heap[oid], entry)
        for gone in step.get("gc", []):
            old[gone] = heap.pop(gone)
        if "ret" in step:
            state["ret"] = step["ret"]
        if "exc" in step:
            state["exc"] = step["exc"]
        yield step, state, old, old_stack


def states(steps: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """The program's state after each step: the stack of calls with their variables, and the
    objects they refer to. The same dict is updated each time, so read it before asking for
    the next."""
    for _, state, _, _ in decode(steps):
        yield state


def _copy(obj: dict[str, Any]) -> dict[str, Any]:
    copied = dict(obj)
    if "items" in obj:
        copied["items"] = list(obj["items"])
    if "fields" in obj:
        copied["fields"] = dict(obj["fields"])
    return copied


def _patch(obj: dict[str, Any], patch: dict[str, Any]) -> None:
    """Edit an object in place. Edits index the items as they were, so they run back to front."""
    for edit in reversed(patch.get("ops", [])):
        if len(edit) == 2:
            obj["items"][edit[0]] = edit[1]
        else:
            start, count, items = edit
            obj["items"][start : start + count] = items
    if "set" in patch:
        obj["fields"].update(patch["set"])
    for name in patch.get("del", []):
        del obj["fields"][name]
    if "more" in patch:
        if patch["more"]:
            obj["more"] = patch["more"]
        else:
            obj.pop("more", None)


def placeholder(obj: dict[str, Any]) -> bool:
    """Whether obj stands in for an object past the reel's limit of objects, not shown."""
    return obj.get("t") == "repr" and str(obj.get("v", "")).startswith(PLACEHOLDER)


def clean(text: str, tabs: bool = False) -> str:
    """text with control characters written as escapes, so it stays on one line and can't
    move the cursor or clear the screen; tabs are kept if asked, for indented code."""
    return text.translate({**CONTROLS, 0x09: "\t"} if tabs else CONTROLS)


def show(value: Any, heap: Mapping[int, Any], depth: int = 0, opened: tuple[int, ...] = ()) -> str:
    """A recorded value written the way Python prints it. Collections show their first ITEMS
    items, objects nested more than two deep show only their class, objects past the reel's
    limit of objects show as …, and a container inside itself shows as [...], as Python's
    own repr does."""
    if isinstance(value, dict):
        if "ref" in value:
            oid = value["ref"]
            obj = heap.get(oid)
            if obj is None:
                return "…"
            if oid in opened:
                return "[...]" if obj["cls"] == "list" else "{...}" if obj["t"] == "map" else "..."
            return show_object(obj, heap, depth, (*opened, oid))
        if "inf" in value:
            return "inf" if value["inf"] > 0 else "-inf"
        if "nan" in value:
            return "nan"
        if "bigint" in value:
            return str(value["bigint"])
        if "float" in value:
            return str(value["float"])
    return repr(value)


def show_object(
    obj: dict[str, Any], heap: Mapping[int, Any], depth: int = 0, opened: tuple[int, ...] = ()
) -> str:
    kind, cls = obj["t"], obj["cls"]
    if kind == "repr":
        return "…" if placeholder(obj) else str(obj["v"])
    if depth >= 3:
        return f"{cls}(…)"
    if kind == "obj":
        fields = obj.get("fields", {})
        if not fields and cls.endswith(("Error", "Exception", "Warning")):
            return f"{cls}(…)"  # an exception's message isn't one of its fields
        name = fields.get("__qualname__")
        if isinstance(name, str) and "__module__" in fields:
            return f"<{cls} {name}>"  # a function's wrapper, such as staticmethod or lru_cache
        parts = (f"{k}={show(v, heap, depth + 1, opened)}" for k, v in fields.items())
        return f"{cls}({_joined(parts, False)})"
    items = obj.get("items", [])
    more = bool(obj.get("more"))
    if kind == "map":
        pairs = (
            f"{show(k, heap, depth + 1, opened)}: {show(v, heap, depth + 1, opened)}"
            for k, v in items
        )
        text = "{" + _joined(pairs, more) + "}"
        return text if cls == "dict" else f"{cls}({text})"
    text = _joined((show(v, heap, depth + 1, opened) for v in items), more)
    if cls == "list":
        return f"[{text}]"
    if cls == "tuple":
        return f"({text}{',' if len(items) == 1 and not more else ''})"
    if cls == "set":
        return "{" + text + "}" if items else "set()"
    if cls == "frozenset":
        return f"frozenset({{{text}}})" if items else "frozenset()"
    return f"{cls}([{text}])"


def _joined(parts: Iterable[str], more: bool) -> str:
    """parts joined with commas, ending with … once ITEMS parts or SHOWN characters are
    written, or when there were more, so a huge value costs no more than it shows."""
    kept: list[str] = []
    size = 0
    for part in parts:
        if len(kept) == ITEMS or size > SHOWN:
            more = True
            break
        kept.append(part)
        size += len(part) + 2
    if not kept:
        return "…" if more else ""
    return ", ".join(kept) + (", …" if more else "")


def short(text: str, width: int = WIDTH) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def printed(trace: dict[str, Any]) -> str:
    return "".join(text for _, text in trace.get("stdout", []))


def source_lines(trace: dict[str, Any]) -> list[str]:
    """The file's lines, split only at newlines, as Python and the player number them."""
    text: str = trace["source"]["text"]
    return (text[:-1] if text.endswith("\n") else text).split("\n")


def overview(trace: dict[str, Any], path: str) -> None:
    """How the run ended, what it printed, and the source with the lines that ran marked."""
    source, steps = trace["source"], trace["steps"]
    what = f"the call {source['entry']}" if source["entry"] else "the whole script"
    print(clean(f"{path} records {what} in {source['file']}."))
    print(f"Open it at {Path(path).resolve().as_uri()}, adding #step=LINK at the end to open")
    print("one step. LINK is the step number minus 1, as --steps lists it.")
    counts: Counter[int] = Counter()
    heap: dict[int, Any] = {}
    first: dict[int, str] = {}  # call id -> the event of its first recorded step
    last = ("", 0)
    for state in states(steps):
        counts[state["line"]] += 1
        heap = state["heap"]
        if state["stack"]:
            first.setdefault(state["stack"][-1]["fid"], state["ev"])
        last = (state["ev"], len(state["stack"]))
    print(ending(trace, heap))
    if isinstance(trace.get("result"), str) and "error" not in trace:
        print("(A result in quotes may also be a value the steps never held, not a string.)")
    text = printed(trace)
    if text:
        print("\nIt printed:")
        print(text[:PRINTED], end="" if text[:PRINTED].endswith("\n") else "\n")
        if len(text) > PRINTED:
            print(f"… and {len(text) - PRINTED:,} more characters: see --printed")
        elif not text.endswith("\n"):
            print("(with no newline at the end)")
    print("\n> marks the lines that ran, and the number after it is how many steps each had.")
    print("  line steps")
    for n, line in enumerate(source_lines(trace), 1):
        print(
            clean(f"{'>' if counts[n] else ' '} {n:>4} {counts[n] or '':>5}  {line}".rstrip(), True)
        )
    print(
        "\nLines with no code of their own, such as else:, finally:, comments and blank lines,"
        " never show as run, so judge a branch by the lines inside it."
    )
    if lines_only(trace, first, last):
        print(
            "This reel was recorded with --lines, so only those lines show as run. Other lines"
            " may have run unrecorded: text they printed is listed at the last recorded step"
            " before it (or the first step), and a list or object in the result may show as it"
            " was at the last recorded step."
        )
    elif source["entry"]:
        print(
            "Only the code the call ran was recorded, and with --lines only those lines; the"
            " file's top-level code never shows."
        )
    if trace.get("truncated"):
        print("The step limit was reached, so lines that ran after it aren't marked.")


def lines_only(trace: dict[str, Any], first: dict[int, str], last: tuple[str, int]) -> bool:
    """Whether the reel was recorded with --lines, as far as its steps show: a call whose first
    recorded step isn't its start, or a run that ended normally but not with a return from
    the bottom of the stack."""
    if any(event != "call" for event in first.values()):
        return True
    ended = not (trace.get("truncated") or trace.get("stopped") or "error" in trace)
    return ended and last != ("return", 1)


def ending(trace: dict[str, Any], heap: Mapping[int, Any]) -> str:
    """How the run ended, like runreel's own summary."""
    count = len(trace["steps"])
    parts = [f"{count:,} step{'' if count == 1 else 's'}"]
    if trace.get("truncated"):
        parts.append("truncated: the step limit was reached, and the rest ran unrecorded")
    if trace.get("stopped") == "timeout":
        parts.append("stopped at the time limit")
    elif trace.get("stopped") == "interrupt":
        parts.append("stopped by Ctrl+C")
    if "error" in trace:
        parts.append(f"error {trace['error']}")
    elif "result" in trace:
        parts.append(f"result {short(show(trace['result'], heap), 300)}")
    return clean(" · ".join(parts))


def wanted(steps: str, count: int, parser: argparse.ArgumentParser) -> tuple[int, int]:
    """The first and last step to list, counted from 1 as the reel's counter does."""
    if not steps:
        return 1, min(count, LISTED)
    found = RANGE.fullmatch(steps)
    first = int(found.group(1)) if found else 0
    last = int(found.group(2) or first) if found else 0
    if not 1 <= first <= last:
        parser.error(f"--steps takes a step or a range of steps, such as 40-60, not {steps!r}")
    if first > count:
        parser.error(f"the reel has {count:,} step{'' if count == 1 else 's'}")
    return first, min(last, count)


def list_steps(trace: dict[str, Any], first: int, last: int) -> None:
    """One line per step: its number, its link, its line and what it printed."""
    steps, entry = trace["steps"], trace["source"]["entry"]
    lines = source_lines(trace)
    stops = bool(trace.get("truncated") or trace.get("stopped"))
    prints: dict[int, str] = {}
    for at, text in trace.get("stdout", []):
        prints[at] = prints.get(at, "") + text
    print("step is the number on the reel's counter, and #step=LINK opens it. Each step shows")
    print("the line about to run. Printed text shows on the last step recorded before it was")
    print("printed (or the first step, if none was yet), usually the step of the line that")
    print("prints it.")
    print(f"{'step':>5} {'link':>5} {'line':>4}  {'code':<34}  printed")
    heap: Mapping[int, Any] = {}
    for at, (step, state, _, _) in enumerate(decode(steps)):
        if at + 1 > last:
            break
        heap = state["heap"]
        if at + 1 < first:
            continue
        notes: list[str] = []
        if at in prints:
            label = "prints"
            if at == 0 and entry and step["ev"] == "call":
                label = "printed while the file loaded:"
            elif at == len(steps) - 1 and stops:
                label = "prints, up to the end of the run,"
            notes.append(f"{label} {short(repr(prints[at]))}")
        line = state["line"]
        code = short(clean(lines[line - 1].strip()) if 0 < line <= len(lines) else "(start)", 34)
        print(f"{at + 1:>5} {at:>5} {line:>4}  {code:<34}  {', '.join(notes)}".rstrip())
    total = len(steps)
    if last < total:
        rest = f"{last + 1}" if last + 1 == total else f"{last + 1}-{total}"
        many = total - last != 1
        print(
            f"… {total - last:,} more step{'s' if many else ''}: list"
            f" {'them' if many else 'it'} with --steps {rest}"
        )
    else:
        print(f"The reel ends here: {ending(trace, heap)}")


if __name__ == "__main__":
    try:
        code = main()
        if sys.stdout is not None:
            sys.stdout.flush()
    except BrokenPipeError:  # whatever read the output, such as head, stopped early
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        code = 0
    except OSError as error:  # the output can't be written, as on a full disk
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        if sys.stderr is not None:
            sys.stderr.write(f"read_reel.py: can't write the output: {error}\n")
        code = 1
    sys.exit(code)
