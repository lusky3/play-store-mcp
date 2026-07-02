"""Play Store MCP Server - Main server implementation."""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import ipaddress
import json
import logging
import os
import secrets
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
# One-Time Product Catalog Tools
# =============================================================================


@mcp.tool()
def get_one_time_product(
    package_name: str,
    product_id: str,
) -> dict[str, Any]:
    """Get details of a specific one-time product.

    Args:
        package_name: App package name
        product_id: One-time product ID

    Returns:
        One-time product details including listings and purchase options
    """
    client = get_client_from_context()

    product = client.get_one_time_product(package_name, product_id)
    return product.model_dump()


@mcp.tool()
def list_one_time_products(
    package_name: str,
) -> list[dict[str, Any]]:
    """List all one-time products for an app.

    Args:
        package_name: App package name

    Returns:
        List of one-time products
    """
    client = get_client_from_context()

    products = client.list_one_time_products(package_name)
    return [product.model_dump() for product in products]


@mcp.tool()
def batch_get_one_time_products(
    package_name: str,
    product_ids: list[str],
) -> list[dict[str, Any]]:
    """Get details for multiple one-time products at once.

    Args:
        package_name: App package name
        product_ids: List of one-time product IDs to retrieve

    Returns:
        List of one-time products
    """
    client = get_client_from_context()

    products = client.batch_get_one_time_products(
        package_name=package_name, product_ids=product_ids
    )
    return [product.model_dump() for product in products]


@mcp.tool()
def patch_one_time_product(
    package_name: str,
    product_id: str,
    product: dict[str, Any],
    update_mask: str,
    regions_version: str = "2022/02",
) -> dict[str, Any]:
    """Create or update a one-time product (patch is create-or-update).

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: One-time product ID
        product: Partial OneTimeProduct resource body with fields to change
        update_mask: Comma-separated list of fields to update
        regions_version: Version of available regions for regional prices (default: "2022/02")

    Returns:
        The patched one-time product
    """
    if blocked := _read_only_block("patch_one_time_product"):
        return blocked
    client = get_client_from_context()

    result = client.patch_one_time_product(
        package_name=package_name,
        product_id=product_id,
        product=product,
        update_mask=update_mask,
        regions_version=regions_version,
    )
    return result.model_dump()


@mcp.tool()
def delete_one_time_product(
    package_name: str,
    product_id: str,
) -> dict[str, Any]:
    """Delete a one-time product from the catalog.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: One-time product ID

    Returns:
        Result with success status
    """
    if blocked := _read_only_block("delete_one_time_product"):
        return blocked
    client = get_client_from_context()

    result = client.delete_one_time_product(package_name=package_name, product_id=product_id)
    return result.model_dump()


@mcp.tool()
def batch_update_one_time_products(
    package_name: str,
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]] | dict[str, Any]:
    """Update multiple one-time products in a single operation.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        requests: List of UpdateOneTimeProductRequest bodies (each with oneTimeProduct,
            updateMask, and optional regionsVersion / allowMissing)

    Returns:
        List of updated one-time products, or an error object in read-only mode
    """
    if blocked := _read_only_block("batch_update_one_time_products"):
        return blocked
    client = get_client_from_context()

    products = client.batch_update_one_time_products(package_name=package_name, requests=requests)
    return [product.model_dump() for product in products]


@mcp.tool()
def batch_delete_one_time_products(
    package_name: str,
    requests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Delete multiple one-time products in a single operation.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        requests: List of DeleteOneTimeProductRequest bodies (each with productId
            and optional packageName / latencyTolerance)

    Returns:
        Result with success status
    """
    if blocked := _read_only_block("batch_delete_one_time_products"):
        return blocked
    client = get_client_from_context()

    result = client.batch_delete_one_time_products(package_name=package_name, requests=requests)
    return result.model_dump()


# =============================================================================
# One-Time Product Purchase Option Tools
# =============================================================================


@mcp.tool()
def batch_delete_purchase_options(
    package_name: str,
    product_id: str,
    requests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Delete multiple purchase options from a one-time product in a single operation.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent one-time product ID
        requests: List of DeletePurchaseOptionRequest bodies (each with purchaseOptionId
            and optional latencyTolerance)

    Returns:
        Result with success status
    """
    if blocked := _read_only_block("batch_delete_purchase_options"):
        return blocked
    client = get_client_from_context()

    result = client.batch_delete_purchase_options(
        package_name=package_name, product_id=product_id, requests=requests
    )
    return result.model_dump()


@mcp.tool()
def batch_update_purchase_option_states(
    package_name: str,
    product_id: str,
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]] | dict[str, Any]:
    """Activate or deactivate multiple purchase options in a single operation.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent one-time product ID
        requests: List of UpdatePurchaseOptionStateRequest bodies (each with a nested
            activatePurchaseOptionRequest or deactivatePurchaseOptionRequest)

    Returns:
        List of updated one-time products, or an error object in read-only mode
    """
    if blocked := _read_only_block("batch_update_purchase_option_states"):
        return blocked
    client = get_client_from_context()

    products = client.batch_update_purchase_option_states(
        package_name=package_name, product_id=product_id, requests=requests
    )
    return [product.model_dump() for product in products]


# =============================================================================
# One-Time Product Purchase Option Offer Tools
# =============================================================================


@mcp.tool()
def list_purchase_option_offers(
    package_name: str,
    product_id: str,
    purchase_option_id: str,
) -> list[dict[str, Any]]:
    """List all offers for a one-time product purchase option.

    Args:
        package_name: App package name
        product_id: Parent one-time product ID ('-' wildcard lists across products)
        purchase_option_id: Parent purchase option ID ('-' wildcard lists across options)

    Returns:
        List of one-time product offers
    """
    client = get_client_from_context()

    offers = client.list_purchase_option_offers(
        package_name=package_name,
        product_id=product_id,
        purchase_option_id=purchase_option_id,
    )
    return [offer.model_dump() for offer in offers]


