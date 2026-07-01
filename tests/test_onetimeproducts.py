"""Tests for one-time product catalog management (get/list/patch/delete/batch)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import OneTimeProduct, OneTimeProductActionResult

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_one_time_product_defaults():
    p = OneTimeProduct(product_id="coins_pack", package_name="com.example.app")
    assert p.product_id == "coins_pack"
    assert p.package_name == "com.example.app"
    assert p.listings == []
    assert p.purchase_options == []
    assert p.offer_tags == []
    assert p.restricted_payment_countries is None


def test_one_time_product_populated():
    p = OneTimeProduct(
        product_id="coins_pack",
        package_name="com.example.app",
        listings=[{"languageCode": "en-US", "title": "Coins"}],
        purchase_options=[{"purchaseOptionId": "opt1"}],
        offer_tags=[{"tag": "promo"}],
        restricted_payment_countries={"regionCodes": ["US"]},
    )
    assert p.listings == [{"languageCode": "en-US", "title": "Coins"}]
    assert p.purchase_options == [{"purchaseOptionId": "opt1"}]
    assert p.offer_tags == [{"tag": "promo"}]
    assert p.restricted_payment_countries == {"regionCodes": ["US"]}


def test_one_time_product_action_result_defaults():
    r = OneTimeProductActionResult(
        success=True,
        package_name="com.example.app",
        product_id="coins_pack",
        message="ok",
    )
    assert r.success is True
    assert r.product_id == "coins_pack"
    assert r.error is None


def test_one_time_product_action_result_batch_product_id_none():
    r = OneTimeProductActionResult(success=True, package_name="com.example.app", message="ok")
    assert r.product_id is None
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


def _otp(service: MagicMock) -> MagicMock:
    return service.monetization.return_value.onetimeproducts.return_value


_OTP_RESPONSE = {
    "productId": "coins_pack",
    "packageName": "com.example.app",
    "listings": [{"languageCode": "en-US", "title": "Coins Pack"}],
    "purchaseOptions": [{"purchaseOptionId": "opt1"}],
    "offerTags": [{"tag": "promo"}],
    "restrictedPaymentCountries": {"regionCodes": ["US"]},
}


# ---------------------------------------------------------------------------
# Client: get
# ---------------------------------------------------------------------------


def test_get_one_time_product_success():
    service = MagicMock()
    _otp(service).get.return_value.execute.return_value = _OTP_RESPONSE
    client = _client(service)

    result = client.get_one_time_product("com.example.app", "coins_pack")

    assert isinstance(result, OneTimeProduct)
    assert result.product_id == "coins_pack"
    assert result.package_name == "com.example.app"
    assert result.listings == [{"languageCode": "en-US", "title": "Coins Pack"}]
    assert result.purchase_options == [{"purchaseOptionId": "opt1"}]
    assert result.offer_tags == [{"tag": "promo"}]
    assert result.restricted_payment_countries == {"regionCodes": ["US"]}
    _otp(service).get.assert_called_once_with(packageName="com.example.app", productId="coins_pack")


def test_get_one_time_product_missing_fields():
    service = MagicMock()
    _otp(service).get.return_value.execute.return_value = {}
    client = _client(service)

    result = client.get_one_time_product("com.example.app", "coins_pack")

    assert result.product_id == ""
    assert result.listings == []
    assert result.purchase_options == []
    assert result.offer_tags == []
    assert result.restricted_payment_countries is None


def test_get_one_time_product_http_error():
    service = MagicMock()
    _otp(service).get.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to get one-time product"):
        client.get_one_time_product("com.example.app", "coins_pack")


# ---------------------------------------------------------------------------
# Client: list
# ---------------------------------------------------------------------------


def test_list_one_time_products_success():
    service = MagicMock()
    _otp(service).list.return_value.execute.return_value = {
        "oneTimeProducts": [
            _OTP_RESPONSE,
            {"productId": "gems_pack"},
        ]
    }
    client = _client(service)

    result = client.list_one_time_products("com.example.app")

    assert [p.product_id for p in result] == ["coins_pack", "gems_pack"]
    assert result[1].listings == []
    _otp(service).list.assert_called_once_with(packageName="com.example.app")


def test_list_one_time_products_empty():
    service = MagicMock()
    _otp(service).list.return_value.execute.return_value = {}
    client = _client(service)

    result = client.list_one_time_products("com.example.app")

    assert result == []


def test_list_one_time_products_http_error():
    service = MagicMock()
    _otp(service).list.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to list one-time products"):
        client.list_one_time_products("com.example.app")


# ---------------------------------------------------------------------------
# Client: batchGet
# ---------------------------------------------------------------------------


def test_batch_get_one_time_products_success():
    service = MagicMock()
    _otp(service).batchGet.return_value.execute.return_value = {
        "oneTimeProducts": [
            _OTP_RESPONSE,
            {"productId": "gems_pack"},
        ]
    }
    client = _client(service)

    result = client.batch_get_one_time_products("com.example.app", ["coins_pack", "gems_pack"])

    assert [p.product_id for p in result] == ["coins_pack", "gems_pack"]
    assert result[1].purchase_options == []
    _otp(service).batchGet.assert_called_once_with(
        packageName="com.example.app", productIds=["coins_pack", "gems_pack"]
    )


def test_batch_get_one_time_products_empty():
    service = MagicMock()
    _otp(service).batchGet.return_value.execute.return_value = {}
    client = _client(service)

    result = client.batch_get_one_time_products("com.example.app", ["coins_pack"])

    assert result == []


def test_batch_get_one_time_products_http_error():
    service = MagicMock()
    _otp(service).batchGet.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch get one-time products"):
        client.batch_get_one_time_products("com.example.app", ["coins_pack"])


# ---------------------------------------------------------------------------
# Client: patch
# ---------------------------------------------------------------------------


def test_patch_one_time_product_success():
    service = MagicMock()
    _otp(service).patch.return_value.execute.return_value = _OTP_RESPONSE
    client = _client(service)

    body = {"listings": [{"languageCode": "en-US", "title": "Coins"}]}
    result = client.patch_one_time_product(
        "com.example.app", "coins_pack", body, update_mask="listings"
    )

    assert result.product_id == "coins_pack"
    _otp(service).patch.assert_called_once_with(
        packageName="com.example.app",
        productId="coins_pack",
        updateMask="listings",
        regionsVersion_version="2022/02",
        body=body,
    )


def test_patch_one_time_product_custom_regions_version():
    service = MagicMock()
    _otp(service).patch.return_value.execute.return_value = _OTP_RESPONSE
    client = _client(service)

    body = {"offerTags": [{"tag": "promo"}]}
    client.patch_one_time_product(
        "com.example.app",
        "coins_pack",
        body,
        update_mask="offerTags",
        regions_version="2023/06",
    )

    _otp(service).patch.assert_called_once_with(
        packageName="com.example.app",
        productId="coins_pack",
        updateMask="offerTags",
        regionsVersion_version="2023/06",
        body=body,
    )


def test_patch_one_time_product_http_error():
    service = MagicMock()
    _otp(service).patch.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to patch one-time product"):
        client.patch_one_time_product(
            "com.example.app", "coins_pack", {"offerTags": []}, update_mask="offerTags"
        )


# ---------------------------------------------------------------------------
# Client: delete
# ---------------------------------------------------------------------------


def test_delete_one_time_product_success():
    service = MagicMock()
    client = _client(service)

    result = client.delete_one_time_product("com.example.app", "coins_pack")

    assert isinstance(result, OneTimeProductActionResult)
    assert result.success is True
    assert result.product_id == "coins_pack"
    assert "coins_pack" in result.message
    _otp(service).delete.assert_called_once_with(
        packageName="com.example.app", productId="coins_pack"
    )


def test_delete_one_time_product_http_error():
    service = MagicMock()
    _otp(service).delete.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to delete one-time product"):
        client.delete_one_time_product("com.example.app", "coins_pack")


# ---------------------------------------------------------------------------
# Client: batchUpdate
# ---------------------------------------------------------------------------


def test_batch_update_one_time_products_success():
    service = MagicMock()
    _otp(service).batchUpdate.return_value.execute.return_value = {
        "oneTimeProducts": [_OTP_RESPONSE]
    }
    client = _client(service)

    requests = [
        {
            "oneTimeProduct": {"productId": "coins_pack"},
            "updateMask": "listings",
        }
    ]
    result = client.batch_update_one_time_products("com.example.app", requests)

    assert [p.product_id for p in result] == ["coins_pack"]
    _otp(service).batchUpdate.assert_called_once_with(
        packageName="com.example.app", body={"requests": requests}
    )


def test_batch_update_one_time_products_empty():
    service = MagicMock()
    _otp(service).batchUpdate.return_value.execute.return_value = {}
    client = _client(service)

    result = client.batch_update_one_time_products(
        "com.example.app", [{"oneTimeProduct": {"productId": "x"}}]
    )

    assert result == []


def test_batch_update_one_time_products_http_error():
    service = MagicMock()
    _otp(service).batchUpdate.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch update one-time products"):
        client.batch_update_one_time_products("com.example.app", [{"oneTimeProduct": {}}])


# ---------------------------------------------------------------------------
# Client: batchDelete
# ---------------------------------------------------------------------------


def test_batch_delete_one_time_products_success():
    service = MagicMock()
    client = _client(service)

    requests = [{"productId": "coins_pack"}, {"productId": "gems_pack"}]
    result = client.batch_delete_one_time_products("com.example.app", requests)

    assert isinstance(result, OneTimeProductActionResult)
    assert result.success is True
    assert result.product_id is None
    assert "2" in result.message
    _otp(service).batchDelete.assert_called_once_with(
        packageName="com.example.app", body={"requests": requests}
    )


def test_batch_delete_one_time_products_http_error():
    service = MagicMock()
    _otp(service).batchDelete.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch delete one-time products"):
        client.batch_delete_one_time_products("com.example.app", [{"productId": "coins_pack"}])


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_tool_get_one_time_product(monkeypatch):
    mc = MagicMock()
    mc.get_one_time_product.return_value = OneTimeProduct(
        product_id="coins_pack", package_name="com.example.app"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.get_one_time_product("com.example.app", "coins_pack")

    assert result["product_id"] == "coins_pack"
    mc.get_one_time_product.assert_called_once_with("com.example.app", "coins_pack")


def test_tool_list_one_time_products(monkeypatch):
    mc = MagicMock()
    mc.list_one_time_products.return_value = [
        OneTimeProduct(product_id="coins_pack", package_name="com.example.app")
    ]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.list_one_time_products("com.example.app")

    assert result[0]["product_id"] == "coins_pack"
    mc.list_one_time_products.assert_called_once_with("com.example.app")


def test_tool_batch_get_one_time_products(monkeypatch):
    mc = MagicMock()
    mc.batch_get_one_time_products.return_value = [
        OneTimeProduct(product_id="coins_pack", package_name="com.example.app")
    ]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.batch_get_one_time_products("com.example.app", ["coins_pack"])

    assert result[0]["product_id"] == "coins_pack"
    mc.batch_get_one_time_products.assert_called_once_with(
        package_name="com.example.app", product_ids=["coins_pack"]
    )


def test_tool_patch_one_time_product(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.patch_one_time_product.return_value = OneTimeProduct(
        product_id="coins_pack", package_name="com.example.app"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    body = {"listings": [{"languageCode": "en-US", "title": "Coins"}]}
    result = server.patch_one_time_product(
        "com.example.app", "coins_pack", body, update_mask="listings"
    )

    assert result["product_id"] == "coins_pack"
    mc.patch_one_time_product.assert_called_once_with(
        package_name="com.example.app",
        product_id="coins_pack",
        product=body,
        update_mask="listings",
        regions_version="2022/02",
    )


def test_tool_delete_one_time_product(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.delete_one_time_product.return_value = OneTimeProductActionResult(
        success=True,
        package_name="com.example.app",
        product_id="coins_pack",
        message="ok",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.delete_one_time_product("com.example.app", "coins_pack")

    assert result["success"] is True
    mc.delete_one_time_product.assert_called_once_with(
        package_name="com.example.app", product_id="coins_pack"
    )


def test_tool_batch_update_one_time_products(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.batch_update_one_time_products.return_value = [
        OneTimeProduct(product_id="coins_pack", package_name="com.example.app")
    ]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    requests = [{"oneTimeProduct": {"productId": "coins_pack"}, "updateMask": "listings"}]
    result = server.batch_update_one_time_products("com.example.app", requests)

    assert result[0]["product_id"] == "coins_pack"
    mc.batch_update_one_time_products.assert_called_once_with(
        package_name="com.example.app", requests=requests
    )


def test_tool_batch_delete_one_time_products(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.batch_delete_one_time_products.return_value = OneTimeProductActionResult(
        success=True,
        package_name="com.example.app",
        message="ok",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    requests = [{"productId": "coins_pack"}]
    result = server.batch_delete_one_time_products("com.example.app", requests)

    assert result["success"] is True
    mc.batch_delete_one_time_products.assert_called_once_with(
        package_name="com.example.app", requests=requests
    )
