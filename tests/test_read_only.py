"""Tests for read-only mode (flag, env parsing, guard helper, write gating)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import play_store_mcp.server as server

# ---------------------------------------------------------------------------
# Core: env parsing, guard helper, setter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("Yes", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("", False),
        ("maybe", False),
    ],
)
def test_env_read_only_parsing(monkeypatch, value, expected):
    monkeypatch.setenv("PLAY_STORE_MCP_READ_ONLY", value)
    assert server._env_read_only() is expected


def test_env_read_only_unset(monkeypatch):
    monkeypatch.delenv("PLAY_STORE_MCP_READ_ONLY", raising=False)
    assert server._env_read_only() is False


def test_read_only_block_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    assert server._read_only_block("deploy_app") is None


def test_read_only_block_returns_error_when_enabled(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", True)
    result = server._read_only_block("deploy_app")
    assert result is not None
    assert "read-only" in result["error"].lower()
    assert "deploy_app" in result["error"]


def test_set_read_only_updates_global(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    server.set_read_only(True)
    assert server.READ_ONLY is True
    server.set_read_only(False)
    assert server.READ_ONLY is False


# ---------------------------------------------------------------------------
# Write tools are blocked; read tools are not
# ---------------------------------------------------------------------------

# (tool_name, kwargs) — kwargs satisfy each signature; the guard returns
# before any argument is used, so values are arbitrary but well-typed.
WRITE_TOOLS = [
    (
        "deploy_app",
        {"package_name": "com.example.app", "track": "internal", "file_path": "app.aab"},
    ),
    (
        "deploy_app_multilang",
        {
            "package_name": "com.example.app",
            "track": "internal",
            "file_path": "app.aab",
            "release_notes": {"en-US": "notes"},
        },
    ),
    (
        "promote_release",
        {
            "package_name": "com.example.app",
            "from_track": "internal",
            "to_track": "alpha",
            "version_code": 1,
        },
    ),
    ("halt_release", {"package_name": "com.example.app", "track": "production", "version_code": 1}),
    (
        "update_rollout",
        {
            "package_name": "com.example.app",
            "track": "production",
            "version_code": 1,
            "rollout_percentage": 50.0,
        },
    ),
    (
        "reply_to_review",
        {"package_name": "com.example.app", "review_id": "r1", "reply_text": "thanks"},
    ),
    ("update_listing", {"package_name": "com.example.app", "language": "en-US"}),
    (
        "update_testers",
        {"package_name": "com.example.app", "track": "internal", "google_groups": []},
    ),
    (
        "batch_deploy",
        {"package_name": "com.example.app", "file_path": "app.aab", "tracks": ["internal"]},
    ),
    (
        "acknowledge_product_purchase",
        {"package_name": "com.example.app", "product_id": "sku1", "purchase_token": "tok"},
    ),
    (
        "consume_product_purchase",
        {"package_name": "com.example.app", "product_id": "sku1", "purchase_token": "tok"},
    ),
    ("refund_order", {"package_name": "com.example.app", "order_id": "GPA.1"}),
    (
        "cancel_subscription_purchase",
        {"package_name": "com.example.app", "purchase_token": "tok"},
    ),
    (
        "defer_subscription_purchase",
        {
            "package_name": "com.example.app",
            "purchase_token": "tok",
            "defer_duration": "604800s",
            "etag": "e",
        },
    ),
    (
        "revoke_subscription_purchase",
        {"package_name": "com.example.app", "purchase_token": "tok"},
    ),
]


@pytest.mark.parametrize(("tool_name", "kwargs"), WRITE_TOOLS)
def test_write_tool_blocked_in_read_only(monkeypatch, tool_name, kwargs):
    monkeypatch.setattr(server, "READ_ONLY", True)
    mock_ctx = MagicMock()  # get_client_from_context must NOT be called
    monkeypatch.setattr(server, "get_client_from_context", mock_ctx)

    result = getattr(server, tool_name)(**kwargs)

    assert "error" in result
    assert "read-only" in result["error"].lower()
    assert tool_name in result["error"]
    mock_ctx.assert_not_called()


def test_read_tool_not_blocked_in_read_only(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", True)
    mock_client = MagicMock()
    mock_client.get_releases.return_value = []
    monkeypatch.setattr(server, "get_client_from_context", lambda: mock_client)

    result = server.get_releases("com.example.app")

    assert result == []
    mock_client.get_releases.assert_called_once_with("com.example.app")


# ---------------------------------------------------------------------------
# main() flag / env reconciliation
# ---------------------------------------------------------------------------


def test_main_read_only_flag_sets_global(monkeypatch):
    monkeypatch.delenv("PLAY_STORE_MCP_READ_ONLY", raising=False)
    monkeypatch.setattr(server, "READ_ONLY", False)
    monkeypatch.setattr(server.mcp, "run", MagicMock())

    server.main(["--read-only"])

    assert server.READ_ONLY is True


def test_main_defaults_to_env_read_only(monkeypatch):
    monkeypatch.setenv("PLAY_STORE_MCP_READ_ONLY", "1")
    monkeypatch.setattr(server, "READ_ONLY", False)
    monkeypatch.setattr(server.mcp, "run", MagicMock())

    server.main([])

    assert server.READ_ONLY is True


def test_main_not_read_only_by_default(monkeypatch):
    monkeypatch.delenv("PLAY_STORE_MCP_READ_ONLY", raising=False)
    monkeypatch.setattr(server, "READ_ONLY", True)  # ensure main() actively clears it
    monkeypatch.setattr(server.mcp, "run", MagicMock())

    server.main([])

    assert server.READ_ONLY is False
