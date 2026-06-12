"""Pydantic models for Play Store MCP Server."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic needs this at runtime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Track(StrEnum):
    """Release track options."""

    INTERNAL = "internal"
    ALPHA = "alpha"
    BETA = "beta"
    PRODUCTION = "production"


class ReleaseStatus(StrEnum):
    """Release status options."""

    DRAFT = "draft"
    IN_PROGRESS = "inProgress"
    HALTED = "halted"
    COMPLETED = "completed"


class Release(BaseModel):
    """Represents an app release on a track."""

    package_name: str = Field(..., description="App package name")
    track: str = Field(..., description="Release track")
    status: str = Field(..., description="Release status")
    version_codes: list[int] = Field(default_factory=list, description="Version codes in release")
    version_name: str | None = Field(None, description="Version name")
    rollout_percentage: float = Field(100.0, description="Rollout percentage (0-100)")
    release_notes: dict[str, str] = Field(
        default_factory=dict, description="Release notes by language"
    )


class TrackInfo(BaseModel):
    """Information about a release track."""

    track: str = Field(..., description="Track name")
    releases: list[Release] = Field(default_factory=list, description="Releases on this track")


class DeploymentResult(BaseModel):
    """Result of a deployment operation."""

    success: bool = Field(..., description="Whether deployment succeeded")
    edit_id: str | None = Field(None, description="Edit ID for the operation")
    package_name: str = Field(..., description="App package name")
    track: str = Field(..., description="Target track")
    version_code: int | None = Field(None, description="Deployed version code")
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")


class AppInfo(BaseModel):
    """Basic app information."""

    package_name: str = Field(..., description="App package name")
    title: str | None = Field(None, description="App title")
    default_language: str | None = Field(None, description="Default language")


class AppDetails(BaseModel):
    """Detailed app information."""

    package_name: str = Field(..., description="App package name")
    title: str | None = Field(None, description="App title")
    short_description: str | None = Field(None, description="Short description")
    full_description: str | None = Field(None, description="Full description")
    default_language: str | None = Field(None, description="Default language")
    developer_name: str | None = Field(None, description="Developer name")
    developer_email: str | None = Field(None, description="Developer email")
    developer_website: str | None = Field(None, description="Developer website")


class Review(BaseModel):
    """User review."""

    review_id: str = Field(..., description="Review ID")
    author_name: str = Field(..., description="Author name")
    star_rating: int = Field(..., description="Star rating (1-5)")
    comment: str = Field(..., description="Review comment")
    language: str = Field(..., description="Review language")
    device: str | None = Field(None, description="Device name")
    android_version: str | None = Field(None, description="Android OS version")
    app_version_code: int | None = Field(None, description="App version code")
    app_version_name: str | None = Field(None, description="App version name")
    last_modified: datetime | None = Field(None, description="Last modification time")
    developer_reply: str | None = Field(None, description="Developer reply if present")
    developer_reply_time: datetime | None = Field(None, description="Reply time")


class ReviewReplyResult(BaseModel):
    """Result of replying to a review."""

    success: bool = Field(..., description="Whether reply succeeded")
    review_id: str = Field(..., description="Review ID")
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")


class SubscriptionProduct(BaseModel):
    """Subscription product definition."""

    product_id: str = Field(..., description="Subscription product ID")
    package_name: str = Field(..., description="App package name")
    status: str | None = Field(None, description="Subscription status")
    base_plans: list[dict[str, Any]] = Field(
        default_factory=list, description="Base plan definitions"
    )


class SubscriptionPurchase(BaseModel):
    """Subscription purchase status."""

    package_name: str = Field(..., description="App package name")
    subscription_id: str = Field(..., description="Subscription product ID")
    purchase_token: str = Field(..., description="Purchase token")
    order_id: str | None = Field(None, description="Order ID")
    start_time: datetime | None = Field(None, description="Subscription start time")
    expiry_time: datetime | None = Field(None, description="Subscription expiry time")
    auto_renewing: bool = Field(False, description="Whether auto-renewing")
    cancel_reason: int | None = Field(None, description="Cancellation reason code")
    payment_state: int | None = Field(None, description="Payment state code")
    price_currency: str | None = Field(None, description="Price currency code")
    price_amount_micros: int | None = Field(None, description="Price amount in micros")


class VoidedPurchase(BaseModel):
    """Voided purchase record."""

    package_name: str = Field(..., description="App package name")
    purchase_token: str = Field(..., description="Original purchase token")
    order_id: str | None = Field(None, description="Order ID")
    voided_time: datetime | None = Field(None, description="Time of voiding")
    voided_reason: int | None = Field(None, description="Reason for voiding")
    voided_source: int | None = Field(None, description="Source of voiding")


class VitalsOverview(BaseModel):
    """Android Vitals overview metrics."""

    package_name: str = Field(..., description="App package name")
    crash_rate: float | None = Field(None, description="User-perceived crash rate")
    anr_rate: float | None = Field(None, description="User-perceived ANR rate")
    excessive_wakeups: float | None = Field(None, description="Excessive wakeups rate")
    stuck_wake_locks: float | None = Field(None, description="Stuck wake locks rate")
    freshness_info: str | None = Field(None, description="Data freshness information")


class VitalsMetric(BaseModel):
    """Specific vitals metric data."""

    metric_type: str = Field(..., description="Type of metric")
    value: float | None = Field(None, description="Metric value")
    benchmark: float | None = Field(None, description="Benchmark threshold")
    is_below_threshold: bool | None = Field(None, description="Whether below bad threshold")
    dimension: str | None = Field(None, description="Dimension (e.g., device, version)")
    dimension_value: str | None = Field(None, description="Dimension value")


class InAppProduct(BaseModel):
    """In-app product definition."""

    sku: str = Field(..., description="Product SKU")
    package_name: str = Field(..., description="App package name")
    product_type: str = Field(..., description="Product type (managed_product or subscription)")
    status: str | None = Field(None, description="Product status")
    default_language: str | None = Field(None, description="Default language")
    title: str | None = Field(None, description="Product title")
    description: str | None = Field(None, description="Product description")
    default_price: dict[str, Any] | None = Field(None, description="Default price information")


class Listing(BaseModel):
    """Store listing for a specific language."""

    language: str = Field(..., description="Language code (e.g., en-US)")
    title: str | None = Field(None, description="App title")
    full_description: str | None = Field(None, description="Full description")
    short_description: str | None = Field(None, description="Short description")
    video: str | None = Field(None, description="YouTube video URL")


class ListingUpdateResult(BaseModel):
    """Result of updating a store listing."""

    success: bool = Field(..., description="Whether update succeeded")
    package_name: str = Field(..., description="App package name")
    language: str = Field(..., description="Language code")
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")


class ListingBatchUpdateResult(BaseModel):
    """Result of validating or updating multiple store listings."""

    success: bool = Field(..., description="Whether validation/update succeeded")
    package_name: str = Field(..., description="App package name")
    commit: bool = Field(..., description="Whether changes were committed")
    edit_id: str | None = Field(None, description="Edit ID used for committed updates")
    validated_languages: list[str] = Field(
        default_factory=list, description="Languages that passed validation"
    )
    updated_languages: list[str] = Field(
        default_factory=list, description="Languages updated when commit is true"
    )
    errors: list[dict[str, Any]] = Field(
        default_factory=list, description="Validation or update errors by language"
    )
    message: str = Field(..., description="Status message")


class TesterInfo(BaseModel):
    """Information about testers for a track."""

    track: str = Field(..., description="Track name")
    tester_emails: list[str] = Field(
        default_factory=list, description="List of tester email addresses"
    )


class Order(BaseModel):
    """Order/transaction information."""

    order_id: str = Field(..., description="Order ID")
    package_name: str = Field(..., description="App package name")
    product_id: str | None = Field(None, description="Product ID")
    purchase_time: datetime | None = Field(None, description="Purchase timestamp")
    purchase_state: int | None = Field(None, description="Purchase state")
    purchase_token: str | None = Field(None, description="Purchase token")
    quantity: int | None = Field(None, description="Quantity purchased")


class ExpansionFile(BaseModel):
    """APK expansion file information."""

    version_code: int = Field(..., description="Version code")
    expansion_file_type: str = Field(..., description="Expansion file type (main or patch)")
    file_size: int | None = Field(None, description="File size in bytes")
    references_version: int | None = Field(None, description="Referenced version code")


class BatchDeploymentResult(BaseModel):
    """Result of batch deployment to multiple tracks."""

    success: bool = Field(..., description="Whether all deployments succeeded")
    results: list[DeploymentResult] = Field(
        default_factory=list, description="Individual deployment results"
    )
    successful_count: int = Field(0, description="Number of successful deployments")
    failed_count: int = Field(0, description="Number of failed deployments")
    message: str = Field(..., description="Overall status message")


class ValidationError(BaseModel):
    """Validation error details."""

    field: str = Field(..., description="Field that failed validation")
    message: str = Field(..., description="Error message")
    value: Any | None = Field(None, description="Invalid value")


# =============================================================================
# Images API Models
# =============================================================================


class ImageInfo(BaseModel):
    """Store listing image information."""

    image_id: str = Field(..., description="Image ID")
    url: str = Field(..., description="Image URL")
    sha1: str | None = Field(None, description="SHA1 hash of image")
    sha256: str | None = Field(None, description="SHA256 hash of image")


class ImageUploadResult(BaseModel):
    """Result of an image upload or delete operation."""

    success: bool = Field(..., description="Whether operation succeeded")
    package_name: str = Field(..., description="App package name")
    language: str = Field(..., description="Language code")
    image_type: str = Field(..., description="Image type")
    image_id: str | None = Field(None, description="Image ID (for upload)")
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")


class DeobfuscationFileResult(BaseModel):
    """Result of uploading a deobfuscation (ProGuard/R8) mapping file."""

    success: bool = Field(..., description="Whether upload succeeded")
    package_name: str = Field(..., description="App package name")
    version_code: int = Field(..., description="APK version code")
    deobfuscation_file_type: str = Field(..., description="Type: proguard or nativeCode")
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")


class BundleInfo(BaseModel):
    """Information about an uploaded AAB bundle."""

    package_name: str = Field(..., description="App package name")
    version_code: int = Field(..., description="Version code of the bundle")
    sha1: str | None = Field(None, description="SHA1 hash of the bundle")
    sha256: str | None = Field(None, description="SHA256 hash of the bundle")


class GeneratedApkInfo(BaseModel):
    """Information about a generated APK from an AAB bundle."""

    package_name: str = Field(..., description="App package name")
    bundle_version_code: int = Field(..., description="Version code of the source bundle")
    download_id: str | None = Field(None, description="Download ID for the generated APK")
    variant_id: int | None = Field(None, description="Variant ID")
    target_sdk_version: int | None = Field(None, description="Target SDK version")
    min_sdk_version: int | None = Field(None, description="Minimum SDK version")
    split_types: list[str] = Field(default_factory=list, description="List of split types")


# =============================================================================
# App Details Models
# =============================================================================


class AppDetailsInfo(BaseModel):
    """App details from edits.details API."""

    package_name: str = Field(..., description="App package name")
    default_language: str | None = Field(None, description="Default language code")
    contact_email: str | None = Field(None, description="Developer contact email")
    contact_phone: str | None = Field(None, description="Developer contact phone")
    contact_website: str | None = Field(None, description="Developer contact website")


class AppDetailsUpdateResult(BaseModel):
    """Result of updating app details."""

    success: bool = Field(..., description="Whether update succeeded")
    package_name: str = Field(..., description="App package name")
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")


# =============================================================================
# Country Availability Models
# =============================================================================


class CountryAvailability(BaseModel):
    """Country availability for a release track."""

    package_name: str = Field(..., description="App package name")
    track: str = Field(..., description="Release track")
    countries: list[str] = Field(default_factory=list, description="List of country codes")
    rest_of_world: bool = Field(False, description="Whether available in rest of world")


# =============================================================================
# Users & Grants Models
# =============================================================================


class GrantInfo(BaseModel):
    """App-level grant for a user."""

    package_name: str = Field(..., description="App package name")
    app_level_permissions: list[str] = Field(
        default_factory=list, description="App-level permissions granted"
    )


class UserInfo(BaseModel):
    """Developer account user information."""

    name: str | None = Field(None, description="Resource name of user")
    email: str = Field(..., description="User email address")
    access_state: str | None = Field(None, description="Account-level access state")
    grants: list[GrantInfo] = Field(default_factory=list, description="App-level grants")


class UserOperationResult(BaseModel):
    """Result of a user or grant operation."""

    success: bool = Field(..., description="Whether operation succeeded")
    email: str = Field(..., description="User email address")
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")


# =============================================================================
# Orders & Purchases Models
# =============================================================================


class RefundResult(BaseModel):
    """Result of an order refund operation."""

    success: bool = Field(..., description="Whether refund succeeded")
    order_id: str = Field(..., description="Order ID")
    package_name: str = Field(..., description="App package name")
    revoked: bool = Field(False, description="Whether entitlement was revoked")
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")


class ProductPurchase(BaseModel):
    """One-time in-app product purchase status."""

    package_name: str = Field(..., description="App package name")
    product_id: str = Field(..., description="Product ID")
    purchase_token: str = Field(..., description="Purchase token")
    purchase_time: datetime | None = Field(None, description="Purchase time")
    purchase_state: int | None = Field(None, description="0=purchased, 1=canceled, 2=pending")
    consumption_state: int | None = Field(None, description="0=not consumed, 1=consumed")
    developer_payload: str | None = Field(None, description="Developer payload")
    order_id: str | None = Field(None, description="Order ID")
    acknowledged: bool = Field(False, description="Whether purchase was acknowledged")
    quantity: int | None = Field(None, description="Purchase quantity")


class SubscriptionPurchaseV2(BaseModel):
    """Subscription purchase status (v2 API)."""

    package_name: str = Field(..., description="App package name")
    purchase_token: str = Field(..., description="Purchase token")
    subscription_state: str | None = Field(None, description="Subscription state")
    latest_order_id: str | None = Field(None, description="Latest order ID")
    start_time: datetime | None = Field(None, description="Subscription start time")
    expiry_time: datetime | None = Field(None, description="Current period expiry time")
    auto_renewing: bool = Field(False, description="Whether auto-renewing")
    product_id: str | None = Field(None, description="Subscription product ID")
    base_plan_id: str | None = Field(None, description="Base plan ID")
    offer_id: str | None = Field(None, description="Offer ID if applicable")


# =============================================================================
# Play Developer Reporting API Models
# =============================================================================


class VitalsDataPoint(BaseModel):
    """A single data point from a vitals metric set query."""

    date: str = Field(..., description="Date string YYYY-MM-DD")
    aggregation_period: str = Field(..., description="DAILY or HOURLY")
    dimensions: dict[str, str] = Field(
        default_factory=dict, description="Dimension key-value pairs (e.g. apiLevel: '33')"
    )
    metrics: dict[str, float | None] = Field(
        default_factory=dict, description="Metric key-value pairs (e.g. crashRate: 0.012)"
    )


class VitalsQueryResult(BaseModel):
    """Result of querying a Play Developer Reporting vitals metric set."""

    package_name: str = Field(..., description="App package name")
    metric_set: str = Field(
        ..., description="Metric set name: crashRate, anrRate, slowStartup, etc."
    )
    aggregation_period: str = Field(..., description="DAILY or HOURLY")
    data_points: list[VitalsDataPoint] = Field(
        default_factory=list, description="Timeline data points"
    )
    row_count: int = Field(0, description="Total number of rows returned")


class VitalsAnomaly(BaseModel):
    """A detected anomaly in a vitals metric."""

    name: str = Field(..., description="Anomaly resource name")
    metric_set: str = Field(..., description="Metric set where anomaly was detected")
    dimensions: dict[str, str] = Field(
        default_factory=dict, description="Dimension values for this anomaly"
    )
    first_detection_time: str | None = Field(None, description="When the anomaly was first detected")
    last_detected_day: str | None = Field(None, description="Last day the anomaly was observed")


# ---------------------------------------------------------------------------
# Play Console Browser-Based Stats (via OpenCLI)
# ---------------------------------------------------------------------------


class DailyStatPoint(BaseModel):
    """A single day's data point from Play Console statistics."""

    date: str = Field(..., description="Date in YYYY-MM-DD format")
    value: int = Field(..., description="Metric value for this day")


