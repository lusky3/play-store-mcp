"""Play Store MCP Server - Main server implementation."""

from __future__ import annotations

import argparse
import base64
import binascii
import ipaddress
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from play_store_mcp.client import PlayStoreClient, PlayStoreClientError

# Configure structured logging to stderr (stdout is reserved for MCP JSON-RPC)
log_level = os.environ.get("PLAY_STORE_MCP_LOG_LEVEL", "INFO")
numeric_level = getattr(logging, log_level.upper(), logging.INFO)
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
)
logger = structlog.get_logger(__name__)


def get_client_from_context() -> PlayStoreClient:
    """Get PlayStoreClient from request context.

    Checks for credentials in request headers first (X-Google-Credentials or
    X-Google-Credentials-Base64), then falls back to the shared client from
    lifespan context.

    Returns:
        PlayStoreClient instance

    Raises:
        PlayStoreClientError: If credentials are invalid or client cannot be created
    """
    ctx = mcp.get_context()

    # Check for per-request credentials in headers
    if hasattr(ctx, "request_context") and hasattr(ctx.request_context, "request"):
        request = ctx.request_context.request
        if request is not None and hasattr(request, "headers"):
            headers = request.headers

            # Try X-Google-Credentials header (JSON string or object)
            if "x-google-credentials" in headers:
                creds_str = headers["x-google-credentials"]
                try:
                    creds_json = json.loads(creds_str)
                    return PlayStoreClient(credentials_json=creds_json)
                except json.JSONDecodeError as e:
                    raise PlayStoreClientError(f"Invalid JSON in X-Google-Credentials header: {e}")

            # Try X-Google-Credentials-Base64 header
            if "x-google-credentials-base64" in headers:
                creds_b64 = headers["x-google-credentials-base64"]
                try:
                    creds_bytes = base64.b64decode(creds_b64)
                    creds_str = creds_bytes.decode("utf-8")
                    creds_json = json.loads(creds_str)
                    return PlayStoreClient(credentials_json=creds_json)
                except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as e:
                    raise PlayStoreClientError(
                        f"Invalid base64 or JSON in X-Google-Credentials-Base64 header: {e}"
                    )

    # Fall back to shared client from lifespan
    if hasattr(ctx, "request_context") and hasattr(ctx.request_context, "lifespan_context"):
        client: PlayStoreClient | None = ctx.request_context.lifespan_context.get("client")
        if client is not None:
            return client

    raise PlayStoreClientError(
        "No credentials provided. Set X-Google-Credentials or X-Google-Credentials-Base64 header, "
        "or configure server with GOOGLE_PLAY_STORE_CREDENTIALS environment variable."
    )


@asynccontextmanager
async def lifespan(_server: FastMCP):  # type: ignore[no-untyped-def]
    """Lifespan context manager for the MCP server.

    Initializes the PlayStoreClient and makes it available via server context.
    """
    logger.info("Initializing Play Store MCP Server")

    # Create a shared state dict that will be accessible from custom routes
    shared_state: dict[str, Any] = {"client": None, "credentials_updated": False}

    try:
        client = PlayStoreClient()
        # Validate credentials on startup
        _ = client._get_service()
        logger.info("Play Store client initialized successfully")
        shared_state["client"] = client
    except PlayStoreClientError as e:
        logger.warning("Play Store client initialization failed", error=str(e))
        shared_state["client"] = None

    # Store shared state in the server instance for access from custom routes
    _server._shared_state = shared_state  # type: ignore[attr-defined]

    yield shared_state

    logger.info("Shutting down Play Store MCP Server")


def _validate_deploy_file(file_path: str) -> str | None:
    """Return error message if file_path is invalid, None if valid."""
    resolved = os.path.realpath(file_path)
    if not resolved.lower().endswith((".apk", ".aab")):
        return "file_path must be a .apk or .aab file"
    if not Path(resolved).is_file():
        return f"File not found: {resolved}"
    return None


def _validate_rollout(pct: float) -> str | None:
    """Return error message if rollout percentage is invalid, None if valid."""
    if not (0.0 <= pct <= 100.0):
        return "rollout_percentage must be between 0.0 and 100.0"
    return None


def _env_read_only() -> bool:
    """Return True if PLAY_STORE_MCP_READ_ONLY is set to a truthy value."""
    return os.environ.get("PLAY_STORE_MCP_READ_ONLY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# When True, all write/mutating tools are disabled. Initialized from the
# environment at import time; may be overridden by the --read-only CLI flag.
READ_ONLY: bool = _env_read_only()

READ_ONLY_ERROR = (
    "Server is running in read-only mode; write operations are disabled. "
    "Unset PLAY_STORE_MCP_READ_ONLY (or omit --read-only) to enable writes."
)


def set_read_only(value: bool) -> None:
    """Set the process-wide read-only flag."""
    global READ_ONLY
    READ_ONLY = value


def _read_only_block(operation: str) -> dict[str, Any] | None:
    """Return an error object if read-only mode blocks a write, else None."""
    if READ_ONLY:
        logger.warning("Blocked write operation in read-only mode", operation=operation)
        return {"error": f"{READ_ONLY_ERROR} (attempted: {operation})"}
    return None


# Initialize the MCP server
mcp = FastMCP(
    "Play Store MCP Server",
    lifespan=lifespan,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=not os.environ.get("PLAY_STORE_MCP_DISABLE_DNS_REBINDING"),
    ),
)


# =============================================================================
# Publishing Tools
# =============================================================================


