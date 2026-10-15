from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from runreel.reel import player_js, render_reel, write_reel
from runreel.trace import Trace, record

ROOT = Path(__file__).parent.parent
STUB = "window.RunReelPlayer={mount(){}};"


def example() -> Trace:
    return record(ROOT / "examples" / "dijkstra.py", "dijkstra(G, 0)")


def embedded_trace(page: str) -> object:
    match = re.search(
        r'<script type="application/json" id="runreel-trace">(.*?)</script>', page, re.S
    )
    assert match
    return json.loads(match.group(1))


def test_the_trace_survives_the_round_trip() -> None:
    trace = example()
    assert embedded_trace(render_reel(trace, player=STUB)) == json.loads(json.dumps(trace))


def test_nothing_loads_from_the_network() -> None:
    page = render_reel(example(), player=STUB)
    assert not re.search(r"<(script|link|img|iframe)[^>]+(src|href)=", page)
    assert "http" not in page.replace("https://github.com/RunReel/RunReel", "")


def test_code_that_mentions_script_tags_cant_break_the_page(tmp_path: Path) -> None:
    trace = example()
    trace["source"]["text"] += "\n# </script><script>alert(1)</script>\n"
    page = render_reel(trace, player=STUB + "/*</SCRIPT>*/")
    assert page.lower().count("</script>") == 3  # only the page's own three tags
    assert embedded_trace(page) == json.loads(json.dumps(trace))
    assert "<title>dijkstra.py · dijkstra(G, 0) · RunReel</title>" in page


def test_the_mark_can_be_turned_off(tmp_path: Path) -> None:
    out = write_reel(example(), tmp_path / "r.html", player=STUB, mark=False)
    assert '{"mark": false}' in out.read_text(encoding="utf-8")


def test_a_1000_step_reel_stays_within_budget(tmp_path: Path) -> None:
    program = tmp_path / "sort.py"
    program.write_text(
        "def bubble(a):\n"
        "    for i in range(len(a)):\n"
        "        for j in range(len(a) - 1 - i):\n"
        "            if a[j] > a[j + 1]:\n"
        "                a[j], a[j + 1] = a[j + 1], a[j]\n"
        "    return a\n",
        encoding="utf-8",
    )
    trace = record(program, f"bubble({list(range(60, 0, -1))})", max_steps=1000)
    try:
        player = player_js()
    except FileNotFoundError:
        player = STUB
    assert len(render_reel(trace, player=player).encode()) < 1_000_000


def test_the_packaged_player_is_used_when_built() -> None:
    try:
        player = player_js()
    except FileNotFoundError:
        pytest.skip("player not built; `make build` copies it into the package")
    assert "RunReelPlayer" in player
    assert player in render_reel(example())
