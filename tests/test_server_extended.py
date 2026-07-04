"""Extended tests for server.py — covers MCP tool handlers and lifespan."""

from __future__ import annotations

import base64
import json
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
    ValidationResult,
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


def test_server_uses_fastmcp_and_registers_all_tools() -> None:
    """The server is built on the standalone fastmcp package with all 117 tools."""
    import asyncio

    import fastmcp

    from play_store_mcp import server

    assert isinstance(server.mcp, fastmcp.FastMCP)
    tools = asyncio.run(server.mcp.list_tools())  # Sequence[Tool]
    assert len(tools) == 117


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock PlayStoreClient."""
    return MagicMock(spec=PlayStoreClient)


@pytest.fixture
def tmp_apk(tmp_path: Any) -> str:
    """Create a temporary APK file for deploy tests."""
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"fake apk")
    return str(apk)


@pytest.fixture
def tmp_aab(tmp_path: Any) -> str:
    """Create a temporary AAB file for deploy tests."""
    aab = tmp_path / "app.aab"
    aab.write_bytes(b"fake aab")
    return str(aab)


@pytest.fixture(autouse=True)
def _patch_mcp_context(mock_client: MagicMock, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Route get_client_from_context to the mock client for tool tests."""
    from play_store_mcp import server

    monkeypatch.setattr(server, "get_http_headers", dict)
    monkeypatch.setitem(server._shared_state, "client", mock_client)
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
                assert "client" in ctx
                # Client should be None on failure
                assert ctx["client"] is None


# =========================================================================
# Publishing tools
# =========================================================================


