"""Google Play Developer API client."""

from __future__ import annotations

import contextlib
import functools
import json
import os
import random
import re
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from play_store_mcp.models import (
    AccessResult,
    Apk,
    AppDetails,
    AppImage,
    AppRecovery,
    AppRecoveryResult,
    BatchDeploymentResult,
    Bundle,
    DataSafetyResult,
    DeobfuscationFile,
    DeploymentResult,
    DeviceTierConfig,
    DownloadResult,
    ExpansionFile,
    ExternalTransaction,
    GeneratedApksDownload,
    Grant,
    ImageDeleteResult,
    InAppProduct,
    InAppProductActionResult,
    InternalAppSharingArtifact,
    Listing,
    ListingUpdateResult,
    OneTimeProduct,
    OneTimeProductActionResult,
    OneTimeProductOffer,
    Order,
    OrderLineItem,
    OrderRefundResult,
    ProductPurchase,
    ProductPurchaseActionResult,
    ProductPurchaseV2,
    Release,
    Review,
    ReviewReplyResult,
    SubscriptionActionResult,
    SubscriptionCatalogResult,
    SubscriptionOffer,
    SubscriptionProduct,
    SubscriptionPurchase,
    SystemApkVariant,
    TesterInfo,
    TrackInfo,
    User,
    ValidationResult,
    VoidedPurchase,
)

if TYPE_CHECKING:
    from googleapiclient._apis.androidpublisher.v3 import AndroidPublisherResource

logger = structlog.get_logger(__name__)

# API scopes required for Play Developer API
SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds
MAX_BACKOFF = 32.0  # seconds

# HTTP methods whose requests are safe to retry on an ambiguous server error
# (500/503): repeating them cannot create a duplicate side effect. Non-idempotent
# requests (POST: create, upload, acknowledge, consume, refund, revoke, defer,
# commit, ...) are only retried on 429 (throttled, so never applied).
_IDEMPOTENT_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})

# Revocation contexts for subscription refunds (Purchases.subscriptionsv2.revoke)
_REVOCATION_CONTEXTS: dict[str, dict[str, dict]] = {
    "full": {"fullRefund": {}},
    "prorated": {"proratedRefund": {}},
}


class PlayStoreClientError(Exception):
    """Base exception for Play Store client errors."""


