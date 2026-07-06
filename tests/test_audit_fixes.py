"""Tests for the batch of audit fixes in client.py and server.py.

Each test class maps to a numbered audit finding (see the module docstrings
below). These bring branch coverage of the newly hardened code paths back to
~100% while asserting real behavior, not just execution.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.client as client_module
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError, _parse_rfc3339

# =========================================================================
# Helpers
# =========================================================================


def _make_http_error(status: int, reason: str = "error") -> HttpError:
    """Create a mock HttpError with the given HTTP status."""
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp=resp, content=reason.encode())


# =========================================================================
# Finding 1: retry through a real operation (_execute is @retry_with_backoff)
# =========================================================================


class TestExecuteRetryThroughOperation:
    """_execute retries via backoff: 429 always; 500/503 only for idempotent methods."""

    def test_operation_retries_transient_then_succeeds(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Two 503s then a success dict: get_order returns parsed result, 3 calls."""
        get_req = _mock_service.orders.return_value.get.return_value
        get_req.method = "GET"  # idempotent → 5xx is retried
        execute = get_req.execute
        execute.side_effect = [
            _make_http_error(503),
            _make_http_error(503),
            {
                "orderId": "order-1",
                "state": "PROCESSED",
                "lineItems": [{"productId": "prod-1"}],
                "purchaseToken": "tok-1",
            },
        ]

        order = client.get_order("com.example.app", "order-1")

        assert order.order_id == "order-1"
        assert order.state == "PROCESSED"
        assert order.product_ids == ["prod-1"]
        assert order.purchase_token == "tok-1"
        assert execute.call_count == 3

    def test_operation_raises_after_persistent_transient_errors(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Three consecutive 503s exhaust retries and surface as PlayStoreClientError."""
        get_req = _mock_service.orders.return_value.get.return_value
        get_req.method = "GET"  # idempotent → 5xx is retried
        execute = get_req.execute
        execute.side_effect = [
            _make_http_error(503),
            _make_http_error(503),
            _make_http_error(503),
        ]

        with pytest.raises(PlayStoreClientError, match="Failed to get order"):
            client.get_order("com.example.app", "order-1")

        assert execute.call_count == 3

    def test_non_idempotent_operation_not_retried_on_5xx(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """A POST mutation must NOT retry a 5xx (retrying could duplicate the write)."""
        ack = _mock_service.purchases.return_value.products.return_value.acknowledge.return_value
        ack.method = "POST"
        ack.execute.side_effect = [
            _make_http_error(503),
            {},
        ]

        with pytest.raises(PlayStoreClientError, match="Failed to acknowledge"):
            client.acknowledge_product_purchase("com.example.app", "sku-1", "tok-1")

        assert ack.execute.call_count == 1

    def test_non_idempotent_operation_retries_on_429(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """A POST mutation still retries 429 (throttled, so never applied)."""
        ack = _mock_service.purchases.return_value.products.return_value.acknowledge.return_value
        ack.method = "POST"
        ack.execute.side_effect = [
            _make_http_error(429),
            {},
        ]

        result = client.acknowledge_product_purchase("com.example.app", "sku-1", "tok-1")

        assert result.success is True
        assert ack.execute.call_count == 2


class TestExecuteThreadSafety:
    """The client serializes its (non-thread-safe httplib2) transport via a per-client lock."""

    def test_execute_holds_lock_around_request(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """_http_lock is held while request.execute() runs, and released afterwards."""
        get_req = _mock_service.orders.return_value.get.return_value
        get_req.method = "GET"
        observed: dict[str, bool] = {}

        def fake_execute() -> dict[str, Any]:
            observed["locked_during_call"] = client._http_lock.locked()
            return {"orderId": "o1", "state": "PROCESSED", "lineItems": []}

        get_req.execute.side_effect = fake_execute

        client.get_order("com.example.app", "o1")

        assert observed["locked_during_call"] is True
        assert client._http_lock.locked() is False


# =========================================================================
# Finding 2: _parse_rfc3339
# =========================================================================


class TestParseRfc3339:
    """Module-level RFC3339 parser used by subscriptions v2."""

    def test_valid_rfc3339_returns_aware_datetime(self) -> None:
        result = _parse_rfc3339("2024-10-02T15:01:23Z")
        assert result == datetime(2024, 10, 2, 15, 1, 23, tzinfo=UTC)
        assert result is not None
        assert result.tzinfo is not None

    def test_none_returns_none(self) -> None:
        assert _parse_rfc3339(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_rfc3339("") is None

    def test_invalid_string_returns_none(self) -> None:
        assert _parse_rfc3339("not-a-date") is None


# =========================================================================
# Finding 3: get_subscription_purchase (v2 lineItems + RFC3339 times)
# =========================================================================


class TestGetSubscriptionPurchase:
    """Subscriptions v2 parsing of start/expiry times and auto-renew state."""

    def _get_mock(self, _mock_service: MagicMock) -> MagicMock:
        return _mock_service.purchases.return_value.subscriptionsv2.return_value.get

    def test_matching_line_item_populates_times_and_auto_renew(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """The line item whose productId matches supplies expiry + auto-renew."""
        self._get_mock(_mock_service).return_value.execute.return_value = {
            "startTime": "2024-10-02T15:01:23Z",
            "latestOrderId": "order-9",
            "lineItems": [
                {
                    "productId": "sub_premium",
                    "expiryTime": "2025-01-01T00:00:00Z",
                    "autoRenewingPlan": {"autoRenewEnabled": True},
                }
            ],
        }

        result = client.get_subscription_purchase("com.example.app", "sub_premium", "token-1")

        assert result.start_time == datetime(2024, 10, 2, 15, 1, 23, tzinfo=UTC)
        assert result.expiry_time == datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert result.auto_renewing is True
        assert result.order_id == "order-9"

    def test_no_matching_line_item_yields_no_expiry(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """When no line item matches the subscription id, expiry is not guessed."""
        self._get_mock(_mock_service).return_value.execute.return_value = {
            "startTime": "2024-10-02T15:01:23Z",
            "lineItems": [
                {
                    "productId": "some_other_id",
                    "expiryTime": "2025-02-02T00:00:00Z",
                    "autoRenewingPlan": {"autoRenewEnabled": True},
                }
            ],
        }

        result = client.get_subscription_purchase("com.example.app", "sub_premium", "token-1")

        # No line item matched the requested subscription id, so neither expiry
        # nor auto-renew is taken from the non-matching product.
        assert result.expiry_time is None
        assert result.auto_renewing is False


# =========================================================================
# Finding 4: read methods now wrap HttpError in PlayStoreClientError
# =========================================================================


class TestReadMethodsWrapHttpError:
    """These read methods previously leaked raw HttpError; now they wrap it."""

    def test_get_releases_wraps_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        edits = _mock_service.edits.return_value
        edits.insert.return_value.execute.return_value = {"id": "edit-1"}
        edits.tracks.return_value.list.return_value.execute.side_effect = _make_http_error(403)

        with pytest.raises(PlayStoreClientError, match="Failed to fetch releases"):
            client.get_releases("com.example.app")

    def test_get_app_details_wraps_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        edits = _mock_service.edits.return_value
        edits.insert.return_value.execute.return_value = {"id": "edit-1"}
        edits.details.return_value.get.return_value.execute.side_effect = _make_http_error(403)

        with pytest.raises(PlayStoreClientError, match="Failed to fetch app details"):
            client.get_app_details("com.example.app")

    def test_get_listing_wraps_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        edits = _mock_service.edits.return_value
        edits.insert.return_value.execute.return_value = {"id": "edit-1"}
        edits.listings.return_value.get.return_value.execute.side_effect = _make_http_error(404)

        with pytest.raises(PlayStoreClientError, match="Failed to get store listing"):
            client.get_listing("com.example.app")

    def test_list_all_listings_wraps_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        edits = _mock_service.edits.return_value
        edits.insert.return_value.execute.return_value = {"id": "edit-1"}
        edits.listings.return_value.list.return_value.execute.side_effect = _make_http_error(403)

        with pytest.raises(PlayStoreClientError, match="Failed to list store listings"):
            client.list_all_listings("com.example.app")


# =========================================================================
# Finding 5: edit-orphan cleanup on non-HttpError failures (except Exception)
# =========================================================================


class TestEditOrphanCleanup:
    """Non-HttpError failures inside edit txns must abandon the edit and wrap."""

    def _prime_edit(self, _mock_service: MagicMock) -> MagicMock:
        edits = _mock_service.edits.return_value
        edits.insert.return_value.execute.return_value = {"id": "edit-1"}
        edits.delete.return_value.execute.return_value = None
        return edits

    def test_upload_apk_cleanup_on_oserror(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Any,
    ) -> None:
        edits = self._prime_edit(_mock_service)
        monkeypatch.setattr(
            client_module, "MediaFileUpload", MagicMock(side_effect=OSError("disk"))
        )
        apk = tmp_path / "app.apk"
        apk.write_bytes(b"x")

        with pytest.raises(PlayStoreClientError, match="Failed to upload APK"):
            client.upload_apk("com.example.app", str(apk))

        edits.delete.assert_called()

    def test_upload_bundle_cleanup_on_oserror(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Any,
    ) -> None:
        edits = self._prime_edit(_mock_service)
        monkeypatch.setattr(
            client_module, "MediaFileUpload", MagicMock(side_effect=OSError("disk"))
        )
        bundle = tmp_path / "app.aab"
        bundle.write_bytes(b"x")

        with pytest.raises(PlayStoreClientError, match="Failed to upload bundle"):
            client.upload_bundle("com.example.app", str(bundle))

        edits.delete.assert_called()

    def test_upload_deobfuscation_file_cleanup_on_oserror(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Any,
    ) -> None:
        edits = self._prime_edit(_mock_service)
        monkeypatch.setattr(
            client_module, "MediaFileUpload", MagicMock(side_effect=OSError("disk"))
        )
        mapping = tmp_path / "mapping.txt"
        mapping.write_text("x")

        with pytest.raises(PlayStoreClientError, match="Failed to upload deobfuscation file"):
            client.upload_deobfuscation_file("com.example.app", 100, str(mapping))

        edits.delete.assert_called()

    def test_upload_expansion_file_cleanup_on_oserror(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Any,
    ) -> None:
        edits = self._prime_edit(_mock_service)
        monkeypatch.setattr(
            client_module, "MediaFileUpload", MagicMock(side_effect=OSError("disk"))
        )
        obb = tmp_path / "main.obb"
        obb.write_bytes(b"x")

        with pytest.raises(PlayStoreClientError, match="Failed to upload expansion file"):
            client.upload_expansion_file("com.example.app", 100, str(obb))

        edits.delete.assert_called()

    def test_upload_image_cleanup_on_oserror(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Any,
    ) -> None:
        edits = self._prime_edit(_mock_service)
        monkeypatch.setattr(
            client_module, "MediaFileUpload", MagicMock(side_effect=OSError("disk"))
        )
        img = tmp_path / "icon.png"
        img.write_bytes(b"x")

        with pytest.raises(PlayStoreClientError, match="Failed to upload image"):
            client.upload_image("com.example.app", "en-US", "icon", str(img))

        edits.delete.assert_called()

    def test_delete_image_cleanup_on_runtime_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        edits = self._prime_edit(_mock_service)
        # The image delete itself succeeds; the commit step blows up.
        edits.commit.return_value.execute.side_effect = RuntimeError("commit boom")

        with pytest.raises(PlayStoreClientError, match="Failed to delete image"):
            client.delete_image("com.example.app", "en-US", "icon", "img-1")

        edits.delete.assert_called()

    def test_delete_all_images_cleanup_on_runtime_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        edits = self._prime_edit(_mock_service)
        edits.images.return_value.deleteall.return_value.execute.return_value = {"deleted": []}
        edits.commit.return_value.execute.side_effect = RuntimeError("commit boom")

        with pytest.raises(PlayStoreClientError, match="Failed to delete all images"):
            client.delete_all_images("com.example.app", "en-US", "icon")

        edits.delete.assert_called()

    def test_update_testers_cleanup_on_runtime_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        edits = self._prime_edit(_mock_service)
        edits.commit.return_value.execute.side_effect = RuntimeError("commit boom")

        result = client.update_testers("com.example.app", "internal", ["g@example.com"])

        assert result["success"] is False
        assert result["track"] == "internal"
        assert "commit boom" in result["error"]
        edits.delete.assert_called()


# =========================================================================
# Finding 6: revoke_subscription_purchase rejects unknown refund_type
# =========================================================================


class TestRevokeSubscriptionRefundType:
    def test_invalid_refund_type_raises(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        with pytest.raises(PlayStoreClientError, match="Invalid refund_type"):
            client.revoke_subscription_purchase("com.example.app", "token-1", refund_type="bogus")


# =========================================================================
# Finding 7: pagination across nextPageToken for list_* methods
# =========================================================================


class TestPagination:
    """Each list_* method must combine pages and pass pageToken on page 2."""

    def test_list_subscriptions_paginates(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        list_mock = _mock_service.monetization.return_value.subscriptions.return_value.list
        list_mock.return_value.execute.side_effect = [
            {"subscriptions": [{"productId": "s1"}], "nextPageToken": "tok"},
            {"subscriptions": [{"productId": "s2"}]},
        ]

        result = client.list_subscriptions("com.example.app")

        assert [s.product_id for s in result] == ["s1", "s2"]
        assert list_mock.call_count == 2
        assert list_mock.call_args_list[1].kwargs["pageToken"] == "tok"

    def test_list_one_time_products_paginates(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        list_mock = _mock_service.monetization.return_value.onetimeproducts.return_value.list
        list_mock.return_value.execute.side_effect = [
            {"oneTimeProducts": [{"productId": "p1"}], "nextPageToken": "tok"},
            {"oneTimeProducts": [{"productId": "p2"}]},
        ]

        result = client.list_one_time_products("com.example.app")

        assert [p.product_id for p in result] == ["p1", "p2"]
        assert list_mock.call_count == 2
        assert list_mock.call_args_list[1].kwargs["pageToken"] == "tok"

    def test_list_purchase_option_offers_paginates(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        list_mock = _mock_service.monetization.return_value.onetimeproducts.return_value.purchaseOptions.return_value.offers.return_value.list
        list_mock.return_value.execute.side_effect = [
            {"oneTimeProductOffers": [{"offerId": "o1"}], "nextPageToken": "tok"},
            {"oneTimeProductOffers": [{"offerId": "o2"}]},
        ]

        result = client.list_purchase_option_offers("com.example.app", "prod", "opt")

        assert [o.offer_id for o in result] == ["o1", "o2"]
        assert list_mock.call_count == 2
        first_call = list_mock.call_args_list[0].kwargs
        assert first_call["productId"] == "prod"
        assert first_call["purchaseOptionId"] == "opt"
        assert list_mock.call_args_list[1].kwargs["pageToken"] == "tok"

    def test_list_subscription_offers_paginates(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        list_mock = _mock_service.monetization.return_value.subscriptions.return_value.basePlans.return_value.offers.return_value.list
        list_mock.return_value.execute.side_effect = [
            {"subscriptionOffers": [{"offerId": "o1"}], "nextPageToken": "tok"},
            {"subscriptionOffers": [{"offerId": "o2"}]},
        ]

        result = client.list_subscription_offers("com.example.app", "prod", "base")

        assert [o.offer_id for o in result] == ["o1", "o2"]
        assert list_mock.call_count == 2
        first_call = list_mock.call_args_list[0].kwargs
        assert first_call["productId"] == "prod"
        assert first_call["basePlanId"] == "base"
        assert list_mock.call_args_list[1].kwargs["pageToken"] == "tok"

    def test_list_device_tier_configs_paginates(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        list_mock = _mock_service.applications.return_value.deviceTierConfigs.return_value.list
        list_mock.return_value.execute.side_effect = [
            {"deviceTierConfigs": [{"deviceTierConfigId": "c1"}], "nextPageToken": "tok"},
            {"deviceTierConfigs": [{"deviceTierConfigId": "c2"}]},
        ]

        result = client.list_device_tier_configs("com.example.app")

        assert [c.device_tier_config_id for c in result] == ["c1", "c2"]
        assert list_mock.call_count == 2
        assert list_mock.call_args_list[1].kwargs["pageToken"] == "tok"

    def test_list_users_paginates(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        list_mock = _mock_service.users.return_value.list
        list_mock.return_value.execute.side_effect = [
            {"users": [{"email": "a@b.com"}], "nextPageToken": "tok"},
            {"users": [{"email": "c@d.com"}]},
        ]

        result = client.list_users("dev-123")

        assert [u.email for u in result] == ["a@b.com", "c@d.com"]
        assert list_mock.call_count == 2
        assert list_mock.call_args_list[0].kwargs["parent"] == "developers/dev-123"
        assert list_mock.call_args_list[1].kwargs["pageToken"] == "tok"

    def test_list_in_app_products_paginates(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """inappproducts.list paginates via tokenPagination.nextPageToken (older shape)."""
        list_mock = _mock_service.inappproducts.return_value.list
        list_mock.return_value.execute.side_effect = [
            {"inappproduct": [{"sku": "p1"}], "tokenPagination": {"nextPageToken": "tok"}},
            {"inappproduct": [{"sku": "p2"}]},
        ]

        result = client.list_in_app_products("com.example.app")

        assert [p.sku for p in result] == ["p1", "p2"]
        assert list_mock.call_count == 2
        assert list_mock.call_args_list[1].kwargs["token"] == "tok"

    def test_get_reviews_paginates(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """reviews.list paginates via tokenPagination.nextPageToken and combines pages."""
        list_mock = _mock_service.reviews.return_value.list
        list_mock.return_value.execute.side_effect = [
            {
                "reviews": [{"reviewId": "r1", "comments": [{"userComment": {"text": "a"}}]}],
                "tokenPagination": {"nextPageToken": "tok"},
            },
            {"reviews": [{"reviewId": "r2", "comments": [{"userComment": {"text": "b"}}]}]},
        ]

        result = client.get_reviews("com.example.app")

        assert [r.review_id for r in result] == ["r1", "r2"]
        assert list_mock.call_count == 2
        assert list_mock.call_args_list[1].kwargs["token"] == "tok"

    def test_get_reviews_stops_at_max_results(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Once max_results reviews are collected, pagination stops and the list is sliced."""
        list_mock = _mock_service.reviews.return_value.list
        list_mock.return_value.execute.return_value = {
            "reviews": [
                {"reviewId": "r1", "comments": [{"userComment": {"text": "a"}}]},
                {"reviewId": "r2", "comments": [{"userComment": {"text": "b"}}]},
            ],
            "tokenPagination": {"nextPageToken": "tok"},
        }

        result = client.get_reviews("com.example.app", max_results=1)

        assert [r.review_id for r in result] == ["r1"]
        assert list_mock.call_count == 1

    def test_list_voided_purchases_paginates(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """voidedpurchases.list paginates via tokenPagination.nextPageToken."""
        list_mock = _mock_service.purchases.return_value.voidedpurchases.return_value.list
        list_mock.return_value.execute.side_effect = [
            {
                "voidedPurchases": [{"purchaseToken": "t1"}],
                "tokenPagination": {"nextPageToken": "tok"},
            },
            {"voidedPurchases": [{"purchaseToken": "t2"}]},
        ]

        result = client.list_voided_purchases("com.example.app")

        assert [v.purchase_token for v in result] == ["t1", "t2"]
        assert list_mock.call_count == 2
        assert list_mock.call_args_list[1].kwargs["token"] == "tok"

    def test_list_voided_purchases_stops_at_max_results(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Once max_results voided purchases are collected, pagination stops and slices."""
        list_mock = _mock_service.purchases.return_value.voidedpurchases.return_value.list
        list_mock.return_value.execute.return_value = {
            "voidedPurchases": [{"purchaseToken": "t1"}, {"purchaseToken": "t2"}],
            "tokenPagination": {"nextPageToken": "tok"},
        }

        result = client.list_voided_purchases("com.example.app", max_results=1)

        assert [v.purchase_token for v in result] == ["t1"]
        assert list_mock.call_count == 1


class TestOrderParsing:
    """get_order/batch_get_orders parse the v3 Order resource (lineItems + state)."""

    def test_get_order_falls_back_to_requested_id(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """When the response omits orderId, the requested id is used."""
        _mock_service.orders.return_value.get.return_value.execute.return_value = {
            "state": "PROCESSED",
            "lineItems": [{"productId": "coins"}],
        }

        order = client.get_order("com.example.app", "GPA.requested")

        assert order.order_id == "GPA.requested"
        assert order.state == "PROCESSED"
        assert order.product_ids == ["coins"]


# =========================================================================
# Finding 8: download OSError is caught and wrapped
# =========================================================================


class TestDownloadOsError:
    """Writing to an undwritable path raises OSError, now wrapped."""

    _BAD_PATH = "/nonexistent_dir_xyzzy/out.apk"

    def test_download_generated_apk_wraps_oserror(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        with pytest.raises(PlayStoreClientError, match="Failed to write generated APK"):
            client.download_generated_apk("com.example.app", 100, "download-1", self._BAD_PATH)

    def test_download_system_apk_variant_wraps_oserror(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        with pytest.raises(PlayStoreClientError, match="Failed to write system APK variant"):
            client.download_system_apk_variant("com.example.app", 100, 1, self._BAD_PATH)


# =========================================================================
# Finding 9: /credentials endpoint auth hardening
# =========================================================================

_ADMIN_TOKEN_ENV = "PLAY_STORE_MCP_ADMIN_TOKEN"


def _valid_credentials() -> dict[str, str]:
    return {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "kid",
        "private_key": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----",
        "client_email": "svc@test-project.iam.gserviceaccount.com",
        "client_id": "1",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


class TestCredentialsAuthorization:
    """_authorize_credentials_request gating (loopback vs admin token)."""

    def test_no_token_non_loopback_returns_403(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from starlette.requests import Request

        from play_store_mcp.server import _authorize_credentials_request

        monkeypatch.delenv(_ADMIN_TOKEN_ENV, raising=False)

        request = MagicMock(spec=Request)
        request.client.host = "203.0.113.5"
        request.headers = {}

        result = _authorize_credentials_request(request)

        assert result is not None
        assert result.status_code == 403
        assert "localhost" in json.loads(result.body)["error"]

    def test_token_valid_bearer_from_non_loopback_authorizes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from starlette.requests import Request

        from play_store_mcp.server import _authorize_credentials_request

        monkeypatch.setenv(_ADMIN_TOKEN_ENV, "secret-token")

        request = MagicMock(spec=Request)
        request.client.host = "203.0.113.5"
        request.headers = {"authorization": "Bearer secret-token"}

        # None means "authorized, proceed".
        assert _authorize_credentials_request(request) is None

    def test_token_wrong_header_returns_401(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from starlette.requests import Request

        from play_store_mcp.server import _authorize_credentials_request

        monkeypatch.setenv(_ADMIN_TOKEN_ENV, "secret-token")

        request = MagicMock(spec=Request)
        request.client.host = "127.0.0.1"
        request.headers = {"authorization": "Bearer wrong-token"}

        result = _authorize_credentials_request(request)

        assert result is not None
        assert result.status_code == 401
        assert json.loads(result.body)["error"] == "Missing or invalid admin token"

    def test_token_missing_header_returns_401(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from starlette.requests import Request

        from play_store_mcp.server import _authorize_credentials_request

        monkeypatch.setenv(_ADMIN_TOKEN_ENV, "secret-token")

        request = MagicMock(spec=Request)
        request.client.host = "127.0.0.1"
        request.headers = {}

        result = _authorize_credentials_request(request)

        assert result is not None
        assert result.status_code == 401
        assert json.loads(result.body)["error"] == "Missing or invalid admin token"

    def test_token_non_ascii_header_returns_401_not_500(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A non-ASCII Authorization header must cleanly return 401, not raise a
        # TypeError (secrets.compare_digest rejects non-ASCII str operands, and
        # Starlette decodes header values as latin-1).
        from starlette.requests import Request

        from play_store_mcp.server import _authorize_credentials_request

        monkeypatch.setenv(_ADMIN_TOKEN_ENV, "secret-token")

        request = MagicMock(spec=Request)
        request.client.host = "203.0.113.5"
        request.headers = {"authorization": "Bearer \x80\xff-not-ascii"}

        result = _authorize_credentials_request(request)

        assert result is not None
        assert result.status_code == 401
        assert json.loads(result.body)["error"] == "Missing or invalid admin token"


class TestCredentialsEndpointAuth:
    """update_credentials honors admin-token auth end-to-end."""

    @pytest.mark.asyncio
    async def test_token_allows_non_loopback_and_updates(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from starlette.requests import Request

        from play_store_mcp import server
        from play_store_mcp.server import update_credentials

        monkeypatch.setenv(_ADMIN_TOKEN_ENV, "secret-token")

        with patch("play_store_mcp.client.PlayStoreClient._get_service") as mock_service:
            mock_service.return_value = MagicMock()

            request = MagicMock(spec=Request)
            request.client.host = "203.0.113.5"
            request.headers = {"authorization": "Bearer secret-token"}
            request.json = AsyncMock(return_value={"credentials": _valid_credentials()})

            server._shared_state = {"client": None, "credentials_updated": False}

            response = await update_credentials(request)

        assert response.status_code == 200
        data = json.loads(response.body)
        assert data["success"] is True
        assert "updated successfully" in data["message"]

    @pytest.mark.asyncio
    async def test_token_wrong_header_blocks_before_body(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from starlette.requests import Request

        from play_store_mcp.server import update_credentials

        monkeypatch.setenv(_ADMIN_TOKEN_ENV, "secret-token")

        request = MagicMock(spec=Request)
        request.client.host = "127.0.0.1"
        request.headers = {"authorization": "Bearer nope"}
        # If auth were bypassed this would be consulted; it must not be.
        request.json = AsyncMock(return_value={"credentials": _valid_credentials()})

        response = await update_credentials(request)

        assert response.status_code == 401
        assert json.loads(response.body)["error"] == "Missing or invalid admin token"
        request.json.assert_not_called()