@mcp.tool()
def batch_get_purchase_option_offers(
    package_name: str,
    product_id: str,
    purchase_option_id: str,
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Get details for multiple one-time product offers at once.

    Args:
        package_name: App package name
        product_id: Parent one-time product ID ('-' wildcard allowed)
        purchase_option_id: Parent purchase option ID ('-' wildcard allowed)
        requests: List of GetOneTimeProductOfferRequest bodies

    Returns:
        List of one-time product offers
    """
    client = get_client_from_context()

    offers = client.batch_get_purchase_option_offers(
        package_name=package_name,
        product_id=product_id,
        purchase_option_id=purchase_option_id,
        requests=requests,
    )
    return [offer.model_dump() for offer in offers]


@mcp.tool()
def activate_purchase_option_offer(
    package_name: str,
    product_id: str,
    purchase_option_id: str,
    offer_id: str,
) -> dict[str, Any]:
    """Activate a one-time product offer, making it available to eligible buyers.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent one-time product ID
        purchase_option_id: Parent purchase option ID
        offer_id: One-time product offer ID to activate

    Returns:
        The updated one-time product offer
    """
    if blocked := _read_only_block("activate_purchase_option_offer"):
        return blocked
    client = get_client_from_context()

    result = client.activate_purchase_option_offer(
        package_name=package_name,
        product_id=product_id,
        purchase_option_id=purchase_option_id,
        offer_id=offer_id,
    )
    return result.model_dump()


@mcp.tool()
def deactivate_purchase_option_offer(
    package_name: str,
    product_id: str,
    purchase_option_id: str,
    offer_id: str,
) -> dict[str, Any]:
    """Deactivate a one-time product offer, making it unavailable to new buyers.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent one-time product ID
        purchase_option_id: Parent purchase option ID
        offer_id: One-time product offer ID to deactivate

    Returns:
        The updated one-time product offer
    """
    if blocked := _read_only_block("deactivate_purchase_option_offer"):
        return blocked
    client = get_client_from_context()

    result = client.deactivate_purchase_option_offer(
        package_name=package_name,
        product_id=product_id,
        purchase_option_id=purchase_option_id,
        offer_id=offer_id,
    )
    return result.model_dump()


@mcp.tool()
def cancel_purchase_option_offer(
    package_name: str,
    product_id: str,
    purchase_option_id: str,
    offer_id: str,
) -> dict[str, Any]:
    """Cancel a one-time product offer (e.g. a pre-order offer).

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent one-time product ID
        purchase_option_id: Parent purchase option ID
        offer_id: One-time product offer ID to cancel

    Returns:
        The updated one-time product offer
    """
    if blocked := _read_only_block("cancel_purchase_option_offer"):
        return blocked
    client = get_client_from_context()

    result = client.cancel_purchase_option_offer(
        package_name=package_name,
        product_id=product_id,
        purchase_option_id=purchase_option_id,
        offer_id=offer_id,
    )
    return result.model_dump()


@mcp.tool()
def batch_update_purchase_option_offers(
    package_name: str,
    product_id: str,
    purchase_option_id: str,
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]] | dict[str, Any]:
    """Create or update multiple one-time product offers in a single operation.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent one-time product ID ('-' wildcard allowed)
        purchase_option_id: Parent purchase option ID ('-' wildcard allowed)
        requests: List of UpdateOneTimeProductOfferRequest bodies (each with
            oneTimeProductOffer, updateMask, and optional allowMissing / latencyTolerance)

    Returns:
        List of updated one-time product offers, or an error object in read-only mode
    """
    if blocked := _read_only_block("batch_update_purchase_option_offers"):
        return blocked
    client = get_client_from_context()

    offers = client.batch_update_purchase_option_offers(
        package_name=package_name,
        product_id=product_id,
        purchase_option_id=purchase_option_id,
        requests=requests,
    )
    return [offer.model_dump() for offer in offers]


@mcp.tool()
def batch_update_purchase_option_offer_states(
    package_name: str,
    product_id: str,
    purchase_option_id: str,
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]] | dict[str, Any]:
    """Activate, deactivate or cancel multiple one-time product offers in a single operation.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent one-time product ID ('-' wildcard allowed)
        purchase_option_id: Parent purchase option ID ('-' wildcard allowed)
        requests: List of UpdateOneTimeProductOfferStateRequest bodies (each with a nested
            activate/deactivate/cancel one-time product offer request)

    Returns:
        List of updated one-time product offers, or an error object in read-only mode
    """
    if blocked := _read_only_block("batch_update_purchase_option_offer_states"):
        return blocked
    client = get_client_from_context()

    offers = client.batch_update_purchase_option_offer_states(
        package_name=package_name,
        product_id=product_id,
        purchase_option_id=purchase_option_id,
        requests=requests,
    )
    return [offer.model_dump() for offer in offers]


@mcp.tool()
def batch_delete_purchase_option_offers(
    package_name: str,
    product_id: str,
    purchase_option_id: str,
    requests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Delete multiple one-time product offers in a single operation.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent one-time product ID ('-' wildcard allowed)
        purchase_option_id: Parent purchase option ID ('-' wildcard allowed)
        requests: List of DeleteOneTimeProductOfferRequest bodies (each with offerId
            and optional latencyTolerance)

    Returns:
        Result with success status
    """
    if blocked := _read_only_block("batch_delete_purchase_option_offers"):
        return blocked
    client = get_client_from_context()

    result = client.batch_delete_purchase_option_offers(
        package_name=package_name,
        product_id=product_id,
        purchase_option_id=purchase_option_id,
        requests=requests,
    )
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
) -> list[dict[str, Any]] | dict[str, Any]:
    """Activate or deactivate multiple base plans in a single operation.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        requests: List of UpdateBasePlanStateRequest bodies (each with a nested
            activateBasePlanRequest or deactivateBasePlanRequest)

    Returns:
        The updated subscriptions, one per request
    """
    if blocked := _read_only_block("batch_update_base_plan_states"):
        return blocked
    client = get_client_from_context()

    results = client.batch_update_base_plan_states(
        package_name=package_name,
        product_id=product_id,
        requests=requests,
    )
    return [result.model_dump() for result in results]


