"""Tests for PlayStoreClient."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

from play_store_mcp.client import PlayStoreClient, PlayStoreClientError


class TestPlayStoreClientInit:
    """Test client initialization."""

    def test_missing_credentials_raises_error(self) -> None:
        """Test that missing credentials raises an error."""
        client = PlayStoreClient(credentials_path="/nonexistent/path.json")

        with pytest.raises(PlayStoreClientError, match="Credentials file not found"):
            client._get_service()

    def test_no_credentials_env_var_raises_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that missing env var raises an error."""
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

        client = PlayStoreClient()

        with pytest.raises(PlayStoreClientError, match="No credentials provided"):
            client._get_service()


class TestGetReleases:
    """Test get_releases method."""

    def test_get_releases_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        sample_track_response: dict[str, Any],
    ) -> None:
        """Test successful release fetching."""
        # Setup mock
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.tracks.return_value.list.return_value.execute.return_value = (
            sample_track_response
        )
        mock_edits.delete.return_value.execute.return_value = None

        # Execute
        tracks = client.get_releases("com.example.app")

        # Verify
        assert len(tracks) == 2

        # Check production track
        prod_track = next(t for t in tracks if t.track == "production")
        assert len(prod_track.releases) == 1
        assert prod_track.releases[0].version_codes == [100]
        assert prod_track.releases[0].status == "completed"

        # Check beta track
        beta_track = next(t for t in tracks if t.track == "beta")
        assert len(beta_track.releases) == 1
        assert beta_track.releases[0].rollout_percentage == 50.0


class TestDeployApp:
    """Test deploy_app method."""

    def test_deploy_file_not_found(
        self,
        client: PlayStoreClient,
    ) -> None:
        """Test deployment with missing file."""
        result = client.deploy_app(
            package_name="com.example.app",
            track="internal",
            file_path="/nonexistent/app.apk",
        )

        assert result.success is False
        assert "File not found" in result.message

    def test_deploy_apk_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test successful APK deployment."""
        # Create test APK file
        apk_file = tmp_path / "app.apk"
        apk_file.write_bytes(b"fake apk content")

        # Setup mocks
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.apks.return_value.upload.return_value.execute.return_value = {"versionCode": 100}
        mock_edits.tracks.return_value.update.return_value.execute.return_value = {}
        mock_edits.commit.return_value.execute.return_value = {}

        # Execute
        result = client.deploy_app(
            package_name="com.example.app",
            track="internal",
            file_path=str(apk_file),
            release_notes="Test release",
            rollout_percentage=100.0,
        )

        # Verify
        assert result.success is True
        assert result.version_code == 100
        assert result.track == "internal"
        assert "Successfully deployed" in result.message

    def test_deploy_aab_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test successful AAB deployment."""
        # Create test AAB file
        aab_file = tmp_path / "app.aab"
        aab_file.write_bytes(b"fake aab content")

        # Setup mocks
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.bundles.return_value.upload.return_value.execute.return_value = {
            "versionCode": 101
        }
        mock_edits.tracks.return_value.update.return_value.execute.return_value = {}
        mock_edits.commit.return_value.execute.return_value = {}

        # Execute
        result = client.deploy_app(
            package_name="com.example.app",
            track="beta",
            file_path=str(aab_file),
            rollout_percentage=50.0,
        )

        # Verify
        assert result.success is True
        assert result.version_code == 101

    def test_deploy_staged_rollout(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test deployment with staged rollout."""
        apk_file = tmp_path / "app.apk"
        apk_file.write_bytes(b"content")

        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.apks.return_value.upload.return_value.execute.return_value = {"versionCode": 100}
        mock_edits.tracks.return_value.update.return_value.execute.return_value = {}
        mock_edits.commit.return_value.execute.return_value = {}

        result = client.deploy_app(
            package_name="com.example.app",
            track="production",
            file_path=str(apk_file),
            rollout_percentage=10.0,
        )

        assert result.success is True

        # Verify the track update was called with inProgress status
        update_call = mock_edits.tracks.return_value.update.call_args
        body = update_call.kwargs["body"]
        assert body["releases"][0]["status"] == "inProgress"
        assert body["releases"][0]["userFraction"] == 0.1


class TestPromoteRelease:
    """Test promote_release method."""

    def test_promote_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test successful promotion."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.tracks.return_value.get.return_value.execute.return_value = {
            "track": "beta",
            "releases": [
                {
                    "versionCodes": ["100"],
                    "name": "1.0.0",
                    "releaseNotes": [{"language": "en-US", "text": "Notes"}],
                }
            ],
        }
        mock_edits.tracks.return_value.update.return_value.execute.return_value = {}
        mock_edits.commit.return_value.execute.return_value = {}

        result = client.promote_release(
            package_name="com.example.app",
            from_track="beta",
            to_track="production",
            version_code=100,
        )

        assert result.success is True
        assert result.track == "production"
        assert "Successfully promoted" in result.message

    def test_promote_version_not_found(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test promotion with nonexistent version."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.tracks.return_value.get.return_value.execute.return_value = {
            "track": "beta",
            "releases": [{"versionCodes": ["99"]}],
        }
        mock_edits.delete.return_value.execute.return_value = None

        result = client.promote_release(
            package_name="com.example.app",
            from_track="beta",
            to_track="production",
            version_code=100,
        )

        assert result.success is False
        assert "not found" in result.message


class TestReviews:
    """Test review methods."""

    def test_get_reviews_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        sample_reviews_response: dict[str, Any],
    ) -> None:
        """Test fetching reviews."""
        _mock_service.reviews.return_value.list.return_value.execute.return_value = (
            sample_reviews_response
        )

        reviews = client.get_reviews("com.example.app")

        assert len(reviews) == 2
        assert reviews[0].review_id == "review-123"
        assert reviews[0].star_rating == 5
        assert reviews[0].comment == "Great app!"
        assert reviews[1].developer_reply == "Thanks for the feedback!"

    def test_reply_to_review_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test replying to a review."""
        _mock_service.reviews.return_value.reply.return_value.execute.return_value = {}

        result = client.reply_to_review(
            package_name="com.example.app",
            review_id="review-123",
            reply_text="Thank you!",
        )

        assert result.success is True
        assert result.review_id == "review-123"


class TestSubscriptions:
    """Test subscription methods."""

    def test_list_subscriptions_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        sample_subscriptions_response: dict[str, Any],
    ) -> None:
        """Test listing subscriptions."""
        _mock_service.monetization.return_value.subscriptions.return_value.list.return_value.execute.return_value = sample_subscriptions_response

        subscriptions = client.list_subscriptions("com.example.app")

        assert len(subscriptions) == 2
        assert subscriptions[0].product_id == "premium_monthly"
        assert subscriptions[1].product_id == "premium_yearly"


