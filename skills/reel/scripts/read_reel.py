#!/usr/bin/env python3
"""Print a RunReel reel as text, for an agent that can't watch it play.

    python3 read_reel.py REEL                what ran, what it printed and how it ended
    python3 read_reel.py REEL --steps        every step, with what changed at it
    python3 read_reel.py REEL --steps 40-60  only steps 40 to 60
    python3 read_reel.py REEL --printed      everything the program printed

Steps are numbered the way the reel's counter shows them, from 1. A link to a step counts
from 0: step N opens with #step=N-1 at the end of the reel's address. The script needs
Python 3.8 or later and nothing else, so it runs without RunReel installed.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import math
import os
import re
import sys
import tokenize
import warnings
from collections import ChainMap, Counter
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # annotations are never evaluated, so Python 3.8 needn't know this one
    Span = tuple[str, set[str], dict[str, Any]]  # a comprehension a step is in, or ""

FORMAT = 1  # the trace format this script reads
LISTED = 300  # steps listed when no range is given, as many as a reel is advised to have
ITEMS = 50  # items of a collection shown
WIDTH = 60  # characters shown of one value
SHOWN = 400  # characters of a value written before it's cut, so a huge one costs little
NOTES = 20  # changes listed for one step
PRINTED = 2000  # characters of printed text shown in the overview
BIG = 10_000_000  # characters of trace past which memory matters more than speed
SEARCHED = 5000  # objects looked through to find names for the changed ones
NAMED = 3  # names given for an object that several names reach
PLACEHOLDER = "(not shown:"  # how an object past the reel's limit of objects is written
RANGE = re.compile(r"(\d+)(?:-(\d+))?")
WORDS = re.compile(r"\w+")
# For lines read as text, when this Python can't parse the file or read its tokens.
STRINGS = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")
YIELDS = re.compile(r"\b(?:yield|await)\b")
AWAITS = re.compile(r"\bawait\b|\basync\s+(?:for|with)\b")
HANDS_OVER = re.compile(r"\byield\s+from\b|\bawait\b|\basync\s+(?:for|with)\b")
LOOPS = re.compile(r"\bfor\b")
# What Python itself sets in a class body; a class's own dunders, such as __init__, still show.
BOOKKEEPING = frozenset(
    {
        "__module__",
        "__qualname__",
        "__firstlineno__",
        "__doc__",
        "__annotations__",
        "__annotate__",
        "__annotate_func__",
        "__conditional_annotations__",
        "__static_attributes__",
        "__type_params__",
        "__classcell__",
    }
)
COMPREHENSIONS = ("<listcomp>", "<setcomp>", "<dictcomp>", "<genexpr>")  # frames before 3.12
# Control characters, and those some tools take for line breaks, are written as escapes.
CONTROLS = {c: f"\\x{c:02x}" for c in [*range(0x20), 0x7F, *range(0x80, 0xA0)]}
CONTROLS.update({0x0A: "\\n", 0x0D: "\\r", 0x09: "\\t", 0x2028: "\\u2028", 0x2029: "\\u2029"})
MISSING = object()


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


def same(a: Any, b: Any) -> bool:
    """Whether two recorded values are equal, telling 1, 1.0 and True apart, as == doesn't."""
    if type(a) is not type(b):
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(same(a[i], b[i]) for i in range(len(a)))
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same(v, b[k]) for k, v in a.items())
    if isinstance(a, float):
        return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)
    return bool(a == b)


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


