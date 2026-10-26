"""Tests for the opt-in tool-failure log (PLAY_STORE_MCP_FAILURE_LOG)."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastmcp import Client, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import TextContent

from play_store_mcp import failure_log, server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.failure_log import (
    FailureLogMiddleware,
    _result_failure,
    _sanitize,
    _scrub_error,
)
from play_store_mcp.models import ProductPurchaseActionResult


@pytest.fixture
def mock_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    # Patched at the lookup, not via _shared_state: Client(server.mcp) runs the
    # server's lifespan, which resets the shared client on startup.
    client = MagicMock(spec=PlayStoreClient)
    monkeypatch.setattr(server, "get_client_from_context", lambda: client)
    return client


@pytest.fixture
def log_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "state" / "tool-failures.jsonl"
    monkeypatch.setenv(failure_log.ENABLE_ENV, "1")
    monkeypatch.setenv(failure_log.PATH_ENV, str(path))
    return path


def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


async def _call(name: str, arguments: dict[str, Any]) -> Any:
    async with Client(server.mcp) as client:
        return await client.call_tool(name, arguments, raise_on_error=False)


class TestDisabledByDefault:
    async def test_nothing_written_when_flag_unset(
        self, mock_client: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "log.jsonl"
        monkeypatch.delenv(failure_log.ENABLE_ENV, raising=False)
        monkeypatch.setenv(failure_log.PATH_ENV, str(path))
        mock_client.get_order.side_effect = PlayStoreClientError("boom")

        await _call("get_order", {"package_name": "com.example.app", "order_id": "o-1"})

        assert not path.exists()

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("1", True), ("true", True), ("ON", True), ("yes", True), ("0", False), ("", False)],
    )
    def test_flag_parsing(
        self, monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
    ) -> None:
        monkeypatch.setenv(failure_log.ENABLE_ENV, value)
        assert failure_log.enabled() is expected


class TestRecordedFailures:
    async def test_raised_exception(self, mock_client: MagicMock, log_file: Path) -> None:
        mock_client.get_order.side_effect = PlayStoreClientError("order lookup failed")

        result = await _call("get_order", {"package_name": "com.example.app", "order_id": "o-1"})

        assert result.is_error
        (record,) = _records(log_file)
        assert record["tool"] == "get_order"
        assert record["kind"] == "raised"
        assert record["error_type"] == "PlayStoreClientError"
        assert "order lookup failed" in record["error"]
        assert record["arguments"] == {"package_name": "com.example.app", "order_id": "o-1"}
        assert record["ts"]

    async def test_returned_error_payload(self, mock_client: MagicMock, log_file: Path) -> None:
        """A {"success": false} result looks like a success to clients; it is logged."""
        mock_client.acknowledge_product_purchase.return_value = ProductPurchaseActionResult(
            success=False,
            package_name="com.example.app",
            product_id="sku",
            purchase_token="tok",
            action="acknowledge",
            message="Failed to acknowledge product purchase: quota",
        )

        await _call(
            "acknowledge_product_purchase",
            {
                "package_name": "com.example.app",
                "product_id": "sku",
                "purchase_token": "tok-123456789",
            },
        )

        (record,) = _records(log_file)
        assert record["kind"] == "returned_error"
        assert "quota" in record["error"]

    async def test_read_only_refusal(
        self, mock_client: MagicMock, log_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(server, "READ_ONLY", True)

        await _call(
            "acknowledge_product_purchase",
            {
                "package_name": "com.example.app",
                "product_id": "sku",
                "purchase_token": "tok-123456789",
            },
        )

        (record,) = _records(log_file)
        assert record["kind"] == "returned_error"
        assert "read-only" in record["error"].lower()
        mock_client.acknowledge_product_purchase.assert_not_called()

    async def test_argument_validation_failure(
        self, mock_client: MagicMock, log_file: Path
    ) -> None:
        """Validation never reaches the client, but the middleware still sees it."""
        await _call("get_order", {"package_name": "com.example.app"})

        (record,) = _records(log_file)
        assert record["tool"] == "get_order"
        assert "order_id" in record["error"]
        mock_client.get_order.assert_not_called()

    async def test_success_is_not_recorded(self, mock_client: MagicMock, log_file: Path) -> None:
        mock_client.list_subscriptions.return_value = []

        await _call("list_subscriptions", {"package_name": "com.example.app"})

        assert not log_file.exists()


class TestRedactionAndLimits:
    async def test_secret_arguments_redacted_in_arguments_and_error(
        self, mock_client: MagicMock, log_file: Path
    ) -> None:
        token = "secret-purchase-token-123"
        mock_client.get_product_purchase.side_effect = PlayStoreClientError(
            f"404 for https://androidpublisher.googleapis.com/.../tokens/{token}?alt=json"
        )

        await _call(
            "get_product_purchase",
            {"package_name": "com.example.app", "product_id": "sku", "purchase_token": token},
        )

        text = log_file.read_text()
        assert token not in text
        (record,) = _records(log_file)
        assert record["arguments"]["purchase_token"] == "[redacted]"
        assert "[redacted]" in record["error"]

    def test_secret_keys_matched_case_and_separator_insensitively(self) -> None:
        sanitized = _sanitize(
            {
                "purchaseToken": "a",
                "API-KEY": "b",
                "nested": {"client_secret": "c", "items": [{"Password": "d"}]},
                "package_name": "com.example.app",
            }
        )
        assert sanitized == {
            "purchaseToken": "[redacted]",
            "API-KEY": "[redacted]",
            "nested": {"client_secret": "[redacted]", "items": [{"Password": "[redacted]"}]},
            "package_name": "com.example.app",
        }

    def test_long_values_truncated(self) -> None:
        sanitized = _sanitize({"text": "x" * 600, "ids": list(range(25))})
        assert sanitized["text"].startswith("x" * failure_log.MAX_STRING)
        assert sanitized["text"].endswith("...[100 more chars]")
        assert len(sanitized["ids"]) == failure_log.MAX_ITEMS + 1
        assert sanitized["ids"][-1] == "[5 more items]"

    def test_error_scrubbing(self) -> None:
        arguments = {"items": [{"purchase_token": "long-secret-value"}], "token": "short"}
        scrubbed = _scrub_error("bad long-secret-value and short", arguments)
        # Very short values aren't scrubbed: they'd match too much ordinary text.
        assert scrubbed == "bad [redacted] and short"

        long_error = _scrub_error("e" * (failure_log.MAX_ERROR + 10), {})
        assert long_error.endswith("...[10 more chars]")

    def test_is_error_result_is_a_failure(self) -> None:
        result = ToolResult(content=[TextContent(type="text", text="boom")], is_error=True)
        assert _result_failure(result) == ("error_result", "boom")

    def test_deep_nesting_and_non_json_values(self) -> None:
        deep: Any = "leaf"
        for _ in range(10):
            deep = {"d": deep}
        assert "nested too deeply" in json.dumps(_sanitize(deep))
        assert _sanitize({"p": Path("/tmp/x")}) == {"p": "/tmp/x"}  # noqa: S108

    async def test_file_is_private(self, mock_client: MagicMock, log_file: Path) -> None:
        mock_client.get_order.side_effect = PlayStoreClientError("boom")

        await _call("get_order", {"package_name": "com.example.app", "order_id": "o-1"})

        assert stat.S_IMODE(log_file.stat().st_mode) == 0o600


class TestFileHandling:
    async def test_rotates_to_one_backup(
        self, mock_client: MagicMock, log_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(failure_log, "MAX_BYTES", 200)
        mock_client.get_order.side_effect = PlayStoreClientError("boom")

        for order_id in ("o-1", "o-2", "o-3"):
            await _call("get_order", {"package_name": "com.example.app", "order_id": order_id})

        backup = log_file.with_name(log_file.name + ".1")
        assert backup.exists()
        assert _records(log_file)[-1]["arguments"]["order_id"] == "o-3"
        assert not log_file.with_name(log_file.name + ".2").exists()

    async def test_unwritable_path_never_breaks_the_call(
        self, mock_client: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("")
        monkeypatch.setenv(failure_log.ENABLE_ENV, "1")
        monkeypatch.setenv(failure_log.PATH_ENV, str(blocker / "log.jsonl"))
        mock_client.get_order.side_effect = PlayStoreClientError("boom")

        for _ in range(2):
            result = await _call("get_order", {"package_name": "com.example.app", "order_id": "o"})
            assert result.is_error

    async def test_record_building_error_never_breaks_the_call(
        self, mock_client: MagicMock, log_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken_path() -> Path:
            raise RuntimeError("no path")

        monkeypatch.setattr(failure_log, "log_path", broken_path)
        mock_client.get_order.side_effect = PlayStoreClientError("boom")

        result = await _call("get_order", {"package_name": "com.example.app", "order_id": "o"})

        assert result.is_error
        assert not log_file.exists()

    def test_default_path_uses_xdg_state_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(failure_log.PATH_ENV, raising=False)
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        assert failure_log.log_path() == tmp_path / "play-store-mcp" / "tool-failures.jsonl"

    def test_default_path_falls_back_to_local_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(failure_log.PATH_ENV, raising=False)
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        assert failure_log.log_path() == (
            tmp_path / ".local" / "state" / "play-store-mcp" / "tool-failures.jsonl"
        )

    def test_configured_path_expands_user(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv(failure_log.PATH_ENV, "~/logs/failures.jsonl")
        assert failure_log.log_path() == tmp_path / "logs" / "failures.jsonl"


class TestCodeMode:
    async def test_inner_call_failures_are_recorded(
        self, log_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """execute's inner call_tool runs through the middleware, so the real tool is named."""
        monkeypatch.setenv("CODE_MODE", "1")
        probe = FastMCP("probe", transforms=server._build_transforms())
        probe.add_middleware(FailureLogMiddleware())

        @probe.tool
        def lookup(order_id: str) -> dict[str, Any]:
            return {"success": False, "error": f"no order {order_id}"}

        async with Client(probe) as client:
            await client.call_tool(
                "execute",
                {"code": "return await call_tool('lookup', {'order_id': 'o-9'})"},
                raise_on_error=False,
            )

        records = _records(log_file)
        inner = [r for r in records if r["tool"] == "lookup"]
        assert inner
        assert inner[0]["kind"] == "returned_error"
        assert inner[0]["arguments"] == {"order_id": "o-9"}
        assert any(r["tool"] == "execute" for r in records)
