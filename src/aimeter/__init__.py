"""AI Stupid Meter CLI — check model score trends."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("aimeter")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
