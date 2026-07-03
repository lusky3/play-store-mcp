"""Tests for generated APK tools (generatedapks resource)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.client as client_module
import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import DownloadResult, GeneratedApksDownload

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_generated_apks_download_model():
    item = GeneratedApksDownload(
        package_name="com.example.app",
        version_code=42,
        download_id="abc123",
        apk_type="split",
    )
    assert item.package_name == "com.example.app"
    assert item.version_code == 42
    assert item.download_id == "abc123"
    assert item.apk_type == "split"


def test_download_result_model_defaults():
    result = DownloadResult(
        success=True,
        destination_path="out/app.apk",
        message="done",
    )
    assert result.success is True
    assert result.destination_path == "out/app.apk"
    assert result.message == "done"
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


def _gak(service: MagicMock) -> MagicMock:
    return service.generatedapks.return_value


# A realistic per-signing-key response with download IDs across several sub-lists.
_LIST_RESPONSE = {
    "generatedApks": [
        {
            "certificateSha256Hash": "deadbeef",
            "generatedSplitApks": [
                {"downloadId": "split-1", "splitId": "", "moduleName": "base"},
                {"downloadId": "split-2", "splitId": "config.arm64", "moduleName": "base"},
            ],
            "generatedStandaloneApks": [
                {"downloadId": "standalone-1", "variantId": 0},
            ],
            "generatedAssetPackSlices": [
                {"downloadId": "slice-1", "sliceId": "0", "moduleName": "assets"},
            ],
            "generatedRecoveryModules": [
                {"downloadId": "recovery-1", "recoveryId": "1", "moduleName": "base"},
            ],
            "generatedUniversalApk": {"downloadId": "universal-1"},
        }
    ]
}


# ---------------------------------------------------------------------------
# Client: list_generated_apks
# ---------------------------------------------------------------------------


def test_list_generated_apks_success():
    service = MagicMock()
    _gak(service).list.return_value.execute.return_value = _LIST_RESPONSE
    client = _client(service)

    result = client.list_generated_apks("com.example.app", 42)

    assert all(isinstance(item, GeneratedApksDownload) for item in result)
    assert all(item.package_name == "com.example.app" for item in result)
    assert all(item.version_code == 42 for item in result)

    by_id = {item.download_id: item.apk_type for item in result}
    assert by_id == {
        "split-1": "split",
        "split-2": "split",
        "standalone-1": "standalone",
        "slice-1": "asset_pack_slice",
        "recovery-1": "recovery",
        "universal-1": "universal",
    }
    _gak(service).list.assert_called_once_with(packageName="com.example.app", versionCode=42)


def test_list_generated_apks_unprotected_variants_and_missing_ids():
    service = MagicMock()
    _gak(service).list.return_value.execute.return_value = {
        "generatedApks": [
            {
                "unprotectedGeneratedSplitApks": [{"downloadId": "usplit-1"}],
                "unprotectedGeneratedStandaloneApks": [{"downloadId": "ustandalone-1"}],
                # Entry with no downloadId is skipped.
                "generatedSplitApks": [{"splitId": "no-id"}],
                # Universal present but without a downloadId is skipped.
                "generatedUniversalApk": {},
            }
        ]
    }
    client = _client(service)

    result = client.list_generated_apks("com.example.app", 7)

    by_id = {item.download_id: item.apk_type for item in result}
    assert by_id == {"usplit-1": "split", "ustandalone-1": "standalone"}


def test_list_generated_apks_empty():
    service = MagicMock()
    _gak(service).list.return_value.execute.return_value = {}
    client = _client(service)

    result = client.list_generated_apks("com.example.app", 42)

    assert result == []


def test_list_generated_apks_http_error():
    service = MagicMock()
    _gak(service).list.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to list generated APKs"):
        client.list_generated_apks("com.example.app", 42)


# ---------------------------------------------------------------------------
# Client: download_generated_apk
# ---------------------------------------------------------------------------


def test_download_generated_apk_success(monkeypatch, tmp_path):
    service = MagicMock()
    request = MagicMock()
    _gak(service).download.return_value = request
    client = _client(service)

    downloader_instance = MagicMock()
    downloader_instance.next_chunk.return_value = (MagicMock(), True)
    downloader_cls = MagicMock(return_value=downloader_instance)
    monkeypatch.setattr(client_module, "MediaIoBaseDownload", downloader_cls)

    destination = tmp_path / "app.apk"
    result = client.download_generated_apk("com.example.app", 42, "split-1", str(destination))

    assert isinstance(result, DownloadResult)
    assert result.success is True
    assert result.destination_path == str(destination)
    assert result.error is None
    # The destination file was created/opened for writing.
    assert destination.exists()

    _gak(service).download.assert_called_once_with(
        packageName="com.example.app",
        versionCode=42,
        downloadId="split-1",
        alt="media",
    )
    # MediaIoBaseDownload was constructed with the request and driven to completion.
    assert downloader_cls.call_args.args[1] is request
    downloader_instance.next_chunk.assert_called_once_with()


def test_download_generated_apk_http_error(monkeypatch, tmp_path):
    service = MagicMock()
    _gak(service).download.side_effect = _make_http_error("bad")
    client = _client(service)

    monkeypatch.setattr(client_module, "MediaIoBaseDownload", MagicMock())

    with pytest.raises(PlayStoreClientError, match="Failed to download generated APK"):
        client.download_generated_apk("com.example.app", 42, "split-1", str(tmp_path / "app.apk"))


def test_download_generated_apk_failure_preserves_destination(monkeypatch, tmp_path):
    """A download failure must not truncate an existing file or leave a partial one."""
    service = MagicMock()
    _gak(service).download.return_value = MagicMock()
    client = _client(service)

    # Fail mid-stream, after the temp file has been opened.
    downloader_instance = MagicMock()
    downloader_instance.next_chunk.side_effect = _make_http_error("interrupted")
    monkeypatch.setattr(
        client_module, "MediaIoBaseDownload", MagicMock(return_value=downloader_instance)
    )

    destination = tmp_path / "existing.apk"
    destination.write_bytes(b"original-contents")

    with pytest.raises(PlayStoreClientError, match="Failed to download generated APK"):
        client.download_generated_apk("com.example.app", 42, "split-1", str(destination))

    # The pre-existing file is untouched and no partial/temp file is left behind.
    assert destination.read_bytes() == b"original-contents"
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "existing.apk"]
    assert leftovers == []


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_tool_list_generated_apks(monkeypatch):
    mc = MagicMock()
    mc.list_generated_apks.return_value = [
        GeneratedApksDownload(
            package_name="com.example.app",
            version_code=42,
            download_id="split-1",
            apk_type="split",
        )
    ]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.list_generated_apks("com.example.app", 42)

    assert result[0]["download_id"] == "split-1"
    assert result[0]["apk_type"] == "split"
    mc.list_generated_apks.assert_called_once_with(package_name="com.example.app", version_code=42)


def test_tool_download_generated_apk(monkeypatch):
    mc = MagicMock()
    mc.download_generated_apk.return_value = DownloadResult(
        success=True,
        destination_path="out/app.apk",
        message="done",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.download_generated_apk("com.example.app", 42, "split-1", "out/app.apk")

    assert result["success"] is True
    assert result["destination_path"] == "out/app.apk"
    mc.download_generated_apk.assert_called_once_with(
        package_name="com.example.app",
        version_code=42,
        download_id="split-1",
        destination_path="out/app.apk",
    )