@mcp.tool()
def deploy_app(
    package_name: str,
    track: str,
    file_path: str,
    release_notes: str | None = None,
    release_notes_language: str = "en-US",
    rollout_percentage: float = 100.0,
) -> dict[str, Any]:
    """Deploy an APK or AAB file to a Play Store track.

    Args:
        package_name: App package name (e.g., com.example.myapp)
        track: Release track - one of: internal, alpha, beta, production
        file_path: Absolute path to APK or AAB file
        release_notes: Optional release notes for this version (string for single language,
                      or use release_notes_multilang for multiple languages)
        release_notes_language: Language code for release notes (default: en-US)
        rollout_percentage: Rollout percentage (0-100). Default 100 for full rollout.

    Returns:
        Deployment result with success status and details
    """
    if blocked := _read_only_block("deploy_app"):
        return blocked
    if err := _validate_deploy_file(file_path):
        return {"error": err}
    if err := _validate_rollout(rollout_percentage):
        return {"error": err}

    client = get_client_from_context()

    result = client.deploy_app(
        package_name=package_name,
        track=track,
        file_path=file_path,
        release_notes=release_notes,
        release_notes_language=release_notes_language,
        rollout_percentage=rollout_percentage,
    )

    return result.model_dump()


@mcp.tool()
def deploy_app_multilang(
    package_name: str,
    track: str,
    file_path: str,
    release_notes: dict[str, str],
    rollout_percentage: float = 100.0,
) -> dict[str, Any]:
    """Deploy an APK or AAB file with multi-language release notes.

    Args:
        package_name: App package name (e.g., com.example.myapp)
        track: Release track - one of: internal, alpha, beta, production
        file_path: Absolute path to APK or AAB file
        release_notes: Dictionary mapping language codes to release notes
                      (e.g., {"en-US": "Bug fixes", "es-ES": "Corrección de errores"})
        rollout_percentage: Rollout percentage (0-100). Default 100 for full rollout.

    Returns:
        Deployment result with success status and details
    """
    if blocked := _read_only_block("deploy_app_multilang"):
        return blocked
    if err := _validate_deploy_file(file_path):
        return {"error": err}
    if err := _validate_rollout(rollout_percentage):
        return {"error": err}

    client = get_client_from_context()

    result = client.deploy_app(
        package_name=package_name,
        track=track,
        file_path=file_path,
        release_notes=release_notes,
        rollout_percentage=rollout_percentage,
    )

    return result.model_dump()


@mcp.tool()
def promote_release(
    package_name: str,
    from_track: str,
    to_track: str,
    version_code: int,
    rollout_percentage: float = 100.0,
) -> dict[str, Any]:
    """Promote a release from one track to another.

    Args:
        package_name: App package name
        from_track: Source track (internal, alpha, beta)
        to_track: Destination track (alpha, beta, production)
        version_code: Version code to promote
        rollout_percentage: Rollout percentage for target track (0-100)

    Returns:
        Promotion result with success status and details
    """
    if blocked := _read_only_block("promote_release"):
        return blocked
    if err := _validate_rollout(rollout_percentage):
        return {"error": err}

    client = get_client_from_context()

    result = client.promote_release(
        package_name=package_name,
        from_track=from_track,
        to_track=to_track,
        version_code=version_code,
        rollout_percentage=rollout_percentage,
    )

    return result.model_dump()


@mcp.tool()
def get_releases(package_name: str) -> list[dict[str, Any]]:
    """Get release status for all tracks of an app.

    Args:
        package_name: App package name

    Returns:
        List of tracks with their releases and version information
    """
    client = get_client_from_context()

    tracks = client.get_releases(package_name)
    return [track.model_dump() for track in tracks]


@mcp.tool()
def halt_release(
    package_name: str,
    track: str,
    version_code: int,
) -> dict[str, Any]:
    """Halt a staged rollout.

    Use this to stop a release that is currently rolling out.
    The release will be marked as halted and users will stop receiving updates.

    Args:
        package_name: App package name
        track: Track containing the release (internal, alpha, beta, production)
        version_code: Version code of the release to halt

    Returns:
        Result with success status and details
    """
    if blocked := _read_only_block("halt_release"):
        return blocked
    client = get_client_from_context()

    result = client.halt_release(
        package_name=package_name,
        track=track,
        version_code=version_code,
    )

    return result.model_dump()


@mcp.tool()
def update_rollout(
    package_name: str,
    track: str,
    version_code: int,
    rollout_percentage: float,
) -> dict[str, Any]:
    """Update the rollout percentage for a staged release.

    Use this to increase or decrease the percentage of users receiving an update.
    Set to 100 to complete the rollout.

    Args:
        package_name: App package name
        track: Track containing the release
        version_code: Version code of the staged release
        rollout_percentage: New rollout percentage (0-100)

    Returns:
        Result with success status and details
    """
    if blocked := _read_only_block("update_rollout"):
        return blocked
    if err := _validate_rollout(rollout_percentage):
        return {"error": err}

    client = get_client_from_context()

    result = client.update_rollout(
        package_name=package_name,
        track=track,
        version_code=version_code,
        rollout_percentage=rollout_percentage,
    )

    return result.model_dump()


@mcp.tool()
def get_app_details(
    package_name: str,
    language: str = "en-US",
) -> dict[str, Any]:
    """Get app details including title, description, and developer info.

    Args:
        package_name: App package name
        language: Language code for localized content (default: en-US)

    Returns:
        App details including title, descriptions, and developer information
    """
    client = get_client_from_context()

    details = client.get_app_details(package_name, language)
    return details.model_dump()


# =============================================================================
# Reviews Tools
# =============================================================================


