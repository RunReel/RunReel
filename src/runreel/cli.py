"""Command-line entry point for `runreel`."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from runreel import __version__
from runreel.reel import write_reel
from runreel.trace import MAX_STEPS, TIMEOUT, ExitedWhileLoading, Trace, record, state_at

RUN_HELP = """\
Run FILE, record every step and write the reel: one HTML file that opens offline.

This executes FILE's code on your machine, with your permissions, exactly as running it
yourself would. Only run code you trust.

After the step limit the program keeps running unrecorded until it ends or hits the time
limit. Ctrl+C stops it too, and the reel is still written.

Arguments after -- go to the program: runreel run app.py -- --n 5 runs it the way
python app.py --n 5 would.
"""
CALL_HINT = (
    "With --call the file is loaded first, untraced, so it should only define functions;"
    ' put the code that runs the program under `if __name__ == "__main__":`'
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runreel",
        description="Turn an algorithm into an interactive step-through reel.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    run = commands.add_parser(
        "run",
        help="run a Python file and write its reel",
        description=RUN_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run.add_argument("file", type=Path, help="Python file to run")
    run.add_argument("args", nargs="*", metavar="ARGS", help="arguments for the program, after --")
    run.add_argument(
        "--call",
        help='expression to trace, e.g. "dijkstra(G, 0)"; without it FILE runs as a script',
    )
    run.add_argument("--stdin", type=Path, metavar="FILE", help="file to give the program as input")
    run.add_argument(
        "--lines",
        type=parse_lines,
        metavar="RANGES",
        help="record only these lines, e.g. 12-30 or 12-30,40",
    )
    run.add_argument(
        "--max-steps",
        type=positive,
        default=MAX_STEPS,
        metavar="N",
        help=f"stop recording after N steps (default: {MAX_STEPS})",
    )
    run.add_argument(
        "--timeout",
        type=seconds,
        default=TIMEOUT,
        metavar="SECONDS",
        help=f"stop the program once it has run for SECONDS (default: {TIMEOUT:g}; 0: no limit)",
    )
    run.add_argument("--out", type=Path, help="reel to write (default: FILE with .reel.html)")
    run.add_argument("--open", action="store_true", help="open the reel in your browser")
    run.add_argument("--no-mark", action="store_true", help='hide the "made with RunReel" link')
    return parser


def parse_lines(spec: str) -> frozenset[int]:
    """Line ranges like "12-30,40" as a set of line numbers."""
    lines: set[int] = set()
    try:
        for part in spec.split(","):
            first, dash, last = part.strip().partition("-")
            start, end = int(first), int(last if dash else first)
            if start < 1 or end < start:
                raise ValueError
            lines.update(range(start, end + 1))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a line range: {spec!r} (try 12-30,40)") from None
    return frozenset(lines)


def positive(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be a whole number of at least 1: {text!r}")
    return n


def seconds(text: str) -> float:
    try:
        n = float(text)
    except ValueError:
        n = -1
    if not n >= 0:  # also refuses nan
        raise argparse.ArgumentTypeError(f"must be a number of seconds, 0 or more: {text!r}")
    return n


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        return run(args)
    except KeyboardInterrupt:  # Ctrl+C before or after the run, e.g. while writing the reel
        print("runreel: interrupted", file=sys.stderr)
        return 130


def run(args: argparse.Namespace) -> int:
    """Record the file, write the reel and print a one-line summary that agents can read."""
    file: Path = args.file
    try:
        stdin = args.stdin.read_text(encoding="utf-8") if args.stdin else ""
        trace = record(
            file,
            args.call,
            lines=args.lines,
            max_steps=args.max_steps,
            args=args.args,
            stdin=stdin,
            timeout=args.timeout or None,
        )
    except OSError as error:
        return fail(f"can't read {error.filename or file}: {error.strerror or error}")
    except UnicodeDecodeError:
        return fail(f"can't read {file}: it isn't UTF-8 text")
    except SyntaxError as error:
        return fail(f"{file} doesn't compile: {error.msg} (line {error.lineno})")
    except ExitedWhileLoading as error:
        return fail(f"{file} {error}. {CALL_HINT}")
    except Exception as error:  # raised while loading the file, before the traced call
        return fail(f"{file} failed while loading: {type(error).__name__}: {error}")
    if not trace["steps"] and "stopped" in trace:
        message = f"{file} was {stopped(trace, args.timeout)} before any step was recorded"
        return fail(f"{message}. {CALL_HINT}" if args.call else message)
    out: Path = args.out or file.with_suffix(".reel.html")
    try:
        write_reel(trace, out, mark=not args.no_mark)
    except FileNotFoundError as error:
        return fail(str(error))
    except OSError as error:
        return fail(f"can't write {out}: {error.strerror or error}")
    print(summary(trace, out, args.timeout))
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


def fail(message: str) -> int:
    print(f"runreel: {message}", file=sys.stderr)
    return 1


def summary(trace: Trace, out: Path, timeout: float | None = None) -> str:
    """E.g. "reel: dijkstra.reel.html (29 KB) · 63 steps · result {0: 0, 1: 3}"."""
    steps = trace["steps"]
    parts = [f"reel: {out} ({max(out.stat().st_size // 1024, 1)} KB)", f"{len(steps)} steps"]
    if trace.get("truncated"):
        parts[-1] += " (truncated: raise --max-steps to see more)"
    if "stopped" in trace:
        parts.append(stopped(trace, timeout))
        if trace["stopped"] == "timeout":
            parts[-1] += " (raise --timeout to let it run longer)"
    if "error" in trace:
        parts.append(f"error {trace['error']}")
    elif "result" in trace:
        heap = state_at(steps, len(steps) - 1)["heap"] if steps else {}
        parts.append(f"result {describe(trace['result'], heap)}")
    printed = sum(text.count("\n") for _, text in trace.get("stdout", []))
    if printed:
        parts.append(f"printed {printed} line{'s' if printed != 1 else ''}")
    return " · ".join(parts)


def stopped(trace: Trace, timeout: float | None) -> str:
    """How the program was stopped, e.g. "stopped at the 60 s time limit"."""
    if trace.get("stopped") == "interrupt":
        return "stopped by Ctrl+C"
    return f"stopped at the {timeout:g} s time limit" if timeout else "stopped at the time limit"


def describe(value: Any, heap: dict[int, Any], depth: int = 0) -> str:
    """A short Python-like rendering of a trace value."""
    text = _describe(value, heap, depth)
    return text if len(text) <= 80 else text[:79] + "…"


def _describe(value: Any, heap: dict[int, Any], depth: int) -> str:
    if not isinstance(value, dict):
        return repr(value)
    if "inf" in value:
        return "inf" if value["inf"] == 1 else "-inf"
    if "nan" in value:
        return "nan"
    if "bigint" in value:
        return str(value["bigint"])
    obj = heap.get(value.get("ref", -1))
    if obj is None or depth > 2:
        return "…"
    if obj["t"] == "repr":
        return str(obj["v"])
    if obj["t"] == "obj":
        fields = ", ".join(f"{k}={_describe(v, heap, depth + 1)}" for k, v in obj["fields"].items())
        return f"{obj['cls']}({fields})"
    more = ", …" if obj.get("more") else ""
    if obj["t"] == "map":
        pairs = (
            f"{_describe(k, heap, depth + 1)}: {_describe(v, heap, depth + 1)}"
            for k, v in obj["items"]
        )
        return "{" + ", ".join(pairs) + more + "}"
    items = ", ".join(_describe(v, heap, depth + 1) for v in obj["items"])
    if obj["cls"] == "tuple":
        return f"({items}{',' if len(obj['items']) == 1 else ''}{more})"
    if obj["cls"] in ("set", "frozenset"):
        return "{" + items + more + "}"
    return f"[{items}{more}]"
