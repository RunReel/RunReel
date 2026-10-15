"""Write a trace and the player into one self-contained HTML file that works offline."""

from __future__ import annotations

import html
import json
import re
from importlib import resources
from pathlib import Path

from runreel.trace import Trace

PLAYER = "_player/player.js"  # copied into the package by `make build`


def player_js() -> str:
    """The bundled player shipped inside the package."""
    try:
        return resources.files("runreel").joinpath(PLAYER).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError("the player isn't built yet; run `make build`") from None


def render_reel(trace: Trace, *, player: str | None = None, mark: bool = True) -> str:
    """The reel's HTML. Nothing in it loads from the network."""
    data = json.dumps(trace, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    data = data.replace("<", "\\u003c")  # so the trace can never close its <script> tag
    script = re.sub(
        r"</(script)", r"<\\/\1", player if player is not None else player_js(), flags=re.I
    )
    source = trace["source"]
    title = html.escape(
        f"{source['file']} · {source['entry']}" if source["entry"] else source["file"]
    )
    options = json.dumps({"mark": mark})
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="generator" content="RunReel">\n'
        f"<title>{title} · RunReel</title>\n</head>\n<body>\n"
        '<div id="runreel"></div>\n'
        f'<script type="application/json" id="runreel-trace">{data}</script>\n'
        f"<script>{script}</script>\n"
        '<script>RunReelPlayer.mount(document.getElementById("runreel"), '
        f'JSON.parse(document.getElementById("runreel-trace").textContent), {options});</script>\n'
        "</body>\n</html>\n"
    )


def write_reel(
    trace: Trace, path: str | Path, *, player: str | None = None, mark: bool = True
) -> Path:
    """Write the reel to path and return it."""
    out = Path(path)
    out.write_text(render_reel(trace, player=player, mark=mark), encoding="utf-8")
    return out