class ConsoleStatsResult(BaseModel):
    """Result from one metric/dimension combination."""

    metric: str = Field(..., description="Metric name: install_events, net_installs, active_users")
    dimension: str = Field(default="overall", description="Dimension: overall or country code")
    total: int = Field(0, description="Sum of all daily values in range")
    data_points: list[DailyStatPoint] = Field(default_factory=list, description="Daily data points (non-zero only)")


class ConsoleInstallStats(BaseModel):
    """Install statistics from Play Console (requires browser login via OpenCLI)."""

    package_name: str = Field(..., description="App package name")
    start_date: str = Field(..., description="Start date YYYY-MM-DD")
    end_date: str = Field(..., description="End date YYYY-MM-DD")
    install_events: ConsoleStatsResult | None = Field(None, description="Total install events including re-installs")
    net_installs: ConsoleStatsResult | None = Field(None, description="Net installs = installs - uninstalls")
    active_users: ConsoleStatsResult | None = Field(None, description="Unique active users")
    by_country: list[ConsoleStatsResult] = Field(default_factory=list, description="Per-country install events breakdown")


class SearchTermResult(BaseModel):
    """A single search term with its install and visitor stats."""

    term: str = Field(..., description="Search term string")
    installs: int = Field(0, description="Number of installs attributed to this search term")
    store_listing_visitors: int = Field(0, description="Number of store listing visitors from this term")


