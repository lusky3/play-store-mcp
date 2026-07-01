"""Tests for PlayStoreClient."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    pass

from play_store_mcp.client import PlayStoreClient, PlayStoreClientError


class TestPlayStoreClientInit:
    """Test client initialization."""

    def test_missing_credentials_raises_error(self) -> None:
        """Test that missing credentials raises an error."""
        client = PlayStoreClient(credentials_path="/nonexistent/path.json")

        with pytest.raises(PlayStoreClientError, match="No valid credentials found"):
            client._get_service()

    def test_no_credentials_env_var_raises_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that missing env var raises an error."""
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

        client = PlayStoreClient()

        with pytest.raises(PlayStoreClientError, match="No valid credentials found"):
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


class TestGetAppDetails:
    """Test get_app_details method."""

    def test_developer_name_is_not_website(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Bug: developer_name was incorrectly set to contactWebsite value."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.details.return_value.get.return_value.execute.return_value = {
            "defaultLanguage": "en-US",
            "contactEmail": "dev@example.com",
            "contactWebsite": "https://example.com",
        }
        mock_edits.listings.return_value.get.return_value.execute.return_value = {
            "title": "My App",
            "shortDescription": "Short",
            "fullDescription": "Full",
        }
        mock_edits.delete.return_value.execute.return_value = None

        details = client.get_app_details("com.example.app")

        assert details.developer_name is None
        assert details.developer_website == "https://example.com"
        assert details.developer_email == "dev@example.com"


