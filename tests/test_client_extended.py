"""Extended tests for PlayStoreClient — covers error paths, retry logic, and uncovered methods."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from play_store_mcp.client import (
    MAX_RETRIES,
    PlayStoreClient,
    PlayStoreClientError,
    retry_with_backoff,
)

# =========================================================================
# Helpers
# =========================================================================


def _make_http_error(status: int, reason: str = "error") -> HttpError:
    """Create a mock HttpError with given status."""
    resp = MagicMock()
    resp.status = status
    return HttpError(resp=resp, content=reason.encode())


# =========================================================================
# retry_with_backoff tests
# =========================================================================


class TestRetryWithBackoff:
    """Test the retry decorator."""

    @patch("play_store_mcp.client.time.sleep")
    def test_retries_on_500(self, mock_sleep: MagicMock) -> None:
        """Test that 500 errors trigger retries."""
        call_count = 0

        @retry_with_backoff
        def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise _make_http_error(500)
            return "ok"

        result = flaky()
        assert result == "ok"
        assert call_count == 3
        assert mock_sleep.call_count == 2

    @patch("play_store_mcp.client.time.sleep")
    def test_retries_on_429(self, _mock_sleep: MagicMock) -> None:
        """Test that 429 rate limit errors trigger retries."""
        call_count = 0

        @retry_with_backoff
        def rate_limited() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise _make_http_error(429)
            return "ok"

        result = rate_limited()
        assert result == "ok"
        assert call_count == 2

    @patch("play_store_mcp.client.time.sleep")
    def test_retries_on_503(self, _mock_sleep: MagicMock) -> None:
        """Test that 503 errors trigger retries."""
        call_count = 0

        @retry_with_backoff
        def unavailable() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise _make_http_error(503)
            return "ok"

        result = unavailable()
        assert result == "ok"

    def test_no_retry_on_400(self) -> None:
        """Test that 400 errors are not retried."""

        @retry_with_backoff
        def bad_request() -> str:
            raise _make_http_error(400)

        with pytest.raises(HttpError):
            bad_request()

    def test_no_retry_on_403(self) -> None:
        """Test that 403 errors are not retried."""

        @retry_with_backoff
        def forbidden() -> str:
            raise _make_http_error(403)

        with pytest.raises(HttpError):
            forbidden()

    def test_no_retry_on_non_http_error(self) -> None:
        """Test that non-HttpError exceptions are not retried."""

        @retry_with_backoff
        def broken() -> str:
            raise ValueError("not an http error")

        with pytest.raises(ValueError, match="not an http error"):
            broken()

    @patch("play_store_mcp.client.time.sleep")
    def test_max_retries_exceeded(self, mock_sleep: MagicMock) -> None:
        """Test that exceeding max retries raises the error."""

        @retry_with_backoff
        def always_fails() -> str:
            raise _make_http_error(500)

        with pytest.raises(HttpError):
            always_fails()

        # Should have slept MAX_RETRIES - 1 times then raised on the last attempt
        assert mock_sleep.call_count == MAX_RETRIES - 1

    def test_success_on_first_try(self) -> None:
        """Test that successful calls work without retries."""

        @retry_with_backoff
        def works() -> str:
            return "immediate"

        assert works() == "immediate"


# =========================================================================
# _get_service error path
# =========================================================================


class TestGetServiceErrors:
    """Test _get_service error handling."""

    def test_service_init_failure(self, tmp_path: Any) -> None:
        """Test that service initialization failure wraps the error."""
        creds_file = tmp_path / "bad-creds.json"
        creds_file.write_text('{"type": "invalid"}')

        client = PlayStoreClient(credentials_path=str(creds_file))

        with (
            patch(
                "play_store_mcp.client.service_account.Credentials.from_service_account_file",
                side_effect=ValueError("bad creds"),
            ),
            pytest.raises(PlayStoreClientError, match="Failed to initialize API client"),
        ):
            client._get_service()

    def test_cached_service_returned(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test that cached service is returned on subsequent calls."""
        svc1 = client._get_service()
        svc2 = client._get_service()
        assert svc1 is svc2


