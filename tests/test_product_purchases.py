"""Tests for in-app product purchase tools (get / acknowledge / consume)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import ProductPurchase, ProductPurchaseActionResult

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_product_purchase_model_defaults():
    p = ProductPurchase(package_name="com.example.app", product_id="sku1", purchase_token="tok")
    assert p.package_name == "com.example.app"
    assert p.product_id == "sku1"
    assert p.purchase_token == "tok"
    assert p.order_id is None
    assert p.purchase_state is None
    assert p.consumption_state is None
    assert p.acknowledgement_state is None


def test_product_purchase_model_full():
    p = ProductPurchase(
        package_name="com.example.app",
        product_id="sku1",
        purchase_token="tok",
        order_id="GPA.1",
        purchase_state=0,
        consumption_state=0,
        acknowledgement_state=1,
        purchase_time=datetime(2026, 1, 1, tzinfo=UTC),
        purchase_type=0,
        quantity=1,
        region_code="US",
        developer_payload="payload",
    )
    assert p.acknowledgement_state == 1
    assert p.region_code == "US"


def test_product_purchase_action_result():
    r = ProductPurchaseActionResult(
        success=True,
        package_name="com.example.app",
        product_id="sku1",
        purchase_token="tok",
        action="consume",
        message="ok",
    )
    assert r.success is True
    assert r.action == "consume"
    assert r.error is None


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


def _client_with_products(products_mock: MagicMock) -> PlayStoreClient:
    client = PlayStoreClient(credentials_json={"type": "service_account"})
    service = MagicMock()
    service.purchases.return_value.products.return_value = products_mock
    client._service = service
    return client


def test_get_product_purchase_success():
    products = MagicMock()
    products.get.return_value.execute.return_value = {
        "orderId": "GPA.1",
        "purchaseState": 0,
        "consumptionState": 0,
        "acknowledgementState": 1,
        "purchaseTimeMillis": "1767225600000",
        "purchaseType": 0,
        "quantity": 1,
        "regionCode": "US",
        "developerPayload": "pl",
    }
    client = _client_with_products(products)

    result = client.get_product_purchase("com.example.app", "sku1", "tok")

    assert result.order_id == "GPA.1"
    assert result.acknowledgement_state == 1
    assert result.region_code == "US"
    assert result.purchase_time is not None
    products.get.assert_called_once_with(
        packageName="com.example.app", productId="sku1", token="tok"
    )


def test_get_product_purchase_no_time():
    products = MagicMock()
    products.get.return_value.execute.return_value = {"purchaseState": 2}
    client = _client_with_products(products)

    result = client.get_product_purchase("com.example.app", "sku1", "tok")

    assert result.purchase_time is None
    assert result.purchase_state == 2


def test_get_product_purchase_http_error():
    products = MagicMock()
    products.get.return_value.execute.side_effect = _make_http_error("not found")
    client = _client_with_products(products)

    with pytest.raises(PlayStoreClientError, match="Failed to get product purchase"):
        client.get_product_purchase("com.example.app", "sku1", "tok")


def test_acknowledge_product_purchase_success_with_payload():
    products = MagicMock()
    client = _client_with_products(products)

    result = client.acknowledge_product_purchase(
        "com.example.app", "sku1", "tok", developer_payload="pl"
    )

    assert result.success is True
    assert result.action == "acknowledge"
    products.acknowledge.assert_called_once_with(
        packageName="com.example.app",
        productId="sku1",
        token="tok",
        body={"developerPayload": "pl"},
    )


def test_acknowledge_product_purchase_success_no_payload():
    products = MagicMock()
    client = _client_with_products(products)

    result = client.acknowledge_product_purchase("com.example.app", "sku1", "tok")

    assert result.success is True
    products.acknowledge.assert_called_once_with(
        packageName="com.example.app", productId="sku1", token="tok", body={}
    )


def test_acknowledge_product_purchase_http_error():
    products = MagicMock()
    products.acknowledge.return_value.execute.side_effect = _make_http_error("bad")
    client = _client_with_products(products)

    with pytest.raises(PlayStoreClientError, match="Failed to acknowledge product purchase"):
        client.acknowledge_product_purchase("com.example.app", "sku1", "tok")


def test_consume_product_purchase_success():
    products = MagicMock()
    client = _client_with_products(products)

    result = client.consume_product_purchase("com.example.app", "sku1", "tok")

    assert result.success is True
    assert result.action == "consume"
    products.consume.assert_called_once_with(
        packageName="com.example.app", productId="sku1", token="tok"
    )


def test_consume_product_purchase_http_error():
    products = MagicMock()
    products.consume.return_value.execute.side_effect = _make_http_error("bad")
    client = _client_with_products(products)

    with pytest.raises(PlayStoreClientError, match="Failed to consume product purchase"):
        client.consume_product_purchase("com.example.app", "sku1", "tok")


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_tool_get_product_purchase(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mock_client = MagicMock()
    mock_client.get_product_purchase.return_value = ProductPurchase(
        package_name="com.example.app", product_id="sku1", purchase_token="tok", purchase_state=0
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mock_client)

    result = server.get_product_purchase("com.example.app", "sku1", "tok")

    assert result["purchase_state"] == 0
    mock_client.get_product_purchase.assert_called_once_with(
        package_name="com.example.app", product_id="sku1", token="tok"
    )


def test_tool_acknowledge_product_purchase(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mock_client = MagicMock()
    mock_client.acknowledge_product_purchase.return_value = ProductPurchaseActionResult(
        success=True,
        package_name="com.example.app",
        product_id="sku1",
        purchase_token="tok",
        action="acknowledge",
        message="ok",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mock_client)

    result = server.acknowledge_product_purchase(
        "com.example.app", "sku1", "tok", developer_payload="pl"
    )

    assert result["success"] is True
    mock_client.acknowledge_product_purchase.assert_called_once_with(
        package_name="com.example.app", product_id="sku1", token="tok", developer_payload="pl"
    )


def test_tool_consume_product_purchase(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mock_client = MagicMock()
    mock_client.consume_product_purchase.return_value = ProductPurchaseActionResult(
        success=True,
        package_name="com.example.app",
        product_id="sku1",
        purchase_token="tok",
        action="consume",
        message="ok",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mock_client)

    result = server.consume_product_purchase("com.example.app", "sku1", "tok")

    assert result["success"] is True
    mock_client.consume_product_purchase.assert_called_once_with(
        package_name="com.example.app", product_id="sku1", token="tok"
    )
