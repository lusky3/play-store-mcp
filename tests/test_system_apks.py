"""Tests for system APK variant tools (systemapks.variants resource)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.client as client_module
import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import DownloadResult, SystemApkVariant

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_system_apk_variant_defaults():
    variant = SystemApkVariant(package_name="com.example.app", version_code=42)
    assert variant.package_name == "com.example.app"
    assert variant.version_code == 42
    assert variant.variant_id is None
    assert variant.device_spec is None
    assert variant.options is None


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


def _variants(service: MagicMock) -> MagicMock:
    return service.systemapks.return_value.variants.return_value


_VARIANT_RESPONSE = {
    "variantId": 1,
    "deviceSpec": {
        "supportedAbis": ["arm64-v8a"],
        "supportedLocales": ["en-US"],
        "screenDensity": 480,
    },
    "options": {"uncompressedNativeLibraries": True, "rotated": False},
}


# ---------------------------------------------------------------------------
# Client: get_system_apk_variant
# ---------------------------------------------------------------------------


def test_get_system_apk_variant_success():
    service = MagicMock()
    _variants(service).get.return_value.execute.return_value = _VARIANT_RESPONSE
    client = _client(service)

    result = client.get_system_apk_variant("com.example.app", 42, 1)

    assert isinstance(result, SystemApkVariant)
    assert result.package_name == "com.example.app"
    assert result.version_code == 42
    assert result.variant_id == 1
    assert result.device_spec == _VARIANT_RESPONSE["deviceSpec"]
    assert result.options == _VARIANT_RESPONSE["options"]
    _variants(service).get.assert_called_once_with(
        packageName="com.example.app", versionCode=42, variantId=1
    )


def test_get_system_apk_variant_http_error():
    service = MagicMock()
    _variants(service).get.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to get system APK variant"):
        client.get_system_apk_variant("com.example.app", 42, 1)


# ---------------------------------------------------------------------------
# Client: list_system_apk_variants
# ---------------------------------------------------------------------------


def test_list_system_apk_variants_success():
    service = MagicMock()
    _variants(service).list.return_value.execute.return_value = {
        "variants": [
            _VARIANT_RESPONSE,
            {"variantId": 2},
        ]
    }
    client = _client(service)

    result = client.list_system_apk_variants("com.example.app", 42)

    assert all(isinstance(v, SystemApkVariant) for v in result)
    assert [v.variant_id for v in result] == [1, 2]
    assert result[1].device_spec is None
    assert result[1].options is None
    _variants(service).list.assert_called_once_with(packageName="com.example.app", versionCode=42)


def test_list_system_apk_variants_empty():
    service = MagicMock()
    _variants(service).list.return_value.execute.return_value = {}
    client = _client(service)

    result = client.list_system_apk_variants("com.example.app", 42)

    assert result == []


def test_list_system_apk_variants_http_error():
    service = MagicMock()
    _variants(service).list.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to list system APK variants"):
        client.list_system_apk_variants("com.example.app", 42)


# ---------------------------------------------------------------------------
# Client: create_system_apk_variant
# ---------------------------------------------------------------------------


def test_create_system_apk_variant_success():
    service = MagicMock()
    _variants(service).create.return_value.execute.return_value = _VARIANT_RESPONSE
    client = _client(service)

    body = {"deviceSpec": {"screenDensity": 480}}
    result = client.create_system_apk_variant("com.example.app", 42, body)

    assert isinstance(result, SystemApkVariant)
    assert result.variant_id == 1
    assert result.version_code == 42
    _variants(service).create.assert_called_once_with(
        packageName="com.example.app",
        versionCode=42,
        body=body,
    )


def test_create_system_apk_variant_http_error():
    service = MagicMock()
    _variants(service).create.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to create system APK variant"):
        client.create_system_apk_variant("com.example.app", 42, {"deviceSpec": {}})


# ---------------------------------------------------------------------------
# Client: download_system_apk_variant
# ---------------------------------------------------------------------------


def test_download_system_apk_variant_success(monkeypatch, tmp_path):
    service = MagicMock()
    request = MagicMock()
    _variants(service).download.return_value = request
    client = _client(service)

    downloader_instance = MagicMock()
    downloader_instance.next_chunk.return_value = (MagicMock(), True)
    downloader_cls = MagicMock(return_value=downloader_instance)
    monkeypatch.setattr(client_module, "MediaIoBaseDownload", downloader_cls)

    client._download_dir = str(tmp_path)
    destination = tmp_path / "variant.apk"
    result = client.download_system_apk_variant("com.example.app", 42, 1, str(destination))

    assert isinstance(result, DownloadResult)
    assert result.success is True
    assert result.destination_path == str(destination)
    assert result.error is None
    assert destination.exists()

    _variants(service).download.assert_called_once_with(
        packageName="com.example.app",
        versionCode=42,
        variantId=1,
        alt="media",
    )
    assert downloader_cls.call_args.args[1] is request
    downloader_instance.next_chunk.assert_called_once_with()


def test_download_system_apk_variant_http_error(monkeypatch, tmp_path):
    service = MagicMock()
    _variants(service).download.side_effect = _make_http_error("bad")
    client = _client(service)

    monkeypatch.setattr(client_module, "MediaIoBaseDownload", MagicMock())

    with pytest.raises(PlayStoreClientError, match="Failed to download system APK variant"):
        client.download_system_apk_variant("com.example.app", 42, 1, str(tmp_path / "variant.apk"))


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_tool_get_system_apk_variant(monkeypatch):
    mc = MagicMock()
    mc.get_system_apk_variant.return_value = SystemApkVariant(
        package_name="com.example.app", version_code=42, variant_id=1
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.get_system_apk_variant("com.example.app", 42, 1)

    assert result["variant_id"] == 1
    mc.get_system_apk_variant.assert_called_once_with(
        package_name="com.example.app", version_code=42, variant_id=1
    )


def test_tool_list_system_apk_variants(monkeypatch):
    mc = MagicMock()
    mc.list_system_apk_variants.return_value = [
        SystemApkVariant(package_name="com.example.app", version_code=42, variant_id=1)
    ]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.list_system_apk_variants("com.example.app", 42)

    assert result[0]["variant_id"] == 1
    mc.list_system_apk_variants.assert_called_once_with(
        package_name="com.example.app", version_code=42
    )


def test_tool_create_system_apk_variant(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.create_system_apk_variant.return_value = SystemApkVariant(
        package_name="com.example.app", version_code=42, variant_id=1
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    body = {"deviceSpec": {"screenDensity": 480}}
    result = server.create_system_apk_variant("com.example.app", 42, body)

    assert result["variant_id"] == 1
    mc.create_system_apk_variant.assert_called_once_with(
        package_name="com.example.app",
        version_code=42,
        variant=body,
    )


def test_tool_download_system_apk_variant(monkeypatch):
    mc = MagicMock()
    mc.download_system_apk_variant.return_value = DownloadResult(
        success=True,
        destination_path="out/variant.apk",
        message="done",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.download_system_apk_variant("com.example.app", 42, 1, "out/variant.apk")

    assert result["success"] is True
    assert result["destination_path"] == "out/variant.apk"
    mc.download_system_apk_variant.assert_called_once_with(
        package_name="com.example.app",
        version_code=42,
        variant_id=1,
        destination_path="out/variant.apk",
    )