class TestDeployAppMultilang:
    """Test deploy_app with multi-language release notes."""

    def test_deploy_with_multilang_notes(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test deployment with multi-language release notes."""
        apk_file = tmp_path / "app.apk"
        apk_file.write_bytes(b"content")

        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.apks.return_value.upload.return_value.execute.return_value = {"versionCode": 100}
        mock_edits.tracks.return_value.update.return_value.execute.return_value = {}
        mock_edits.commit.return_value.execute.return_value = {}

        release_notes = {
            "en-US": "Bug fixes and improvements",
            "es-ES": "Corrección de errores y mejoras",
            "fr-FR": "Corrections de bugs et améliorations",
        }

        result = client.deploy_app(
            package_name="com.example.app",
            track="production",
            file_path=str(apk_file),
            release_notes=release_notes,
            rollout_percentage=100.0,
        )

        assert result.success is True

        # Verify the track update was called with multi-language notes
        update_call = mock_edits.tracks.return_value.update.call_args
        body = update_call.kwargs["body"]
        notes = body["releases"][0]["releaseNotes"]
        assert len(notes) == 3
        assert any(n["language"] == "en-US" for n in notes)
        assert any(n["language"] == "es-ES" for n in notes)
        assert any(n["language"] == "fr-FR" for n in notes)


class TestInAppProducts:
    """Test in-app products methods."""

    def test_list_in_app_products_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test listing in-app products."""
        _mock_service.inappproducts.return_value.list.return_value.execute.return_value = {
            "inappproduct": [
                {
                    "sku": "premium_upgrade",
                    "purchaseType": "managedProduct",
                    "status": "active",
                    "defaultLanguage": "en-US",
                    "listings": {
                        "en-US": {
                            "title": "Premium Upgrade",
                            "description": "Unlock all features",
                        }
                    },
                    "defaultPrice": {
                        "currency": "USD",
                        "priceMicros": "4990000",
                    },
                },
                {
                    "sku": "remove_ads",
                    "purchaseType": "managedProduct",
                    "status": "active",
                    "defaultLanguage": "en-US",
                    "listings": {
                        "en-US": {
                            "title": "Remove Ads",
                            "description": "Remove all advertisements",
                        }
                    },
                },
            ]
        }

        products = client.list_in_app_products("com.example.app")

        assert len(products) == 2
        assert products[0].sku == "premium_upgrade"
        assert products[0].title == "Premium Upgrade"
        assert products[0].default_price is not None
        assert products[1].sku == "remove_ads"

    def test_get_in_app_product_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test getting a specific in-app product."""
        _mock_service.inappproducts.return_value.get.return_value.execute.return_value = {
            "sku": "premium_upgrade",
            "purchaseType": "managedProduct",
            "status": "active",
            "defaultLanguage": "en-US",
            "listings": {
                "en-US": {
                    "title": "Premium Upgrade",
                    "description": "Unlock all features",
                }
            },
            "defaultPrice": {
                "currency": "USD",
                "priceMicros": "4990000",
            },
        }

        product = client.get_in_app_product("com.example.app", "premium_upgrade")

        assert product.sku == "premium_upgrade"
        assert product.title == "Premium Upgrade"
        assert product.status == "active"


class TestVitalsMetrics:
    """Test vitals metrics methods."""

    def test_get_vitals_metrics(
        self,
        client: PlayStoreClient,
    ) -> None:
        """Test getting vitals metrics."""
        metrics = client.get_vitals_metrics("com.example.app", "crashRate")

        assert len(metrics) > 0
        assert metrics[0].metric_type == "crashRate"
        # Note: This is a placeholder implementation
        assert "Requires Play Developer Reporting API" in str(metrics[0].dimension_value)