# =========================================================================
# deploy_app error paths
# =========================================================================


class TestDeployAppErrors:
    """Test deploy_app error handling."""

    def test_deploy_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test deployment failure from HttpError."""
        apk_file = tmp_path / "app.apk"
        apk_file.write_bytes(b"content")

        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.apks.return_value.upload.return_value.execute.side_effect = _make_http_error(
            403, "forbidden"
        )
        mock_edits.delete.return_value.execute.return_value = None

        result = client.deploy_app(
            package_name="com.example.app",
            track="internal",
            file_path=str(apk_file),
        )

        assert result.success is False
        assert "Deployment failed" in result.message

    def test_deploy_generic_exception(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test deployment failure from generic Exception."""
        apk_file = tmp_path / "app.apk"
        apk_file.write_bytes(b"content")

        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.apks.return_value.upload.return_value.execute.side_effect = RuntimeError(
            "disk full"
        )
        mock_edits.delete.return_value.execute.return_value = None

        result = client.deploy_app(
            package_name="com.example.app",
            track="internal",
            file_path=str(apk_file),
        )

        assert result.success is False
        assert "disk full" in result.message


# =========================================================================
# promote_release error paths
# =========================================================================


class TestPromoteReleaseErrors:
    """Test promote_release error handling."""

    def test_promote_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test promotion failure from HttpError."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.tracks.return_value.get.return_value.execute.side_effect = _make_http_error(
            404, "not found"
        )
        mock_edits.delete.return_value.execute.return_value = None

        result = client.promote_release(
            package_name="com.example.app",
            from_track="beta",
            to_track="production",
            version_code=100,
        )

        assert result.success is False
        assert "Promotion failed" in result.message

    def test_promote_generic_exception(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test promotion failure from generic Exception."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.tracks.return_value.get.return_value.execute.side_effect = RuntimeError("boom")
        mock_edits.delete.return_value.execute.return_value = None

        result = client.promote_release(
            package_name="com.example.app",
            from_track="beta",
            to_track="production",
            version_code=100,
        )

        assert result.success is False
        assert "boom" in result.message

    def test_promote_staged_rollout(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test promotion with staged rollout percentage."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.tracks.return_value.get.return_value.execute.return_value = {
            "track": "beta",
            "releases": [{"versionCodes": ["100"], "releaseNotes": []}],
        }
        mock_edits.tracks.return_value.update.return_value.execute.return_value = {}
        mock_edits.commit.return_value.execute.return_value = {}

        result = client.promote_release(
            package_name="com.example.app",
            from_track="beta",
            to_track="production",
            version_code=100,
            rollout_percentage=25.0,
        )

        assert result.success is True
        update_call = mock_edits.tracks.return_value.update.call_args
        body = update_call.kwargs["body"]
        assert body["releases"][0]["status"] == "inProgress"
        assert body["releases"][0]["userFraction"] == 0.25


# =========================================================================
# halt_release tests
# =========================================================================


class TestHaltRelease:
    """Test halt_release method."""

    def test_halt_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test successful halt."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.tracks.return_value.get.return_value.execute.return_value = {
            "track": "production",
            "releases": [{"versionCodes": ["100"], "status": "inProgress"}],
        }
        mock_edits.tracks.return_value.update.return_value.execute.return_value = {}
        mock_edits.commit.return_value.execute.return_value = {}

        result = client.halt_release("com.example.app", "production", 100)

        assert result.success is True
        assert "halted" in result.message.lower()

    def test_halt_version_not_found(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test halt with nonexistent version."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.tracks.return_value.get.return_value.execute.return_value = {
            "track": "production",
            "releases": [{"versionCodes": ["99"]}],
        }
        mock_edits.delete.return_value.execute.return_value = None

        result = client.halt_release("com.example.app", "production", 100)

        assert result.success is False
        assert "not found" in result.message

    def test_halt_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test halt failure from HttpError."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.tracks.return_value.get.return_value.execute.side_effect = _make_http_error(500)
        mock_edits.delete.return_value.execute.return_value = None

        result = client.halt_release("com.example.app", "production", 100)

        assert result.success is False
        assert "Halt failed" in result.message

    def test_halt_generic_exception(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test halt failure from generic Exception."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.tracks.return_value.get.return_value.execute.side_effect = RuntimeError("oops")
        mock_edits.delete.return_value.execute.return_value = None

        result = client.halt_release("com.example.app", "production", 100)

        assert result.success is False
        assert "oops" in result.message


# =========================================================================
# update_rollout tests
# =========================================================================


class TestUpdateRollout:
    """Test update_rollout method."""

    def test_update_rollout_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test successful rollout update."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.tracks.return_value.get.return_value.execute.return_value = {
            "track": "production",
            "releases": [{"versionCodes": ["100"], "status": "inProgress", "userFraction": 0.1}],
        }
        mock_edits.tracks.return_value.update.return_value.execute.return_value = {}
        mock_edits.commit.return_value.execute.return_value = {}

        result = client.update_rollout("com.example.app", "production", 100, 50.0)

        assert result.success is True
        assert "50.0%" in result.message

    def test_update_rollout_complete(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test completing a rollout (100%)."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.tracks.return_value.get.return_value.execute.return_value = {
            "track": "production",
            "releases": [{"versionCodes": ["100"], "status": "inProgress", "userFraction": 0.5}],
        }
        mock_edits.tracks.return_value.update.return_value.execute.return_value = {}
        mock_edits.commit.return_value.execute.return_value = {}

        result = client.update_rollout("com.example.app", "production", 100, 100.0)

        assert result.success is True

    def test_update_rollout_version_not_found(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test rollout update with nonexistent version."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.tracks.return_value.get.return_value.execute.return_value = {
            "track": "production",
            "releases": [{"versionCodes": ["99"]}],
        }
        mock_edits.delete.return_value.execute.return_value = None

        result = client.update_rollout("com.example.app", "production", 100, 50.0)

        assert result.success is False
        assert "not found" in result.message

    def test_update_rollout_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test rollout update failure from HttpError."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.tracks.return_value.get.return_value.execute.side_effect = _make_http_error(500)
        mock_edits.delete.return_value.execute.return_value = None

        result = client.update_rollout("com.example.app", "production", 100, 50.0)

        assert result.success is False

    def test_update_rollout_generic_exception(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test rollout update failure from generic Exception."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.tracks.return_value.get.return_value.execute.side_effect = RuntimeError("fail")
        mock_edits.delete.return_value.execute.return_value = None

        result = client.update_rollout("com.example.app", "production", 100, 50.0)

        assert result.success is False
        assert "fail" in result.message


# =========================================================================
# list_apps, get_app_details tests
# =========================================================================


class TestListApps:
    """Test list_apps method."""

    def test_list_apps_returns_empty(self, client: PlayStoreClient) -> None:
        """Test that list_apps returns empty list."""
        apps = client.list_apps()
        assert apps == []


class TestGetAppDetails:
    """Test get_app_details method."""

    def test_get_app_details_listing_not_found(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test get_app_details when listing is not found for language."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.details.return_value.get.return_value.execute.return_value = {
            "defaultLanguage": "en-US",
            "contactEmail": "dev@example.com",
        }
        # Listing fetch fails with 404
        mock_edits.listings.return_value.get.return_value.execute.side_effect = _make_http_error(
            404
        )
        mock_edits.delete.return_value.execute.return_value = None

        details = client.get_app_details("com.example.app", "fr-FR")

        assert details.package_name == "com.example.app"
        assert details.title is None  # No listing found
        assert details.default_language == "en-US"


# =========================================================================
# Reviews error paths
# =========================================================================


class TestReviewsExtended:
    """Extended review tests."""

    def test_get_reviews_with_translation(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test get_reviews with translation language."""
        _mock_service.reviews.return_value.list.return_value.execute.return_value = {
            "reviews": [
                {
                    "reviewId": "r1",
                    "authorName": "User",
                    "comments": [
                        {"userComment": {"starRating": 4, "text": "Good", "reviewerLanguage": "es"}}
                    ],
                }
            ]
        }

        reviews = client.get_reviews("com.example.app", translation_language="en")

        assert len(reviews) == 1
        assert reviews[0].star_rating == 4

    def test_get_reviews_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test get_reviews HttpError."""
        _mock_service.reviews.return_value.list.return_value.execute.side_effect = _make_http_error(
            403
        )

        with pytest.raises(PlayStoreClientError, match="Failed to fetch reviews"):
            client.get_reviews("com.example.app")

    def test_reply_to_review_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test reply_to_review HttpError."""
        _mock_service.reviews.return_value.reply.return_value.execute.side_effect = (
            _make_http_error(403)
        )

        result = client.reply_to_review("com.example.app", "r1", "Thanks!")

        assert result.success is False
        assert "Failed to reply" in result.message


# =========================================================================
# Subscriptions error paths
# =========================================================================


class TestSubscriptionsExtended:
    """Extended subscription tests."""

    def test_list_subscriptions_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test list_subscriptions HttpError."""
        _mock_service.monetization.return_value.subscriptions.return_value.list.return_value.execute.side_effect = _make_http_error(
            403
        )

        with pytest.raises(PlayStoreClientError, match="Failed to list subscriptions"):
            client.list_subscriptions("com.example.app")

    def test_get_subscription_purchase_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test successful subscription purchase fetch."""
        _mock_service.purchases.return_value.subscriptionsv2.return_value.get.return_value.execute.return_value = {
            "latestOrderId": "order-123",
            "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
        }

        result = client.get_subscription_purchase("com.example.app", "premium", "token123")

        assert result.subscription_id == "premium"
        assert result.auto_renewing is True
        assert result.order_id == "order-123"

    def test_get_subscription_purchase_inactive(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test subscription purchase that is not active."""
        _mock_service.purchases.return_value.subscriptionsv2.return_value.get.return_value.execute.return_value = {
            "latestOrderId": "order-456",
            "subscriptionState": "SUBSCRIPTION_STATE_EXPIRED",
        }

        result = client.get_subscription_purchase("com.example.app", "premium", "token456")

        assert result.auto_renewing is False

    def test_get_subscription_purchase_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test get_subscription_purchase HttpError."""
        _mock_service.purchases.return_value.subscriptionsv2.return_value.get.return_value.execute.side_effect = _make_http_error(
            404
        )

        with pytest.raises(PlayStoreClientError, match="Failed to get subscription status"):
            client.get_subscription_purchase("com.example.app", "premium", "token")


# =========================================================================
# Voided purchases
# =========================================================================


class TestVoidedPurchases:
    """Test voided purchases methods."""

    def test_list_voided_purchases_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test successful voided purchases fetch."""
        _mock_service.purchases.return_value.voidedpurchases.return_value.list.return_value.execute.return_value = {
            "voidedPurchases": [
                {
                    "purchaseToken": "tok1",
                    "orderId": "order1",
                    "voidedReason": 1,
                    "voidedSource": 0,
                },
                {
                    "purchaseToken": "tok2",
                    "orderId": "order2",
                },
            ]
        }

        voided = client.list_voided_purchases("com.example.app")

        assert len(voided) == 2
        assert voided[0].purchase_token == "tok1"
        assert voided[0].voided_reason == 1
        assert voided[1].order_id == "order2"

    def test_list_voided_purchases_empty(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test voided purchases when none exist."""
        _mock_service.purchases.return_value.voidedpurchases.return_value.list.return_value.execute.return_value = {}

        voided = client.list_voided_purchases("com.example.app")

        assert voided == []

    def test_list_voided_purchases_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test list_voided_purchases HttpError."""
        _mock_service.purchases.return_value.voidedpurchases.return_value.list.return_value.execute.side_effect = _make_http_error(
            403
        )

        with pytest.raises(PlayStoreClientError, match="Failed to list voided purchases"):
            client.list_voided_purchases("com.example.app")


# =========================================================================
# Listing update error paths
# =========================================================================


class TestUpdateListingErrors:
    """Test update_listing error handling."""

    def test_update_listing_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test update_listing HttpError."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.listings.return_value.get.return_value.execute.return_value = {
            "title": "Old",
            "fullDescription": "Old desc",
            "shortDescription": "Old short",
        }
        mock_edits.listings.return_value.update.return_value.execute.side_effect = _make_http_error(
            403
        )
        mock_edits.delete.return_value.execute.return_value = None

        result = client.update_listing(
            package_name="com.example.app",
            language="en-US",
            title="New Title",
        )

        assert result.success is False
        assert "Failed to update listing" in result.message

    def test_update_listing_generic_exception(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test update_listing generic Exception."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.listings.return_value.get.return_value.execute.return_value = {}
        mock_edits.listings.return_value.update.return_value.execute.side_effect = RuntimeError(
            "boom"
        )
        mock_edits.delete.return_value.execute.return_value = None

        result = client.update_listing(
            package_name="com.example.app",
            language="en-US",
            full_description="New desc",
        )

        assert result.success is False
        assert "boom" in result.message

    def test_update_listing_current_listing_not_found(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test update_listing when current listing doesn't exist."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        # Current listing fetch fails
        mock_edits.listings.return_value.get.return_value.execute.side_effect = _make_http_error(
            404
        )
        mock_edits.listings.return_value.update.return_value.execute.return_value = {}
        mock_edits.commit.return_value.execute.return_value = {}

        # Need to reset side_effect after first call
        call_count = 0

        def get_side_effect() -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_http_error(404)
            return {}

        mock_edits.listings.return_value.get.return_value.execute.side_effect = get_side_effect

        result = client.update_listing(
            package_name="com.example.app",
            language="en-US",
            title="Brand New",
            short_description="New short",
        )

        assert result.success is True


# =========================================================================
# Testers error paths
# =========================================================================


class TestTestersExtended:
    """Extended testers tests."""

    def test_get_testers_404(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test get_testers when no testers configured (404)."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.testers.return_value.get.return_value.execute.side_effect = _make_http_error(404)
        mock_edits.delete.return_value.execute.return_value = None

        testers = client.get_testers("com.example.app", "internal")

        assert testers.track == "internal"
        assert testers.tester_emails == []

    def test_get_testers_other_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test get_testers with non-404 error."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.testers.return_value.get.return_value.execute.side_effect = _make_http_error(500)
        mock_edits.delete.return_value.execute.return_value = None

        with pytest.raises(PlayStoreClientError, match="Failed to get testers"):
            client.get_testers("com.example.app", "internal")

    def test_update_testers_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test update_testers HttpError."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.testers.return_value.update.return_value.execute.side_effect = _make_http_error(
            403
        )
        mock_edits.delete.return_value.execute.return_value = None

        result = client.update_testers("com.example.app", "beta", ["test@example.com"])

        assert result.success is False
        assert "Failed to update testers" in result.message


# =========================================================================
# Orders error paths
# =========================================================================


class TestOrdersExtended:
    """Extended orders tests."""

    def test_get_order_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test get_order HttpError."""
        _mock_service.orders.return_value.get.return_value.execute.side_effect = _make_http_error(
            404
        )

        with pytest.raises(PlayStoreClientError, match="Failed to get order"):
            client.get_order("com.example.app", "order-123")


# =========================================================================
# Expansion files error paths
# =========================================================================


class TestExpansionFilesExtended:
    """Extended expansion file tests."""

    def test_get_expansion_file_404(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test get_expansion_file when no expansion file exists (404)."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.expansionfiles.return_value.get.return_value.execute.side_effect = (
            _make_http_error(404)
        )
        mock_edits.delete.return_value.execute.return_value = None

        expansion = client.get_expansion_file("com.example.app", 100, "main")

        assert expansion.version_code == 100
        assert expansion.file_size is None

    def test_get_expansion_file_other_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test get_expansion_file with non-404 error."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.expansionfiles.return_value.get.return_value.execute.side_effect = (
            _make_http_error(500)
        )
        mock_edits.delete.return_value.execute.return_value = None

        with pytest.raises(PlayStoreClientError, match="Failed to get expansion file"):
            client.get_expansion_file("com.example.app", 100, "main")


# =========================================================================
# Validation edge cases
# =========================================================================


class TestValidationExtended:
    """Extended validation tests."""

    def test_validate_empty_package_name(self, client: PlayStoreClient) -> None:
        """Test validating empty package name."""
        errors = client.validate_package_name("")
        assert len(errors) == 1
        assert "empty" in errors[0].message.lower()

    def test_validate_short_description_too_long(self, client: PlayStoreClient) -> None:
        """Test validating short description that's too long."""
        errors = client.validate_listing_text(short_description="A" * 81)
        assert len(errors) == 1
        assert "short_description" in errors[0].field

    def test_validate_full_description_too_long(self, client: PlayStoreClient) -> None:
        """Test validating full description that's too long."""
        errors = client.validate_listing_text(full_description="A" * 4001)
        assert len(errors) == 1
        assert "full_description" in errors[0].field

    def test_validate_all_listing_text_too_long(self, client: PlayStoreClient) -> None:
        """Test validating all listing text fields too long."""
        errors = client.validate_listing_text(
            title="A" * 51,
            short_description="B" * 81,
            full_description="C" * 4001,
        )
        assert len(errors) == 3


# =========================================================================
# Batch deploy edge cases
# =========================================================================


class TestBatchDeployExtended:
    """Extended batch deploy tests."""

    def test_batch_deploy_with_rollout_percentages(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test batch deploy with custom rollout percentages."""
        apk_file = tmp_path / "app.apk"
        apk_file.write_bytes(b"content")

        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.apks.return_value.upload.return_value.execute.return_value = {"versionCode": 100}
        mock_edits.tracks.return_value.update.return_value.execute.return_value = {}
        mock_edits.commit.return_value.execute.return_value = {}

        result = client.batch_deploy(
            package_name="com.example.app",
            file_path=str(apk_file),
            tracks=["internal", "production"],
            release_notes="Test",
            rollout_percentages={"production": 10.0},
        )

        assert result.success is True
        assert result.successful_count == 2

    def test_batch_deploy_partial_failure(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test batch deploy where one track fails."""
        apk_file = tmp_path / "app.apk"
        apk_file.write_bytes(b"content")

        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}

        call_count = 0

        def upload_side_effect(**_kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            if call_count > 1:
                mock.execute.side_effect = _make_http_error(403)
            else:
                mock.execute.return_value = {"versionCode": 100}
            return mock

        mock_edits.apks.return_value.upload.side_effect = upload_side_effect
        mock_edits.tracks.return_value.update.return_value.execute.return_value = {}
        mock_edits.commit.return_value.execute.return_value = {}
        mock_edits.delete.return_value.execute.return_value = None

        result = client.batch_deploy(
            package_name="com.example.app",
            file_path=str(apk_file),
            tracks=["internal", "beta"],
        )

        assert result.success is False
        assert result.successful_count == 1
        assert result.failed_count == 1
        assert "failed" in result.message.lower()


# =========================================================================
# _delete_edit edge case
# =========================================================================


class TestDeleteEdit:
    """Test _delete_edit error handling."""

    def test_delete_edit_ignores_http_error(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test that _delete_edit silently ignores HttpError."""
        # First call _get_service to initialize
        client._get_service()

        _mock_service.edits.return_value.delete.return_value.execute.side_effect = _make_http_error(
            404
        )

        # Should not raise
        client._delete_edit("com.example.app", "edit-123")