@mcp.tool()
def get_reviews(
    package_name: str,
    max_results: int = 50,
    translation_language: str | None = None,
) -> list[dict[str, Any]]:
    """Get recent reviews for an app.

    Args:
        package_name: App package name
        max_results: Maximum number of reviews to return (default: 50, max: 100)
        translation_language: Optional language code to translate reviews to

    Returns:
        List of reviews with ratings, comments, and author info
    """
    client = get_client_from_context()

    reviews = client.get_reviews(
        package_name=package_name,
        max_results=min(max_results, 100),
        translation_language=translation_language,
    )

    return [review.model_dump() for review in reviews]


@mcp.tool()
def reply_to_review(
    package_name: str,
    review_id: str,
    reply_text: str,
) -> dict[str, Any]:
    """Reply to a user review.

    Args:
        package_name: App package name
        review_id: ID of the review to reply to (from get_reviews)
        reply_text: Text of the reply (will be visible to the reviewer)

    Returns:
        Result with success status
    """
    if blocked := _read_only_block("reply_to_review"):
        return blocked
    client = get_client_from_context()

    result = client.reply_to_review(
        package_name=package_name,
        review_id=review_id,
        reply_text=reply_text,
    )

    return result.model_dump()


@mcp.tool()
def get_review(
    package_name: str,
    review_id: str,
    translation_language: str | None = None,
) -> dict[str, Any]:
    """Get a single user review by its ID.

    Args:
        package_name: App package name
        review_id: Review ID (from get_reviews)
        translation_language: Optional language to translate the review to

    Returns:
        The review with rating, text, and any developer reply
    """
    client = get_client_from_context()

    review = client.get_review(
        package_name=package_name,
        review_id=review_id,
        translation_language=translation_language,
    )

    return review.model_dump()


# =============================================================================
# Subscription Tools
# =============================================================================


@mcp.tool()
def list_subscriptions(package_name: str) -> list[dict[str, Any]]:
    """List all subscription products for an app.

    Args:
        package_name: App package name

    Returns:
        List of subscription products with their base plans
    """
    client = get_client_from_context()

    subscriptions = client.list_subscriptions(package_name)
    return [sub.model_dump() for sub in subscriptions]


@mcp.tool()
def get_subscription_status(
    package_name: str,
    subscription_id: str,
    purchase_token: str,
) -> dict[str, Any]:
    """Get the status of a subscription purchase.

    Args:
        package_name: App package name
        subscription_id: Subscription product ID
        purchase_token: The purchase token from the client app

    Returns:
        Subscription purchase status including expiry and renewal info
    """
    client = get_client_from_context()

    status = client.get_subscription_purchase(
        package_name=package_name,
        subscription_id=subscription_id,
        token=purchase_token,
    )

    return status.model_dump()


