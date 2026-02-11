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


class TestStoreListings:
    """Test store listings methods."""

    def test_get_listing_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test getting a store listing."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.listings.return_value.get.return_value.execute.return_value = {
            "title": "My Awesome App",
            "fullDescription": "This is a great app that does amazing things.",
            "shortDescription": "A great app",
            "video": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }
        mock_edits.delete.return_value.execute.return_value = None

        listing = client.get_listing("com.example.app", "en-US")

        assert listing.language == "en-US"
        assert listing.title == "My Awesome App"
        assert listing.full_description == "This is a great app that does amazing things."
        assert listing.short_description == "A great app"

    def test_update_listing_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test updating a store listing."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.listings.return_value.get.return_value.execute.return_value = {
            "title": "Old Title",
            "fullDescription": "Old description",
            "shortDescription": "Old short",
        }
        mock_edits.listings.return_value.update.return_value.execute.return_value = {}
        mock_edits.commit.return_value.execute.return_value = {}

        result = client.update_listing(
            package_name="com.example.app",
            language="en-US",
            title="New Title",
            short_description="New short description",
        )

        assert result.success is True
        assert result.language == "en-US"

    def test_list_all_listings_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test listing all store listings."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.listings.return_value.list.return_value.execute.return_value = {
            "listings": {
                "en-US": {
                    "title": "My App",
                    "fullDescription": "English description",
                    "shortDescription": "English short",
                },
                "es-ES": {
                    "title": "Mi Aplicación",
                    "fullDescription": "Descripción en español",
                    "shortDescription": "Corto en español",
                },
            }
        }
        mock_edits.delete.return_value.execute.return_value = None

        listings = client.list_all_listings("com.example.app")

        assert len(listings) == 2
        assert any(listing.language == "en-US" for listing in listings)
        assert any(listing.language == "es-ES" for listing in listings)


class TestTesters:
    """Test testers management methods."""

    def test_get_testers_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test getting testers for a track."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.testers.return_value.get.return_value.execute.return_value = {
            "googleGroups": ["testers@example.com", "beta-testers@example.com"]
        }
        mock_edits.delete.return_value.execute.return_value = None

        testers = client.get_testers("com.example.app", "beta")

        assert testers.track == "beta"
        assert len(testers.tester_emails) == 2
        assert "testers@example.com" in testers.tester_emails

    def test_update_testers_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test updating testers for a track."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.testers.return_value.update.return_value.execute.return_value = {}
        mock_edits.commit.return_value.execute.return_value = {}

        result = client.update_testers(
            package_name="com.example.app",
            track="alpha",
            tester_emails=["alpha-testers@example.com"],
        )

        assert result.success is True


class TestOrders:
    """Test orders methods."""

    def test_get_order_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test getting order details."""
        _mock_service.orders.return_value.get.return_value.execute.return_value = {
            "orderId": "GPA.1234-5678-9012-34567",
            "packageName": "com.example.app",
            "productId": "premium_upgrade",
            "purchaseState": 0,
            "purchaseToken": "token123",
        }

        order = client.get_order("com.example.app", "GPA.1234-5678-9012-34567")

        assert order.order_id == "GPA.1234-5678-9012-34567"
        assert order.product_id == "premium_upgrade"
        assert order.purchase_state == 0


class TestExpansionFiles:
    """Test expansion files methods."""

    def test_get_expansion_file_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test getting expansion file info."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.expansionfiles.return_value.get.return_value.execute.return_value = {
            "fileSize": 104857600,  # 100MB
            "referencesVersion": 100,
        }
        mock_edits.delete.return_value.execute.return_value = None

        expansion = client.get_expansion_file("com.example.app", 100, "main")

        assert expansion.version_code == 100
        assert expansion.expansion_file_type == "main"
        assert expansion.file_size == 104857600


class TestValidation:
    """Test validation methods."""

    def test_validate_package_name_valid(
        self,
        client: PlayStoreClient,
    ) -> None:
        """Test validating a valid package name."""
        errors = client.validate_package_name("com.example.myapp")
        assert len(errors) == 0

    def test_validate_package_name_invalid_no_dot(
        self,
        client: PlayStoreClient,
    ) -> None:
        """Test validating package name without dot."""
        errors = client.validate_package_name("myapp")
        assert len(errors) > 0
        assert any("dot" in e.message.lower() for e in errors)

    def test_validate_package_name_invalid_format(
        self,
        client: PlayStoreClient,
    ) -> None:
        """Test validating package name with invalid format."""
        errors = client.validate_package_name("Com.Example.MyApp")
        assert len(errors) > 0

    def test_validate_track_valid(
        self,
        client: PlayStoreClient,
    ) -> None:
        """Test validating valid track names."""
        for track in ["internal", "alpha", "beta", "production"]:
            errors = client.validate_track(track)
            assert len(errors) == 0

    def test_validate_track_invalid(
        self,
        client: PlayStoreClient,
    ) -> None:
        """Test validating invalid track name."""
        errors = client.validate_track("staging")
        assert len(errors) > 0

    def test_validate_listing_text_valid(
        self,
        client: PlayStoreClient,
    ) -> None:
        """Test validating valid listing text."""
        errors = client.validate_listing_text(
            title="My App",
            short_description="A great app",
            full_description="This is a comprehensive description.",
        )
        assert len(errors) == 0

    def test_validate_listing_text_title_too_long(
        self,
        client: PlayStoreClient,
    ) -> None:
        """Test validating title that's too long."""
        errors = client.validate_listing_text(title="A" * 51)
        assert len(errors) > 0
        assert any("title" in e.field.lower() for e in errors)


class TestBatchOperations:
    """Test batch operations."""

    def test_batch_deploy_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        tmp_path: Any,
    ) -> None:
        """Test batch deployment to multiple tracks."""
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
            tracks=["internal", "alpha"],
            release_notes="Test release",
        )

        assert result.success is True
        assert result.successful_count == 2
        assert result.failed_count == 0
        assert len(result.results) == 2
