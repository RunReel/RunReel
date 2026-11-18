"""The reel Agent Skill in skills/reel: it follows the Agent Skills format and stays portable,
its links lead to its own files, and the commands, options, limits, names and step counts it
teaches match the command line, the code and the player."""

from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path

import pytest
from test_read_reel import read_reel

from runreel.cli import build_parser
from runreel.trace.serialize import MAX_ITEMS, MAX_OBJECTS, MAX_STR
from runreel.trace.tracer import MAX_OUTPUT, MAX_STEPS, TIMEOUT

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "skills" / "reel"
PLAYER = ROOT / "player" / "src"
GOLDEN = Path(__file__).parent / "fixtures" / "golden"
# The fields the Agent Skills specification allows; some tools reject a SKILL.md with any other.
# The parser below reads one-line values only, so a metadata map would fail it.
FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
# A runreel command, possibly run through uv, uvx or an outer time limit, with runreel's own
# part captured.
COMMAND = r"(?:(?:uvx|uv run|uv tool run)(?: --[a-z-]+ \S+)* |timeout \d+ )?(runreel(?: [^`\n]*)?)"
TIMES = "\u00d7"  # the multiplication sign the pages use, as in a grid size or a speed
SHELL = re.compile(r" (?:<|>|\||2>|&&) ")  # where a shell redirection or a second command starts


def pages() -> list[Path]:
    return sorted(SKILL.rglob("*.md"))


def frontmatter() -> dict[str, str]:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md has to start with its frontmatter"
    head, end, _ = text[4:].partition("\n---\n")
    assert end, "the frontmatter has to end with a line of ---"
    fields: dict[str, str] = {}
    for line in head.splitlines():
        key, colon, value = line.partition(": ")
        assert colon and key not in fields, f"not a plain `key: value` line: {line!r}"
        fields[key] = value
    return fields


def test_the_frontmatter_follows_the_agent_skills_format() -> None:
    fields = frontmatter()
    assert set(fields) <= FIELDS
    assert fields["name"] == SKILL.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fields["name"]) and len(fields["name"]) <= 64
    assert not re.search("anthropic|claude", fields["name"])  # names some tools reserve
    assert 1 <= len(fields["description"]) <= 1024
    assert len(fields.get("compatibility", "")) <= 500
    for key, value in fields.items():
        # Plain YAML values: each of these would end a value early, turn it into a comment, a
        # list or a mapping, or read as a boolean, null or number, and some tools refuse
        # angle brackets.
        assert not re.search(r":(\s|$)|\s#|---|[<>\t]", value), key
        assert not value.startswith(tuple("#-?:,[]{}`'\"&*!|>%@")), key
        assert not re.fullmatch(
            r"(?i)y|n|yes|no|on|off|true|false|null|~|[-+]?(\.\d+|\d[\d_]*(\.\d*)?)([eE][-+]?\d+)?",
            value,
        ), key


def test_the_body_stays_short() -> None:
    """The body loads whole every time the skill is used, and a tool that compacts its context
    may keep only its first 5,000 tokens, so it stays under about 4,400 (17,500 characters)."""
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) < 500
    assert len(text) <= 17_500


def test_the_skill_carries_its_licence() -> None:
    """Installers copy the skill's folder alone, and MIT asks for the notice to go with it."""
    assert frontmatter()["license"] == "MIT. LICENSE.txt has the full terms"
    licence = (SKILL / "LICENSE.txt").read_text(encoding="utf-8")
    assert licence == (ROOT / "LICENSE").read_text(encoding="utf-8")


def test_it_uses_nothing_only_one_tool_understands() -> None:
    """Shell commands run when the skill loads (!`...`) and variables such as $ARGUMENTS or
    ${CLAUDE_SKILL_DIR} work in Claude Code alone, and break the skill everywhere else."""
    for page in pages():
        text = page.read_text(encoding="utf-8")
        assert not re.search(r"(^|\s)!`|```!|\$ARGUMENTS|\$\{CLAUDE_|\$[0-9]\b", text), page.name


def links(page: Path) -> list[str]:
    targets = re.findall(r"\]\(([^)\s#]+)", page.read_text(encoding="utf-8"))
    return [target for target in targets if "://" not in target]


def test_skill_md_links_to_each_reference_page() -> None:
    linked = {(SKILL / target).resolve() for target in links(SKILL / "SKILL.md")}
    for target in linked:
        assert target.is_file() and SKILL.resolve() in target.parents, target
    references = {page.resolve() for page in (SKILL / "references").glob("*.md")}
    assert references and references <= linked


def test_reference_pages_link_to_nothing_else() -> None:
    """References stay one level deep: an agent reads a page it was sent to, not a chain."""
    for page in (SKILL / "references").glob("*.md"):
        assert links(page) == [], page.name


def test_the_scripts_it_names_exist() -> None:
    named = set()
    for page in pages():
        named |= set(re.findall(r"scripts/[\w.]+\.py", page.read_text(encoding="utf-8")))
    assert named == {"scripts/read_reel.py"}
    assert all((SKILL / script).is_file() for script in named)


