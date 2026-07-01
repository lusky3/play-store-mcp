"""Google Play Developer API client."""

from __future__ import annotations

import functools
import json
import os
import random
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from play_store_mcp.models import (
    AppDetails,
    BatchDeploymentResult,
    DeploymentResult,
    ExpansionFile,
    InAppProduct,
    InAppProductActionResult,
    Listing,
    ListingUpdateResult,
    OneTimeProduct,
    OneTimeProductActionResult,
    OneTimeProductOffer,
    Order,
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
    TesterInfo,
    TrackInfo,
    ValidationResult,
    VitalsMetric,
    VitalsOverview,
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


def retry_with_backoff(func):  # type: ignore[no-untyped-def]
    """Decorator to retry API calls with exponential backoff.

    Retries on transient errors (500, 503) and rate limit errors (429).
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        retries = 0
        backoff = INITIAL_BACKOFF

        while retries < MAX_RETRIES:
            try:
                return func(*args, **kwargs)
            except HttpError as e:
                # Retry on server errors and rate limits
                if e.resp.status in (429, 500, 503):
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
                else:
                    raise
            except Exception:
                raise

    return wrapper


class PlayStoreClient:
    """Client for interacting with Google Play Developer API."""

    def __init__(
        self,
        credentials_path: str | None = None,
        credentials_json: str | dict[str, Any] | None = None,
        application_name: str = "Play Store MCP Server",
    ) -> None:
        """Initialize the Play Store client.

        Args:
            credentials_path: Path to service account JSON key.
                             Defaults to GOOGLE_APPLICATION_CREDENTIALS env var.
            credentials_json: JSON string or dictionary with service account credentials.
                             Defaults to GOOGLE_PLAY_STORE_CREDENTIALS env var.
            application_name: Application name for API requests.
        """
        self._credentials_path = credentials_path or os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )
        self._credentials_json = credentials_json or os.environ.get("GOOGLE_PLAY_STORE_CREDENTIALS")
        self._application_name = application_name
        self._service: AndroidPublisherResource | None = None
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

    def _create_edit(self, package_name: str) -> str:
        """Create a new edit for the package.

        Args:
            package_name: App package name.

        Returns:
            Edit ID.
        """
        service = self._get_service()
        result = service.edits().insert(packageName=package_name, body={}).execute()
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
        service.edits().commit(packageName=package_name, editId=edit_id).execute()
        self._logger.debug("Committed edit", package_name=package_name, edit_id=edit_id)

    def _delete_edit(self, package_name: str, edit_id: str) -> None:
        """Delete an edit without committing.

        Args:
            package_name: App package name.
            edit_id: Edit ID to delete.
        """
        service = self._get_service()
        try:
            service.edits().delete(packageName=package_name, editId=edit_id).execute()
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
            result = (
                service.edits().tracks().list(packageName=package_name, editId=edit_id).execute()
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
            is_bundle = file_path.endswith(".aab")
            content_type = (
                "application/octet-stream"
                if is_bundle
                else "application/vnd.android.package-archive"
            )

            media = MediaFileUpload(file_path, mimetype=content_type, resumable=True)

            if is_bundle:
                upload_response = (
                    service.edits()
                    .bundles()
                    .upload(packageName=package_name, editId=edit_id, media_body=media)
                    .execute()
                )
            else:
                upload_response = (
                    service.edits()
                    .apks()
                    .upload(packageName=package_name, editId=edit_id, media_body=media)
                    .execute()
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
            service.edits().tracks().update(
                packageName=package_name,
                editId=edit_id,
                track=track,
                body=track_body,
            ).execute()

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
            source_track = (
                service.edits()
                .tracks()
                .get(packageName=package_name, editId=edit_id, track=from_track)
                .execute()
            )

            # Find the release with matching version code
            source_release = None
            for release in source_track.get("releases", []):
                version_codes = [int(vc) for vc in release.get("versionCodes", [])]
                if version_code in version_codes:
                    source_release = release
                    break

            if not source_release:
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
            service.edits().tracks().update(
                packageName=package_name,
                editId=edit_id,
                track=to_track,
                body={"releases": [new_release]},
            ).execute()

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
            current_track = (
                service.edits()
                .tracks()
                .get(packageName=package_name, editId=edit_id, track=track)
                .execute()
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
                return DeploymentResult(
                    success=False,
                    package_name=package_name,
                    track=track,
                    version_code=version_code,
                    message=f"Version {version_code} not found in {track}",
                    error="VersionNotFound",
                )

            # Update track
            service.edits().tracks().update(
                packageName=package_name,
                editId=edit_id,
                track=track,
                body={"releases": releases},
            ).execute()

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
            current_track = (
                service.edits()
                .tracks()
                .get(packageName=package_name, editId=edit_id, track=track)
                .execute()
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
                return DeploymentResult(
                    success=False,
                    package_name=package_name,
                    track=track,
                    version_code=version_code,
                    message=f"Version {version_code} not found in {track}",
                    error="VersionNotFound",
                )

            # Update track
            service.edits().tracks().update(
                packageName=package_name,
                editId=edit_id,
                track=track,
                body={"releases": releases},
            ).execute()

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
            details = (
                service.edits().details().get(packageName=package_name, editId=edit_id).execute()
            )

            # Get listings for the specified language
            try:
                listing = (
                    service.edits()
                    .listings()
                    .get(packageName=package_name, editId=edit_id, language=language)
                    .execute()
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
            kwargs: dict[str, Any] = {"packageName": package_name, "maxResults": max_results}
            if translation_language:
                kwargs["translationLanguage"] = translation_language
            request = service.reviews().list(**kwargs)

            result = request.execute()

            reviews: list[Review] = []
            for review_data in result.get("reviews", []):
                review = _parse_review(review_data)
                if review is not None:
                    reviews.append(review)

            return reviews

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
            result = service.reviews().get(**kwargs).execute()

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
            service.reviews().reply(
                packageName=package_name,
                reviewId=review_id,
                body={"replyText": reply_text},
            ).execute()

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
            result = service.monetization().subscriptions().list(packageName=package_name).execute()

            subscriptions = [
                SubscriptionProduct(
                    product_id=sub_data.get("productId", ""),
                    package_name=package_name,
                    base_plans=sub_data.get("basePlans", []),
                )
                for sub_data in result.get("subscriptions", [])
            ]

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
            result = (
                service.purchases()
                .subscriptionsv2()
                .get(packageName=package_name, token=token)
                .execute()
            )

            line_items = result.get("lineItems", [])
            auto_renewing = any(
                item.get("productId") == subscription_id
                and item.get("autoRenewingPlan", {}).get("autoRenewEnabled", False)
                for item in line_items
            )

            return SubscriptionPurchase(
                package_name=package_name,
                subscription_id=subscription_id,
                purchase_token=token,
                order_id=result.get("latestOrderId"),
                auto_renewing=auto_renewing,
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
            result = (
                service.purchases()
                .voidedpurchases()
                .list(packageName=package_name, maxResults=max_results)
                .execute()
            )

            voided = [
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
            ]

            return voided

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
            result = (
                service.purchases()
                .products()
                .get(packageName=package_name, productId=product_id, token=token)
                .execute()
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
            service.purchases().products().acknowledge(
                packageName=package_name,
                productId=product_id,
                token=token,
                body=body,
            ).execute()

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
            service.purchases().products().consume(
                packageName=package_name,
                productId=product_id,
                token=token,
            ).execute()

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
            service.orders().refund(
                packageName=package_name, orderId=order_id, revoke=revoke
            ).execute()

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
            service.purchases().subscriptionsv2().cancel(
                packageName=package_name,
                token=token,
                body={"cancellationContext": {"cancellationType": cancellation_type}},
            ).execute()

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
            result = (
                service.purchases()
                .subscriptionsv2()
                .defer(
                    packageName=package_name,
                    token=token,
                    body={"deferralContext": {"deferDuration": defer_duration, "etag": etag}},
                )
                .execute()
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
        service = self._get_service()

        try:
            service.purchases().subscriptionsv2().revoke(
                packageName=package_name,
                token=token,
                body={"revocationContext": _REVOCATION_CONTEXTS[refund_type]},
            ).execute()

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
            result = (
                service.purchases()
                .productsv2()
                .getproductpurchasev2(packageName=package_name, token=token)
                .execute()
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
    # Vitals API
    # =========================================================================

    def get_vitals_overview(self, package_name: str) -> VitalsOverview:
        """Get Android Vitals overview.

        Placeholder implementation. The Vitals API is part of the Play Developer
        Reporting API, which is a separate API requiring its own setup and credentials.

        Args:
            package_name: App package name.

        Returns:
            Vitals overview placeholder.
        """
        # TODO: Implement with Play Developer Reporting API
        self._logger.info("Getting vitals overview", package_name=package_name)

        # The Vitals API is part of the Play Developer Reporting API
        # which requires separate authentication/setup
        # For now, return a placeholder that indicates where data would come from

        return VitalsOverview(
            package_name=package_name,
            freshness_info="Vitals data requires Play Developer Reporting API access",
        )

    def get_vitals_metrics(
        self,
        package_name: str,
        metric_type: str = "crashRate",
    ) -> list[VitalsMetric]:
        """Get specific Android Vitals metrics.

        Placeholder implementation. The Vitals API is part of the Play Developer
        Reporting API, which is a separate API requiring its own setup and credentials.

        Args:
            package_name: App package name.
            metric_type: Type of metric (crashRate, anrRate, etc.).

        Returns:
            List of vitals metrics placeholders.
        """
        # TODO: Implement with Play Developer Reporting API
        self._logger.info(
            "Getting vitals metrics",
            package_name=package_name,
            metric_type=metric_type,
        )

        # The Play Developer Reporting API is separate and requires additional setup
        # Return placeholder indicating this limitation
        return [
            VitalsMetric(
                metric_type=metric_type,
                value=None,
                benchmark=None,
                is_below_threshold=None,
                dimension="api_level",
                dimension_value="Requires Play Developer Reporting API access",
            )
        ]

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
            result = service.inappproducts().list(packageName=package_name).execute()

            return [
                self._parse_in_app_product(package_name, product_data)
                for product_data in result.get("inappproduct", [])
            ]

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
            product_data = service.inappproducts().get(packageName=package_name, sku=sku).execute()
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
            result = (
                service.inappproducts().insert(packageName=package_name, body=product).execute()
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
            result = (
                service.inappproducts()
                .update(
                    packageName=package_name,
                    sku=sku,
                    autoConvertMissingPrices=auto_convert_missing_prices,
                    body=product,
                )
                .execute()
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
            result = (
                service.inappproducts()
                .patch(packageName=package_name, sku=sku, body=product)
                .execute()
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
            service.inappproducts().delete(packageName=package_name, sku=sku).execute()

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
            result = service.inappproducts().batchGet(packageName=package_name, sku=skus).execute()

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
            service.inappproducts().batchDelete(
                packageName=package_name,
                body={"requests": [{"packageName": package_name, "sku": s} for s in skus]},
            ).execute()

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
            data = (
                service.monetization()
                .onetimeproducts()
                .get(packageName=package_name, productId=product_id)
                .execute()
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
            result = (
                service.monetization().onetimeproducts().list(packageName=package_name).execute()
            )

            return [
                self._parse_one_time_product(package_name, data)
                for data in result.get("oneTimeProducts", [])
            ]

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
            result = (
                service.monetization()
                .onetimeproducts()
                .batchGet(packageName=package_name, productIds=product_ids)
                .execute()
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
            result = (
                service.monetization()
                .onetimeproducts()
                .patch(
                    packageName=package_name,
                    productId=product_id,
                    updateMask=update_mask,
                    regionsVersion_version=regions_version,
                    body=product,
                )
                .execute()
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
            service.monetization().onetimeproducts().delete(
                packageName=package_name, productId=product_id
            ).execute()

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
            result = (
                service.monetization()
                .onetimeproducts()
                .batchUpdate(packageName=package_name, body={"requests": requests})
                .execute()
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
            service.monetization().onetimeproducts().batchDelete(
                packageName=package_name, body={"requests": requests}
            ).execute()

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
            service.monetization().onetimeproducts().purchaseOptions().batchDelete(
                packageName=package_name,
                productId=product_id,
                body={"requests": requests},
            ).execute()

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
            result = (
                service.monetization()
                .onetimeproducts()
                .purchaseOptions()
                .batchUpdateStates(
                    packageName=package_name,
                    productId=product_id,
                    body={"requests": requests},
                )
                .execute()
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
            result = (
                service.monetization()
                .onetimeproducts()
                .purchaseOptions()
                .offers()
                .list(
                    packageName=package_name,
                    productId=product_id,
                    purchaseOptionId=purchase_option_id,
                )
                .execute()
            )
            return [
                self._parse_one_time_product_offer(offer)
                for offer in result.get("oneTimeProductOffers", [])
            ]

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
            result = (
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
                .execute()
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
            result = (
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
                .execute()
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
            result = (
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
                .execute()
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
            result = (
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
                .execute()
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
            result = (
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
                .execute()
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
            result = (
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
                .execute()
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
            service.monetization().onetimeproducts().purchaseOptions().offers().batchDelete(
                packageName=package_name,
                productId=product_id,
                purchaseOptionId=purchase_option_id,
                body={"requests": requests},
            ).execute()

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
            data = (
                service.monetization()
                .subscriptions()
                .get(packageName=package_name, productId=product_id)
                .execute()
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
            result = (
                service.monetization()
                .subscriptions()
                .create(
                    packageName=package_name,
                    productId=product_id,
                    regionsVersion_version=regions_version,
                    body=subscription,
                )
                .execute()
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
            result = (
                service.monetization()
                .subscriptions()
                .patch(
                    packageName=package_name,
                    productId=product_id,
                    updateMask=update_mask,
                    regionsVersion_version=regions_version,
                    body=subscription,
                )
                .execute()
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
            service.monetization().subscriptions().delete(
                packageName=package_name, productId=product_id
            ).execute()

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
            result = (
                service.monetization()
                .subscriptions()
                .batchGet(packageName=package_name, productIds=product_ids)
                .execute()
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
            result = (
                service.monetization()
                .subscriptions()
                .batchUpdate(packageName=package_name, body={"requests": requests})
                .execute()
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
            result = (
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
                .execute()
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
            result = (
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
                .execute()
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
            service.monetization().subscriptions().basePlans().delete(
                packageName=package_name,
                productId=product_id,
                basePlanId=base_plan_id,
            ).execute()

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
            result: dict[str, Any] = (
                service.monetization()
                .subscriptions()
                .basePlans()
                .migratePrices(
                    packageName=package_name,
                    productId=product_id,
                    basePlanId=base_plan_id,
                    body=request,
                )
                .execute()
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
            result: dict[str, Any] = (
                service.monetization()
                .subscriptions()
                .basePlans()
                .batchMigratePrices(
                    packageName=package_name,
                    productId=product_id,
                    body={"requests": requests},
                )
                .execute()
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
            result = (
                service.monetization()
                .subscriptions()
                .basePlans()
                .batchUpdateStates(
                    packageName=package_name,
                    productId=product_id,
                    body={"requests": requests},
                )
                .execute()
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
            data = (
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
                .execute()
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
            result = (
                service.monetization()
                .subscriptions()
                .basePlans()
                .offers()
                .list(
                    packageName=package_name,
                    productId=product_id,
                    basePlanId=base_plan_id,
                )
                .execute()
            )
            return [
                self._parse_subscription_offer(offer)
                for offer in result.get("subscriptionOffers", [])
            ]

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
            result = (
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
                .execute()
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
            result = (
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
                .execute()
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
            result = (
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
                .execute()
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
            result = (
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
                .execute()
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
            service.monetization().subscriptions().basePlans().offers().delete(
                packageName=package_name,
                productId=product_id,
                basePlanId=base_plan_id,
                offerId=offer_id,
            ).execute()

            return SubscriptionCatalogResult(
                success=True,
                package_name=package_name,
                product_id=offer_id,
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
            result = (
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
                .execute()
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
            result = (
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
                .execute()
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
            result = (
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
                .execute()
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
            listing_data = (
                service.edits()
                .listings()
                .get(packageName=package_name, editId=edit_id, language=language)
                .execute()
            )

            return Listing(
                language=language,
                title=listing_data.get("title"),
                full_description=listing_data.get("fullDescription"),
                short_description=listing_data.get("shortDescription"),
                video=listing_data.get("video"),
            )
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
                current_listing = (
                    service.edits()
                    .listings()
                    .get(packageName=package_name, editId=edit_id, language=language)
                    .execute()
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
            service.edits().listings().update(
                packageName=package_name,
                editId=edit_id,
                language=language,
                body=update_body,
            ).execute()

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
            result = (
                service.edits().listings().list(packageName=package_name, editId=edit_id).execute()
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
            testers_data = (
                service.edits()
                .testers()
                .get(packageName=package_name, editId=edit_id, track=track)
                .execute()
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
            service.edits().testers().update(
                packageName=package_name,
                editId=edit_id,
                track=track,
                body={"googleGroups": google_groups},
            ).execute()

            self._commit_edit(package_name, edit_id)

            return {"success": True, "track": track, "google_groups": google_groups}

        except HttpError as e:
            self._logger.exception("Failed to update testers", error=str(e))
            self._delete_edit(package_name, edit_id)
            return {"success": False, "track": track, "error": str(e)}

    # =========================================================================
    # Orders API
    # =========================================================================

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
            order_data = service.orders().get(packageName=package_name, orderId=order_id).execute()

            return Order(
                order_id=order_id,
                package_name=package_name,
                product_id=order_data.get("productId"),
                purchase_state=order_data.get("purchaseState"),
                purchase_token=order_data.get("purchaseToken"),
            )

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
            result = (
                service.orders().batchget(packageName=package_name, orderIds=order_ids).execute()
            )

            return [
                Order(
                    order_id=order_data.get("orderId", ""),
                    package_name=package_name,
                    product_id=order_data.get("productId"),
                    purchase_state=order_data.get("purchaseState"),
                    purchase_token=order_data.get("purchaseToken"),
                )
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
            expansion_data = (
                service.edits()
                .expansionfiles()
                .get(
                    packageName=package_name,
                    editId=edit_id,
                    apkVersionCode=version_code,
                    expansionFileType=expansion_file_type,
                )
                .execute()
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
