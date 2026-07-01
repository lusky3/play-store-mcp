"""Tests for account access tools (users & grants)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import AccessResult, Grant, User

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_user_defaults():
    user = User(developer_id="dev123")
    assert user.email is None
    assert user.access_state is None
    assert user.expiration_time is None
    assert user.developer_account_permissions == []


def test_user_full():
    user = User(
        developer_id="dev123",
        email="a@b.com",
        access_state="ACCESS_GRANTED",
        expiration_time="2027-01-01T00:00:00Z",
        developer_account_permissions=["CAN_VIEW_FINANCIAL_DATA_GLOBAL"],
    )
    assert user.email == "a@b.com"
    assert user.access_state == "ACCESS_GRANTED"
    assert user.expiration_time == "2027-01-01T00:00:00Z"
    assert user.developer_account_permissions == ["CAN_VIEW_FINANCIAL_DATA_GLOBAL"]


def test_grant_defaults():
    grant = Grant(developer_id="dev123", email="a@b.com")
    assert grant.package_name is None
    assert grant.app_level_permissions == []


def test_grant_full():
    grant = Grant(
        developer_id="dev123",
        email="a@b.com",
        package_name="com.example.app",
        app_level_permissions=["CAN_MANAGE_PUBLIC_APKS_GLOBAL"],
    )
    assert grant.package_name == "com.example.app"
    assert grant.app_level_permissions == ["CAN_MANAGE_PUBLIC_APKS_GLOBAL"]


def test_access_result():
    result = AccessResult(success=True, message="ok")
    assert result.success is True
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


def _users(service: MagicMock) -> MagicMock:
    return service.users.return_value


def _grants(service: MagicMock) -> MagicMock:
    return service.grants.return_value


_USER_RESPONSE = {
    "name": "developers/dev123/users/a@b.com",
    "email": "a@b.com",
    "accessState": "ACCESS_GRANTED",
    "expirationTime": "2027-01-01T00:00:00Z",
    "developerAccountPermissions": ["CAN_VIEW_FINANCIAL_DATA_GLOBAL"],
}

_GRANT_RESPONSE = {
    "name": "developers/dev123/users/a@b.com/grants/com.example.app",
    "packageName": "com.example.app",
    "appLevelPermissions": ["CAN_MANAGE_PUBLIC_APKS_GLOBAL"],
}


# ---------------------------------------------------------------------------
# Client: list_users
# ---------------------------------------------------------------------------


def test_list_users_success():
    service = MagicMock()
    _users(service).list.return_value.execute.return_value = {
        "users": [_USER_RESPONSE, {"name": "developers/dev123/users/c@d.com"}]
    }
    client = _client(service)

    result = client.list_users("dev123")

    assert [u.email for u in result] == ["a@b.com", "c@d.com"]
    assert result[0].access_state == "ACCESS_GRANTED"
    assert result[0].developer_account_permissions == ["CAN_VIEW_FINANCIAL_DATA_GLOBAL"]
    assert result[1].email == "c@d.com"
    assert result[1].developer_account_permissions == []
    _users(service).list.assert_called_once_with(parent="developers/dev123")


def test_list_users_empty():
    service = MagicMock()
    _users(service).list.return_value.execute.return_value = {}
    client = _client(service)

    assert client.list_users("dev123") == []


def test_list_users_http_error():
    service = MagicMock()
    _users(service).list.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to list users"):
        client.list_users("dev123")


# ---------------------------------------------------------------------------
# Client: create_user
# ---------------------------------------------------------------------------


def test_create_user_success():
    service = MagicMock()
    _users(service).create.return_value.execute.return_value = _USER_RESPONSE
    client = _client(service)

    body = {"email": "a@b.com", "developerAccountPermissions": ["CAN_VIEW_FINANCIAL_DATA_GLOBAL"]}
    result = client.create_user("dev123", body)

    assert isinstance(result, User)
    assert result.developer_id == "dev123"
    assert result.email == "a@b.com"
    _users(service).create.assert_called_once_with(parent="developers/dev123", body=body)


def test_create_user_http_error():
    service = MagicMock()
    _users(service).create.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to create user"):
        client.create_user("dev123", {"email": "a@b.com"})


# ---------------------------------------------------------------------------
# Client: update_user
# ---------------------------------------------------------------------------


def test_update_user_success():
    service = MagicMock()
    _users(service).patch.return_value.execute.return_value = _USER_RESPONSE
    client = _client(service)

    body = {"developerAccountPermissions": ["CAN_VIEW_FINANCIAL_DATA_GLOBAL"]}
    result = client.update_user(
        "dev123", "a@b.com", body, update_mask="developerAccountPermissions"
    )

    assert isinstance(result, User)
    assert result.email == "a@b.com"
    _users(service).patch.assert_called_once_with(
        name="developers/dev123/users/a@b.com",
        updateMask="developerAccountPermissions",
        body=body,
    )


def test_update_user_http_error():
    service = MagicMock()
    _users(service).patch.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to update user"):
        client.update_user("dev123", "a@b.com", {}, update_mask="expirationTime")


# ---------------------------------------------------------------------------
# Client: delete_user
# ---------------------------------------------------------------------------


def test_delete_user_success():
    service = MagicMock()
    _users(service).delete.return_value.execute.return_value = {}
    client = _client(service)

    result = client.delete_user("dev123", "a@b.com")

    assert isinstance(result, AccessResult)
    assert result.success is True
    assert "a@b.com" in result.message
    _users(service).delete.assert_called_once_with(name="developers/dev123/users/a@b.com")


def test_delete_user_http_error():
    service = MagicMock()
    _users(service).delete.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to delete user"):
        client.delete_user("dev123", "a@b.com")


# ---------------------------------------------------------------------------
# Client: create_grant
# ---------------------------------------------------------------------------


def test_create_grant_success():
    service = MagicMock()
    _grants(service).create.return_value.execute.return_value = _GRANT_RESPONSE
    client = _client(service)

    body = {
        "packageName": "com.example.app",
        "appLevelPermissions": ["CAN_MANAGE_PUBLIC_APKS_GLOBAL"],
    }
    result = client.create_grant("dev123", "a@b.com", body)

    assert isinstance(result, Grant)
    assert result.developer_id == "dev123"
    assert result.email == "a@b.com"
    assert result.package_name == "com.example.app"
    assert result.app_level_permissions == ["CAN_MANAGE_PUBLIC_APKS_GLOBAL"]
    _grants(service).create.assert_called_once_with(
        parent="developers/dev123/users/a@b.com", body=body
    )


def test_create_grant_package_name_from_name_suffix():
    service = MagicMock()
    _grants(service).create.return_value.execute.return_value = {
        "name": "developers/dev123/users/a@b.com/grants/com.example.app"
    }
    client = _client(service)

    result = client.create_grant("dev123", "a@b.com", {})

    assert result.package_name == "com.example.app"
    assert result.app_level_permissions == []


def test_create_grant_http_error():
    service = MagicMock()
    _grants(service).create.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to create grant"):
        client.create_grant("dev123", "a@b.com", {})


# ---------------------------------------------------------------------------
# Client: update_grant
# ---------------------------------------------------------------------------


def test_update_grant_success():
    service = MagicMock()
    _grants(service).patch.return_value.execute.return_value = _GRANT_RESPONSE
    client = _client(service)

    body = {"appLevelPermissions": ["CAN_MANAGE_PUBLIC_APKS_GLOBAL"]}
    result = client.update_grant(
        "dev123", "a@b.com", "com.example.app", body, update_mask="appLevelPermissions"
    )

    assert isinstance(result, Grant)
    assert result.package_name == "com.example.app"
    _grants(service).patch.assert_called_once_with(
        name="developers/dev123/users/a@b.com/grants/com.example.app",
        updateMask="appLevelPermissions",
        body=body,
    )


def test_update_grant_http_error():
    service = MagicMock()
    _grants(service).patch.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to update grant"):
        client.update_grant(
            "dev123", "a@b.com", "com.example.app", {}, update_mask="appLevelPermissions"
        )


# ---------------------------------------------------------------------------
# Client: delete_grant
# ---------------------------------------------------------------------------


def test_delete_grant_success():
    service = MagicMock()
    _grants(service).delete.return_value.execute.return_value = {}
    client = _client(service)

    result = client.delete_grant("dev123", "a@b.com", "com.example.app")

    assert isinstance(result, AccessResult)
    assert result.success is True
    assert "com.example.app" in result.message
    _grants(service).delete.assert_called_once_with(
        name="developers/dev123/users/a@b.com/grants/com.example.app"
    )


def test_delete_grant_http_error():
    service = MagicMock()
    _grants(service).delete.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to delete grant"):
        client.delete_grant("dev123", "a@b.com", "com.example.app")


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_tool_list_users(monkeypatch):
    mc = MagicMock()
    mc.list_users.return_value = [User(developer_id="dev123", email="a@b.com")]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.list_users("dev123")

    assert result[0]["email"] == "a@b.com"
    mc.list_users.assert_called_once_with("dev123")


def test_tool_create_user(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.create_user.return_value = User(developer_id="dev123", email="a@b.com")
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    body = {"email": "a@b.com"}
    result = server.create_user("dev123", body)

    assert result["email"] == "a@b.com"
    mc.create_user.assert_called_once_with(developer_id="dev123", user=body)


def test_tool_update_user(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.update_user.return_value = User(developer_id="dev123", email="a@b.com")
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    body = {"developerAccountPermissions": []}
    result = server.update_user(
        "dev123", "a@b.com", body, update_mask="developerAccountPermissions"
    )

    assert result["email"] == "a@b.com"
    mc.update_user.assert_called_once_with(
        developer_id="dev123",
        email="a@b.com",
        user=body,
        update_mask="developerAccountPermissions",
    )


def test_tool_delete_user(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.delete_user.return_value = AccessResult(success=True, message="removed")
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.delete_user("dev123", "a@b.com")

    assert result["success"] is True
    mc.delete_user.assert_called_once_with(developer_id="dev123", email="a@b.com")


def test_tool_create_grant(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.create_grant.return_value = Grant(
        developer_id="dev123", email="a@b.com", package_name="com.example.app"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    body = {"packageName": "com.example.app"}
    result = server.create_grant("dev123", "a@b.com", body)

    assert result["package_name"] == "com.example.app"
    mc.create_grant.assert_called_once_with(developer_id="dev123", email="a@b.com", grant=body)


def test_tool_update_grant(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.update_grant.return_value = Grant(
        developer_id="dev123", email="a@b.com", package_name="com.example.app"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    body = {"appLevelPermissions": []}
    result = server.update_grant(
        "dev123", "a@b.com", "com.example.app", body, update_mask="appLevelPermissions"
    )

    assert result["package_name"] == "com.example.app"
    mc.update_grant.assert_called_once_with(
        developer_id="dev123",
        email="a@b.com",
        package_name="com.example.app",
        grant=body,
        update_mask="appLevelPermissions",
    )


def test_tool_delete_grant(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.delete_grant.return_value = AccessResult(success=True, message="removed")
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.delete_grant("dev123", "a@b.com", "com.example.app")

    assert result["success"] is True
    mc.delete_grant.assert_called_once_with(
        developer_id="dev123", email="a@b.com", package_name="com.example.app"
    )
