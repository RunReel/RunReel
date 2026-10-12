"""Command-line entry point for `runreel`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from runreel import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runreel",
        description="Turn an algorithm into an interactive step-through reel.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    run = commands.add_parser("run", help="trace a program and write a reel (not implemented yet)")
    run.add_argument("file", help="Python file to trace")
    run.add_argument("--call", help='expression to run, e.g. "dijkstra(G, 0)"')
    run.add_argument("--out", default="reel.html", help="output HTML file (default: reel.html)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    print(f"runreel: '{args.command}' is not implemented yet", file=sys.stderr)
    return 2