class SearchTermsStats(BaseModel):
    """Search terms statistics from Play Console."""

    package_name: str = Field(..., description="App package name")
    start_date: str = Field(..., description="Start date YYYY-MM-DD")
    end_date: str = Field(..., description="End date YYYY-MM-DD")
    terms: list[SearchTermResult] = Field(default_factory=list, description="Search terms sorted by installs descending")


class AcquisitionFunnelStage(BaseModel):
    """A single stage in the user acquisition funnel."""

    stage: str = Field(..., description="Stage name: impressions, store_listing_visitors, installers, buyers")
    value: int = Field(0, description="Count for this stage")
    conversion_rate: float = Field(0.0, description="Conversion rate relative to previous stage (0.0-1.0)")


class AcquisitionFunnelResult(BaseModel):
    """User acquisition funnel from Play Console."""

    package_name: str = Field(..., description="App package name")
    start_date: str = Field(..., description="Start date YYYY-MM-DD")
    end_date: str = Field(..., description="End date YYYY-MM-DD")


# ---------------------------------------------------------------------------
# New models for missing API coverage
# ---------------------------------------------------------------------------


class InAppProductUpsertResult(BaseModel):
    """Result of creating or updating an in-app product."""

    success: bool
    package_name: str
    sku: str
    message: str
    error: str | None = None


