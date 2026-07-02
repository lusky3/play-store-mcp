"""Tests for app recovery tools (applications.appRecoveries)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import AppRecovery, AppRecoveryResult

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_app_recovery_defaults():
    recovery = AppRecovery(package_name="com.example.app")
    assert recovery.app_recovery_id is None
    assert recovery.status is None
    assert recovery.targeting is None
    assert recovery.create_time is None


def test_app_recovery_result_defaults():
    result = AppRecoveryResult(
        success=True,
        package_name="com.example.app",
        message="ok",
    )
    assert result.success is True
    assert result.package_name == "com.example.app"
    assert result.app_recovery_id is None
    assert result.message == "ok"
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


def _rec(service: MagicMock) -> MagicMock:
    return service.apprecovery.return_value


_ACTION_RESPONSE = {
    "appRecoveryId": "123",
    "status": "RECOVERY_STATUS_DRAFT",
    "targeting": {"allUsers": {}},
    "createTime": "2026-01-01T00:00:00Z",
}


# ---------------------------------------------------------------------------
# Client: list_app_recoveries
# ---------------------------------------------------------------------------


def test_list_app_recoveries_success():
    service = MagicMock()
    _rec(service).list.return_value.execute.return_value = {
        "recoveryActions": [
            _ACTION_RESPONSE,
            {"appRecoveryId": "456"},
        ]
    }
    client = _client(service)

    result = client.list_app_recoveries("com.example.app", 8)

    assert [r.app_recovery_id for r in result] == ["123", "456"]
    assert result[0].status == "RECOVERY_STATUS_DRAFT"
    assert result[0].targeting == {"allUsers": {}}
    assert result[0].create_time == "2026-01-01T00:00:00Z"
    assert result[1].status is None
    assert result[1].targeting is None
    _rec(service).list.assert_called_once_with(packageName="com.example.app", versionCode=8)


def test_list_app_recoveries_empty():
    service = MagicMock()
    _rec(service).list.return_value.execute.return_value = {}
    client = _client(service)

    result = client.list_app_recoveries("com.example.app", 8)

    assert result == []


def test_list_app_recoveries_http_error():
    service = MagicMock()
    _rec(service).list.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to list app recoveries"):
        client.list_app_recoveries("com.example.app", 8)


# ---------------------------------------------------------------------------
# Client: create_app_recovery
# ---------------------------------------------------------------------------


def test_create_app_recovery_success():
    service = MagicMock()
    _rec(service).create.return_value.execute.return_value = _ACTION_RESPONSE
    client = _client(service)
    body = {"remoteInAppUpdate": {"isRemoteInAppUpdateRequested": True}}

    result = client.create_app_recovery("com.example.app", body)

    assert isinstance(result, AppRecovery)
    assert result.app_recovery_id == "123"
    assert result.status == "RECOVERY_STATUS_DRAFT"
    _rec(service).create.assert_called_once_with(packageName="com.example.app", body=body)


def test_create_app_recovery_http_error():
    service = MagicMock()
    _rec(service).create.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to create app recovery"):
        client.create_app_recovery("com.example.app", {})


# ---------------------------------------------------------------------------
# Client: deploy_app_recovery
# ---------------------------------------------------------------------------


def test_deploy_app_recovery_success():
    service = MagicMock()
    _rec(service).deploy.return_value.execute.return_value = {}
    client = _client(service)

    result = client.deploy_app_recovery("com.example.app", "123")

    assert isinstance(result, AppRecoveryResult)
    assert result.success is True
    assert result.app_recovery_id == "123"
    assert result.message == "App recovery deployed"
    assert result.error is None
    _rec(service).deploy.assert_called_once_with(
        packageName="com.example.app", appRecoveryId="123", body={}
    )


def test_deploy_app_recovery_http_error():
    service = MagicMock()
    _rec(service).deploy.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to deploy app recovery"):
        client.deploy_app_recovery("com.example.app", "123")


# ---------------------------------------------------------------------------
# Client: cancel_app_recovery
# ---------------------------------------------------------------------------


def test_cancel_app_recovery_success():
    service = MagicMock()
    _rec(service).cancel.return_value.execute.return_value = {}
    client = _client(service)

    result = client.cancel_app_recovery("com.example.app", "123")

    assert isinstance(result, AppRecoveryResult)
    assert result.success is True
    assert result.app_recovery_id == "123"
    assert result.message == "App recovery canceled"
    _rec(service).cancel.assert_called_once_with(
        packageName="com.example.app", appRecoveryId="123", body={}
    )


def test_cancel_app_recovery_http_error():
    service = MagicMock()
    _rec(service).cancel.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to cancel app recovery"):
        client.cancel_app_recovery("com.example.app", "123")


# ---------------------------------------------------------------------------
# Client: add_app_recovery_targeting
# ---------------------------------------------------------------------------


def test_add_app_recovery_targeting_success():
    service = MagicMock()
    _rec(service).addTargeting.return_value.execute.return_value = {}
    client = _client(service)
    body = {"targetingUpdate": {"allUsers": {}}}

    result = client.add_app_recovery_targeting("com.example.app", "123", body)

    assert isinstance(result, AppRecoveryResult)
    assert result.success is True
    assert result.app_recovery_id == "123"
    assert result.message == "App recovery targeting added"
    _rec(service).addTargeting.assert_called_once_with(
        packageName="com.example.app", appRecoveryId="123", body=body
    )


def test_add_app_recovery_targeting_http_error():
    service = MagicMock()
    _rec(service).addTargeting.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to add app recovery targeting"):
        client.add_app_recovery_targeting("com.example.app", "123", {})


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_tool_list_app_recoveries(monkeypatch):
    mc = MagicMock()
    mc.list_app_recoveries.return_value = [
        AppRecovery(
            package_name="com.example.app",
            app_recovery_id="123",
            status="RECOVERY_STATUS_DRAFT",
        )
    ]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.list_app_recoveries("com.example.app", 8)

    assert result == [
        {
            "package_name": "com.example.app",
            "app_recovery_id": "123",
            "status": "RECOVERY_STATUS_DRAFT",
            "targeting": None,
            "create_time": None,
        }
    ]
    mc.list_app_recoveries.assert_called_once_with("com.example.app", 8)


def test_tool_create_app_recovery(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.create_app_recovery.return_value = AppRecovery(
        package_name="com.example.app",
        app_recovery_id="123",
        status="RECOVERY_STATUS_DRAFT",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)
    body = {"remoteInAppUpdate": {"isRemoteInAppUpdateRequested": True}}

    result = server.create_app_recovery("com.example.app", body)

    assert result["app_recovery_id"] == "123"
    mc.create_app_recovery.assert_called_once_with(package_name="com.example.app", recovery=body)


def test_tool_deploy_app_recovery(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.deploy_app_recovery.return_value = AppRecoveryResult(
        success=True,
        package_name="com.example.app",
        app_recovery_id="123",
        message="App recovery deployed",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.deploy_app_recovery("com.example.app", "123")

    assert result["success"] is True
    mc.deploy_app_recovery.assert_called_once_with(
        package_name="com.example.app", app_recovery_id="123"
    )


def test_tool_cancel_app_recovery(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.cancel_app_recovery.return_value = AppRecoveryResult(
        success=True,
        package_name="com.example.app",
        app_recovery_id="123",
        message="App recovery canceled",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.cancel_app_recovery("com.example.app", "123")

    assert result["success"] is True
    mc.cancel_app_recovery.assert_called_once_with(
        package_name="com.example.app", app_recovery_id="123"
    )


def test_tool_add_app_recovery_targeting(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.add_app_recovery_targeting.return_value = AppRecoveryResult(
        success=True,
        package_name="com.example.app",
        app_recovery_id="123",
        message="App recovery targeting added",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)
    body = {"targetingUpdate": {"allUsers": {}}}

    result = server.add_app_recovery_targeting("com.example.app", "123", body)

    assert result["success"] is True
    mc.add_app_recovery_targeting.assert_called_once_with(
        package_name="com.example.app", app_recovery_id="123", targeting=body
    )
