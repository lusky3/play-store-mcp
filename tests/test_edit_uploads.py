"""Tests for edit upload tools (apks, bundles, deobfuscation & expansion files)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.client as client_module
import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import Apk, Bundle, DeobfuscationFile, ExpansionFile

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


def _edits(service: MagicMock) -> MagicMock:
    """The mock returned by service.edits()."""
    return service.edits.return_value


def _prime_edit(service: MagicMock, edit_id: str = "edit-123") -> None:
    """Wire edits().insert().execute() to return an edit id."""
    _edits(service).insert.return_value.execute.return_value = {"id": edit_id}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_apk_model_defaults():
    apk = Apk(package_name="com.example.app", version_code=42)
    assert apk.package_name == "com.example.app"
    assert apk.version_code == 42
    assert apk.sha1 is None
    assert apk.sha256 is None


def test_bundle_model_defaults():
    bundle = Bundle(package_name="com.example.app", version_code=7)
    assert bundle.package_name == "com.example.app"
    assert bundle.version_code == 7
    assert bundle.sha1 is None
    assert bundle.sha256 is None


def test_deobfuscation_file_model_defaults():
    dfile = DeobfuscationFile(package_name="com.example.app", version_code=3)
    assert dfile.package_name == "com.example.app"
    assert dfile.version_code == 3
    assert dfile.symbol_type is None


def test_apk_model_full():
    apk = Apk(package_name="com.example.app", version_code=42, sha1="aa", sha256="bb")
    assert apk.sha1 == "aa"
    assert apk.sha256 == "bb"


def test_bundle_model_full():
    bundle = Bundle(package_name="com.example.app", version_code=7, sha1="cc", sha256="dd")
    assert bundle.sha1 == "cc"
    assert bundle.sha256 == "dd"


def test_deobfuscation_file_model_full():
    dfile = DeobfuscationFile(
        package_name="com.example.app", version_code=3, symbol_type="proguard"
    )
    assert dfile.symbol_type == "proguard"


# ---------------------------------------------------------------------------
# Client: list_apks (READ — edit created then abandoned)
# ---------------------------------------------------------------------------


def test_list_apks_success():
    service = MagicMock()
    _prime_edit(service)
    _edits(service).apks.return_value.list.return_value.execute.return_value = {
        "apks": [
            {"versionCode": 10, "binary": {"sha1": "s1", "sha256": "s256"}},
            {"versionCode": 11},
        ]
    }
    client = _client(service)

    apks = client.list_apks("com.example.app")

    assert [(a.version_code, a.sha1, a.sha256) for a in apks] == [
        (10, "s1", "s256"),
        (11, None, None),
    ]
    assert all(a.package_name == "com.example.app" for a in apks)
    _edits(service).apks.return_value.list.assert_called_once_with(
        packageName="com.example.app", editId="edit-123"
    )
    # Read pattern: edit abandoned, never committed.
    _edits(service).delete.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).commit.assert_not_called()


def test_list_apks_http_error_still_abandons_edit():
    service = MagicMock()
    _prime_edit(service)
    _edits(service).apks.return_value.list.return_value.execute.side_effect = _make_http_error()
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to list APKs"):
        client.list_apks("com.example.app")

    _edits(service).delete.assert_called_once_with(packageName="com.example.app", editId="edit-123")


# ---------------------------------------------------------------------------
# Client: list_bundles (READ)
# ---------------------------------------------------------------------------


def test_list_bundles_success():
    service = MagicMock()
    _prime_edit(service)
    _edits(service).bundles.return_value.list.return_value.execute.return_value = {
        "bundles": [
            {"versionCode": 20, "sha1": "b1", "sha256": "b256"},
            {"versionCode": 21},
        ]
    }
    client = _client(service)

    bundles = client.list_bundles("com.example.app")

    assert [(b.version_code, b.sha1, b.sha256) for b in bundles] == [
        (20, "b1", "b256"),
        (21, None, None),
    ]
    _edits(service).bundles.return_value.list.assert_called_once_with(
        packageName="com.example.app", editId="edit-123"
    )
    _edits(service).delete.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).commit.assert_not_called()


def test_list_bundles_http_error_still_abandons_edit():
    service = MagicMock()
    _prime_edit(service)
    _edits(service).bundles.return_value.list.return_value.execute.side_effect = _make_http_error()
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to list bundles"):
        client.list_bundles("com.example.app")

    _edits(service).delete.assert_called_once_with(packageName="com.example.app", editId="edit-123")


# ---------------------------------------------------------------------------
# Client: upload_apk (WRITE — commit on success)
# ---------------------------------------------------------------------------


def test_upload_apk_success(monkeypatch):
    service = MagicMock()
    _prime_edit(service)
    _edits(service).apks.return_value.upload.return_value.execute.return_value = {
        "versionCode": 30,
        "binary": {"sha1": "a1", "sha256": "a256"},
    }
    fake_media = MagicMock(name="media")
    media_ctor = MagicMock(return_value=fake_media)
    monkeypatch.setattr(client_module, "MediaFileUpload", media_ctor)
    client = _client(service)

    result = client.upload_apk("com.example.app", "/data/build/app.apk")

    assert isinstance(result, Apk)
    assert (result.version_code, result.sha1, result.sha256) == (30, "a1", "a256")
    media_ctor.assert_called_once_with(
        "/data/build/app.apk",
        mimetype="application/vnd.android.package-archive",
        resumable=True,
    )
    _edits(service).apks.return_value.upload.assert_called_once_with(
        packageName="com.example.app", editId="edit-123", media_body=fake_media
    )
    # Write pattern: edit committed, not abandoned.
    _edits(service).commit.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).delete.assert_not_called()


def test_upload_apk_http_error_abandons_edit(monkeypatch):
    service = MagicMock()
    _prime_edit(service)
    _edits(service).apks.return_value.upload.return_value.execute.side_effect = _make_http_error(
        "bad apk"
    )
    monkeypatch.setattr(client_module, "MediaFileUpload", MagicMock())
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to upload APK"):
        client.upload_apk("com.example.app", "/data/build/app.apk")

    _edits(service).delete.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).commit.assert_not_called()


# ---------------------------------------------------------------------------
# Client: upload_bundle (WRITE)
# ---------------------------------------------------------------------------


def test_upload_bundle_success(monkeypatch):
    service = MagicMock()
    _prime_edit(service)
    _edits(service).bundles.return_value.upload.return_value.execute.return_value = {
        "versionCode": 40,
        "sha1": "u1",
        "sha256": "u256",
    }
    fake_media = MagicMock(name="media")
    media_ctor = MagicMock(return_value=fake_media)
    monkeypatch.setattr(client_module, "MediaFileUpload", media_ctor)
    client = _client(service)

    result = client.upload_bundle("com.example.app", "/data/build/app.aab")

    assert isinstance(result, Bundle)
    assert (result.version_code, result.sha1, result.sha256) == (40, "u1", "u256")
    media_ctor.assert_called_once_with(
        "/data/build/app.aab",
        mimetype="application/octet-stream",
        resumable=True,
    )
    _edits(service).bundles.return_value.upload.assert_called_once_with(
        packageName="com.example.app", editId="edit-123", media_body=fake_media
    )
    _edits(service).commit.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).delete.assert_not_called()


def test_upload_bundle_http_error_abandons_edit(monkeypatch):
    service = MagicMock()
    _prime_edit(service)
    _edits(service).bundles.return_value.upload.return_value.execute.side_effect = _make_http_error(
        "bad aab"
    )
    monkeypatch.setattr(client_module, "MediaFileUpload", MagicMock())
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to upload bundle"):
        client.upload_bundle("com.example.app", "/data/build/app.aab")

    _edits(service).delete.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).commit.assert_not_called()


# ---------------------------------------------------------------------------
# Client: upload_deobfuscation_file (WRITE)
# ---------------------------------------------------------------------------


def test_upload_deobfuscation_file_success(monkeypatch):
    service = MagicMock()
    _prime_edit(service)
    _edits(service).deobfuscationfiles.return_value.upload.return_value.execute.return_value = {
        "deobfuscationFile": {"symbolType": "proguard"}
    }
    fake_media = MagicMock(name="media")
    media_ctor = MagicMock(return_value=fake_media)
    monkeypatch.setattr(client_module, "MediaFileUpload", media_ctor)
    client = _client(service)

    result = client.upload_deobfuscation_file(
        "com.example.app", 30, "/data/build/mapping.txt", "proguard"
    )

    assert isinstance(result, DeobfuscationFile)
    assert result.version_code == 30
    assert result.symbol_type == "proguard"
    media_ctor.assert_called_once_with(
        "/data/build/mapping.txt", mimetype="application/octet-stream", resumable=True
    )
    _edits(service).deobfuscationfiles.return_value.upload.assert_called_once_with(
        packageName="com.example.app",
        editId="edit-123",
        apkVersionCode=30,
        deobfuscationFileType="proguard",
        media_body=fake_media,
    )
    _edits(service).commit.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).delete.assert_not_called()


def test_upload_deobfuscation_file_default_type_and_missing_response(monkeypatch):
    service = MagicMock()
    _prime_edit(service)
    # Response without a deobfuscationFile key exercises the `or {}` fallback.
    _edits(service).deobfuscationfiles.return_value.upload.return_value.execute.return_value = {}
    monkeypatch.setattr(client_module, "MediaFileUpload", MagicMock())
    client = _client(service)

    result = client.upload_deobfuscation_file("com.example.app", 5, "/data/build/symbols.zip")

    assert result.symbol_type is None
    _edits(service).deobfuscationfiles.return_value.upload.assert_called_once_with(
        packageName="com.example.app",
        editId="edit-123",
        apkVersionCode=5,
        deobfuscationFileType="proguard",
        media_body=client_module.MediaFileUpload.return_value,
    )


def test_upload_deobfuscation_file_http_error_abandons_edit(monkeypatch):
    service = MagicMock()
    _prime_edit(service)
    _edits(
        service
    ).deobfuscationfiles.return_value.upload.return_value.execute.side_effect = _make_http_error(
        "bad map"
    )
    monkeypatch.setattr(client_module, "MediaFileUpload", MagicMock())
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to upload deobfuscation file"):
        client.upload_deobfuscation_file("com.example.app", 30, "/data/build/mapping.txt")

    _edits(service).delete.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).commit.assert_not_called()


# ---------------------------------------------------------------------------
# Client: upload_expansion_file (WRITE)
# ---------------------------------------------------------------------------


def test_upload_expansion_file_success(monkeypatch):
    service = MagicMock()
    _prime_edit(service)
    _edits(service).expansionfiles.return_value.upload.return_value.execute.return_value = {
        "expansionFile": {"fileSize": 123456, "referencesVersion": 29}
    }
    fake_media = MagicMock(name="media")
    media_ctor = MagicMock(return_value=fake_media)
    monkeypatch.setattr(client_module, "MediaFileUpload", media_ctor)
    client = _client(service)

    result = client.upload_expansion_file("com.example.app", 30, "/data/build/main.obb", "main")

    assert isinstance(result, ExpansionFile)
    assert result.version_code == 30
    assert result.expansion_file_type == "main"
    assert result.file_size == 123456
    assert result.references_version == 29
    media_ctor.assert_called_once_with(
        "/data/build/main.obb", mimetype="application/octet-stream", resumable=True
    )
    _edits(service).expansionfiles.return_value.upload.assert_called_once_with(
        packageName="com.example.app",
        editId="edit-123",
        apkVersionCode=30,
        expansionFileType="main",
        media_body=fake_media,
    )
    _edits(service).commit.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).delete.assert_not_called()


def test_upload_expansion_file_default_type_and_missing_response(monkeypatch):
    service = MagicMock()
    _prime_edit(service)
    _edits(service).expansionfiles.return_value.upload.return_value.execute.return_value = {}
    monkeypatch.setattr(client_module, "MediaFileUpload", MagicMock())
    client = _client(service)

    result = client.upload_expansion_file("com.example.app", 8, "/data/build/patch.obb")

    assert result.expansion_file_type == "main"
    assert result.file_size is None
    assert result.references_version is None
    _edits(service).expansionfiles.return_value.upload.assert_called_once_with(
        packageName="com.example.app",
        editId="edit-123",
        apkVersionCode=8,
        expansionFileType="main",
        media_body=client_module.MediaFileUpload.return_value,
    )


def test_upload_expansion_file_http_error_abandons_edit(monkeypatch):
    service = MagicMock()
    _prime_edit(service)
    _edits(
        service
    ).expansionfiles.return_value.upload.return_value.execute.side_effect = _make_http_error(
        "bad obb"
    )
    monkeypatch.setattr(client_module, "MediaFileUpload", MagicMock())
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to upload expansion file"):
        client.upload_expansion_file("com.example.app", 30, "/data/build/main.obb")

    _edits(service).delete.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).commit.assert_not_called()


# ---------------------------------------------------------------------------
# MCP tools (delegation)
# ---------------------------------------------------------------------------


def test_tool_list_apks(monkeypatch):
    mc = MagicMock()
    mc.list_apks.return_value = [Apk(package_name="com.example.app", version_code=10, sha1="s1")]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.list_apks("com.example.app")

    assert result == [
        {"package_name": "com.example.app", "version_code": 10, "sha1": "s1", "sha256": None}
    ]
    mc.list_apks.assert_called_once_with("com.example.app")


def test_tool_list_bundles(monkeypatch):
    mc = MagicMock()
    mc.list_bundles.return_value = [
        Bundle(package_name="com.example.app", version_code=20, sha256="b256")
    ]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.list_bundles("com.example.app")

    assert result == [
        {"package_name": "com.example.app", "version_code": 20, "sha1": None, "sha256": "b256"}
    ]
    mc.list_bundles.assert_called_once_with("com.example.app")


def test_tool_upload_apk(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.upload_apk.return_value = Apk(package_name="com.example.app", version_code=30, sha1="a1")
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.upload_apk("com.example.app", "/data/build/app.apk")

    assert result["version_code"] == 30
    assert result["sha1"] == "a1"
    mc.upload_apk.assert_called_once_with(
        package_name="com.example.app", apk_path="/data/build/app.apk"
    )


def test_tool_upload_bundle(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.upload_bundle.return_value = Bundle(
        package_name="com.example.app", version_code=40, sha256="u256"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.upload_bundle("com.example.app", "/data/build/app.aab")

    assert result["version_code"] == 40
    assert result["sha256"] == "u256"
    mc.upload_bundle.assert_called_once_with(
        package_name="com.example.app", bundle_path="/data/build/app.aab"
    )


def test_tool_upload_deobfuscation_file(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.upload_deobfuscation_file.return_value = DeobfuscationFile(
        package_name="com.example.app", version_code=30, symbol_type="nativeCode"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.upload_deobfuscation_file(
        "com.example.app", 30, "/data/build/symbols.zip", "nativeCode"
    )

    assert result["symbol_type"] == "nativeCode"
    mc.upload_deobfuscation_file.assert_called_once_with(
        package_name="com.example.app",
        version_code=30,
        file_path="/data/build/symbols.zip",
        deobfuscation_file_type="nativeCode",
    )


def test_tool_upload_expansion_file(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.upload_expansion_file.return_value = ExpansionFile(
        version_code=30, expansion_file_type="patch", file_size=99, references_version=29
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.upload_expansion_file("com.example.app", 30, "/data/build/patch.obb", "patch")

    assert result["file_size"] == 99
    assert result["references_version"] == 29
    assert result["expansion_file_type"] == "patch"
    mc.upload_expansion_file.assert_called_once_with(
        package_name="com.example.app",
        version_code=30,
        file_path="/data/build/patch.obb",
        expansion_file_type="patch",
    )