@mcp.tool()
def list_voided_purchases(
    package_name: str,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """List voided purchases (refunds, chargebacks).

    Args:
        package_name: App package name
        max_results: Maximum number of results (default: 100)

    Returns:
        List of voided purchases with reason and timing
    """
    client = get_client_from_context()

    voided = client.list_voided_purchases(
        package_name=package_name,
        max_results=max_results,
    )

    return [v.model_dump() for v in voided]


@mcp.tool()
def get_product_purchase(
    package_name: str,
    product_id: str,
    purchase_token: str,
) -> dict[str, Any]:
    """Get the status of an in-app product purchase.

    Args:
        package_name: App package name
        product_id: In-app product SKU
        purchase_token: The purchase token from the client app

    Returns:
        Product purchase status (purchase/consumption/acknowledgement state, order, region)
    """
    client = get_client_from_context()

    purchase = client.get_product_purchase(
        package_name=package_name,
        product_id=product_id,
        token=purchase_token,
    )

    return purchase.model_dump()


@mcp.tool()
def acknowledge_product_purchase(
    package_name: str,
    product_id: str,
    purchase_token: str,
    developer_payload: str | None = None,
) -> dict[str, Any]:
    """Acknowledge an in-app product purchase.

    Purchases not acknowledged within 3 days are automatically refunded.

    Args:
        package_name: App package name
        product_id: In-app product SKU
        purchase_token: The purchase token from the client app
        developer_payload: Optional payload to associate with the purchase

    Returns:
        Result with success status and details
    """
    if blocked := _read_only_block("acknowledge_product_purchase"):
        return blocked
    client = get_client_from_context()

    result = client.acknowledge_product_purchase(
        package_name=package_name,
        product_id=product_id,
        token=purchase_token,
        developer_payload=developer_payload,
    )

    return result.model_dump()


@mcp.tool()
def consume_product_purchase(
    package_name: str,
    product_id: str,
    purchase_token: str,
) -> dict[str, Any]:
    """Consume an in-app product purchase (for consumable products).

    Marks the product as consumed so the user can purchase it again.

    Args:
        package_name: App package name
        product_id: In-app product SKU
        purchase_token: The purchase token from the client app

    Returns:
        Result with success status and details
    """
    if blocked := _read_only_block("consume_product_purchase"):
        return blocked
    client = get_client_from_context()

    result = client.consume_product_purchase(
        package_name=package_name,
        product_id=product_id,
        token=purchase_token,
    )

    return result.model_dump()


@mcp.tool()
def refund_order(
    package_name: str,
    order_id: str,
    revoke: bool = False,
) -> dict[str, Any]:
    """Refund an order, optionally revoking the user's entitlement.

    Args:
        package_name: App package name
        order_id: Order ID to refund
        revoke: If True, also revoke the user's entitlement (default: False)

    Returns:
        Result with success status and details
    """
    if blocked := _read_only_block("refund_order"):
        return blocked
    client = get_client_from_context()

    result = client.refund_order(package_name=package_name, order_id=order_id, revoke=revoke)

    return result.model_dump()


@mcp.tool()
def cancel_subscription_purchase(
    package_name: str,
    purchase_token: str,
    cancellation_type: str = "USER_REQUESTED_STOP_RENEWALS",
) -> dict[str, Any]:
    """Cancel a subscription purchase.

    Args:
        package_name: App package name
        purchase_token: The purchase token from the client app
        cancellation_type: USER_REQUESTED_STOP_RENEWALS (default),
            DEVELOPER_REQUESTED_STOP_PAYMENTS, or CANCELLATION_TYPE_UNSPECIFIED

    Returns:
        Result with success status and details
    """
    if blocked := _read_only_block("cancel_subscription_purchase"):
        return blocked
    client = get_client_from_context()

    result = client.cancel_subscription_purchase(
        package_name=package_name,
        token=purchase_token,
        cancellation_type=cancellation_type,
    )

    return result.model_dump()


@mcp.tool()
def defer_subscription_purchase(
    package_name: str,
    purchase_token: str,
    defer_duration: str,
    etag: str,
) -> dict[str, Any]:
    """Defer a subscription purchase's next renewal.

    Args:
        package_name: App package name
        purchase_token: The purchase token from the client app
        defer_duration: Duration to defer, e.g. "604800s" for 7 days
        etag: Current etag of the subscription purchase

    Returns:
        Result with success status and new expiry details
    """
    if blocked := _read_only_block("defer_subscription_purchase"):
        return blocked
    client = get_client_from_context()

    result = client.defer_subscription_purchase(
        package_name=package_name,
        token=purchase_token,
        defer_duration=defer_duration,
        etag=etag,
    )

    return result.model_dump()


@mcp.tool()
def revoke_subscription_purchase(
    package_name: str,
    purchase_token: str,
    refund_type: str = "full",
) -> dict[str, Any]:
    """Revoke (refund) a subscription purchase.

    Args:
        package_name: App package name
        purchase_token: The purchase token from the client app
        refund_type: "full" or "prorated" (default: full)

    Returns:
        Result with success status and details
    """
    if blocked := _read_only_block("revoke_subscription_purchase"):
        return blocked
    if refund_type not in ("full", "prorated"):
        return {"error": "refund_type must be 'full' or 'prorated'"}
    client = get_client_from_context()

    result = client.revoke_subscription_purchase(
        package_name=package_name,
        token=purchase_token,
        refund_type=refund_type,
    )

    return result.model_dump()


@mcp.tool()
def get_product_purchase_v2(
    package_name: str,
    purchase_token: str,
) -> dict[str, Any]:
    """Get the status of an in-app product purchase using the v2 API.

    Unlike get_product_purchase, this identifies the purchase by token alone
    (no product ID) and returns line items and acknowledgement state.

    Args:
        package_name: App package name
        purchase_token: The purchase token from the client app

    Returns:
        Product purchase (v2) status
    """
    client = get_client_from_context()

    purchase = client.get_product_purchase_v2(package_name=package_name, token=purchase_token)

    return purchase.model_dump()


# =============================================================================
# Vitals Tools
# =============================================================================


@mcp.tool()
def get_vitals_overview(package_name: str) -> dict[str, Any]:
    """Get Android Vitals overview for an app (placeholder - requires Play Developer Reporting API).

    Returns placeholder data. Full implementation requires the separate
    Play Developer Reporting API, not the Play Developer API.

    Args:
        package_name: App package name

    Returns:
        Vitals overview placeholder
    """
    client = get_client_from_context()

    vitals = client.get_vitals_overview(package_name)
    return vitals.model_dump()


@mcp.tool()
def get_vitals_metrics(
    package_name: str,
    metric_type: str = "crashRate",
) -> list[dict[str, Any]]:
    """Get specific Android Vitals metrics (placeholder - requires Play Developer Reporting API).

    Returns placeholder data. Full implementation requires the separate
    Play Developer Reporting API, not the Play Developer API.

    Args:
        package_name: App package name
        metric_type: Type of metric to retrieve (crashRate, anrRate, etc.)

    Returns:
        List of vitals metrics placeholders
    """
    client = get_client_from_context()

    metrics = client.get_vitals_metrics(package_name, metric_type)
    return [metric.model_dump() for metric in metrics]


# =============================================================================
# In-App Products Tools
# =============================================================================


@mcp.tool()
def list_in_app_products(package_name: str) -> list[dict[str, Any]]:
    """List all in-app products for an app.

    Args:
        package_name: App package name

    Returns:
        List of in-app products with SKU, title, description, and pricing
    """
    client = get_client_from_context()

    products = client.list_in_app_products(package_name)
    return [product.model_dump() for product in products]


@mcp.tool()
def get_in_app_product(
    package_name: str,
    sku: str,
) -> dict[str, Any]:
    """Get details of a specific in-app product.

    Args:
        package_name: App package name
        sku: Product SKU identifier

    Returns:
        In-app product details including title, description, and pricing
    """
    client = get_client_from_context()

    product = client.get_in_app_product(package_name, sku)
    return product.model_dump()


@mcp.tool()
def create_in_app_product(
    package_name: str,
    product: dict[str, Any],
) -> dict[str, Any]:
    """Create a new in-app product in the catalog.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product: In-app product resource body (e.g. sku, purchaseType, defaultPrice,
            listings, status, defaultLanguage)

    Returns:
        The created in-app product
    """
    if blocked := _read_only_block("create_in_app_product"):
        return blocked
    client = get_client_from_context()

    result = client.create_in_app_product(package_name=package_name, product=product)
    return result.model_dump()


@mcp.tool()
def update_in_app_product(
    package_name: str,
    sku: str,
    product: dict[str, Any],
    auto_convert_missing_prices: bool = False,
) -> dict[str, Any]:
    """Update (replace) an existing in-app product.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        sku: Product SKU identifier
        product: In-app product resource body
        auto_convert_missing_prices: Auto-convert prices for regions without a
            specified price based on the default price (default: False)

    Returns:
        The updated in-app product
    """
    if blocked := _read_only_block("update_in_app_product"):
        return blocked
    client = get_client_from_context()

    result = client.update_in_app_product(
        package_name=package_name,
        sku=sku,
        product=product,
        auto_convert_missing_prices=auto_convert_missing_prices,
    )
    return result.model_dump()


@mcp.tool()
def patch_in_app_product(
    package_name: str,
    sku: str,
    product: dict[str, Any],
) -> dict[str, Any]:
    """Partially update an existing in-app product.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        sku: Product SKU identifier
        product: Partial in-app product resource body with fields to change

    Returns:
        The patched in-app product
    """
    if blocked := _read_only_block("patch_in_app_product"):
        return blocked
    client = get_client_from_context()

    result = client.patch_in_app_product(package_name=package_name, sku=sku, product=product)
    return result.model_dump()


@mcp.tool()
def delete_in_app_product(
    package_name: str,
    sku: str,
) -> dict[str, Any]:
    """Delete an in-app product from the catalog.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        sku: Product SKU identifier

    Returns:
        Result with success status
    """
    if blocked := _read_only_block("delete_in_app_product"):
        return blocked
    client = get_client_from_context()

    result = client.delete_in_app_product(package_name=package_name, sku=sku)
    return result.model_dump()


@mcp.tool()
def batch_get_in_app_products(
    package_name: str,
    skus: list[str],
) -> list[dict[str, Any]]:
    """Get details for multiple in-app products at once.

    Args:
        package_name: App package name
        skus: List of product SKUs to retrieve

    Returns:
        List of in-app products, in the same order as requested
    """
    client = get_client_from_context()

    products = client.batch_get_in_app_products(package_name=package_name, skus=skus)
    return [product.model_dump() for product in products]


@mcp.tool()
def batch_delete_in_app_products(
    package_name: str,
    skus: list[str],
) -> dict[str, Any]:
    """Delete multiple in-app products in a single operation.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        skus: List of product SKUs to delete

    Returns:
        Result with success status
    """
    if blocked := _read_only_block("batch_delete_in_app_products"):
        return blocked
    client = get_client_from_context()

    result = client.batch_delete_in_app_products(package_name=package_name, skus=skus)
    return result.model_dump()


# =============================================================================
# Subscription Catalog Tools
# =============================================================================


@mcp.tool()
def get_subscription(
    package_name: str,
    product_id: str,
) -> dict[str, Any]:
    """Get details of a specific subscription product.

    Args:
        package_name: App package name
        product_id: Subscription product ID

    Returns:
        Subscription product details including base plans
    """
    client = get_client_from_context()

    subscription = client.get_subscription(package_name, product_id)
    return subscription.model_dump()


@mcp.tool()
def create_subscription(
    package_name: str,
    product_id: str,
    subscription: dict[str, Any],
    regions_version: str = "2022/02",
) -> dict[str, Any]:
    """Create a new subscription product in the catalog.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Subscription product ID
        subscription: Subscription resource body (e.g. basePlans, listings)
        regions_version: Version of available regions for regional prices (default: "2022/02")

    Returns:
        The created subscription product
    """
    if blocked := _read_only_block("create_subscription"):
        return blocked
    client = get_client_from_context()

    result = client.create_subscription(
        package_name=package_name,
        product_id=product_id,
        subscription=subscription,
        regions_version=regions_version,
    )
    return result.model_dump()


@mcp.tool()
def patch_subscription(
    package_name: str,
    product_id: str,
    subscription: dict[str, Any],
    update_mask: str,
    regions_version: str = "2022/02",
) -> dict[str, Any]:
    """Partially update an existing subscription product.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Subscription product ID
        subscription: Partial Subscription resource body with fields to change
        update_mask: Comma-separated list of fields to update
        regions_version: Version of available regions for regional prices (default: "2022/02")

    Returns:
        The patched subscription product
    """
    if blocked := _read_only_block("patch_subscription"):
        return blocked
    client = get_client_from_context()

    result = client.patch_subscription(
        package_name=package_name,
        product_id=product_id,
        subscription=subscription,
        update_mask=update_mask,
        regions_version=regions_version,
    )
    return result.model_dump()


@mcp.tool()
def delete_subscription(
    package_name: str,
    product_id: str,
) -> dict[str, Any]:
    """Delete a subscription product from the catalog.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Subscription product ID

    Returns:
        Result with success status
    """
    if blocked := _read_only_block("delete_subscription"):
        return blocked
    client = get_client_from_context()

    result = client.delete_subscription(package_name=package_name, product_id=product_id)
    return result.model_dump()


@mcp.tool()
def batch_get_subscriptions(
    package_name: str,
    product_ids: list[str],
) -> list[dict[str, Any]]:
    """Get details for multiple subscription products at once.

    Args:
        package_name: App package name
        product_ids: List of subscription product IDs to retrieve

    Returns:
        List of subscription products
    """
    client = get_client_from_context()

    subscriptions = client.batch_get_subscriptions(
        package_name=package_name, product_ids=product_ids
    )
    return [sub.model_dump() for sub in subscriptions]


@mcp.tool()
def batch_update_subscriptions(
    package_name: str,
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]] | dict[str, Any]:
    """Update multiple subscription products in a single operation.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        requests: List of UpdateSubscriptionRequest bodies (each with subscription,
            updateMask, and optional regionsVersion)

    Returns:
        List of updated subscription products, or an error object in read-only mode
    """
    if blocked := _read_only_block("batch_update_subscriptions"):
        return blocked
    client = get_client_from_context()

    subscriptions = client.batch_update_subscriptions(package_name=package_name, requests=requests)
    return [sub.model_dump() for sub in subscriptions]