class Source:
    """What the file's code says that the trace doesn't: which line each function's and
    class's calls start on, each function's parameters and kind, and which lines yield, hand
    over to another generator or coroutine, or loop. A file this Python can't parse, such as
    one using newer syntax, is read from its tokens instead, and past where those fail, as
    text."""

    def __init__(self, text: str) -> None:
        self.parsed = True
        self.read_to = 0  # without a parse, the last line the tokens reached
        self.params: dict[tuple[int, str], set[str]] = {}  # (first line, name) -> parameters
        self.kinds: dict[tuple[int, str], str] = {}  # (first line, name) -> generator, ...
        self.classes: set[tuple[int, str]] = set()  # (first line, name) of each class
        self.yields: Counter[int] = Counter()  # line -> how many yields it holds
        self.awaits: set[int] = set()  # lines that await: await, async for and async with
        self.hands_over: set[int] = set()  # yield from, await, async for and async with lines
        self.loops: set[int] = set()  # the lines of for loops and comprehensions
        # Comprehensions that run inside their function from 3.12: lines, and names they bind.
        self.comprehensions: list[tuple[int, int, set[str]]] = []
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # the file's own warnings showed when it ran
                tree = ast.parse(text)
            self._read_tree(tree)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            self._reset()
            self.parsed = False
            self._read_tokens(text)

    def _reset(self) -> None:
        self.params, self.kinds, self.classes = {}, {}, set()
        self.yields, self.hands_over, self.loops, self.comprehensions = Counter(), set(), set(), []
        self.awaits = set()

    def _read_tree(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Yield, ast.YieldFrom)):
                self.yields[node.lineno] += 1
                if isinstance(node, ast.YieldFrom):
                    self.hands_over.add(node.lineno)
            elif isinstance(node, ast.Await):
                self.awaits.add(node.lineno)
                self.hands_over.add(node.lineno)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                self.loops |= {node.lineno, node.iter.lineno}
                if isinstance(node, ast.AsyncFor):
                    self.awaits |= {node.lineno, node.iter.lineno}
                    self.hands_over |= {node.lineno, node.iter.lineno}
            elif isinstance(node, ast.AsyncWith):
                lines = {node.lineno, *(item.context_expr.lineno for item in node.items)}
                self.awaits |= lines
                self.hands_over |= lines
            elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                last = getattr(node, "end_lineno", None) or node.lineno
                lines = set(range(node.lineno, last + 1))
                self.loops |= lines
                if any(g.is_async for g in node.generators):
                    self.awaits |= lines
                    self.hands_over |= lines
                if not isinstance(node, ast.GeneratorExp):
                    bound = {
                        n.id
                        for g in node.generators
                        for n in ast.walk(g.target)
                        if isinstance(n, ast.Name)
                    }
                    self.comprehensions.append((node.lineno, last, bound))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                given = node.args
                names = {a.arg for a in [*given.posonlyargs, *given.args, *given.kwonlyargs]}
                names |= {a.arg for a in (given.vararg, given.kwarg) if a is not None}
                if isinstance(node, ast.Lambda):
                    name, starts, kind = "<lambda>", {node.lineno}, "function"
                else:  # a decorated function's calls start on its first decorator's line
                    name, starts = node.name, {node.lineno}
                    starts |= {d.lineno for d in node.decorator_list[:1]}
                    yields = any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in _own(node))
                    if isinstance(node, ast.AsyncFunctionDef):
                        kind = "async generator" if yields else "coroutine"
                    else:
                        kind = "generator" if yields else "function"
                for line in starts:
                    self.params[(line, name)] = self.params.get((line, name), set()) | names
                    self.kinds.setdefault((line, name), kind)
            elif isinstance(node, ast.ClassDef):
                starts = {node.lineno} | {d.lineno for d in node.decorator_list[:1]}
                self.classes |= {(line, node.name) for line in starts}

    def _read_tokens(self, text: str) -> None:
        """Read what a parse would have given from the file's tokens, leaving out strings and
        comments, as far as they go."""
        tokens: list[tokenize.TokenInfo] = []
        try:
            for token in tokenize.generate_tokens(io.StringIO(text).readline):
                tokens.append(token)
        except (tokenize.TokenError, SyntaxError, ValueError):
            pass  # syntax too new even for the tokens: the rest is read as text
        self.read_to = tokens[-1].start[0] - 1 if tokens else 0
        quiet = {tokenize.COMMENT, tokenize.NL, tokenize.INDENT, tokenize.DEDENT, tokenize.STRING}
        quiet |= {tokenize.ENCODING, tokenize.ENDMARKER}
        quiet |= {
            getattr(tokenize, name)
            for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
            if hasattr(tokenize, name)
        }
        words: list[tuple[tokenize.TokenInfo, bool]] = []  # with whether it starts a statement
        starts = True
        for token in tokens:
            if token.type == tokenize.NEWLINE:
                starts = True
            elif token.type not in quiet:
                words.append((token, starts))
                starts = False
        decorated = 0  # the first line of decorators waiting for their def or class
        for i, (token, first) in enumerate(words):
            line, word = token.start[0], token.string
            after = words[i + 1][0].string if i + 1 < len(words) else ""
            if first and word == "@":
                decorated = decorated or line
            elif first and word not in ("def", "class", "async"):
                decorated = 0
            if token.type != tokenize.NAME:
                continue
            if word == "yield":
                self.yields[line] += 1
                if after == "from":
                    self.hands_over.add(line)
            elif word == "await" or (word == "async" and after in ("for", "with")):
                self.awaits.add(line)
                self.hands_over.add(line)
            elif word == "for":
                self.loops.add(line)
            elif word in ("def", "class") and i + 1 < len(words):
                begins = {line} | ({decorated} if decorated else set())
                decorated = 0
                if word == "class":
                    self.classes |= {(n, after) for n in begins}
                else:
                    names = _parameters(words, i + 2)
                    for n in begins:
                        self.params[(n, after)] = self.params.get((n, after), set()) | names
            elif word == "lambda":
                names = _parameters(words, i + 1, lambda_=True)
                key = (line, "<lambda>")
                self.params[key] = self.params.get(key, set()) | names

    def _known(self, line: int) -> bool:
        return self.parsed or line <= self.read_to

    def parameters(self, line: int, fn: str) -> set[str] | None:
        """The parameters of the function fn whose calls start on this line, if known."""
        return self.params.get((line, fn))

    def starts(self, line: int, fn: str) -> bool | None:
        """Whether calls of fn start on this line, or None if that can't be told."""
        if not self._known(line):
            return None
        return (line, fn) in self.params or (line, fn) in self.classes

    def is_class(self, line: int, fn: str) -> bool:
        return (line, fn) in self.classes

    def kind(self, line: int, fn: str) -> str:
        return self.kinds.get((line, fn), "")

    def yields_on(self, line: int, code: str) -> int:
        """How many times a call can stop on the line: its yields, and one for any await."""
        if self._known(line):
            return self.yields[line] + (line in self.awaits)
        return len(YIELDS.findall(_bare(code)))

    def waits_on(self, line: int, code: str) -> bool:
        """Whether a call stopping on the line is awaiting, not yielding."""
        if self._known(line):
            return line in self.awaits and not self.yields[line]
        bare = _bare(code)
        return bool(AWAITS.search(bare)) and not re.search(r"\byield\b", bare)

    def hands_over_on(self, line: int, code: str) -> bool:
        if self._known(line):
            return line in self.hands_over
        return bool(HANDS_OVER.search(_bare(code)))

    def loops_on(self, line: int, code: str) -> bool:
        if self._known(line):
            return line in self.loops
        return bool(LOOPS.search(_bare(code)))

    def comprehension_at(self, line: int) -> tuple[int, int, set[str]] | None:
        """The comprehensions on this line that run inside their function, from 3.12, as the
        lines they span and the names they bind."""
        found = [c for c in self.comprehensions if c[0] <= line <= c[1]]
        if not found:
            return None
        first = min(c[0] for c in found)
        last = max(c[1] for c in found)
        return first, last, {name for c in found for name in c[2]}


