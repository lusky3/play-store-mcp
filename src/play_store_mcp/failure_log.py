"""Opt-in log of failed tool calls.

MCP clients record that a tool call completed, not what it answered, so a tool
that returns ``{"error": ...}`` looks like a success in every client log. When
``PLAY_STORE_MCP_FAILURE_LOG`` is on, this middleware appends each failed call
to a JSON-lines file. It sits above the tools, so it also sees argument
validation failures and, with code-mode on, the inner calls made by ``execute``.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from fastmcp.server.middleware import Middleware

if TYPE_CHECKING:
    import mcp.types as mt
    from fastmcp.server.middleware import CallNext, MiddlewareContext
    from fastmcp.tools import ToolResult

logger = structlog.get_logger(__name__)

ENABLE_ENV = "PLAY_STORE_MCP_FAILURE_LOG"
PATH_ENV = "PLAY_STORE_MCP_FAILURE_LOG_PATH"

MAX_BYTES = 5 * 1024 * 1024
MAX_STRING = 500
MAX_ERROR = 2000
MAX_ITEMS = 20
MAX_DEPTH = 5

# Argument names are compared lowercased with separators removed, so
# purchase_token, purchaseToken and PURCHASE-TOKEN all match "token".
_SECRET_MARKERS = (
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "apikey",
    "privatekey",
    "accesskey",
    "authorization",
)
_REDACTED = "[redacted]"


def enabled() -> bool:
    """Return True if PLAY_STORE_MCP_FAILURE_LOG is set to a truthy value (default off)."""
    return os.environ.get(ENABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def log_path() -> Path:
    """Return the configured log path, else $XDG_STATE_HOME (or ~/.local/state)."""
    configured = os.environ.get(PATH_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    base = Path(state_home) if state_home else Path.home() / ".local" / "state"
    return base / "play-store-mcp" / "tool-failures.jsonl"


def _is_secret(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(marker in normalized for marker in _SECRET_MARKERS)


def _sanitize(value: Any, depth: int = 0) -> Any:
    """Redact secret-named keys and truncate long values, recursively."""
    if depth > MAX_DEPTH:
        return "[truncated: nested too deeply]"
    if isinstance(value, dict):
        return _sanitize_mapping(value, depth)
    if isinstance(value, list | tuple):
        return _sanitize_sequence(value, depth)
    return _sanitize_scalar(value)


def _sanitize_mapping(value: dict[Any, Any], depth: int) -> dict[str, Any]:
    return {
        str(key): _REDACTED if _is_secret(str(key)) else _sanitize(item, depth + 1)
        for key, item in value.items()
    }


def _sanitize_sequence(value: list[Any] | tuple[Any, ...], depth: int) -> list[Any]:
    items = [_sanitize(item, depth + 1) for item in value[:MAX_ITEMS]]
    if len(value) > MAX_ITEMS:
        items.append(f"[{len(value) - MAX_ITEMS} more items]")
    return items


def _sanitize_scalar(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    text = str(value)
    if len(text) > MAX_STRING:
        return f"{text[:MAX_STRING]}...[{len(text) - MAX_STRING} more chars]"
    return text


def _secret_values(value: Any) -> list[str]:
    """Collect the string values of secret-named arguments, at any depth."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_secret(str(key)) and isinstance(item, str):
                found.append(item)
            else:
                found.extend(_secret_values(item))
    elif isinstance(value, list | tuple):
        for item in value:
            found.extend(_secret_values(item))
    return found


def _scrub_error(text: str, arguments: dict[str, Any]) -> str:
    """Remove secret argument values from an error message, then truncate it.

    API errors echo the request URL, which can contain a purchase token.
    """
    for secret in _secret_values(arguments):
        if len(secret) >= 8:
            text = text.replace(secret, _REDACTED)
    if len(text) > MAX_ERROR:
        return f"{text[:MAX_ERROR]}...[{len(text) - MAX_ERROR} more chars]"
    return text


def _result_failure(result: ToolResult) -> tuple[str, str] | None:
    """Return (kind, error) if a tool result reports a failure, else None."""
    if result.is_error:
        text = " ".join(getattr(block, "text", "") for block in result.content)
        return "error_result", text
    content = result.structured_content
    if isinstance(content, dict) and (content.get("error") or content.get("success") is False):
        return "returned_error", str(content.get("error") or content.get("message") or content)
    return None


class FailureLogMiddleware(Middleware):
    """Append failed tool calls to a JSON-lines file when the failure log is enabled."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._unwritable: set[Path] = set()

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if not enabled():
            return await call_next(context)
        params = context.message
        try:
            result = await call_next(context)
        except Exception as exc:
            # FastMCP wraps a tool's own exception in ToolError; name the original.
            cause = exc.__cause__ or exc
            self._record(params, "raised", str(exc), error_type=type(cause).__name__)
            raise
        failure = _result_failure(result)
        if failure is not None:
            self._record(params, *failure)
        return result

    def _record(
        self,
        params: mt.CallToolRequestParams,
        kind: str,
        error: str,
        *,
        error_type: str | None = None,
    ) -> None:
        """Write one failure record. Best-effort: never breaks the tool call."""
        try:
            arguments = params.arguments or {}
            record = {
                "ts": datetime.now(UTC).isoformat(),
                "tool": params.name,
                "kind": kind,
                "error_type": error_type,
                "error": _scrub_error(error, arguments),
                "arguments": _sanitize(arguments),
            }
            line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
            self._append(log_path(), line)
        except Exception as exc:  # noqa: BLE001 - logging must never fail a tool call
            logger.warning("Could not record tool failure", error=str(exc))

    def _append(self, path: Path, line: str) -> None:
        """Append a line, rotating to ``<name>.1`` once the file would exceed MAX_BYTES."""
        with self._lock:
            if path in self._unwritable:
                return
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                size = path.stat().st_size if path.exists() else 0
                if size and size + len(line.encode()) > MAX_BYTES:
                    path.replace(path.with_name(path.name + ".1"))
                # 0o600: arguments may hold app data the operator didn't mean to share.
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError as exc:
                self._unwritable.add(path)
                logger.warning(
                    "Tool failure log is not writable; disabling it for this path",
                    path=str(path),
                    error=str(exc),
                )
