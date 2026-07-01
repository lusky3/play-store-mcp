"""Pydantic models for Play Store MCP Server."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic needs this at runtime
from typing import Any

from pydantic import BaseModel, Field


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


class InAppProductActionResult(BaseModel):
    """Result of a delete/batch-delete action on in-app products."""

    success: bool = Field(..., description="Whether the action succeeded")
    package_name: str = Field(..., description="App package name")
    sku: str | None = Field(None, description="Product SKU (None for batch operations)")
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")


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


class TesterInfo(BaseModel):
    """Information about testers for a track."""

    track: str = Field(..., description="Track name")
    google_groups: list[str] = Field(
        default_factory=list, description="List of Google Group email addresses"
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


class ProductPurchase(BaseModel):
    """Status of an in-app product purchase."""

    package_name: str = Field(..., description="App package name")
    product_id: str = Field(..., description="In-app product SKU")
    purchase_token: str = Field(..., description="Purchase token")
    order_id: str | None = Field(None, description="Order ID")
    purchase_state: int | None = Field(
        None, description="Purchase state (0=purchased, 1=canceled, 2=pending)"
    )
    consumption_state: int | None = Field(
        None, description="Consumption state (0=yet to be consumed, 1=consumed)"
    )
    acknowledgement_state: int | None = Field(
        None, description="Acknowledgement state (0=not acknowledged, 1=acknowledged)"
    )
    purchase_time: datetime | None = Field(None, description="Purchase time")
    purchase_type: int | None = Field(
        None, description="Purchase type (0=test, 1=promo, 2=rewarded)"
    )
    quantity: int | None = Field(None, description="Quantity purchased")
    region_code: str | None = Field(None, description="Billing region code")
    developer_payload: str | None = Field(None, description="Developer-supplied payload")


class ProductPurchaseActionResult(BaseModel):
    """Result of an acknowledge/consume action on an in-app product purchase."""

    success: bool = Field(..., description="Whether the action succeeded")
    package_name: str = Field(..., description="App package name")
    product_id: str = Field(..., description="In-app product SKU")
    purchase_token: str = Field(..., description="Purchase token")
    action: str = Field(..., description="Action performed (acknowledge or consume)")
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")


class ValidationResult(BaseModel):
    """Validation result details."""

    field: str = Field(..., description="Field that failed validation")
    message: str = Field(..., description="Error message")
    value: Any | None = Field(None, description="Invalid value")


class OrderRefundResult(BaseModel):
    """Result of refunding an order."""

    success: bool = Field(..., description="Whether the refund succeeded")
    package_name: str = Field(..., description="App package name")
    order_id: str = Field(..., description="Order ID")
    revoked: bool = Field(..., description="Whether the entitlement was also revoked")
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")


class SubscriptionActionResult(BaseModel):
    """Result of a cancel/defer/revoke action on a subscription purchase."""

    success: bool = Field(..., description="Whether the action succeeded")
    package_name: str = Field(..., description="App package name")
    purchase_token: str = Field(..., description="Purchase token")
    action: str = Field(..., description="Action performed (cancel, defer, or revoke)")
    message: str = Field(..., description="Status message")
    details: dict[str, Any] | None = Field(
        None, description="Extra result data (e.g. defer expiry)"
    )
    error: str | None = Field(None, description="Error details if failed")


class SubscriptionCatalogResult(BaseModel):
    """Result of a delete action on a subscription catalog product."""

    success: bool = Field(..., description="Whether the action succeeded")
    package_name: str = Field(..., description="App package name")
    product_id: str | None = Field(
        None, description="Subscription product ID (None for batch operations)"
    )
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")


class SubscriptionOffer(BaseModel):
    """Subscription offer definition (basePlans.offers resource)."""

    package_name: str = Field(..., description="App package name")
    product_id: str = Field(..., description="Parent subscription product ID")
    base_plan_id: str = Field(..., description="Parent base plan ID")
    offer_id: str = Field(..., description="Subscription offer ID")
    state: str | None = Field(None, description="Offer state (e.g. DRAFT, ACTIVE, INACTIVE)")
    offer_tags: list[str] = Field(default_factory=list, description="Offer tag strings")
    phases: list[dict[str, Any]] = Field(
        default_factory=list, description="Offer phase definitions"
    )
    regions_version: str | None = Field(None, description="Regions catalog version")


class OneTimeProduct(BaseModel):
    """One-time product definition (monetization.oneTimeProducts resource)."""

    product_id: str = Field(..., description="One-time product ID")
    package_name: str = Field(..., description="App package name")
    listings: list[dict[str, Any]] = Field(
        default_factory=list, description="Store listing definitions"
    )
    purchase_options: list[dict[str, Any]] = Field(
        default_factory=list, description="Purchase option definitions"
    )
    offer_tags: list[dict[str, Any]] = Field(
        default_factory=list, description="Offer tag definitions"
    )
    restricted_payment_countries: dict[str, Any] | None = Field(
        None, description="Restricted payment countries configuration"
    )


class OneTimeProductActionResult(BaseModel):
    """Result of a delete/batch-delete action on a one-time product catalog resource."""

    success: bool = Field(..., description="Whether the action succeeded")
    package_name: str = Field(..., description="App package name")
    product_id: str | None = Field(
        None, description="One-time product ID (None for batch operations)"
    )
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")


class OneTimeProductOffer(BaseModel):
    """One-time product offer definition (purchaseOptions.offers resource)."""

    package_name: str = Field(..., description="App package name")
    product_id: str = Field(..., description="Parent one-time product ID")
    purchase_option_id: str = Field(..., description="Parent purchase option ID")
    offer_id: str = Field(..., description="One-time product offer ID")
    state: str | None = Field(None, description="Offer state (e.g. DRAFT, ACTIVE, INACTIVE)")
    offer_tags: list[str] = Field(default_factory=list, description="Offer tag strings")
    regions_version: str | None = Field(None, description="Regions catalog version")


class ProductPurchaseV2(BaseModel):
    """Status of an in-app product purchase (Purchases.productsv2)."""

    package_name: str = Field(..., description="App package name")
    purchase_token: str = Field(..., description="Purchase token")
    order_id: str | None = Field(None, description="Order ID")
    acknowledgement_state: str | None = Field(None, description="Acknowledgement state (enum)")
    purchase_completion_time: str | None = Field(
        None, description="Purchase completion time (RFC3339)"
    )
    region_code: str | None = Field(None, description="Billing region code")
    product_line_items: list[dict[str, Any]] = Field(
        default_factory=list, description="Purchased product line items"
    )
    obfuscated_external_account_id: str | None = Field(
        None, description="Obfuscated external account ID"
    )
    obfuscated_external_profile_id: str | None = Field(
        None, description="Obfuscated external profile ID"
    )
    test_purchase: bool = Field(False, description="Whether this is a test purchase")


class ExternalTransaction(BaseModel):
    """External (alternative billing) transaction (externaltransactions resource)."""

    package_name: str = Field(..., description="App package name")
    external_transaction_id: str = Field(..., description="External transaction ID")
    transaction_state: str | None = Field(None, description="Current transaction state")
    create_time: str | None = Field(None, description="Time the transaction was created (RFC3339)")
    current_pre_tax_amount: dict[str, Any] | None = Field(
        None, description="Current transaction amount before tax (Price)"
    )
    original_pre_tax_amount: dict[str, Any] | None = Field(
        None, description="Original transaction amount before tax (Price)"
    )
    test_purchase: bool = Field(False, description="Whether this is a test purchase")


class DeviceTierConfig(BaseModel):
    """Device tier config (applications.deviceTierConfigs resource)."""

    package_name: str = Field(..., description="App package name")
    device_tier_config_id: str | None = Field(None, description="Device tier config ID")
    device_groups: list[dict[str, Any]] = Field(
        default_factory=list, description="Device group definitions"
    )
    device_tier_set: dict[str, Any] | None = Field(
        None, description="Set of device tiers for the app"
    )
    user_country_sets: list[dict[str, Any]] = Field(
        default_factory=list, description="User country set definitions"
    )
