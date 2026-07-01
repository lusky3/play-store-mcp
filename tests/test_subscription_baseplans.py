"""Tests for subscription base plan management (activate/deactivate/delete/migrate)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import SubscriptionCatalogResult, SubscriptionProduct

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


def _base_plans(service: MagicMock) -> MagicMock:
    return service.monetization.return_value.subscriptions.return_value.basePlans.return_value


_SUBSCRIPTION_RESPONSE = {
    "productId": "premium_monthly",
    "packageName": "com.example.app",
    "basePlans": [{"basePlanId": "monthly", "state": "ACTIVE"}],
}


# ---------------------------------------------------------------------------
# Client: activate
# ---------------------------------------------------------------------------


def test_activate_base_plan_success():
    service = MagicMock()
    _base_plans(service).activate.return_value.execute.return_value = _SUBSCRIPTION_RESPONSE
    client = _client(service)

    result = client.activate_base_plan("com.example.app", "premium_monthly", "monthly")

    assert isinstance(result, SubscriptionProduct)
    assert result.product_id == "premium_monthly"
    assert result.base_plans == [{"basePlanId": "monthly", "state": "ACTIVE"}]
    _base_plans(service).activate.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
        body={
            "packageName": "com.example.app",
            "productId": "premium_monthly",
            "basePlanId": "monthly",
        },
    )


def test_activate_base_plan_http_error():
    service = MagicMock()
    _base_plans(service).activate.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to activate base plan"):
        client.activate_base_plan("com.example.app", "premium_monthly", "monthly")


# ---------------------------------------------------------------------------
# Client: deactivate
# ---------------------------------------------------------------------------


def test_deactivate_base_plan_success():
    service = MagicMock()
    _base_plans(service).deactivate.return_value.execute.return_value = _SUBSCRIPTION_RESPONSE
    client = _client(service)

    result = client.deactivate_base_plan("com.example.app", "premium_monthly", "monthly")

    assert isinstance(result, SubscriptionProduct)
    assert result.product_id == "premium_monthly"
    _base_plans(service).deactivate.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
        body={
            "packageName": "com.example.app",
            "productId": "premium_monthly",
            "basePlanId": "monthly",
        },
    )


def test_deactivate_base_plan_http_error():
    service = MagicMock()
    _base_plans(service).deactivate.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to deactivate base plan"):
        client.deactivate_base_plan("com.example.app", "premium_monthly", "monthly")


# ---------------------------------------------------------------------------
# Client: delete
# ---------------------------------------------------------------------------


def test_delete_base_plan_success():
    service = MagicMock()
    client = _client(service)

    result = client.delete_base_plan("com.example.app", "premium_monthly", "monthly")

    assert isinstance(result, SubscriptionCatalogResult)
    assert result.success is True
    assert result.product_id == "premium_monthly"
    assert "monthly" in result.message
    _base_plans(service).delete.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
    )


def test_delete_base_plan_http_error():
    service = MagicMock()
    _base_plans(service).delete.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to delete base plan"):
        client.delete_base_plan("com.example.app", "premium_monthly", "monthly")


# ---------------------------------------------------------------------------
# Client: migratePrices
# ---------------------------------------------------------------------------


def test_migrate_base_plan_prices_success():
    service = MagicMock()
    _base_plans(service).migratePrices.return_value.execute.return_value = {"foo": "bar"}
    client = _client(service)

    request = {"regionalPriceMigrations": [], "regionsVersion": {"version": "2022/02"}}
    result = client.migrate_base_plan_prices(
        "com.example.app", "premium_monthly", "monthly", request
    )

    assert result == {"foo": "bar"}
    _base_plans(service).migratePrices.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
        body=request,
    )


def test_migrate_base_plan_prices_http_error():
    service = MagicMock()
    _base_plans(service).migratePrices.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to migrate base plan prices"):
        client.migrate_base_plan_prices("com.example.app", "premium_monthly", "monthly", {})


# ---------------------------------------------------------------------------
# Client: batchMigratePrices
# ---------------------------------------------------------------------------


def test_batch_migrate_base_plan_prices_success():
    service = MagicMock()
    _base_plans(service).batchMigratePrices.return_value.execute.return_value = {"responses": []}
    client = _client(service)

    requests = [{"basePlanId": "monthly", "regionsVersion": {"version": "2022/02"}}]
    result = client.batch_migrate_base_plan_prices("com.example.app", "premium_monthly", requests)

    assert result == {"responses": []}
    _base_plans(service).batchMigratePrices.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        body={"requests": requests},
    )


def test_batch_migrate_base_plan_prices_http_error():
    service = MagicMock()
    _base_plans(service).batchMigratePrices.return_value.execute.side_effect = _make_http_error(
        "bad"
    )
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch migrate base plan prices"):
        client.batch_migrate_base_plan_prices("com.example.app", "premium_monthly", [])


# ---------------------------------------------------------------------------
# Client: batchUpdateStates
# ---------------------------------------------------------------------------


def test_batch_update_base_plan_states_success():
    service = MagicMock()
    _base_plans(service).batchUpdateStates.return_value.execute.return_value = {
        "subscriptions": [_SUBSCRIPTION_RESPONSE]
    }
    client = _client(service)

    requests = [{"activateBasePlanRequest": {"basePlanId": "monthly"}}]
    result = client.batch_update_base_plan_states("com.example.app", "premium_monthly", requests)

    assert isinstance(result, SubscriptionProduct)
    assert result.product_id == "premium_monthly"
    _base_plans(service).batchUpdateStates.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        body={"requests": requests},
    )


def test_batch_update_base_plan_states_empty():
    service = MagicMock()
    _base_plans(service).batchUpdateStates.return_value.execute.return_value = {}
    client = _client(service)

    result = client.batch_update_base_plan_states(
        "com.example.app", "premium_monthly", [{"activateBasePlanRequest": {}}]
    )

    assert isinstance(result, SubscriptionProduct)
    assert result.product_id == ""
    assert result.base_plans == []


def test_batch_update_base_plan_states_http_error():
    service = MagicMock()
    _base_plans(service).batchUpdateStates.return_value.execute.side_effect = _make_http_error(
        "bad"
    )
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch update base plan states"):
        client.batch_update_base_plan_states("com.example.app", "premium_monthly", [])


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_tool_activate_base_plan(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.activate_base_plan.return_value = SubscriptionProduct(
        product_id="premium_monthly", package_name="com.example.app"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.activate_base_plan("com.example.app", "premium_monthly", "monthly")

    assert result["product_id"] == "premium_monthly"
    mc.activate_base_plan.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
    )


def test_tool_deactivate_base_plan(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.deactivate_base_plan.return_value = SubscriptionProduct(
        product_id="premium_monthly", package_name="com.example.app"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.deactivate_base_plan("com.example.app", "premium_monthly", "monthly")

    assert result["product_id"] == "premium_monthly"
    mc.deactivate_base_plan.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
    )


def test_tool_delete_base_plan(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.delete_base_plan.return_value = SubscriptionCatalogResult(
        success=True,
        package_name="com.example.app",
        product_id="premium_monthly",
        message="ok",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.delete_base_plan("com.example.app", "premium_monthly", "monthly")

    assert result["success"] is True
    mc.delete_base_plan.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
    )


def test_tool_migrate_base_plan_prices(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.migrate_base_plan_prices.return_value = {"foo": "bar"}
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    request = {"regionsVersion": {"version": "2022/02"}}
    result = server.migrate_base_plan_prices(
        "com.example.app", "premium_monthly", "monthly", request
    )

    assert result == {"foo": "bar"}
    mc.migrate_base_plan_prices.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
        request=request,
    )


def test_tool_batch_migrate_base_plan_prices(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.batch_migrate_base_plan_prices.return_value = {"responses": []}
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    requests = [{"basePlanId": "monthly"}]
    result = server.batch_migrate_base_plan_prices("com.example.app", "premium_monthly", requests)

    assert result == {"responses": []}
    mc.batch_migrate_base_plan_prices.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        requests=requests,
    )


def test_tool_batch_update_base_plan_states(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.batch_update_base_plan_states.return_value = SubscriptionProduct(
        product_id="premium_monthly", package_name="com.example.app"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    requests = [{"activateBasePlanRequest": {"basePlanId": "monthly"}}]
    result = server.batch_update_base_plan_states("com.example.app", "premium_monthly", requests)

    assert result["product_id"] == "premium_monthly"
    mc.batch_update_base_plan_states.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        requests=requests,
    )
