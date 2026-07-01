"""Tests for purchase management tools (refund / cancel / defer / revoke / v2 read)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import OrderRefundResult, ProductPurchaseV2, SubscriptionActionResult

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_order_refund_result():
    r = OrderRefundResult(
        success=True, package_name="com.example.app", order_id="GPA.1", revoked=True, message="ok"
    )
    assert r.success is True
    assert r.revoked is True
    assert r.error is None


def test_subscription_action_result_defaults():
    r = SubscriptionActionResult(
        success=True,
        package_name="com.example.app",
        purchase_token="tok",
        action="cancel",
        message="ok",
    )
    assert r.action == "cancel"
    assert r.details is None
    assert r.error is None


def test_product_purchase_v2_defaults():
    p = ProductPurchaseV2(package_name="com.example.app", purchase_token="tok")
    assert p.order_id is None
    assert p.product_line_items == []
    assert p.test_purchase is False


# ---------------------------------------------------------------------------
# Client methods
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


def _subs_v2(service: MagicMock) -> MagicMock:
    return service.purchases.return_value.subscriptionsv2.return_value


def _products_v2(service: MagicMock) -> MagicMock:
    return service.purchases.return_value.productsv2.return_value


def test_refund_order_success_with_revoke():
    service = MagicMock()
    client = _client(service)

    result = client.refund_order("com.example.app", "GPA.1", revoke=True)

    assert result.success is True
    assert result.revoked is True
    service.orders.return_value.refund.assert_called_once_with(
        packageName="com.example.app", orderId="GPA.1", revoke=True
    )


def test_refund_order_default_no_revoke():
    service = MagicMock()
    client = _client(service)

    result = client.refund_order("com.example.app", "GPA.1")

    assert result.revoked is False
    service.orders.return_value.refund.assert_called_once_with(
        packageName="com.example.app", orderId="GPA.1", revoke=False
    )


def test_refund_order_http_error():
    service = MagicMock()
    service.orders.return_value.refund.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to refund order"):
        client.refund_order("com.example.app", "GPA.1")


def test_cancel_subscription_success():
    service = MagicMock()
    client = _client(service)

    result = client.cancel_subscription_purchase("com.example.app", "tok")

    assert result.action == "cancel"
    _subs_v2(service).cancel.assert_called_once_with(
        packageName="com.example.app",
        token="tok",
        body={"cancellationContext": {"cancellationType": "USER_REQUESTED_STOP_RENEWALS"}},
    )


def test_cancel_subscription_http_error():
    service = MagicMock()
    _subs_v2(service).cancel.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to cancel subscription"):
        client.cancel_subscription_purchase("com.example.app", "tok")


def test_defer_subscription_success():
    service = MagicMock()
    _subs_v2(service).defer.return_value.execute.return_value = {
        "itemExpiryTimeDetails": [{"productId": "sub1", "expiryTime": "2026-02-01T00:00:00Z"}]
    }
    client = _client(service)

    result = client.defer_subscription_purchase("com.example.app", "tok", "604800s", "etag123")

    assert result.action == "defer"
    assert result.details == {
        "itemExpiryTimeDetails": [{"productId": "sub1", "expiryTime": "2026-02-01T00:00:00Z"}]
    }
    _subs_v2(service).defer.assert_called_once_with(
        packageName="com.example.app",
        token="tok",
        body={"deferralContext": {"deferDuration": "604800s", "etag": "etag123"}},
    )


def test_defer_subscription_http_error():
    service = MagicMock()
    _subs_v2(service).defer.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to defer subscription"):
        client.defer_subscription_purchase("com.example.app", "tok", "604800s", "etag")


def test_revoke_subscription_full():
    service = MagicMock()
    client = _client(service)

    result = client.revoke_subscription_purchase("com.example.app", "tok", refund_type="full")

    assert result.action == "revoke"
    _subs_v2(service).revoke.assert_called_once_with(
        packageName="com.example.app", token="tok", body={"revocationContext": {"fullRefund": {}}}
    )


def test_revoke_subscription_prorated():
    service = MagicMock()
    client = _client(service)

    client.revoke_subscription_purchase("com.example.app", "tok", refund_type="prorated")

    _subs_v2(service).revoke.assert_called_once_with(
        packageName="com.example.app",
        token="tok",
        body={"revocationContext": {"proratedRefund": {}}},
    )


def test_revoke_subscription_http_error():
    service = MagicMock()
    _subs_v2(service).revoke.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to revoke subscription"):
        client.revoke_subscription_purchase("com.example.app", "tok")


def test_get_product_purchase_v2_success():
    service = MagicMock()
    _products_v2(service).getproductpurchasev2.return_value.execute.return_value = {
        "orderId": "GPA.2",
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        "purchaseCompletionTime": "2026-01-01T00:00:00Z",
        "regionCode": "US",
        "productLineItem": [{"productId": "coins"}],
        "testPurchaseContext": {},
    }
    client = _client(service)

    result = client.get_product_purchase_v2("com.example.app", "tok")

    assert result.order_id == "GPA.2"
    assert result.acknowledgement_state == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
    assert result.product_line_items == [{"productId": "coins"}]
    assert result.test_purchase is True
    _products_v2(service).getproductpurchasev2.assert_called_once_with(
        packageName="com.example.app", token="tok"
    )


def test_get_product_purchase_v2_minimal():
    service = MagicMock()
    _products_v2(service).getproductpurchasev2.return_value.execute.return_value = {}
    client = _client(service)

    result = client.get_product_purchase_v2("com.example.app", "tok")

    assert result.order_id is None
    assert result.product_line_items == []
    assert result.test_purchase is False


def test_get_product_purchase_v2_http_error():
    service = MagicMock()
    _products_v2(service).getproductpurchasev2.return_value.execute.side_effect = _make_http_error(
        "nope"
    )
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to get product purchase"):
        client.get_product_purchase_v2("com.example.app", "tok")


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_tool_refund_order(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.refund_order.return_value = OrderRefundResult(
        success=True, package_name="com.example.app", order_id="GPA.1", revoked=True, message="ok"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.refund_order("com.example.app", "GPA.1", revoke=True)

    assert result["success"] is True
    mc.refund_order.assert_called_once_with(
        package_name="com.example.app", order_id="GPA.1", revoke=True
    )


def test_tool_cancel_subscription(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.cancel_subscription_purchase.return_value = SubscriptionActionResult(
        success=True,
        package_name="com.example.app",
        purchase_token="tok",
        action="cancel",
        message="ok",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.cancel_subscription_purchase("com.example.app", "tok")

    assert result["action"] == "cancel"
    mc.cancel_subscription_purchase.assert_called_once_with(
        package_name="com.example.app",
        token="tok",
        cancellation_type="USER_REQUESTED_STOP_RENEWALS",
    )


def test_tool_defer_subscription(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.defer_subscription_purchase.return_value = SubscriptionActionResult(
        success=True,
        package_name="com.example.app",
        purchase_token="tok",
        action="defer",
        message="ok",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.defer_subscription_purchase("com.example.app", "tok", "604800s", "etag")

    assert result["success"] is True
    mc.defer_subscription_purchase.assert_called_once_with(
        package_name="com.example.app", token="tok", defer_duration="604800s", etag="etag"
    )


def test_tool_revoke_subscription(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.revoke_subscription_purchase.return_value = SubscriptionActionResult(
        success=True,
        package_name="com.example.app",
        purchase_token="tok",
        action="revoke",
        message="ok",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.revoke_subscription_purchase("com.example.app", "tok", refund_type="prorated")

    assert result["success"] is True
    mc.revoke_subscription_purchase.assert_called_once_with(
        package_name="com.example.app", token="tok", refund_type="prorated"
    )


def test_tool_revoke_subscription_invalid_type(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.revoke_subscription_purchase("com.example.app", "tok", refund_type="bogus")

    assert "error" in result
    assert "full" in result["error"] and "prorated" in result["error"]
    mc.revoke_subscription_purchase.assert_not_called()


def test_tool_get_product_purchase_v2(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.get_product_purchase_v2.return_value = ProductPurchaseV2(
        package_name="com.example.app", purchase_token="tok", order_id="GPA.2"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.get_product_purchase_v2("com.example.app", "tok")

    assert result["order_id"] == "GPA.2"
    mc.get_product_purchase_v2.assert_called_once_with(package_name="com.example.app", token="tok")
