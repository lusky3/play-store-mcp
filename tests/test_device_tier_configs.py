"""Tests for device tier config tools (applications.deviceTierConfigs)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import DeviceTierConfig

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_device_tier_config_defaults():
    config = DeviceTierConfig(package_name="com.example.app")
    assert config.device_tier_config_id is None
    assert config.device_groups == []
    assert config.device_tier_set is None
    assert config.user_country_sets == []


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


def _dtc(service: MagicMock) -> MagicMock:
    return service.applications.return_value.deviceTierConfigs.return_value


_CONFIG_RESPONSE = {
    "deviceTierConfigId": "12345",
    "deviceGroups": [{"name": "high_ram", "deviceSelectors": [{"deviceRam": {"minBytes": "1"}}]}],
    "deviceTierSet": {"deviceTiers": [{"level": 1, "deviceGroupNames": ["high_ram"]}]},
    "userCountrySets": [{"name": "europe", "countryCodes": ["DE", "FR"]}],
}


# ---------------------------------------------------------------------------
# Client: get_device_tier_config
# ---------------------------------------------------------------------------


def test_get_device_tier_config_success():
    service = MagicMock()
    _dtc(service).get.return_value.execute.return_value = _CONFIG_RESPONSE
    client = _client(service)

    result = client.get_device_tier_config("com.example.app", "12345")

    assert isinstance(result, DeviceTierConfig)
    assert result.package_name == "com.example.app"
    assert result.device_tier_config_id == "12345"
    assert result.device_groups == _CONFIG_RESPONSE["deviceGroups"]
    assert result.device_tier_set == _CONFIG_RESPONSE["deviceTierSet"]
    assert result.user_country_sets == _CONFIG_RESPONSE["userCountrySets"]
    _dtc(service).get.assert_called_once_with(
        packageName="com.example.app", deviceTierConfigId="12345"
    )


def test_get_device_tier_config_http_error():
    service = MagicMock()
    _dtc(service).get.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to get device tier config"):
        client.get_device_tier_config("com.example.app", "12345")


# ---------------------------------------------------------------------------
# Client: list_device_tier_configs
# ---------------------------------------------------------------------------


def test_list_device_tier_configs_success():
    service = MagicMock()
    _dtc(service).list.return_value.execute.return_value = {
        "deviceTierConfigs": [
            _CONFIG_RESPONSE,
            {"deviceTierConfigId": "67890"},
        ]
    }
    client = _client(service)

    result = client.list_device_tier_configs("com.example.app")

    assert [c.device_tier_config_id for c in result] == ["12345", "67890"]
    assert result[1].device_groups == []
    assert result[1].device_tier_set is None
    _dtc(service).list.assert_called_once_with(packageName="com.example.app")


def test_list_device_tier_configs_empty():
    service = MagicMock()
    _dtc(service).list.return_value.execute.return_value = {}
    client = _client(service)

    result = client.list_device_tier_configs("com.example.app")

    assert result == []


def test_list_device_tier_configs_http_error():
    service = MagicMock()
    _dtc(service).list.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to list device tier configs"):
        client.list_device_tier_configs("com.example.app")


# ---------------------------------------------------------------------------
# Client: create_device_tier_config
# ---------------------------------------------------------------------------


def test_create_device_tier_config_success_defaults():
    service = MagicMock()
    _dtc(service).create.return_value.execute.return_value = _CONFIG_RESPONSE
    client = _client(service)

    body = {"deviceGroups": [{"name": "high_ram"}]}
    result = client.create_device_tier_config("com.example.app", body)

    assert isinstance(result, DeviceTierConfig)
    assert result.device_tier_config_id == "12345"
    _dtc(service).create.assert_called_once_with(
        packageName="com.example.app",
        allowUnknownDevices=False,
        body=body,
    )


def test_create_device_tier_config_allow_unknown_devices_true():
    service = MagicMock()
    _dtc(service).create.return_value.execute.return_value = _CONFIG_RESPONSE
    client = _client(service)

    body = {"deviceGroups": [{"name": "high_ram"}]}
    client.create_device_tier_config("com.example.app", body, allow_unknown_devices=True)

    _dtc(service).create.assert_called_once_with(
        packageName="com.example.app",
        allowUnknownDevices=True,
        body=body,
    )


def test_create_device_tier_config_http_error():
    service = MagicMock()
    _dtc(service).create.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to create device tier config"):
        client.create_device_tier_config("com.example.app", {"deviceGroups": []})


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_tool_get_device_tier_config(monkeypatch):
    mc = MagicMock()
    mc.get_device_tier_config.return_value = DeviceTierConfig(
        package_name="com.example.app", device_tier_config_id="12345"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.get_device_tier_config("com.example.app", "12345")

    assert result["device_tier_config_id"] == "12345"
    mc.get_device_tier_config.assert_called_once_with(
        package_name="com.example.app", device_tier_config_id="12345"
    )


def test_tool_list_device_tier_configs(monkeypatch):
    mc = MagicMock()
    mc.list_device_tier_configs.return_value = [
        DeviceTierConfig(package_name="com.example.app", device_tier_config_id="12345")
    ]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.list_device_tier_configs("com.example.app")

    assert result[0]["device_tier_config_id"] == "12345"
    mc.list_device_tier_configs.assert_called_once_with("com.example.app")


def test_tool_create_device_tier_config(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.create_device_tier_config.return_value = DeviceTierConfig(
        package_name="com.example.app", device_tier_config_id="12345"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    body = {"deviceGroups": [{"name": "high_ram"}]}
    result = server.create_device_tier_config("com.example.app", body, allow_unknown_devices=True)

    assert result["device_tier_config_id"] == "12345"
    mc.create_device_tier_config.assert_called_once_with(
        package_name="com.example.app",
        config=body,
        allow_unknown_devices=True,
    )