def _parse_timestamp(value: dict[str, Any] | None) -> datetime | None:
    """Parse a protobuf Timestamp {seconds, nanos} to datetime, or None."""
    if not value:
        return None
    seconds = value.get("seconds")
    if seconds is None:
        return None
    try:
        nanos = int(value.get("nanos", 0) or 0)
        return datetime.fromtimestamp(int(seconds) + nanos / 1_000_000_000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _parse_rfc3339(value: str | None) -> datetime | None:
    """Parse an RFC3339 timestamp string (e.g. "2024-10-02T15:01:23Z") to datetime.

    The subscriptions v2 API returns RFC3339 strings rather than the protobuf
    {seconds, nanos} form handled by ``_parse_timestamp``.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _parse_review(review_data: dict[str, Any]) -> Review | None:
    """Parse a Reviews API resource into a Review, or None if it has no user comment."""
    user_comment = None
    dev_comment = None
    for comment in review_data.get("comments", []):
        if "userComment" in comment:
            user_comment = comment["userComment"]
        if "developerComment" in comment:
            dev_comment = comment["developerComment"]

    if not user_comment:
        return None

    return Review(
        review_id=review_data.get("reviewId", ""),
        author_name=review_data.get("authorName", "Anonymous"),
        star_rating=user_comment.get("starRating", 0),
        comment=user_comment.get("text", ""),
        language=user_comment.get("reviewerLanguage", "en"),
        device=user_comment.get("device"),
        android_version=user_comment.get("androidOsVersion"),
        app_version_code=user_comment.get("appVersionCode"),
        app_version_name=user_comment.get("appVersionName"),
        last_modified=_parse_timestamp(user_comment.get("lastModified")),
        developer_reply=dev_comment.get("text") if dev_comment else None,
        developer_reply_time=(
            _parse_timestamp(dev_comment.get("lastModified")) if dev_comment else None
        ),
    )


def _is_retryable_status(status: int, *, retry_server_errors: bool) -> bool:
    """Whether an HTTP error status should be retried.

    429 (rate limited) is always retryable: the request was throttled, not
    applied, so repeating it is safe for any HTTP method. 500/503 are retried
    only when ``retry_server_errors`` is set (idempotent requests), because the
    server may have already applied a non-idempotent request before erroring.
    """
    if status == 429:
        return True
    return retry_server_errors and status in (500, 503)


def _run_with_backoff(call, *, retry_server_errors=True):  # type: ignore[no-untyped-def]
    """Run ``call`` with exponential-backoff retries on transient errors."""
    retries = 0
    backoff = INITIAL_BACKOFF

    while retries < MAX_RETRIES:
        try:
            return call()
        except HttpError as e:
            if not _is_retryable_status(e.resp.status, retry_server_errors=retry_server_errors):
                raise
            retries += 1
            if retries >= MAX_RETRIES:
                raise

            # Add jitter to prevent thundering herd
            sleep_time = backoff * (0.5 + random.random())  # noqa: S311 # nosec B311 — non-crypto jitter for retry backoff
            logger.warning(
                "API error, retrying",
                status=e.resp.status,
                retry=retries,
                sleep=sleep_time,
            )
            time.sleep(sleep_time)
            backoff = min(backoff * 2, MAX_BACKOFF)

    # The loop above always returns or raises while MAX_RETRIES >= 1. This
    # guards against a misconfigured MAX_RETRIES so a call can never fall
    # through and implicitly return None.
    raise PlayStoreClientError(  # pragma: no cover - only reachable if MAX_RETRIES <= 0
        "Retry attempts exhausted without a result"
    )


def retry_with_backoff(func):  # type: ignore[no-untyped-def]
    """Decorator to retry a call on transient errors (429/500/503).

    For idempotent operations only (e.g. building the API service). Individual
    Play API requests go through ``PlayStoreClient._execute``, which decides
    whether to retry server errors based on the request's HTTP method.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _run_with_backoff(lambda: func(*args, **kwargs), retry_server_errors=True)

    return wrapper


class PlayStoreClient:
    """Client for interacting with Google Play Developer API."""

    def __init__(
        self,
        credentials_path: str | None = None,
        credentials_json: str | dict[str, Any] | None = None,
        application_name: str = "Play Store MCP Server",
        download_dir: str | None = None,
    ) -> None:
        """Initialize the Play Store client.

        Args:
            credentials_path: Path to service account JSON key.
                             Defaults to GOOGLE_APPLICATION_CREDENTIALS env var.
            credentials_json: JSON string or dictionary with service account credentials.
                             Defaults to GOOGLE_PLAY_STORE_CREDENTIALS env var.
            application_name: Application name for API requests.
            download_dir: Optional directory that download destinations are
                             confined to. Defaults to the PLAY_STORE_MCP_DOWNLOAD_DIR
                             env var. When unset, downloads may target any path
                             (single-user local case); when set, a destination
                             outside it is rejected.
        """
        self._credentials_path = credentials_path or os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )
        self._credentials_json = credentials_json or os.environ.get("GOOGLE_PLAY_STORE_CREDENTIALS")
        self._application_name = application_name
        self._download_dir = (
            download_dir
            if download_dir is not None
            else os.environ.get("PLAY_STORE_MCP_DOWNLOAD_DIR")
        )
        self._service: AndroidPublisherResource | None = None
        # Serializes API I/O on this client's single (non-thread-safe) httplib2
        # transport. The shared fallback client is used across concurrent tool
        # worker threads; per-request header clients each get their own lock.
        self._http_lock = threading.Lock()
        self._logger = logger.bind(component="PlayStoreClient")

    # =========================================================================
    # Validation Helpers
    # =========================================================================

    def validate_package_name(self, package_name: str) -> list[ValidationResult]:
        """Validate package name format.

        Args:
            package_name: Package name to validate.

        Returns:
            List of validation errors (empty if valid).
        """
        errors: list[ValidationResult] = []

        if not package_name:
            errors.append(
                ValidationResult(
                    field="package_name",
                    message="Package name cannot be empty",
                    value=package_name,
                )
            )
            return errors

        # Check format: must contain at least one dot
        if "." not in package_name:
            errors.append(
                ValidationResult(
                    field="package_name",
                    message="Package name must contain at least one dot (e.g., com.example.app)",
                    value=package_name,
                )
            )

        # Check for invalid characters
        if not re.match(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", package_name):
            errors.append(
                ValidationResult(
                    field="package_name",
                    message="Package name must start with lowercase letter and contain only lowercase letters, numbers, underscores, and dots",
                    value=package_name,
                )
            )

        return errors

    def validate_track(self, track: str) -> list[ValidationResult]:
        """Validate track name.

        Args:
            track: Track name to validate.

        Returns:
            List of validation errors (empty if valid).
        """
        errors: list[ValidationResult] = []
        valid_tracks = ["internal", "alpha", "beta", "production"]

        if track not in valid_tracks:
            errors.append(
                ValidationResult(
                    field="track",
                    message=f"Track must be one of: {', '.join(valid_tracks)}",
                    value=track,
                )
            )

        return errors

    def validate_listing_text(
        self,
        title: str | None = None,
        short_description: str | None = None,
        full_description: str | None = None,
    ) -> list[ValidationResult]:
        """Validate store listing text lengths.

        Args:
            title: App title (max 50 chars).
            short_description: Short description (max 80 chars).
            full_description: Full description (max 4000 chars).

        Returns:
            List of validation errors (empty if valid).
        """
        errors: list[ValidationResult] = []

        if title and len(title) > 50:
            errors.append(
                ValidationResult(
                    field="title",
                    message="Title must be 50 characters or less",
                    value=f"{len(title)} characters",
                )
            )

        if short_description and len(short_description) > 80:
            errors.append(
                ValidationResult(
                    field="short_description",
                    message="Short description must be 80 characters or less",
                    value=f"{len(short_description)} characters",
                )
            )

        if full_description and len(full_description) > 4000:
            errors.append(
                ValidationResult(
                    field="full_description",
                    message="Full description must be 4000 characters or less",
                    value=f"{len(full_description)} characters",
                )
            )

        return errors

    @retry_with_backoff
    def _get_service(self) -> AndroidPublisherResource:
        """Get or create the API service instance."""
        if self._service is not None:
            return self._service

        self._logger.info("Initializing Google Play Developer API client")

        try:
            credentials = None

            # Try credentials_json first (from string or dict)
            if self._credentials_json:
                if isinstance(self._credentials_json, str):
                    try:
                        # Check if it's actually JSON or a path to a file
                        if self._credentials_json.strip().startswith("{"):
                            creds_info = json.loads(self._credentials_json)
                            credentials = service_account.Credentials.from_service_account_info(
                                creds_info, scopes=SCOPES
                            )
                        elif Path(self._credentials_json).exists():
                            credentials = service_account.Credentials.from_service_account_file(
                                self._credentials_json, scopes=SCOPES
                            )
                    except json.JSONDecodeError:
                        # If it's not JSON, maybe it's a path that doesn't exist?
                        self._logger.warning(
                            "credentials_json string is not valid JSON and not a valid file path",
                        )

                elif isinstance(self._credentials_json, dict):
                    credentials = service_account.Credentials.from_service_account_info(
                        self._credentials_json, scopes=SCOPES
                    )

            # Fall back to credentials_path
            if not credentials and self._credentials_path:
                creds_path = Path(self._credentials_path)
                if creds_path.exists():
                    credentials = service_account.Credentials.from_service_account_file(
                        str(creds_path), scopes=SCOPES
                    )

            if not credentials:
                raise PlayStoreClientError(
                    "No valid credentials found. Set GOOGLE_APPLICATION_CREDENTIALS (path) "
                    "or GOOGLE_PLAY_STORE_CREDENTIALS (JSON or path)."
                )

            self._service = build(
                "androidpublisher",
                "v3",
                credentials=credentials,
                cache_discovery=False,
            )
            self._logger.info("API client initialized successfully")
            return self._service  # type: ignore[return-value]
        except Exception as e:
            if isinstance(e, PlayStoreClientError):
                raise
            self._logger.exception("Failed to initialize API client", error=str(e))
            raise PlayStoreClientError(f"Failed to initialize API client: {e}") from e

    def _execute(self, request: Any) -> Any:
        """Execute a googleapiclient request with retry/backoff.

        All Play API calls go through here. 429 (rate limited) is always
        retried; 500/503 are retried only for idempotent HTTP methods. A
        non-idempotent request (POST: create, upload, acknowledge, consume,
        refund, revoke, defer, commit, ...) is not retried on a 5xx, because
        the server may have already applied it and a retry could duplicate the
        side effect. Non-transient errors (e.g. 400/403/404) propagate to each
        caller's own ``except HttpError`` handling.
        """
        method = (getattr(request, "method", "") or "").upper()
        retry_server_errors = method in _IDEMPOTENT_HTTP_METHODS

        def _locked_execute() -> Any:
            # Hold the lock only around the actual transport call, not the
            # backoff sleep between attempts, so retries don't serialize waits.
            with self._http_lock:
                return request.execute()

        return _run_with_backoff(_locked_execute, retry_server_errors=retry_server_errors)

    def _create_edit(self, package_name: str) -> str:
        """Create a new edit for the package.

        Args:
            package_name: App package name.

        Returns:
            Edit ID.
        """
        service = self._get_service()
        try:
            result = self._execute(service.edits().insert(packageName=package_name, body={}))
        except HttpError as e:
            self._logger.exception("Failed to create edit", error=str(e))
            raise PlayStoreClientError(f"Failed to create edit: {e.reason}") from e
        edit_id: str = result["id"]
        self._logger.debug("Created edit", package_name=package_name, edit_id=edit_id)
        return edit_id

    def _commit_edit(self, package_name: str, edit_id: str) -> None:
        """Commit an edit.

        Args:
            package_name: App package name.
            edit_id: Edit ID to commit.
        """
        service = self._get_service()
        self._execute(service.edits().commit(packageName=package_name, editId=edit_id))
        self._logger.debug("Committed edit", package_name=package_name, edit_id=edit_id)

    def _delete_edit(self, package_name: str, edit_id: str) -> None:
        """Delete an edit without committing.

        Args:
            package_name: App package name.
            edit_id: Edit ID to delete.
        """
        service = self._get_service()
        try:
            self._execute(service.edits().delete(packageName=package_name, editId=edit_id))
            self._logger.debug("Deleted edit", package_name=package_name, edit_id=edit_id)
        except HttpError as e:
            # Edit may have already been committed or expired
            self._logger.debug("Edit cleanup failed", error=str(e))

    # =========================================================================
    # Publishing API
    # =========================================================================

    def get_releases(self, package_name: str) -> list[TrackInfo]:
        """Get release information for all tracks.

        Args:
            package_name: App package name.

        Returns:
            List of track information with releases.
        """
        self._logger.info("Fetching releases", package_name=package_name)
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            result = self._execute(
                service.edits().tracks().list(packageName=package_name, editId=edit_id)
            )

            tracks: list[TrackInfo] = []
            for track_data in result.get("tracks", []):
                releases: list[Release] = []
                for release_data in track_data.get("releases", []):
                    # Extract release notes
                    release_notes: dict[str, str] = {}
                    for note in release_data.get("releaseNotes", []):
                        release_notes[note.get("language", "en-US")] = note.get("text", "")

                    releases.append(
                        Release(
                            package_name=package_name,
                            track=track_data.get("track", "unknown"),
                            status=release_data.get("status", "unknown"),
                            version_codes=[int(vc) for vc in release_data.get("versionCodes", [])],
                            version_name=release_data.get("name"),
                            rollout_percentage=(release_data.get("userFraction", 1.0) * 100),
                            release_notes=release_notes,
                        )
                    )

                tracks.append(
                    TrackInfo(
                        track=track_data.get("track", "unknown"),
                        releases=releases,
                    )
                )

            return tracks
        except HttpError as e:
            self._logger.exception("Failed to fetch releases", error=str(e))
            raise PlayStoreClientError(f"Failed to fetch releases: {e.reason}") from e
        finally:
            self._delete_edit(package_name, edit_id)

    def deploy_app(
        self,
        package_name: str,
        track: str,
        file_path: str,
        release_notes: str | dict[str, str] | None = None,
        release_notes_language: str = "en-US",
        rollout_percentage: float = 100.0,
    ) -> DeploymentResult:
        """Deploy an APK or AAB to a track.

        Args:
            package_name: App package name.
            track: Target track (internal, alpha, beta, production).
            file_path: Path to APK or AAB file.
            release_notes: Release notes text (string for single language) or
                          dict mapping language codes to release notes for multiple languages.
            release_notes_language: Language code for release notes (used only if release_notes is a string).
            rollout_percentage: Rollout percentage (0-100).

        Returns:
            Deployment result.
        """
        self._logger.info(
            "Deploying app",
            package_name=package_name,
            track=track,
            file_path=file_path,
            rollout_percentage=rollout_percentage,
        )

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            return DeploymentResult(
                success=False,
                package_name=package_name,
                track=track,
                message=f"File not found: {file_path}",
                error="FileNotFoundError",
            )

        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            # Determine content type and upload method
            is_bundle = file_path.lower().endswith(".aab")
            content_type = (
                "application/octet-stream"
                if is_bundle
                else "application/vnd.android.package-archive"
            )

            media = MediaFileUpload(file_path, mimetype=content_type, resumable=True)

            if is_bundle:
                upload_response = self._execute(
                    service.edits()
                    .bundles()
                    .upload(packageName=package_name, editId=edit_id, media_body=media)
                )
            else:
                upload_response = self._execute(
                    service.edits()
                    .apks()
                    .upload(packageName=package_name, editId=edit_id, media_body=media)
                )

            uploaded_version_code = int(upload_response.get("versionCode", 0))
            self._logger.info("Upload complete", version_code=uploaded_version_code)

            # Build release
            release_body: dict[str, Any] = {
                "versionCodes": [str(uploaded_version_code)],
            }

            if rollout_percentage < 100:
                release_body["status"] = "inProgress"
                release_body["userFraction"] = rollout_percentage / 100.0
            else:
                release_body["status"] = "completed"

            # Handle release notes - support both string and dict formats
            if release_notes:
                if isinstance(release_notes, dict):
                    # Multi-language release notes
                    release_body["releaseNotes"] = [
                        {"language": lang, "text": text} for lang, text in release_notes.items()
                    ]
                else:
                    # Single language release notes
                    release_body["releaseNotes"] = [
                        {"language": release_notes_language, "text": release_notes}
                    ]

            # Update track
            track_body = {"releases": [release_body]}
            self._execute(
                service.edits()
                .tracks()
                .update(
                    packageName=package_name,
                    editId=edit_id,
                    track=track,
                    body=track_body,
                )
            )

            # Commit
            self._commit_edit(package_name, edit_id)

            return DeploymentResult(
                success=True,
                edit_id=edit_id,
                package_name=package_name,
                track=track,
                version_code=uploaded_version_code,
                message=f"Successfully deployed version {uploaded_version_code} to {track}",
            )

        except HttpError as e:
            self._logger.exception("Deployment failed", error=str(e))
            self._delete_edit(package_name, edit_id)
            return DeploymentResult(
                success=False,
                package_name=package_name,
                track=track,
                message=f"Deployment failed: {e.reason}",
                error=str(e),
            )
        except Exception as e:
            self._logger.exception("Deployment failed", error=str(e))
            self._delete_edit(package_name, edit_id)
            return DeploymentResult(
                success=False,
                package_name=package_name,
                track=track,
                message=f"Deployment failed: {e}",
                error=str(e),
            )

    def promote_release(
        self,
        package_name: str,
        from_track: str,
        to_track: str,
        version_code: int,
        rollout_percentage: float = 100.0,
    ) -> DeploymentResult:
        """Promote a release from one track to another.

        Args:
            package_name: App package name.
            from_track: Source track.
            to_track: Destination track.
            version_code: Version code to promote.
            rollout_percentage: Rollout percentage for the target track.

        Returns:
            Deployment result.
        """
        self._logger.info(
            "Promoting release",
            package_name=package_name,
            from_track=from_track,
            to_track=to_track,
            version_code=version_code,
        )

        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            # Get source track info
            source_track = self._execute(
                service.edits()
                .tracks()
                .get(packageName=package_name, editId=edit_id, track=from_track)
            )

            # Find the release with matching version code
            source_release = None
            for release in source_track.get("releases", []):
                version_codes = [int(vc) for vc in release.get("versionCodes", [])]
                if version_code in version_codes:
                    source_release = release
                    break

            if not source_release:
                self._delete_edit(package_name, edit_id)
                return DeploymentResult(
                    success=False,
                    package_name=package_name,
                    track=to_track,
                    version_code=version_code,
                    message=f"Version {version_code} not found in {from_track}",
                    error="VersionNotFound",
                )

            # Create new release for target track
            new_release: dict[str, Any] = {
                "versionCodes": [str(version_code)],
                "releaseNotes": source_release.get("releaseNotes", []),
            }

            if rollout_percentage < 100:
                new_release["status"] = "inProgress"
                new_release["userFraction"] = rollout_percentage / 100.0
            else:
                new_release["status"] = "completed"

            # Update target track
            self._execute(
                service.edits()
                .tracks()
                .update(
                    packageName=package_name,
                    editId=edit_id,
                    track=to_track,
                    body={"releases": [new_release]},
                )
            )

            self._commit_edit(package_name, edit_id)

            return DeploymentResult(
                success=True,
                edit_id=edit_id,
                package_name=package_name,
                track=to_track,
                version_code=version_code,
                message=f"Successfully promoted version {version_code} from {from_track} to {to_track}",
            )

        except HttpError as e:
            self._logger.exception("Promotion failed", error=str(e))
            self._delete_edit(package_name, edit_id)
            return DeploymentResult(
                success=False,
                package_name=package_name,
                track=to_track,
                version_code=version_code,
                message=f"Promotion failed: {e.reason}",
                error=str(e),
            )
        except Exception as e:
            self._logger.exception("Promotion failed", error=str(e))
            self._delete_edit(package_name, edit_id)
            return DeploymentResult(
                success=False,
                package_name=package_name,
                track=to_track,
                version_code=version_code,
                message=f"Promotion failed: {e}",
                error=str(e),
            )

    def halt_release(self, package_name: str, track: str, version_code: int) -> DeploymentResult:
        """Halt a staged rollout.

        Args:
            package_name: App package name.
            track: Track with the release to halt.
            version_code: Version code to halt.

        Returns:
            Deployment result.
        """
        self._logger.info(
            "Halting release",
            package_name=package_name,
            track=track,
            version_code=version_code,
        )

        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            # Get current track info
            current_track = self._execute(
                service.edits().tracks().get(packageName=package_name, editId=edit_id, track=track)
            )

            # Find and update the release
            releases = current_track.get("releases", [])
            updated = False
            for release in releases:
                version_codes = [int(vc) for vc in release.get("versionCodes", [])]
                if version_code in version_codes:
                    release["status"] = "halted"
                    updated = True
                    break

            if not updated:
                self._delete_edit(package_name, edit_id)
                return DeploymentResult(
                    success=False,
                    package_name=package_name,
                    track=track,
                    version_code=version_code,
                    message=f"Version {version_code} not found in {track}",
                    error="VersionNotFound",
                )

            # Update track
            self._execute(
                service.edits()
                .tracks()
                .update(
                    packageName=package_name,
                    editId=edit_id,
                    track=track,
                    body={"releases": releases},
                )
            )

            self._commit_edit(package_name, edit_id)

            return DeploymentResult(
                success=True,
                edit_id=edit_id,
                package_name=package_name,
                track=track,
                version_code=version_code,
                message=f"Successfully halted version {version_code} on {track}",
            )

        except HttpError as e:
            self._logger.exception("Halt failed", error=str(e))
            self._delete_edit(package_name, edit_id)
            return DeploymentResult(
                success=False,
                package_name=package_name,
                track=track,
                version_code=version_code,
                message=f"Halt failed: {e.reason}",
                error=str(e),
            )
        except Exception as e:
            self._logger.exception("Halt failed", error=str(e))
            self._delete_edit(package_name, edit_id)
            return DeploymentResult(
                success=False,
                package_name=package_name,
                track=track,
                version_code=version_code,
                message=f"Halt failed: {e}",
                error=str(e),
            )

    def update_rollout(
        self,
        package_name: str,
        track: str,
        version_code: int,
        rollout_percentage: float,
    ) -> DeploymentResult:
        """Update the rollout percentage for a staged release.

        Args:
            package_name: App package name.
            track: Track with the staged release.
            version_code: Version code to update.
            rollout_percentage: New rollout percentage (0-100).

        Returns:
            Deployment result.
        """
        self._logger.info(
            "Updating rollout",
            package_name=package_name,
            track=track,
            version_code=version_code,
            rollout_percentage=rollout_percentage,
        )

        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            # Get current track info
            current_track = self._execute(
                service.edits().tracks().get(packageName=package_name, editId=edit_id, track=track)
            )

            # Find and update the release
            releases = current_track.get("releases", [])
            updated = False
            for release in releases:
                version_codes = [int(vc) for vc in release.get("versionCodes", [])]
                if version_code in version_codes:
                    if rollout_percentage >= 100:
                        release["status"] = "completed"
                        release.pop("userFraction", None)
                    else:
                        release["status"] = "inProgress"
                        release["userFraction"] = rollout_percentage / 100.0
                    updated = True
                    break

            if not updated:
                self._delete_edit(package_name, edit_id)
                return DeploymentResult(
                    success=False,
                    package_name=package_name,
                    track=track,
                    version_code=version_code,
                    message=f"Version {version_code} not found in {track}",
                    error="VersionNotFound",
                )

            # Update track
            self._execute(
                service.edits()
                .tracks()
                .update(
                    packageName=package_name,
                    editId=edit_id,
                    track=track,
                    body={"releases": releases},
                )
            )

            self._commit_edit(package_name, edit_id)

            return DeploymentResult(
                success=True,
                edit_id=edit_id,
                package_name=package_name,
                track=track,
                version_code=version_code,
                message=f"Successfully updated rollout to {rollout_percentage}% for version {version_code}",
            )

        except HttpError as e:
            self._logger.exception("Rollout update failed", error=str(e))
            self._delete_edit(package_name, edit_id)
            return DeploymentResult(
                success=False,
                package_name=package_name,
                track=track,
                version_code=version_code,
                message=f"Rollout update failed: {e.reason}",
                error=str(e),
            )
        except Exception as e:
            self._logger.exception("Rollout update failed", error=str(e))
            self._delete_edit(package_name, edit_id)
            return DeploymentResult(
                success=False,
                package_name=package_name,
                track=track,
                version_code=version_code,
                message=f"Rollout update failed: {e}",
                error=str(e),
            )

    def get_app_details(self, package_name: str, language: str = "en-US") -> AppDetails:
        """Get app details.

        Args:
            package_name: App package name.
            language: Language code for localized content.

        Returns:
            App details.
        """
        self._logger.info("Fetching app details", package_name=package_name, language=language)
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            # Get app details
            details = self._execute(
                service.edits().details().get(packageName=package_name, editId=edit_id)
            )

            # Get listings for the specified language
            try:
                listing = self._execute(
                    service.edits()
                    .listings()
                    .get(packageName=package_name, editId=edit_id, language=language)
                )
            except HttpError:
                listing = {}

            return AppDetails(
                package_name=package_name,
                title=listing.get("title"),
                short_description=listing.get("shortDescription"),
                full_description=listing.get("fullDescription"),
                default_language=details.get("defaultLanguage"),
                developer_name=None,  # edits.details API has no developer name field
                developer_email=details.get("contactEmail"),
                developer_website=details.get("contactWebsite"),
            )
        except HttpError as e:
            self._logger.exception("Failed to fetch app details", error=str(e))
            raise PlayStoreClientError(f"Failed to fetch app details: {e.reason}") from e
        finally:
            self._delete_edit(package_name, edit_id)

    # =========================================================================
    # Reviews API
    # =========================================================================

    def get_reviews(
        self,
        package_name: str,
        max_results: int = 100,
        translation_language: str | None = None,
    ) -> list[Review]:
        """Get app reviews.

        Args:
            package_name: App package name.
            max_results: Maximum number of reviews to return.
            translation_language: Language to translate reviews to.

        Returns:
            List of reviews.
        """
        self._logger.info(
            "Fetching reviews",
            package_name=package_name,
            max_results=max_results,
        )
        service = self._get_service()

        try:
            reviews: list[Review] = []
            # reviews.list paginates via tokenPagination.nextPageToken and caps
            # each page at ~100; loop until max_results collected (or exhausted).
            per_page = min(max_results, 100)
            token: str | None = None
            while len(reviews) < max_results:
                kwargs: dict[str, Any] = {"packageName": package_name, "maxResults": per_page}
                if translation_language:
                    kwargs["translationLanguage"] = translation_language
                if token:
                    kwargs["token"] = token
                result = self._execute(service.reviews().list(**kwargs))
                for review_data in result.get("reviews", []):
                    review = _parse_review(review_data)
                    if review is not None:
                        reviews.append(review)
                token = result.get("tokenPagination", {}).get("nextPageToken")
                if not token:
                    break

            return reviews[:max_results]

        except HttpError as e:
            self._logger.exception("Failed to fetch reviews", error=str(e))
            raise PlayStoreClientError(f"Failed to fetch reviews: {e.reason}") from e

    def get_review(
        self,
        package_name: str,
        review_id: str,
        translation_language: str | None = None,
    ) -> Review:
        """Get a single review by ID.

        Args:
            package_name: App package name.
            review_id: Review ID.
            translation_language: Optional language to translate the review to.

        Returns:
            The review.
        """
        self._logger.info("Fetching review", package_name=package_name, review_id=review_id)
        service = self._get_service()

        try:
            kwargs: dict[str, Any] = {"packageName": package_name, "reviewId": review_id}
            if translation_language:
                kwargs["translationLanguage"] = translation_language
            result = self._execute(service.reviews().get(**kwargs))

            review = _parse_review(result)
            if review is None:
                raise PlayStoreClientError(f"Review {review_id} has no user comment")
            return review

        except HttpError as e:
            self._logger.exception("Failed to fetch review", error=str(e))
            raise PlayStoreClientError(f"Failed to fetch review: {e.reason}") from e

    def reply_to_review(
        self,
        package_name: str,
        review_id: str,
        reply_text: str,
    ) -> ReviewReplyResult:
        """Reply to a review.

        Args:
            package_name: App package name.
            review_id: Review ID to reply to.
            reply_text: Reply text.

        Returns:
            Reply result.
        """
        self._logger.info(
            "Replying to review",
            package_name=package_name,
            review_id=review_id,
        )
        service = self._get_service()

        try:
            self._execute(
                service.reviews().reply(
                    packageName=package_name,
                    reviewId=review_id,
                    body={"replyText": reply_text},
                )
            )

            return ReviewReplyResult(
                success=True,
                review_id=review_id,
                message="Reply posted successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to reply to review", error=str(e))
            return ReviewReplyResult(
                success=False,
                review_id=review_id,
                message=f"Failed to reply: {e.reason}",
                error=str(e),
            )

    # =========================================================================
    # Subscriptions API
    # =========================================================================

    def list_subscriptions(self, package_name: str) -> list[SubscriptionProduct]:
        """List subscription products for an app.

        Args:
            package_name: App package name.

        Returns:
            List of subscription products.
        """
        self._logger.info("Listing subscriptions", package_name=package_name)
        service = self._get_service()

        try:
            subscriptions: list[SubscriptionProduct] = []
            page_token: str | None = None
            while True:
                kwargs: dict[str, Any] = {"packageName": package_name}
                if page_token:
                    kwargs["pageToken"] = page_token
                result = self._execute(service.monetization().subscriptions().list(**kwargs))
                subscriptions.extend(
                    SubscriptionProduct(
                        product_id=sub_data.get("productId", ""),
                        package_name=package_name,
                        base_plans=sub_data.get("basePlans", []),
                    )
                    for sub_data in result.get("subscriptions", [])
                )
                page_token = result.get("nextPageToken")
                if not page_token:
                    break

            return subscriptions

        except HttpError as e:
            self._logger.exception("Failed to list subscriptions", error=str(e))
            raise PlayStoreClientError(f"Failed to list subscriptions: {e.reason}") from e

    def get_subscription_purchase(
        self,
        package_name: str,
        subscription_id: str,
        token: str,
    ) -> SubscriptionPurchase:
        """Get subscription purchase status.

        Args:
            package_name: App package name.
            subscription_id: Subscription product ID.
            token: Purchase token.

        Returns:
            Subscription purchase details.
        """
        self._logger.info(
            "Getting subscription status",
            package_name=package_name,
            subscription_id=subscription_id,
        )
        service = self._get_service()

        try:
            # Use v2 API for subscriptions
            result = self._execute(
                service.purchases().subscriptionsv2().get(packageName=package_name, token=token)
            )

            line_items = result.get("lineItems", [])
            auto_renewing = any(
                item.get("productId") == subscription_id
                and item.get("autoRenewingPlan", {}).get("autoRenewEnabled", False)
                for item in line_items
            )

            # Expiry is per line item; use the one for this subscription. If no
            # line item matches, the purchase isn't for this subscription id, so
            # leave expiry unset rather than reporting another product's expiry
            # (keeps it consistent with auto_renewing above).
            expiry_raw = next(
                (
                    item.get("expiryTime")
                    for item in line_items
                    if item.get("productId") == subscription_id
                ),
                None,
            )

            return SubscriptionPurchase(
                package_name=package_name,
                subscription_id=subscription_id,
                purchase_token=token,
                order_id=result.get("latestOrderId"),
                auto_renewing=auto_renewing,
                start_time=_parse_rfc3339(result.get("startTime")),
                expiry_time=_parse_rfc3339(expiry_raw),
            )

        except HttpError as e:
            self._logger.exception("Failed to get subscription status", error=str(e))
            raise PlayStoreClientError(f"Failed to get subscription status: {e.reason}") from e

    def list_voided_purchases(
        self,
        package_name: str,
        max_results: int = 100,
    ) -> list[VoidedPurchase]:
        """List voided purchases.

        Args:
            package_name: App package name.
            max_results: Maximum results to return.

        Returns:
            List of voided purchases.
        """
        self._logger.info("Listing voided purchases", package_name=package_name)
        service = self._get_service()

        try:
            voided: list[VoidedPurchase] = []
            # voidedpurchases.list paginates via tokenPagination.nextPageToken;
            # loop until max_results collected (or the results are exhausted).
            token: str | None = None
            while len(voided) < max_results:
                kwargs: dict[str, Any] = {"packageName": package_name, "maxResults": max_results}
                if token:
                    kwargs["token"] = token
                result = self._execute(service.purchases().voidedpurchases().list(**kwargs))
                voided.extend(
                    VoidedPurchase(
                        package_name=package_name,
                        purchase_token=purchase.get("purchaseToken", ""),
                        order_id=purchase.get("orderId"),
                        voided_reason=purchase.get("voidedReason"),
                        voided_source=purchase.get("voidedSource"),
                        voided_time=datetime.fromtimestamp(
                            int(purchase.get("voidedTimeMillis")) / 1000, tz=UTC
                        )
                        if purchase.get("voidedTimeMillis")
                        else None,
                    )
                    for purchase in result.get("voidedPurchases", [])
                )
                token = result.get("tokenPagination", {}).get("nextPageToken")
                if not token:
                    break

            return voided[:max_results]

        except HttpError as e:
            self._logger.exception("Failed to list voided purchases", error=str(e))
            raise PlayStoreClientError(f"Failed to list voided purchases: {e.reason}") from e

    def get_product_purchase(
        self,
        package_name: str,
        product_id: str,
        token: str,
    ) -> ProductPurchase:
        """Get the status of an in-app product purchase.

        Args:
            package_name: App package name.
            product_id: In-app product SKU.
            token: Purchase token.

        Returns:
            Product purchase details.
        """
        self._logger.info(
            "Getting product purchase", package_name=package_name, product_id=product_id
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.purchases()
                .products()
                .get(packageName=package_name, productId=product_id, token=token)
            )

            purchase_time = (
                datetime.fromtimestamp(int(result["purchaseTimeMillis"]) / 1000, tz=UTC)
                if result.get("purchaseTimeMillis")
                else None
            )

            return ProductPurchase(
                package_name=package_name,
                product_id=product_id,
                purchase_token=token,
                order_id=result.get("orderId"),
                purchase_state=result.get("purchaseState"),
                consumption_state=result.get("consumptionState"),
                acknowledgement_state=result.get("acknowledgementState"),
                purchase_time=purchase_time,
                purchase_type=result.get("purchaseType"),
                quantity=result.get("quantity"),
                region_code=result.get("regionCode"),
                developer_payload=result.get("developerPayload"),
            )

        except HttpError as e:
            self._logger.exception("Failed to get product purchase", error=str(e))
            raise PlayStoreClientError(f"Failed to get product purchase: {e.reason}") from e

    def acknowledge_product_purchase(
        self,
        package_name: str,
        product_id: str,
        token: str,
        developer_payload: str | None = None,
    ) -> ProductPurchaseActionResult:
        """Acknowledge an in-app product purchase.

        Args:
            package_name: App package name.
            product_id: In-app product SKU.
            token: Purchase token.
            developer_payload: Optional payload to attach to the purchase.

        Returns:
            Action result with success status.
        """
        self._logger.info(
            "Acknowledging product purchase", package_name=package_name, product_id=product_id
        )
        service = self._get_service()
        body = {"developerPayload": developer_payload} if developer_payload else {}

        try:
            self._execute(
                service.purchases()
                .products()
                .acknowledge(
                    packageName=package_name,
                    productId=product_id,
                    token=token,
                    body=body,
                )
            )

            return ProductPurchaseActionResult(
                success=True,
                package_name=package_name,
                product_id=product_id,
                purchase_token=token,
                action="acknowledge",
                message="Purchase acknowledged successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to acknowledge product purchase", error=str(e))
            raise PlayStoreClientError(f"Failed to acknowledge product purchase: {e.reason}") from e

    def consume_product_purchase(
        self,
        package_name: str,
        product_id: str,
        token: str,
    ) -> ProductPurchaseActionResult:
        """Consume an in-app product purchase.

        Args:
            package_name: App package name.
            product_id: In-app product SKU.
            token: Purchase token.

        Returns:
            Action result with success status.
        """
        self._logger.info(
            "Consuming product purchase", package_name=package_name, product_id=product_id
        )
        service = self._get_service()

        try:
            self._execute(
                service.purchases()
                .products()
                .consume(
                    packageName=package_name,
                    productId=product_id,
                    token=token,
                )
            )

            return ProductPurchaseActionResult(
                success=True,
                package_name=package_name,
                product_id=product_id,
                purchase_token=token,
                action="consume",
                message="Purchase consumed successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to consume product purchase", error=str(e))
            raise PlayStoreClientError(f"Failed to consume product purchase: {e.reason}") from e

    def refund_order(
        self,
        package_name: str,
        order_id: str,
        revoke: bool = False,
    ) -> OrderRefundResult:
        """Refund an order, optionally revoking the entitlement.

        Args:
            package_name: App package name.
            order_id: Order ID to refund.
            revoke: If True, also revoke the user's entitlement.

        Returns:
            Refund result with success status.
        """
        self._logger.info("Refunding order", package_name=package_name, order_id=order_id)
        service = self._get_service()

        try:
            self._execute(
                service.orders().refund(packageName=package_name, orderId=order_id, revoke=revoke)
            )

            message = "Order refunded successfully"
            if revoke:
                message += " and entitlement revoked"
            return OrderRefundResult(
                success=True,
                package_name=package_name,
                order_id=order_id,
                revoked=revoke,
                message=message,
            )

        except HttpError as e:
            self._logger.exception("Failed to refund order", error=str(e))
            raise PlayStoreClientError(f"Failed to refund order: {e.reason}") from e

    def cancel_subscription_purchase(
        self,
        package_name: str,
        token: str,
        cancellation_type: str = "USER_REQUESTED_STOP_RENEWALS",
    ) -> SubscriptionActionResult:
        """Cancel a subscription purchase.

        Args:
            package_name: App package name.
            token: Purchase token.
            cancellation_type: One of USER_REQUESTED_STOP_RENEWALS,
                DEVELOPER_REQUESTED_STOP_PAYMENTS, CANCELLATION_TYPE_UNSPECIFIED.

        Returns:
            Action result with success status.
        """
        self._logger.info("Cancelling subscription purchase", package_name=package_name)
        service = self._get_service()

        try:
            self._execute(
                service.purchases()
                .subscriptionsv2()
                .cancel(
                    packageName=package_name,
                    token=token,
                    body={"cancellationContext": {"cancellationType": cancellation_type}},
                )
            )

            return SubscriptionActionResult(
                success=True,
                package_name=package_name,
                purchase_token=token,
                action="cancel",
                message="Subscription cancellation scheduled",
            )

        except HttpError as e:
            self._logger.exception("Failed to cancel subscription", error=str(e))
            raise PlayStoreClientError(f"Failed to cancel subscription: {e.reason}") from e

    def defer_subscription_purchase(
        self,
        package_name: str,
        token: str,
        defer_duration: str,
        etag: str,
    ) -> SubscriptionActionResult:
        """Defer a subscription purchase's next renewal.

        Args:
            package_name: App package name.
            token: Purchase token.
            defer_duration: Duration to defer, e.g. "604800s" (7 days).
            etag: Current etag of the subscription purchase.

        Returns:
            Action result with success status and new expiry details.
        """
        self._logger.info("Deferring subscription purchase", package_name=package_name)
        service = self._get_service()

        try:
            result = self._execute(
                service.purchases()
                .subscriptionsv2()
                .defer(
                    packageName=package_name,
                    token=token,
                    body={"deferralContext": {"deferDuration": defer_duration, "etag": etag}},
                )
            )

            return SubscriptionActionResult(
                success=True,
                package_name=package_name,
                purchase_token=token,
                action="defer",
                message="Subscription deferred",
                details={"itemExpiryTimeDetails": result.get("itemExpiryTimeDetails", [])},
            )

        except HttpError as e:
            self._logger.exception("Failed to defer subscription", error=str(e))
            raise PlayStoreClientError(f"Failed to defer subscription: {e.reason}") from e

    def revoke_subscription_purchase(
        self,
        package_name: str,
        token: str,
        refund_type: str = "full",
    ) -> SubscriptionActionResult:
        """Revoke (refund) a subscription purchase.

        Args:
            package_name: App package name.
            token: Purchase token.
            refund_type: "full" or "prorated".

        Returns:
            Action result with success status.
        """
        self._logger.info(
            "Revoking subscription purchase", package_name=package_name, refund_type=refund_type
        )
        if refund_type not in _REVOCATION_CONTEXTS:
            raise PlayStoreClientError(
                f"Invalid refund_type '{refund_type}'; must be one of: "
                f"{', '.join(sorted(_REVOCATION_CONTEXTS))}"
            )
        service = self._get_service()

        try:
            self._execute(
                service.purchases()
                .subscriptionsv2()
                .revoke(
                    packageName=package_name,
                    token=token,
                    body={"revocationContext": _REVOCATION_CONTEXTS[refund_type]},
                )
            )

            return SubscriptionActionResult(
                success=True,
                package_name=package_name,
                purchase_token=token,
                action="revoke",
                message=f"Subscription revoked ({refund_type} refund)",
            )

        except HttpError as e:
            self._logger.exception("Failed to revoke subscription", error=str(e))
            raise PlayStoreClientError(f"Failed to revoke subscription: {e.reason}") from e

    def get_product_purchase_v2(
        self,
        package_name: str,
        token: str,
    ) -> ProductPurchaseV2:
        """Get the status of an in-app product purchase (v2 API).

        Args:
            package_name: App package name.
            token: Purchase token (identifies the purchase; no product ID needed).

        Returns:
            Product purchase (v2) details.
        """
        self._logger.info("Getting product purchase (v2)", package_name=package_name)
        service = self._get_service()

        try:
            result = self._execute(
                service.purchases()
                .productsv2()
                .getproductpurchasev2(packageName=package_name, token=token)
            )

            return ProductPurchaseV2(
                package_name=package_name,
                purchase_token=token,
                order_id=result.get("orderId"),
                acknowledgement_state=result.get("acknowledgementState"),
                purchase_completion_time=result.get("purchaseCompletionTime"),
                region_code=result.get("regionCode"),
                product_line_items=result.get("productLineItem", []),
                obfuscated_external_account_id=result.get("obfuscatedExternalAccountId"),
                obfuscated_external_profile_id=result.get("obfuscatedExternalProfileId"),
                test_purchase="testPurchaseContext" in result,
            )

        except HttpError as e:
            self._logger.exception("Failed to get product purchase (v2)", error=str(e))
            raise PlayStoreClientError(f"Failed to get product purchase: {e.reason}") from e

    # =========================================================================
    # Batch Operations
    # =========================================================================

    def batch_deploy(
        self,
        package_name: str,
        file_path: str,
        tracks: list[str],
        release_notes: str | dict[str, str] | None = None,
        rollout_percentages: dict[str, float] | None = None,
    ) -> BatchDeploymentResult:
        """Deploy to multiple tracks in a single operation.

        Args:
            package_name: App package name.
            file_path: Path to APK or AAB file.
            tracks: List of tracks to deploy to (e.g., ["internal", "alpha"]).
            release_notes: Release notes (string or dict for multi-language).
            rollout_percentages: Optional dict mapping track to rollout percentage.

        Returns:
            Batch deployment result with individual results.
        """
        self._logger.info(
            "Starting batch deployment",
            package_name=package_name,
            tracks=tracks,
        )

        results: list[DeploymentResult] = []
        successful = 0
        failed = 0

        for track in tracks:
            rollout = 100.0
            if rollout_percentages and track in rollout_percentages:
                rollout = rollout_percentages[track]

            result = self.deploy_app(
                package_name=package_name,
                track=track,
                file_path=file_path,
                release_notes=release_notes,
                rollout_percentage=rollout,
            )

            results.append(result)
            if result.success:
                successful += 1
            else:
                failed += 1

        all_success = failed == 0
        message = f"Deployed to {successful}/{len(tracks)} tracks successfully"
        if failed > 0:
            message += f" ({failed} failed)"

        return BatchDeploymentResult(
            success=all_success,
            results=results,
            successful_count=successful,
            failed_count=failed,
            message=message,
        )

    # =========================================================================
    # In-App Products API
    # =========================================================================

    def list_in_app_products(self, package_name: str) -> list[InAppProduct]:
        """List in-app products for an app.

        Args:
            package_name: App package name.

        Returns:
            List of in-app products.
        """
        self._logger.info("Listing in-app products", package_name=package_name)
        service = self._get_service()

        try:
            products: list[InAppProduct] = []
            # inappproducts.list paginates via tokenPagination.nextPageToken
            # (the older shape), not a top-level nextPageToken.
            token: str | None = None
            while True:
                kwargs: dict[str, Any] = {"packageName": package_name}
                if token:
                    kwargs["token"] = token
                result = self._execute(service.inappproducts().list(**kwargs))
                products.extend(
                    self._parse_in_app_product(package_name, product_data)
                    for product_data in result.get("inappproduct", [])
                )
                token = result.get("tokenPagination", {}).get("nextPageToken")
                if not token:
                    break

            return products

        except HttpError as e:
            self._logger.exception("Failed to list in-app products", error=str(e))
            raise PlayStoreClientError(f"Failed to list in-app products: {e.reason}") from e

    def get_in_app_product(self, package_name: str, sku: str) -> InAppProduct:
        """Get details of a specific in-app product.

        Args:
            package_name: App package name.
            sku: Product SKU.

        Returns:
            In-app product details.
        """
        self._logger.info("Getting in-app product", package_name=package_name, sku=sku)
        service = self._get_service()

        try:
            product_data = self._execute(
                service.inappproducts().get(packageName=package_name, sku=sku)
            )
            return self._parse_in_app_product(package_name, product_data)

        except HttpError as e:
            self._logger.exception("Failed to get in-app product", error=str(e))
            raise PlayStoreClientError(f"Failed to get in-app product: {e.reason}") from e

    @staticmethod
    def _parse_in_app_product(package_name: str, product_data: dict[str, Any]) -> InAppProduct:
        """Parse an InappProduct API resource into an InAppProduct model."""
        # Get default price if available
        default_price = None
        if "defaultPrice" in product_data:
            default_price = product_data["defaultPrice"]

        # Get localized listings
        listings = product_data.get("listings", {})
        default_listing = listings.get(product_data.get("defaultLanguage", "en-US"), {})

        return InAppProduct(
            sku=product_data.get("sku", ""),
            package_name=package_name,
            product_type=product_data.get("purchaseType", "managedProduct"),
            status=product_data.get("status"),
            default_language=product_data.get("defaultLanguage"),
            title=default_listing.get("title"),
            description=default_listing.get("description"),
            default_price=default_price,
        )

    def create_in_app_product(self, package_name: str, product: dict[str, Any]) -> InAppProduct:
        """Create a new in-app product.

        Args:
            package_name: App package name.
            product: In-app product body (InAppProduct resource).

        Returns:
            The created in-app product.
        """
        self._logger.info("Creating in-app product", package_name=package_name)
        service = self._get_service()

        try:
            result = self._execute(
                service.inappproducts().insert(packageName=package_name, body=product)
            )
            return self._parse_in_app_product(package_name, result)

        except HttpError as e:
            self._logger.exception("Failed to create in-app product", error=str(e))
            raise PlayStoreClientError(f"Failed to create in-app product: {e.reason}") from e

    def update_in_app_product(
        self,
        package_name: str,
        sku: str,
        product: dict[str, Any],
        auto_convert_missing_prices: bool = False,
    ) -> InAppProduct:
        """Update (replace) an existing in-app product.

        Args:
            package_name: App package name.
            sku: Product SKU.
            product: In-app product body (InAppProduct resource).
            auto_convert_missing_prices: If True, auto-convert prices for regions
                without a specified price based on the default price.

        Returns:
            The updated in-app product.
        """
        self._logger.info("Updating in-app product", package_name=package_name, sku=sku)
        service = self._get_service()

        try:
            result = self._execute(
                service.inappproducts().update(
                    packageName=package_name,
                    sku=sku,
                    autoConvertMissingPrices=auto_convert_missing_prices,
                    body=product,
                )
            )
            return self._parse_in_app_product(package_name, result)

        except HttpError as e:
            self._logger.exception("Failed to update in-app product", error=str(e))
            raise PlayStoreClientError(f"Failed to update in-app product: {e.reason}") from e

    def patch_in_app_product(
        self, package_name: str, sku: str, product: dict[str, Any]
    ) -> InAppProduct:
        """Partially update an existing in-app product.

        Args:
            package_name: App package name.
            sku: Product SKU.
            product: Partial in-app product body (InAppProduct resource).

        Returns:
            The patched in-app product.
        """
        self._logger.info("Patching in-app product", package_name=package_name, sku=sku)
        service = self._get_service()

        try:
            result = self._execute(
                service.inappproducts().patch(packageName=package_name, sku=sku, body=product)
            )
            return self._parse_in_app_product(package_name, result)

        except HttpError as e:
            self._logger.exception("Failed to patch in-app product", error=str(e))
            raise PlayStoreClientError(f"Failed to patch in-app product: {e.reason}") from e

    def delete_in_app_product(self, package_name: str, sku: str) -> InAppProductActionResult:
        """Delete an in-app product.

        Args:
            package_name: App package name.
            sku: Product SKU.

        Returns:
            Action result with success status.
        """
        self._logger.info("Deleting in-app product", package_name=package_name, sku=sku)
        service = self._get_service()

        try:
            self._execute(service.inappproducts().delete(packageName=package_name, sku=sku))

            return InAppProductActionResult(
                success=True,
                package_name=package_name,
                sku=sku,
                message=f"In-app product {sku} deleted successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to delete in-app product", error=str(e))
            raise PlayStoreClientError(f"Failed to delete in-app product: {e.reason}") from e

    def batch_get_in_app_products(self, package_name: str, skus: list[str]) -> list[InAppProduct]:
        """Get details for multiple in-app products.

        Args:
            package_name: App package name.
            skus: List of product SKUs to retrieve.

        Returns:
            List of in-app products, in the same order as the request.
        """
        self._logger.info(
            "Batch getting in-app products", package_name=package_name, count=len(skus)
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.inappproducts().batchGet(packageName=package_name, sku=skus)
            )

            return [
                self._parse_in_app_product(package_name, product_data)
                for product_data in result.get("inappproduct", [])
            ]

        except HttpError as e:
            self._logger.exception("Failed to batch get in-app products", error=str(e))
            raise PlayStoreClientError(f"Failed to batch get in-app products: {e.reason}") from e

    def batch_delete_in_app_products(
        self, package_name: str, skus: list[str]
    ) -> InAppProductActionResult:
        """Delete multiple in-app products in a single operation.

        Args:
            package_name: App package name.
            skus: List of product SKUs to delete.

        Returns:
            Action result with success status.
        """
        self._logger.info(
            "Batch deleting in-app products", package_name=package_name, count=len(skus)
        )
        service = self._get_service()

        try:
            self._execute(
                service.inappproducts().batchDelete(
                    packageName=package_name,
                    body={"requests": [{"packageName": package_name, "sku": s} for s in skus]},
                )
            )

            return InAppProductActionResult(
                success=True,
                package_name=package_name,
                sku=None,
                message=f"Deleted {len(skus)} in-app product(s) successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to batch delete in-app products", error=str(e))
            raise PlayStoreClientError(f"Failed to batch delete in-app products: {e.reason}") from e

    # =========================================================================
    # One-Time Product Catalog API
    # =========================================================================

    @staticmethod
    def _parse_one_time_product(package_name: str, data: dict[str, Any]) -> OneTimeProduct:
        """Parse a OneTimeProduct API resource into a OneTimeProduct model."""
        return OneTimeProduct(
            product_id=data.get("productId", ""),
            package_name=package_name,
            listings=data.get("listings", []),
            purchase_options=data.get("purchaseOptions", []),
            offer_tags=data.get("offerTags", []),
            restricted_payment_countries=data.get("restrictedPaymentCountries"),
        )

    def get_one_time_product(self, package_name: str, product_id: str) -> OneTimeProduct:
        """Get details of a specific one-time product.

        Args:
            package_name: App package name.
            product_id: One-time product ID.

        Returns:
            One-time product details.
        """
        self._logger.info(
            "Getting one-time product", package_name=package_name, product_id=product_id
        )
        service = self._get_service()

        try:
            data = self._execute(
                service.monetization()
                .onetimeproducts()
                .get(packageName=package_name, productId=product_id)
            )
            return self._parse_one_time_product(package_name, data)

        except HttpError as e:
            self._logger.exception("Failed to get one-time product", error=str(e))
            raise PlayStoreClientError(f"Failed to get one-time product: {e.reason}") from e

    def list_one_time_products(self, package_name: str) -> list[OneTimeProduct]:
        """List one-time products for an app.

        Args:
            package_name: App package name.

        Returns:
            List of one-time products.
        """
        self._logger.info("Listing one-time products", package_name=package_name)
        service = self._get_service()

        try:
            products: list[OneTimeProduct] = []
            page_token: str | None = None
            while True:
                kwargs: dict[str, Any] = {"packageName": package_name}
                if page_token:
                    kwargs["pageToken"] = page_token
                result = self._execute(service.monetization().onetimeproducts().list(**kwargs))
                products.extend(
                    self._parse_one_time_product(package_name, data)
                    for data in result.get("oneTimeProducts", [])
                )
                page_token = result.get("nextPageToken")
                if not page_token:
                    break

            return products

        except HttpError as e:
            self._logger.exception("Failed to list one-time products", error=str(e))
            raise PlayStoreClientError(f"Failed to list one-time products: {e.reason}") from e

    def batch_get_one_time_products(
        self, package_name: str, product_ids: list[str]
    ) -> list[OneTimeProduct]:
        """Get details for multiple one-time products.

        Args:
            package_name: App package name.
            product_ids: List of one-time product IDs to retrieve.

        Returns:
            List of one-time products.
        """
        self._logger.info(
            "Batch getting one-time products", package_name=package_name, count=len(product_ids)
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .onetimeproducts()
                .batchGet(packageName=package_name, productIds=product_ids)
            )

            return [
                self._parse_one_time_product(package_name, data)
                for data in result.get("oneTimeProducts", [])
            ]

        except HttpError as e:
            self._logger.exception("Failed to batch get one-time products", error=str(e))
            raise PlayStoreClientError(f"Failed to batch get one-time products: {e.reason}") from e

    def patch_one_time_product(
        self,
        package_name: str,
        product_id: str,
        product: dict[str, Any],
        update_mask: str,
        regions_version: str = "2022/02",
    ) -> OneTimeProduct:
        """Create or update a one-time product (patch is create-or-update).

        Args:
            package_name: App package name.
            product_id: One-time product ID.
            product: Partial OneTimeProduct resource body.
            update_mask: Comma-separated list of fields to update.
            regions_version: Version of available regions to use for regional prices.

        Returns:
            The patched one-time product.
        """
        self._logger.info(
            "Patching one-time product", package_name=package_name, product_id=product_id
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .onetimeproducts()
                .patch(
                    packageName=package_name,
                    productId=product_id,
                    updateMask=update_mask,
                    regionsVersion_version=regions_version,
                    body=product,
                )
            )
            return self._parse_one_time_product(package_name, result)

        except HttpError as e:
            self._logger.exception("Failed to patch one-time product", error=str(e))
            raise PlayStoreClientError(f"Failed to patch one-time product: {e.reason}") from e

    def delete_one_time_product(
        self, package_name: str, product_id: str
    ) -> OneTimeProductActionResult:
        """Delete a one-time product.

        Args:
            package_name: App package name.
            product_id: One-time product ID.

        Returns:
            Action result with success status.
        """
        self._logger.info(
            "Deleting one-time product", package_name=package_name, product_id=product_id
        )
        service = self._get_service()

        try:
            self._execute(
                service.monetization()
                .onetimeproducts()
                .delete(packageName=package_name, productId=product_id)
            )

            return OneTimeProductActionResult(
                success=True,
                package_name=package_name,
                product_id=product_id,
                message=f"One-time product {product_id} deleted successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to delete one-time product", error=str(e))
            raise PlayStoreClientError(f"Failed to delete one-time product: {e.reason}") from e

    def batch_update_one_time_products(
        self, package_name: str, requests: list[dict[str, Any]]
    ) -> list[OneTimeProduct]:
        """Update multiple one-time products in a single operation.

        Args:
            package_name: App package name.
            requests: List of UpdateOneTimeProductRequest bodies.

        Returns:
            List of updated one-time products.
        """
        self._logger.info(
            "Batch updating one-time products", package_name=package_name, count=len(requests)
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .onetimeproducts()
                .batchUpdate(packageName=package_name, body={"requests": requests})
            )

            return [
                self._parse_one_time_product(package_name, data)
                for data in result.get("oneTimeProducts", [])
            ]

        except HttpError as e:
            self._logger.exception("Failed to batch update one-time products", error=str(e))
            raise PlayStoreClientError(
                f"Failed to batch update one-time products: {e.reason}"
            ) from e

    def batch_delete_one_time_products(
        self, package_name: str, requests: list[dict[str, Any]]
    ) -> OneTimeProductActionResult:
        """Delete multiple one-time products in a single operation.

        Args:
            package_name: App package name.
            requests: List of DeleteOneTimeProductRequest bodies.

        Returns:
            Action result with success status.
        """
        self._logger.info(
            "Batch deleting one-time products", package_name=package_name, count=len(requests)
        )
        service = self._get_service()

        try:
            self._execute(
                service.monetization()
                .onetimeproducts()
                .batchDelete(packageName=package_name, body={"requests": requests})
            )

            return OneTimeProductActionResult(
                success=True,
                package_name=package_name,
                product_id=None,
                message=f"Deleted {len(requests)} one-time product(s) successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to batch delete one-time products", error=str(e))
            raise PlayStoreClientError(
                f"Failed to batch delete one-time products: {e.reason}"
            ) from e

    # =========================================================================
    # One-Time Product Purchase Options API
    # =========================================================================

    def batch_delete_purchase_options(
        self, package_name: str, product_id: str, requests: list[dict[str, Any]]
    ) -> OneTimeProductActionResult:
        """Delete multiple purchase options from a one-time product in a single operation.

        Args:
            package_name: App package name.
            product_id: Parent one-time product ID.
            requests: List of DeletePurchaseOptionRequest bodies.

        Returns:
            Action result with success status.
        """
        self._logger.info(
            "Batch deleting purchase options",
            package_name=package_name,
            product_id=product_id,
            count=len(requests),
        )
        service = self._get_service()

        try:
            self._execute(
                service.monetization()
                .onetimeproducts()
                .purchaseOptions()
                .batchDelete(
                    packageName=package_name,
                    productId=product_id,
                    body={"requests": requests},
                )
            )

            return OneTimeProductActionResult(
                success=True,
                package_name=package_name,
                product_id=product_id,
                message=f"Deleted {len(requests)} purchase option(s) successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to batch delete purchase options", error=str(e))
            raise PlayStoreClientError(
                f"Failed to batch delete purchase options: {e.reason}"
            ) from e

    def batch_update_purchase_option_states(
        self, package_name: str, product_id: str, requests: list[dict[str, Any]]
    ) -> list[OneTimeProduct]:
        """Activate or deactivate multiple purchase options in a single operation.

        Args:
            package_name: App package name.
            product_id: Parent one-time product ID.
            requests: List of UpdatePurchaseOptionStateRequest bodies (each with a
                nested activatePurchaseOptionRequest or deactivatePurchaseOptionRequest).

        Returns:
            The updated one-time products, one per request in order.
        """
        self._logger.info(
            "Batch updating purchase option states",
            package_name=package_name,
            product_id=product_id,
            count=len(requests),
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .onetimeproducts()
                .purchaseOptions()
                .batchUpdateStates(
                    packageName=package_name,
                    productId=product_id,
                    body={"requests": requests},
                )
            )

            return [
                self._parse_one_time_product(package_name, data)
                for data in result.get("oneTimeProducts", [])
            ]

        except HttpError as e:
            self._logger.exception("Failed to batch update purchase option states", error=str(e))
            raise PlayStoreClientError(
                f"Failed to batch update purchase option states: {e.reason}"
            ) from e

    # =========================================================================
    # One-Time Product Purchase Option Offers API
    # =========================================================================

    @staticmethod
    def _parse_one_time_product_offer(data: dict[str, Any]) -> OneTimeProductOffer:
        """Parse a OneTimeProductOffer API resource into a OneTimeProductOffer model."""
        return OneTimeProductOffer(
            package_name=data.get("packageName", ""),
            product_id=data.get("productId", ""),
            purchase_option_id=data.get("purchaseOptionId", ""),
            offer_id=data.get("offerId", ""),
            state=data.get("state"),
            offer_tags=[
                tag["tag"] for tag in data.get("offerTags", []) if tag.get("tag") is not None
            ],
            regions_version=data.get("regionsVersion", {}).get("version"),
        )

    def list_purchase_option_offers(
        self, package_name: str, product_id: str, purchase_option_id: str
    ) -> list[OneTimeProductOffer]:
        """List all offers for a one-time product purchase option.

        Args:
            package_name: App package name.
            product_id: Parent one-time product ID ('-' wildcard allowed).
            purchase_option_id: Parent purchase option ID ('-' wildcard allowed).

        Returns:
            List of one-time product offers.
        """
        self._logger.info(
            "Listing purchase option offers",
            package_name=package_name,
            product_id=product_id,
            purchase_option_id=purchase_option_id,
        )
        service = self._get_service()

        try:
            offers: list[OneTimeProductOffer] = []
            page_token: str | None = None
            while True:
                kwargs: dict[str, Any] = {
                    "packageName": package_name,
                    "productId": product_id,
                    "purchaseOptionId": purchase_option_id,
                }
                if page_token:
                    kwargs["pageToken"] = page_token
                result = self._execute(
                    service.monetization()
                    .onetimeproducts()
                    .purchaseOptions()
                    .offers()
                    .list(**kwargs)
                )
                offers.extend(
                    self._parse_one_time_product_offer(offer)
                    for offer in result.get("oneTimeProductOffers", [])
                )
                page_token = result.get("nextPageToken")
                if not page_token:
                    break

            return offers

        except HttpError as e:
            self._logger.exception("Failed to list purchase option offers", error=str(e))
            raise PlayStoreClientError(f"Failed to list purchase option offers: {e.reason}") from e

    def batch_get_purchase_option_offers(
        self,
        package_name: str,
        product_id: str,
        purchase_option_id: str,
        requests: list[dict[str, Any]],
    ) -> list[OneTimeProductOffer]:
        """Get details for multiple one-time product offers in a single operation.

        Args:
            package_name: App package name.
            product_id: Parent one-time product ID ('-' wildcard allowed).
            purchase_option_id: Parent purchase option ID ('-' wildcard allowed).
            requests: List of GetOneTimeProductOfferRequest bodies.

        Returns:
            List of one-time product offers.
        """
        self._logger.info(
            "Batch getting purchase option offers",
            package_name=package_name,
            product_id=product_id,
            purchase_option_id=purchase_option_id,
            count=len(requests),
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .onetimeproducts()
                .purchaseOptions()
                .offers()
                .batchGet(
                    packageName=package_name,
                    productId=product_id,
                    purchaseOptionId=purchase_option_id,
                    body={"requests": requests},
                )
            )
            return [
                self._parse_one_time_product_offer(offer)
                for offer in result.get("oneTimeProductOffers", [])
            ]

        except HttpError as e:
            self._logger.exception("Failed to batch get purchase option offers", error=str(e))
            raise PlayStoreClientError(
                f"Failed to batch get purchase option offers: {e.reason}"
            ) from e

    def activate_purchase_option_offer(
        self, package_name: str, product_id: str, purchase_option_id: str, offer_id: str
    ) -> OneTimeProductOffer:
        """Activate a one-time product offer.

        Args:
            package_name: App package name.
            product_id: Parent one-time product ID.
            purchase_option_id: Parent purchase option ID.
            offer_id: One-time product offer ID to activate.

        Returns:
            The updated one-time product offer.
        """
        self._logger.info(
            "Activating purchase option offer",
            package_name=package_name,
            product_id=product_id,
            purchase_option_id=purchase_option_id,
            offer_id=offer_id,
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .onetimeproducts()
                .purchaseOptions()
                .offers()
                .activate(
                    packageName=package_name,
                    productId=product_id,
                    purchaseOptionId=purchase_option_id,
                    offerId=offer_id,
                    body={
                        "packageName": package_name,
                        "productId": product_id,
                        "purchaseOptionId": purchase_option_id,
                        "offerId": offer_id,
                    },
                )
            )
            return self._parse_one_time_product_offer(result)

        except HttpError as e:
            self._logger.exception("Failed to activate purchase option offer", error=str(e))
            raise PlayStoreClientError(
                f"Failed to activate purchase option offer: {e.reason}"
            ) from e

    def deactivate_purchase_option_offer(
        self, package_name: str, product_id: str, purchase_option_id: str, offer_id: str
    ) -> OneTimeProductOffer:
        """Deactivate a one-time product offer.

        Args:
            package_name: App package name.
            product_id: Parent one-time product ID.
            purchase_option_id: Parent purchase option ID.
            offer_id: One-time product offer ID to deactivate.

        Returns:
            The updated one-time product offer.
        """
        self._logger.info(
            "Deactivating purchase option offer",
            package_name=package_name,
            product_id=product_id,
            purchase_option_id=purchase_option_id,
            offer_id=offer_id,
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .onetimeproducts()
                .purchaseOptions()
                .offers()
                .deactivate(
                    packageName=package_name,
                    productId=product_id,
                    purchaseOptionId=purchase_option_id,
                    offerId=offer_id,
                    body={
                        "packageName": package_name,
                        "productId": product_id,
                        "purchaseOptionId": purchase_option_id,
                        "offerId": offer_id,
                    },
                )
            )
            return self._parse_one_time_product_offer(result)

        except HttpError as e:
            self._logger.exception("Failed to deactivate purchase option offer", error=str(e))
            raise PlayStoreClientError(
                f"Failed to deactivate purchase option offer: {e.reason}"
            ) from e

    def cancel_purchase_option_offer(
        self, package_name: str, product_id: str, purchase_option_id: str, offer_id: str
    ) -> OneTimeProductOffer:
        """Cancel a one-time product offer (e.g. a pre-order offer).

        Args:
            package_name: App package name.
            product_id: Parent one-time product ID.
            purchase_option_id: Parent purchase option ID.
            offer_id: One-time product offer ID to cancel.

        Returns:
            The updated one-time product offer.
        """
        self._logger.info(
            "Cancelling purchase option offer",
            package_name=package_name,
            product_id=product_id,
            purchase_option_id=purchase_option_id,
            offer_id=offer_id,
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .onetimeproducts()
                .purchaseOptions()
                .offers()
                .cancel(
                    packageName=package_name,
                    productId=product_id,
                    purchaseOptionId=purchase_option_id,
                    offerId=offer_id,
                    body={
                        "packageName": package_name,
                        "productId": product_id,
                        "purchaseOptionId": purchase_option_id,
                        "offerId": offer_id,
                    },
                )
            )
            return self._parse_one_time_product_offer(result)

        except HttpError as e:
            self._logger.exception("Failed to cancel purchase option offer", error=str(e))
            raise PlayStoreClientError(f"Failed to cancel purchase option offer: {e.reason}") from e

    def batch_update_purchase_option_offers(
        self,
        package_name: str,
        product_id: str,
        purchase_option_id: str,
        requests: list[dict[str, Any]],
    ) -> list[OneTimeProductOffer]:
        """Create or update multiple one-time product offers in a single operation.

        Args:
            package_name: App package name.
            product_id: Parent one-time product ID ('-' wildcard allowed).
            purchase_option_id: Parent purchase option ID ('-' wildcard allowed).
            requests: List of UpdateOneTimeProductOfferRequest bodies.

        Returns:
            List of updated one-time product offers.
        """
        self._logger.info(
            "Batch updating purchase option offers",
            package_name=package_name,
            product_id=product_id,
            purchase_option_id=purchase_option_id,
            count=len(requests),
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .onetimeproducts()
                .purchaseOptions()
                .offers()
                .batchUpdate(
                    packageName=package_name,
                    productId=product_id,
                    purchaseOptionId=purchase_option_id,
                    body={"requests": requests},
                )
            )
            return [
                self._parse_one_time_product_offer(offer)
                for offer in result.get("oneTimeProductOffers", [])
            ]

        except HttpError as e:
            self._logger.exception("Failed to batch update purchase option offers", error=str(e))
            raise PlayStoreClientError(
                f"Failed to batch update purchase option offers: {e.reason}"
            ) from e

    def batch_update_purchase_option_offer_states(
        self,
        package_name: str,
        product_id: str,
        purchase_option_id: str,
        requests: list[dict[str, Any]],
    ) -> list[OneTimeProductOffer]:
        """Activate, deactivate or cancel multiple one-time product offers at once.

        Args:
            package_name: App package name.
            product_id: Parent one-time product ID ('-' wildcard allowed).
            purchase_option_id: Parent purchase option ID ('-' wildcard allowed).
            requests: List of UpdateOneTimeProductOfferStateRequest bodies (each with a
                nested activate/deactivate/cancel one-time product offer request).

        Returns:
            The updated one-time product offers, one per request in order.
        """
        self._logger.info(
            "Batch updating purchase option offer states",
            package_name=package_name,
            product_id=product_id,
            purchase_option_id=purchase_option_id,
            count=len(requests),
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .onetimeproducts()
                .purchaseOptions()
                .offers()
                .batchUpdateStates(
                    packageName=package_name,
                    productId=product_id,
                    purchaseOptionId=purchase_option_id,
                    body={"requests": requests},
                )
            )
            return [
                self._parse_one_time_product_offer(offer)
                for offer in result.get("oneTimeProductOffers", [])
            ]

        except HttpError as e:
            self._logger.exception(
                "Failed to batch update purchase option offer states", error=str(e)
            )
            raise PlayStoreClientError(
                f"Failed to batch update purchase option offer states: {e.reason}"
            ) from e

    def batch_delete_purchase_option_offers(
        self,
        package_name: str,
        product_id: str,
        purchase_option_id: str,
        requests: list[dict[str, Any]],
    ) -> OneTimeProductActionResult:
        """Delete multiple one-time product offers in a single operation.

        Args:
            package_name: App package name.
            product_id: Parent one-time product ID ('-' wildcard allowed).
            purchase_option_id: Parent purchase option ID ('-' wildcard allowed).
            requests: List of DeleteOneTimeProductOfferRequest bodies.

        Returns:
            Action result with success status.
        """
        self._logger.info(
            "Batch deleting purchase option offers",
            package_name=package_name,
            product_id=product_id,
            purchase_option_id=purchase_option_id,
            count=len(requests),
        )
        service = self._get_service()

        try:
            self._execute(
                service.monetization()
                .onetimeproducts()
                .purchaseOptions()
                .offers()
                .batchDelete(
                    packageName=package_name,
                    productId=product_id,
                    purchaseOptionId=purchase_option_id,
                    body={"requests": requests},
                )
            )

            return OneTimeProductActionResult(
                success=True,
                package_name=package_name,
                product_id=product_id,
                message=f"Deleted {len(requests)} one-time product offer(s) successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to batch delete purchase option offers", error=str(e))
            raise PlayStoreClientError(
                f"Failed to batch delete purchase option offers: {e.reason}"
            ) from e

    # =========================================================================
    # Subscription Catalog API
    # =========================================================================

    @staticmethod
    def _parse_subscription(package_name: str, data: dict[str, Any]) -> SubscriptionProduct:
        """Parse a Subscription API resource into a SubscriptionProduct model."""
        return SubscriptionProduct(
            product_id=data.get("productId", ""),
            package_name=package_name,
            status=None,
            base_plans=data.get("basePlans", []),
        )

    def get_subscription(self, package_name: str, product_id: str) -> SubscriptionProduct:
        """Get details of a specific subscription product.

        Args:
            package_name: App package name.
            product_id: Subscription product ID.

        Returns:
            Subscription product details.
        """
        self._logger.info("Getting subscription", package_name=package_name, product_id=product_id)
        service = self._get_service()

        try:
            data = self._execute(
                service.monetization()
                .subscriptions()
                .get(packageName=package_name, productId=product_id)
            )
            return self._parse_subscription(package_name, data)

        except HttpError as e:
            self._logger.exception("Failed to get subscription", error=str(e))
            raise PlayStoreClientError(f"Failed to get subscription: {e.reason}") from e

    def create_subscription(
        self,
        package_name: str,
        product_id: str,
        subscription: dict[str, Any],
        regions_version: str = "2022/02",
    ) -> SubscriptionProduct:
        """Create a new subscription product.

        Args:
            package_name: App package name.
            product_id: Subscription product ID (query param).
            subscription: Subscription resource body.
            regions_version: Version of available regions to use for regional prices.

        Returns:
            The created subscription product.
        """
        self._logger.info("Creating subscription", package_name=package_name, product_id=product_id)
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .subscriptions()
                .create(
                    packageName=package_name,
                    productId=product_id,
                    regionsVersion_version=regions_version,
                    body=subscription,
                )
            )
            return self._parse_subscription(package_name, result)

        except HttpError as e:
            self._logger.exception("Failed to create subscription", error=str(e))
            raise PlayStoreClientError(f"Failed to create subscription: {e.reason}") from e

    def patch_subscription(
        self,
        package_name: str,
        product_id: str,
        subscription: dict[str, Any],
        update_mask: str,
        regions_version: str = "2022/02",
    ) -> SubscriptionProduct:
        """Partially update an existing subscription product.

        Args:
            package_name: App package name.
            product_id: Subscription product ID.
            subscription: Partial Subscription resource body.
            update_mask: Comma-separated list of fields to update.
            regions_version: Version of available regions to use for regional prices.

        Returns:
            The patched subscription product.
        """
        self._logger.info("Patching subscription", package_name=package_name, product_id=product_id)
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .subscriptions()
                .patch(
                    packageName=package_name,
                    productId=product_id,
                    updateMask=update_mask,
                    regionsVersion_version=regions_version,
                    body=subscription,
                )
            )
            return self._parse_subscription(package_name, result)

        except HttpError as e:
            self._logger.exception("Failed to patch subscription", error=str(e))
            raise PlayStoreClientError(f"Failed to patch subscription: {e.reason}") from e

    def delete_subscription(self, package_name: str, product_id: str) -> SubscriptionCatalogResult:
        """Delete a subscription product.

        Args:
            package_name: App package name.
            product_id: Subscription product ID.

        Returns:
            Action result with success status.
        """
        self._logger.info("Deleting subscription", package_name=package_name, product_id=product_id)
        service = self._get_service()

        try:
            self._execute(
                service.monetization()
                .subscriptions()
                .delete(packageName=package_name, productId=product_id)
            )

            return SubscriptionCatalogResult(
                success=True,
                package_name=package_name,
                product_id=product_id,
                message=f"Subscription {product_id} deleted successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to delete subscription", error=str(e))
            raise PlayStoreClientError(f"Failed to delete subscription: {e.reason}") from e

    def batch_get_subscriptions(
        self, package_name: str, product_ids: list[str]
    ) -> list[SubscriptionProduct]:
        """Get details for multiple subscription products.

        Args:
            package_name: App package name.
            product_ids: List of subscription product IDs to retrieve.

        Returns:
            List of subscription products.
        """
        self._logger.info(
            "Batch getting subscriptions", package_name=package_name, count=len(product_ids)
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .subscriptions()
                .batchGet(packageName=package_name, productIds=product_ids)
            )

            return [
                self._parse_subscription(package_name, data)
                for data in result.get("subscriptions", [])
            ]

        except HttpError as e:
            self._logger.exception("Failed to batch get subscriptions", error=str(e))
            raise PlayStoreClientError(f"Failed to batch get subscriptions: {e.reason}") from e

    def batch_update_subscriptions(
        self, package_name: str, requests: list[dict[str, Any]]
    ) -> list[SubscriptionProduct]:
        """Update multiple subscription products in a single operation.

        Args:
            package_name: App package name.
            requests: List of UpdateSubscriptionRequest bodies.

        Returns:
            List of updated subscription products.
        """
        self._logger.info(
            "Batch updating subscriptions", package_name=package_name, count=len(requests)
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .subscriptions()
                .batchUpdate(packageName=package_name, body={"requests": requests})
            )

            return [
                self._parse_subscription(package_name, data)
                for data in result.get("subscriptions", [])
            ]

        except HttpError as e:
            self._logger.exception("Failed to batch update subscriptions", error=str(e))
            raise PlayStoreClientError(f"Failed to batch update subscriptions: {e.reason}") from e

    # =========================================================================
    # Subscription Base Plans API
    # =========================================================================

    def activate_base_plan(
        self, package_name: str, product_id: str, base_plan_id: str
    ) -> SubscriptionProduct:
        """Activate a subscription base plan.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            base_plan_id: Base plan ID to activate.

        Returns:
            The updated subscription product.
        """
        self._logger.info(
            "Activating base plan",
            package_name=package_name,
            product_id=product_id,
            base_plan_id=base_plan_id,
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .subscriptions()
                .basePlans()
                .activate(
                    packageName=package_name,
                    productId=product_id,
                    basePlanId=base_plan_id,
                    body={
                        "packageName": package_name,
                        "productId": product_id,
                        "basePlanId": base_plan_id,
                    },
                )
            )
            return self._parse_subscription(package_name, result)

        except HttpError as e:
            self._logger.exception("Failed to activate base plan", error=str(e))
            raise PlayStoreClientError(f"Failed to activate base plan: {e.reason}") from e

    def deactivate_base_plan(
        self, package_name: str, product_id: str, base_plan_id: str
    ) -> SubscriptionProduct:
        """Deactivate a subscription base plan.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            base_plan_id: Base plan ID to deactivate.

        Returns:
            The updated subscription product.
        """
        self._logger.info(
            "Deactivating base plan",
            package_name=package_name,
            product_id=product_id,
            base_plan_id=base_plan_id,
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .subscriptions()
                .basePlans()
                .deactivate(
                    packageName=package_name,
                    productId=product_id,
                    basePlanId=base_plan_id,
                    body={
                        "packageName": package_name,
                        "productId": product_id,
                        "basePlanId": base_plan_id,
                    },
                )
            )
            return self._parse_subscription(package_name, result)

        except HttpError as e:
            self._logger.exception("Failed to deactivate base plan", error=str(e))
            raise PlayStoreClientError(f"Failed to deactivate base plan: {e.reason}") from e

    def delete_base_plan(
        self, package_name: str, product_id: str, base_plan_id: str
    ) -> SubscriptionCatalogResult:
        """Delete a subscription base plan.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            base_plan_id: Base plan ID to delete.

        Returns:
            Action result with success status.
        """
        self._logger.info(
            "Deleting base plan",
            package_name=package_name,
            product_id=product_id,
            base_plan_id=base_plan_id,
        )
        service = self._get_service()

        try:
            self._execute(
                service.monetization()
                .subscriptions()
                .basePlans()
                .delete(
                    packageName=package_name,
                    productId=product_id,
                    basePlanId=base_plan_id,
                )
            )

            return SubscriptionCatalogResult(
                success=True,
                package_name=package_name,
                product_id=product_id,
                message=f"Base plan {base_plan_id} deleted successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to delete base plan", error=str(e))
            raise PlayStoreClientError(f"Failed to delete base plan: {e.reason}") from e

    def migrate_base_plan_prices(
        self,
        package_name: str,
        product_id: str,
        base_plan_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        """Migrate subscribers to the current base plan prices.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            base_plan_id: Base plan ID whose prices to migrate.
            request: MigrateBasePlanPricesRequest body.

        Returns:
            The raw MigrateBasePlanPricesResponse dict.
        """
        self._logger.info(
            "Migrating base plan prices",
            package_name=package_name,
            product_id=product_id,
            base_plan_id=base_plan_id,
        )
        service = self._get_service()

        try:
            result: dict[str, Any] = self._execute(
                service.monetization()
                .subscriptions()
                .basePlans()
                .migratePrices(
                    packageName=package_name,
                    productId=product_id,
                    basePlanId=base_plan_id,
                    body=request,
                )
            )
            return result

        except HttpError as e:
            self._logger.exception("Failed to migrate base plan prices", error=str(e))
            raise PlayStoreClientError(f"Failed to migrate base plan prices: {e.reason}") from e

    def batch_migrate_base_plan_prices(
        self,
        package_name: str,
        product_id: str,
        requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Migrate prices for multiple base plans in a single operation.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            requests: List of MigrateBasePlanPricesRequest bodies.

        Returns:
            The raw BatchMigrateBasePlanPricesResponse dict.
        """
        self._logger.info(
            "Batch migrating base plan prices",
            package_name=package_name,
            product_id=product_id,
            count=len(requests),
        )
        service = self._get_service()

        try:
            result: dict[str, Any] = self._execute(
                service.monetization()
                .subscriptions()
                .basePlans()
                .batchMigratePrices(
                    packageName=package_name,
                    productId=product_id,
                    body={"requests": requests},
                )
            )
            return result

        except HttpError as e:
            self._logger.exception("Failed to batch migrate base plan prices", error=str(e))
            raise PlayStoreClientError(
                f"Failed to batch migrate base plan prices: {e.reason}"
            ) from e

    def batch_update_base_plan_states(
        self,
        package_name: str,
        product_id: str,
        requests: list[dict[str, Any]],
    ) -> list[SubscriptionProduct]:
        """Activate or deactivate multiple base plans in a single operation.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            requests: List of UpdateBasePlanStateRequest bodies (each with a
                nested activateBasePlanRequest or deactivateBasePlanRequest).

        Returns:
            The updated subscriptions, one per request in order.
        """
        self._logger.info(
            "Batch updating base plan states",
            package_name=package_name,
            product_id=product_id,
            count=len(requests),
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .subscriptions()
                .basePlans()
                .batchUpdateStates(
                    packageName=package_name,
                    productId=product_id,
                    body={"requests": requests},
                )
            )
            return [
                self._parse_subscription(package_name, sub)
                for sub in result.get("subscriptions", [])
            ]

        except HttpError as e:
            self._logger.exception("Failed to batch update base plan states", error=str(e))
            raise PlayStoreClientError(
                f"Failed to batch update base plan states: {e.reason}"
            ) from e

    # =========================================================================
    # Subscription Offers API
    # =========================================================================

    @staticmethod
    def _parse_subscription_offer(offer_data: dict[str, Any]) -> SubscriptionOffer:
        """Parse a SubscriptionOffer API resource into a SubscriptionOffer model."""
        return SubscriptionOffer(
            package_name=offer_data.get("packageName", ""),
            product_id=offer_data.get("productId", ""),
            base_plan_id=offer_data.get("basePlanId", ""),
            offer_id=offer_data.get("offerId", ""),
            state=offer_data.get("state"),
            offer_tags=[
                tag["tag"] for tag in offer_data.get("offerTags", []) if tag.get("tag") is not None
            ],
            phases=offer_data.get("phases", []),
            regions_version=offer_data.get("regionsVersion", {}).get("version"),
        )

    def get_subscription_offer(
        self, package_name: str, product_id: str, base_plan_id: str, offer_id: str
    ) -> SubscriptionOffer:
        """Get details of a specific subscription offer.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            base_plan_id: Parent base plan ID.
            offer_id: Subscription offer ID.

        Returns:
            The subscription offer details.
        """
        self._logger.info(
            "Getting subscription offer",
            package_name=package_name,
            product_id=product_id,
            base_plan_id=base_plan_id,
            offer_id=offer_id,
        )
        service = self._get_service()

        try:
            data = self._execute(
                service.monetization()
                .subscriptions()
                .basePlans()
                .offers()
                .get(
                    packageName=package_name,
                    productId=product_id,
                    basePlanId=base_plan_id,
                    offerId=offer_id,
                )
            )
            return self._parse_subscription_offer(data)

        except HttpError as e:
            self._logger.exception("Failed to get subscription offer", error=str(e))
            raise PlayStoreClientError(f"Failed to get subscription offer: {e.reason}") from e

    def list_subscription_offers(
        self, package_name: str, product_id: str, base_plan_id: str
    ) -> list[SubscriptionOffer]:
        """List all offers for a subscription base plan.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            base_plan_id: Parent base plan ID ('-' wildcard allowed).

        Returns:
            List of subscription offers.
        """
        self._logger.info(
            "Listing subscription offers",
            package_name=package_name,
            product_id=product_id,
            base_plan_id=base_plan_id,
        )
        service = self._get_service()

        try:
            offers: list[SubscriptionOffer] = []
            page_token: str | None = None
            while True:
                kwargs: dict[str, Any] = {
                    "packageName": package_name,
                    "productId": product_id,
                    "basePlanId": base_plan_id,
                }
                if page_token:
                    kwargs["pageToken"] = page_token
                result = self._execute(
                    service.monetization().subscriptions().basePlans().offers().list(**kwargs)
                )
                offers.extend(
                    self._parse_subscription_offer(offer)
                    for offer in result.get("subscriptionOffers", [])
                )
                page_token = result.get("nextPageToken")
                if not page_token:
                    break

            return offers

        except HttpError as e:
            self._logger.exception("Failed to list subscription offers", error=str(e))
            raise PlayStoreClientError(f"Failed to list subscription offers: {e.reason}") from e

    def create_subscription_offer(
        self,
        package_name: str,
        product_id: str,
        base_plan_id: str,
        offer_id: str,
        offer: dict[str, Any],
        regions_version: str = "2022/02",
    ) -> SubscriptionOffer:
        """Create a new subscription offer.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            base_plan_id: Parent base plan ID.
            offer_id: Subscription offer ID (query param).
            offer: SubscriptionOffer resource body.
            regions_version: Version of available regions to use for regional prices.

        Returns:
            The created subscription offer.
        """
        self._logger.info(
            "Creating subscription offer",
            package_name=package_name,
            product_id=product_id,
            base_plan_id=base_plan_id,
            offer_id=offer_id,
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .subscriptions()
                .basePlans()
                .offers()
                .create(
                    packageName=package_name,
                    productId=product_id,
                    basePlanId=base_plan_id,
                    offerId=offer_id,
                    regionsVersion_version=regions_version,
                    body=offer,
                )
            )
            return self._parse_subscription_offer(result)

        except HttpError as e:
            self._logger.exception("Failed to create subscription offer", error=str(e))
            raise PlayStoreClientError(f"Failed to create subscription offer: {e.reason}") from e

    def patch_subscription_offer(
        self,
        package_name: str,
        product_id: str,
        base_plan_id: str,
        offer_id: str,
        offer: dict[str, Any],
        update_mask: str,
        regions_version: str = "2022/02",
    ) -> SubscriptionOffer:
        """Partially update an existing subscription offer.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            base_plan_id: Parent base plan ID.
            offer_id: Subscription offer ID.
            offer: Partial SubscriptionOffer resource body.
            update_mask: Comma-separated list of fields to update.
            regions_version: Version of available regions to use for regional prices.

        Returns:
            The patched subscription offer.
        """
        self._logger.info(
            "Patching subscription offer",
            package_name=package_name,
            product_id=product_id,
            base_plan_id=base_plan_id,
            offer_id=offer_id,
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .subscriptions()
                .basePlans()
                .offers()
                .patch(
                    packageName=package_name,
                    productId=product_id,
                    basePlanId=base_plan_id,
                    offerId=offer_id,
                    updateMask=update_mask,
                    regionsVersion_version=regions_version,
                    body=offer,
                )
            )
            return self._parse_subscription_offer(result)

        except HttpError as e:
            self._logger.exception("Failed to patch subscription offer", error=str(e))
            raise PlayStoreClientError(f"Failed to patch subscription offer: {e.reason}") from e

    def activate_subscription_offer(
        self, package_name: str, product_id: str, base_plan_id: str, offer_id: str
    ) -> SubscriptionOffer:
        """Activate a subscription offer.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            base_plan_id: Parent base plan ID.
            offer_id: Subscription offer ID to activate.

        Returns:
            The updated subscription offer.
        """
        self._logger.info(
            "Activating subscription offer",
            package_name=package_name,
            product_id=product_id,
            base_plan_id=base_plan_id,
            offer_id=offer_id,
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .subscriptions()
                .basePlans()
                .offers()
                .activate(
                    packageName=package_name,
                    productId=product_id,
                    basePlanId=base_plan_id,
                    offerId=offer_id,
                    body={
                        "packageName": package_name,
                        "productId": product_id,
                        "basePlanId": base_plan_id,
                        "offerId": offer_id,
                    },
                )
            )
            return self._parse_subscription_offer(result)

        except HttpError as e:
            self._logger.exception("Failed to activate subscription offer", error=str(e))
            raise PlayStoreClientError(f"Failed to activate subscription offer: {e.reason}") from e

    def deactivate_subscription_offer(
        self, package_name: str, product_id: str, base_plan_id: str, offer_id: str
    ) -> SubscriptionOffer:
        """Deactivate a subscription offer.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            base_plan_id: Parent base plan ID.
            offer_id: Subscription offer ID to deactivate.

        Returns:
            The updated subscription offer.
        """
        self._logger.info(
            "Deactivating subscription offer",
            package_name=package_name,
            product_id=product_id,
            base_plan_id=base_plan_id,
            offer_id=offer_id,
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .subscriptions()
                .basePlans()
                .offers()
                .deactivate(
                    packageName=package_name,
                    productId=product_id,
                    basePlanId=base_plan_id,
                    offerId=offer_id,
                    body={
                        "packageName": package_name,
                        "productId": product_id,
                        "basePlanId": base_plan_id,
                        "offerId": offer_id,
                    },
                )
            )
            return self._parse_subscription_offer(result)

        except HttpError as e:
            self._logger.exception("Failed to deactivate subscription offer", error=str(e))
            raise PlayStoreClientError(
                f"Failed to deactivate subscription offer: {e.reason}"
            ) from e

    def delete_subscription_offer(
        self, package_name: str, product_id: str, base_plan_id: str, offer_id: str
    ) -> SubscriptionCatalogResult:
        """Delete a subscription offer.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            base_plan_id: Parent base plan ID.
            offer_id: Subscription offer ID to delete.

        Returns:
            Action result with success status.
        """
        self._logger.info(
            "Deleting subscription offer",
            package_name=package_name,
            product_id=product_id,
            base_plan_id=base_plan_id,
            offer_id=offer_id,
        )
        service = self._get_service()

        try:
            self._execute(
                service.monetization()
                .subscriptions()
                .basePlans()
                .offers()
                .delete(
                    packageName=package_name,
                    productId=product_id,
                    basePlanId=base_plan_id,
                    offerId=offer_id,
                )
            )

            return SubscriptionCatalogResult(
                success=True,
                package_name=package_name,
                product_id=product_id,
                message=f"Subscription offer {offer_id} deleted successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to delete subscription offer", error=str(e))
            raise PlayStoreClientError(f"Failed to delete subscription offer: {e.reason}") from e

    def batch_get_subscription_offers(
        self,
        package_name: str,
        product_id: str,
        base_plan_id: str,
        requests: list[dict[str, Any]],
    ) -> list[SubscriptionOffer]:
        """Get details for multiple subscription offers in a single operation.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            base_plan_id: Parent base plan ID ('-' wildcard allowed).
            requests: List of GetSubscriptionOfferRequest bodies.

        Returns:
            List of subscription offers.
        """
        self._logger.info(
            "Batch getting subscription offers",
            package_name=package_name,
            product_id=product_id,
            base_plan_id=base_plan_id,
            count=len(requests),
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .subscriptions()
                .basePlans()
                .offers()
                .batchGet(
                    packageName=package_name,
                    productId=product_id,
                    basePlanId=base_plan_id,
                    body={"requests": requests},
                )
            )
            return [
                self._parse_subscription_offer(offer)
                for offer in result.get("subscriptionOffers", [])
            ]

        except HttpError as e:
            self._logger.exception("Failed to batch get subscription offers", error=str(e))
            raise PlayStoreClientError(
                f"Failed to batch get subscription offers: {e.reason}"
            ) from e

    def batch_update_subscription_offers(
        self,
        package_name: str,
        product_id: str,
        base_plan_id: str,
        requests: list[dict[str, Any]],
    ) -> list[SubscriptionOffer]:
        """Update multiple subscription offers in a single operation.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            base_plan_id: Parent base plan ID ('-' wildcard allowed).
            requests: List of UpdateSubscriptionOfferRequest bodies.

        Returns:
            List of updated subscription offers.
        """
        self._logger.info(
            "Batch updating subscription offers",
            package_name=package_name,
            product_id=product_id,
            base_plan_id=base_plan_id,
            count=len(requests),
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .subscriptions()
                .basePlans()
                .offers()
                .batchUpdate(
                    packageName=package_name,
                    productId=product_id,
                    basePlanId=base_plan_id,
                    body={"requests": requests},
                )
            )
            return [
                self._parse_subscription_offer(offer)
                for offer in result.get("subscriptionOffers", [])
            ]

        except HttpError as e:
            self._logger.exception("Failed to batch update subscription offers", error=str(e))
            raise PlayStoreClientError(
                f"Failed to batch update subscription offers: {e.reason}"
            ) from e

    def batch_update_subscription_offer_states(
        self,
        package_name: str,
        product_id: str,
        base_plan_id: str,
        requests: list[dict[str, Any]],
    ) -> list[SubscriptionOffer]:
        """Activate or deactivate multiple subscription offers in a single operation.

        Args:
            package_name: App package name.
            product_id: Parent subscription product ID.
            base_plan_id: Parent base plan ID ('-' wildcard allowed).
            requests: List of UpdateSubscriptionOfferStateRequest bodies (each with a
                nested activateSubscriptionOfferRequest or
                deactivateSubscriptionOfferRequest).

        Returns:
            The updated subscription offers, one per request in order.
        """
        self._logger.info(
            "Batch updating subscription offer states",
            package_name=package_name,
            product_id=product_id,
            base_plan_id=base_plan_id,
            count=len(requests),
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.monetization()
                .subscriptions()
                .basePlans()
                .offers()
                .batchUpdateStates(
                    packageName=package_name,
                    productId=product_id,
                    basePlanId=base_plan_id,
                    body={"requests": requests},
                )
            )
            return [
                self._parse_subscription_offer(offer)
                for offer in result.get("subscriptionOffers", [])
            ]

        except HttpError as e:
            self._logger.exception("Failed to batch update subscription offer states", error=str(e))
            raise PlayStoreClientError(
                f"Failed to batch update subscription offer states: {e.reason}"
            ) from e

    # =========================================================================
    # Store Listings API
    # =========================================================================

    def get_listing(self, package_name: str, language: str = "en-US") -> Listing:
        """Get store listing for a specific language.

        Args:
            package_name: App package name.
            language: Language code (e.g., en-US, es-ES).

        Returns:
            Store listing information.
        """
        self._logger.info("Getting store listing", package_name=package_name, language=language)
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            listing_data = self._execute(
                service.edits()
                .listings()
                .get(packageName=package_name, editId=edit_id, language=language)
            )

            return Listing(
                language=language,
                title=listing_data.get("title"),
                full_description=listing_data.get("fullDescription"),
                short_description=listing_data.get("shortDescription"),
                video=listing_data.get("video"),
            )
        except HttpError as e:
            self._logger.exception("Failed to get store listing", error=str(e))
            raise PlayStoreClientError(f"Failed to get store listing: {e.reason}") from e
        finally:
            self._delete_edit(package_name, edit_id)

    def update_listing(
        self,
        package_name: str,
        language: str,
        title: str | None = None,
        full_description: str | None = None,
        short_description: str | None = None,
        video: str | None = None,
    ) -> ListingUpdateResult:
        """Update store listing for a specific language.

        Args:
            package_name: App package name.
            language: Language code (e.g., en-US, es-ES).
            title: App title (max 50 characters).
            full_description: Full description (max 4000 characters).
            short_description: Short description (max 80 characters).
            video: YouTube video URL.

        Returns:
            Update result.
        """
        self._logger.info("Updating store listing", package_name=package_name, language=language)
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            # Get current listing
            try:
                current_listing = self._execute(
                    service.edits()
                    .listings()
                    .get(packageName=package_name, editId=edit_id, language=language)
                )
            except HttpError:
                current_listing = {}

            # Build update body with only provided fields
            update_body: dict[str, Any] = {}
            if title is not None:
                update_body["title"] = title
            else:
                update_body["title"] = current_listing.get("title", "")

            if full_description is not None:
                update_body["fullDescription"] = full_description
            else:
                update_body["fullDescription"] = current_listing.get("fullDescription", "")

            if short_description is not None:
                update_body["shortDescription"] = short_description
            else:
                update_body["shortDescription"] = current_listing.get("shortDescription", "")

            if video is not None:
                update_body["video"] = video

            # Update listing
            self._execute(
                service.edits()
                .listings()
                .update(
                    packageName=package_name,
                    editId=edit_id,
                    language=language,
                    body=update_body,
                )
            )

            self._commit_edit(package_name, edit_id)

            return ListingUpdateResult(
                success=True,
                package_name=package_name,
                language=language,
                message=f"Successfully updated listing for {language}",
            )

        except HttpError as e:
            self._logger.exception("Failed to update listing", error=str(e))
            self._delete_edit(package_name, edit_id)
            return ListingUpdateResult(
                success=False,
                package_name=package_name,
                language=language,
                message=f"Failed to update listing: {e.reason}",
                error=str(e),
            )
        except Exception as e:
            self._logger.exception("Failed to update listing", error=str(e))
            self._delete_edit(package_name, edit_id)
            return ListingUpdateResult(
                success=False,
                package_name=package_name,
                language=language,
                message=f"Failed to update listing: {e}",
                error=str(e),
            )

    def list_all_listings(self, package_name: str) -> list[Listing]:
        """List all store listings for all languages.

        Args:
            package_name: App package name.

        Returns:
            List of store listings.
        """
        self._logger.info("Listing all store listings", package_name=package_name)
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            result = self._execute(
                service.edits().listings().list(packageName=package_name, editId=edit_id)
            )

            listings: list[Listing] = [
                Listing(
                    language=listing_data.get("language", ""),
                    title=listing_data.get("title"),
                    full_description=listing_data.get("fullDescription"),
                    short_description=listing_data.get("shortDescription"),
                    video=listing_data.get("video"),
                )
                for listing_data in result.get("listings", [])
            ]

            return listings
        except HttpError as e:
            self._logger.exception("Failed to list store listings", error=str(e))
            raise PlayStoreClientError(f"Failed to list store listings: {e.reason}") from e
        finally:
            self._delete_edit(package_name, edit_id)

    # =========================================================================
    # Testers API
    # =========================================================================

    def get_testers(self, package_name: str, track: str) -> TesterInfo:
        """Get testers for a specific track.

        Args:
            package_name: App package name.
            track: Track name (internal, alpha, beta).

        Returns:
            Tester information.
        """
        self._logger.info("Getting testers", package_name=package_name, track=track)
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            testers_data = self._execute(
                service.edits().testers().get(packageName=package_name, editId=edit_id, track=track)
            )

            return TesterInfo(
                track=track,
                # API limitation: only returns googleGroups[], not individual tester emails
                google_groups=testers_data.get("googleGroups", []),
            )
        except HttpError as e:
            if e.resp.status == 404:
                # No testers configured
                return TesterInfo(track=track, google_groups=[])
            raise PlayStoreClientError(f"Failed to get testers: {e.reason}") from e
        finally:
            self._delete_edit(package_name, edit_id)

    def update_testers(
        self,
        package_name: str,
        track: str,
        google_groups: list[str],
    ) -> dict[str, Any]:
        """Update testers for a specific track.

        Args:
            package_name: App package name.
            track: Track name (internal, alpha, beta).
            google_groups: List of Google Group email addresses.

        Returns:
            Update result dict.
        """
        self._logger.info(
            "Updating testers",
            package_name=package_name,
            track=track,
            count=len(google_groups),
        )
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            self._execute(
                service.edits()
                .testers()
                .update(
                    packageName=package_name,
                    editId=edit_id,
                    track=track,
                    body={"googleGroups": google_groups},
                )
            )

            self._commit_edit(package_name, edit_id)

            return {"success": True, "track": track, "google_groups": google_groups}

        except HttpError as e:
            self._logger.exception("Failed to update testers", error=str(e))
            self._delete_edit(package_name, edit_id)
            return {"success": False, "track": track, "error": str(e)}
        except Exception as e:
            self._logger.exception("Failed to update testers", error=str(e))
            self._delete_edit(package_name, edit_id)
            return {"success": False, "track": track, "error": str(e)}

    # =========================================================================
    # Orders API
    # =========================================================================

    @staticmethod
    def _parse_order(package_name: str, order_data: dict[str, Any]) -> Order:
        """Parse an Orders API resource into an Order model.

        The v3 Order resource carries product IDs inside ``lineItems`` and the
        order status in ``state`` (a string enum); it has no top-level
        ``productId`` or ``purchaseState``.
        """
        line_items = [
            OrderLineItem(
                product_id=item.get("productId"),
                product_title=item.get("productTitle"),
            )
            for item in order_data.get("lineItems", [])
        ]
        return Order(
            order_id=order_data.get("orderId", ""),
            package_name=package_name,
            state=order_data.get("state"),
            line_items=line_items,
            product_ids=[li.product_id for li in line_items if li.product_id],
            purchase_token=order_data.get("purchaseToken"),
            create_time=_parse_rfc3339(order_data.get("createTime")),
        )

    def get_order(self, package_name: str, order_id: str) -> Order:
        """Get order details.

        Args:
            package_name: App package name.
            order_id: Order ID.

        Returns:
            Order information.
        """
        self._logger.info("Getting order", package_name=package_name, order_id=order_id)
        service = self._get_service()

        try:
            order_data = self._execute(
                service.orders().get(packageName=package_name, orderId=order_id)
            )

            order = self._parse_order(package_name, order_data)
            # The response normally echoes orderId; fall back to the requested id.
            if not order.order_id:
                order.order_id = order_id
            return order

        except HttpError as e:
            self._logger.exception("Failed to get order", error=str(e))
            raise PlayStoreClientError(f"Failed to get order: {e.reason}") from e

    def batch_get_orders(self, package_name: str, order_ids: list[str]) -> list[Order]:
        """Get details for multiple orders.

        Args:
            package_name: App package name.
            order_ids: List of order IDs to retrieve.

        Returns:
            List of orders.
        """
        self._logger.info("Batch getting orders", package_name=package_name, count=len(order_ids))
        service = self._get_service()

        try:
            # NOTE: googleapiclient method is lowercase "batchget" (per the discovery doc).
            result = self._execute(
                service.orders().batchget(packageName=package_name, orderIds=order_ids)
            )

            return [
                self._parse_order(package_name, order_data)
                for order_data in result.get("orders", [])
            ]

        except HttpError as e:
            self._logger.exception("Failed to batch get orders", error=str(e))
            raise PlayStoreClientError(f"Failed to batch get orders: {e.reason}") from e

    # =========================================================================
    # Expansion Files API
    # =========================================================================

    def get_expansion_file(
        self,
        package_name: str,
        version_code: int,
        expansion_file_type: str = "main",
    ) -> ExpansionFile:
        """Get expansion file information.

        Args:
            package_name: App package name.
            version_code: APK version code.
            expansion_file_type: Type of expansion file (main or patch).

        Returns:
            Expansion file information.
        """
        self._logger.info(
            "Getting expansion file",
            package_name=package_name,
            version_code=version_code,
            type=expansion_file_type,
        )
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            expansion_data = self._execute(
                service.edits()
                .expansionfiles()
                .get(
                    packageName=package_name,
                    editId=edit_id,
                    apkVersionCode=version_code,
                    expansionFileType=expansion_file_type,
                )
            )

            return ExpansionFile(
                version_code=version_code,
                expansion_file_type=expansion_file_type,
                file_size=expansion_data.get("fileSize"),
                references_version=expansion_data.get("referencesVersion"),
            )

        except HttpError as e:
            if e.resp.status == 404:
                # No expansion file
                return ExpansionFile(
                    version_code=version_code,
                    expansion_file_type=expansion_file_type,
                )
            self._logger.exception("Failed to get expansion file", error=str(e))
            raise PlayStoreClientError(f"Failed to get expansion file: {e.reason}") from e
        finally:
            self._delete_edit(package_name, edit_id)

    # =========================================================================
    # Edit Uploads API (apks, bundles, deobfuscation files, expansion files)
    # =========================================================================

    def list_apks(self, package_name: str) -> list[Apk]:
        """List the APKs currently attached to a new edit.

        Args:
            package_name: App package name.

        Returns:
            List of APKs with their version codes and binary hashes.
        """
        self._logger.info("Listing APKs", package_name=package_name)
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            result = self._execute(
                service.edits().apks().list(packageName=package_name, editId=edit_id)
            )
            apks: list[Apk] = []
            for apk_data in result.get("apks", []):
                binary = apk_data.get("binary") or {}
                apks.append(
                    Apk(
                        package_name=package_name,
                        version_code=int(apk_data.get("versionCode", 0)),
                        sha1=binary.get("sha1"),
                        sha256=binary.get("sha256"),
                    )
                )
            return apks
        except HttpError as e:
            self._logger.exception("Failed to list APKs", error=str(e))
            raise PlayStoreClientError(f"Failed to list APKs: {e.reason}") from e
        finally:
            self._delete_edit(package_name, edit_id)

    def list_bundles(self, package_name: str) -> list[Bundle]:
        """List the app bundles currently attached to a new edit.

        Args:
            package_name: App package name.

        Returns:
            List of app bundles with their version codes and hashes.
        """
        self._logger.info("Listing bundles", package_name=package_name)
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            result = self._execute(
                service.edits().bundles().list(packageName=package_name, editId=edit_id)
            )
            return [
                Bundle(
                    package_name=package_name,
                    version_code=int(bundle_data.get("versionCode", 0)),
                    sha1=bundle_data.get("sha1"),
                    sha256=bundle_data.get("sha256"),
                )
                for bundle_data in result.get("bundles", [])
            ]
        except HttpError as e:
            self._logger.exception("Failed to list bundles", error=str(e))
            raise PlayStoreClientError(f"Failed to list bundles: {e.reason}") from e
        finally:
            self._delete_edit(package_name, edit_id)

    def upload_apk(self, package_name: str, apk_path: str) -> Apk:
        """Upload an APK to a new edit and commit it.

        Args:
            package_name: App package name.
            apk_path: Local path to the APK file.

        Returns:
            The uploaded APK with its version code and binary hashes.
        """
        self._logger.info("Uploading APK", package_name=package_name, apk_path=apk_path)
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            media = MediaFileUpload(
                apk_path,
                mimetype="application/vnd.android.package-archive",
                resumable=True,
            )
            data = self._execute(
                service.edits()
                .apks()
                .upload(packageName=package_name, editId=edit_id, media_body=media)
            )
            self._commit_edit(package_name, edit_id)
            binary = data.get("binary") or {}
            return Apk(
                package_name=package_name,
                version_code=int(data.get("versionCode", 0)),
                sha1=binary.get("sha1"),
                sha256=binary.get("sha256"),
            )
        except HttpError as e:
            self._logger.exception("Failed to upload APK", error=str(e))
            self._delete_edit(package_name, edit_id)
            raise PlayStoreClientError(f"Failed to upload APK: {e.reason}") from e
        except Exception as e:
            self._logger.exception("Failed to upload APK", error=str(e))
            self._delete_edit(package_name, edit_id)
            raise PlayStoreClientError(f"Failed to upload APK: {e}") from e

    def upload_bundle(self, package_name: str, bundle_path: str) -> Bundle:
        """Upload an app bundle (.aab) to a new edit and commit it.

        Args:
            package_name: App package name.
            bundle_path: Local path to the app bundle (.aab) file.

        Returns:
            The uploaded app bundle with its version code and hashes.
        """
        self._logger.info("Uploading bundle", package_name=package_name, bundle_path=bundle_path)
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            media = MediaFileUpload(
                bundle_path,
                mimetype="application/octet-stream",
                resumable=True,
            )
            data = self._execute(
                service.edits()
                .bundles()
                .upload(packageName=package_name, editId=edit_id, media_body=media)
            )
            self._commit_edit(package_name, edit_id)
            return Bundle(
                package_name=package_name,
                version_code=int(data.get("versionCode", 0)),
                sha1=data.get("sha1"),
                sha256=data.get("sha256"),
            )
        except HttpError as e:
            self._logger.exception("Failed to upload bundle", error=str(e))
            self._delete_edit(package_name, edit_id)
            raise PlayStoreClientError(f"Failed to upload bundle: {e.reason}") from e
        except Exception as e:
            self._logger.exception("Failed to upload bundle", error=str(e))
            self._delete_edit(package_name, edit_id)
            raise PlayStoreClientError(f"Failed to upload bundle: {e}") from e

    def upload_deobfuscation_file(
        self,
        package_name: str,
        version_code: int,
        file_path: str,
        deobfuscation_file_type: str = "proguard",
    ) -> DeobfuscationFile:
        """Upload a deobfuscation (mapping/symbol) file for an APK version.

        Args:
            package_name: App package name.
            version_code: APK version code the file applies to.
            file_path: Local path to the deobfuscation file.
            deobfuscation_file_type: Type of file (proguard or nativeCode).

        Returns:
            The uploaded deobfuscation file configuration.
        """
        self._logger.info(
            "Uploading deobfuscation file",
            package_name=package_name,
            version_code=version_code,
            type=deobfuscation_file_type,
        )
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            media = MediaFileUpload(file_path, mimetype="application/octet-stream", resumable=True)
            data = self._execute(
                service.edits()
                .deobfuscationfiles()
                .upload(
                    packageName=package_name,
                    editId=edit_id,
                    apkVersionCode=version_code,
                    deobfuscationFileType=deobfuscation_file_type,
                    media_body=media,
                )
            )
            self._commit_edit(package_name, edit_id)
            deobfuscation_file = data.get("deobfuscationFile") or {}
            return DeobfuscationFile(
                package_name=package_name,
                version_code=version_code,
                symbol_type=deobfuscation_file.get("symbolType"),
            )
        except HttpError as e:
            self._logger.exception("Failed to upload deobfuscation file", error=str(e))
            self._delete_edit(package_name, edit_id)
            raise PlayStoreClientError(f"Failed to upload deobfuscation file: {e.reason}") from e
        except Exception as e:
            self._logger.exception("Failed to upload deobfuscation file", error=str(e))
            self._delete_edit(package_name, edit_id)
            raise PlayStoreClientError(f"Failed to upload deobfuscation file: {e}") from e

    def upload_expansion_file(
        self,
        package_name: str,
        version_code: int,
        file_path: str,
        expansion_file_type: str = "main",
    ) -> ExpansionFile:
        """Upload an APK expansion file for an APK version.

        Args:
            package_name: App package name.
            version_code: APK version code the file applies to.
            file_path: Local path to the expansion file.
            expansion_file_type: Type of expansion file (main or patch).

        Returns:
            The uploaded expansion file information.
        """
        self._logger.info(
            "Uploading expansion file",
            package_name=package_name,
            version_code=version_code,
            type=expansion_file_type,
        )
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            media = MediaFileUpload(file_path, mimetype="application/octet-stream", resumable=True)
            data = self._execute(
                service.edits()
                .expansionfiles()
                .upload(
                    packageName=package_name,
                    editId=edit_id,
                    apkVersionCode=version_code,
                    expansionFileType=expansion_file_type,
                    media_body=media,
                )
            )
            self._commit_edit(package_name, edit_id)
            expansion_file = data.get("expansionFile") or {}
            return ExpansionFile(
                version_code=version_code,
                expansion_file_type=expansion_file_type,
                file_size=expansion_file.get("fileSize"),
                references_version=expansion_file.get("referencesVersion"),
            )
        except HttpError as e:
            self._logger.exception("Failed to upload expansion file", error=str(e))
            self._delete_edit(package_name, edit_id)
            raise PlayStoreClientError(f"Failed to upload expansion file: {e.reason}") from e
        except Exception as e:
            self._logger.exception("Failed to upload expansion file", error=str(e))
            self._delete_edit(package_name, edit_id)
            raise PlayStoreClientError(f"Failed to upload expansion file: {e}") from e

    # =========================================================================
    # Store Listing Images API (edits.images)
    # =========================================================================

    @staticmethod
    def _parse_app_image(
        package_name: str,
        language: str,
        image_type: str,
        data: dict[str, Any],
    ) -> AppImage:
        """Parse an Image API resource into an AppImage model."""
        return AppImage(
            package_name=package_name,
            language=language,
            image_type=image_type,
            image_id=data.get("id"),
            url=data.get("url"),
            sha1=data.get("sha1"),
            sha256=data.get("sha256"),
        )

    def list_images(
        self,
        package_name: str,
        language: str,
        image_type: str,
    ) -> list[AppImage]:
        """List the store-listing images for a language and image type.

        Args:
            package_name: App package name.
            language: Language localization code (BCP-47 tag, e.g. "en-US").
            image_type: Image type (e.g. phoneScreenshots, icon, featureGraphic).

        Returns:
            List of images with their IDs, URLs and hashes.
        """
        self._logger.info(
            "Listing images",
            package_name=package_name,
            language=language,
            image_type=image_type,
        )
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            result = self._execute(
                service.edits()
                .images()
                .list(
                    packageName=package_name,
                    editId=edit_id,
                    language=language,
                    imageType=image_type,
                )
            )
            return [
                self._parse_app_image(package_name, language, image_type, image_data)
                for image_data in result.get("images", [])
            ]
        except HttpError as e:
            self._logger.exception("Failed to list images", error=str(e))
            raise PlayStoreClientError(f"Failed to list images: {e.reason}") from e
        finally:
            self._delete_edit(package_name, edit_id)

    def upload_image(
        self,
        package_name: str,
        language: str,
        image_type: str,
        image_path: str,
    ) -> AppImage:
        """Upload a store-listing image to a new edit and commit it.

        Args:
            package_name: App package name.
            language: Language localization code (BCP-47 tag, e.g. "en-US").
            image_type: Image type (e.g. phoneScreenshots, icon, featureGraphic).
            image_path: Local path to the image file (PNG or JPEG).

        Returns:
            The uploaded image with its ID, URL and hashes.
        """
        self._logger.info(
            "Uploading image",
            package_name=package_name,
            language=language,
            image_type=image_type,
            image_path=image_path,
        )
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            mimetype = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
            media = MediaFileUpload(image_path, mimetype=mimetype, resumable=True)
            data = self._execute(
                service.edits()
                .images()
                .upload(
                    packageName=package_name,
                    editId=edit_id,
                    language=language,
                    imageType=image_type,
                    media_body=media,
                )
            )
            self._commit_edit(package_name, edit_id)
            image = data.get("image") or {}
            return self._parse_app_image(package_name, language, image_type, image)
        except HttpError as e:
            self._logger.exception("Failed to upload image", error=str(e))
            self._delete_edit(package_name, edit_id)
            raise PlayStoreClientError(f"Failed to upload image: {e.reason}") from e
        except Exception as e:
            self._logger.exception("Failed to upload image", error=str(e))
            self._delete_edit(package_name, edit_id)
            raise PlayStoreClientError(f"Failed to upload image: {e}") from e

    def delete_image(
        self,
        package_name: str,
        language: str,
        image_type: str,
        image_id: str,
    ) -> ImageDeleteResult:
        """Delete a single store-listing image by ID and commit the edit.

        Args:
            package_name: App package name.
            language: Language localization code (BCP-47 tag, e.g. "en-US").
            image_type: Image type the image belongs to.
            image_id: Unique identifier of the image to delete.

        Returns:
            Delete result with success status.
        """
        self._logger.info(
            "Deleting image",
            package_name=package_name,
            language=language,
            image_type=image_type,
            image_id=image_id,
        )
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            self._execute(
                service.edits()
                .images()
                .delete(
                    packageName=package_name,
                    editId=edit_id,
                    language=language,
                    imageType=image_type,
                    imageId=image_id,
                )
            )
            self._commit_edit(package_name, edit_id)
            return ImageDeleteResult(
                success=True,
                package_name=package_name,
                language=language,
                image_type=image_type,
                deleted_count=1,
                message=f"Deleted image {image_id}",
            )
        except HttpError as e:
            self._logger.exception("Failed to delete image", error=str(e))
            self._delete_edit(package_name, edit_id)
            raise PlayStoreClientError(f"Failed to delete image: {e.reason}") from e
        except Exception as e:
            self._logger.exception("Failed to delete image", error=str(e))
            self._delete_edit(package_name, edit_id)
            raise PlayStoreClientError(f"Failed to delete image: {e}") from e

    def delete_all_images(
        self,
        package_name: str,
        language: str,
        image_type: str,
    ) -> ImageDeleteResult:
        """Delete all store-listing images for a language and image type.

        Args:
            package_name: App package name.
            language: Language localization code (BCP-47 tag, e.g. "en-US").
            image_type: Image type to clear all images for.

        Returns:
            Delete result with the number of images deleted.
        """
        self._logger.info(
            "Deleting all images",
            package_name=package_name,
            language=language,
            image_type=image_type,
        )
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            result = self._execute(
                service.edits()
                .images()
                .deleteall(
                    packageName=package_name,
                    editId=edit_id,
                    language=language,
                    imageType=image_type,
                )
            )
            self._commit_edit(package_name, edit_id)
            deleted_count = len(result.get("deleted", []))
            return ImageDeleteResult(
                success=True,
                package_name=package_name,
                language=language,
                image_type=image_type,
                deleted_count=deleted_count,
                message=f"Deleted {deleted_count} image(s)",
            )
        except HttpError as e:
            self._logger.exception("Failed to delete all images", error=str(e))
            self._delete_edit(package_name, edit_id)
            raise PlayStoreClientError(f"Failed to delete all images: {e.reason}") from e
        except Exception as e:
            self._logger.exception("Failed to delete all images", error=str(e))
            self._delete_edit(package_name, edit_id)
            raise PlayStoreClientError(f"Failed to delete all images: {e}") from e

    # =========================================================================
    # External Transactions API (alternative billing)
    # =========================================================================

    @staticmethod
    def _parse_external_transaction(
        package_name: str,
        external_transaction_id: str,
        data: dict[str, Any],
    ) -> ExternalTransaction:
        """Parse an ExternalTransaction API resource into an ExternalTransaction model.

        The API's externalTransactionId is the full resource-name suffix; we prefer
        the caller-supplied external_transaction_id for a stable, plain identifier.
        """
        return ExternalTransaction(
            package_name=package_name,
            external_transaction_id=external_transaction_id,
            transaction_state=data.get("transactionState"),
            create_time=data.get("createTime"),
            current_pre_tax_amount=data.get("currentPreTaxAmount"),
            original_pre_tax_amount=data.get("originalPreTaxAmount"),
            test_purchase="testPurchase" in data,
        )

    def get_external_transaction(
        self,
        package_name: str,
        external_transaction_id: str,
    ) -> ExternalTransaction:
        """Get an external (alternative billing) transaction.

        Args:
            package_name: App package name.
            external_transaction_id: External transaction ID.

        Returns:
            The external transaction.
        """
        self._logger.info(
            "Getting external transaction",
            package_name=package_name,
            external_transaction_id=external_transaction_id,
        )
        service = self._get_service()
        name = f"applications/{package_name}/externalTransactions/{external_transaction_id}"

        try:
            data = self._execute(service.externaltransactions().getexternaltransaction(name=name))
            return self._parse_external_transaction(package_name, external_transaction_id, data)

        except HttpError as e:
            self._logger.exception("Failed to get external transaction", error=str(e))
            raise PlayStoreClientError(f"Failed to get external transaction: {e.reason}") from e

    def create_external_transaction(
        self,
        package_name: str,
        external_transaction_id: str,
        transaction: dict[str, Any],
    ) -> ExternalTransaction:
        """Create an external (alternative billing) transaction.

        Args:
            package_name: App package name.
            external_transaction_id: External transaction ID to assign.
            transaction: ExternalTransaction resource body.

        Returns:
            The created external transaction.
        """
        self._logger.info(
            "Creating external transaction",
            package_name=package_name,
            external_transaction_id=external_transaction_id,
        )
        service = self._get_service()
        parent = f"applications/{package_name}"

        try:
            data = self._execute(
                service.externaltransactions().createexternaltransaction(
                    parent=parent,
                    externalTransactionId=external_transaction_id,
                    body=transaction,
                )
            )
            return self._parse_external_transaction(package_name, external_transaction_id, data)

        except HttpError as e:
            self._logger.exception("Failed to create external transaction", error=str(e))
            raise PlayStoreClientError(f"Failed to create external transaction: {e.reason}") from e

    def refund_external_transaction(
        self,
        package_name: str,
        external_transaction_id: str,
        refund: dict[str, Any],
    ) -> ExternalTransaction:
        """Refund an external (alternative billing) transaction.

        Args:
            package_name: App package name.
            external_transaction_id: External transaction ID to refund.
            refund: RefundExternalTransactionRequest body (e.g. refundTime plus
                fullRefund or partialRefund).

        Returns:
            The refunded external transaction.
        """
        self._logger.info(
            "Refunding external transaction",
            package_name=package_name,
            external_transaction_id=external_transaction_id,
        )
        service = self._get_service()
        name = f"applications/{package_name}/externalTransactions/{external_transaction_id}"

        try:
            data = self._execute(
                service.externaltransactions().refundexternaltransaction(name=name, body=refund)
            )
            return self._parse_external_transaction(package_name, external_transaction_id, data)

        except HttpError as e:
            self._logger.exception("Failed to refund external transaction", error=str(e))
            raise PlayStoreClientError(f"Failed to refund external transaction: {e.reason}") from e

    # =========================================================================
    # Device Tier Configs API
    # =========================================================================

    @staticmethod
    def _parse_device_tier_config(package_name: str, data: dict[str, Any]) -> DeviceTierConfig:
        """Parse a DeviceTierConfig API resource into a DeviceTierConfig model."""
        return DeviceTierConfig(
            package_name=package_name,
            device_tier_config_id=data.get("deviceTierConfigId"),
            device_groups=data.get("deviceGroups", []),
            device_tier_set=data.get("deviceTierSet"),
            user_country_sets=data.get("userCountrySets", []),
        )

    def get_device_tier_config(
        self,
        package_name: str,
        device_tier_config_id: str,
    ) -> DeviceTierConfig:
        """Get a device tier config.

        Args:
            package_name: App package name.
            device_tier_config_id: Device tier config ID.

        Returns:
            The device tier config.
        """
        self._logger.info(
            "Getting device tier config",
            package_name=package_name,
            device_tier_config_id=device_tier_config_id,
        )
        service = self._get_service()

        try:
            data = self._execute(
                service.applications()
                .deviceTierConfigs()
                .get(packageName=package_name, deviceTierConfigId=device_tier_config_id)
            )
            return self._parse_device_tier_config(package_name, data)

        except HttpError as e:
            self._logger.exception("Failed to get device tier config", error=str(e))
            raise PlayStoreClientError(f"Failed to get device tier config: {e.reason}") from e

    def list_device_tier_configs(self, package_name: str) -> list[DeviceTierConfig]:
        """List device tier configs for an app.

        Args:
            package_name: App package name.

        Returns:
            List of device tier configs.
        """
        self._logger.info("Listing device tier configs", package_name=package_name)
        service = self._get_service()

        try:
            configs: list[DeviceTierConfig] = []
            page_token: str | None = None
            while True:
                kwargs: dict[str, Any] = {"packageName": package_name}
                if page_token:
                    kwargs["pageToken"] = page_token
                result = self._execute(service.applications().deviceTierConfigs().list(**kwargs))
                configs.extend(
                    self._parse_device_tier_config(package_name, config_data)
                    for config_data in result.get("deviceTierConfigs", [])
                )
                page_token = result.get("nextPageToken")
                if not page_token:
                    break

            return configs

        except HttpError as e:
            self._logger.exception("Failed to list device tier configs", error=str(e))
            raise PlayStoreClientError(f"Failed to list device tier configs: {e.reason}") from e

    def create_device_tier_config(
        self,
        package_name: str,
        config: dict[str, Any],
        allow_unknown_devices: bool = False,
    ) -> DeviceTierConfig:
        """Create a new device tier config.

        Args:
            package_name: App package name.
            config: DeviceTierConfig resource body (deviceGroups, deviceTierSet,
                userCountrySets).
            allow_unknown_devices: If True, accept device IDs unknown to Play's
                catalog rather than rejecting them.

        Returns:
            The created device tier config.
        """
        self._logger.info("Creating device tier config", package_name=package_name)
        service = self._get_service()

        try:
            data = self._execute(
                service.applications()
                .deviceTierConfigs()
                .create(
                    packageName=package_name,
                    allowUnknownDevices=allow_unknown_devices,
                    body=config,
                )
            )
            return self._parse_device_tier_config(package_name, data)

        except HttpError as e:
            self._logger.exception("Failed to create device tier config", error=str(e))
            raise PlayStoreClientError(f"Failed to create device tier config: {e.reason}") from e

    # =========================================================================
    # Account Access API (users & grants)
    # =========================================================================

    @staticmethod
    def _parse_user(developer_id: str, data: dict[str, Any]) -> User:
        """Parse a User API resource into a User model.

        The email is preferred from the response body; if absent it is derived
        from the resource name suffix (developers/{developerId}/users/{email}).
        """
        email = data.get("email")
        if email is None and (name := data.get("name")):
            email = name.rsplit("/", 1)[-1]
        return User(
            developer_id=developer_id,
            email=email,
            access_state=data.get("accessState"),
            expiration_time=data.get("expirationTime"),
            developer_account_permissions=data.get("developerAccountPermissions", []),
        )

    @staticmethod
    def _parse_grant(developer_id: str, email: str, data: dict[str, Any]) -> Grant:
        """Parse a Grant API resource into a Grant model.

        The package name is preferred from the response body; if absent it is
        derived from the resource name suffix
        (developers/{developerId}/users/{email}/grants/{packageName}).
        """
        package_name = data.get("packageName")
        if package_name is None and (name := data.get("name")):
            package_name = name.rsplit("/", 1)[-1]
        return Grant(
            developer_id=developer_id,
            email=email,
            package_name=package_name,
            app_level_permissions=data.get("appLevelPermissions", []),
        )

    def list_users(self, developer_id: str) -> list[User]:
        """List users with access to a developer account.

        Args:
            developer_id: Developer account ID.

        Returns:
            List of users.
        """
        self._logger.info("Listing users", developer_id=developer_id)
        service = self._get_service()
        parent = f"developers/{developer_id}"

        try:
            users: list[User] = []
            page_token: str | None = None
            while True:
                kwargs: dict[str, Any] = {"parent": parent}
                if page_token:
                    kwargs["pageToken"] = page_token
                result = self._execute(service.users().list(**kwargs))
                users.extend(
                    self._parse_user(developer_id, user_data)
                    for user_data in result.get("users", [])
                )
                page_token = result.get("nextPageToken")
                if not page_token:
                    break

            return users

        except HttpError as e:
            self._logger.exception("Failed to list users", error=str(e))
            raise PlayStoreClientError(f"Failed to list users: {e.reason}") from e

    def create_user(self, developer_id: str, user: dict[str, Any]) -> User:
        """Grant a user access to a developer account.

        Args:
            developer_id: Developer account ID.
            user: User resource body (email, developerAccountPermissions,
                expirationTime, grants).

        Returns:
            The created user.
        """
        self._logger.info("Creating user", developer_id=developer_id)
        service = self._get_service()
        parent = f"developers/{developer_id}"

        try:
            data = self._execute(service.users().create(parent=parent, body=user))
            return self._parse_user(developer_id, data)

        except HttpError as e:
            self._logger.exception("Failed to create user", error=str(e))
            raise PlayStoreClientError(f"Failed to create user: {e.reason}") from e

    def update_user(
        self,
        developer_id: str,
        email: str,
        user: dict[str, Any],
        update_mask: str,
    ) -> User:
        """Update a user's account access.

        Args:
            developer_id: Developer account ID.
            email: Email of the user to update.
            user: User resource body with the fields to update.
            update_mask: Comma-separated list of fields to update (e.g.
                "developerAccountPermissions,expirationTime").

        Returns:
            The updated user.
        """
        self._logger.info("Updating user", developer_id=developer_id, email=email)
        service = self._get_service()
        name = f"developers/{developer_id}/users/{email}"

        try:
            data = self._execute(
                service.users().patch(name=name, updateMask=update_mask, body=user)
            )
            return self._parse_user(developer_id, data)

        except HttpError as e:
            self._logger.exception("Failed to update user", error=str(e))
            raise PlayStoreClientError(f"Failed to update user: {e.reason}") from e

    def delete_user(self, developer_id: str, email: str) -> AccessResult:
        """Remove a user's access to a developer account.

        Args:
            developer_id: Developer account ID.
            email: Email of the user to remove.

        Returns:
            Access result with success status.
        """
        self._logger.info("Deleting user", developer_id=developer_id, email=email)
        service = self._get_service()
        name = f"developers/{developer_id}/users/{email}"

        try:
            self._execute(service.users().delete(name=name))

            return AccessResult(
                success=True,
                message=f"User {email} removed successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to delete user", error=str(e))
            raise PlayStoreClientError(f"Failed to delete user: {e.reason}") from e

    def create_grant(self, developer_id: str, email: str, grant: dict[str, Any]) -> Grant:
        """Grant a user app-level access.

        Args:
            developer_id: Developer account ID.
            email: Email of the user to grant access to.
            grant: Grant resource body (packageName, appLevelPermissions).

        Returns:
            The created grant.
        """
        self._logger.info("Creating grant", developer_id=developer_id, email=email)
        service = self._get_service()
        parent = f"developers/{developer_id}/users/{email}"

        try:
            data = self._execute(service.grants().create(parent=parent, body=grant))
            return self._parse_grant(developer_id, email, data)

        except HttpError as e:
            self._logger.exception("Failed to create grant", error=str(e))
            raise PlayStoreClientError(f"Failed to create grant: {e.reason}") from e

    def update_grant(
        self,
        developer_id: str,
        email: str,
        package_name: str,
        grant: dict[str, Any],
        update_mask: str,
    ) -> Grant:
        """Update a user's app-level access.

        Args:
            developer_id: Developer account ID.
            email: Email of the user the grant belongs to.
            package_name: App package name the grant applies to.
            grant: Grant resource body with the fields to update.
            update_mask: Comma-separated list of fields to update (e.g.
                "appLevelPermissions").

        Returns:
            The updated grant.
        """
        self._logger.info(
            "Updating grant",
            developer_id=developer_id,
            email=email,
            package_name=package_name,
        )
        service = self._get_service()
        name = f"developers/{developer_id}/users/{email}/grants/{package_name}"

        try:
            data = self._execute(
                service.grants().patch(name=name, updateMask=update_mask, body=grant)
            )
            return self._parse_grant(developer_id, email, data)

        except HttpError as e:
            self._logger.exception("Failed to update grant", error=str(e))
            raise PlayStoreClientError(f"Failed to update grant: {e.reason}") from e

    def delete_grant(self, developer_id: str, email: str, package_name: str) -> AccessResult:
        """Remove a user's app-level access.

        Args:
            developer_id: Developer account ID.
            email: Email of the user the grant belongs to.
            package_name: App package name the grant applies to.

        Returns:
            Access result with success status.
        """
        self._logger.info(
            "Deleting grant",
            developer_id=developer_id,
            email=email,
            package_name=package_name,
        )
        service = self._get_service()
        name = f"developers/{developer_id}/users/{email}/grants/{package_name}"

        try:
            self._execute(service.grants().delete(name=name))

            return AccessResult(
                success=True,
                message=f"Grant for {package_name} removed successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to delete grant", error=str(e))
            raise PlayStoreClientError(f"Failed to delete grant: {e.reason}") from e

    # =========================================================================
    # Data Safety API
    # =========================================================================

    def set_data_safety(
        self,
        package_name: str,
        safety_labels: dict[str, Any],
    ) -> DataSafetyResult:
        """Write the data safety labels declaration of an app.

        Args:
            package_name: App package name.
            safety_labels: SafetyLabelsUpdateRequest resource body. Contains a
                ``safetyLabels`` string with the contents of the Data Safety CSV.

        Returns:
            The result of the update.
        """
        self._logger.info("Setting data safety labels", package_name=package_name)
        service = self._get_service()

        try:
            self._execute(
                service.applications().dataSafety(
                    packageName=package_name,
                    body=safety_labels,
                )
            )
            return DataSafetyResult(
                success=True,
                package_name=package_name,
                message="Data safety labels updated",
            )

        except HttpError as e:
            self._logger.exception("Failed to update data safety labels", error=str(e))
            raise PlayStoreClientError(f"Failed to update data safety labels: {e.reason}") from e

    # =========================================================================
    # App Recovery API
    # =========================================================================

    @staticmethod
    def _parse_app_recovery(package_name: str, data: dict[str, Any]) -> AppRecovery:
        """Parse an AppRecoveryAction API resource into an AppRecovery model."""
        return AppRecovery(
            package_name=package_name,
            app_recovery_id=data.get("recoveryId") or data.get("appRecoveryId"),
            status=data.get("recoveryStatus") or data.get("status"),
            targeting=data.get("targeting"),
            create_time=data.get("createTime"),
        )

    def list_app_recoveries(self, package_name: str, version_code: int) -> list[AppRecovery]:
        """List app recovery actions for an app version.

        Args:
            package_name: App package name.
            version_code: App version code the recovery actions target (required
                by the API).

        Returns:
            List of app recovery actions.
        """
        self._logger.info(
            "Listing app recoveries", package_name=package_name, version_code=version_code
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.apprecovery().list(packageName=package_name, versionCode=version_code)
            )

            return [
                self._parse_app_recovery(package_name, recovery_data)
                for recovery_data in result.get("recoveryActions", [])
            ]

        except HttpError as e:
            self._logger.exception("Failed to list app recoveries", error=str(e))
            raise PlayStoreClientError(f"Failed to list app recoveries: {e.reason}") from e

    def create_app_recovery(
        self,
        package_name: str,
        recovery: dict[str, Any],
    ) -> AppRecovery:
        """Create a draft app recovery action.

        Args:
            package_name: App package name.
            recovery: CreateDraftAppRecoveryRequest resource body (e.g.
                ``remoteInAppUpdate`` plus ``targeting``).

        Returns:
            The created app recovery action.
        """
        self._logger.info("Creating app recovery", package_name=package_name)
        service = self._get_service()

        try:
            data = self._execute(
                service.apprecovery().create(packageName=package_name, body=recovery)
            )
            return self._parse_app_recovery(package_name, data)

        except HttpError as e:
            self._logger.exception("Failed to create app recovery", error=str(e))
            raise PlayStoreClientError(f"Failed to create app recovery: {e.reason}") from e

    def deploy_app_recovery(
        self,
        package_name: str,
        app_recovery_id: str,
    ) -> AppRecoveryResult:
        """Deploy an app recovery action to users.

        Args:
            package_name: App package name.
            app_recovery_id: App recovery action ID.

        Returns:
            The result of the deploy action.
        """
        self._logger.info(
            "Deploying app recovery",
            package_name=package_name,
            app_recovery_id=app_recovery_id,
        )
        service = self._get_service()

        try:
            self._execute(
                service.apprecovery().deploy(
                    packageName=package_name,
                    appRecoveryId=app_recovery_id,
                    body={},
                )
            )
            return AppRecoveryResult(
                success=True,
                package_name=package_name,
                app_recovery_id=app_recovery_id,
                message="App recovery deployed",
            )

        except HttpError as e:
            self._logger.exception("Failed to deploy app recovery", error=str(e))
            raise PlayStoreClientError(f"Failed to deploy app recovery: {e.reason}") from e

    def cancel_app_recovery(
        self,
        package_name: str,
        app_recovery_id: str,
    ) -> AppRecoveryResult:
        """Cancel an app recovery action.

        Args:
            package_name: App package name.
            app_recovery_id: App recovery action ID.

        Returns:
            The result of the cancel action.
        """
        self._logger.info(
            "Canceling app recovery",
            package_name=package_name,
            app_recovery_id=app_recovery_id,
        )
        service = self._get_service()

        try:
            self._execute(
                service.apprecovery().cancel(
                    packageName=package_name,
                    appRecoveryId=app_recovery_id,
                    body={},
                )
            )
            return AppRecoveryResult(
                success=True,
                package_name=package_name,
                app_recovery_id=app_recovery_id,
                message="App recovery canceled",
            )

        except HttpError as e:
            self._logger.exception("Failed to cancel app recovery", error=str(e))
            raise PlayStoreClientError(f"Failed to cancel app recovery: {e.reason}") from e

    def add_app_recovery_targeting(
        self,
        package_name: str,
        app_recovery_id: str,
        targeting: dict[str, Any],
    ) -> AppRecoveryResult:
        """Add targeting to an app recovery action.

        Args:
            package_name: App package name.
            app_recovery_id: App recovery action ID.
            targeting: AddTargetingRequest resource body (e.g. a
                ``targetingUpdate`` object).

        Returns:
            The result of the add-targeting action.
        """
        self._logger.info(
            "Adding app recovery targeting",
            package_name=package_name,
            app_recovery_id=app_recovery_id,
        )
        service = self._get_service()

        try:
            self._execute(
                service.apprecovery().addTargeting(
                    packageName=package_name,
                    appRecoveryId=app_recovery_id,
                    body=targeting,
                )
            )
            return AppRecoveryResult(
                success=True,
                package_name=package_name,
                app_recovery_id=app_recovery_id,
                message="App recovery targeting added",
            )

        except HttpError as e:
            self._logger.exception("Failed to add app recovery targeting", error=str(e))
            raise PlayStoreClientError(f"Failed to add app recovery targeting: {e.reason}") from e

    # =========================================================================
    # Generated APKs API
    # =========================================================================

    def list_generated_apks(
        self,
        package_name: str,
        version_code: int,
    ) -> list[GeneratedApksDownload]:
        """List the downloadable APKs generated from an app bundle version.

        Google Play generates split, standalone, universal, asset-pack-slice,
        and recovery APKs from an uploaded app bundle. This flattens the
        per-signing-key response into one item per downloadable APK.

        Args:
            package_name: App package name.
            version_code: Version code of the app bundle.

        Returns:
            List of downloadable generated APKs, each with its download ID and type.
        """
        self._logger.info(
            "Listing generated APKs",
            package_name=package_name,
            version_code=version_code,
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.generatedapks().list(packageName=package_name, versionCode=version_code)
            )

            downloads: list[GeneratedApksDownload] = []
            for entry in result.get("generatedApks", []):
                # Each signing-key entry holds several sub-lists (plus optional
                # unprotected variants) and a single universal APK object; every
                # sub-entry carries a "downloadId". Flatten them all.
                list_fields: list[tuple[str, str]] = [
                    ("generatedSplitApks", "split"),
                    ("unprotectedGeneratedSplitApks", "split"),
                    ("generatedStandaloneApks", "standalone"),
                    ("unprotectedGeneratedStandaloneApks", "standalone"),
                    ("generatedAssetPackSlices", "asset_pack_slice"),
                    ("generatedRecoveryModules", "recovery"),
                ]
                for field_name, apk_type in list_fields:
                    for sub in entry.get(field_name, []):
                        download_id = sub.get("downloadId")
                        if download_id:
                            downloads.append(
                                GeneratedApksDownload(
                                    package_name=package_name,
                                    version_code=version_code,
                                    download_id=download_id,
                                    apk_type=apk_type,
                                )
                            )

                universal = entry.get("generatedUniversalApk") or {}
                universal_download_id = universal.get("downloadId")
                if universal_download_id:
                    downloads.append(
                        GeneratedApksDownload(
                            package_name=package_name,
                            version_code=version_code,
                            download_id=universal_download_id,
                            apk_type="universal",
                        )
                    )

            return downloads

        except HttpError as e:
            self._logger.exception("Failed to list generated APKs", error=str(e))
            raise PlayStoreClientError(f"Failed to list generated APKs: {e.reason}") from e

    def _confine_download_path(self, destination_path: str) -> str:
        """Validate and canonicalize a download destination.

        When ``self._download_dir`` is set, the resolved destination must stay
        within that directory; otherwise a :class:`PlayStoreClientError` is
        raised (path traversal / arbitrary-file overwrite protection). When it
        is unset (the single-user local default), the base is the filesystem
        root, so any absolute path is allowed — but the destination is still
        canonicalized here and the canonical result is what callers write to,
        so user-controlled input never reaches the filesystem unvalidated.

        Returns the realpath-canonicalized, confinement-checked destination.
        """
        base_real = os.path.realpath(self._download_dir) if self._download_dir else os.sep
        dest_real = os.path.realpath(destination_path)
        try:
            within = os.path.commonpath([base_real, dest_real]) == base_real
        except ValueError:
            # Different drives / mixed path kinds — treat as outside.
            within = False
        if not within:
            self._logger.warning(
                "Blocked download outside PLAY_STORE_MCP_DOWNLOAD_DIR",
                destination=destination_path,
                allowed_dir=base_real,
            )
            raise PlayStoreClientError(
                f"destination_path must be within PLAY_STORE_MCP_DOWNLOAD_DIR ({base_real})"
            )
        return dest_real

    def _download_to_file(self, request: Any, destination_path: str) -> None:
        """Stream a media download request to ``destination_path`` atomically.

        The destination is first confined via :meth:`_confine_download_path`, so
        both the temporary ``.part`` file and the final file are written only to
        a validated location (never straight from user-controlled input).

        Writes to a temporary file in the same directory and renames it onto the
        destination only after the download completes successfully, so a failed
        or unauthorized download never truncates an existing file or leaves a
        partial one in its place.

        Each ``next_chunk()`` is guarded by ``_http_lock`` (per chunk, not for
        the whole download) so a download shares the non-thread-safe httplib2
        transport safely with concurrent calls on the shared client, without
        serializing an entire multi-hundred-MB download under one held lock.
        """
        safe_path = self._confine_download_path(destination_path)
        dest = Path(safe_path)
        tmp_fd, tmp_name = tempfile.mkstemp(
            dir=str(dest.parent), prefix=f".{dest.name}.", suffix=".part"
        )
        succeeded = False
        try:
            with os.fdopen(tmp_fd, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    with self._http_lock:
                        _status, done = downloader.next_chunk()
            Path(tmp_name).replace(safe_path)
            succeeded = True
        finally:
            if not succeeded:
                with contextlib.suppress(OSError):
                    Path(tmp_name).unlink()

    def download_generated_apk(
        self,
        package_name: str,
        version_code: int,
        download_id: str,
        destination_path: str,
    ) -> DownloadResult:
        """Download a single generated APK to a local file.

        Args:
            package_name: App package name.
            version_code: Version code of the app bundle.
            download_id: Download ID identifying the generated APK (from
                :meth:`list_generated_apks`).
            destination_path: Local path to stream the APK bytes to.

        Returns:
            Download result with success status and destination path.
        """
        self._logger.info(
            "Downloading generated APK",
            package_name=package_name,
            version_code=version_code,
            download_id=download_id,
            destination_path=destination_path,
        )
        service = self._get_service()

        try:
            request = service.generatedapks().download(
                packageName=package_name,
                versionCode=version_code,
                downloadId=download_id,
                alt="media",
            )

            self._download_to_file(request, destination_path)

            return DownloadResult(
                success=True,
                destination_path=destination_path,
                message=f"Downloaded generated APK to {destination_path}",
            )

        except HttpError as e:
            self._logger.exception("Failed to download generated APK", error=str(e))
            raise PlayStoreClientError(f"Failed to download generated APK: {e.reason}") from e
        except OSError as e:
            self._logger.exception("Failed to write generated APK", error=str(e))
            raise PlayStoreClientError(
                f"Failed to write generated APK to {destination_path}: {e}"
            ) from e

    # =========================================================================
    # System APK Variants API
    # =========================================================================

    @staticmethod
    def _parse_system_apk_variant(
        package_name: str,
        version_code: int,
        data: dict[str, Any],
    ) -> SystemApkVariant:
        """Parse a Variant API resource into a SystemApkVariant model."""
        return SystemApkVariant(
            package_name=package_name,
            version_code=version_code,
            variant_id=data.get("variantId"),
            device_spec=data.get("deviceSpec"),
            options=data.get("options"),
        )

    def get_system_apk_variant(
        self,
        package_name: str,
        version_code: int,
        variant_id: int,
    ) -> SystemApkVariant:
        """Get a previously created system APK variant.

        Args:
            package_name: App package name.
            version_code: Version code of the app bundle.
            variant_id: ID of the system APK variant.

        Returns:
            The system APK variant.
        """
        self._logger.info(
            "Getting system APK variant",
            package_name=package_name,
            version_code=version_code,
            variant_id=variant_id,
        )
        service = self._get_service()

        try:
            data = self._execute(
                service.systemapks()
                .variants()
                .get(
                    packageName=package_name,
                    versionCode=version_code,
                    variantId=variant_id,
                )
            )
            return self._parse_system_apk_variant(package_name, version_code, data)

        except HttpError as e:
            self._logger.exception("Failed to get system APK variant", error=str(e))
            raise PlayStoreClientError(f"Failed to get system APK variant: {e.reason}") from e

    def list_system_apk_variants(
        self,
        package_name: str,
        version_code: int,
    ) -> list[SystemApkVariant]:
        """List previously created system APK variants for an app bundle version.

        Args:
            package_name: App package name.
            version_code: Version code of the app bundle.

        Returns:
            List of system APK variants.
        """
        self._logger.info(
            "Listing system APK variants",
            package_name=package_name,
            version_code=version_code,
        )
        service = self._get_service()

        try:
            result = self._execute(
                service.systemapks()
                .variants()
                .list(packageName=package_name, versionCode=version_code)
            )

            return [
                self._parse_system_apk_variant(package_name, version_code, variant_data)
                for variant_data in result.get("variants", [])
            ]

        except HttpError as e:
            self._logger.exception("Failed to list system APK variants", error=str(e))
            raise PlayStoreClientError(f"Failed to list system APK variants: {e.reason}") from e

    def create_system_apk_variant(
        self,
        package_name: str,
        version_code: int,
        variant: dict[str, Any],
    ) -> SystemApkVariant:
        """Create a system APK variant from an uploaded app bundle.

        Args:
            package_name: App package name.
            version_code: Version code of the app bundle.
            variant: Variant resource body (e.g. ``deviceSpec`` and ``options``).

        Returns:
            The created system APK variant.
        """
        self._logger.info(
            "Creating system APK variant",
            package_name=package_name,
            version_code=version_code,
        )
        service = self._get_service()

        try:
            data = self._execute(
                service.systemapks()
                .variants()
                .create(
                    packageName=package_name,
                    versionCode=version_code,
                    body=variant,
                )
            )
            return self._parse_system_apk_variant(package_name, version_code, data)

        except HttpError as e:
            self._logger.exception("Failed to create system APK variant", error=str(e))
            raise PlayStoreClientError(f"Failed to create system APK variant: {e.reason}") from e

    def download_system_apk_variant(
        self,
        package_name: str,
        version_code: int,
        variant_id: int,
        destination_path: str,
    ) -> DownloadResult:
        """Download a previously created system APK variant to a local file.

        Args:
            package_name: App package name.
            version_code: Version code of the app bundle.
            variant_id: ID of the system APK variant (from
                :meth:`list_system_apk_variants`).
            destination_path: Local path to stream the APK bytes to.

        Returns:
            Download result with success status and destination path.
        """
        self._logger.info(
            "Downloading system APK variant",
            package_name=package_name,
            version_code=version_code,
            variant_id=variant_id,
            destination_path=destination_path,
        )
        service = self._get_service()

        try:
            request = (
                service.systemapks()
                .variants()
                .download(
                    packageName=package_name,
                    versionCode=version_code,
                    variantId=variant_id,
                    alt="media",
                )
            )

            self._download_to_file(request, destination_path)

            return DownloadResult(
                success=True,
                destination_path=destination_path,
                message=f"Downloaded system APK variant to {destination_path}",
            )

        except HttpError as e:
            self._logger.exception("Failed to download system APK variant", error=str(e))
            raise PlayStoreClientError(f"Failed to download system APK variant: {e.reason}") from e
        except OSError as e:
            self._logger.exception("Failed to write system APK variant", error=str(e))
            raise PlayStoreClientError(
                f"Failed to write system APK variant to {destination_path}: {e}"
            ) from e

    # =========================================================================
    # Internal App Sharing API
    # =========================================================================

    @staticmethod
    def _parse_internal_app_sharing_artifact(
        package_name: str,
        data: dict[str, Any],
    ) -> InternalAppSharingArtifact:
        """Parse an InternalAppSharingArtifact API resource into a model."""
        return InternalAppSharingArtifact(
            package_name=package_name,
            download_url=data.get("downloadUrl"),
            certificate_fingerprint=data.get("certificateFingerprint"),
            sha256=data.get("sha256"),
        )

    def upload_internal_app_sharing_apk(
        self,
        package_name: str,
        apk_path: str,
    ) -> InternalAppSharingArtifact:
        """Upload an APK to internal app sharing.

        Args:
            package_name: App package name.
            apk_path: Local path to the APK file.

        Returns:
            The uploaded internal app sharing artifact.
        """
        self._logger.info(
            "Uploading internal app sharing APK",
            package_name=package_name,
            apk_path=apk_path,
        )
        service = self._get_service()

        try:
            media = MediaFileUpload(
                apk_path,
                mimetype="application/vnd.android.package-archive",
                resumable=True,
            )
            data = self._execute(
                service.internalappsharingartifacts().uploadapk(
                    packageName=package_name, media_body=media
                )
            )
            return self._parse_internal_app_sharing_artifact(package_name, data)

        except HttpError as e:
            self._logger.exception("Failed to upload internal app sharing APK", error=str(e))
            raise PlayStoreClientError(
                f"Failed to upload internal app sharing APK: {e.reason}"
            ) from e

    def upload_internal_app_sharing_bundle(
        self,
        package_name: str,
        bundle_path: str,
    ) -> InternalAppSharingArtifact:
        """Upload an app bundle (.aab) to internal app sharing.

        Args:
            package_name: App package name.
            bundle_path: Local path to the app bundle (.aab) file.

        Returns:
            The uploaded internal app sharing artifact.
        """
        self._logger.info(
            "Uploading internal app sharing bundle",
            package_name=package_name,
            bundle_path=bundle_path,
        )
        service = self._get_service()

        try:
            media = MediaFileUpload(
                bundle_path,
                mimetype="application/octet-stream",
                resumable=True,
            )
            data = self._execute(
                service.internalappsharingartifacts().uploadbundle(
                    packageName=package_name, media_body=media
                )
            )
            return self._parse_internal_app_sharing_artifact(package_name, data)

        except HttpError as e:
            self._logger.exception("Failed to upload internal app sharing bundle", error=str(e))
            raise PlayStoreClientError(
                f"Failed to upload internal app sharing bundle: {e.reason}"
            ) from e
