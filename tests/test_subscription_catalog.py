"""Tests for subscription catalog management (get/create/patch/delete/batch)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import SubscriptionCatalogResult, SubscriptionProduct

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_subscription_catalog_result_defaults():
    r = SubscriptionCatalogResult(
        success=True,
        package_name="com.example.app",
        product_id="premium_monthly",
        message="ok",
    )
    assert r.success is True
    assert r.product_id == "premium_monthly"
    assert r.error is None


def test_subscription_catalog_result_batch_product_id_none():
    r = SubscriptionCatalogResult(success=True, package_name="com.example.app", message="ok")
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


def _subs(service: MagicMock) -> MagicMock:
    return service.monetization.return_value.subscriptions.return_value


_SUBSCRIPTION_RESPONSE = {
    "productId": "premium_monthly",
    "packageName": "com.example.app",
    "basePlans": [{"basePlanId": "monthly", "state": "ACTIVE"}],
    "listings": [{"languageCode": "en-US", "title": "Premium Monthly"}],
    "archived": False,
}


# ---------------------------------------------------------------------------
# Client: get
# ---------------------------------------------------------------------------


def test_get_subscription_success():
    service = MagicMock()
    _subs(service).get.return_value.execute.return_value = _SUBSCRIPTION_RESPONSE
    client = _client(service)

    result = client.get_subscription("com.example.app", "premium_monthly")

    assert isinstance(result, SubscriptionProduct)
    assert result.product_id == "premium_monthly"
    assert result.package_name == "com.example.app"
    assert result.status is None
    assert result.base_plans == [{"basePlanId": "monthly", "state": "ACTIVE"}]
    _subs(service).get.assert_called_once_with(
        packageName="com.example.app", productId="premium_monthly"
    )


def test_get_subscription_missing_fields():
    service = MagicMock()
    _subs(service).get.return_value.execute.return_value = {}
    client = _client(service)

    result = client.get_subscription("com.example.app", "premium_monthly")

    assert result.product_id == ""
    assert result.base_plans == []
    assert result.status is None


def test_get_subscription_http_error():
    service = MagicMock()
    _subs(service).get.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to get subscription"):
        client.get_subscription("com.example.app", "premium_monthly")


# ---------------------------------------------------------------------------
# Client: create
# ---------------------------------------------------------------------------


def test_create_subscription_success_defaults():
    service = MagicMock()
    _subs(service).create.return_value.execute.return_value = _SUBSCRIPTION_RESPONSE
    client = _client(service)

    body = {"productId": "premium_monthly", "basePlans": []}
    result = client.create_subscription("com.example.app", "premium_monthly", body)

    assert result.product_id == "premium_monthly"
    _subs(service).create.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        regionsVersion_version="2022/02",
        body=body,
    )


def test_create_subscription_custom_regions_version():
    service = MagicMock()
    _subs(service).create.return_value.execute.return_value = _SUBSCRIPTION_RESPONSE
    client = _client(service)

    body = {"productId": "premium_monthly"}
    client.create_subscription(
        "com.example.app", "premium_monthly", body, regions_version="2023/06"
    )

    _subs(service).create.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        regionsVersion_version="2023/06",
        body=body,
    )


def test_create_subscription_http_error():
    service = MagicMock()
    _subs(service).create.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to create subscription"):
        client.create_subscription("com.example.app", "premium_monthly", {"productId": "x"})


# ---------------------------------------------------------------------------
# Client: patch
# ---------------------------------------------------------------------------


def test_patch_subscription_success():
    service = MagicMock()
    _subs(service).patch.return_value.execute.return_value = _SUBSCRIPTION_RESPONSE
    client = _client(service)

    body = {"listings": [{"languageCode": "en-US", "title": "Premium"}]}
    result = client.patch_subscription(
        "com.example.app", "premium_monthly", body, update_mask="listings"
    )

    assert result.product_id == "premium_monthly"
    _subs(service).patch.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        updateMask="listings",
        regionsVersion_version="2022/02",
        body=body,
    )


def test_patch_subscription_custom_regions_version():
    service = MagicMock()
    _subs(service).patch.return_value.execute.return_value = _SUBSCRIPTION_RESPONSE
    client = _client(service)

    body = {"archived": True}
    client.patch_subscription(
        "com.example.app",
        "premium_monthly",
        body,
        update_mask="archived",
        regions_version="2023/06",
    )

    _subs(service).patch.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        updateMask="archived",
        regionsVersion_version="2023/06",
        body=body,
    )


def test_patch_subscription_http_error():
    service = MagicMock()
    _subs(service).patch.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to patch subscription"):
        client.patch_subscription(
            "com.example.app", "premium_monthly", {"archived": True}, update_mask="archived"
        )


# ---------------------------------------------------------------------------
# Client: delete
# ---------------------------------------------------------------------------


def test_delete_subscription_success():
    service = MagicMock()
    client = _client(service)

    result = client.delete_subscription("com.example.app", "premium_monthly")

    assert isinstance(result, SubscriptionCatalogResult)
    assert result.success is True
    assert result.product_id == "premium_monthly"
    assert "premium_monthly" in result.message
    _subs(service).delete.assert_called_once_with(
        packageName="com.example.app", productId="premium_monthly"
    )


def test_delete_subscription_http_error():
    service = MagicMock()
    _subs(service).delete.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to delete subscription"):
        client.delete_subscription("com.example.app", "premium_monthly")


# ---------------------------------------------------------------------------
# Client: batchGet
# ---------------------------------------------------------------------------


def test_batch_get_subscriptions_success():
    service = MagicMock()
    _subs(service).batchGet.return_value.execute.return_value = {
        "subscriptions": [
            _SUBSCRIPTION_RESPONSE,
            {"productId": "premium_yearly", "basePlans": []},
        ]
    }
    client = _client(service)

    result = client.batch_get_subscriptions(
        "com.example.app", ["premium_monthly", "premium_yearly"]
    )

    assert [s.product_id for s in result] == ["premium_monthly", "premium_yearly"]
    assert result[1].base_plans == []
    _subs(service).batchGet.assert_called_once_with(
        packageName="com.example.app", productIds=["premium_monthly", "premium_yearly"]
    )


def test_batch_get_subscriptions_empty():
    service = MagicMock()
    _subs(service).batchGet.return_value.execute.return_value = {}
    client = _client(service)

    result = client.batch_get_subscriptions("com.example.app", ["premium_monthly"])

    assert result == []


def test_batch_get_subscriptions_http_error():
    service = MagicMock()
    _subs(service).batchGet.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch get subscriptions"):
        client.batch_get_subscriptions("com.example.app", ["premium_monthly"])


# ---------------------------------------------------------------------------
# Client: batchUpdate
# ---------------------------------------------------------------------------


def test_batch_update_subscriptions_success():
    service = MagicMock()
    _subs(service).batchUpdate.return_value.execute.return_value = {
        "subscriptions": [_SUBSCRIPTION_RESPONSE]
    }
    client = _client(service)

    requests = [
        {
            "subscription": {"productId": "premium_monthly"},
            "updateMask": "listings",
        }
    ]
    result = client.batch_update_subscriptions("com.example.app", requests)

    assert [s.product_id for s in result] == ["premium_monthly"]
    _subs(service).batchUpdate.assert_called_once_with(
        packageName="com.example.app", body={"requests": requests}
    )


def test_batch_update_subscriptions_empty():
    service = MagicMock()
    _subs(service).batchUpdate.return_value.execute.return_value = {}
    client = _client(service)

    result = client.batch_update_subscriptions(
        "com.example.app", [{"subscription": {"productId": "x"}}]
    )

    assert result == []


def test_batch_update_subscriptions_http_error():
    service = MagicMock()
    _subs(service).batchUpdate.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch update subscriptions"):
        client.batch_update_subscriptions("com.example.app", [{"subscription": {}}])


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_tool_get_subscription(monkeypatch):
    mc = MagicMock()
    mc.get_subscription.return_value = SubscriptionProduct(
        product_id="premium_monthly", package_name="com.example.app"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.get_subscription("com.example.app", "premium_monthly")

    assert result["product_id"] == "premium_monthly"
    mc.get_subscription.assert_called_once_with("com.example.app", "premium_monthly")


def test_tool_create_subscription(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.create_subscription.return_value = SubscriptionProduct(
        product_id="premium_monthly", package_name="com.example.app"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    body = {"productId": "premium_monthly"}
    result = server.create_subscription("com.example.app", "premium_monthly", body)

    assert result["product_id"] == "premium_monthly"
    mc.create_subscription.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        subscription=body,
        regions_version="2022/02",
    )


def test_tool_patch_subscription(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.patch_subscription.return_value = SubscriptionProduct(
        product_id="premium_monthly", package_name="com.example.app"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    body = {"archived": True}
    result = server.patch_subscription(
        "com.example.app", "premium_monthly", body, update_mask="archived"
    )

    assert result["product_id"] == "premium_monthly"
    mc.patch_subscription.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        subscription=body,
        update_mask="archived",
        regions_version="2022/02",
    )


def test_tool_delete_subscription(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.delete_subscription.return_value = SubscriptionCatalogResult(
        success=True,
        package_name="com.example.app",
        product_id="premium_monthly",
        message="ok",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.delete_subscription("com.example.app", "premium_monthly")

    assert result["success"] is True
    mc.delete_subscription.assert_called_once_with(
        package_name="com.example.app", product_id="premium_monthly"
    )


def test_tool_batch_get_subscriptions(monkeypatch):
    mc = MagicMock()
    mc.batch_get_subscriptions.return_value = [
        SubscriptionProduct(product_id="premium_monthly", package_name="com.example.app")
    ]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.batch_get_subscriptions("com.example.app", ["premium_monthly"])

    assert result[0]["product_id"] == "premium_monthly"
    mc.batch_get_subscriptions.assert_called_once_with(
        package_name="com.example.app", product_ids=["premium_monthly"]
    )


def test_tool_batch_update_subscriptions(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.batch_update_subscriptions.return_value = [
        SubscriptionProduct(product_id="premium_monthly", package_name="com.example.app")
    ]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    requests = [{"subscription": {"productId": "premium_monthly"}, "updateMask": "listings"}]
    result = server.batch_update_subscriptions("com.example.app", requests)

    assert result[0]["product_id"] == "premium_monthly"
    mc.batch_update_subscriptions.assert_called_once_with(
        package_name="com.example.app", requests=requests
    )