# =============================================================================
# Subscription Offer Tools
# =============================================================================


@mcp.tool()
def get_subscription_offer(
    package_name: str,
    product_id: str,
    base_plan_id: str,
    offer_id: str,
) -> dict[str, Any]:
    """Get details of a specific subscription offer.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        base_plan_id: Parent base plan ID
        offer_id: Subscription offer ID

    Returns:
        The subscription offer details
    """
    client = get_client_from_context()

    offer = client.get_subscription_offer(
        package_name=package_name,
        product_id=product_id,
        base_plan_id=base_plan_id,
        offer_id=offer_id,
    )
    return offer.model_dump()


@mcp.tool()
def list_subscription_offers(
    package_name: str,
    product_id: str,
    base_plan_id: str,
) -> list[dict[str, Any]]:
    """List all offers for a subscription base plan.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        base_plan_id: Parent base plan ID ('-' wildcard lists offers across base plans)

    Returns:
        List of subscription offers
    """
    client = get_client_from_context()

    offers = client.list_subscription_offers(
        package_name=package_name,
        product_id=product_id,
        base_plan_id=base_plan_id,
    )
    return [offer.model_dump() for offer in offers]


@mcp.tool()
def create_subscription_offer(
    package_name: str,
    product_id: str,
    base_plan_id: str,
    offer_id: str,
    offer: dict[str, Any],
    regions_version: str = "2022/02",
) -> dict[str, Any]:
    """Create a new subscription offer.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        base_plan_id: Parent base plan ID
        offer_id: Subscription offer ID
        offer: SubscriptionOffer resource body (e.g. phases, regionalConfigs, targeting)
        regions_version: Version of available regions for regional prices (default: "2022/02")

    Returns:
        The created subscription offer
    """
    if blocked := _read_only_block("create_subscription_offer"):
        return blocked
    client = get_client_from_context()

    result = client.create_subscription_offer(
        package_name=package_name,
        product_id=product_id,
        base_plan_id=base_plan_id,
        offer_id=offer_id,
        offer=offer,
        regions_version=regions_version,
    )
    return result.model_dump()


@mcp.tool()
def patch_subscription_offer(
    package_name: str,
    product_id: str,
    base_plan_id: str,
    offer_id: str,
    offer: dict[str, Any],
    update_mask: str,
    regions_version: str = "2022/02",
) -> dict[str, Any]:
    """Partially update an existing subscription offer.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        base_plan_id: Parent base plan ID
        offer_id: Subscription offer ID
        offer: Partial SubscriptionOffer resource body with fields to change
        update_mask: Comma-separated list of fields to update
        regions_version: Version of available regions for regional prices (default: "2022/02")

    Returns:
        The patched subscription offer
    """
    if blocked := _read_only_block("patch_subscription_offer"):
        return blocked
    client = get_client_from_context()

    result = client.patch_subscription_offer(
        package_name=package_name,
        product_id=product_id,
        base_plan_id=base_plan_id,
        offer_id=offer_id,
        offer=offer,
        update_mask=update_mask,
        regions_version=regions_version,
    )
    return result.model_dump()


@mcp.tool()
def activate_subscription_offer(
    package_name: str,
    product_id: str,
    base_plan_id: str,
    offer_id: str,
) -> dict[str, Any]:
    """Activate a subscription offer, making it available to eligible subscribers.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        base_plan_id: Parent base plan ID
        offer_id: Subscription offer ID to activate

    Returns:
        The updated subscription offer
    """
    if blocked := _read_only_block("activate_subscription_offer"):
        return blocked
    client = get_client_from_context()

    result = client.activate_subscription_offer(
        package_name=package_name,
        product_id=product_id,
        base_plan_id=base_plan_id,
        offer_id=offer_id,
    )
    return result.model_dump()


@mcp.tool()
def deactivate_subscription_offer(
    package_name: str,
    product_id: str,
    base_plan_id: str,
    offer_id: str,
) -> dict[str, Any]:
    """Deactivate a subscription offer, making it unavailable to new subscribers.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        base_plan_id: Parent base plan ID
        offer_id: Subscription offer ID to deactivate

    Returns:
        The updated subscription offer
    """
    if blocked := _read_only_block("deactivate_subscription_offer"):
        return blocked
    client = get_client_from_context()

    result = client.deactivate_subscription_offer(
        package_name=package_name,
        product_id=product_id,
        base_plan_id=base_plan_id,
        offer_id=offer_id,
    )
    return result.model_dump()


