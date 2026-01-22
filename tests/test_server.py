"""Tests for MCP server tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestServerTools:
    """Test MCP server tool functions."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock PlayStoreClient."""
        return MagicMock()

    def test_server_module_imports(self) -> None:
        """Test that server module can be imported."""
        # This tests that the module structure is correct
        from play_store_mcp import server

        assert hasattr(server, "mcp")
        assert hasattr(server, "main")
        assert hasattr(server, "deploy_app")
        assert hasattr(server, "get_releases")
        assert hasattr(server, "promote_release")

    def test_tool_functions_exist(self) -> None:
        """Test that all expected tools are defined."""
        from play_store_mcp import server

        expected_tools = [
            "deploy_app",
            "promote_release",
            "get_releases",
            "halt_release",
            "update_rollout",
            "get_app_details",
            "get_reviews",
            "reply_to_review",
            "list_subscriptions",
            "get_subscription_status",
            "list_voided_purchases",
            "get_vitals_overview",
        ]

        for tool_name in expected_tools:
            assert hasattr(server, tool_name), f"Missing tool: {tool_name}"
