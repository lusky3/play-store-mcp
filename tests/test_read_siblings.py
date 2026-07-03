"""Tests for read-sibling tools (get_review, batch_get_orders)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import Order, Review


def _make_http_error(reason: str = "boom") -> HttpError:
    resp = MagicMock()
    resp.status = 404
    resp.reason = reason
    err = HttpError(resp, b"{}")
    err.reason = reason
    return err


def _client(service: MagicMock) -> PlayStoreClient:
    client = PlayStoreClient(credentials_json={"type": "service_account"})
    client._service = service
    return client


_REVIEW_RESPONSE = {
    "reviewId": "rev-1",
    "authorName": "Jane",
    "comments": [
        {
            "userComment": {
                "starRating": 4,
                "text": "Nice app",
                "reviewerLanguage": "en",
                "device": "Pixel",
                "androidOsVersion": "13",
                "appVersionCode": 100,
                "appVersionName": "1.0.0",
                "lastModified": {"seconds": "1767225600", "nanos": 0},
            }
        },
        {"developerComment": {"text": "Thanks!", "lastModified": {"seconds": "1767312000"}}},
    ],
}


def test_get_review_success():
    service = MagicMock()
    service.reviews.return_value.get.return_value.execute.return_value = _REVIEW_RESPONSE
    client = _client(service)

    review = client.get_review("com.example.app", "rev-1")

    assert review.review_id == "rev-1"
    assert review.star_rating == 4
    assert review.developer_reply == "Thanks!"
    service.reviews.return_value.get.assert_called_once_with(
        packageName="com.example.app", reviewId="rev-1"
    )


def test_get_review_with_translation():
    service = MagicMock()
    service.reviews.return_value.get.return_value.execute.return_value = _REVIEW_RESPONSE
    client = _client(service)

    client.get_review("com.example.app", "rev-1", translation_language="fr")

    service.reviews.return_value.get.assert_called_once_with(
        packageName="com.example.app", reviewId="rev-1", translationLanguage="fr"
    )


def test_get_review_no_user_comment_raises():
    service = MagicMock()
    service.reviews.return_value.get.return_value.execute.return_value = {
        "reviewId": "rev-2",
        "comments": [{"developerComment": {"text": "hi"}}],
    }
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="no user comment"):
        client.get_review("com.example.app", "rev-2")


def test_get_review_http_error():
    service = MagicMock()
    service.reviews.return_value.get.return_value.execute.side_effect = _make_http_error("nope")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to fetch review"):
        client.get_review("com.example.app", "rev-1")


def test_batch_get_orders_success():
    service = MagicMock()
    service.orders.return_value.batchget.return_value.execute.return_value = {
        "orders": [
            {
                "orderId": "GPA.1",
                "state": "PROCESSED",
                "lineItems": [{"productId": "coins"}],
                "purchaseToken": "t1",
            },
            {"orderId": "GPA.2", "state": "CANCELED", "purchaseToken": "t2"},
        ]
    }
    client = _client(service)

    orders = client.batch_get_orders("com.example.app", ["GPA.1", "GPA.2"])

    assert [o.order_id for o in orders] == ["GPA.1", "GPA.2"]
    assert orders[0].product_ids == ["coins"]
    assert orders[0].state == "PROCESSED"
    assert orders[1].product_ids == []
    service.orders.return_value.batchget.assert_called_once_with(
        packageName="com.example.app", orderIds=["GPA.1", "GPA.2"]
    )


def test_batch_get_orders_empty():
    service = MagicMock()
    service.orders.return_value.batchget.return_value.execute.return_value = {}
    client = _client(service)

    assert client.batch_get_orders("com.example.app", ["GPA.1"]) == []


def test_batch_get_orders_http_error():
    service = MagicMock()
    service.orders.return_value.batchget.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to batch get orders"):
        client.batch_get_orders("com.example.app", ["GPA.1"])


def test_tool_get_review(monkeypatch):
    mc = MagicMock()
    mc.get_review.return_value = Review(
        review_id="rev-1",
        author_name="Jane",
        star_rating=5,
        comment="great",
        language="en",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.get_review("com.example.app", "rev-1", translation_language="fr")

    assert result["review_id"] == "rev-1"
    mc.get_review.assert_called_once_with(
        package_name="com.example.app", review_id="rev-1", translation_language="fr"
    )


def test_tool_batch_get_orders(monkeypatch):
    mc = MagicMock()
    mc.batch_get_orders.return_value = [
        Order(order_id="GPA.1", package_name="com.example.app"),
        Order(order_id="GPA.2", package_name="com.example.app"),
    ]
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.batch_get_orders("com.example.app", ["GPA.1", "GPA.2"])

    assert [o["order_id"] for o in result] == ["GPA.1", "GPA.2"]
    mc.batch_get_orders.assert_called_once_with(
        package_name="com.example.app", order_ids=["GPA.1", "GPA.2"]
    )