# =============================================================================
# Subscription Base Plan Tools
# =============================================================================


@mcp.tool()
def activate_base_plan(
    package_name: str,
    product_id: str,
    base_plan_id: str,
) -> dict[str, Any]:
    """Activate a subscription base plan, making it available to new subscribers.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        base_plan_id: Base plan ID to activate

    Returns:
        The updated subscription product
    """
    if blocked := _read_only_block("activate_base_plan"):
        return blocked
    client = get_client_from_context()

    result = client.activate_base_plan(
        package_name=package_name,
        product_id=product_id,
        base_plan_id=base_plan_id,
    )
    return result.model_dump()


@mcp.tool()
def deactivate_base_plan(
    package_name: str,
    product_id: str,
    base_plan_id: str,
) -> dict[str, Any]:
    """Deactivate a subscription base plan, making it unavailable to new subscribers.

    Existing subscribers keep their subscription. Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        base_plan_id: Base plan ID to deactivate

    Returns:
        The updated subscription product
    """
    if blocked := _read_only_block("deactivate_base_plan"):
        return blocked
    client = get_client_from_context()

    result = client.deactivate_base_plan(
        package_name=package_name,
        product_id=product_id,
        base_plan_id=base_plan_id,
    )
    return result.model_dump()


@mcp.tool()
def delete_base_plan(
    package_name: str,
    product_id: str,
    base_plan_id: str,
) -> dict[str, Any]:
    """Delete a subscription base plan.

    Only inactive base plans with no active subscribers can be deleted.
    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        base_plan_id: Base plan ID to delete

    Returns:
        Result with success status
    """
    if blocked := _read_only_block("delete_base_plan"):
        return blocked
    client = get_client_from_context()

    result = client.delete_base_plan(
        package_name=package_name,
        product_id=product_id,
        base_plan_id=base_plan_id,
    )
    return result.model_dump()


