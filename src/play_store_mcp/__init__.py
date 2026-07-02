"""Play Store MCP Server - Google Play Developer API integration via MCP."""

from importlib.metadata import PackageNotFoundError, version

from play_store_mcp.server import main

try:
    # Single source of truth: the version declared in pyproject.toml.
    __version__ = version("play-store-mcp")
except PackageNotFoundError:  # pragma: no cover - source checkout without install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__", "main"]