def _own(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    """The nodes of a function's own body, leaving out functions, lambdas and classes in it."""
    waiting: list[ast.AST] = list(node.body)
    while waiting:
        child = waiting.pop()
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        yield child
        waiting.extend(ast.iter_child_nodes(child))


def _parameters(
    words: list[tuple[tokenize.TokenInfo, bool]], at: int, lambda_: bool = False
) -> set[str]:
    """The parameter names in a def's brackets or a lambda's head, from its tokens."""
    if not lambda_:  # skip type parameters, as in def first[T](xs)
        while at < len(words) and words[at][0].string not in ("(", ":"):
            at += 1
        at += 1
    names: set[str] = set()
    depth = 0
    before = "lambda" if lambda_ else "("
    for token, _ in words[at:]:
        word = token.string
        if token.type == tokenize.OP and word in "([{":
            depth += 1
        elif token.type == tokenize.OP and word in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and lambda_ and word == ":":
            break
        elif (
            depth == 0 and token.type == tokenize.NAME and before in ("(", ",", "*", "**", "lambda")
        ):
            names.add(word)
        before = word
    return names


def _bare(code: str) -> str:
    """A line's code without its strings and comment, as well as text can tell."""
    return STRINGS.sub("''", code).split("#")[0]


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
    """One line per step: its number, its link, its line and what changed at it."""
    steps, entry = trace["steps"], trace["source"]["entry"]
    lines = source_lines(trace)
    stops = bool(trace.get("truncated") or trace.get("stopped"))
    prints: dict[int, str] = {}
    for at, text in trace.get("stdout", []):
        prints[at] = prints.get(at, "") + text
    narrator = Narrator(trace)
    print("step is the number on the reel's counter, and #step=LINK opens it. Each step shows")
    print("the line about to run, with what changed since the step before. Printed text is")
    print("the exception: it shows on the last step recorded before it was printed (or the")
    print("first step, if none was yet), usually the step of the line that prints it.")
    if not narrator.source.parsed:
        print(
            clean(
                f"This Python can't parse {trace['source']['file']}, so calls and yields are"
                " read from its text, less exactly. A newer Python reads it fully."
            )
        )
    print(f"{'step':>5} {'link':>5} {'line':>4}  {'code':<34}  changes")
    heap: Mapping[int, Any] = {}
    for at, (step, state, old, old_stack) in enumerate(decode(steps)):
        if at + 1 > last:
            break
        listed = at + 1 >= first
        notes = narrator.notes(at, step, state, old, old_stack, listed)
        heap = state["heap"]
        if not listed:
            continue
        if len(notes) > NOTES:
            notes = [*notes[: NOTES - 1], f"… and {len(notes) - NOTES + 1} more changes"]
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


class Narrator:
    """Says what each step did, in a few words: calls, returns, yields and exceptions, the
    variables bound to something new, and the lists, dicts, sets and objects changed in place,
    named the way the code could name them, as in dp[2][3]=4 or cur.next=None."""

    def __init__(self, trace: dict[str, Any]) -> None:
        self.lines = source_lines(trace)
        self.source = Source(trace["source"]["text"])
        self.error = trace.get("error")
        self.finished = "result" in trace
        self.last_run: dict[int, int] = {}  # call id -> the last step it runs at
        self.classes: set[int] = set()  # call ids that run a class body
        self.kinds: dict[int, str] = {}  # call id -> its function's kind, such as coroutine
        self.events: list[tuple[str, int | None, Any]] = []  # each step's event, call, exception
        self.stacks: list[tuple[int, ...]] = []  # each step's call ids, bottom first
        first: dict[int, str] = {}
        fids: tuple[int, ...] = ()
        for at, (step, state, _, _) in enumerate(decode(trace["steps"])):
            if "stack" in step or step.get("key"):
                fids = tuple(frame["fid"] for frame in state["stack"])
            frame = state["stack"][-1] if state["stack"] else None
            fid = frame["fid"] if frame else None
            if frame is not None:
                self.last_run[frame["fid"]] = at
                first.setdefault(frame["fid"], state["ev"])
                local = frame["locals"]
                if "__module__" in local and "__qualname__" in local:
                    self.classes.add(frame["fid"])  # even a decorated class, whose body starts
                    # on its decorator's line
                if state["ev"] == "call" and frame["fid"] not in self.kinds:
                    start = (state["line"], frame["fn"])
                    self.kinds[frame["fid"]] = self.source.kind(*start)
                    if self.source.is_class(*start):
                        self.classes.add(frame["fid"])  # seen at its start, as with --lines
            self.events.append((state["ev"], fid, state.get("exc")))
            self.stacks.append(fids)
        ended = (self.events[-1][0], len(self.stacks[-1])) if self.events else ("", 0)
        self.complete = not lines_only(trace, first, ended)  # every call's caller recorded
        self.seen: set[int] = set()  # call ids that have run
        self.parked: dict[int, dict[str, Any]] = {}  # generator -> its variables when it yielded
        self.raised: dict[int, Any] = {}  # call id -> the exception it last raised or passed on
        self.last: dict[int, tuple[str, int]] = {}  # call id -> its last step's event and line
        self.running: int | None = None  # the call id that ran the step before
        self.at = 0  # the step being told
        self.before: tuple[str, int | None] = ("", None)  # the step before's event and call id
        self.code = ""  # the line the step before ran
        # A comprehension running inside its call, as from 3.12: the call id, the lines it
        # spans, the names it binds, and the call's variables just before it.
        self.span: tuple[int, int, int, set[str], dict[str, Any]] | None = None

    def notes(
        self,
        at: int,
        step: dict[str, Any],
        state: dict[str, Any],
        old: dict[int, Any],
        old_stack: list[Any] | None,
        listed: bool,
    ) -> list[str]:
        frame = state["stack"][-1] if state["stack"] else None
        if frame is None:
            self.before, self.running = (step["ev"], None), None
            return []
        fid, event = frame["fid"], step["ev"]
        # A StopIteration ending a loop, a yield from or an await is never seen by the code.
        ends = event == "exception" and self._ends(state)
        self.at = at
        span = self._comprehension(fid, state)
        notes: list[str] = []
        if listed:
            said = self._say(at, step, state, frame, old, old_stack, ends, span)
            notes = [clean(n) for n in said]
        if event == "exception" and not ends:
            self.raised[fid] = state.get("exc")
        if event == "return" and self.last_run.get(fid, -1) > at:
            self.parked[fid] = dict(frame["locals"])  # a generator yielding, to carry on later
        self.seen.add(fid)
        self.last[fid] = (event, state["line"])
        self.before, self.running = ("ends" if ends else event, fid), fid
        self.code = self._line(state["line"])
        return notes

    def _line(self, n: int) -> str:
        return self.lines[n - 1] if 0 < n <= len(self.lines) else ""

    def _ends(self, state: dict[str, Any]) -> bool:
        exc, line = str(state.get("exc", "")), state["line"]
        stops = re.match(r"Stop(?:Async)?Iteration(?::|$)", exc)
        code = self._line(line)
        return bool(stops) and (
            self.source.hands_over_on(line, code) or self.source.loops_on(line, code)
        )

    def _comprehension(self, fid: int, state: dict[str, Any]) -> Span:
        """Follow a comprehension that runs inside its call, as from Python 3.12, so its
        variables aren't told as the call's own. Gives "inside" while the call runs it and
        "left" on the step after, with the names it binds and the call's variables before
        it, else ""."""
        frame = state["stack"][-1]
        span = self.span
        if span is not None and span[0] not in self.stacks[self.at]:
            self.span = span = None  # its call has ended
        if span is not None and span[0] != fid:
            return ("", set(), {})  # a call made from the comprehension is running
        line = state["line"]
        if span is not None and span[1] <= line <= span[2]:
            return ("inside", span[3], span[4])
        self.span = None
        found = self.source.comprehension_at(line)
        if found is not None and frame["fn"] not in COMPREHENSIONS:
            self.span = (fid, found[0], found[1], found[2], dict(frame["locals"]))
        return ("left", span[3], span[4]) if span is not None else ("", set(), {})

    def _say(
        self,
        at: int,
        step: dict[str, Any],
        state: dict[str, Any],
        frame: dict[str, Any],
        old: dict[int, Any],
        old_stack: list[Any] | None,
        ends: bool,
        span: Span,
    ) -> list[str]:
        heap, fid, event, fn = state["heap"], frame["fid"], step["ev"], frame["fn"]
        line = state["line"]
        notes: list[str] = []
        unseen = event == "call" and fid not in self.seen
        resumed = event == "call" and not unseen
        if unseen and fn not in COMPREHENSIONS and self.source.starts(line, fn) is False:
            # A call that doesn't start where fn begins: a generator that ran before the
            # recording began, carrying on.
            resumed = bool(self.source.yields_on(line, self._line(line)))
        if resumed:
            notes.append(f"resumes {fn}")
            was = self.parked.get(fid, {})
            shared = {
                k: v for f in state["stack"] if f is not frame for k, v in f["locals"].items()
            }
            rebound = {
                k: v
                for k, v in frame["locals"].items()
                if not same(was.get(k, MISSING), v) and not (k in shared and same(shared[k], v))
            }
            notes += self._bound(frame, frame, rebound, [], heap, {})
            notes += self._changes(step, state, frame, old, old_stack, False, span)
        elif event == "call" and fid in self.classes:
            notes.append(f"runs the body of class {fn}")
            notes += self._changes(step, state, frame, old, old_stack, False, span)
        elif event == "call":
            names = set() if fn in COMPREHENSIONS else self.source.parameters(line, fn)
            given = [(k, v) for k, v in frame["locals"].items() if names is None or k in names]
            notes.append(f"call {fn}({', '.join(f'{k}={short(show(v, heap))}' for k, v in given)})")
            notes += self._changes(step, state, frame, old, old_stack, False, span)
        else:
            if fid != self.running:
                notes.append(f"{'back in' if fid in self.seen else 'in'} {fn}")
            notes += self._changes(step, state, frame, old, old_stack, True, span)
        if event == "return":
            notes.append(self._leaves(at, state, frame))
        elif event == "exception" and not ends:
            notes.append(f"raises {short(str(state.get('exc', '')), 2 * WIDTH)}")
        return notes

    def _leaves(self, at: int, state: dict[str, Any], frame: dict[str, Any]) -> str:
        """How a call ends at a return step: returning, yielding, waiting, being closed or
        leaving because of an exception, which the trace also records as a return, of None."""
        fid, ret, heap = frame["fid"], state.get("ret"), state["heap"]
        if ret is None:
            unwinds = self._unwinds(at, state)
            raised = str(self.raised.get(fid, ""))
            if unwinds is None:
                return "returns None, or leaves because of the exception"
            if unwinds:
                return "leaves because of the exception"
            if re.match(r"GeneratorExit(?::|$)", raised):
                return "is closed"
        if fid in self.classes:
            return "finishes the class body"
        if frame["fn"] == "<module>":
            return "the script ends"
        if not self._yields(at, state, fid):
            return f"returns {short(show(ret, heap))}"
        kind, line = self.kinds.get(fid, ""), state["line"]
        if kind == "coroutine" or self.source.waits_on(line, self._line(line)):
            return "waits"  # an await handing control to the event loop
        value = show(ret, heap)
        if kind == "async generator" or value.startswith("<async_generator_wrapped_value"):
            got = self._sent_up(at, state)
            return f"yields {short(got)}" if got is not None else "yields"
        return f"yields {short(value)}"

    def _unwinds(self, at: int, state: dict[str, Any]) -> bool | None:
        """Whether the returning call is leaving because of an exception it raised or passed
        on: its caller gets the same exception next, or runs on if it didn't. Without its
        caller's next step, it goes by the step before (an exception right before), and if
        that can't tell, None."""
        stack = state["stack"]
        fid = stack[-1]["fid"]
        raised = self.raised.get(fid)
        if raised is None:
            return False
        right_after = self.before == ("exception", fid)
        if at + 1 < len(self.events):
            event, after, exc = self.events[at + 1]
            following = self.stacks[at + 1]
            depth = len(stack) - 2  # where the caller sits
            if depth >= 0 and len(following) > depth and following[depth] == stack[depth]["fid"]:
                return event == "exception" and after == stack[depth]["fid"] and exc == raised
            if depth < 0 and self.complete:
                return False  # nothing escaped: an exception here would have ended the run
            return True if right_after else None
        if self.error == raised:
            return True
        if len(stack) > 1:  # the run was cut off before its caller ran again
            return True if right_after else None
        return right_after and not self.finished

    def _yields(self, at: int, state: dict[str, Any], fid: int) -> bool:
        """Whether a call's return is a yield: it carries on later, or it returns on a yield
        line it was about to run, as the last yield of a generator never resumed does."""
        if self.last_run.get(fid, -1) > at:
            return True
        line = state["line"]
        count = self.source.yields_on(line, self._line(line))
        if not count:
            return False
        before = self.last.get(fid)
        if before == ("line", line):
            return True
        # Resumed on a line with two yields, such as yield 1; yield 2, it yields again.
        return before == ("call", line) and count > 1 and state.get("ret") is not None

    def _sent_up(self, at: int, state: dict[str, Any]) -> str | None:
        """The value an async generator yields, which reaches its caller as StopIteration's."""
        below = {f["fid"] for f in state["stack"][:-1]}
        for event, fid, exc in self.events[at + 1 : at + 6]:
            if event == "exception" and fid in below and str(exc).startswith("StopIteration: "):
                return str(exc)[len("StopIteration: ") :]
        return None

    def _changes(
        self,
        step: dict[str, Any],
        state: dict[str, Any],
        frame: dict[str, Any],
        old: dict[int, Any],
        old_stack: list[Any] | None,
        own: bool,
        span: Span,
    ) -> list[str]:
        """Variables bound to something new, then objects changed in place. own says whether
        to include the running call's own variables (a new call's are its arguments)."""
        heap = state["heap"]
        notes: list[str] = []
        # A closure's variable, shared by calls already running, shows once. A call new at
        # this step shows all its variables, even ones named and valued as another call's.
        told: dict[str, Any] = {}
        stack = state["stack"]
        bound: list[tuple[dict[str, Any], dict[str, Any], list[str]]] = []
        if old_stack is not None:  # a keyframe: compare with the whole state before
            before = {f["fid"]: f["locals"] for f in old_stack}
            for f in [frame, *(f for f in reversed(stack) if f is not frame)]:
                if f is frame and not own:
                    continue
                was, now = before.get(f["fid"], {}), f["locals"]  # a new call: all its variables
                sets = {k: v for k, v in now.items() if not same(was.get(k, MISSING), v)}
                bound.append((f, sets, [k for k in was if k not in now]))
            changed = [oid for oid, obj in heap.items() if oid in old and not same(old[oid], obj)]
        else:
            patched = []  # (where on the stack, call, patch): only calls whose variables changed
            for key, patch in step.get("frames", {}).items():
                found = _find(stack, int(key))
                if found is not None and not (found[1] is frame and not own):
                    patched.append((found[0], found[1], patch))
            patched.sort(key=lambda item: (item[1] is not frame, -item[0]))  # running, then inner
            bound = [(f, patch.get("set", {}), patch.get("del", [])) for _, f, patch in patched]
            changed = [oid for oid in old if oid in heap]
        before_ids = self.stacks[self.at - 1] if self.at else ()
        for f, sets, gone in bound:
            tags: dict[str, str] = {}
            if f is frame and span[0]:
                sets, gone, tags = self._in_comprehension(sets, gone, span)
            fresh = f["fid"] not in before_ids
            notes += self._bound(f, frame, sets, gone, heap, {} if fresh else told, tags)
        # An object past the reel's limit of objects is a placeholder at some steps and itself
        # at others, as the objects counted change; that's no change to the object.
        changed = [oid for oid in changed if not (placeholder(old[oid]) or placeholder(heap[oid]))]
        was_heap = ChainMap(old, heap)
        for oid, (path, fn, also) in self._names(changed, state, frame).items():
            said = []
            for name in [path, *also][:NAMED]:  # the change under each name, up to NAMED
                said += in_place(name, old[oid], heap[oid], was_heap, heap)
            if not said:
                continue
            where = f" (in {fn})" if fn else ""
            labels = [f"in {fn}"] if fn else []
            labels += [also_named([path, *also], heap[oid])] if also else []
            last = f" ({'; '.join(labels)})" if labels else ""
            notes += [n + where for n in said[:-1]] + [said[-1] + last]
        return notes

    @staticmethod
    def _in_comprehension(
        sets: dict[str, Any], gone: list[str], span: Span
    ) -> tuple[dict[str, Any], list[str], dict[str, str]]:
        """A call's changes while a comprehension runs inside it, or just after: its own
        variables are tagged, and names the comprehension hides and puts back aren't told."""
        where, names, kept = span
        restored = {k for k, v in sets.items() if k in kept and same(kept[k], v)}
        if where == "inside":
            sets = {k: v for k, v in sets.items() if k in names or k not in restored}
            return sets, [], {k: " (in the comprehension)" for k in sets if k in names}
        sets = {k: v for k, v in sets.items() if k not in restored}
        return sets, [k for k in gone if k not in names], {}

    def _bound(
        self,
        f: dict[str, Any],
        running: dict[str, Any],
        sets: dict[str, Any],
        dels: list[str],
        heap: Mapping[int, Any],
        told: dict[str, Any],
        tags: dict[str, str] | None = None,
    ) -> list[str]:
        where = "" if f is running else f"in {f['fn']}"
        hidden = f["fid"] in self.classes  # a class body, whose bookkeeping isn't shown
        notes = []
        for name, value in sets.items():
            if (hidden and name in BOOKKEEPING) or (name in told and same(told[name], value)):
                continue
            told[name] = value
            extra = [where] if where else []
            obj = heap.get(value["ref"]) if _is_ref(value) else None
            if obj is not None:
                rows = _shared(name, obj, heap)
                extra += [rows] if rows else []
            tail = f" ({'; '.join(extra)})" if extra else ""
            notes.append(f"{name}={short(show(value, heap))}{(tags or {}).get(name, '')}{tail}")
        gone = [name for name in dels if not (hidden and name in BOOKKEEPING)]
        return notes + [f"del {name}{f' ({where})' if where else ''}" for name in gone]

    def _names(
        self, changed: list[int], state: dict[str, Any], running: dict[str, Any]
    ) -> dict[int, tuple[str, str, list[str]]]:
        """For each changed object, the shortest way to name it from a variable, such as dp[2]
        or head.next, the call whose variable it is (blank for the running one), and other
        names for it that are as short and in the same container, as when dp = [[0] * 3] * 3
        makes every row one list, or two variables of the call that hold one list or dict.
        The running call is searched first, and among names equally short, one the line that
        just ran uses comes first. Each object is looked through once, and only as deep as
        the changed objects are."""
        heap, wanted = state["heap"], set(changed)
        found: dict[int, tuple[str, str, list[str]]] = {}
        seen: set[int] = set()
        used = set(WORDS.findall(self.code))
        others = [f for f in reversed(state["stack"]) if f is not running]
        for frame in [running, *others]:
            if not wanted:
                break
            fn = "" if frame is running else frame["fn"]
            hidden = frame["fid"] in self.classes
            level: list[tuple[str, int, str]] = [
                (name, v["ref"], "")
                for name, v in frame["locals"].items()
                if _is_ref(v) and not (hidden and name in BOOKKEEPING)
            ]
            level.sort(key=lambda item: item[0] not in used)
            while level and wanted and len(seen) < SEARCHED:
                here: dict[int, tuple[str, list[str]]] = {}  # found at this depth: parent, names
                fresh: list[tuple[str, int]] = []
                for path, oid, parent in level:
                    if oid in here:
                        first_parent, paths = here[oid]
                        obj = heap.get(oid)
                        if parent == first_parent and (parent or (obj and _container(obj))):
                            paths.append(path)
                        continue
                    if oid in seen:
                        continue
                    seen.add(oid)
                    if oid in wanted:
                        here[oid] = (parent, [path])
                    fresh.append((path, oid))
                for oid, (_, paths) in here.items():
                    found[oid] = (paths[0], fn, paths[1:])
                    wanted.discard(oid)
                if not wanted:
                    break
                level = []
                for path, oid in fresh:
                    obj = heap.get(oid)
                    if obj is not None:
                        level += [
                            (child, inner, path) for child, inner in _children(path, obj, heap)
                        ]
        return found


def _find(stack: list[dict[str, Any]], fid: int) -> tuple[int, dict[str, Any]] | None:
    """Where the call with this id is on the stack, and the call: looked for at the top and
    the bottom first, where changed calls usually are, so a deep stack costs little."""
    last = len(stack) - 1
    if stack and stack[last]["fid"] == fid:
        return last, stack[last]
    if stack and stack[0]["fid"] == fid:
        return 0, stack[0]
    for i in range(last - 1, 0, -1):
        if stack[i]["fid"] == fid:
            return i, stack[i]
    return None


def _is_ref(value: Any) -> bool:
    return isinstance(value, dict) and "ref" in value


def _container(obj: dict[str, Any]) -> bool:
    """Whether obj is a list, dict, set or deque, which two names holding is worth a word."""
    return obj["t"] == "map" or (obj["t"] == "seq" and obj["cls"] in ("list", "set", "deque"))


def _children(path: str, obj: dict[str, Any], heap: Mapping[int, Any]) -> list[tuple[str, int]]:
    """The objects obj holds, each with how the code would name it."""
    kind = obj["t"]
    if kind == "obj":
        fields = obj.get("fields", {}).items()
        return [(f"{path}.{name}", v["ref"]) for name, v in fields if _is_ref(v)]
    if kind == "map":
        items = obj.get("items", [])
        return [(f"{path}[{show(k, heap)}]", v["ref"]) for k, v in items if _is_ref(v)]
    if kind == "seq" and obj["cls"] not in ("set", "frozenset"):
        items = obj.get("items", [])
        return [(f"{path}[{i}]", v["ref"]) for i, v in enumerate(items) if _is_ref(v)]
    return []


def _shared(path: str, obj: dict[str, Any], heap: Mapping[int, Any]) -> str:
    """For a container holding one list, dict, set or object more than once, as
    [[0] * n] * n does, says so, as in dp[0] and dp[1] are the same list."""
    if obj["t"] not in ("seq", "map"):
        return ""
    by_oid: dict[int, list[str]] = {}
    for child, oid in _children(path, obj, heap):
        by_oid.setdefault(oid, []).append(child)
    for oid, paths in by_oid.items():
        inner = heap.get(oid)
        if len(paths) > 1 and inner is not None and (_container(inner) or inner["t"] == "obj"):
            return also_named(paths, inner)
    return ""


def also_named(names: list[str], obj: dict[str, Any]) -> str:
    """Says that several names reach one object, as in dp[0], dp[1] and dp[2] are the same
    list."""
    shown, rest = names[:NAMED], len(names) - NAMED
    if rest > 0:
        listed = f"{', '.join(shown)} and {rest} more"
    else:
        listed = f"{', '.join(shown[:-1])} and {shown[-1]}"
    kind = "dict" if obj["t"] == "map" else obj["cls"]
    return f"{listed} are the same {kind if kind in ('list', 'dict', 'set', 'deque') else 'object'}"


def in_place(
    path: str,
    old: dict[str, Any],
    new: dict[str, Any],
    was_heap: Mapping[int, Any],
    heap: Mapping[int, Any],
) -> list[str]:
    """What changed in one list, dict, set or object that stayed the same object, as
    statements such as a[2]=5, a.append(7), del d['k'], s |= {3} or node.next=None, or its
    new value when too much changed to list, as a[:]=[…] or d={…} (changed in place), which
    tells it apart from binding a name to a new object."""

    def whole() -> list[str]:
        value = short(show_object(new, heap))
        if new["cls"] == "list":
            return [f"{path}[:]={value}"]
        return [f"{path}={value} (changed in place)"]

    if old["t"] != new["t"] or old["cls"] != new["cls"] or new["t"] == "repr":
        return [] if same(old, new) else whole()
    kind, cls = new["t"], new["cls"]
    notes: list[str] = []
    if kind == "obj":
        was, now = old.get("fields", {}), new.get("fields", {})
        notes += [
            f"{path}.{k}={short(show(v, heap))}"
            for k, v in now.items()
            if not same(was.get(k, MISSING), v)
        ]
        notes += [f"del {path}.{k}" for k in was if k not in now]
        return notes
    a, b = old.get("items", []), new.get("items", [])
    size = len(b) + new.get("more", 0)
    grown = size - len(a) - old.get("more", 0)
    if old.get("more") or new.get("more"):
        # Only the first items are kept, so items move into view and out of it as others
        # come and go: report the size, or items changed where they stand.
        if grown:
            notes.append(f"len({path})={size}")
        elif kind == "map":
            olds, news = _keyed(a, b, was_heap, heap)
            if list(olds) != list(news):
                return whole()  # keys moved, or one went and another came: can't tell which
            for key, (k, v) in news.items():
                if not same(olds[key][1], v):
                    notes.append(f"{path}[{show(k, heap)}]={short(show(v, heap))}")
        elif cls not in ("set", "frozenset") and len(a) == len(b):
            notes += [
                f"{path}[{i}]={short(show(b[i], heap))}"
                for i in range(len(b))
                if not same(a[i], b[i])
            ]
        elif not same(a, b):
            return whole()
    elif kind == "map":
        olds, news = _keyed(a, b, was_heap, heap)
        notes += [
            f"{path}[{show(k, heap)}]={short(show(v, heap))}"
            for key, (k, v) in news.items()
            if key not in olds or not same(olds[key][1], v)
        ]
        notes += [
            f"del {path}[{show(k, was_heap)}]" for key, (k, _) in olds.items() if key not in news
        ]
        keys = {key: show(k, heap) for key, (k, _) in news.items()}
        moved = _moved(
            path, cls, [keys[k] for k in olds if k in news], [keys[k] for k in news if k in olds]
        )
        if moved is None:
            return [f"{path}={short(show_object(new, heap))} (reordered)"]
        notes += moved
    elif cls in ("set", "frozenset"):
        old_items, new_items = _keyed(
            [[v, None] for v in a], [[v, None] for v in b], was_heap, heap
        )
        olds_set = {key: k for key, (k, _) in old_items.items()}
        news_set = {key: k for key, (k, _) in new_items.items()}
        gained = [show(v, heap) for key, v in news_set.items() if key not in olds_set]
        lost = [show(v, was_heap) for key, v in olds_set.items() if key not in news_set]
        notes += [f"{path} |= {{{short(', '.join(gained))}}}"] if gained else []
        notes += [f"{path} -= {{{short(', '.join(lost))}}}"] if lost else []
    else:
        notes += _sequence(path, cls, a, b, heap)
    return whole() if len(notes) > 4 else notes


def _keyed(
    a: list[Any], b: list[Any], was_heap: Mapping[int, Any], heap: Mapping[int, Any]
) -> tuple[dict[tuple[str, Any], tuple[Any, Any]], dict[tuple[str, Any], tuple[Any, Any]]]:
    """A dict's [key, value] items before and after, by key, in order. A key that is an
    object, such as a tuple, is matched by its object, which stays the same even when it's
    past the reel's limit of objects and doesn't show; failing that, by how it prints, as a
    key deleted and added again is a new object that Python takes for the same key."""

    def ident(key: Any, objects: Mapping[int, Any]) -> tuple[str, Any]:
        return ("object", key["ref"]) if _is_ref(key) else ("text", show(key, objects))

    olds = {ident(k, was_heap): (k, v) for k, v in a}
    news = {ident(k, heap): (k, v) for k, v in b}
    lost = {}
    for key, (k, _) in olds.items():
        text = show(k, was_heap)
        if key[0] == "object" and key not in news and "…" not in text:
            lost[text] = key
    renamed = {}
    for key, (k, _) in news.items():
        text = show(k, heap)
        if key[0] == "object" and key not in olds and "…" not in text and text in lost:
            renamed[key] = lost.pop(text)
    return olds, {renamed.get(key, key): item for key, item in news.items()}


def _moved(path: str, cls: str, before: list[str], after: list[str]) -> list[str] | None:
    """How a dict's keys moved, given the keys it kept, in their old order and their new one:
    no note if they kept their places, one if a single key moved to the end or the front,
    as OrderedDict.move_to_end does, and None if they moved some other way."""
    if before == after:
        return []
    end, front = after[-1], after[0]
    if [k for k in before if k != end] + [end] == after:
        if cls == "OrderedDict":
            return [f"{path}.move_to_end({end})"]
        return [f"{path}[{end}] moved to the end"]
    if [front] + [k for k in before if k != front] == after:
        if cls == "OrderedDict":
            return [f"{path}.move_to_end({front}, last=False)"]
        return [f"{path}[{front}] moved to the front"]
    return None


def _sequence(
    path: str, cls: str, a: list[Any], b: list[Any], heap: Mapping[int, Any]
) -> list[str]:
    """A list's or deque's change: the run of items between the parts that stayed put, or a
    deque's rotation."""
    if cls == "deque" and len(a) == len(b) > 1:
        n = len(a)
        for k in range(1, n):
            if all(same(b[i], a[(i - k) % n]) for i in range(n)):
                if not all(same(a[i], a[0]) for i in range(n)):
                    return [f"{path}.rotate({k if k <= n // 2 else k - n})"]
                break
    p = 0
    while p < len(a) and p < len(b) and same(a[p], b[p]):
        p += 1
    s = 0
    while s < len(a) - p and s < len(b) - p and same(a[-1 - s], b[-1 - s]):
        s += 1
    removed, added = a[p : len(a) - s], b[p : len(b) - s]
    listed = short(", ".join(show(v, heap) for v in added))
    if not removed and not added:
        return []
    deque = cls == "deque" and len(removed) + len(added) == 1
    if not removed:
        if p == len(a):
            return [f"{path}.append({listed})" if len(added) == 1 else f"{path} += [{listed}]"]
        if deque and p == 0:
            return [f"{path}.appendleft({listed})"]
        return [
            f"{path}.insert({p}, {listed})" if len(added) == 1 else f"{path}[{p}:{p}] = [{listed}]"
        ]
    if not added:
        if deque and p == 0:
            return [f"{path}.popleft()"]
        if deque and p == len(a) - 1:
            return [f"{path}.pop()"]
        return [f"del {path}[{p}]" if len(removed) == 1 else f"del {path}[{p}:{p + len(removed)}]"]
    if len(removed) == len(added):
        changed = [i for i in range(len(added)) if not same(removed[i], added[i])]
        return [f"{path}[{p + i}]={short(show(added[i], heap))}" for i in changed]
    return [f"{path}[{p}:{p + len(removed)}] = [{listed}]"]


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
