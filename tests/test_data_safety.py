"""Tests for data safety tools (applications.dataSafety)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import DataSafetyResult

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_data_safety_result_defaults():
    result = DataSafetyResult(
        success=True,
        package_name="com.example.app",
        message="Data safety labels updated",
    )
    assert result.success is True
    assert result.package_name == "com.example.app"
    assert result.message == "Data safety labels updated"
    assert result.error is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_http_error(reason: str = "boom") -> HttpError:
    resp = MagicMock()
    resp.status = 400
    resp.reason = reason
    err = HttpError(resp, b"{}")
    err.reason = reason
    return err


def _client(service: MagicMock) -> PlayStoreClient:
    client = PlayStoreClient(credentials_json={"type": "service_account"})
    client._service = service
    return client


# ---------------------------------------------------------------------------
# Client: set_data_safety
# ---------------------------------------------------------------------------


def test_set_data_safety_success():
    service = MagicMock()
    service.applications.return_value.dataSafety.return_value.execute.return_value = {}
    client = _client(service)

    safety_labels = {"safetyLabels": "col1,col2\nval1,val2"}
    result = client.set_data_safety("com.example.app", safety_labels)

    assert isinstance(result, DataSafetyResult)
    assert result.success is True
    assert result.package_name == "com.example.app"
    assert result.message == "Data safety labels updated"
    assert result.error is None
    service.applications.return_value.dataSafety.assert_called_once_with(
        packageName="com.example.app", body=safety_labels
    )


def test_set_data_safety_http_error():
    service = MagicMock()
    service.applications.return_value.dataSafety.return_value.execute.side_effect = (
        _make_http_error("bad")
    )
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to update data safety labels"):
        client.set_data_safety("com.example.app", {"safetyLabels": "csv"})


# ---------------------------------------------------------------------------
# MCP tool
# ---------------------------------------------------------------------------


def test_tool_set_data_safety(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.set_data_safety.return_value = DataSafetyResult(
        success=True,
        package_name="com.example.app",
        message="Data safety labels updated",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    safety_labels = {"safetyLabels": "col1,col2\nval1,val2"}
    result = server.set_data_safety("com.example.app", safety_labels)

    assert result["success"] is True
    assert result["package_name"] == "com.example.app"
    mc.set_data_safety.assert_called_once_with(
        package_name="com.example.app",
        safety_labels=safety_labels,
    )
