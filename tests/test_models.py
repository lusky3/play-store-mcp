"""Tests for Pydantic models."""

from __future__ import annotations

from play_store_mcp.models import (
    AppDetails,
    DeploymentResult,
    Release,
    Review,
    SubscriptionProduct,
    Track,
    VitalsOverview,
)


class TestTrackEnum:
    """Test Track enum."""

    def test_track_values(self) -> None:
        """Test track enum values."""
        assert Track.INTERNAL == "internal"
        assert Track.ALPHA == "alpha"
        assert Track.BETA == "beta"
        assert Track.PRODUCTION == "production"


class TestRelease:
    """Test Release model."""

    def test_release_minimal(self) -> None:
        """Test creating a release with minimal fields."""
        release = Release(
            package_name="com.example.app",
            track="production",
            status="completed",
        )

        assert release.package_name == "com.example.app"
        assert release.version_codes == []
        assert release.rollout_percentage == 100.0

    def test_release_full(self) -> None:
        """Test creating a release with all fields."""
        release = Release(
            package_name="com.example.app",
            track="beta",
            status="inProgress",
            version_codes=[100, 101],
            version_name="1.0.0",
            rollout_percentage=50.0,
            release_notes={"en-US": "Test notes"},
        )

        assert release.version_codes == [100, 101]
        assert release.rollout_percentage == 50.0
        assert release.release_notes["en-US"] == "Test notes"


class TestDeploymentResult:
    """Test DeploymentResult model."""

    def test_successful_deployment(self) -> None:
        """Test successful deployment result."""
        result = DeploymentResult(
            success=True,
            edit_id="edit-123",
            package_name="com.example.app",
            track="production",
            version_code=100,
            message="Deployed successfully",
        )

        assert result.success is True
        assert result.error is None

    def test_failed_deployment(self) -> None:
        """Test failed deployment result."""
        result = DeploymentResult(
            success=False,
            package_name="com.example.app",
            track="production",
            message="Deployment failed",
            error="Permission denied",
        )

        assert result.success is False
        assert result.edit_id is None
        assert result.error == "Permission denied"


class TestReview:
    """Test Review model."""

    def test_review_required_fields(self) -> None:
        """Test review with required fields only."""
        review = Review(
            review_id="review-123",
            author_name="Test User",
            star_rating=5,
            comment="Great app!",
            language="en",
        )

        assert review.star_rating == 5
        assert review.developer_reply is None

    def test_review_with_reply(self) -> None:
        """Test review with developer reply."""
        review = Review(
            review_id="review-123",
            author_name="Test User",
            star_rating=3,
            comment="Could be better",
            language="en",
            developer_reply="Thanks for the feedback!",
        )

        assert review.developer_reply == "Thanks for the feedback!"


class TestAppDetails:
    """Test AppDetails model."""

    def test_app_details(self) -> None:
        """Test app details model."""
        details = AppDetails(
            package_name="com.example.app",
            title="My App",
            short_description="A great app",
            full_description="This is a great app that does amazing things.",
            default_language="en-US",
            developer_email="dev@example.com",
        )

        assert details.title == "My App"
        assert details.developer_website is None


class TestSubscriptionProduct:
    """Test SubscriptionProduct model."""

    def test_subscription_product(self) -> None:
        """Test subscription product model."""
        product = SubscriptionProduct(
            product_id="premium_monthly",
            package_name="com.example.app",
            base_plans=[
                {"basePlanId": "monthly", "state": "ACTIVE"},
            ],
        )

        assert product.product_id == "premium_monthly"
        assert len(product.base_plans) == 1


class TestVitalsOverview:
    """Test VitalsOverview model."""

    def test_vitals_overview(self) -> None:
        """Test vitals overview model."""
        vitals = VitalsOverview(
            package_name="com.example.app",
            crash_rate=0.5,
            anr_rate=0.1,
        )

        assert vitals.crash_rate == 0.5
        assert vitals.excessive_wakeups is None



class TestInAppProduct:
    """Test InAppProduct model."""

    def test_in_app_product(self) -> None:
        """Test in-app product model."""
        from play_store_mcp.models import InAppProduct

        product = InAppProduct(
            sku="premium_upgrade",
            package_name="com.example.app",
            product_type="managedProduct",
            status="active",
            default_language="en-US",
            title="Premium Upgrade",
            description="Unlock all features",
            default_price={"currency": "USD", "priceMicros": "4990000"},
        )

        assert product.sku == "premium_upgrade"
        assert product.product_type == "managedProduct"
        assert product.default_price is not None


class TestVitalsMetric:
    """Test VitalsMetric model."""

    def test_vitals_metric(self) -> None:
        """Test vitals metric model."""
        from play_store_mcp.models import VitalsMetric

        metric = VitalsMetric(
            metric_type="crashRate",
            value=0.5,
            benchmark=1.0,
            is_below_threshold=True,
            dimension="api_level",
            dimension_value="30",
        )

        assert metric.metric_type == "crashRate"
        assert metric.value == 0.5
        assert metric.is_below_threshold is True
