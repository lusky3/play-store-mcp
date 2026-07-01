"""Tests for in-app product catalog management (create/update/patch/delete/batch)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import InAppProduct, InAppProductActionResult

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_in_app_product_action_result_defaults():
    r = InAppProductActionResult(
        success=True, package_name="com.example.app", sku="sku1", message="ok"
    )
    assert r.success is True
    assert r.sku == "sku1"
    assert r.error is None


def test_in_app_product_action_result_batch_sku_none():
    r = InAppProductActionResult(success=True, package_name="com.example.app", message="ok")
    assert r.sku is None
    assert r.error is None


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


def _iap(service: MagicMock) -> MagicMock:
    return service.inappproducts.return_value


_PRODUCT_RESPONSE = {
    "sku": "premium_upgrade",
    "purchaseType": "managedProduct",
    "status": "active",
    "defaultLanguage": "en-US",
    "defaultPrice": {"priceMicros": "990000", "currency": "USD"},
    "listings": {"en-US": {"title": "Premium Upgrade", "description": "Unlock premium features"}},
}


# ---------------------------------------------------------------------------
# Client: create
# ---------------------------------------------------------------------------


def test_create_in_app_product_success():
    service = MagicMock()
    _iap(service).insert.return_value.execute.return_value = _PRODUCT_RESPONSE
    client = _client(service)

    body = {"sku": "premium_upgrade", "purchaseType": "managedProduct"}
    result = client.create_in_app_product("com.example.app", body)

    assert isinstance(result, InAppProduct)
    assert result.sku == "premium_upgrade"
    assert result.product_type == "managedProduct"
    assert result.title == "Premium Upgrade"
    assert result.description == "Unlock premium features"
    assert result.default_price == {"priceMicros": "990000", "currency": "USD"}
    _iap(service).insert.assert_called_once_with(packageName="com.example.app", body=body)


def test_create_in_app_product_http_error():
    service = MagicMock()
    _iap(service).insert.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to create in-app product"):
        client.create_in_app_product("com.example.app", {"sku": "sku1"})


# ---------------------------------------------------------------------------
# Client: update
# ---------------------------------------------------------------------------


def test_update_in_app_product_success_defaults():
    service = MagicMock()
    _iap(service).update.return_value.execute.return_value = _PRODUCT_RESPONSE
    client = _client(service)

    body = {"sku": "premium_upgrade", "status": "active"}
    result = client.update_in_app_product("com.example.app", "premium_upgrade", body)

    assert result.sku == "premium_upgrade"
    _iap(service).update.assert_called_once_with(
        packageName="com.example.app",
        sku="premium_upgrade",
        autoConvertMissingPrices=False,
        body=body,
    )


def test_update_in_app_product_auto_convert_true():
    service = MagicMock()
    _iap(service).update.return_value.execute.return_value = _PRODUCT_RESPONSE
    client = _client(service)

    body = {"sku": "premium_upgrade"}
    client.update_in_app_product(
        "com.example.app", "premium_upgrade", body, auto_convert_missing_prices=True
    )

    _iap(service).update.assert_called_once_with(
        packageName="com.example.app",
        sku="premium_upgrade",
        autoConvertMissingPrices=True,
        body=body,
    )


def test_update_in_app_product_http_error():
    service = MagicMock()
    _iap(service).update.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to update in-app product"):
        client.update_in_app_product("com.example.app", "sku1", {"sku": "sku1"})


# ---------------------------------------------------------------------------
# Client: patch
# ---------------------------------------------------------------------------


def test_patch_in_app_product_success():
    service = MagicMock()
    _iap(service).patch.return_value.execute.return_value = _PRODUCT_RESPONSE
    client = _client(service)

    body = {"status": "inactive"}
    result = client.patch_in_app_product("com.example.app", "premium_upgrade", body)

    assert result.sku == "premium_upgrade"
    _iap(service).patch.assert_called_once_with(
        packageName="com.example.app", sku="premium_upgrade", body=body
    )


def test_patch_in_app_product_no_default_price():
    service = MagicMock()
    _iap(service).patch.return_value.execute.return_value = {
        "sku": "premium_upgrade",
        "status": "active",
    }
    client = _client(service)

    result = client.patch_in_app_product("com.example.app", "premium_upgrade", {"status": "active"})

    assert result.default_price is None
    assert result.title is None
    assert result.product_type == "managedProduct"


def test_patch_in_app_product_http_error():
    service = MagicMock()
    _iap(service).patch.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to patch in-app product"):
        client.patch_in_app_product("com.example.app", "sku1", {"status": "active"})


# ---------------------------------------------------------------------------
# Client: delete
# ---------------------------------------------------------------------------


def test_delete_in_app_product_success():
    service = MagicMock()
    client = _client(service)

    result = client.delete_in_app_product("com.example.app", "premium_upgrade")

    assert isinstance(result, InAppProductActionResult)
    assert result.success is True
    assert result.sku == "premium_upgrade"
    assert "premium_upgrade" in result.message
    _iap(service).delete.assert_called_once_with(
        packageName="com.example.app", sku="premium_upgrade"
    )


def test_delete_in_app_product_http_error():
    service = MagicMock()
    _iap(service).delete.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to delete in-app product"):
        client.delete_in_app_product("com.example.app", "sku1")


# ---------------------------------------------------------------------------
# Client: batchGet
# ---------------------------------------------------------------------------


def test_batch_get_in_app_products_success():
    service = MagicMock()
    _iap(service).batchGet.return_value.execute.return_value = {
        "inappproduct": [
            _PRODUCT_RESPONSE,
            {"sku": "coins_100", "purchaseType": "managedProduct"},
        ]
    }
    client = _client(service)

    result = client.batch_get_in_app_products("com.example.app", ["premium_upgrade", "coins_100"])

    assert [p.sku for p in result] == ["premium_upgrade", "coins_100"]
    assert result[1].default_price is None
    _iap(service).batchGet.assert_called_once_with(
        packageName="com.example.app", sku=["premium_upgrade", "coins_100"]
    )


def test_batch_get_in_app_products_empty():
    service = MagicMock()
    _iap(service).batchGet.return_value.execute.return_value = {}
    client = _client(service)

    result = client.batch_get_in_app_products("com.example.app", ["sku1"])

    assert result == []


def test_batch_get_in_app_products_http_error():
    service = MagicMock()
    _iap(service).batchGet.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch get in-app products"):
        client.batch_get_in_app_products("com.example.app", ["sku1"])


# ---------------------------------------------------------------------------
# Client: batchDelete
# ---------------------------------------------------------------------------


def test_batch_delete_in_app_products_success():
    service = MagicMock()
    client = _client(service)

    result = client.batch_delete_in_app_products("com.example.app", ["sku1", "sku2"])

    assert isinstance(result, InAppProductActionResult)
    assert result.success is True
    assert result.sku is None
    assert "2" in result.message
    _iap(service).batchDelete.assert_called_once_with(
        packageName="com.example.app",
        body={
            "requests": [
                {"packageName": "com.example.app", "sku": "sku1"},
                {"packageName": "com.example.app", "sku": "sku2"},
            ]
        },
    )


def test_batch_delete_in_app_products_http_error():
    service = MagicMock()
    _iap(service).batchDelete.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch delete in-app products"):
        client.batch_delete_in_app_products("com.example.app", ["sku1"])


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_tool_create_in_app_product(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.create_in_app_product.return_value = InAppProduct(
        sku="premium_upgrade", package_name="com.example.app", product_type="managedProduct"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    body = {"sku": "premium_upgrade"}
    result = server.create_in_app_product("com.example.app", body)

    assert result["sku"] == "premium_upgrade"
    mc.create_in_app_product.assert_called_once_with(package_name="com.example.app", product=body)


def test_tool_update_in_app_product(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.update_in_app_product.return_value = InAppProduct(
        sku="premium_upgrade", package_name="com.example.app", product_type="managedProduct"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    body = {"sku": "premium_upgrade"}
    result = server.update_in_app_product(
        "com.example.app", "premium_upgrade", body, auto_convert_missing_prices=True
    )

    assert result["sku"] == "premium_upgrade"
    mc.update_in_app_product.assert_called_once_with(
        package_name="com.example.app",
        sku="premium_upgrade",
        product=body,
        auto_convert_missing_prices=True,
    )


def test_tool_patch_in_app_product(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.patch_in_app_product.return_value = InAppProduct(
        sku="premium_upgrade", package_name="com.example.app", product_type="managedProduct"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    body = {"status": "inactive"}
    result = server.patch_in_app_product("com.example.app", "premium_upgrade", body)

    assert result["sku"] == "premium_upgrade"
    mc.patch_in_app_product.assert_called_once_with(
        package_name="com.example.app", sku="premium_upgrade", product=body
    )


def test_tool_delete_in_app_product(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.delete_in_app_product.return_value = InAppProductActionResult(
        success=True, package_name="com.example.app", sku="premium_upgrade", message="ok"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.delete_in_app_product("com.example.app", "premium_upgrade")

    assert result["success"] is True
    mc.delete_in_app_product.assert_called_once_with(
        package_name="com.example.app", sku="premium_upgrade"
    )


def test_tool_batch_get_in_app_products(monkeypatch):
    mc = MagicMock()
    mc.batch_get_in_app_products.return_value = [
        InAppProduct(
            sku="premium_upgrade", package_name="com.example.app", product_type="managedProduct"
        )
    ]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.batch_get_in_app_products("com.example.app", ["premium_upgrade"])

    assert result[0]["sku"] == "premium_upgrade"
    mc.batch_get_in_app_products.assert_called_once_with(
        package_name="com.example.app", skus=["premium_upgrade"]
    )


def test_tool_batch_delete_in_app_products(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.batch_delete_in_app_products.return_value = InAppProductActionResult(
        success=True, package_name="com.example.app", message="ok"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.batch_delete_in_app_products("com.example.app", ["sku1", "sku2"])

    assert result["success"] is True
    mc.batch_delete_in_app_products.assert_called_once_with(
        package_name="com.example.app", skus=["sku1", "sku2"]
    )
