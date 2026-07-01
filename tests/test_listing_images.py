"""Tests for store-listing image tools (edits.images: list/upload/delete/deleteall)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.client as client_module
import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import AppImage, ImageDeleteResult

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


def _images(service: MagicMock) -> MagicMock:
    """The mock returned by service.edits().images()."""
    return _edits(service).images.return_value


def _prime_edit(service: MagicMock, edit_id: str = "edit-123") -> None:
    """Wire edits().insert().execute() to return an edit id."""
    _edits(service).insert.return_value.execute.return_value = {"id": edit_id}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_app_image_model_defaults():
    image = AppImage(package_name="com.example.app", language="en-US", image_type="icon")
    assert image.package_name == "com.example.app"
    assert image.language == "en-US"
    assert image.image_type == "icon"
    assert image.image_id is None
    assert image.url is None
    assert image.sha1 is None
    assert image.sha256 is None


def test_app_image_model_full():
    image = AppImage(
        package_name="com.example.app",
        language="en-US",
        image_type="phoneScreenshots",
        image_id="img-1",
        url="https://play.example/img-1",
        sha1="s1",
        sha256="s256",
    )
    assert image.image_id == "img-1"
    assert image.url == "https://play.example/img-1"
    assert image.sha1 == "s1"
    assert image.sha256 == "s256"


def test_image_delete_result_defaults():
    result = ImageDeleteResult(
        success=True,
        package_name="com.example.app",
        language="en-US",
        image_type="icon",
        message="done",
    )
    assert result.success is True
    assert result.deleted_count == 0
    assert result.error is None


def test_image_delete_result_full():
    result = ImageDeleteResult(
        success=False,
        package_name="com.example.app",
        language="en-US",
        image_type="icon",
        deleted_count=3,
        message="failed",
        error="boom",
    )
    assert result.deleted_count == 3
    assert result.error == "boom"


# ---------------------------------------------------------------------------
# Client: _parse_app_image helper
# ---------------------------------------------------------------------------


def test_parse_app_image_maps_fields():
    image = PlayStoreClient._parse_app_image(
        "com.example.app",
        "en-US",
        "featureGraphic",
        {"id": "img-9", "url": "https://x/y", "sha1": "aa", "sha256": "bb"},
    )
    assert isinstance(image, AppImage)
    assert (image.image_id, image.url, image.sha1, image.sha256) == (
        "img-9",
        "https://x/y",
        "aa",
        "bb",
    )
    assert (image.package_name, image.language, image.image_type) == (
        "com.example.app",
        "en-US",
        "featureGraphic",
    )


def test_parse_app_image_missing_fields():
    image = PlayStoreClient._parse_app_image("com.example.app", "en-US", "icon", {})
    assert image.image_id is None
    assert image.url is None
    assert image.sha1 is None
    assert image.sha256 is None


# ---------------------------------------------------------------------------
# Client: list_images (READ — edit created then abandoned)
# ---------------------------------------------------------------------------


def test_list_images_success():
    service = MagicMock()
    _prime_edit(service)
    _images(service).list.return_value.execute.return_value = {
        "images": [
            {"id": "i1", "url": "u1", "sha1": "s1", "sha256": "h1"},
            {"id": "i2"},
        ]
    }
    client = _client(service)

    images = client.list_images("com.example.app", "en-US", "phoneScreenshots")

    assert [(i.image_id, i.url, i.sha1, i.sha256) for i in images] == [
        ("i1", "u1", "s1", "h1"),
        ("i2", None, None, None),
    ]
    assert all(i.package_name == "com.example.app" for i in images)
    assert all(i.language == "en-US" for i in images)
    assert all(i.image_type == "phoneScreenshots" for i in images)
    _images(service).list.assert_called_once_with(
        packageName="com.example.app",
        editId="edit-123",
        language="en-US",
        imageType="phoneScreenshots",
    )
    # Read pattern: edit abandoned, never committed.
    _edits(service).delete.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).commit.assert_not_called()


def test_list_images_empty_response():
    service = MagicMock()
    _prime_edit(service)
    _images(service).list.return_value.execute.return_value = {}
    client = _client(service)

    images = client.list_images("com.example.app", "en-US", "icon")

    assert images == []
    _edits(service).delete.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).commit.assert_not_called()


def test_list_images_http_error_still_abandons_edit():
    service = MagicMock()
    _prime_edit(service)
    _images(service).list.return_value.execute.side_effect = _make_http_error()
    client = _client(service)

    with pytest.raises(HttpError):
        client.list_images("com.example.app", "en-US", "icon")

    _edits(service).delete.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).commit.assert_not_called()


# ---------------------------------------------------------------------------
# Client: upload_image (WRITE — commit on success)
# ---------------------------------------------------------------------------


def test_upload_image_success_png(monkeypatch):
    service = MagicMock()
    _prime_edit(service)
    _images(service).upload.return_value.execute.return_value = {
        "image": {"id": "img-30", "url": "u30", "sha1": "a1", "sha256": "a256"}
    }
    fake_media = MagicMock(name="media")
    media_ctor = MagicMock(return_value=fake_media)
    monkeypatch.setattr(client_module, "MediaFileUpload", media_ctor)
    client = _client(service)

    result = client.upload_image("com.example.app", "en-US", "icon", "/data/assets/icon.png")

    assert isinstance(result, AppImage)
    assert (result.image_id, result.url, result.sha1, result.sha256) == (
        "img-30",
        "u30",
        "a1",
        "a256",
    )
    assert (result.language, result.image_type) == ("en-US", "icon")
    media_ctor.assert_called_once_with(
        "/data/assets/icon.png", mimetype="image/png", resumable=True
    )
    _images(service).upload.assert_called_once_with(
        packageName="com.example.app",
        editId="edit-123",
        language="en-US",
        imageType="icon",
        media_body=fake_media,
    )
    # Write pattern: edit committed, not abandoned.
    _edits(service).commit.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).delete.assert_not_called()


def test_upload_image_jpeg_mimetype_and_missing_image(monkeypatch):
    service = MagicMock()
    _prime_edit(service)
    # Response without an "image" key exercises the `or {}` fallback.
    _images(service).upload.return_value.execute.return_value = {}
    media_ctor = MagicMock()
    monkeypatch.setattr(client_module, "MediaFileUpload", media_ctor)
    client = _client(service)

    result = client.upload_image(
        "com.example.app", "fr-FR", "featureGraphic", "/data/assets/banner.jpg"
    )

    assert result.image_id is None
    assert result.url is None
    media_ctor.assert_called_once_with(
        "/data/assets/banner.jpg", mimetype="image/jpeg", resumable=True
    )
    _edits(service).commit.assert_called_once_with(packageName="com.example.app", editId="edit-123")


def test_upload_image_http_error_abandons_edit(monkeypatch):
    service = MagicMock()
    _prime_edit(service)
    _images(service).upload.return_value.execute.side_effect = _make_http_error("bad image")
    monkeypatch.setattr(client_module, "MediaFileUpload", MagicMock())
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to upload image"):
        client.upload_image("com.example.app", "en-US", "icon", "/data/assets/icon.png")

    _edits(service).delete.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).commit.assert_not_called()


# ---------------------------------------------------------------------------
# Client: delete_image (WRITE — commit on success, empty response)
# ---------------------------------------------------------------------------


def test_delete_image_success():
    service = MagicMock()
    _prime_edit(service)
    _images(service).delete.return_value.execute.return_value = {}
    client = _client(service)

    result = client.delete_image("com.example.app", "en-US", "phoneScreenshots", "img-1")

    assert isinstance(result, ImageDeleteResult)
    assert result.success is True
    assert result.deleted_count == 1
    assert (result.language, result.image_type) == ("en-US", "phoneScreenshots")
    _images(service).delete.assert_called_once_with(
        packageName="com.example.app",
        editId="edit-123",
        language="en-US",
        imageType="phoneScreenshots",
        imageId="img-1",
    )
    _edits(service).commit.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).delete.assert_not_called()


def test_delete_image_http_error_abandons_edit():
    service = MagicMock()
    _prime_edit(service)
    _images(service).delete.return_value.execute.side_effect = _make_http_error("nope")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to delete image"):
        client.delete_image("com.example.app", "en-US", "icon", "img-1")

    _edits(service).delete.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).commit.assert_not_called()


# ---------------------------------------------------------------------------
# Client: delete_all_images (WRITE — commit on success, {deleted:[...]} response)
# ---------------------------------------------------------------------------


def test_delete_all_images_success():
    service = MagicMock()
    _prime_edit(service)
    _images(service).deleteall.return_value.execute.return_value = {
        "deleted": [{"id": "i1"}, {"id": "i2"}, {"id": "i3"}]
    }
    client = _client(service)

    result = client.delete_all_images("com.example.app", "en-US", "phoneScreenshots")

    assert isinstance(result, ImageDeleteResult)
    assert result.success is True
    assert result.deleted_count == 3
    _images(service).deleteall.assert_called_once_with(
        packageName="com.example.app",
        editId="edit-123",
        language="en-US",
        imageType="phoneScreenshots",
    )
    _edits(service).commit.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).delete.assert_not_called()


def test_delete_all_images_empty_response():
    service = MagicMock()
    _prime_edit(service)
    _images(service).deleteall.return_value.execute.return_value = {}
    client = _client(service)

    result = client.delete_all_images("com.example.app", "en-US", "icon")

    assert result.deleted_count == 0
    _edits(service).commit.assert_called_once_with(packageName="com.example.app", editId="edit-123")


def test_delete_all_images_http_error_abandons_edit():
    service = MagicMock()
    _prime_edit(service)
    _images(service).deleteall.return_value.execute.side_effect = _make_http_error("nope")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to delete all images"):
        client.delete_all_images("com.example.app", "en-US", "icon")

    _edits(service).delete.assert_called_once_with(packageName="com.example.app", editId="edit-123")
    _edits(service).commit.assert_not_called()


# ---------------------------------------------------------------------------
# MCP tools (delegation)
# ---------------------------------------------------------------------------


def test_tool_list_images(monkeypatch):
    mc = MagicMock()
    mc.list_images.return_value = [
        AppImage(
            package_name="com.example.app",
            language="en-US",
            image_type="icon",
            image_id="i1",
            sha1="s1",
        )
    ]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.list_images("com.example.app", "en-US", "icon")

    assert result == [
        {
            "package_name": "com.example.app",
            "language": "en-US",
            "image_type": "icon",
            "image_id": "i1",
            "url": None,
            "sha1": "s1",
            "sha256": None,
        }
    ]
    mc.list_images.assert_called_once_with("com.example.app", "en-US", "icon")


def test_tool_upload_image(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.upload_image.return_value = AppImage(
        package_name="com.example.app",
        language="en-US",
        image_type="icon",
        image_id="i30",
        url="u30",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.upload_image("com.example.app", "en-US", "icon", "/data/assets/icon.png")

    assert result["image_id"] == "i30"
    assert result["url"] == "u30"
    mc.upload_image.assert_called_once_with(
        package_name="com.example.app",
        language="en-US",
        image_type="icon",
        image_path="/data/assets/icon.png",
    )


def test_tool_delete_image(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.delete_image.return_value = ImageDeleteResult(
        success=True,
        package_name="com.example.app",
        language="en-US",
        image_type="icon",
        deleted_count=1,
        message="Deleted image i1",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.delete_image("com.example.app", "en-US", "icon", "i1")

    assert result["success"] is True
    assert result["deleted_count"] == 1
    mc.delete_image.assert_called_once_with(
        package_name="com.example.app",
        language="en-US",
        image_type="icon",
        image_id="i1",
    )


def test_tool_delete_all_images(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.delete_all_images.return_value = ImageDeleteResult(
        success=True,
        package_name="com.example.app",
        language="en-US",
        image_type="phoneScreenshots",
        deleted_count=4,
        message="Deleted 4 image(s)",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.delete_all_images("com.example.app", "en-US", "phoneScreenshots")

    assert result["deleted_count"] == 4
    mc.delete_all_images.assert_called_once_with(
        package_name="com.example.app",
        language="en-US",
        image_type="phoneScreenshots",
    )