class TestProductPurchases:
    """Test one-time in-app product purchase methods."""

    def test_consume_product_purchase_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Consumes a one-time in-app product purchase via the official API."""
        mock_products = _mock_service.purchases.return_value.products.return_value
        mock_products.consume.return_value.execute.return_value = {}

        result = client.consume_product_purchase(
            package_name="com.example.app",
            product_id="coins_100",
            token="purchase-token",
        )

        assert result.success is True
        assert result.package_name == "com.example.app"
        assert result.product_id == "coins_100"
        assert result.purchase_token == "purchase-token"
        mock_products.consume.assert_called_once_with(
            packageName="com.example.app",
            productId="coins_100",
            token="purchase-token",
        )


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


class TestVitalsStubs:
    """Verify vitals methods raise clear errors rather than returning fake data."""

    def test_get_vitals_overview_raises_not_implemented(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        with pytest.raises(PlayStoreClientError, match="Play Developer Reporting API"):
            client.get_vitals_overview("com.example.app")

    def test_get_vitals_metrics_raises_not_implemented(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        with pytest.raises(PlayStoreClientError, match="Play Developer Reporting API"):
            client.get_vitals_metrics("com.example.app", "crashRate")


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

    def test_batch_update_listings_dry_run_does_not_create_edit(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test dry-run validates multiple listings without creating an edit."""
        result = client.batch_update_listings(
            package_name="com.example.app",
            updates=[
                {"language": "en-US", "title": "New Title"},
                {"language": "es-ES", "short_description": "Nueva descripcion"},
            ],
        )

        assert result.success is True
        assert result.commit is False
        assert result.validated_languages == ["en-US", "es-ES"]
        _mock_service.edits.return_value.insert.assert_not_called()

    def test_batch_update_listings_validation_error_blocks_edit(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test invalid batch input fails before any edit is created."""
        result = client.batch_update_listings(
            package_name="com.example.app",
            updates=[{"language": "en-US", "title": "A" * 31}],
            commit=True,
        )

        assert result.success is False
        assert result.commit is False
        assert result.errors[0]["field"] == "title"
        _mock_service.edits.return_value.insert.assert_not_called()

    def test_batch_update_listings_commit_multiple_languages(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Test committing multiple locale listing updates in one edit."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.listings.return_value.get.return_value.execute.side_effect = [
            {
                "title": "Old Title",
                "fullDescription": "Old full",
                "shortDescription": "Old short",
                "video": "https://youtu.be/old",
            },
            {
                "title": "Titulo viejo",
                "fullDescription": "Descripcion vieja",
                "shortDescription": "Corta vieja",
            },
        ]
        mock_edits.listings.return_value.update.return_value.execute.return_value = {}
        mock_edits.commit.return_value.execute.return_value = {}

        result = client.batch_update_listings(
            package_name="com.example.app",
            updates=[
                {"language": "en-US", "title": "New Title"},
                {"language": "es-ES", "short_description": "Nueva corta"},
            ],
            commit=True,
        )

        assert result.success is True
        assert result.commit is True
        assert result.edit_id == "edit-123"
        assert result.updated_languages == ["en-US", "es-ES"]
        assert mock_edits.listings.return_value.update.call_count == 2
        first_update = mock_edits.listings.return_value.update.call_args_list[0].kwargs
        assert first_update["language"] == "en-US"
        assert first_update["body"]["title"] == "New Title"
        assert first_update["body"]["fullDescription"] == "Old full"
        assert first_update["body"]["shortDescription"] == "Old short"
        assert first_update["body"]["video"] == "https://youtu.be/old"
        second_update = mock_edits.listings.return_value.update.call_args_list[1].kwargs
        assert second_update["language"] == "es-ES"
        assert second_update["body"]["title"] == "Titulo viejo"
        assert second_update["body"]["shortDescription"] == "Nueva corta"
        mock_edits.commit.assert_called_once_with(packageName="com.example.app", editId="edit-123")


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


class TestUpdateTesters:
    """Test update_testers method."""

    def test_individual_emails_go_to_testers_field(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        """Bug: individual tester emails must go into 'testers', not 'googleGroups'."""
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.testers.return_value.update.return_value.execute.return_value = {}
        mock_edits.get.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.commit.return_value.execute.return_value = {}

        result = client.update_testers(
            package_name="com.example.app",
            track="alpha",
            tester_emails=["alice@example.com", "bob@example.com"],
            google_group_emails=[],
        )

        assert result.success is True
        call_kwargs = mock_edits.testers.return_value.update.call_args
        body = call_kwargs.kwargs["body"]
        assert body["testers"] == ["alice@example.com", "bob@example.com"]
        assert body["googleGroups"] == []

    def test_google_groups_go_to_googleGroups_field(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.testers.return_value.update.return_value.execute.return_value = {}
        mock_edits.get.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.commit.return_value.execute.return_value = {}

        result = client.update_testers(
            package_name="com.example.app",
            track="alpha",
            tester_emails=[],
            google_group_emails=["testers@example.com"],
        )

        assert result.success is True
        call_kwargs = mock_edits.testers.return_value.update.call_args
        body = call_kwargs.kwargs["body"]
        assert body["testers"] == []
        assert body["googleGroups"] == ["testers@example.com"]


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


class TestUploadDeobfuscationFile:
    """Test upload_deobfuscation_file method."""

    def test_upload_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        tmp_path: Any,
    ) -> None:
        mapping_file = tmp_path / "mapping.txt"
        mapping_file.write_text("obfuscated -> Original")

        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.deobfuscationfiles.return_value.upload.return_value.execute.return_value = {
            "deobfuscationFile": {"symbolType": "proguard"}
        }
        mock_edits.commit.return_value.execute.return_value = {}

        result = client.upload_deobfuscation_file(
            package_name="com.example.app",
            version_code=100,
            file_path=str(mapping_file),
            deobfuscation_file_type="proguard",
        )

        assert result.success is True
        assert result.version_code == 100
        assert result.deobfuscation_file_type == "proguard"

    def test_upload_file_not_found(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        result = client.upload_deobfuscation_file(
            package_name="com.example.app",
            version_code=100,
            file_path="/nonexistent/mapping.txt",
        )
        assert result.success is False
        assert "not found" in result.message.lower()


class TestListBundles:
    """Test list_bundles method."""

    def test_list_bundles_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.bundles.return_value.list.return_value.execute.return_value = {
            "bundles": [
                {"versionCode": 100, "sha1": "abc123", "sha256": "def456"},
                {"versionCode": 101, "sha1": "ghi789", "sha256": "jkl012"},
            ]
        }
        mock_edits.delete.return_value.execute.return_value = None

        bundles = client.list_bundles("com.example.app")

        assert len(bundles) == 2
        assert bundles[0].version_code == 100
        assert bundles[0].sha1 == "abc123"
        assert bundles[1].version_code == 101

    def test_list_bundles_empty(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.bundles.return_value.list.return_value.execute.return_value = {}
        mock_edits.delete.return_value.execute.return_value = None

        bundles = client.list_bundles("com.example.app")
        assert bundles == []


class TestListGeneratedApks:
    """Test list_generated_apks method."""

    def test_list_generated_apks_success(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
    ) -> None:
        mock_edits = _mock_service.edits.return_value
        mock_edits.insert.return_value.execute.return_value = {"id": "edit-123"}
        mock_edits.generatedapks.return_value.list.return_value.execute.return_value = {
            "generatedApks": [
                {
                    "downloadId": "download-abc",
                    "variantId": 1,
                    "targetSdkVersion": 33,
                    "minSdkVersion": 21,
                    "generatedSplitApks": [],
                    "generatedUniversalApk": {},
                }
            ]
        }
        mock_edits.delete.return_value.execute.return_value = None

        apks = client.list_generated_apks("com.example.app", bundle_version_code=100)

        assert len(apks) == 1
        assert apks[0].bundle_version_code == 100
        assert apks[0].download_id == "download-abc"
        assert apks[0].target_sdk_version == 33


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
        errors = client.validate_listing_text(title="A" * 31)
        assert len(errors) > 0
        assert any("title" in e.field.lower() for e in errors)

    def test_validate_listing_text_title_at_limit(
        self,
        client: PlayStoreClient,
    ) -> None:
        """Test validating title at the 30 character limit."""
        errors = client.validate_listing_text(title="A" * 30)
        assert len(errors) == 0


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


class TestBrowserStats:
    """Tests for browser-based stats methods (get_search_terms, get_acquisition_funnel)."""

    @pytest.fixture()
    def bare_client(self) -> PlayStoreClient:
        return PlayStoreClient(credentials_path="/nonexistent/path.json")

    def test_get_search_terms_success(self, bare_client: PlayStoreClient) -> None:
        # Response format from getAcquisitionDetailsTableData with dimension type 2 (search term).
        # "1" = outer wrapper; "3" = list of rows;
        # each row: "1"={"1":term_id,"2":display}, "2"={"1":visitors}, "3"={"1":installs}
        response = {
            "1": {
                "1": 2,
                "3": [
                    {"1": {"1": "puzzle game", "2": "puzzle game"}, "2": {"1": "120"}, "3": {"1": "42"}},
                    {"1": {"1": "brain teaser", "2": "brain teaser"}, "2": {"1": "60"}, "3": {"1": "15"}},
                    {"1": {"1": "word game", "2": "word game"}, "2": {"1": "95"}, "3": {"1": "28"}},
                ],
            }
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(response), stderr="")
            result = bare_client.get_search_terms(
                package_name="com.vast.jujubit",
                developer_id="6287361731679611511",
                app_id="4973755093875388037",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        assert result.package_name == "com.vast.jujubit"
        assert result.start_date == "2024-01-01"
        assert result.end_date == "2024-01-31"
        assert len(result.terms) == 3
        # Should be sorted by installs descending
        assert result.terms[0].term == "puzzle game"
        assert result.terms[0].installs == 42
        assert result.terms[0].store_listing_visitors == 120
        assert result.terms[1].term == "word game"
        assert result.terms[1].installs == 28
        assert result.terms[2].term == "brain teaser"
        assert result.terms[2].installs == 15

    def test_get_search_terms_empty(self, bare_client: PlayStoreClient) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps({}), stderr="")
            result = bare_client.get_search_terms(
                package_name="com.vast.jujubit",
                developer_id="123",
                app_id="456",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )
        assert result.terms == []

    def test_get_search_terms_browser_error(self, bare_client: PlayStoreClient) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps({"error": "Not logged into Play Console"}),
                stderr="",
            )
            with pytest.raises(PlayStoreClientError, match="Not logged into Play Console"):
                bare_client.get_search_terms(
                    package_name="com.vast.jujubit",
                    developer_id="123",
                    app_id="456",
                    start_date="2024-01-01",
                    end_date="2024-01-31",
                )

    def test_get_acquisition_funnel_success(self, bare_client: PlayStoreClient) -> None:
        # Response format from getAcquisitionSummary (live reverse-engineered):
        # "1" = traffic source array; "2" = conversion summary (visitors, installers, rate)
        response = {
            "1": [
                {"1": {"1": "@OVERALL@"}, "2": {"1": "22"}},
                {"1": {"1": "STORE_SEARCH", "2": "Google Play search"}, "2": {"1": "9"}},
                {"1": {"1": "STORE_BROWSE", "2": "Google Play explore"}, "2": {"1": "8"}},
                {"1": {"1": "DEEPLINK", "2": "Ads and referrals"}, "2": {"1": "5"}},
            ],
            "2": {
                "1": {"1": "177"},
                "2": {"1": "22"},
                "3": {"1": 0.12429378531073447},
            },
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(response), stderr="")
            result = bare_client.get_acquisition_funnel(
                package_name="com.vast.jujubit",
                developer_id="6287361731679611511",
                app_id="4973755093875388037",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        assert result.package_name == "com.vast.jujubit"
        # 2 funnel stages + 3 traffic source breakdown stages
        assert len(result.stages) == 5
        assert result.stages[0].stage == "store_listing_visitors"
        assert result.stages[0].value == 177
        assert result.stages[0].conversion_rate == 0.0
        assert result.stages[1].stage == "installers"
        assert result.stages[1].value == 22
        assert result.stages[1].conversion_rate == round(0.12429378531073447, 4)
        # Traffic source breakdown
        assert result.stages[2].stage == "src:search"
        assert result.stages[2].value == 9

    def test_get_acquisition_funnel_empty(self, bare_client: PlayStoreClient) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps({}), stderr="")
            result = bare_client.get_acquisition_funnel(
                package_name="com.vast.jujubit",
                developer_id="123",
                app_id="456",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )
        assert result.stages[0].stage == "store_listing_visitors"
        assert result.stages[0].value == 0

    def test_get_acquisition_funnel_browser_error(self, bare_client: PlayStoreClient) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps({"error": "Not logged into Play Console"}),
                stderr="",
            )
            with pytest.raises(PlayStoreClientError, match="Not logged into Play Console"):
                bare_client.get_acquisition_funnel(
                    package_name="com.vast.jujubit",
                    developer_id="123",
                    app_id="456",
                    start_date="2024-01-01",
                    end_date="2024-01-31",
                )