class TestDeployAppTool:
    """Test deploy_app server tool."""

    def test_deploy_app(self, mock_client: MagicMock, tmp_apk: str) -> None:
        """Test deploy_app tool."""
        mock_client.deploy_app.return_value = DeploymentResult(
            success=True,
            package_name="com.example.app",
            track="internal",
            version_code=100,
            message="Deployed",
        )

        result = deploy_app("com.example.app", "internal", tmp_apk)

        mock_client.deploy_app.assert_called_once_with(
            package_name="com.example.app",
            track="internal",
            file_path=tmp_apk,
            release_notes=None,
            release_notes_language="en-US",
            rollout_percentage=100.0,
        )
        assert result["success"] is True
        assert result["version_code"] == 100

    def test_deploy_app_multilang(self, mock_client: MagicMock, tmp_aab: str) -> None:
        """Test deploy_app_multilang tool."""
        mock_client.deploy_app.return_value = DeploymentResult(
            success=True,
            package_name="com.example.app",
            track="beta",
            version_code=101,
            message="Deployed",
        )

        notes = {"en-US": "Notes", "es-ES": "Notas"}
        result = deploy_app_multilang(
            "com.example.app",
            "beta",
            tmp_aab,
            notes,
        )

        mock_client.deploy_app.assert_called_once_with(
            package_name="com.example.app",
            track="beta",
            file_path=tmp_aab,
            release_notes=notes,
            rollout_percentage=100.0,
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

        mock_client.promote_release.assert_called_once_with(
            package_name="com.example.app",
            from_track="beta",
            to_track="production",
            version_code=100,
            rollout_percentage=100.0,
        )
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

        mock_client.get_releases.assert_called_once_with("com.example.app")
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

        mock_client.halt_release.assert_called_once_with(
            package_name="com.example.app",
            track="production",
            version_code=100,
        )
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

        mock_client.update_rollout.assert_called_once_with(
            package_name="com.example.app",
            track="production",
            version_code=100,
            rollout_percentage=50.0,
        )
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

        mock_client.get_app_details.assert_called_once_with("com.example.app", "en-US")
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

        mock_client.get_reviews.assert_called_once_with(
            package_name="com.example.app",
            max_results=50,
            translation_language=None,
        )
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

        mock_client.reply_to_review.assert_called_once_with(
            package_name="com.example.app",
            review_id="r1",
            reply_text="Thanks!",
        )
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

        mock_client.list_subscriptions.assert_called_once_with("com.example.app")
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

        mock_client.get_subscription_purchase.assert_called_once_with(
            package_name="com.example.app",
            subscription_id="premium",
            token="tok123",
        )
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

        mock_client.list_voided_purchases.assert_called_once_with(
            package_name="com.example.app",
            max_results=100,
        )
        assert len(result) == 1


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

        mock_client.list_in_app_products.assert_called_once_with("com.example.app")
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

        mock_client.get_in_app_product.assert_called_once_with("com.example.app", "premium")
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

        mock_client.get_listing.assert_called_once_with("com.example.app", "en-US")
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

        mock_client.update_listing.assert_called_once_with(
            package_name="com.example.app",
            language="en-US",
            title="New Title",
            full_description=None,
            short_description=None,
            video=None,
        )
        assert result["success"] is True

    def test_list_all_listings(self, mock_client: MagicMock) -> None:
        """Test list_all_listings tool."""
        mock_client.list_all_listings.return_value = [
            Listing(language="en-US", title="My App"),
            Listing(language="es-ES", title="Mi App"),
        ]

        result = list_all_listings("com.example.app")

        mock_client.list_all_listings.assert_called_once_with("com.example.app")
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
            google_groups=["test@example.com"],
        )

        result = get_testers("com.example.app", "beta")

        mock_client.get_testers.assert_called_once_with("com.example.app", "beta")
        assert len(result["google_groups"]) == 1

    def test_update_testers(self, mock_client: MagicMock) -> None:
        """Test update_testers tool."""
        mock_client.update_testers.return_value = {
            "success": True,
            "package_name": "com.example.app",
            "track": "beta",
            "message": "Updated",
        }

        result = update_testers("com.example.app", "beta", ["test@example.com"])

        mock_client.update_testers.assert_called_once_with(
            "com.example.app", "beta", ["test@example.com"]
        )
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

        mock_client.get_order.assert_called_once_with("com.example.app", "order-123")
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

        mock_client.get_expansion_file.assert_called_once_with("com.example.app", 100, "main")
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

        mock_client.validate_package_name.assert_called_once_with("com.example.app")
        assert result["valid"] is True
        assert result["errors"] == []

    def test_validate_package_name_invalid(self, mock_client: MagicMock) -> None:
        """Test validate_package_name with invalid name."""
        mock_client.validate_package_name.return_value = [
            ValidationResult(field="package_name", message="Bad name", value="bad")
        ]

        result = validate_package_name("bad")

        mock_client.validate_package_name.assert_called_once_with("bad")
        assert result["valid"] is False
        assert len(result["errors"]) == 1

    def test_validate_track_valid(self, mock_client: MagicMock) -> None:
        """Test validate_track with valid track."""
        mock_client.validate_track.return_value = []

        result = validate_track("production")

        mock_client.validate_track.assert_called_once_with("production")
        assert result["valid"] is True

    def test_validate_listing_text(self, mock_client: MagicMock) -> None:
        """Test validate_listing_text."""
        mock_client.validate_listing_text.return_value = []

        result = validate_listing_text(title="My App")

        mock_client.validate_listing_text.assert_called_once_with("My App", None, None)
        assert result["valid"] is True


# =========================================================================
# Batch deploy tool
# =========================================================================