@mcp.tool()
def migrate_base_plan_prices(
    package_name: str,
    product_id: str,
    base_plan_id: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    """Migrate subscribers to the current base plan prices.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        base_plan_id: Base plan ID whose prices to migrate
        request: MigrateBasePlanPricesRequest body (e.g. regionalPriceMigrations,
            regionsVersion)

    Returns:
        The MigrateBasePlanPricesResponse (raw dict), or an error object in read-only mode
    """
    if blocked := _read_only_block("migrate_base_plan_prices"):
        return blocked
    client = get_client_from_context()

    return client.migrate_base_plan_prices(
        package_name=package_name,
        product_id=product_id,
        base_plan_id=base_plan_id,
        request=request,
    )


@mcp.tool()
def batch_migrate_base_plan_prices(
    package_name: str,
    product_id: str,
    requests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Migrate prices for multiple base plans in a single operation.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        requests: List of MigrateBasePlanPricesRequest bodies

    Returns:
        The BatchMigrateBasePlanPricesResponse (raw dict), or an error object in
        read-only mode
    """
    if blocked := _read_only_block("batch_migrate_base_plan_prices"):
        return blocked
    client = get_client_from_context()

    return client.batch_migrate_base_plan_prices(
        package_name=package_name,
        product_id=product_id,
        requests=requests,
    )


@mcp.tool()
def batch_update_base_plan_states(
    package_name: str,
    product_id: str,
    requests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Activate or deactivate multiple base plans in a single operation.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        requests: List of UpdateBasePlanStateRequest bodies (each with a nested
            activateBasePlanRequest or deactivateBasePlanRequest)

    Returns:
        The updated subscription product
    """
    if blocked := _read_only_block("batch_update_base_plan_states"):
        return blocked
    client = get_client_from_context()

    result = client.batch_update_base_plan_states(
        package_name=package_name,
        product_id=product_id,
        requests=requests,
    )
    return result.model_dump()


# =============================================================================
# Store Listings Tools
# =============================================================================


@mcp.tool()
def get_listing(
    package_name: str,
    language: str = "en-US",
) -> dict[str, Any]:
    """Get store listing for a specific language.

    Args:
        package_name: App package name
        language: Language code (e.g., en-US, es-ES, fr-FR)

    Returns:
        Store listing with title, descriptions, and video
    """
    client = get_client_from_context()

    listing = client.get_listing(package_name, language)
    return listing.model_dump()


@mcp.tool()
def update_listing(
    package_name: str,
    language: str,
    title: str | None = None,
    full_description: str | None = None,
    short_description: str | None = None,
    video: str | None = None,
) -> dict[str, Any]:
    """Update store listing for a specific language.

    Args:
        package_name: App package name
        language: Language code (e.g., en-US, es-ES, fr-FR)
        title: App title (max 50 characters, optional)
        full_description: Full description (max 4000 characters, optional)
        short_description: Short description (max 80 characters, optional)
        video: YouTube video URL (optional)

    Returns:
        Update result with success status
    """
    if blocked := _read_only_block("update_listing"):
        return blocked
    client = get_client_from_context()

    result = client.update_listing(
        package_name=package_name,
        language=language,
        title=title,
        full_description=full_description,
        short_description=short_description,
        video=video,
    )
    return result.model_dump()


@mcp.tool()
def list_all_listings(package_name: str) -> list[dict[str, Any]]:
    """List all store listings for all languages.

    Args:
        package_name: App package name

    Returns:
        List of store listings for all configured languages
    """
    client = get_client_from_context()

    listings = client.list_all_listings(package_name)
    return [listing.model_dump() for listing in listings]


# =============================================================================
# Testers Management Tools
# =============================================================================


@mcp.tool()
def get_testers(
    package_name: str,
    track: str,
) -> dict[str, Any]:
    """Get testers for a specific testing track.

    Args:
        package_name: App package name
        track: Track name (internal, alpha, beta)

    Returns:
        Tester information with list of email addresses
    """
    client = get_client_from_context()

    testers = client.get_testers(package_name, track)
    return testers.model_dump()


@mcp.tool()
def update_testers(
    package_name: str,
    track: str,
    google_groups: list[str],
) -> dict[str, Any]:
    """Update testers for a specific testing track.

    Args:
        package_name: App package name
        track: Track name (internal, alpha, beta)
        google_groups: List of Google Group email addresses

    Returns:
        Update result with success status
    """
    if blocked := _read_only_block("update_testers"):
        return blocked
    client = get_client_from_context()

    result = client.update_testers(package_name, track, google_groups)
    return result


# =============================================================================
# Orders Tools
# =============================================================================


@mcp.tool()
def get_order(
    package_name: str,
    order_id: str,
) -> dict[str, Any]:
    """Get detailed order/transaction information.

    Args:
        package_name: App package name
        order_id: Order ID to retrieve

    Returns:
        Order details including product, purchase state, and token
    """
    client = get_client_from_context()

    order = client.get_order(package_name, order_id)
    return order.model_dump()


@mcp.tool()
def batch_get_orders(
    package_name: str,
    order_ids: list[str],
) -> list[dict[str, Any]]:
    """Get detailed information for multiple orders at once.

    Args:
        package_name: App package name
        order_ids: List of order IDs to retrieve (1-1000)

    Returns:
        List of order details
    """
    client = get_client_from_context()

    orders = client.batch_get_orders(package_name=package_name, order_ids=order_ids)
    return [order.model_dump() for order in orders]


# =============================================================================
# Expansion Files Tools
# =============================================================================


@mcp.tool()
def get_expansion_file(
    package_name: str,
    version_code: int,
    expansion_file_type: str = "main",
) -> dict[str, Any]:
    """Get APK expansion file information.

    Expansion files are used for large apps (especially games) that exceed
    the 100MB APK size limit.

    Args:
        package_name: App package name
        version_code: APK version code
        expansion_file_type: Type of expansion file (main or patch)

    Returns:
        Expansion file information including size and references
    """
    client = get_client_from_context()

    expansion_file = client.get_expansion_file(package_name, version_code, expansion_file_type)
    return expansion_file.model_dump()


# =============================================================================
# Validation Tools
# =============================================================================


@mcp.tool()
def validate_package_name(package_name: str) -> dict[str, Any]:
    """Validate package name format before using it in other operations.

    Args:
        package_name: Package name to validate (e.g., com.example.myapp)

    Returns:
        Validation result with any errors found
    """
    client = get_client_from_context()

    errors = client.validate_package_name(package_name)
    return {
        "valid": len(errors) == 0,
        "errors": [error.model_dump() for error in errors],
        "package_name": package_name,
    }


@mcp.tool()
def validate_track(track: str) -> dict[str, Any]:
    """Validate track name before using it in deployment operations.

    Args:
        track: Track name to validate (internal, alpha, beta, production)

    Returns:
        Validation result with any errors found
    """
    client = get_client_from_context()

    errors = client.validate_track(track)
    return {
        "valid": len(errors) == 0,
        "errors": [error.model_dump() for error in errors],
        "track": track,
    }


@mcp.tool()
def validate_listing_text(
    title: str | None = None,
    short_description: str | None = None,
    full_description: str | None = None,
) -> dict[str, Any]:
    """Validate store listing text lengths before updating.

    Args:
        title: App title (max 50 characters)
        short_description: Short description (max 80 characters)
        full_description: Full description (max 4000 characters)

    Returns:
        Validation result with any errors found
    """
    client = get_client_from_context()

    errors = client.validate_listing_text(title, short_description, full_description)
    return {
        "valid": len(errors) == 0,
        "errors": [error.model_dump() for error in errors],
    }


# =============================================================================
# Batch Operations Tools
# =============================================================================


@mcp.tool()
def batch_deploy(
    package_name: str,
    file_path: str,
    tracks: list[str],
    release_notes: str | None = None,
    rollout_percentages: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Deploy an app to multiple tracks in a single operation.

    This is useful for deploying to internal and alpha tracks simultaneously,
    or for promoting to multiple testing tracks at once.

    Args:
        package_name: App package name
        file_path: Absolute path to APK or AAB file
        tracks: List of tracks to deploy to (e.g., ["internal", "alpha"])
        release_notes: Optional release notes for all tracks
        rollout_percentages: Optional dict mapping track names to rollout percentages

    Returns:
        Batch deployment result with individual results for each track
    """
    if blocked := _read_only_block("batch_deploy"):
        return blocked
    if err := _validate_deploy_file(file_path):
        return {"error": err}

    if rollout_percentages:
        for track_name, pct in rollout_percentages.items():
            if not (0.0 <= pct <= 100.0):
                return {
                    "error": f"rollout_percentage for track '{track_name}' must be between 0.0 and 100.0"
                }

    client = get_client_from_context()

    result = client.batch_deploy(
        package_name=package_name,
        file_path=file_path,
        tracks=tracks,
        release_notes=release_notes,
        rollout_percentages=rollout_percentages,
    )
    return result.model_dump()


# =============================================================================
# HTTP Endpoints for Streamable Transport
# =============================================================================


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:  # noqa: ARG001
    """Health check endpoint for monitoring and load balancers."""
    return JSONResponse({"status": "healthy", "service": "play-store-mcp"})


@mcp.custom_route("/credentials", methods=["POST"])
async def update_credentials(request: Request) -> JSONResponse:
    """Update Google Play Store credentials via HTTP POST.

    Management endpoint - restricted to localhost only.

    This endpoint allows local clients to provide credentials when using
    streamable-http transport. Accepts JSON credentials in the request body.

    Request body should be one of:
    - {"credentials": {...}} - Service account JSON object
    - {"credentials": "..."} - Service account JSON string
    - {"credentials_base64": "..."} - Base64-encoded service account JSON

    Returns:
        JSON response with success status
    """
    # Management endpoint: only allow requests from localhost
    client_host = request.client.host if request.client else None
    try:
        is_loopback = client_host is not None and ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        return JSONResponse(
            {"success": False, "error": "This endpoint is only accessible from localhost"},
            status_code=403,
        )

    try:
        body = await request.json()

        credentials = body.get("credentials")
        credentials_base64 = body.get("credentials_base64")

        if not credentials and not credentials_base64:
            return JSONResponse(
                {
                    "success": False,
                    "error": "Missing 'credentials' or 'credentials_base64' in request body",
                },
                status_code=400,
            )

        # Create new client with provided credentials
        if credentials_base64:
            # Decode base64 credentials
            try:
                decoded = base64.b64decode(credentials_base64).decode("utf-8")
                credentials_dict = json.loads(decoded)
                new_client = PlayStoreClient(credentials_json=credentials_dict)
            except (binascii.Error, UnicodeDecodeError) as e:
                return JSONResponse(
                    {"success": False, "error": f"Invalid base64 encoding: {e}"},
                    status_code=400,
                )
            except json.JSONDecodeError:
                return JSONResponse(
                    {"success": False, "error": "Invalid JSON in base64-decoded credentials"},
                    status_code=400,
                )
        elif credentials:
            if isinstance(credentials, str):
                # Validate it's valid JSON
                try:
                    json.loads(credentials)
                except json.JSONDecodeError:
                    return JSONResponse(
                        {"success": False, "error": "Invalid JSON in credentials string"},
                        status_code=400,
                    )
                new_client = PlayStoreClient(credentials_json=credentials)
            elif isinstance(credentials, dict):
                new_client = PlayStoreClient(credentials_json=credentials)
            else:
                return JSONResponse(
                    {"success": False, "error": "credentials must be a string or object"},
                    status_code=400,
                )

        # Validate credentials by attempting to get service
        try:
            _ = new_client._get_service()
        except PlayStoreClientError as e:
            return JSONResponse(
                {"success": False, "error": f"Invalid credentials: {e}"},
                status_code=401,
            )

        # Update the client in the shared state
        if hasattr(mcp, "_shared_state"):
            mcp._shared_state["client"] = new_client  # type: ignore[attr-defined]
            mcp._shared_state["credentials_updated"] = True  # type: ignore[attr-defined]

        logger.info("Credentials updated successfully via HTTP endpoint")

        return JSONResponse(
            {"success": True, "message": "Credentials updated successfully"},
            status_code=200,
        )

    except json.JSONDecodeError:
        return JSONResponse(
            {"success": False, "error": "Invalid JSON in request body"},
            status_code=400,
        )
    except Exception as e:
        logger.exception("Error updating credentials", error=str(e))
        return JSONResponse(
            {"success": False, "error": f"Internal error: {e}"},
            status_code=500,
        )


# =============================================================================
# Entry Point
# =============================================================================


def main(argv: list[str] | None = None) -> None:
    """Run the Play Store MCP Server."""
    parser = argparse.ArgumentParser(description="Play Store MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help="Transport protocol (default: stdio, or set MCP_TRANSPORT env var)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", "127.0.0.1"),
        help="Host to bind to for network transports (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", "8000")),
        help="Port to bind to for network transports (default: 8000)",
    )
    parser.add_argument(
        "--credentials",
        default=os.environ.get("GOOGLE_PLAY_STORE_CREDENTIALS"),
        help="Path to service account JSON key or JSON content (default: GOOGLE_PLAY_STORE_CREDENTIALS env var)",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        default=_env_read_only(),
        help="Disable all write operations (or set PLAY_STORE_MCP_READ_ONLY=1)",
    )
    args = parser.parse_args(argv)

    if args.credentials:
        os.environ["GOOGLE_PLAY_STORE_CREDENTIALS"] = args.credentials

    set_read_only(args.read_only)

    logger.info(
        "Starting Play Store MCP Server",
        transport=args.transport,
        host=args.host if args.transport != "stdio" else None,
        port=args.port if args.transport != "stdio" else None,
        read_only=READ_ONLY,
    )

    if args.transport != "stdio":
        mcp.settings.host = args.host
        mcp.settings.port = args.port

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
