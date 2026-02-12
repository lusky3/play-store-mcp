"""Extended tests for server.py — covers MCP tool handlers and lifespan."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import (
    AppDetails,
    BatchDeploymentResult,
    DeploymentResult,
    ExpansionFile,
    InAppProduct,
    Listing,
    ListingUpdateResult,
    Order,
    Release,
    Review,
    ReviewReplyResult,
    SubscriptionProduct,
    SubscriptionPurchase,
    TesterInfo,
    TrackInfo,
    ValidationError,
    VitalsMetric,
    VitalsOverview,
    VoidedPurchase,
)
from play_store_mcp.server import (
    batch_deploy,
    deploy_app,
    deploy_app_multilang,
    get_app_details,
    get_expansion_file,
    get_in_app_product,
    get_listing,
    get_order,
    get_releases,
    get_reviews,
    get_testers,
    get_vitals_metrics,
    get_vitals_overview,
    halt_release,
    list_all_listings,
    list_in_app_products,
    list_subscriptions,
    list_voided_purchases,
    mcp,
    promote_release,
    reply_to_review,
    update_listing,
    update_rollout,
    update_testers,
    validate_listing_text,
    validate_package_name,
    validate_track,
)


def _mock_context(client: MagicMock) -> MagicMock:
    """Create a mock MCP context with the given client."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"client": client}
    return ctx


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock PlayStoreClient."""
    return MagicMock(spec=PlayStoreClient)


@pytest.fixture(autouse=True)
def _patch_mcp_context(mock_client: MagicMock) -> Any:
    """Patch mcp.get_context to return our mock client."""
    ctx = _mock_context(mock_client)
    with patch.object(mcp, "get_context", return_value=ctx):
        yield


# =========================================================================
# Lifespan
# =========================================================================


class TestLifespan:
    """Test server lifespan."""

    @pytest.mark.asyncio
    async def test_lifespan_success(self) -> None:
        """Test successful lifespan initialization."""
        from play_store_mcp.server import lifespan

        mock_server = MagicMock()

        with (
            patch("play_store_mcp.server.PlayStoreClient") as MockClient,
            patch("play_store_mcp.server.PlayStoreClientError", PlayStoreClientError),
        ):
            instance = MockClient.return_value
            instance._get_service.return_value = MagicMock()

            async with lifespan(mock_server) as ctx:
                assert "client" in ctx
                assert ctx["client"] is instance

    @pytest.mark.asyncio
    async def test_lifespan_credentials_failure(self) -> None:
        """Test lifespan when credentials fail."""
        from play_store_mcp.server import lifespan

        mock_server = MagicMock()

        with (
            patch("play_store_mcp.server.PlayStoreClient") as MockClient,
            patch("play_store_mcp.server.PlayStoreClientError", PlayStoreClientError),
        ):
            instance = MockClient.return_value
            instance._get_service.side_effect = PlayStoreClientError("bad creds")

            async with lifespan(mock_server) as ctx:
                # Should still yield a client even on failure
                assert "client" in ctx


# =========================================================================
# Publishing tools
# =========================================================================


class TestDeployAppTool:
    """Test deploy_app server tool."""

    def test_deploy_app(self, mock_client: MagicMock) -> None:
        """Test deploy_app tool."""
        mock_client.deploy_app.return_value = DeploymentResult(
            success=True,
            package_name="com.example.app",
            track="internal",
            version_code=100,
            message="Deployed",
        )

        result = deploy_app("com.example.app", "internal", "/path/to/app.apk")

        assert result["success"] is True
        assert result["version_code"] == 100

    def test_deploy_app_multilang(self, mock_client: MagicMock) -> None:
        """Test deploy_app_multilang tool."""
        mock_client.deploy_app.return_value = DeploymentResult(
            success=True,
            package_name="com.example.app",
            track="beta",
            version_code=101,
            message="Deployed",
        )

        result = deploy_app_multilang(
            "com.example.app",
            "beta",
            "/path/to/app.aab",
            {"en-US": "Notes", "es-ES": "Notas"},
        )

        assert result["success"] is True


class TestPromoteReleaseTool:
    """Test promote_release server tool."""

    def test_promote_release(self, mock_client: MagicMock) -> None:
        """Test promote_release tool."""
        mock_client.promote_release.return_value = DeploymentResult(
            success=True,
            package_name="com.example.app",
            track="production",
            version_code=100,
            message="Promoted",
        )

        result = promote_release("com.example.app", "beta", "production", 100)

        assert result["success"] is True


class TestGetReleasesTool:
    """Test get_releases server tool."""

    def test_get_releases(self, mock_client: MagicMock) -> None:
        """Test get_releases tool."""
        mock_client.get_releases.return_value = [
            TrackInfo(
                track="production",
                releases=[
                    Release(
                        package_name="com.example.app",
                        track="production",
                        status="completed",
                        version_codes=[100],
                    )
                ],
            )
        ]

        result = get_releases("com.example.app")

        assert len(result) == 1
        assert result[0]["track"] == "production"


class TestHaltReleaseTool:
    """Test halt_release server tool."""

    def test_halt_release(self, mock_client: MagicMock) -> None:
        """Test halt_release tool."""
        mock_client.halt_release.return_value = DeploymentResult(
            success=True,
            package_name="com.example.app",
            track="production",
            version_code=100,
            message="Halted",
        )

        result = halt_release("com.example.app", "production", 100)

        assert result["success"] is True


class TestUpdateRolloutTool:
    """Test update_rollout server tool."""

    def test_update_rollout(self, mock_client: MagicMock) -> None:
        """Test update_rollout tool."""
        mock_client.update_rollout.return_value = DeploymentResult(
            success=True,
            package_name="com.example.app",
            track="production",
            version_code=100,
            message="Updated",
        )

        result = update_rollout("com.example.app", "production", 100, 50.0)

        assert result["success"] is True


class TestGetAppDetailsTool:
    """Test get_app_details server tool."""

    def test_get_app_details(self, mock_client: MagicMock) -> None:
        """Test get_app_details tool."""
        mock_client.get_app_details.return_value = AppDetails(
            package_name="com.example.app",
            title="My App",
        )

        result = get_app_details("com.example.app")

        assert result["title"] == "My App"


# =========================================================================
# Reviews tools
# =========================================================================


class TestReviewsTools:
    """Test review server tools."""

    def test_get_reviews(self, mock_client: MagicMock) -> None:
        """Test get_reviews tool."""
        mock_client.get_reviews.return_value = [
            Review(
                review_id="r1",
                author_name="User",
                star_rating=5,
                comment="Great!",
                language="en",
            )
        ]

        result = get_reviews("com.example.app")

        assert len(result) == 1
        assert result[0]["star_rating"] == 5

    def test_get_reviews_with_options(self, mock_client: MagicMock) -> None:
        """Test get_reviews with max_results and translation."""
        mock_client.get_reviews.return_value = []

        result = get_reviews("com.example.app", max_results=10, translation_language="es")

        assert result == []
        mock_client.get_reviews.assert_called_once_with(
            package_name="com.example.app",
            max_results=10,
            translation_language="es",
        )

    def test_get_reviews_caps_at_100(self, mock_client: MagicMock) -> None:
        """Test that max_results is capped at 100."""
        mock_client.get_reviews.return_value = []

        get_reviews("com.example.app", max_results=200)

        mock_client.get_reviews.assert_called_once_with(
            package_name="com.example.app",
            max_results=100,
            translation_language=None,
        )

    def test_reply_to_review(self, mock_client: MagicMock) -> None:
        """Test reply_to_review tool."""
        mock_client.reply_to_review.return_value = ReviewReplyResult(
            success=True,
            review_id="r1",
            message="Replied",
        )

        result = reply_to_review("com.example.app", "r1", "Thanks!")

        assert result["success"] is True


# =========================================================================
# Subscription tools
# =========================================================================


class TestSubscriptionTools:
    """Test subscription server tools."""

    def test_list_subscriptions(self, mock_client: MagicMock) -> None:
        """Test list_subscriptions tool."""
        mock_client.list_subscriptions.return_value = [
            SubscriptionProduct(
                product_id="premium",
                package_name="com.example.app",
            )
        ]

        result = list_subscriptions("com.example.app")

        assert len(result) == 1
        assert result[0]["product_id"] == "premium"

    def test_get_subscription_status(self, mock_client: MagicMock) -> None:
        """Test get_subscription_status tool."""
        from play_store_mcp.server import get_subscription_status

        mock_client.get_subscription_purchase.return_value = SubscriptionPurchase(
            package_name="com.example.app",
            subscription_id="premium",
            purchase_token="tok123",
            auto_renewing=True,
        )

        result = get_subscription_status("com.example.app", "premium", "tok123")

        assert result["auto_renewing"] is True

    def test_list_voided_purchases(self, mock_client: MagicMock) -> None:
        """Test list_voided_purchases tool."""
        mock_client.list_voided_purchases.return_value = [
            VoidedPurchase(
                package_name="com.example.app",
                purchase_token="tok1",
            )
        ]

        result = list_voided_purchases("com.example.app")

        assert len(result) == 1


# =========================================================================
# Vitals tools
# =========================================================================


class TestVitalsTools:
    """Test vitals server tools."""

    def test_get_vitals_overview(self, mock_client: MagicMock) -> None:
        """Test get_vitals_overview tool."""
        mock_client.get_vitals_overview.return_value = VitalsOverview(
            package_name="com.example.app",
            crash_rate=0.5,
        )

        result = get_vitals_overview("com.example.app")

        assert result["crash_rate"] == 0.5

    def test_get_vitals_metrics(self, mock_client: MagicMock) -> None:
        """Test get_vitals_metrics tool."""
        mock_client.get_vitals_metrics.return_value = [
            VitalsMetric(metric_type="crashRate", value=0.5)
        ]

        result = get_vitals_metrics("com.example.app")

        assert len(result) == 1
        assert result[0]["metric_type"] == "crashRate"


# =========================================================================
# In-App Products tools
# =========================================================================


class TestInAppProductsTools:
    """Test in-app products server tools."""

    def test_list_in_app_products(self, mock_client: MagicMock) -> None:
        """Test list_in_app_products tool."""
        mock_client.list_in_app_products.return_value = [
            InAppProduct(
                sku="premium",
                package_name="com.example.app",
                product_type="managedProduct",
            )
        ]

        result = list_in_app_products("com.example.app")

        assert len(result) == 1

    def test_get_in_app_product(self, mock_client: MagicMock) -> None:
        """Test get_in_app_product tool."""
        mock_client.get_in_app_product.return_value = InAppProduct(
            sku="premium",
            package_name="com.example.app",
            product_type="managedProduct",
            title="Premium",
        )

        result = get_in_app_product("com.example.app", "premium")

        assert result["title"] == "Premium"


# =========================================================================
# Store Listings tools
# =========================================================================


class TestListingsTools:
    """Test store listings server tools."""

    def test_get_listing(self, mock_client: MagicMock) -> None:
        """Test get_listing tool."""
        mock_client.get_listing.return_value = Listing(
            language="en-US",
            title="My App",
        )

        result = get_listing("com.example.app")

        assert result["title"] == "My App"

    def test_update_listing(self, mock_client: MagicMock) -> None:
        """Test update_listing tool."""
        mock_client.update_listing.return_value = ListingUpdateResult(
            success=True,
            package_name="com.example.app",
            language="en-US",
            message="Updated",
        )

        result = update_listing("com.example.app", "en-US", title="New Title")

        assert result["success"] is True

    def test_list_all_listings(self, mock_client: MagicMock) -> None:
        """Test list_all_listings tool."""
        mock_client.list_all_listings.return_value = [
            Listing(language="en-US", title="My App"),
            Listing(language="es-ES", title="Mi App"),
        ]

        result = list_all_listings("com.example.app")

        assert len(result) == 2


# =========================================================================
# Testers tools
# =========================================================================


class TestTestersTools:
    """Test testers server tools."""

    def test_get_testers(self, mock_client: MagicMock) -> None:
        """Test get_testers tool."""
        mock_client.get_testers.return_value = TesterInfo(
            track="beta",
            tester_emails=["test@example.com"],
        )

        result = get_testers("com.example.app", "beta")

        assert len(result["tester_emails"]) == 1

    def test_update_testers(self, mock_client: MagicMock) -> None:
        """Test update_testers tool."""
        mock_client.update_testers.return_value = ListingUpdateResult(
            success=True,
            package_name="com.example.app",
            language="beta",
            message="Updated",
        )

        result = update_testers("com.example.app", "beta", ["test@example.com"])

        assert result["success"] is True


# =========================================================================
# Orders tools
# =========================================================================


class TestOrdersTools:
    """Test orders server tools."""

    def test_get_order(self, mock_client: MagicMock) -> None:
        """Test get_order tool."""
        mock_client.get_order.return_value = Order(
            order_id="order-123",
            package_name="com.example.app",
            product_id="premium",
        )

        result = get_order("com.example.app", "order-123")

        assert result["order_id"] == "order-123"


# =========================================================================
# Expansion Files tools
# =========================================================================


class TestExpansionFilesTools:
    """Test expansion files server tools."""

    def test_get_expansion_file(self, mock_client: MagicMock) -> None:
        """Test get_expansion_file tool."""
        mock_client.get_expansion_file.return_value = ExpansionFile(
            version_code=100,
            expansion_file_type="main",
            file_size=104857600,
        )

        result = get_expansion_file("com.example.app", 100)

        assert result["file_size"] == 104857600


# =========================================================================
# Validation tools
# =========================================================================


class TestValidationTools:
    """Test validation server tools."""

    def test_validate_package_name_valid(self, mock_client: MagicMock) -> None:
        """Test validate_package_name with valid name."""
        mock_client.validate_package_name.return_value = []

        result = validate_package_name("com.example.app")

        assert result["valid"] is True
        assert result["errors"] == []

    def test_validate_package_name_invalid(self, mock_client: MagicMock) -> None:
        """Test validate_package_name with invalid name."""
        mock_client.validate_package_name.return_value = [
            ValidationError(field="package_name", message="Bad name", value="bad")
        ]

        result = validate_package_name("bad")

        assert result["valid"] is False
        assert len(result["errors"]) == 1

    def test_validate_track_valid(self, mock_client: MagicMock) -> None:
        """Test validate_track with valid track."""
        mock_client.validate_track.return_value = []

        result = validate_track("production")

        assert result["valid"] is True

    def test_validate_listing_text(self, mock_client: MagicMock) -> None:
        """Test validate_listing_text."""
        mock_client.validate_listing_text.return_value = []

        result = validate_listing_text(title="My App")

        assert result["valid"] is True


# =========================================================================
# Batch deploy tool
# =========================================================================


class TestBatchDeployTool:
    """Test batch_deploy server tool."""

    def test_batch_deploy(self, mock_client: MagicMock) -> None:
        """Test batch_deploy tool."""
        mock_client.batch_deploy.return_value = BatchDeploymentResult(
            success=True,
            results=[],
            successful_count=2,
            failed_count=0,
            message="All good",
        )

        result = batch_deploy(
            "com.example.app",
            "/path/to/app.apk",
            ["internal", "alpha"],
        )

        assert result["success"] is True
        assert result["successful_count"] == 2


# =========================================================================
# Server main entry point
# =========================================================================


class TestServerMain:
    """Test server main function."""

    def test_main_calls_mcp_run(self) -> None:
        """Test that main() calls mcp.run()."""
        from play_store_mcp.server import main

        with patch.object(mcp, "run") as mock_run:
            main([])
            mock_run.assert_called_once()

    def test_get_subscription_status_tool(self, mock_client: MagicMock) -> None:
        """Test get_subscription_status tool."""
        from play_store_mcp.server import get_subscription_status

        mock_client.get_subscription_purchase.return_value = SubscriptionPurchase(
            package_name="com.example.app",
            subscription_id="sub1",
            purchase_token="tok",
        )

        result = get_subscription_status("com.example.app", "sub1", "tok")

        assert result["subscription_id"] == "sub1"