class SubscriptionDetails(BaseModel):
    """Full subscription product details from the Monetization API."""

    product_id: str
    package_name: str
    state: str | None = None
    listings: dict | None = None
    base_plans: list[dict] | None = None


class SubscriptionUpsertResult(BaseModel):
    """Result of creating or updating a subscription product."""

    success: bool
    package_name: str
    product_id: str
    message: str
    error: str | None = None


class BasePlanActionResult(BaseModel):
    """Result of activating or deactivating a base plan."""

    success: bool
    package_name: str
    product_id: str
    base_plan_id: str
    action: str
    message: str
    error: str | None = None


class CountryAvailabilityUpdateResult(BaseModel):
    """Result of updating country availability for a track."""

    success: bool
    package_name: str
    track: str
    countries_set: list[str]
    rest_of_world: bool
    message: str
    error: str | None = None


class SubscriptionDeferResult(BaseModel):
    """Result of deferring a subscription renewal."""

    success: bool
    package_name: str
    subscription_id: str
    new_expiry_time_millis: str | None = None
    message: str
    error: str | None = None


class ListingDeleteResult(BaseModel):
    """Result of deleting a store listing."""

    success: bool
    package_name: str
    language: str | None = None
    message: str
    error: str | None = None


class RegionPrice(BaseModel):
    """Converted price for a specific region."""

    region_code: str
    price_micros: str
    currency_code: str


class ConvertRegionPricesResult(BaseModel):
    """Result of converting a price to all regional equivalents."""

    success: bool
    converted_prices: list[RegionPrice]
    error: str | None = None
    stages: list[AcquisitionFunnelStage] = Field(default_factory=list, description="Funnel stages in order")