def commands() -> list[str]:
    """runreel's part of every runreel command in the skill: lines of its shell blocks, and
    inline code, without any shell redirection after it."""
    found: list[str] = []
    for page in pages():
        text = page.read_text(encoding="utf-8")
        for block in re.findall(r"```sh\n(.*?)```", text, re.S):
            for line in block.splitlines():
                command = re.fullmatch(COMMAND, line)
                found += [command.group(1)] if command else []
        found += [m.group(1) for m in re.finditer(rf"`{COMMAND}`", text)]
    found = [c for c in found if not re.match(r"runreel( run)?:", c)]  # quoted messages
    found = [c for c in found if "..." not in c.split()]  # outlines such as runreel run ...
    return [SHELL.split(c)[0] for c in found]


def test_there_are_commands_to_check() -> None:
    assert len(commands()) >= 8


def test_every_read_reel_command_is_accepted() -> None:
    parser = read_reel().build_parser()
    found = 0
    for page in pages():
        for line in page.read_text(encoding="utf-8").splitlines():
            if "scripts/read_reel.py" in line and line.startswith("python3 "):
                parser.parse_args(shlex.split(line)[2:])  # exits 2 if an option is wrong
                found += 1
    assert found >= 4


@pytest.mark.parametrize("command", commands())
def test_every_command_in_the_skill_is_accepted(command: str) -> None:
    argv = shlex.split(command)[1:]
    try:
        build_parser().parse_args(argv)
    except SystemExit as stop:  # --version and --help exit 0; anything wrong exits 2
        assert stop.code == 0, command


def options() -> set[str]:
    parser = build_parser()
    run = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    every = [*parser._actions, *run.choices["run"]._actions]
    return {name for action in every for name in action.option_strings}


def test_every_option_the_skill_mentions_exists() -> None:
    known = options()
    mentioned = set()
    for page in pages():
        for span in re.findall(r"`([^`\n]+)`", page.read_text(encoding="utf-8")):
            # Options in a runreel command, or standing alone. Options before runreel are
            # uv's, options after a bare -- are the program's, and other commands are skipped.
            if "runreel" in span:
                ours = span.split("runreel", 1)[1]
            elif span.startswith("--"):
                ours = span
            else:
                continue
            ours = SHELL.split(ours.split(" -- ")[0])[0]
            mentioned |= set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", ours))
    assert mentioned and mentioned <= known, sorted(mentioned - known)


def test_the_limits_it_gives_are_the_codes() -> None:
    text = (SKILL / "references" / "troubleshooting.md").read_text(encoding="utf-8")
    for row, value in [
        ("Steps recorded", f"{MAX_STEPS:,} (`--max-steps`)"),
        ("Time", f"{TIMEOUT:g} s (`--timeout`, 0 for none)"),
        ("Items per list, tuple, set or dict", f"{MAX_ITEMS:,}"),
        ("Objects per step", f"{MAX_OBJECTS:,}"),
        ("Characters per string", f"{MAX_STR:,}"),
        ("Printed text", f"{MAX_OUTPUT:,} characters"),
    ]:
        assert f"| {row} | {value} |" in text, row
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert f"{MAX_STEPS:,} by default" in skill and f"{TIMEOUT:g} s by default" in skill


def constant(file: str, name: str) -> str:
    """The value of a constant in the player's source, as written there."""
    found = re.search(rf"const {name} = (.+?);", (PLAYER / file).read_text(encoding="utf-8"))
    assert found, name
    return found.group(1)


def test_the_pictures_page_matches_the_player() -> None:
    page = (SKILL / "references" / "pictures.md").read_text(encoding="utf-8")
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert f"cuts each value at {constant('view/format.ts', 'MAX_TEXT')} characters" in page
    assert f"Grids over {int(constant('view/infer.ts', 'GRID_CELLS')):,} cells" in page
    window = re.fullmatch(
        r"\{ rows: (\d+), cols: (\d+) \}", constant("view/infer.ts", "GRID_WINDOW")
    )
    assert window and f"a {window[1]} {TIMES} {window[2]} window" in page
    assert f"Chains over {constant('view/infer.ts', 'LIST_NODES')} nodes" in page
    assert f"at most {constant('view/infer.ts', 'LIST_ROWS')} chains" in page
    for names in ["POINTER_NAMES", "CURRENT_NAMES", "NEXT_NAMES", "DIST_NAMES", "VISITED_NAMES"]:
        listed = re.findall(r'"(\w+)"', constant("view/infer.ts", names))
        assert listed and all(f"`{name}`" in page for name in listed), names
    speeds = json.loads(constant("ui/model.ts", "SPEEDS"))
    assert f"from {speeds[0]:g}{TIMES} to {speeds[-1]:g}{TIMES}" in skill
    assert constant("ui/model.ts", "STEPS_PER_SECOND") == "2"
    assert "two steps a second" in page and "two steps a second" in skill


def test_the_step_counts_it_quotes_are_the_goldens() -> None:
    def count(family: str, name: str) -> int:
        trace = json.loads((GOLDEN / family / f"{name}.json").read_text(encoding="utf-8"))
        return len(trace["steps"])

    page = (SKILL / "references" / "pictures.md").read_text(encoding="utf-8")
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    searched = f"binary search on 7 items takes {count('py312', 'binary_search')} steps"
    assert searched in page and searched in skill
    assert f"binary search tree {count('py312', 'bst_insert')}" in page
    assert f"4 nodes and 5 edges {count('py312', 'dijkstra')}" in page
    assert f"strings of 7 and 6 characters {count('py312', 'lcs')}" in page
    assert f"(Dijkstra {count('py310', 'dijkstra')}, the table {count('py310', 'lcs')})" in page