@mcp.tool()
def delete_subscription_offer(
    package_name: str,
    product_id: str,
    base_plan_id: str,
    offer_id: str,
) -> dict[str, Any]:
    """Delete a subscription offer.

    Only inactive offers with no active subscribers can be deleted.
    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        base_plan_id: Parent base plan ID
        offer_id: Subscription offer ID to delete

    Returns:
        Result with success status
    """
    if blocked := _read_only_block("delete_subscription_offer"):
        return blocked
    client = get_client_from_context()

    result = client.delete_subscription_offer(
        package_name=package_name,
        product_id=product_id,
        base_plan_id=base_plan_id,
        offer_id=offer_id,
    )
    return result.model_dump()


@mcp.tool()
def batch_get_subscription_offers(
    package_name: str,
    product_id: str,
    base_plan_id: str,
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Get details for multiple subscription offers in a single operation.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        base_plan_id: Parent base plan ID ('-' wildcard allowed)
        requests: List of GetSubscriptionOfferRequest bodies

    Returns:
        List of subscription offers
    """
    client = get_client_from_context()

    offers = client.batch_get_subscription_offers(
        package_name=package_name,
        product_id=product_id,
        base_plan_id=base_plan_id,
        requests=requests,
    )
    return [offer.model_dump() for offer in offers]


@mcp.tool()
def batch_update_subscription_offers(
    package_name: str,
    product_id: str,
    base_plan_id: str,
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]] | dict[str, Any]:
    """Update multiple subscription offers in a single operation.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        base_plan_id: Parent base plan ID ('-' wildcard allowed)
        requests: List of UpdateSubscriptionOfferRequest bodies (each with
            subscriptionOffer, updateMask, and optional regionsVersion)

    Returns:
        List of updated subscription offers, or an error object in read-only mode
    """
    if blocked := _read_only_block("batch_update_subscription_offers"):
        return blocked
    client = get_client_from_context()

    offers = client.batch_update_subscription_offers(
        package_name=package_name,
        product_id=product_id,
        base_plan_id=base_plan_id,
        requests=requests,
    )
    return [offer.model_dump() for offer in offers]


@mcp.tool()
def batch_update_subscription_offer_states(
    package_name: str,
    product_id: str,
    base_plan_id: str,
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]] | dict[str, Any]:
    """Activate or deactivate multiple subscription offers in a single operation.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        product_id: Parent subscription product ID
        base_plan_id: Parent base plan ID ('-' wildcard allowed)
        requests: List of UpdateSubscriptionOfferStateRequest bodies (each with a
            nested activateSubscriptionOfferRequest or deactivateSubscriptionOfferRequest)

    Returns:
        The updated subscription offers, one per request
    """
    if blocked := _read_only_block("batch_update_subscription_offer_states"):
        return blocked
    client = get_client_from_context()

    offers = client.batch_update_subscription_offer_states(
        package_name=package_name,
        product_id=product_id,
        base_plan_id=base_plan_id,
        requests=requests,
    )
    return [offer.model_dump() for offer in offers]


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
# External Transactions Tools
# =============================================================================


@mcp.tool()
def get_external_transaction(
    package_name: str,
    external_transaction_id: str,
) -> dict[str, Any]:
    """Get an external (alternative billing) transaction.

    Args:
        package_name: App package name
        external_transaction_id: External transaction ID

    Returns:
        External transaction details including state, amounts, and create time
    """
    client = get_client_from_context()

    transaction = client.get_external_transaction(
        package_name=package_name,
        external_transaction_id=external_transaction_id,
    )
    return transaction.model_dump()


@mcp.tool()
def create_external_transaction(
    package_name: str,
    external_transaction_id: str,
    transaction: dict[str, Any],
) -> dict[str, Any]:
    """Create an external (alternative billing) transaction.

    Args:
        package_name: App package name
        external_transaction_id: External transaction ID to assign
        transaction: ExternalTransaction resource body

    Returns:
        The created external transaction
    """
    if blocked := _read_only_block("create_external_transaction"):
        return blocked
    client = get_client_from_context()

    result = client.create_external_transaction(
        package_name=package_name,
        external_transaction_id=external_transaction_id,
        transaction=transaction,
    )
    return result.model_dump()


@mcp.tool()
def refund_external_transaction(
    package_name: str,
    external_transaction_id: str,
    refund: dict[str, Any],
) -> dict[str, Any]:
    """Refund an external (alternative billing) transaction.

    Args:
        package_name: App package name
        external_transaction_id: External transaction ID to refund
        refund: RefundExternalTransactionRequest body (e.g. refundTime plus
            fullRefund or partialRefund)

    Returns:
        The refunded external transaction
    """
    if blocked := _read_only_block("refund_external_transaction"):
        return blocked
    client = get_client_from_context()

    result = client.refund_external_transaction(
        package_name=package_name,
        external_transaction_id=external_transaction_id,
        refund=refund,
    )
    return result.model_dump()


# =============================================================================
# Device Tier Config Tools
# =============================================================================


@mcp.tool()
def get_device_tier_config(
    package_name: str,
    device_tier_config_id: str,
) -> dict[str, Any]:
    """Get a device tier config.

    Args:
        package_name: App package name
        device_tier_config_id: Device tier config ID

    Returns:
        Device tier config details including device groups, tier set, and country sets
    """
    client = get_client_from_context()

    config = client.get_device_tier_config(
        package_name=package_name,
        device_tier_config_id=device_tier_config_id,
    )
    return config.model_dump()


@mcp.tool()
def list_device_tier_configs(package_name: str) -> list[dict[str, Any]]:
    """List all device tier configs for an app.

    Args:
        package_name: App package name

    Returns:
        List of device tier configs with device groups, tier set, and country sets
    """
    client = get_client_from_context()

    configs = client.list_device_tier_configs(package_name)
    return [config.model_dump() for config in configs]


@mcp.tool()
def create_device_tier_config(
    package_name: str,
    config: dict[str, Any],
    allow_unknown_devices: bool = False,
) -> dict[str, Any]:
    """Create a new device tier config.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        config: DeviceTierConfig resource body (deviceGroups, deviceTierSet,
            userCountrySets)
        allow_unknown_devices: Accept device IDs unknown to Play's catalog rather
            than rejecting them (default: False)

    Returns:
        The created device tier config
    """
    if blocked := _read_only_block("create_device_tier_config"):
        return blocked
    client = get_client_from_context()

    result = client.create_device_tier_config(
        package_name=package_name,
        config=config,
        allow_unknown_devices=allow_unknown_devices,
    )
    return result.model_dump()


# =============================================================================
# Account Access Tools (Users & Grants)
# =============================================================================


@mcp.tool()
def list_users(developer_id: str) -> list[dict[str, Any]]:
    """List users with access to a developer account.

    Args:
        developer_id: Developer account ID

    Returns:
        List of users with their access state and account-level permissions
    """
    client = get_client_from_context()

    users = client.list_users(developer_id)
    return [user.model_dump() for user in users]


@mcp.tool()
def create_user(developer_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Grant a user access to a developer account.

    Disabled in read-only mode.

    Args:
        developer_id: Developer account ID
        user: User resource body (email, developerAccountPermissions,
            expirationTime, grants)

    Returns:
        The created user
    """
    if blocked := _read_only_block("create_user"):
        return blocked
    client = get_client_from_context()

    result = client.create_user(developer_id=developer_id, user=user)
    return result.model_dump()


@mcp.tool()
def update_user(
    developer_id: str,
    email: str,
    user: dict[str, Any],
    update_mask: str,
) -> dict[str, Any]:
    """Update a user's account access.

    Disabled in read-only mode.

    Args:
        developer_id: Developer account ID
        email: Email of the user to update
        user: User resource body with the fields to update
        update_mask: Comma-separated list of fields to update (e.g.
            "developerAccountPermissions,expirationTime")

    Returns:
        The updated user
    """
    if blocked := _read_only_block("update_user"):
        return blocked
    client = get_client_from_context()

    result = client.update_user(
        developer_id=developer_id,
        email=email,
        user=user,
        update_mask=update_mask,
    )
    return result.model_dump()


@mcp.tool()
def delete_user(developer_id: str, email: str) -> dict[str, Any]:
    """Remove a user's access to a developer account.

    Disabled in read-only mode.

    Args:
        developer_id: Developer account ID
        email: Email of the user to remove

    Returns:
        Access result with success status
    """
    if blocked := _read_only_block("delete_user"):
        return blocked
    client = get_client_from_context()

    result = client.delete_user(developer_id=developer_id, email=email)
    return result.model_dump()


@mcp.tool()
def create_grant(developer_id: str, email: str, grant: dict[str, Any]) -> dict[str, Any]:
    """Grant a user app-level access.

    Disabled in read-only mode.

    Args:
        developer_id: Developer account ID
        email: Email of the user to grant access to
        grant: Grant resource body (packageName, appLevelPermissions)

    Returns:
        The created grant
    """
    if blocked := _read_only_block("create_grant"):
        return blocked
    client = get_client_from_context()

    result = client.create_grant(developer_id=developer_id, email=email, grant=grant)
    return result.model_dump()


@mcp.tool()
def update_grant(
    developer_id: str,
    email: str,
    package_name: str,
    grant: dict[str, Any],
    update_mask: str,
) -> dict[str, Any]:
    """Update a user's app-level access.

    Disabled in read-only mode.

    Args:
        developer_id: Developer account ID
        email: Email of the user the grant belongs to
        package_name: App package name the grant applies to
        grant: Grant resource body with the fields to update
        update_mask: Comma-separated list of fields to update (e.g.
            "appLevelPermissions")

    Returns:
        The updated grant
    """
    if blocked := _read_only_block("update_grant"):
        return blocked
    client = get_client_from_context()

    result = client.update_grant(
        developer_id=developer_id,
        email=email,
        package_name=package_name,
        grant=grant,
        update_mask=update_mask,
    )
    return result.model_dump()


@mcp.tool()
def delete_grant(developer_id: str, email: str, package_name: str) -> dict[str, Any]:
    """Remove a user's app-level access.

    Disabled in read-only mode.

    Args:
        developer_id: Developer account ID
        email: Email of the user the grant belongs to
        package_name: App package name the grant applies to

    Returns:
        Access result with success status
    """
    if blocked := _read_only_block("delete_grant"):
        return blocked
    client = get_client_from_context()

    result = client.delete_grant(
        developer_id=developer_id,
        email=email,
        package_name=package_name,
    )
    return result.model_dump()


# =============================================================================
# Data Safety Tools
# =============================================================================


@mcp.tool()
def set_data_safety(
    package_name: str,
    safety_labels: dict[str, Any],
) -> dict[str, Any]:
    """Write the data safety labels declaration of an app.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        safety_labels: SafetyLabelsUpdateRequest resource body. Contains a
            `safetyLabels` string with the contents of the Data Safety CSV

    Returns:
        The result of the update
    """
    if blocked := _read_only_block("set_data_safety"):
        return blocked
    client = get_client_from_context()

    result = client.set_data_safety(
        package_name=package_name,
        safety_labels=safety_labels,
    )
    return result.model_dump()


# =============================================================================
# App Recovery Tools
# =============================================================================


@mcp.tool()
def list_app_recoveries(package_name: str, version_code: int) -> list[dict[str, Any]]:
    """List all app recovery actions for an app version.

    Args:
        package_name: App package name
        version_code: App version code the recovery actions target

    Returns:
        List of app recovery actions with ID, status, targeting, and create time
    """
    client = get_client_from_context()

    recoveries = client.list_app_recoveries(package_name, version_code)
    return [recovery.model_dump() for recovery in recoveries]


@mcp.tool()
def create_app_recovery(
    package_name: str,
    recovery: dict[str, Any],
) -> dict[str, Any]:
    """Create a draft app recovery action.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        recovery: CreateDraftAppRecoveryRequest resource body (e.g.
            `remoteInAppUpdate` plus `targeting`)

    Returns:
        The created app recovery action
    """
    if blocked := _read_only_block("create_app_recovery"):
        return blocked
    client = get_client_from_context()

    result = client.create_app_recovery(
        package_name=package_name,
        recovery=recovery,
    )
    return result.model_dump()


@mcp.tool()
def deploy_app_recovery(
    package_name: str,
    app_recovery_id: str,
) -> dict[str, Any]:
    """Deploy an app recovery action to users.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        app_recovery_id: App recovery action ID

    Returns:
        The result of the deploy action
    """
    if blocked := _read_only_block("deploy_app_recovery"):
        return blocked
    client = get_client_from_context()

    result = client.deploy_app_recovery(
        package_name=package_name,
        app_recovery_id=app_recovery_id,
    )
    return result.model_dump()


@mcp.tool()
def cancel_app_recovery(
    package_name: str,
    app_recovery_id: str,
) -> dict[str, Any]:
    """Cancel an app recovery action.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        app_recovery_id: App recovery action ID

    Returns:
        The result of the cancel action
    """
    if blocked := _read_only_block("cancel_app_recovery"):
        return blocked
    client = get_client_from_context()

    result = client.cancel_app_recovery(
        package_name=package_name,
        app_recovery_id=app_recovery_id,
    )
    return result.model_dump()


@mcp.tool()
def add_app_recovery_targeting(
    package_name: str,
    app_recovery_id: str,
    targeting: dict[str, Any],
) -> dict[str, Any]:
    """Add targeting to an app recovery action.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        app_recovery_id: App recovery action ID
        targeting: AddTargetingRequest resource body (e.g. a `targetingUpdate`
            object)

    Returns:
        The result of the add-targeting action
    """
    if blocked := _read_only_block("add_app_recovery_targeting"):
        return blocked
    client = get_client_from_context()

    result = client.add_app_recovery_targeting(
        package_name=package_name,
        app_recovery_id=app_recovery_id,
        targeting=targeting,
    )
    return result.model_dump()


# =============================================================================
# Generated APKs Tools
# =============================================================================


@mcp.tool()
def list_generated_apks(
    package_name: str,
    version_code: int,
) -> list[dict[str, Any]]:
    """List the APKs Google Play generated from an app bundle version.

    Returns one entry per downloadable generated APK (split, standalone,
    universal, asset pack slice, or recovery), each with a download ID that can
    be passed to `download_generated_apk`.

    Args:
        package_name: App package name
        version_code: Version code of the app bundle

    Returns:
        List of downloadable generated APKs with their download IDs and types
    """
    client = get_client_from_context()

    downloads = client.list_generated_apks(
        package_name=package_name,
        version_code=version_code,
    )
    return [download.model_dump() for download in downloads]


@mcp.tool()
def download_generated_apk(
    package_name: str,
    version_code: int,
    download_id: str,
    destination_path: str,
) -> dict[str, Any]:
    """Download a single generated APK to a local file.

    Args:
        package_name: App package name
        version_code: Version code of the app bundle
        download_id: Download ID of the generated APK (from `list_generated_apks`)
        destination_path: Local path to write the APK bytes to

    Returns:
        Download result with success status and destination path
    """
    client = get_client_from_context()

    result = client.download_generated_apk(
        package_name=package_name,
        version_code=version_code,
        download_id=download_id,
        destination_path=destination_path,
    )
    return result.model_dump()


# =============================================================================
# System APK Variants Tools
# =============================================================================


@mcp.tool()
def get_system_apk_variant(
    package_name: str,
    version_code: int,
    variant_id: int,
) -> dict[str, Any]:
    """Get a previously created system APK variant.

    Args:
        package_name: App package name
        version_code: Version code of the app bundle
        variant_id: ID of the system APK variant

    Returns:
        System APK variant details including device spec and options
    """
    client = get_client_from_context()

    variant = client.get_system_apk_variant(
        package_name=package_name,
        version_code=version_code,
        variant_id=variant_id,
    )
    return variant.model_dump()


@mcp.tool()
def list_system_apk_variants(
    package_name: str,
    version_code: int,
) -> list[dict[str, Any]]:
    """List previously created system APK variants for an app bundle version.

    Args:
        package_name: App package name
        version_code: Version code of the app bundle

    Returns:
        List of system APK variants with their IDs, device specs, and options
    """
    client = get_client_from_context()

    variants = client.list_system_apk_variants(
        package_name=package_name,
        version_code=version_code,
    )
    return [variant.model_dump() for variant in variants]


@mcp.tool()
def create_system_apk_variant(
    package_name: str,
    version_code: int,
    variant: dict[str, Any],
) -> dict[str, Any]:
    """Create a system APK variant from an uploaded app bundle.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        version_code: Version code of the app bundle
        variant: Variant resource body (e.g. `deviceSpec` and `options`)

    Returns:
        The created system APK variant
    """
    if blocked := _read_only_block("create_system_apk_variant"):
        return blocked
    client = get_client_from_context()

    result = client.create_system_apk_variant(
        package_name=package_name,
        version_code=version_code,
        variant=variant,
    )
    return result.model_dump()


@mcp.tool()
def download_system_apk_variant(
    package_name: str,
    version_code: int,
    variant_id: int,
    destination_path: str,
) -> dict[str, Any]:
    """Download a previously created system APK variant to a local file.

    Args:
        package_name: App package name
        version_code: Version code of the app bundle
        variant_id: ID of the system APK variant (from `list_system_apk_variants`)
        destination_path: Local path to write the APK bytes to

    Returns:
        Download result with success status and destination path
    """
    client = get_client_from_context()

    result = client.download_system_apk_variant(
        package_name=package_name,
        version_code=version_code,
        variant_id=variant_id,
        destination_path=destination_path,
    )
    return result.model_dump()


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
# Edit Upload Tools (APKs, bundles, deobfuscation & expansion files)
# =============================================================================


@mcp.tool()
def list_apks(package_name: str) -> list[dict[str, Any]]:
    """List the APKs currently uploaded for an app.

    Args:
        package_name: App package name

    Returns:
        List of APKs, each with its version code and binary sha1/sha256 hashes
    """
    client = get_client_from_context()

    apks = client.list_apks(package_name)
    return [apk.model_dump() for apk in apks]


@mcp.tool()
def list_bundles(package_name: str) -> list[dict[str, Any]]:
    """List the Android App Bundles currently uploaded for an app.

    Args:
        package_name: App package name

    Returns:
        List of app bundles, each with its version code and sha1/sha256 hashes
    """
    client = get_client_from_context()

    bundles = client.list_bundles(package_name)
    return [bundle.model_dump() for bundle in bundles]


@mcp.tool()
def upload_apk(package_name: str, apk_path: str) -> dict[str, Any]:
    """Upload an APK to a new edit and commit it.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        apk_path: Local path to the APK file

    Returns:
        The uploaded APK with its version code and binary sha1/sha256 hashes
    """
    if blocked := _read_only_block("upload_apk"):
        return blocked
    client = get_client_from_context()

    apk = client.upload_apk(package_name=package_name, apk_path=apk_path)
    return apk.model_dump()


@mcp.tool()
def upload_bundle(package_name: str, bundle_path: str) -> dict[str, Any]:
    """Upload an Android App Bundle (.aab) to a new edit and commit it.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        bundle_path: Local path to the app bundle (.aab) file

    Returns:
        The uploaded app bundle with its version code and sha1/sha256 hashes
    """
    if blocked := _read_only_block("upload_bundle"):
        return blocked
    client = get_client_from_context()

    bundle = client.upload_bundle(package_name=package_name, bundle_path=bundle_path)
    return bundle.model_dump()


@mcp.tool()
def upload_deobfuscation_file(
    package_name: str,
    version_code: int,
    file_path: str,
    deobfuscation_file_type: str = "proguard",
) -> dict[str, Any]:
    """Upload a deobfuscation (ProGuard mapping or native symbols) file.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        version_code: APK version code the file applies to
        file_path: Local path to the deobfuscation file
        deobfuscation_file_type: Type of file - one of: proguard, nativeCode

    Returns:
        The uploaded deobfuscation file configuration with its symbol type
    """
    if blocked := _read_only_block("upload_deobfuscation_file"):
        return blocked
    client = get_client_from_context()

    deobfuscation_file = client.upload_deobfuscation_file(
        package_name=package_name,
        version_code=version_code,
        file_path=file_path,
        deobfuscation_file_type=deobfuscation_file_type,
    )
    return deobfuscation_file.model_dump()


@mcp.tool()
def upload_expansion_file(
    package_name: str,
    version_code: int,
    file_path: str,
    expansion_file_type: str = "main",
) -> dict[str, Any]:
    """Upload an APK expansion file (OBB) to a new edit and commit it.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        version_code: APK version code the file applies to
        file_path: Local path to the expansion file
        expansion_file_type: Type of expansion file - one of: main, patch

    Returns:
        The uploaded expansion file information including size and references
    """
    if blocked := _read_only_block("upload_expansion_file"):
        return blocked
    client = get_client_from_context()

    expansion_file = client.upload_expansion_file(
        package_name=package_name,
        version_code=version_code,
        file_path=file_path,
        expansion_file_type=expansion_file_type,
    )
    return expansion_file.model_dump()


# =============================================================================
# Store Listing Image Tools
# =============================================================================


@mcp.tool()
def list_images(package_name: str, language: str, image_type: str) -> list[dict[str, Any]]:
    """List the store-listing images for a language and image type.

    Args:
        package_name: App package name
        language: Language localization code (BCP-47 tag, e.g. en-US)
        image_type: Image type - one of: phoneScreenshots, sevenInchScreenshots,
            tenInchScreenshots, tvScreenshots, wearScreenshots, icon, featureGraphic,
            tvBanner

    Returns:
        List of images, each with its ID, serving URL and sha1/sha256 hashes
    """
    client = get_client_from_context()

    images = client.list_images(package_name, language, image_type)
    return [image.model_dump() for image in images]


@mcp.tool()
def upload_image(
    package_name: str, language: str, image_type: str, image_path: str
) -> dict[str, Any]:
    """Upload a store-listing image (PNG or JPEG) to a new edit and commit it.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        language: Language localization code (BCP-47 tag, e.g. en-US)
        image_type: Image type - one of: phoneScreenshots, sevenInchScreenshots,
            tenInchScreenshots, tvScreenshots, wearScreenshots, icon, featureGraphic,
            tvBanner
        image_path: Local path to the image file (PNG or JPEG)

    Returns:
        The uploaded image with its ID, serving URL and sha1/sha256 hashes
    """
    if blocked := _read_only_block("upload_image"):
        return blocked
    client = get_client_from_context()

    image = client.upload_image(
        package_name=package_name,
        language=language,
        image_type=image_type,
        image_path=image_path,
    )
    return image.model_dump()


@mcp.tool()
def delete_image(
    package_name: str, language: str, image_type: str, image_id: str
) -> dict[str, Any]:
    """Delete a single store-listing image by ID and commit the edit.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        language: Language localization code (BCP-47 tag, e.g. en-US)
        image_type: Image type the image belongs to
        image_id: Unique identifier of the image to delete

    Returns:
        Delete result with success status and deleted count
    """
    if blocked := _read_only_block("delete_image"):
        return blocked
    client = get_client_from_context()

    result = client.delete_image(
        package_name=package_name,
        language=language,
        image_type=image_type,
        image_id=image_id,
    )
    return result.model_dump()


@mcp.tool()
def delete_all_images(package_name: str, language: str, image_type: str) -> dict[str, Any]:
    """Delete all store-listing images for a language and image type; commit the edit.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        language: Language localization code (BCP-47 tag, e.g. en-US)
        image_type: Image type to clear all images for

    Returns:
        Delete result with success status and the number of images deleted
    """
    if blocked := _read_only_block("delete_all_images"):
        return blocked
    client = get_client_from_context()

    result = client.delete_all_images(
        package_name=package_name,
        language=language,
        image_type=image_type,
    )
    return result.model_dump()


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
# Internal App Sharing Tools
# =============================================================================


@mcp.tool()
def upload_internal_app_sharing_apk(
    package_name: str,
    apk_path: str,
) -> dict[str, Any]:
    """Upload an APK to internal app sharing.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        apk_path: Local path to the APK file

    Returns:
        The uploaded artifact with download URL, certificate fingerprint, and sha256
    """
    if blocked := _read_only_block("upload_internal_app_sharing_apk"):
        return blocked
    client = get_client_from_context()

    artifact = client.upload_internal_app_sharing_apk(
        package_name=package_name,
        apk_path=apk_path,
    )
    return artifact.model_dump()


@mcp.tool()
def upload_internal_app_sharing_bundle(
    package_name: str,
    bundle_path: str,
) -> dict[str, Any]:
    """Upload an app bundle (.aab) to internal app sharing.

    Disabled in read-only mode.

    Args:
        package_name: App package name
        bundle_path: Local path to the app bundle (.aab) file

    Returns:
        The uploaded artifact with download URL, certificate fingerprint, and sha256
    """
    if blocked := _read_only_block("upload_internal_app_sharing_bundle"):
        return blocked
    client = get_client_from_context()

    artifact = client.upload_internal_app_sharing_bundle(
        package_name=package_name,
        bundle_path=bundle_path,
    )
    return artifact.model_dump()


# =============================================================================
# HTTP Endpoints for Streamable Transport
# =============================================================================


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:  # noqa: ARG001
    """Health check endpoint for monitoring and load balancers."""
    return JSONResponse({"status": "healthy", "service": "play-store-mcp"})


def _authorize_credentials_request(request: Request) -> JSONResponse | None:
    """Authorize a POST to the /credentials management endpoint.

    If PLAY_STORE_MCP_ADMIN_TOKEN is set, an ``Authorization: Bearer <token>``
    header matching it (constant-time comparison) is required, and the request
    is accepted from any host. This is the correct mode behind a reverse proxy,
    where ``request.client.host`` is the proxy address and cannot be trusted as
    a "localhost" signal.

    If no admin token is configured, the endpoint accepts loopback (localhost)
    peers only — the historical behavior.

    Returns an error ``JSONResponse`` if the request is not authorized, else None.
    """
    admin_token = os.environ.get("PLAY_STORE_MCP_ADMIN_TOKEN")
    if admin_token:
        provided = request.headers.get("authorization", "")
        expected = f"Bearer {admin_token}"
        # Compare as bytes: secrets.compare_digest raises TypeError on non-ASCII
        # str operands, and Starlette decodes header values as latin-1, so a
        # crafted header could otherwise turn a 401 into an uncaught 500.
        if not (
            provided and secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))
        ):
            return JSONResponse(
                {"success": False, "error": "Missing or invalid admin token"},
                status_code=401,
            )
        return None

    # No admin token configured: only allow loopback peers.
    client_host = request.client.host if request.client else None
    try:
        is_loopback = client_host is not None and ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        return JSONResponse(
            {
                "success": False,
                "error": (
                    "This endpoint is only accessible from localhost. Set "
                    "PLAY_STORE_MCP_ADMIN_TOKEN and send an 'Authorization: Bearer' header "
                    "to allow authenticated access (required when running behind a proxy, "
                    "where the peer address is the proxy and not the real client)."
                ),
            },
            status_code=403,
        )
    return None


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
    # Management endpoint: authorize by admin token (if configured) or localhost.
    auth_error = _authorize_credentials_request(request)
    if auth_error is not None:
        return auth_error

    new_client: PlayStoreClient | None = None
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

        if (
            new_client is None
        ):  # pragma: no cover - defensive; branches above always assign or return
            return JSONResponse(
                {"success": False, "error": "No credentials could be parsed from the request"},
                status_code=400,
            )

        # Validate credentials by attempting to build the service. This does
        # blocking network I/O, so run it off the event loop.
        try:
            await asyncio.to_thread(new_client._get_service)
        except PlayStoreClientError:
            logger.warning("Credential validation failed for /credentials request")
            return JSONResponse(
                {"success": False, "error": "Invalid credentials"},
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
    except Exception:
        logger.exception("Error updating credentials")
        return JSONResponse(
            {"success": False, "error": "Internal server error"},
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