class TestBatchDeployTool:
    """Test batch_deploy server tool."""

    def test_batch_deploy(self, mock_client: MagicMock, tmp_apk: str) -> None:
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
            tmp_apk,
            ["internal", "alpha"],
        )

        mock_client.batch_deploy.assert_called_once_with(
            package_name="com.example.app",
            file_path=tmp_apk,
            tracks=["internal", "alpha"],
            release_notes=None,
            rollout_percentages=None,
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

        mock_client.get_subscription_purchase.assert_called_once_with(
            package_name="com.example.app",
            subscription_id="sub1",
            token="tok",
        )
        assert result["subscription_id"] == "sub1"


# =========================================================================
# get_client_from_context — header-based credentials
# =========================================================================


class TestGetClientFromContext:
    """get_client_from_context resolves per-request headers, then the shared client."""

    def test_json_header_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from play_store_mcp import server

        monkeypatch.setattr(
            server,
            "get_http_headers",
            lambda: {"x-google-credentials": '{"type": "service_account"}'},
        )
        created = {}

        def fake_client(credentials_json=None):
            created["creds"] = credentials_json
            return "CLIENT"

        monkeypatch.setattr(server, "PlayStoreClient", fake_client)
        assert server.get_client_from_context() == "CLIENT"
        assert created["creds"] == {"type": "service_account"}

    def test_invalid_json_header_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from play_store_mcp import server

        monkeypatch.setattr(
            server, "get_http_headers", lambda: {"x-google-credentials": "not-json"}
        )
        with pytest.raises(server.PlayStoreClientError, match="Invalid JSON"):
            server.get_client_from_context()

    def test_base64_header_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from play_store_mcp import server

        b64 = base64.b64encode(b'{"type":"service_account"}').decode()
        monkeypatch.setattr(
            server, "get_http_headers", lambda: {"x-google-credentials-base64": b64}
        )
        created = {}

        def fake_client(credentials_json=None):
            created["creds"] = credentials_json
            return "CLIENT"

        monkeypatch.setattr(server, "PlayStoreClient", fake_client)
        assert server.get_client_from_context() == "CLIENT"
        assert created["creds"] == {"type": "service_account"}

    def test_invalid_base64_header_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from play_store_mcp import server

        monkeypatch.setattr(
            server,
            "get_http_headers",
            lambda: {"x-google-credentials-base64": "!!!not-base64!!!"},
        )
        with pytest.raises(server.PlayStoreClientError, match="Invalid base64 or JSON"):
            server.get_client_from_context()

    def test_falls_back_to_shared_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from play_store_mcp import server

        monkeypatch.setattr(server, "get_http_headers", dict)
        monkeypatch.setitem(server._shared_state, "client", "SHARED")
        assert server.get_client_from_context() == "SHARED"

    def test_no_credentials_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from play_store_mcp import server

        monkeypatch.setattr(server, "get_http_headers", dict)
        monkeypatch.setitem(server._shared_state, "client", None)
        with pytest.raises(server.PlayStoreClientError, match="No credentials"):
            server.get_client_from_context()


# =========================================================================
# Tool validation error returns
# =========================================================================


class TestToolValidationErrors:
    """Test that tools return {"error": ...} on validation failure."""

    def test_deploy_app_bad_extension(self, tmp_path: Any) -> None:
        """deploy_app rejects a non-apk/aab file."""
        bad = tmp_path / "app.txt"
        bad.write_text("x")

        result = deploy_app("com.example.app", "internal", str(bad))

        assert result["error"] == "file_path must be a .apk or .aab file"

    def test_deploy_app_file_not_found(self, tmp_path: Any) -> None:
        """deploy_app rejects a missing file."""
        missing = str(tmp_path / "missing.apk")

        result = deploy_app("com.example.app", "internal", missing)

        assert "File not found" in result["error"]

    def test_deploy_app_rollout_out_of_range(self, tmp_apk: str) -> None:
        """deploy_app rejects an out-of-range rollout percentage."""
        result = deploy_app("com.example.app", "internal", tmp_apk, rollout_percentage=150.0)

        assert result["error"] == "rollout_percentage must be between 0.0 and 100.0"

    def test_deploy_app_multilang_bad_extension(self, tmp_path: Any) -> None:
        """deploy_app_multilang rejects a non-apk/aab file."""
        bad = tmp_path / "app.txt"
        bad.write_text("x")

        result = deploy_app_multilang("com.example.app", "internal", str(bad), {"en-US": "notes"})

        assert result["error"] == "file_path must be a .apk or .aab file"

    def test_deploy_app_multilang_rollout_out_of_range(self, tmp_apk: str) -> None:
        """deploy_app_multilang rejects an out-of-range rollout percentage."""
        result = deploy_app_multilang(
            "com.example.app", "internal", tmp_apk, {"en-US": "notes"}, rollout_percentage=-1.0
        )

        assert result["error"] == "rollout_percentage must be between 0.0 and 100.0"

    def test_promote_release_rollout_out_of_range(self) -> None:
        """promote_release rejects an out-of-range rollout percentage."""
        result = promote_release("com.example.app", "beta", "production", 100, 200.0)

        assert result["error"] == "rollout_percentage must be between 0.0 and 100.0"

    def test_update_rollout_out_of_range(self) -> None:
        """update_rollout rejects an out-of-range rollout percentage."""
        result = update_rollout("com.example.app", "production", 100, 101.0)

        assert result["error"] == "rollout_percentage must be between 0.0 and 100.0"

    def test_batch_deploy_bad_extension(self, tmp_path: Any) -> None:
        """batch_deploy rejects a non-apk/aab file."""
        bad = tmp_path / "app.txt"
        bad.write_text("x")

        result = batch_deploy("com.example.app", str(bad), ["internal"])

        assert result["error"] == "file_path must be a .apk or .aab file"

    def test_batch_deploy_per_track_rollout_out_of_range(self, tmp_apk: str) -> None:
        """batch_deploy validates each per-track rollout percentage."""
        result = batch_deploy(
            "com.example.app",
            tmp_apk,
            ["internal", "alpha"],
            rollout_percentages={"internal": 50.0, "alpha": 150.0},
        )

        assert "alpha" in result["error"]
        assert "between 0.0 and 100.0" in result["error"]

    def test_batch_deploy_per_track_rollout_all_valid(
        self, mock_client: MagicMock, tmp_apk: str
    ) -> None:
        """batch_deploy proceeds when all per-track rollout percentages are valid."""
        mock_client.batch_deploy.return_value = BatchDeploymentResult(
            success=True,
            results=[],
            successful_count=2,
            failed_count=0,
            message="All good",
        )

        result = batch_deploy(
            "com.example.app",
            tmp_apk,
            ["internal", "alpha"],
            rollout_percentages={"internal": 50.0, "alpha": 100.0},
        )

        assert result["success"] is True
        mock_client.batch_deploy.assert_called_once_with(
            package_name="com.example.app",
            file_path=tmp_apk,
            tracks=["internal", "alpha"],
            release_notes=None,
            rollout_percentages={"internal": 50.0, "alpha": 100.0},
        )


# =========================================================================
# HTTP endpoints — health check and localhost enforcement
# =========================================================================


class TestHealthCheck:
    """Test the /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_check(self) -> None:
        """health_check returns a healthy status payload."""
        from play_store_mcp.server import health_check

        response = await health_check(MagicMock())

        assert response.status_code == 200
        data = json.loads(response.body)
        assert data["status"] == "healthy"
        assert data["service"] == "play-store-mcp"


class TestCredentialsEndpointExtra:
    """Additional /credentials endpoint branch coverage."""

    @pytest.mark.asyncio
    async def test_non_loopback_rejected(self) -> None:
        """A non-loopback client is rejected with 403."""
        from starlette.requests import Request

        from play_store_mcp.server import update_credentials

        mock_request = MagicMock(spec=Request)
        mock_request.client.host = "8.8.8.8"

        response = await update_credentials(mock_request)

        assert response.status_code == 403
        data = json.loads(response.body)
        assert data["success"] is False
        assert "localhost" in data["error"]

    @pytest.mark.asyncio
    async def test_no_client_host_rejected(self) -> None:
        """A request with no client (None host) is rejected with 403."""
        from starlette.requests import Request

        from play_store_mcp.server import update_credentials

        mock_request = MagicMock(spec=Request)
        mock_request.client = None

        response = await update_credentials(mock_request)

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_malformed_host_rejected(self) -> None:
        """A malformed host (invalid IP) hits the ValueError branch and is rejected."""
        from starlette.requests import Request

        from play_store_mcp.server import update_credentials

        mock_request = MagicMock(spec=Request)
        mock_request.client.host = "not-an-ip-address"

        response = await update_credentials(mock_request)

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_base64_invalid_decoded_json(self) -> None:
        """Base64 that decodes to invalid JSON returns 400."""
        from starlette.requests import Request

        from play_store_mcp.server import update_credentials

        # Valid base64 decoding to text that is not JSON.
        b64 = base64.b64encode(b"this is not json").decode("utf-8")
        mock_request = MagicMock(spec=Request)
        mock_request.client.host = "127.0.0.1"
        mock_request.json = AsyncMock(return_value={"credentials_base64": b64})

        response = await update_credentials(mock_request)

        assert response.status_code == 400
        data = json.loads(response.body)
        assert data["success"] is False
        assert "base64-decoded" in data["error"]

    @pytest.mark.asyncio
    async def test_generic_exception_returns_500(self) -> None:
        """An unexpected error inside the handler returns 500."""
        from starlette.requests import Request

        from play_store_mcp.server import update_credentials

        mock_request = MagicMock(spec=Request)
        mock_request.client.host = "127.0.0.1"
        # Raise a non-JSONDecodeError to hit the generic Exception handler.
        mock_request.json = AsyncMock(side_effect=RuntimeError("boom"))

        response = await update_credentials(mock_request)

        assert response.status_code == 500
        data = json.loads(response.body)
        assert data["success"] is False
        # Generic message; the raw exception detail must not leak to the client.
        assert data["error"] == "Internal server error"
        assert "boom" not in data["error"]

    @pytest.mark.asyncio
    async def test_success_updates_module_shared_state(self) -> None:
        """A successful update writes the new client into module-level _shared_state."""
        from starlette.requests import Request

        from play_store_mcp import server
        from play_store_mcp.server import update_credentials

        creds = {"type": "service_account", "project_id": "test"}

        with patch("play_store_mcp.client.PlayStoreClient._get_service") as mock_service:
            mock_service.return_value = MagicMock()

            mock_request = MagicMock(spec=Request)
            mock_request.client.host = "127.0.0.1"
            mock_request.json = AsyncMock(return_value={"credentials": creds})

            response = await update_credentials(mock_request)

        assert response.status_code == 200
        data = json.loads(response.body)
        assert data["success"] is True
        assert server._shared_state["credentials_updated"] is True
        assert server._shared_state["client"] is not None


# =========================================================================
# main() entry point branches
# =========================================================================


class TestMainEntryPoint:
    """Test main() argument handling branches."""

    def test_main_sets_credentials_env(self, monkeypatch: Any) -> None:
        """--credentials sets GOOGLE_PLAY_STORE_CREDENTIALS."""
        from play_store_mcp.server import main

        monkeypatch.delenv("GOOGLE_PLAY_STORE_CREDENTIALS", raising=False)

        with patch.object(mcp, "run") as mock_run:
            main(["--credentials", "/path/to/creds.json"])

        assert os.environ["GOOGLE_PLAY_STORE_CREDENTIALS"] == "/path/to/creds.json"
        mock_run.assert_called_once()

    def test_main_network_transport_sets_host_port(self, monkeypatch: Any) -> None:
        """A network transport sets mcp.settings.host and port."""
        from play_store_mcp.server import main

        monkeypatch.delenv("GOOGLE_PLAY_STORE_CREDENTIALS", raising=False)

        orig_host = mcp.settings.host
        orig_port = mcp.settings.port
        try:
            with patch.object(mcp, "run") as mock_run:
                main(["--transport", "streamable-http", "--host", "192.168.1.10", "--port", "9999"])

            assert mcp.settings.host == "192.168.1.10"
            assert mcp.settings.port == 9999
            mock_run.assert_called_once_with(transport="streamable-http")
        finally:
            mcp.settings.host = orig_host
            mcp.settings.port = orig_port
