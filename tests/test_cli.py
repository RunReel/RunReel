from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

import runreel.reel
from runreel import __version__
from runreel.cli import main, parse_lines

ROOT = Path(__file__).parent.parent
STUB = "window.RunReelPlayer={mount(){}};"


@pytest.fixture(autouse=True)
def stub_player(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests check the CLI, so they don't need the built player."""
    monkeypatch.setattr(runreel.reel, "player_js", lambda: STUB)


def embedded_trace(page: Path) -> dict[str, object]:
    match = re.search(r'id="runreel-trace">(.*?)</script>', page.read_text(encoding="utf-8"), re.S)
    assert match
    data: dict[str, object] = json.loads(match.group(1))
    return data


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"runreel {__version__}"


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: runreel" in capsys.readouterr().out


def test_spec_acceptance_one_writes_the_reel_next_to_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # SPEC §10, stage 0, acceptance 1: runreel run examples/dijkstra.py --call "dijkstra(G, 0)"
    examples = tmp_path / "examples"
    examples.mkdir()
    shutil.copy(ROOT / "examples" / "dijkstra.py", examples)
    assert main(["run", str(examples / "dijkstra.py"), "--call", "dijkstra(G, 0)"]) == 0
    reel = examples / "dijkstra.reel.html"
    trace = embedded_trace(reel)
    steps = 60 if sys.version_info >= (3, 12) else 63  # 3.12+ runs the dict comprehension inline
    assert len(trace["steps"]) == steps  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert out.startswith(f"reel: {reel} (")
    assert f"{steps} steps · result {{0: 0, 1: 3, 2: 1, 3: 4}}" in out


def test_script_with_input_lines_and_no_mark(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = tmp_path / "sum.py"
    script.write_text(
        "n = int(input())\ntotal = 0\nfor i in range(n):\n    total += i\nprint(total)\n"
    )
    data = tmp_path / "in.txt"
    data.write_text("4\n")
    out = tmp_path / "r.html"
    args = [
        "run",
        str(script),
        "--stdin",
        str(data),
        "--lines",
        "3-4",
        "--out",
        str(out),
        "--no-mark",
    ]
    assert main(args) == 0
    trace = embedded_trace(out)
    assert {step["line"] for step in trace["steps"]} == {3, 4}  # type: ignore[attr-defined]
    assert trace["stdout"] == [[8, "6\n"]]
    assert '{"mark": false}' in out.read_text(encoding="utf-8")
    assert "printed 1 line" in capsys.readouterr().out


def test_an_error_in_the_program_still_writes_the_reel(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = tmp_path / "bad.py"
    script.write_text("def f(a):\n    return a[3]\n")
    assert main(["run", str(script), "--call", "f([1])"]) == 0
    assert (tmp_path / "bad.reel.html").exists()
    assert "error IndexError: list index out of range" in capsys.readouterr().out


def test_truncation_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    script = tmp_path / "loop.py"
    script.write_text("n = 0\nwhile n < 100:\n    n += 1\n")
    assert main(["run", str(script), "--max-steps", "5"]) == 0
    assert "5 steps (truncated: raise --max-steps to see more)" in capsys.readouterr().out


def test_open_shows_the_reel_in_the_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    script = tmp_path / "x.py"
    script.write_text("x = 1\n")
    assert main(["run", str(script), "--open"]) == 0
    assert opened == [(tmp_path / "x.reel.html").resolve().as_uri()]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (None, "can't read"),
        ("def f(:\n", "doesn't compile: "),
        ("raise ValueError('boom')\n", "failed while loading: ValueError: boom"),
    ],
)
def test_files_that_cant_run_exit_with_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str | None, message: str
) -> None:
    script = tmp_path / "p.py"
    if text is not None:
        script.write_text(text)
    assert main(["run", str(script), "--call", "f()"]) == 1
    assert message in capsys.readouterr().err


def test_a_missing_player_exits_with_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def missing() -> str:
        raise FileNotFoundError("the player isn't built yet; run `make build`")

    monkeypatch.setattr(runreel.reel, "player_js", missing)
    script = tmp_path / "x.py"
    script.write_text("x = 1\n")
    assert main(["run", str(script)]) == 1
    assert "make build" in capsys.readouterr().err


def test_line_ranges() -> None:
    assert parse_lines("3") == {3}
    assert parse_lines("12-14,20") == {12, 13, 14, 20}
    for bad in ["", "x", "5-3", "0-2", "1-"]:
        with pytest.raises(Exception, match="not a line range"):
            parse_lines(bad)


@pytest.mark.parametrize("args", [["--lines", "a"], ["--max-steps", "0"]])
def test_bad_arguments_exit_with_2(tmp_path: Path, args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["run", str(tmp_path / "x.py"), *args])
    assert exc.value.code == 2
