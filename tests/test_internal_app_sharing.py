"""Tests for internal app sharing tools (internalappsharingartifacts)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.client as client_module
import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import InternalAppSharingArtifact

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_internal_app_sharing_artifact_defaults():
    artifact = InternalAppSharingArtifact(package_name="com.example.app")
    assert artifact.package_name == "com.example.app"
    assert artifact.download_url is None
    assert artifact.certificate_fingerprint is None
    assert artifact.sha256 is None


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


def _iasa(service: MagicMock) -> MagicMock:
    return service.internalappsharingartifacts.return_value


_ARTIFACT_RESPONSE = {
    "downloadUrl": "https://play.google.com/apps/test/abc123",
    "certificateFingerprint": "AA:BB:CC",
    "sha256": "deadbeef",
}


# ---------------------------------------------------------------------------
# Client: upload_internal_app_sharing_apk
# ---------------------------------------------------------------------------


def test_upload_internal_app_sharing_apk_success(monkeypatch):
    service = MagicMock()
    _iasa(service).uploadapk.return_value.execute.return_value = _ARTIFACT_RESPONSE
    fake_media = MagicMock(name="media")
    media_ctor = MagicMock(return_value=fake_media)
    monkeypatch.setattr(client_module, "MediaFileUpload", media_ctor)
    client = _client(service)

    result = client.upload_internal_app_sharing_apk("com.example.app", "app.apk")

    assert isinstance(result, InternalAppSharingArtifact)
    assert result.package_name == "com.example.app"
    assert result.download_url == "https://play.google.com/apps/test/abc123"
    assert result.certificate_fingerprint == "AA:BB:CC"
    assert result.sha256 == "deadbeef"
    media_ctor.assert_called_once_with(
        "app.apk",
        mimetype="application/vnd.android.package-archive",
        resumable=True,
    )
    _iasa(service).uploadapk.assert_called_once_with(
        packageName="com.example.app", media_body=fake_media
    )


def test_upload_internal_app_sharing_apk_http_error(monkeypatch):
    service = MagicMock()
    _iasa(service).uploadapk.return_value.execute.side_effect = _make_http_error("bad")
    monkeypatch.setattr(client_module, "MediaFileUpload", MagicMock())
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to upload internal app sharing APK"):
        client.upload_internal_app_sharing_apk("com.example.app", "app.apk")


# ---------------------------------------------------------------------------
# Client: upload_internal_app_sharing_bundle
# ---------------------------------------------------------------------------


def test_upload_internal_app_sharing_bundle_success(monkeypatch):
    service = MagicMock()
    _iasa(service).uploadbundle.return_value.execute.return_value = _ARTIFACT_RESPONSE
    fake_media = MagicMock(name="media")
    media_ctor = MagicMock(return_value=fake_media)
    monkeypatch.setattr(client_module, "MediaFileUpload", media_ctor)
    client = _client(service)

    result = client.upload_internal_app_sharing_bundle("com.example.app", "app.aab")

    assert isinstance(result, InternalAppSharingArtifact)
    assert result.package_name == "com.example.app"
    assert result.download_url == "https://play.google.com/apps/test/abc123"
    assert result.certificate_fingerprint == "AA:BB:CC"
    assert result.sha256 == "deadbeef"
    media_ctor.assert_called_once_with(
        "app.aab",
        mimetype="application/octet-stream",
        resumable=True,
    )
    _iasa(service).uploadbundle.assert_called_once_with(
        packageName="com.example.app", media_body=fake_media
    )


def test_upload_internal_app_sharing_bundle_http_error(monkeypatch):
    service = MagicMock()
    _iasa(service).uploadbundle.return_value.execute.side_effect = _make_http_error("bad")
    monkeypatch.setattr(client_module, "MediaFileUpload", MagicMock())
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to upload internal app sharing bundle"):
        client.upload_internal_app_sharing_bundle("com.example.app", "app.aab")


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_tool_upload_internal_app_sharing_apk(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.upload_internal_app_sharing_apk.return_value = InternalAppSharingArtifact(
        package_name="com.example.app", download_url="https://dl/x", sha256="abc"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.upload_internal_app_sharing_apk("com.example.app", "app.apk")

    assert result["download_url"] == "https://dl/x"
    assert result["sha256"] == "abc"
    mc.upload_internal_app_sharing_apk.assert_called_once_with(
        package_name="com.example.app", apk_path="app.apk"
    )


def test_tool_upload_internal_app_sharing_bundle(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.upload_internal_app_sharing_bundle.return_value = InternalAppSharingArtifact(
        package_name="com.example.app", download_url="https://dl/y", sha256="def"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.upload_internal_app_sharing_bundle("com.example.app", "app.aab")

    assert result["download_url"] == "https://dl/y"
    assert result["sha256"] == "def"
    mc.upload_internal_app_sharing_bundle.assert_called_once_with(
        package_name="com.example.app", bundle_path="app.aab"
    )
