"""Tests for subscription offer management (basePlans.offers resource)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import SubscriptionCatalogResult, SubscriptionOffer

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


def _offers(service: MagicMock) -> MagicMock:
    return service.monetization.return_value.subscriptions.return_value.basePlans.return_value.offers.return_value


_OFFER_RESPONSE = {
    "packageName": "com.example.app",
    "productId": "premium_monthly",
    "basePlanId": "monthly",
    "offerId": "intro",
    "state": "ACTIVE",
    "offerTags": [{"tag": "promo"}, {"tag": "welcome"}],
    "phases": [{"recurrenceCount": 1}],
    "regionsVersion": {"version": "2022/02"},
}


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_subscription_offer_model_defaults():
    offer = SubscriptionOffer(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
        offer_id="intro",
    )
    assert offer.state is None
    assert offer.offer_tags == []
    assert offer.phases == []
    assert offer.regions_version is None


def test_parse_subscription_offer_maps_fields():
    offer = PlayStoreClient._parse_subscription_offer(_OFFER_RESPONSE)

    assert isinstance(offer, SubscriptionOffer)
    assert offer.package_name == "com.example.app"
    assert offer.product_id == "premium_monthly"
    assert offer.base_plan_id == "monthly"
    assert offer.offer_id == "intro"
    assert offer.state == "ACTIVE"
    assert offer.offer_tags == ["promo", "welcome"]
    assert offer.phases == [{"recurrenceCount": 1}]
    assert offer.regions_version == "2022/02"


def test_parse_subscription_offer_missing_fields():
    offer = PlayStoreClient._parse_subscription_offer({})

    assert offer.package_name == ""
    assert offer.product_id == ""
    assert offer.base_plan_id == ""
    assert offer.offer_id == ""
    assert offer.state is None
    assert offer.offer_tags == []
    assert offer.phases == []
    assert offer.regions_version is None


# ---------------------------------------------------------------------------
# Client: get
# ---------------------------------------------------------------------------


def test_get_subscription_offer_success():
    service = MagicMock()
    _offers(service).get.return_value.execute.return_value = _OFFER_RESPONSE
    client = _client(service)

    result = client.get_subscription_offer("com.example.app", "premium_monthly", "monthly", "intro")

    assert isinstance(result, SubscriptionOffer)
    assert result.offer_id == "intro"
    assert result.offer_tags == ["promo", "welcome"]
    _offers(service).get.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
        offerId="intro",
    )


def test_get_subscription_offer_http_error():
    service = MagicMock()
    _offers(service).get.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to get subscription offer"):
        client.get_subscription_offer("com.example.app", "premium_monthly", "monthly", "intro")


# ---------------------------------------------------------------------------
# Client: list
# ---------------------------------------------------------------------------


def test_list_subscription_offers_success():
    service = MagicMock()
    _offers(service).list.return_value.execute.return_value = {
        "subscriptionOffers": [_OFFER_RESPONSE]
    }
    client = _client(service)

    result = client.list_subscription_offers("com.example.app", "premium_monthly", "monthly")

    assert [o.offer_id for o in result] == ["intro"]
    _offers(service).list.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
    )


def test_list_subscription_offers_empty():
    service = MagicMock()
    _offers(service).list.return_value.execute.return_value = {}
    client = _client(service)

    result = client.list_subscription_offers("com.example.app", "premium_monthly", "monthly")

    assert result == []


def test_list_subscription_offers_http_error():
    service = MagicMock()
    _offers(service).list.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to list subscription offers"):
        client.list_subscription_offers("com.example.app", "premium_monthly", "monthly")


# ---------------------------------------------------------------------------
# Client: create
# ---------------------------------------------------------------------------


def test_create_subscription_offer_success_defaults():
    service = MagicMock()
    _offers(service).create.return_value.execute.return_value = _OFFER_RESPONSE
    client = _client(service)

    body = {"offerId": "intro", "phases": []}
    result = client.create_subscription_offer(
        "com.example.app", "premium_monthly", "monthly", "intro", body
    )

    assert result.offer_id == "intro"
    _offers(service).create.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
        offerId="intro",
        regionsVersion_version="2022/02",
        body=body,
    )


def test_create_subscription_offer_custom_regions_version():
    service = MagicMock()
    _offers(service).create.return_value.execute.return_value = _OFFER_RESPONSE
    client = _client(service)

    body = {"offerId": "intro"}
    client.create_subscription_offer(
        "com.example.app",
        "premium_monthly",
        "monthly",
        "intro",
        body,
        regions_version="2023/06",
    )

    _offers(service).create.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
        offerId="intro",
        regionsVersion_version="2023/06",
        body=body,
    )


def test_create_subscription_offer_http_error():
    service = MagicMock()
    _offers(service).create.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to create subscription offer"):
        client.create_subscription_offer(
            "com.example.app", "premium_monthly", "monthly", "intro", {"offerId": "intro"}
        )


# ---------------------------------------------------------------------------
# Client: patch
# ---------------------------------------------------------------------------


def test_patch_subscription_offer_success():
    service = MagicMock()
    _offers(service).patch.return_value.execute.return_value = _OFFER_RESPONSE
    client = _client(service)

    body = {"phases": []}
    result = client.patch_subscription_offer(
        "com.example.app", "premium_monthly", "monthly", "intro", body, update_mask="phases"
    )

    assert result.offer_id == "intro"
    _offers(service).patch.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
        offerId="intro",
        updateMask="phases",
        regionsVersion_version="2022/02",
        body=body,
    )


def test_patch_subscription_offer_custom_regions_version():
    service = MagicMock()
    _offers(service).patch.return_value.execute.return_value = _OFFER_RESPONSE
    client = _client(service)

    body = {"phases": []}
    client.patch_subscription_offer(
        "com.example.app",
        "premium_monthly",
        "monthly",
        "intro",
        body,
        update_mask="phases",
        regions_version="2023/06",
    )

    _offers(service).patch.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
        offerId="intro",
        updateMask="phases",
        regionsVersion_version="2023/06",
        body=body,
    )


def test_patch_subscription_offer_http_error():
    service = MagicMock()
    _offers(service).patch.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to patch subscription offer"):
        client.patch_subscription_offer(
            "com.example.app", "premium_monthly", "monthly", "intro", {}, update_mask="phases"
        )


# ---------------------------------------------------------------------------
# Client: activate
# ---------------------------------------------------------------------------


def test_activate_subscription_offer_success():
    service = MagicMock()
    _offers(service).activate.return_value.execute.return_value = _OFFER_RESPONSE
    client = _client(service)

    result = client.activate_subscription_offer(
        "com.example.app", "premium_monthly", "monthly", "intro"
    )

    assert result.offer_id == "intro"
    _offers(service).activate.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
        offerId="intro",
        body={
            "packageName": "com.example.app",
            "productId": "premium_monthly",
            "basePlanId": "monthly",
            "offerId": "intro",
        },
    )


def test_activate_subscription_offer_http_error():
    service = MagicMock()
    _offers(service).activate.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to activate subscription offer"):
        client.activate_subscription_offer("com.example.app", "premium_monthly", "monthly", "intro")


# ---------------------------------------------------------------------------
# Client: deactivate
# ---------------------------------------------------------------------------


def test_deactivate_subscription_offer_success():
    service = MagicMock()
    _offers(service).deactivate.return_value.execute.return_value = _OFFER_RESPONSE
    client = _client(service)

    result = client.deactivate_subscription_offer(
        "com.example.app", "premium_monthly", "monthly", "intro"
    )

    assert result.offer_id == "intro"
    _offers(service).deactivate.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
        offerId="intro",
        body={
            "packageName": "com.example.app",
            "productId": "premium_monthly",
            "basePlanId": "monthly",
            "offerId": "intro",
        },
    )


def test_deactivate_subscription_offer_http_error():
    service = MagicMock()
    _offers(service).deactivate.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to deactivate subscription offer"):
        client.deactivate_subscription_offer(
            "com.example.app", "premium_monthly", "monthly", "intro"
        )


# ---------------------------------------------------------------------------
# Client: delete
# ---------------------------------------------------------------------------


def test_delete_subscription_offer_success():
    service = MagicMock()
    client = _client(service)

    result = client.delete_subscription_offer(
        "com.example.app", "premium_monthly", "monthly", "intro"
    )

    assert isinstance(result, SubscriptionCatalogResult)
    assert result.success is True
    # product_id is the parent subscription product, not the deleted offer id.
    assert result.product_id == "premium_monthly"
    assert "intro" in result.message
    _offers(service).delete.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
        offerId="intro",
    )


def test_delete_subscription_offer_http_error():
    service = MagicMock()
    _offers(service).delete.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to delete subscription offer"):
        client.delete_subscription_offer("com.example.app", "premium_monthly", "monthly", "intro")


# ---------------------------------------------------------------------------
# Client: batchGet
# ---------------------------------------------------------------------------


def test_batch_get_subscription_offers_success():
    service = MagicMock()
    _offers(service).batchGet.return_value.execute.return_value = {
        "subscriptionOffers": [_OFFER_RESPONSE]
    }
    client = _client(service)

    requests = [{"offerId": "intro"}]
    result = client.batch_get_subscription_offers(
        "com.example.app", "premium_monthly", "monthly", requests
    )

    assert [o.offer_id for o in result] == ["intro"]
    _offers(service).batchGet.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
        body={"requests": requests},
    )


def test_batch_get_subscription_offers_empty():
    service = MagicMock()
    _offers(service).batchGet.return_value.execute.return_value = {}
    client = _client(service)

    result = client.batch_get_subscription_offers(
        "com.example.app", "premium_monthly", "monthly", [{"offerId": "intro"}]
    )

    assert result == []


def test_batch_get_subscription_offers_http_error():
    service = MagicMock()
    _offers(service).batchGet.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch get subscription offers"):
        client.batch_get_subscription_offers("com.example.app", "premium_monthly", "monthly", [])


# ---------------------------------------------------------------------------
# Client: batchUpdate
# ---------------------------------------------------------------------------


def test_batch_update_subscription_offers_success():
    service = MagicMock()
    _offers(service).batchUpdate.return_value.execute.return_value = {
        "subscriptionOffers": [_OFFER_RESPONSE]
    }
    client = _client(service)

    requests = [{"subscriptionOffer": {"offerId": "intro"}, "updateMask": "phases"}]
    result = client.batch_update_subscription_offers(
        "com.example.app", "premium_monthly", "monthly", requests
    )

    assert [o.offer_id for o in result] == ["intro"]
    _offers(service).batchUpdate.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
        body={"requests": requests},
    )


def test_batch_update_subscription_offers_empty():
    service = MagicMock()
    _offers(service).batchUpdate.return_value.execute.return_value = {}
    client = _client(service)

    result = client.batch_update_subscription_offers(
        "com.example.app", "premium_monthly", "monthly", [{"subscriptionOffer": {}}]
    )

    assert result == []


def test_batch_update_subscription_offers_http_error():
    service = MagicMock()
    _offers(service).batchUpdate.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch update subscription offers"):
        client.batch_update_subscription_offers("com.example.app", "premium_monthly", "monthly", [])


# ---------------------------------------------------------------------------
# Client: batchUpdateStates
# ---------------------------------------------------------------------------


def test_batch_update_subscription_offer_states_success():
    service = MagicMock()
    _offers(service).batchUpdateStates.return_value.execute.return_value = {
        "subscriptionOffers": [_OFFER_RESPONSE]
    }
    client = _client(service)

    requests = [{"activateSubscriptionOfferRequest": {"offerId": "intro"}}]
    result = client.batch_update_subscription_offer_states(
        "com.example.app", "premium_monthly", "monthly", requests
    )

    assert [o.offer_id for o in result] == ["intro"]
    _offers(service).batchUpdateStates.assert_called_once_with(
        packageName="com.example.app",
        productId="premium_monthly",
        basePlanId="monthly",
        body={"requests": requests},
    )


def test_batch_update_subscription_offer_states_empty():
    service = MagicMock()
    _offers(service).batchUpdateStates.return_value.execute.return_value = {}
    client = _client(service)

    result = client.batch_update_subscription_offer_states(
        "com.example.app",
        "premium_monthly",
        "monthly",
        [{"activateSubscriptionOfferRequest": {}}],
    )

    assert result == []


def test_batch_update_subscription_offer_states_http_error():
    service = MagicMock()
    _offers(service).batchUpdateStates.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(
        PlayStoreClientError, match="Failed to batch update subscription offer states"
    ):
        client.batch_update_subscription_offer_states(
            "com.example.app", "premium_monthly", "monthly", []
        )


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def _offer_model(offer_id: str = "intro") -> SubscriptionOffer:
    return SubscriptionOffer(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
        offer_id=offer_id,
    )


def test_tool_get_subscription_offer(monkeypatch):
    mc = MagicMock()
    mc.get_subscription_offer.return_value = _offer_model()
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.get_subscription_offer("com.example.app", "premium_monthly", "monthly", "intro")

    assert result["offer_id"] == "intro"
    mc.get_subscription_offer.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
        offer_id="intro",
    )


def test_tool_list_subscription_offers(monkeypatch):
    mc = MagicMock()
    mc.list_subscription_offers.return_value = [_offer_model()]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.list_subscription_offers("com.example.app", "premium_monthly", "monthly")

    assert [o["offer_id"] for o in result] == ["intro"]
    mc.list_subscription_offers.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
    )


def test_tool_create_subscription_offer(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.create_subscription_offer.return_value = _offer_model()
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    body = {"offerId": "intro"}
    result = server.create_subscription_offer(
        "com.example.app", "premium_monthly", "monthly", "intro", body
    )

    assert result["offer_id"] == "intro"
    mc.create_subscription_offer.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
        offer_id="intro",
        offer=body,
        regions_version="2022/02",
    )


def test_tool_patch_subscription_offer(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.patch_subscription_offer.return_value = _offer_model()
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    body = {"phases": []}
    result = server.patch_subscription_offer(
        "com.example.app", "premium_monthly", "monthly", "intro", body, "phases"
    )

    assert result["offer_id"] == "intro"
    mc.patch_subscription_offer.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
        offer_id="intro",
        offer=body,
        update_mask="phases",
        regions_version="2022/02",
    )


def test_tool_activate_subscription_offer(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.activate_subscription_offer.return_value = _offer_model()
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.activate_subscription_offer(
        "com.example.app", "premium_monthly", "monthly", "intro"
    )

    assert result["offer_id"] == "intro"
    mc.activate_subscription_offer.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
        offer_id="intro",
    )


def test_tool_deactivate_subscription_offer(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.deactivate_subscription_offer.return_value = _offer_model()
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.deactivate_subscription_offer(
        "com.example.app", "premium_monthly", "monthly", "intro"
    )

    assert result["offer_id"] == "intro"
    mc.deactivate_subscription_offer.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
        offer_id="intro",
    )


def test_tool_delete_subscription_offer(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.delete_subscription_offer.return_value = SubscriptionCatalogResult(
        success=True,
        package_name="com.example.app",
        product_id="intro",
        message="ok",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.delete_subscription_offer(
        "com.example.app", "premium_monthly", "monthly", "intro"
    )

    assert result["success"] is True
    mc.delete_subscription_offer.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
        offer_id="intro",
    )


def test_tool_batch_get_subscription_offers(monkeypatch):
    mc = MagicMock()
    mc.batch_get_subscription_offers.return_value = [_offer_model()]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    requests = [{"offerId": "intro"}]
    result = server.batch_get_subscription_offers(
        "com.example.app", "premium_monthly", "monthly", requests
    )

    assert [o["offer_id"] for o in result] == ["intro"]
    mc.batch_get_subscription_offers.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
        requests=requests,
    )


def test_tool_batch_update_subscription_offers(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.batch_update_subscription_offers.return_value = [_offer_model()]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    requests = [{"subscriptionOffer": {"offerId": "intro"}}]
    result = server.batch_update_subscription_offers(
        "com.example.app", "premium_monthly", "monthly", requests
    )

    assert [o["offer_id"] for o in result] == ["intro"]
    mc.batch_update_subscription_offers.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
        requests=requests,
    )


def test_tool_batch_update_subscription_offer_states(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.batch_update_subscription_offer_states.return_value = [_offer_model()]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    requests = [{"activateSubscriptionOfferRequest": {"offerId": "intro"}}]
    result = server.batch_update_subscription_offer_states(
        "com.example.app", "premium_monthly", "monthly", requests
    )

    assert [o["offer_id"] for o in result] == ["intro"]
    mc.batch_update_subscription_offer_states.assert_called_once_with(
        package_name="com.example.app",
        product_id="premium_monthly",
        base_plan_id="monthly",
        requests=requests,
    )
