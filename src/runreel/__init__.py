"""RunReel: turn any algorithm into an interactive step-through reel."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("runreel")
except PackageNotFoundError:  # running from a source tree that isn't installed, e.g. in Pyodide
    __version__ = "0.0.0+unknown"
