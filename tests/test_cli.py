from __future__ import annotations

import pytest

from runreel import __version__
from runreel.cli import main


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"runreel {__version__}"


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: runreel" in capsys.readouterr().out


def test_run_is_not_implemented_yet(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "example.py"]) == 2
    assert "not implemented yet" in capsys.readouterr().err
