"""Tests for one-time product purchase options and offers.

Covers purchaseOptions batch-delete / batch-update-states and the
purchaseOptions.offers resource (list/batchGet/activate/deactivate/cancel/
batchUpdate/batchUpdateStates/batchDelete).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import (
    OneTimeProduct,
    OneTimeProductActionResult,
    OneTimeProductOffer,
)

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


def _options(service: MagicMock) -> MagicMock:
    return (
        service.monetization.return_value.onetimeproducts.return_value.purchaseOptions.return_value
    )


def _offers(service: MagicMock) -> MagicMock:
    return _options(service).offers.return_value


_OTP_RESPONSE = {
    "productId": "coins_pack",
    "packageName": "com.example.app",
    "purchaseOptions": [{"purchaseOptionId": "opt1"}],
}

_OFFER_RESPONSE = {
    "packageName": "com.example.app",
    "productId": "coins_pack",
    "purchaseOptionId": "opt1",
    "offerId": "intro",
    "state": "ACTIVE",
    "offerTags": [{"tag": "promo"}, {"tag": "welcome"}],
    "regionsVersion": {"version": "2022/02"},
}


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_one_time_product_offer_model_defaults():
    offer = OneTimeProductOffer(
        package_name="com.example.app",
        product_id="coins_pack",
        purchase_option_id="opt1",
        offer_id="intro",
    )
    assert offer.state is None
    assert offer.offer_tags == []
    assert offer.regions_version is None


def test_parse_one_time_product_offer_maps_fields():
    offer = PlayStoreClient._parse_one_time_product_offer(_OFFER_RESPONSE)

    assert isinstance(offer, OneTimeProductOffer)
    assert offer.package_name == "com.example.app"
    assert offer.product_id == "coins_pack"
    assert offer.purchase_option_id == "opt1"
    assert offer.offer_id == "intro"
    assert offer.state == "ACTIVE"
    assert offer.offer_tags == ["promo", "welcome"]
    assert offer.regions_version == "2022/02"


def test_parse_one_time_product_offer_missing_fields():
    offer = PlayStoreClient._parse_one_time_product_offer({})

    assert offer.package_name == ""
    assert offer.product_id == ""
    assert offer.purchase_option_id == ""
    assert offer.offer_id == ""
    assert offer.state is None
    assert offer.offer_tags == []
    assert offer.regions_version is None


# ---------------------------------------------------------------------------
# Client: purchaseOptions.batchDelete
# ---------------------------------------------------------------------------


def test_batch_delete_purchase_options_success():
    service = MagicMock()
    client = _client(service)

    requests = [{"purchaseOptionId": "opt1"}, {"purchaseOptionId": "opt2"}]
    result = client.batch_delete_purchase_options("com.example.app", "coins_pack", requests)

    assert isinstance(result, OneTimeProductActionResult)
    assert result.success is True
    assert result.product_id == "coins_pack"
    assert "2" in result.message
    _options(service).batchDelete.assert_called_once_with(
        packageName="com.example.app", productId="coins_pack", body={"requests": requests}
    )


def test_batch_delete_purchase_options_http_error():
    service = MagicMock()
    _options(service).batchDelete.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch delete purchase options"):
        client.batch_delete_purchase_options(
            "com.example.app", "coins_pack", [{"purchaseOptionId": "opt1"}]
        )


# ---------------------------------------------------------------------------
# Client: purchaseOptions.batchUpdateStates
# ---------------------------------------------------------------------------


def test_batch_update_purchase_option_states_success():
    service = MagicMock()
    _options(service).batchUpdateStates.return_value.execute.return_value = {
        "oneTimeProducts": [_OTP_RESPONSE, {"productId": "gems_pack"}]
    }
    client = _client(service)

    requests = [{"activatePurchaseOptionRequest": {"purchaseOptionId": "opt1"}}]
    result = client.batch_update_purchase_option_states("com.example.app", "coins_pack", requests)

    assert [p.product_id for p in result] == ["coins_pack", "gems_pack"]
    assert all(isinstance(p, OneTimeProduct) for p in result)
    _options(service).batchUpdateStates.assert_called_once_with(
        packageName="com.example.app", productId="coins_pack", body={"requests": requests}
    )


def test_batch_update_purchase_option_states_empty():
    service = MagicMock()
    _options(service).batchUpdateStates.return_value.execute.return_value = {}
    client = _client(service)

    result = client.batch_update_purchase_option_states(
        "com.example.app", "coins_pack", [{"activatePurchaseOptionRequest": {}}]
    )

    assert result == []


def test_batch_update_purchase_option_states_http_error():
    service = MagicMock()
    _options(service).batchUpdateStates.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch update purchase option states"):
        client.batch_update_purchase_option_states(
            "com.example.app", "coins_pack", [{"activatePurchaseOptionRequest": {}}]
        )


# ---------------------------------------------------------------------------
# Client: offers.list
# ---------------------------------------------------------------------------


def test_list_purchase_option_offers_success():
    service = MagicMock()
    _offers(service).list.return_value.execute.return_value = {
        "oneTimeProductOffers": [_OFFER_RESPONSE, {"offerId": "welcome"}]
    }
    client = _client(service)

    result = client.list_purchase_option_offers("com.example.app", "coins_pack", "opt1")

    assert [o.offer_id for o in result] == ["intro", "welcome"]
    assert result[0].offer_tags == ["promo", "welcome"]
    assert result[1].offer_tags == []
    _offers(service).list.assert_called_once_with(
        packageName="com.example.app", productId="coins_pack", purchaseOptionId="opt1"
    )


def test_list_purchase_option_offers_wildcard():
    service = MagicMock()
    _offers(service).list.return_value.execute.return_value = {
        "oneTimeProductOffers": [_OFFER_RESPONSE]
    }
    client = _client(service)

    result = client.list_purchase_option_offers("com.example.app", "-", "-")

    assert [o.offer_id for o in result] == ["intro"]
    _offers(service).list.assert_called_once_with(
        packageName="com.example.app", productId="-", purchaseOptionId="-"
    )


def test_list_purchase_option_offers_empty():
    service = MagicMock()
    _offers(service).list.return_value.execute.return_value = {}
    client = _client(service)

    result = client.list_purchase_option_offers("com.example.app", "coins_pack", "opt1")

    assert result == []


def test_list_purchase_option_offers_http_error():
    service = MagicMock()
    _offers(service).list.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to list purchase option offers"):
        client.list_purchase_option_offers("com.example.app", "coins_pack", "opt1")


# ---------------------------------------------------------------------------
# Client: offers.batchGet
# ---------------------------------------------------------------------------


def test_batch_get_purchase_option_offers_success():
    service = MagicMock()
    _offers(service).batchGet.return_value.execute.return_value = {
        "oneTimeProductOffers": [_OFFER_RESPONSE]
    }
    client = _client(service)

    requests = [{"offerId": "intro"}]
    result = client.batch_get_purchase_option_offers(
        "com.example.app", "coins_pack", "opt1", requests
    )

    assert [o.offer_id for o in result] == ["intro"]
    _offers(service).batchGet.assert_called_once_with(
        packageName="com.example.app",
        productId="coins_pack",
        purchaseOptionId="opt1",
        body={"requests": requests},
    )


def test_batch_get_purchase_option_offers_empty():
    service = MagicMock()
    _offers(service).batchGet.return_value.execute.return_value = {}
    client = _client(service)

    result = client.batch_get_purchase_option_offers(
        "com.example.app", "coins_pack", "opt1", [{"offerId": "intro"}]
    )

    assert result == []


def test_batch_get_purchase_option_offers_http_error():
    service = MagicMock()
    _offers(service).batchGet.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch get purchase option offers"):
        client.batch_get_purchase_option_offers(
            "com.example.app", "coins_pack", "opt1", [{"offerId": "intro"}]
        )


# ---------------------------------------------------------------------------
# Client: offers.activate
# ---------------------------------------------------------------------------


def test_activate_purchase_option_offer_success():
    service = MagicMock()
    _offers(service).activate.return_value.execute.return_value = _OFFER_RESPONSE
    client = _client(service)

    result = client.activate_purchase_option_offer("com.example.app", "coins_pack", "opt1", "intro")

    assert isinstance(result, OneTimeProductOffer)
    assert result.offer_id == "intro"
    assert result.state == "ACTIVE"
    _offers(service).activate.assert_called_once_with(
        packageName="com.example.app",
        productId="coins_pack",
        purchaseOptionId="opt1",
        offerId="intro",
        body={
            "packageName": "com.example.app",
            "productId": "coins_pack",
            "purchaseOptionId": "opt1",
            "offerId": "intro",
        },
    )


def test_activate_purchase_option_offer_http_error():
    service = MagicMock()
    _offers(service).activate.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to activate purchase option offer"):
        client.activate_purchase_option_offer("com.example.app", "coins_pack", "opt1", "intro")


# ---------------------------------------------------------------------------
# Client: offers.deactivate
# ---------------------------------------------------------------------------


def test_deactivate_purchase_option_offer_success():
    service = MagicMock()
    _offers(service).deactivate.return_value.execute.return_value = _OFFER_RESPONSE
    client = _client(service)

    result = client.deactivate_purchase_option_offer(
        "com.example.app", "coins_pack", "opt1", "intro"
    )

    assert isinstance(result, OneTimeProductOffer)
    assert result.offer_id == "intro"
    _offers(service).deactivate.assert_called_once_with(
        packageName="com.example.app",
        productId="coins_pack",
        purchaseOptionId="opt1",
        offerId="intro",
        body={
            "packageName": "com.example.app",
            "productId": "coins_pack",
            "purchaseOptionId": "opt1",
            "offerId": "intro",
        },
    )


def test_deactivate_purchase_option_offer_http_error():
    service = MagicMock()
    _offers(service).deactivate.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to deactivate purchase option offer"):
        client.deactivate_purchase_option_offer("com.example.app", "coins_pack", "opt1", "intro")


# ---------------------------------------------------------------------------
# Client: offers.cancel
# ---------------------------------------------------------------------------


def test_cancel_purchase_option_offer_success():
    service = MagicMock()
    _offers(service).cancel.return_value.execute.return_value = _OFFER_RESPONSE
    client = _client(service)

    result = client.cancel_purchase_option_offer("com.example.app", "coins_pack", "opt1", "intro")

    assert isinstance(result, OneTimeProductOffer)
    assert result.offer_id == "intro"
    _offers(service).cancel.assert_called_once_with(
        packageName="com.example.app",
        productId="coins_pack",
        purchaseOptionId="opt1",
        offerId="intro",
        body={
            "packageName": "com.example.app",
            "productId": "coins_pack",
            "purchaseOptionId": "opt1",
            "offerId": "intro",
        },
    )


def test_cancel_purchase_option_offer_http_error():
    service = MagicMock()
    _offers(service).cancel.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to cancel purchase option offer"):
        client.cancel_purchase_option_offer("com.example.app", "coins_pack", "opt1", "intro")


# ---------------------------------------------------------------------------
# Client: offers.batchUpdate
# ---------------------------------------------------------------------------


def test_batch_update_purchase_option_offers_success():
    service = MagicMock()
    _offers(service).batchUpdate.return_value.execute.return_value = {
        "oneTimeProductOffers": [_OFFER_RESPONSE]
    }
    client = _client(service)

    requests = [{"oneTimeProductOffer": {"offerId": "intro"}, "updateMask": "state"}]
    result = client.batch_update_purchase_option_offers(
        "com.example.app", "coins_pack", "opt1", requests
    )

    assert [o.offer_id for o in result] == ["intro"]
    _offers(service).batchUpdate.assert_called_once_with(
        packageName="com.example.app",
        productId="coins_pack",
        purchaseOptionId="opt1",
        body={"requests": requests},
    )


def test_batch_update_purchase_option_offers_empty():
    service = MagicMock()
    _offers(service).batchUpdate.return_value.execute.return_value = {}
    client = _client(service)

    result = client.batch_update_purchase_option_offers(
        "com.example.app", "coins_pack", "opt1", [{"oneTimeProductOffer": {}}]
    )

    assert result == []


def test_batch_update_purchase_option_offers_http_error():
    service = MagicMock()
    _offers(service).batchUpdate.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch update purchase option offers"):
        client.batch_update_purchase_option_offers(
            "com.example.app", "coins_pack", "opt1", [{"oneTimeProductOffer": {}}]
        )


# ---------------------------------------------------------------------------
# Client: offers.batchUpdateStates
# ---------------------------------------------------------------------------


def test_batch_update_purchase_option_offer_states_success():
    service = MagicMock()
    _offers(service).batchUpdateStates.return_value.execute.return_value = {
        "oneTimeProductOffers": [_OFFER_RESPONSE]
    }
    client = _client(service)

    requests = [{"activateOneTimeProductOfferRequest": {"offerId": "intro"}}]
    result = client.batch_update_purchase_option_offer_states(
        "com.example.app", "coins_pack", "opt1", requests
    )

    assert [o.offer_id for o in result] == ["intro"]
    _offers(service).batchUpdateStates.assert_called_once_with(
        packageName="com.example.app",
        productId="coins_pack",
        purchaseOptionId="opt1",
        body={"requests": requests},
    )


def test_batch_update_purchase_option_offer_states_empty():
    service = MagicMock()
    _offers(service).batchUpdateStates.return_value.execute.return_value = {}
    client = _client(service)

    result = client.batch_update_purchase_option_offer_states(
        "com.example.app", "coins_pack", "opt1", [{"activateOneTimeProductOfferRequest": {}}]
    )

    assert result == []


def test_batch_update_purchase_option_offer_states_http_error():
    service = MagicMock()
    _offers(service).batchUpdateStates.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(
        PlayStoreClientError, match="Failed to batch update purchase option offer states"
    ):
        client.batch_update_purchase_option_offer_states(
            "com.example.app", "coins_pack", "opt1", [{"activateOneTimeProductOfferRequest": {}}]
        )


# ---------------------------------------------------------------------------
# Client: offers.batchDelete
# ---------------------------------------------------------------------------


def test_batch_delete_purchase_option_offers_success():
    service = MagicMock()
    client = _client(service)

    requests = [{"offerId": "intro"}, {"offerId": "welcome"}]
    result = client.batch_delete_purchase_option_offers(
        "com.example.app", "coins_pack", "opt1", requests
    )

    assert isinstance(result, OneTimeProductActionResult)
    assert result.success is True
    assert result.product_id == "coins_pack"
    assert "2" in result.message
    _offers(service).batchDelete.assert_called_once_with(
        packageName="com.example.app",
        productId="coins_pack",
        purchaseOptionId="opt1",
        body={"requests": requests},
    )


def test_batch_delete_purchase_option_offers_http_error():
    service = MagicMock()
    _offers(service).batchDelete.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch delete purchase option offers"):
        client.batch_delete_purchase_option_offers(
            "com.example.app", "coins_pack", "opt1", [{"offerId": "intro"}]
        )


# ---------------------------------------------------------------------------
# MCP tools: purchase options
# ---------------------------------------------------------------------------


def test_tool_batch_delete_purchase_options(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.batch_delete_purchase_options.return_value = OneTimeProductActionResult(
        success=True, package_name="com.example.app", product_id="coins_pack", message="ok"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    requests = [{"purchaseOptionId": "opt1"}]
    result = server.batch_delete_purchase_options("com.example.app", "coins_pack", requests)

    assert result["success"] is True
    mc.batch_delete_purchase_options.assert_called_once_with(
        package_name="com.example.app", product_id="coins_pack", requests=requests
    )


def test_tool_batch_update_purchase_option_states(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.batch_update_purchase_option_states.return_value = [
        OneTimeProduct(product_id="coins_pack", package_name="com.example.app")
    ]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    requests = [{"activatePurchaseOptionRequest": {"purchaseOptionId": "opt1"}}]
    result = server.batch_update_purchase_option_states("com.example.app", "coins_pack", requests)

    assert result[0]["product_id"] == "coins_pack"
    mc.batch_update_purchase_option_states.assert_called_once_with(
        package_name="com.example.app", product_id="coins_pack", requests=requests
    )


# ---------------------------------------------------------------------------
# MCP tools: offers
# ---------------------------------------------------------------------------


def _offer_model() -> OneTimeProductOffer:
    return OneTimeProductOffer(
        package_name="com.example.app",
        product_id="coins_pack",
        purchase_option_id="opt1",
        offer_id="intro",
    )


def test_tool_list_purchase_option_offers(monkeypatch):
    mc = MagicMock()
    mc.list_purchase_option_offers.return_value = [_offer_model()]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.list_purchase_option_offers("com.example.app", "coins_pack", "opt1")

    assert result[0]["offer_id"] == "intro"
    mc.list_purchase_option_offers.assert_called_once_with(
        package_name="com.example.app", product_id="coins_pack", purchase_option_id="opt1"
    )


def test_tool_batch_get_purchase_option_offers(monkeypatch):
    mc = MagicMock()
    mc.batch_get_purchase_option_offers.return_value = [_offer_model()]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    requests = [{"offerId": "intro"}]
    result = server.batch_get_purchase_option_offers(
        "com.example.app", "coins_pack", "opt1", requests
    )

    assert result[0]["offer_id"] == "intro"
    mc.batch_get_purchase_option_offers.assert_called_once_with(
        package_name="com.example.app",
        product_id="coins_pack",
        purchase_option_id="opt1",
        requests=requests,
    )


def test_tool_activate_purchase_option_offer(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.activate_purchase_option_offer.return_value = _offer_model()
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.activate_purchase_option_offer("com.example.app", "coins_pack", "opt1", "intro")

    assert result["offer_id"] == "intro"
    mc.activate_purchase_option_offer.assert_called_once_with(
        package_name="com.example.app",
        product_id="coins_pack",
        purchase_option_id="opt1",
        offer_id="intro",
    )


def test_tool_deactivate_purchase_option_offer(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.deactivate_purchase_option_offer.return_value = _offer_model()
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.deactivate_purchase_option_offer(
        "com.example.app", "coins_pack", "opt1", "intro"
    )

    assert result["offer_id"] == "intro"
    mc.deactivate_purchase_option_offer.assert_called_once_with(
        package_name="com.example.app",
        product_id="coins_pack",
        purchase_option_id="opt1",
        offer_id="intro",
    )


def test_tool_cancel_purchase_option_offer(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.cancel_purchase_option_offer.return_value = _offer_model()
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.cancel_purchase_option_offer("com.example.app", "coins_pack", "opt1", "intro")

    assert result["offer_id"] == "intro"
    mc.cancel_purchase_option_offer.assert_called_once_with(
        package_name="com.example.app",
        product_id="coins_pack",
        purchase_option_id="opt1",
        offer_id="intro",
    )


def test_tool_batch_update_purchase_option_offers(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.batch_update_purchase_option_offers.return_value = [_offer_model()]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    requests = [{"oneTimeProductOffer": {"offerId": "intro"}, "updateMask": "state"}]
    result = server.batch_update_purchase_option_offers(
        "com.example.app", "coins_pack", "opt1", requests
    )

    assert result[0]["offer_id"] == "intro"
    mc.batch_update_purchase_option_offers.assert_called_once_with(
        package_name="com.example.app",
        product_id="coins_pack",
        purchase_option_id="opt1",
        requests=requests,
    )


def test_tool_batch_update_purchase_option_offer_states(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.batch_update_purchase_option_offer_states.return_value = [_offer_model()]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    requests = [{"activateOneTimeProductOfferRequest": {"offerId": "intro"}}]
    result = server.batch_update_purchase_option_offer_states(
        "com.example.app", "coins_pack", "opt1", requests
    )

    assert result[0]["offer_id"] == "intro"
    mc.batch_update_purchase_option_offer_states.assert_called_once_with(
        package_name="com.example.app",
        product_id="coins_pack",
        purchase_option_id="opt1",
        requests=requests,
    )


def test_tool_batch_delete_purchase_option_offers(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.batch_delete_purchase_option_offers.return_value = OneTimeProductActionResult(
        success=True, package_name="com.example.app", product_id="coins_pack", message="ok"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    requests = [{"offerId": "intro"}]
    result = server.batch_delete_purchase_option_offers(
        "com.example.app", "coins_pack", "opt1", requests
    )

    assert result["success"] is True
    mc.batch_delete_purchase_option_offers.assert_called_once_with(
        package_name="com.example.app",
        product_id="coins_pack",
        purchase_option_id="opt1",
        requests=requests,
    )
