"""Google Play Developer API client."""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from play_store_mcp.models import (
    AppDetails,
    AppDetailsInfo,
    AppDetailsUpdateResult,
    AppInfo,
    BatchDeploymentResult,
    BundleInfo,
    AcquisitionFunnelResult,
    AcquisitionFunnelStage,
    ConsoleInstallStats,
    ConsoleStatsResult,
    CountryAvailability,
    DailyStatPoint,
    SearchTermResult,
    SearchTermsStats,
    DeobfuscationFileResult,
    DeploymentResult,
    ExpansionFile,
    GeneratedApkInfo,
    GrantInfo,
    ImageInfo,
    ImageUploadResult,
    InAppProduct,
    Listing,
    ListingUpdateResult,
    Order,
    ProductPurchase,
    RefundResult,
    Release,
    Review,
    ReviewReplyResult,
    SubscriptionProduct,
    SubscriptionPurchase,
    SubscriptionPurchaseV2,
    TesterInfo,
    TrackInfo,
    UserInfo,
    UserOperationResult,
    ValidationError,
    VitalsMetric,
    VitalsOverview,
    VoidedPurchase,
)

if TYPE_CHECKING:
    from googleapiclient._apis.androidpublisher.v3 import AndroidPublisherResource

logger = structlog.get_logger(__name__)

# API scopes required for Play Developer API
SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]

# Scope for Play Developer Reporting API (vitals/crash/ANR data)
REPORTING_SCOPES = ["https://www.googleapis.com/auth/playdeveloperreporting"]

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds
MAX_BACKOFF = 32.0  # seconds


class PlayStoreClientError(Exception):
    """Base exception for Play Store client errors."""


def retry_with_backoff(func):  # type: ignore[no-untyped-def]
    """Decorator to retry API calls with exponential backoff.

    Retries on transient errors (500, 503) and rate limit errors (429).
    """

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
                    sleep_time = backoff * (0.5 + random.random())  # noqa: S311
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

        return func(*args, **kwargs)

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
        self._reporting_service: Any | None = None
        self._logger = logger.bind(component="PlayStoreClient")

    # =========================================================================
    # Validation Helpers
    # =========================================================================

    def validate_package_name(self, package_name: str) -> list[ValidationError]:
        """Validate package name format.

        Args:
            package_name: Package name to validate.

        Returns:
            List of validation errors (empty if valid).
        """
        errors: list[ValidationError] = []

        if not package_name:
            errors.append(
                ValidationError(
                    field="package_name",
                    message="Package name cannot be empty",
                    value=package_name,
                )
            )
            return errors

        # Check format: must contain at least one dot
        if "." not in package_name:
            errors.append(
                ValidationError(
                    field="package_name",
                    message="Package name must contain at least one dot (e.g., com.example.app)",
                    value=package_name,
                )
            )

        # Check for invalid characters
        if not re.match(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", package_name):
            errors.append(
                ValidationError(
                    field="package_name",
                    message="Package name must start with lowercase letter and contain only lowercase letters, numbers, underscores, and dots",
                    value=package_name,
                )
            )

        return errors

    def validate_track(self, track: str) -> list[ValidationError]:
        """Validate track name.

        Args:
            track: Track name to validate.

        Returns:
            List of validation errors (empty if valid).
        """
        errors: list[ValidationError] = []
        valid_tracks = ["internal", "alpha", "beta", "production"]

        if track not in valid_tracks:
            errors.append(
                ValidationError(
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
    ) -> list[ValidationError]:
        """Validate store listing text lengths.

        Args:
            title: App title (max 50 chars).
            short_description: Short description (max 80 chars).
            full_description: Full description (max 4000 chars).

        Returns:
            List of validation errors (empty if valid).
        """
        errors: list[ValidationError] = []

        if title and len(title) > 50:
            errors.append(
                ValidationError(
                    field="title",
                    message="Title must be 50 characters or less",
                    value=f"{len(title)} characters",
                )
            )

        if short_description and len(short_description) > 80:
            errors.append(
                ValidationError(
                    field="short_description",
                    message="Short description must be 80 characters or less",
                    value=f"{len(short_description)} characters",
                )
            )

        if full_description and len(full_description) > 4000:
            errors.append(
                ValidationError(
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
                        pass

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

    def _get_reporting_service(self) -> Any:
        """Get or create the Play Developer Reporting API service instance."""
        if self._reporting_service is not None:
            return self._reporting_service

        self._logger.info("Initializing Play Developer Reporting API client")

        try:
            credentials = None

            if self._credentials_json:
                if isinstance(self._credentials_json, str):
                    if self._credentials_json.strip().startswith("{"):
                        creds_info = json.loads(self._credentials_json)
                        credentials = service_account.Credentials.from_service_account_info(
                            creds_info, scopes=REPORTING_SCOPES
                        )
                    elif Path(self._credentials_json).exists():
                        credentials = service_account.Credentials.from_service_account_file(
                            self._credentials_json, scopes=REPORTING_SCOPES
                        )
                elif isinstance(self._credentials_json, dict):
                    credentials = service_account.Credentials.from_service_account_info(
                        self._credentials_json, scopes=REPORTING_SCOPES
                    )

            if not credentials and self._credentials_path:
                creds_path = Path(self._credentials_path)
                if creds_path.exists():
                    credentials = service_account.Credentials.from_service_account_file(
                        str(creds_path), scopes=REPORTING_SCOPES
                    )

            if not credentials:
                raise PlayStoreClientError(
                    "No valid credentials found for Reporting API. "
                    "Set GOOGLE_PLAY_STORE_CREDENTIALS (JSON or path)."
                )

            self._reporting_service = build(
                "playdeveloperreporting",
                "v1beta1",
                credentials=credentials,
                cache_discovery=False,
            )
            self._logger.info("Reporting API client initialized successfully")
            return self._reporting_service
        except Exception as e:
            if isinstance(e, PlayStoreClientError):
                raise
            self._logger.exception("Failed to initialize Reporting API client", error=str(e))
            raise PlayStoreClientError(f"Failed to initialize Reporting API client: {e}") from e

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
        except HttpError:
            # Edit may have already been committed or expired
            pass

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

    def list_apps(self) -> list[AppInfo]:
        """List all apps in the developer account.

        Note: This attempts to discover apps by checking recent edits.
        The Play Developer API doesn't have a direct "list all apps" endpoint,
        so this may not return all apps in the account.

        Returns:
            List of app info discovered from recent activity.
        """
        self._logger.info("Attempting to discover apps from account activity")

        # The Play Developer API doesn't have a list apps endpoint
        # We can only work with apps we know the package name for
        # Return empty list with informative message
        self._logger.warning(
            "Play Developer API requires package names upfront. "
            "Use get_app_details with known package names instead."
        )
        return []

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
                developer_name=None,
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
        start_index: int = 0,
        translation_language: str | None = None,
    ) -> list[Review]:
        """Get app reviews.

        Args:
            package_name: App package name.
            max_results: Maximum number of reviews to return.
            start_index: Starting index for pagination.
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
            request = service.reviews().list(
                packageName=package_name,
                maxResults=max_results,
                startIndex=start_index,
            )
            if translation_language:
                request = service.reviews().list(
                    packageName=package_name,
                    maxResults=max_results,
                    startIndex=start_index,
                    translationLanguage=translation_language,
                )

            result = request.execute()

            reviews: list[Review] = []
            for review_data in result.get("reviews", []):
                # Get most recent comment
                comments = review_data.get("comments", [])
                user_comment = None
                dev_comment = None

                for comment in comments:
                    if "userComment" in comment:
                        user_comment = comment["userComment"]
                    if "developerComment" in comment:
                        dev_comment = comment["developerComment"]

                if user_comment:
                    reviews.append(
                        Review(
                            review_id=review_data.get("reviewId", ""),
                            author_name=review_data.get("authorName", "Anonymous"),
                            star_rating=user_comment.get("starRating", 0),
                            comment=user_comment.get("text", ""),
                            language=user_comment.get("reviewerLanguage", "en"),
                            device=user_comment.get("device"),
                            android_version=str(user_comment["androidOsVersion"]) if user_comment.get("androidOsVersion") is not None else None,
                            app_version_code=user_comment.get("appVersionCode"),
                            app_version_name=user_comment.get("appVersionName"),
                            developer_reply=dev_comment.get("text") if dev_comment else None,
                        )
                    )

            return reviews

        except HttpError as e:
            self._logger.exception("Failed to fetch reviews", error=str(e))
            raise PlayStoreClientError(f"Failed to fetch reviews: {e.reason}") from e

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

            return SubscriptionPurchase(
                package_name=package_name,
                subscription_id=subscription_id,
                purchase_token=token,
                order_id=result.get("latestOrderId"),
                auto_renewing=result.get("subscriptionState") == "SUBSCRIPTION_STATE_ACTIVE",
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
                )
                for purchase in result.get("voidedPurchases", [])
            ]

            return voided

        except HttpError as e:
            self._logger.exception("Failed to list voided purchases", error=str(e))
            raise PlayStoreClientError(f"Failed to list voided purchases: {e.reason}") from e

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

        Raises:
            PlayStoreClientError: Always - requires separate Play Developer Reporting API
                setup with additional scopes not supported by this MCP.
        """
        raise PlayStoreClientError(
            "get_vitals_overview requires the Play Developer Reporting API "
            "(playdeveloperreporting v1beta1), which is not yet implemented in this MCP. "
            "Use the Google Play Console UI or set up the Reporting API separately."
        )

    def get_vitals_metrics(
        self,
        package_name: str,
        metric_type: str = "crashRate",
    ) -> list[VitalsMetric]:
        """Get specific Android Vitals metrics.

        Raises:
            PlayStoreClientError: Always - requires separate Play Developer Reporting API
                setup with additional scopes not supported by this MCP.
        """
        raise PlayStoreClientError(
            "get_vitals_metrics requires the Play Developer Reporting API "
            "(playdeveloperreporting v1beta1), which is not yet implemented in this MCP. "
            "Use the Google Play Console UI or set up the Reporting API separately."
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
            result = service.inappproducts().list(packageName=package_name).execute()

            products: list[InAppProduct] = []
            for product_data in result.get("inappproduct", []):
                # Get default price if available
                default_price = None
                if "defaultPrice" in product_data:
                    default_price = product_data["defaultPrice"]

                # Get localized listings
                listings = product_data.get("listings", {})
                default_listing = listings.get(product_data.get("defaultLanguage", "en-US"), {})

                products.append(
                    InAppProduct(
                        sku=product_data.get("sku", ""),
                        package_name=package_name,
                        product_type=product_data.get("purchaseType", "managedProduct"),
                        status=product_data.get("status"),
                        default_language=product_data.get("defaultLanguage"),
                        title=default_listing.get("title"),
                        description=default_listing.get("description"),
                        default_price=default_price,
                    )
                )

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
            product_data = service.inappproducts().get(packageName=package_name, sku=sku).execute()

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

        except HttpError as e:
            self._logger.exception("Failed to get in-app product", error=str(e))
            raise PlayStoreClientError(f"Failed to get in-app product: {e.reason}") from e

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

            listings: list[Listing] = []
            raw_listings = result.get("listings", [])
            if isinstance(raw_listings, dict):
                for language, listing_data in raw_listings.items():
                    listings.append(
                        Listing(
                            language=language,
                            title=listing_data.get("title"),
                            full_description=listing_data.get("fullDescription"),
                            short_description=listing_data.get("shortDescription"),
                            video=listing_data.get("video"),
                        )
                    )
            else:
                for listing_data in raw_listings:
                    listings.append(
                        Listing(
                            language=listing_data.get("language", ""),
                            title=listing_data.get("title"),
                            full_description=listing_data.get("fullDescription"),
                            short_description=listing_data.get("shortDescription"),
                            video=listing_data.get("video"),
                        )
                    )

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

            individual_emails: list[str] = testers_data.get("testers", [])
            group_emails: list[str] = testers_data.get("googleGroups", [])
            return TesterInfo(
                track=track,
                tester_emails=individual_emails + group_emails,
            )
        except HttpError as e:
            if e.resp.status == 404:
                # No testers configured
                return TesterInfo(track=track, tester_emails=[])
            raise PlayStoreClientError(f"Failed to get testers: {e.reason}") from e
        finally:
            self._delete_edit(package_name, edit_id)

    def update_testers(
        self,
        package_name: str,
        track: str,
        tester_emails: list[str],
        google_group_emails: list[str] | None = None,
    ) -> ListingUpdateResult:
        """Update the list of testers for a track.

        Args:
            package_name: App package name.
            track: Track name (internal, alpha, beta).
            tester_emails: List of individual tester email addresses.
            google_group_emails: List of Google Group email addresses.

        Returns:
            Update result.
        """
        if google_group_emails is None:
            google_group_emails = []

        self._logger.info(
            "Updating testers",
            package_name=package_name,
            track=track,
            individual_count=len(tester_emails),
            group_count=len(google_group_emails),
        )
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            service.edits().testers().update(
                packageName=package_name,
                editId=edit_id,
                track=track,
                body={"testers": tester_emails, "googleGroups": google_group_emails},
            ).execute()

            self._commit_edit(package_name, edit_id)

            total = len(tester_emails) + len(google_group_emails)

            return ListingUpdateResult(
                success=True,
                package_name=package_name,
                language=track,
                message=f"Successfully updated {total} testers for {track}",
            )

        except HttpError as e:
            self._logger.exception("Failed to update testers", error=str(e))
            self._delete_edit(package_name, edit_id)
            return ListingUpdateResult(
                success=False,
                package_name=package_name,
                language=track,
                message=f"Failed to update testers: {e.reason}",
                error=str(e),
            )

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

    def upload_deobfuscation_file(
        self,
        package_name: str,
        version_code: int,
        file_path: str,
        deobfuscation_file_type: str = "proguard",
    ) -> DeobfuscationFileResult:
        """Upload a deobfuscation (ProGuard/R8) mapping file for an APK version.

        Args:
            package_name: App package name.
            version_code: APK version code to associate the mapping with.
            file_path: Absolute path to the mapping.txt file.
            deobfuscation_file_type: Type of mapping file - 'proguard' or 'nativeCode'.

        Returns:
            Upload result.
        """
        self._logger.info(
            "Uploading deobfuscation file",
            package_name=package_name,
            version_code=version_code,
            file_path=file_path,
            type=deobfuscation_file_type,
        )

        if not os.path.isfile(file_path):
            return DeobfuscationFileResult(
                success=False,
                package_name=package_name,
                version_code=version_code,
                deobfuscation_file_type=deobfuscation_file_type,
                message=f"File not found: {file_path}",
            )

        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            media = MediaFileUpload(
                file_path,
                mimetype="application/octet-stream",
                resumable=False,
            )
            service.edits().deobfuscationfiles().upload(
                packageName=package_name,
                editId=edit_id,
                apkVersionCode=version_code,
                deobfuscationFileType=deobfuscation_file_type,
                media_body=media,
            ).execute()

            self._commit_edit(package_name, edit_id)

            return DeobfuscationFileResult(
                success=True,
                package_name=package_name,
                version_code=version_code,
                deobfuscation_file_type=deobfuscation_file_type,
                message=(
                    f"Successfully uploaded {deobfuscation_file_type} mapping "
                    f"for version {version_code}"
                ),
            )

        except HttpError as e:
            self._logger.exception("Failed to upload deobfuscation file", error=str(e))
            self._delete_edit(package_name, edit_id)
            return DeobfuscationFileResult(
                success=False,
                package_name=package_name,
                version_code=version_code,
                deobfuscation_file_type=deobfuscation_file_type,
                message=f"Failed to upload deobfuscation file: {e.reason}",
                error=str(e),
            )
        except Exception as e:
            self._logger.exception("Failed to upload deobfuscation file", error=str(e))
            self._delete_edit(package_name, edit_id)
            return DeobfuscationFileResult(
                success=False,
                package_name=package_name,
                version_code=version_code,
                deobfuscation_file_type=deobfuscation_file_type,
                message=f"Failed to upload deobfuscation file: {e}",
                error=str(e),
            )

    def list_bundles(self, package_name: str) -> list[BundleInfo]:
        """List all AAB bundles for the app.

        Args:
            package_name: App package name.

        Returns:
            List of bundle information objects.
        """
        self._logger.info("Listing bundles", package_name=package_name)
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            result = (
                service.edits()
                .bundles()
                .list(packageName=package_name, editId=edit_id)
                .execute()
            )

            bundles = []
            for b in result.get("bundles", []):
                bundles.append(
                    BundleInfo(
                        package_name=package_name,
                        version_code=int(b.get("versionCode", 0)),
                        sha1=b.get("sha1"),
                        sha256=b.get("sha256"),
                    )
                )
            return bundles

        except HttpError as e:
            self._logger.exception("Failed to list bundles", error=str(e))
            raise PlayStoreClientError(f"Failed to list bundles: {e.reason}") from e
        finally:
            self._delete_edit(package_name, edit_id)

    def list_generated_apks(
        self,
        package_name: str,
        bundle_version_code: int,
    ) -> list[GeneratedApkInfo]:
        """List APKs generated from a specific AAB bundle version.

        Args:
            package_name: App package name.
            bundle_version_code: Version code of the bundle to query.

        Returns:
            List of generated APK info objects.
        """
        self._logger.info(
            "Listing generated APKs",
            package_name=package_name,
            bundle_version_code=bundle_version_code,
        )
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            result = (
                service.edits()
                .generatedapks()
                .list(
                    packageName=package_name,
                    editId=edit_id,
                    versionCode=bundle_version_code,
                )
                .execute()
            )

            apks = []
            for apk in result.get("generatedApks", []):
                split_types = []
                if apk.get("generatedSplitApks"):
                    split_types.append("splits")
                if apk.get("generatedUniversalApk"):
                    split_types.append("universal")
                if apk.get("generatedStandaloneApks"):
                    split_types.append("standalone")

                apks.append(
                    GeneratedApkInfo(
                        package_name=package_name,
                        bundle_version_code=bundle_version_code,
                        download_id=apk.get("downloadId"),
                        variant_id=apk.get("variantId"),
                        target_sdk_version=apk.get("targetSdkVersion"),
                        min_sdk_version=apk.get("minSdkVersion"),
                        split_types=split_types,
                    )
                )
            return apks

        except HttpError as e:
            self._logger.exception("Failed to list generated APKs", error=str(e))
            raise PlayStoreClientError(f"Failed to list generated APKs: {e.reason}") from e
        finally:
            self._delete_edit(package_name, edit_id)

    # =========================================================================
    # Images API
    # =========================================================================

    def list_images(
        self,
        package_name: str,
        language: str,
        image_type: str,
    ) -> list[ImageInfo]:
        """List store listing images of a given type and language.

        Args:
            package_name: App package name.
            language: Language code (e.g., en-US).
            image_type: One of: phoneScreenshots, sevenInchScreenshots,
                        tenInchScreenshots, tvScreenshots, wearScreenshots,
                        icon, featureGraphic, tvBanner, promoGraphic.

        Returns:
            List of image info objects.
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
            result = (
                service.edits()
                .images()
                .list(
                    packageName=package_name,
                    editId=edit_id,
                    language=language,
                    imageType=image_type,
                )
                .execute()
            )

            return [
                ImageInfo(
                    image_id=img["id"],
                    url=img.get("url", ""),
                    sha1=img.get("sha1"),
                    sha256=img.get("sha256"),
                )
                for img in result.get("images", [])
            ]
        finally:
            self._delete_edit(package_name, edit_id)

    def upload_image(
        self,
        package_name: str,
        language: str,
        image_type: str,
        file_path: str,
    ) -> ImageUploadResult:
        """Upload a store listing image.

        Args:
            package_name: App package name.
            language: Language code (e.g., en-US).
            image_type: Image type (e.g., phoneScreenshots, icon, featureGraphic).
            file_path: Absolute path to the image file (PNG or JPEG).

        Returns:
            Upload result with image ID.
        """
        self._logger.info(
            "Uploading image",
            package_name=package_name,
            language=language,
            image_type=image_type,
            file_path=file_path,
        )
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            media = MediaFileUpload(file_path, resumable=True)
            result = (
                service.edits()
                .images()
                .upload(
                    packageName=package_name,
                    editId=edit_id,
                    language=language,
                    imageType=image_type,
                    media_body=media,
                )
                .execute()
            )

            self._commit_edit(package_name, edit_id)
            img = result.get("image", {})
            return ImageUploadResult(
                success=True,
                package_name=package_name,
                language=language,
                image_type=image_type,
                image_id=img.get("id"),
                message=f"Successfully uploaded {image_type} image for {language}",
            )

        except HttpError as e:
            self._logger.exception("Failed to upload image", error=str(e))
            self._delete_edit(package_name, edit_id)
            return ImageUploadResult(
                success=False,
                package_name=package_name,
                language=language,
                image_type=image_type,
                message=f"Failed to upload image: {e.reason}",
                error=str(e),
            )
        except Exception as e:
            self._logger.exception("Failed to upload image", error=str(e))
            self._delete_edit(package_name, edit_id)
            return ImageUploadResult(
                success=False,
                package_name=package_name,
                language=language,
                image_type=image_type,
                message=f"Failed to upload image: {e}",
                error=str(e),
            )

    def delete_image(
        self,
        package_name: str,
        language: str,
        image_type: str,
        image_id: str,
    ) -> ImageUploadResult:
        """Delete a specific store listing image.

        Args:
            package_name: App package name.
            language: Language code (e.g., en-US).
            image_type: Image type.
            image_id: ID of the image to delete.

        Returns:
            Delete result.
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
            service.edits().images().delete(
                packageName=package_name,
                editId=edit_id,
                language=language,
                imageType=image_type,
                imageId=image_id,
            ).execute()

            self._commit_edit(package_name, edit_id)
            return ImageUploadResult(
                success=True,
                package_name=package_name,
                language=language,
                image_type=image_type,
                image_id=image_id,
                message=f"Successfully deleted image {image_id}",
            )

        except HttpError as e:
            self._logger.exception("Failed to delete image", error=str(e))
            self._delete_edit(package_name, edit_id)
            return ImageUploadResult(
                success=False,
                package_name=package_name,
                language=language,
                image_type=image_type,
                message=f"Failed to delete image: {e.reason}",
                error=str(e),
            )

    def delete_all_images(
        self,
        package_name: str,
        language: str,
        image_type: str,
    ) -> ImageUploadResult:
        """Delete all store listing images of a given type and language.

        Args:
            package_name: App package name.
            language: Language code (e.g., en-US).
            image_type: Image type to clear.

        Returns:
            Delete result.
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
            service.edits().images().deleteall(
                packageName=package_name,
                editId=edit_id,
                language=language,
                imageType=image_type,
            ).execute()

            self._commit_edit(package_name, edit_id)
            return ImageUploadResult(
                success=True,
                package_name=package_name,
                language=language,
                image_type=image_type,
                message=f"Successfully deleted all {image_type} images for {language}",
            )

        except HttpError as e:
            self._logger.exception("Failed to delete all images", error=str(e))
            self._delete_edit(package_name, edit_id)
            return ImageUploadResult(
                success=False,
                package_name=package_name,
                language=language,
                image_type=image_type,
                message=f"Failed to delete all images: {e.reason}",
                error=str(e),
            )

    # =========================================================================
    # App Details API (edits.details)
    # =========================================================================

    def get_app_details_info(self, package_name: str) -> AppDetailsInfo:
        """Get app details including default language and contact info.

        Args:
            package_name: App package name.

        Returns:
            App details info.
        """
        self._logger.info("Getting app details", package_name=package_name)
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            result = (
                service.edits()
                .details()
                .get(packageName=package_name, editId=edit_id)
                .execute()
            )

            return AppDetailsInfo(
                package_name=package_name,
                default_language=result.get("defaultLanguage"),
                contact_email=result.get("contactEmail"),
                contact_phone=result.get("contactPhone"),
                contact_website=result.get("contactWebsite"),
            )
        finally:
            self._delete_edit(package_name, edit_id)

    def update_app_details_info(
        self,
        package_name: str,
        default_language: str | None = None,
        contact_email: str | None = None,
        contact_phone: str | None = None,
        contact_website: str | None = None,
    ) -> AppDetailsUpdateResult:
        """Update app details such as default language and contact info.

        Args:
            package_name: App package name.
            default_language: Default language code (e.g., en-US).
            contact_email: Developer contact email.
            contact_phone: Developer contact phone.
            contact_website: Developer contact website.

        Returns:
            Update result.
        """
        self._logger.info("Updating app details", package_name=package_name)
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            current = (
                service.edits()
                .details()
                .get(packageName=package_name, editId=edit_id)
                .execute()
            )

            body = {
                "defaultLanguage": default_language or current.get("defaultLanguage"),
                "contactEmail": contact_email if contact_email is not None else current.get("contactEmail"),
                "contactPhone": contact_phone if contact_phone is not None else current.get("contactPhone"),
                "contactWebsite": contact_website if contact_website is not None else current.get("contactWebsite"),
            }

            service.edits().details().update(
                packageName=package_name,
                editId=edit_id,
                body=body,
            ).execute()

            self._commit_edit(package_name, edit_id)
            return AppDetailsUpdateResult(
                success=True,
                package_name=package_name,
                message="Successfully updated app details",
            )

        except HttpError as e:
            self._logger.exception("Failed to update app details", error=str(e))
            self._delete_edit(package_name, edit_id)
            return AppDetailsUpdateResult(
                success=False,
                package_name=package_name,
                message=f"Failed to update app details: {e.reason}",
                error=str(e),
            )
        except Exception as e:
            self._logger.exception("Failed to update app details", error=str(e))
            self._delete_edit(package_name, edit_id)
            return AppDetailsUpdateResult(
                success=False,
                package_name=package_name,
                message=f"Failed to update app details: {e}",
                error=str(e),
            )

    # =========================================================================
    # Country Availability API (edits.countryavailability)
    # =========================================================================

    def get_country_availability(
        self,
        package_name: str,
        track: str,
    ) -> CountryAvailability:
        """Get country availability for a release track.

        Args:
            package_name: App package name.
            track: Track name (internal, alpha, beta, production).

        Returns:
            Country availability information.
        """
        self._logger.info(
            "Getting country availability",
            package_name=package_name,
            track=track,
        )
        service = self._get_service()
        edit_id = self._create_edit(package_name)

        try:
            result = (
                service.edits()
                .countryavailability()
                .get(packageName=package_name, editId=edit_id, track=track)
                .execute()
            )

            countries = [
                c.get("countryCode", "")
                for c in result.get("countries", [])
            ]
            return CountryAvailability(
                package_name=package_name,
                track=track,
                countries=countries,
                rest_of_world=result.get("restOfWorld", False),
            )
        except HttpError as e:
            if e.resp.status == 404:
                return CountryAvailability(package_name=package_name, track=track)
            raise PlayStoreClientError(f"Failed to get country availability: {e.reason}") from e
        finally:
            self._delete_edit(package_name, edit_id)

    # =========================================================================
    # Users API
    # =========================================================================

    def list_users(self, developer_id: str) -> list[UserInfo]:
        """List all users in a developer account.

        Args:
            developer_id: Developer account ID (numeric, from Play Console URL).

        Returns:
            List of user info objects.
        """
        self._logger.info("Listing users", developer_id=developer_id)
        service = self._get_service()

        try:
            result = service.users().list(
                parent=f"developers/{developer_id}"
            ).execute()

            users = []
            for u in result.get("users", []):
                grants = [
                    GrantInfo(
                        package_name=g.get("packageName", ""),
                        app_level_permissions=g.get("appLevelPermissions", []),
                    )
                    for g in u.get("grants", [])
                ]
                users.append(
                    UserInfo(
                        name=u.get("name"),
                        email=u.get("email", ""),
                        access_state=u.get("accessState"),
                        grants=grants,
                    )
                )
            return users

        except HttpError as e:
            raise PlayStoreClientError(f"Failed to list users: {e.reason}") from e

    def create_user(
        self,
        developer_id: str,
        email: str,
        access_state: str = "accessGranted",
    ) -> UserOperationResult:
        """Add a user to the developer account.

        Args:
            developer_id: Developer account ID.
            email: User email address.
            access_state: Account-level access state. One of:
                          accessGranted, accessExpired, accessRevoked.

        Returns:
            Operation result.
        """
        self._logger.info(
            "Creating user",
            developer_id=developer_id,
            email=email,
            access_state=access_state,
        )
        service = self._get_service()

        try:
            service.users().create(
                parent=f"developers/{developer_id}",
                body={"email": email, "accessState": access_state},
            ).execute()

            return UserOperationResult(
                success=True,
                email=email,
                message=f"Successfully added user {email}",
            )

        except HttpError as e:
            self._logger.exception("Failed to create user", error=str(e))
            return UserOperationResult(
                success=False,
                email=email,
                message=f"Failed to add user: {e.reason}",
                error=str(e),
            )

    def delete_user(
        self,
        developer_id: str,
        email: str,
    ) -> UserOperationResult:
        """Remove a user from the developer account.

        Args:
            developer_id: Developer account ID.
            email: User email address to remove.

        Returns:
            Operation result.
        """
        self._logger.info("Deleting user", developer_id=developer_id, email=email)
        service = self._get_service()

        try:
            service.users().delete(
                name=f"developers/{developer_id}/users/{email}"
            ).execute()

            return UserOperationResult(
                success=True,
                email=email,
                message=f"Successfully removed user {email}",
            )

        except HttpError as e:
            self._logger.exception("Failed to delete user", error=str(e))
            return UserOperationResult(
                success=False,
                email=email,
                message=f"Failed to remove user: {e.reason}",
                error=str(e),
            )

    # =========================================================================
    # Grants API
    # =========================================================================

    def create_grant(
        self,
        developer_id: str,
        email: str,
        package_name: str,
        app_level_permissions: list[str],
    ) -> UserOperationResult:
        """Grant a user app-level permissions.

        Args:
            developer_id: Developer account ID.
            email: User email address.
            package_name: App package name to grant access to.
            app_level_permissions: List of permissions to grant. Valid values include:
                canAccessStats, canManageProductionRelease, canManageTestTracks,
                canManageStorePresence, canReplyToReviews.

        Returns:
            Operation result.
        """
        self._logger.info(
            "Creating grant",
            developer_id=developer_id,
            email=email,
            package_name=package_name,
        )
        service = self._get_service()

        try:
            service.grants().create(
                parent=f"developers/{developer_id}/users/{email}",
                body={
                    "packageName": package_name,
                    "appLevelPermissions": app_level_permissions,
                },
            ).execute()

            return UserOperationResult(
                success=True,
                email=email,
                message=f"Successfully granted permissions on {package_name} to {email}",
            )

        except HttpError as e:
            self._logger.exception("Failed to create grant", error=str(e))
            return UserOperationResult(
                success=False,
                email=email,
                message=f"Failed to create grant: {e.reason}",
                error=str(e),
            )

    def delete_grant(
        self,
        developer_id: str,
        email: str,
        package_name: str,
    ) -> UserOperationResult:
        """Revoke a user's app-level permissions.

        Args:
            developer_id: Developer account ID.
            email: User email address.
            package_name: App package name to revoke access from.

        Returns:
            Operation result.
        """
        self._logger.info(
            "Deleting grant",
            developer_id=developer_id,
            email=email,
            package_name=package_name,
        )
        service = self._get_service()

        try:
            service.grants().delete(
                name=f"developers/{developer_id}/users/{email}/grants/{package_name}"
            ).execute()

            return UserOperationResult(
                success=True,
                email=email,
                message=f"Successfully revoked permissions on {package_name} from {email}",
            )

        except HttpError as e:
            self._logger.exception("Failed to delete grant", error=str(e))
            return UserOperationResult(
                success=False,
                email=email,
                message=f"Failed to revoke grant: {e.reason}",
                error=str(e),
            )

    # =========================================================================
    # Orders Refund API
    # =========================================================================

    def refund_order(
        self,
        package_name: str,
        order_id: str,
        revoke: bool = False,
    ) -> RefundResult:
        """Refund an order.

        Args:
            package_name: App package name.
            order_id: Order ID to refund.
            revoke: If True, also revokes the user's entitlement to the purchase.

        Returns:
            Refund result.
        """
        self._logger.info(
            "Refunding order",
            package_name=package_name,
            order_id=order_id,
            revoke=revoke,
        )
        service = self._get_service()

        try:
            service.orders().refund(
                packageName=package_name,
                orderId=order_id,
                revoke=revoke,
            ).execute()

            return RefundResult(
                success=True,
                order_id=order_id,
                package_name=package_name,
                revoked=revoke,
                message=f"Successfully refunded order {order_id}"
                + (" and revoked entitlement" if revoke else ""),
            )

        except HttpError as e:
            self._logger.exception("Failed to refund order", error=str(e))
            return RefundResult(
                success=False,
                order_id=order_id,
                package_name=package_name,
                message=f"Failed to refund order: {e.reason}",
                error=str(e),
            )

    # =========================================================================
    # Purchases - Products (one-time in-app purchases)
    # =========================================================================

    def get_product_purchase(
        self,
        package_name: str,
        product_id: str,
        token: str,
    ) -> ProductPurchase:
        """Get the status of a one-time in-app product purchase.

        Args:
            package_name: App package name.
            product_id: Product SKU.
            token: Purchase token from the client.

        Returns:
            Product purchase status.
        """
        self._logger.info(
            "Getting product purchase",
            package_name=package_name,
            product_id=product_id,
        )
        service = self._get_service()

        try:
            result = (
                service.purchases()
                .products()
                .get(
                    packageName=package_name,
                    productId=product_id,
                    token=token,
                )
                .execute()
            )

            purchase_time_ms = result.get("purchaseTimeMillis")
            from datetime import datetime, timezone
            purchase_time = (
                datetime.fromtimestamp(int(purchase_time_ms) / 1000, tz=timezone.utc)
                if purchase_time_ms
                else None
            )

            return ProductPurchase(
                package_name=package_name,
                product_id=product_id,
                purchase_token=token,
                purchase_time=purchase_time,
                purchase_state=result.get("purchaseState"),
                consumption_state=result.get("consumptionState"),
                developer_payload=result.get("developerPayload"),
                order_id=result.get("orderId"),
                acknowledged=bool(result.get("acknowledgementState", 0)),
                quantity=result.get("quantity"),
            )

        except HttpError as e:
            raise PlayStoreClientError(f"Failed to get product purchase: {e.reason}") from e

    def acknowledge_product_purchase(
        self,
        package_name: str,
        product_id: str,
        token: str,
        developer_payload: str = "",
    ) -> UserOperationResult:
        """Acknowledge a one-time in-app product purchase.

        Must be called within 3 days of purchase, or the purchase will be reversed.

        Args:
            package_name: App package name.
            product_id: Product SKU.
            token: Purchase token from the client.
            developer_payload: Optional developer payload string.

        Returns:
            Operation result.
        """
        self._logger.info(
            "Acknowledging product purchase",
            package_name=package_name,
            product_id=product_id,
        )
        service = self._get_service()

        try:
            service.purchases().products().acknowledge(
                packageName=package_name,
                productId=product_id,
                token=token,
                body={"developerPayload": developer_payload},
            ).execute()

            return UserOperationResult(
                success=True,
                email="",
                message=f"Successfully acknowledged purchase of {product_id}",
            )

        except HttpError as e:
            self._logger.exception("Failed to acknowledge purchase", error=str(e))
            return UserOperationResult(
                success=False,
                email="",
                message=f"Failed to acknowledge purchase: {e.reason}",
                error=str(e),
            )

    # =========================================================================
    # Purchases - Subscriptions v2
    # =========================================================================

    def get_subscription_purchase_v2(
        self,
        package_name: str,
        token: str,
    ) -> SubscriptionPurchaseV2:
        """Get subscription purchase details using the v2 API.

        Args:
            package_name: App package name.
            token: Purchase token from the client.

        Returns:
            Subscription purchase v2 status.
        """
        self._logger.info(
            "Getting subscription purchase v2",
            package_name=package_name,
        )
        service = self._get_service()

        try:
            result = (
                service.purchases()
                .subscriptionsv2()
                .get(packageName=package_name, token=token)
                .execute()
            )

            from datetime import datetime, timezone

            def parse_time(ts: str | None) -> datetime | None:
                if not ts:
                    return None
                try:
                    return datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except ValueError:
                    return None

            line_items = result.get("lineItems", [])
            first_item = line_items[0] if line_items else {}

            return SubscriptionPurchaseV2(
                package_name=package_name,
                purchase_token=token,
                subscription_state=result.get("subscriptionState"),
                latest_order_id=result.get("latestOrderId"),
                start_time=parse_time(result.get("startTime")),
                expiry_time=parse_time(first_item.get("expiryTime")),
                auto_renewing=result.get("cancelSurveyResult") is None
                and result.get("subscriptionState") == "SUBSCRIPTION_STATE_ACTIVE",
                product_id=first_item.get("productId"),
                base_plan_id=first_item.get("offerDetails", {}).get("basePlanId"),
                offer_id=first_item.get("offerDetails", {}).get("offerId"),
            )

        except HttpError as e:
            raise PlayStoreClientError(
                f"Failed to get subscription purchase v2: {e.reason}"
            ) from e

    def cancel_subscription_v2(
        self,
        package_name: str,
        token: str,
    ) -> UserOperationResult:
        """Cancel a subscription using the v2 API.

        Args:
            package_name: App package name.
            token: Purchase token from the client.

        Returns:
            Operation result.
        """
        self._logger.info(
            "Canceling subscription v2",
            package_name=package_name,
        )
        service = self._get_service()

        try:
            service.purchases().subscriptionsv2().cancel(
                packageName=package_name,
                token=token,
                body={},
            ).execute()

            return UserOperationResult(
                success=True,
                email="",
                message="Successfully canceled subscription",
            )

        except HttpError as e:
            self._logger.exception("Failed to cancel subscription", error=str(e))
            return UserOperationResult(
                success=False,
                email="",
                message=f"Failed to cancel subscription: {e.reason}",
                error=str(e),
            )

    def revoke_subscription_v2(
        self,
        package_name: str,
        token: str,
    ) -> UserOperationResult:
        """Revoke a subscription using the v2 API (cancels and immediately expires).

        Args:
            package_name: App package name.
            token: Purchase token from the client.

        Returns:
            Operation result.
        """
        self._logger.info(
            "Revoking subscription v2",
            package_name=package_name,
        )
        service = self._get_service()

        try:
            service.purchases().subscriptionsv2().revoke(
                packageName=package_name,
                token=token,
                body={},
            ).execute()

            return UserOperationResult(
                success=True,
                email="",
                message="Successfully revoked subscription",
            )

        except HttpError as e:
            self._logger.exception("Failed to revoke subscription", error=str(e))
            return UserOperationResult(
                success=False,
                email="",
                message=f"Failed to revoke subscription: {e.reason}",
                error=str(e),
            )

    # =========================================================================
    # Play Developer Reporting API
    # =========================================================================

    def _parse_date(self, time_unit: dict[str, Any]) -> str:
        """Convert Reporting API TimeUnit dict to YYYY-MM-DD string."""
        y = time_unit.get("year", 0)
        m = time_unit.get("month", 0)
        d = time_unit.get("day", 0)
        return f"{y:04d}-{m:02d}-{d:02d}"

    def _build_time_unit(self, date_str: str) -> dict[str, Any]:
        """Convert YYYY-MM-DD string to Reporting API TimeUnit dict."""
        parts = date_str.split("-")
        return {"year": int(parts[0]), "month": int(parts[1]), "day": int(parts[2])}

    # Maps metric set name → vitals sub-resource method name in the client library
    _METRIC_SET_RESOURCE: dict[str, str] = {
        "crashRateMetricSet": "crashrate",
        "anrRateMetricSet": "anrrate",
        "slowStartRateMetricSet": "slowstartrate",
        "slowRenderingRateMetricSet": "slowrenderingrate",
        "excessiveWakeupRateMetricSet": "excessivewakeuprate",
        "stuckBackgroundWakelockRateMetricSet": "stuckbackgroundwakelockrate",
        "lmkRateMetricSet": "lmkrate",
    }

    def _query_metric_set(
        self,
        package_name: str,
        metric_set_name: str,
        metrics: list[str],
        dimensions: list[str],
        start_date: str,
        end_date: str,
        aggregation_period: str = "DAILY",
    ) -> "VitalsQueryResult":
        """Generic helper to query any Reporting API metric set."""
        from play_store_mcp.models import VitalsDataPoint, VitalsQueryResult

        service = self._get_reporting_service()

        body: dict[str, Any] = {
            "timelineSpec": {
                "aggregationPeriod": aggregation_period,
                "startTime": self._build_time_unit(start_date),
                "endTime": self._build_time_unit(end_date),
            },
            "metrics": metrics,
        }
        if dimensions:
            body["dimensions"] = dimensions

        self._logger.info(
            "Querying metric set",
            package_name=package_name,
            metric_set=metric_set_name,
            start=start_date,
            end=end_date,
        )

        resource_method = self._METRIC_SET_RESOURCE.get(metric_set_name)
        if not resource_method:
            raise PlayStoreClientError(f"Unknown metric set: {metric_set_name}")

        try:
            resource = getattr(service.vitals(), resource_method)()
            result = resource.query(
                name=f"apps/{package_name}/{metric_set_name}", body=body
            ).execute()

            data_points: list[VitalsDataPoint] = []
            for row in result.get("rows", []):
                dims: dict[str, str] = {}
                for d in row.get("dimensions", []):
                    key = d.get("dimension", "")
                    val = d.get("stringValue") or d.get("int64Value") or d.get("decimalValue", {}).get("value", "")
                    dims[key] = str(val)

                met: dict[str, float | None] = {}
                for m in row.get("metrics", []):
                    key = m.get("metric", "")
                    decimal = m.get("decimalValue", {})
                    val_str = decimal.get("value") if decimal else None
                    met[key] = float(val_str) if val_str is not None else None

                date_str = self._parse_date(row.get("startTime", {}))
                data_points.append(
                    VitalsDataPoint(
                        date=date_str,
                        aggregation_period=aggregation_period,
                        dimensions=dims,
                        metrics=met,
                    )
                )

            display_name = metric_set_name.replace("MetricSet", "")
            return VitalsQueryResult(
                package_name=package_name,
                metric_set=display_name,
                aggregation_period=aggregation_period,
                data_points=data_points,
                row_count=len(data_points),
            )

        except HttpError as e:
            self._logger.exception("Reporting API query failed", error=str(e))
            raise PlayStoreClientError(
                f"Reporting API query failed for {metric_set_name}: {e.reason}"
            ) from e

    def get_crash_rate(
        self,
        package_name: str,
        start_date: str,
        end_date: str,
        dimensions: list[str] | None = None,
    ) -> "VitalsQueryResult":
        """Query crash rate metrics from Play Developer Reporting API.

        Requires the service account to have Performance Analysis permission
        in Play Console (Account-level > Performance Analysis).

        Args:
            package_name: App package name.
            start_date: Start date YYYY-MM-DD.
            end_date: End date YYYY-MM-DD (exclusive).
            dimensions: Optional grouping dimensions e.g. ['versionCode', 'apiLevel'].

        Returns:
            VitalsQueryResult with crashRate and distinctUsers per day.
        """
        return self._query_metric_set(
            package_name=package_name,
            metric_set_name="crashRateMetricSet",
            metrics=["crashRate", "distinctUsers", "crashCount"],
            dimensions=dimensions or [],
            start_date=start_date,
            end_date=end_date,
        )

    def get_anr_rate(
        self,
        package_name: str,
        start_date: str,
        end_date: str,
        dimensions: list[str] | None = None,
    ) -> "VitalsQueryResult":
        """Query ANR (Application Not Responding) rate metrics.

        Args:
            package_name: App package name.
            start_date: Start date YYYY-MM-DD.
            end_date: End date YYYY-MM-DD (exclusive).
            dimensions: Optional grouping dimensions e.g. ['versionCode', 'apiLevel'].

        Returns:
            VitalsQueryResult with anrRate and distinctUsers per day.
        """
        return self._query_metric_set(
            package_name=package_name,
            metric_set_name="anrRateMetricSet",
            metrics=["anrRate", "anrRate7dUserWeighted", "anrRate28dUserWeighted", "distinctUsers"],
            dimensions=dimensions or [],
            start_date=start_date,
            end_date=end_date,
        )

    def get_slow_startup_rate(
        self,
        package_name: str,
        start_date: str,
        end_date: str,
        dimensions: list[str] | None = None,
    ) -> "VitalsQueryResult":
        """Query slow startup rate metrics.

        Args:
            package_name: App package name.
            start_date: Start date YYYY-MM-DD.
            end_date: End date YYYY-MM-DD (exclusive).
            dimensions: Optional grouping dimensions.

        Returns:
            VitalsQueryResult with slowStartupRate per day.
        """
        # startType is a required dimension for slowStartRateMetricSet
        dims = list(dimensions) if dimensions else []
        if "startType" not in dims:
            dims = ["startType"] + dims
        return self._query_metric_set(
            package_name=package_name,
            metric_set_name="slowStartRateMetricSet",
            metrics=["slowStartRate", "slowStartRate7dUserWeighted", "slowStartRate28dUserWeighted", "distinctUsers"],
            dimensions=dims,
            start_date=start_date,
            end_date=end_date,
        )

    def get_slow_rendering_rate(
        self,
        package_name: str,
        start_date: str,
        end_date: str,
        dimensions: list[str] | None = None,
    ) -> "VitalsQueryResult":
        """Query slow rendering rate metrics (< 20fps / < 30fps).

        Args:
            package_name: App package name.
            start_date: Start date YYYY-MM-DD.
            end_date: End date YYYY-MM-DD (exclusive).
            dimensions: Optional grouping dimensions.

        Returns:
            VitalsQueryResult with slowRenderingRate20Fps, slowRenderingRate30Fps per day.
        """
        return self._query_metric_set(
            package_name=package_name,
            metric_set_name="slowRenderingRateMetricSet",
            metrics=["slowRenderingRate20Fps", "slowRenderingRate30Fps", "distinctUsers"],
            dimensions=dimensions or [],
            start_date=start_date,
            end_date=end_date,
        )

    def get_excessive_wakeup_rate(
        self,
        package_name: str,
        start_date: str,
        end_date: str,
        dimensions: list[str] | None = None,
    ) -> "VitalsQueryResult":
        """Query excessive wakeup rate metrics.

        Args:
            package_name: App package name.
            start_date: Start date YYYY-MM-DD.
            end_date: End date YYYY-MM-DD (exclusive).
            dimensions: Optional grouping dimensions.

        Returns:
            VitalsQueryResult with excessiveWakeupRate per day.
        """
        return self._query_metric_set(
            package_name=package_name,
            metric_set_name="excessiveWakeupRateMetricSet",
            metrics=["excessiveWakeupRate", "excessiveWakeupRate7dUserWeighted", "excessiveWakeupRate28dUserWeighted", "distinctUsers"],
            dimensions=dimensions or [],
            start_date=start_date,
            end_date=end_date,
        )

    def get_stuck_wakelock_rate(
        self,
        package_name: str,
        start_date: str,
        end_date: str,
        dimensions: list[str] | None = None,
    ) -> "VitalsQueryResult":
        """Query stuck background wakelock rate metrics.

        Args:
            package_name: App package name.
            start_date: Start date YYYY-MM-DD.
            end_date: End date YYYY-MM-DD (exclusive).
            dimensions: Optional grouping dimensions.

        Returns:
            VitalsQueryResult with stuckBgWakelockRate per day.
        """
        return self._query_metric_set(
            package_name=package_name,
            metric_set_name="stuckBackgroundWakelockRateMetricSet",
            metrics=["stuckBgWakelockRate", "stuckBgWakelockRate7dUserWeighted", "stuckBgWakelockRate28dUserWeighted", "distinctUsers"],
            dimensions=dimensions or [],
            start_date=start_date,
            end_date=end_date,
        )

    def get_lmk_rate(
        self,
        package_name: str,
        start_date: str,
        end_date: str,
        dimensions: list[str] | None = None,
    ) -> "VitalsQueryResult":
        """Query Low Memory Killer (LMK) rate metrics.

        LMK rate measures how often the system kills the app due to memory pressure.
        High LMK rate indicates the app uses too much memory.

        Args:
            package_name: App package name.
            start_date: Start date YYYY-MM-DD.
            end_date: End date YYYY-MM-DD (exclusive).
            dimensions: Optional grouping dimensions.

        Returns:
            VitalsQueryResult with lmkRate per day.
        """
        return self._query_metric_set(
            package_name=package_name,
            metric_set_name="lmkRateMetricSet",
            metrics=["userPerceivedLmkRate", "userPerceivedLmkRate7dUserWeighted", "userPerceivedLmkRate28dUserWeighted", "distinctUsers"],
            dimensions=dimensions or [],
            start_date=start_date,
            end_date=end_date,
        )

    def list_vitals_anomalies(
        self,
        package_name: str,
        filter_str: str | None = None,
    ) -> "list[VitalsAnomaly]":
        """List detected vitals anomalies for an app.

        Anomalies are automatically detected degradations in any vitals metric.

        Args:
            package_name: App package name.
            filter_str: Optional filter string, e.g. 'metric = crashRate'.

        Returns:
            List of VitalsAnomaly objects.
        """
        from play_store_mcp.models import VitalsAnomaly

        service = self._get_reporting_service()
        parent = f"apps/{package_name}"

        self._logger.info("Listing vitals anomalies", package_name=package_name)

        try:
            kwargs: dict[str, Any] = {"parent": parent}
            if filter_str:
                kwargs["filter"] = filter_str

            result = service.anomalies().list(**kwargs).execute()

            anomalies = []
            for a in result.get("anomalies", []):
                dims: dict[str, str] = {}
                for d in a.get("dimensions", []):
                    key = d.get("dimension", "")
                    val = d.get("stringValue") or d.get("int64Value", "")
                    dims[key] = str(val)

                first_time = a.get("firstDetectionTime")
                first_str = self._parse_date(first_time) if first_time else None

                last_day = a.get("lastDetectedDay")
                last_str = self._parse_date(last_day) if last_day else None

                anomalies.append(
                    VitalsAnomaly(
                        name=a.get("name", ""),
                        metric_set=a.get("metricSet", "").replace("MetricSet", ""),
                        dimensions=dims,
                        first_detection_time=first_str,
                        last_detected_day=last_str,
                    )
                )
            return anomalies

        except HttpError as e:
            self._logger.exception("Failed to list anomalies", error=str(e))
            raise PlayStoreClientError(f"Failed to list vitals anomalies: {e.reason}") from e

    # =========================================================================
    # Play Console Browser-Based Stats (requires OpenCLI + logged-in browser)
    # =========================================================================

    # Metric type mapping (reverse-engineered from Play Console internal API)
    # These map the URL metric names to the numeric type used in the PA RPC body.
    _CONSOLE_METRIC_TYPES: dict[str, tuple[int, int]] = {
        "install_events": (1, 1),   # INSTALL_EVENTS, COUNT
        "net_installs": (2, 1),     # NET_INSTALLS, COUNT
        "active_users": (3, 2),     # ACTIVE_USERS, UNIQUE
    }

    _OPENCLI_BIN = os.path.expanduser("~/.npm-global/bin/opencli")

    def _run_browser_js(self, js: str, timeout: int = 20) -> str:
        """Run JS in the OpenCLI automation browser and return the result string."""
        result = subprocess.run(
            [self._OPENCLI_BIN, "browser", "eval", js],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            raise PlayStoreClientError(f"opencli browser eval failed: {result.stderr[:200]}")
        return result.stdout.strip()

    def _fetch_console_time_series(
        self,
        developer_id: str,
        app_id: str,
        metric_type: int,
        count_type: int,
        start_year: int, start_month: int, start_day: int,
        end_year: int, end_month: int, end_day: int,
        country_codes: list[str] | None = None,
    ) -> dict:
        """Make a statspage/time_series request via the browser (bypasses service-account auth)."""
        dimensions_js = "[{'1':1}"  # always include overall
        if country_codes:
            for cc in country_codes:
                dimensions_js += f",{{'1':2,'2':'{cc}'}}"
        dimensions_js += "]"

        js = f"""
(async function() {{
  const SAPISID = document.cookie.match(/SAPISID=([^;]+)/)?.[1];
  if (!SAPISID) return JSON.stringify({{error: 'Not logged into Play Console'}});
  const ts = Date.now();
  const msgBuffer = new TextEncoder().encode(ts + ' ' + SAPISID + ' https://play.google.com');
  const hashBuffer = await crypto.subtle.digest('SHA-1', msgBuffer);
  const sha1 = Array.from(new Uint8Array(hashBuffer)).map(b=>b.toString(16).padStart(2,'0')).join('');
  const auth = 'SAPISIDHASH ' + ts + '_' + sha1;
  const DEV_ID = '{developer_id}';
  const APP_ID = '{app_id}';
  const API_KEY = 'AIzaSyBAha_rcoO_aGsmiR5fWbNfdOjqT0gXwbk';
  const httpHeaders = 'Content-Type:application/json+protobuf\\r\\nX-Goog-AuthUser:0\\r\\nAuthorization:' + auth + '\\r\\nX-Goog-Api-Key:' + API_KEY + '\\r\\n';
  const url = 'https://playconsolestatsfrontend-pa.clients6.google.com/v1/developers/' + DEV_ID + '/apps/' + APP_ID + '/statspage/time_series?$httpHeaders=' + encodeURIComponent(httpHeaders);
  const body = JSON.stringify({{'1':{{'1':{{'1':DEV_ID}},'2':{{'1':APP_ID}}}},'2':{{'1':{{'1':{start_year},'2':{start_month},'3':{start_day}}},'2':{{'1':{end_year},'2':{end_month},'3':{end_day}}}}},'4':[{{'1':{{'1':{metric_type},'2':1,'3':{count_type},'4':1}},'2':2}}],'5':1,'7':{{'1':{dimensions_js}}}}});
  const resp = await fetch(url, {{method:'POST', body:body, credentials:'include'}});
  const data = await resp.json();
  return JSON.stringify(data);
}})()
"""
        raw = self._run_browser_js(js)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise PlayStoreClientError(f"Invalid JSON from browser stats: {raw[:200]}")

    def _parse_console_series(
        self,
        data: dict,
        metric_name: str,
        dim_index: int = 0,
        country_code: str = "overall",
    ) -> ConsoleStatsResult:
        """Parse a statspage/time_series response into ConsoleStatsResult."""
        series_list = data.get("1", [])
        if dim_index >= len(series_list):
            return ConsoleStatsResult(metric=metric_name, dimension=country_code, total=0)

        series = series_list[dim_index]
        points_raw = series.get("4", {}).get("1", [])

        data_points: list[DailyStatPoint] = []
        total = 0
        for p in points_raw:
            val_obj = p.get("2", {})
            val = int(val_obj.get("2") or val_obj.get("1") or 0)
            if val == 0:
                continue
            date_obj = p.get("4", {})
            y, m, d = date_obj.get("1", 0), date_obj.get("2", 0), date_obj.get("3", 0)
            if y and m and d:
                date_str = f"{y:04d}-{m:02d}-{d:02d}"
                data_points.append(DailyStatPoint(date=date_str, value=val))
                total += val

        return ConsoleStatsResult(
            metric=metric_name,
            dimension=country_code,
            total=total,
            data_points=data_points,
        )

    def get_install_stats(
        self,
        package_name: str,
        developer_id: str,
        app_id: str,
        start_date: str,
        end_date: str,
        country_codes: list[str] | None = None,
    ) -> ConsoleInstallStats:
        """Get install statistics from Play Console via browser session.

        Requires OpenCLI to be installed and the user to be logged into
        Play Console (play.google.com/console) in the automation browser.

        developer_id and app_id are the numeric IDs visible in the Play Console
        URL: /console/u/0/developers/{developer_id}/app/{app_id}/statistics

        Args:
            package_name: App package name (for display only).
            developer_id: Numeric developer account ID from Play Console URL.
            app_id: Numeric app ID from Play Console URL.
            start_date: Start date YYYY-MM-DD.
            end_date: End date YYYY-MM-DD.
            country_codes: Optional list of country codes (e.g. ['US','GB']) for breakdown.

        Returns:
            ConsoleInstallStats with install events, net installs, active users,
            and optional per-country breakdown.
        """
        from datetime import date as date_cls

        def parse_date(s: str) -> tuple[int, int, int]:
            d = date_cls.fromisoformat(s)
            return d.year, d.month, d.day

        sy, sm, sd = parse_date(start_date)
        ey, em, ed = parse_date(end_date)

        self._logger.info("Fetching install stats via browser", package_name=package_name)

        # Fetch all three metrics
        install_data = self._fetch_console_time_series(
            developer_id, app_id, 1, 1, sy, sm, sd, ey, em, ed, country_codes
        )
        net_data = self._fetch_console_time_series(
            developer_id, app_id, 2, 1, sy, sm, sd, ey, em, ed
        )
        active_data = self._fetch_console_time_series(
            developer_id, app_id, 3, 2, sy, sm, sd, ey, em, ed
        )

        install_result = self._parse_console_series(install_data, "install_events", 0, "overall")
        net_result = self._parse_console_series(net_data, "net_installs", 0, "overall")
        active_result = self._parse_console_series(active_data, "active_users", 0, "overall")

        # Per-country breakdown for install events
        by_country: list[ConsoleStatsResult] = []
        if country_codes:
            for i, cc in enumerate(country_codes):
                r = self._parse_console_series(install_data, "install_events", i + 1, cc)
                by_country.append(r)

        return ConsoleInstallStats(
            package_name=package_name,
            start_date=start_date,
            end_date=end_date,
            install_events=install_result,
            net_installs=net_result,
            active_users=active_result,
            by_country=by_country,
        )

    def get_search_terms(
        self,
        package_name: str,
        developer_id: str,
        app_id: str,
        start_date: str,
        end_date: str,
    ) -> SearchTermsStats:
        """Get top search terms from Play Console via browser session.

        Calls the top_dimension_values endpoint with dimension=SEARCH_TERM.
        Requires OpenCLI with an active Play Console browser session.

        Args:
            package_name: App package name (display only).
            developer_id: Numeric developer ID from Play Console URL.
            app_id: Numeric app ID from Play Console URL.
            start_date: Start date YYYY-MM-DD.
            end_date: End date YYYY-MM-DD.

        Returns:
            SearchTermsStats with terms sorted by installs descending.
        """
        from datetime import date as date_cls

        def parse_date(s: str) -> tuple[int, int, int]:
            d = date_cls.fromisoformat(s)
            return d.year, d.month, d.day

        sy, sm, sd = parse_date(start_date)
        ey, em, ed = parse_date(end_date)

        self._logger.info("Fetching search terms via browser", package_name=package_name)

        # Uses getAcquisitionDetailsTableData with dimension type 2 (Search term).
        # Note: low-volume apps may only return "Other" due to Google's privacy threshold.
        js = f"""
(async function() {{
  const SAPISID = document.cookie.match(/SAPISID=([^;]+)/)?.[1];
  if (!SAPISID) return JSON.stringify({{error: 'Not logged into Play Console'}});
  const ts = Date.now();
  const msgBuffer = new TextEncoder().encode(ts + ' ' + SAPISID + ' https://play.google.com');
  const hashBuffer = await crypto.subtle.digest('SHA-1', msgBuffer);
  const sha1 = Array.from(new Uint8Array(hashBuffer)).map(b=>b.toString(16).padStart(2,'0')).join('');
  const auth = 'SAPISIDHASH ' + ts + '_' + sha1;
  const DEV_ID = '{developer_id}';
  const APP_ID = '{app_id}';
  const API_KEY = 'AIzaSyBAha_rcoO_aGsmiR5fWbNfdOjqT0gXwbk';
  const httpHeaders = 'Content-Type:application/json+protobuf\\r\\nX-Goog-AuthUser:0\\r\\nAuthorization:' + auth + '\\r\\nX-Goog-Api-Key:' + API_KEY + '\\r\\n';
  const url = 'https://playconsolestatsfrontend-pa.clients6.google.com/v1/developers/' + DEV_ID + '/apps/' + APP_ID + '/stats/acquisition:getAcquisitionDetailsTableData?$httpHeaders=' + encodeURIComponent(httpHeaders);
  const body = JSON.stringify({{'1':{{'1':{{'1':DEV_ID}},'2':{{'1':APP_ID}}}},'2':{{'1':{{'1':{sy},'2':{sm},'3':{sd}}},'2':{{'1':{ey},'2':{em},'3':{ed}}}}},'3':{{'1':2}},'5':1}});
  const resp = await fetch(url, {{method:'POST', body:body, credentials:'include'}});
  const data = await resp.json();
  return JSON.stringify(data);
}})()
"""
        raw = self._run_browser_js(js)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise PlayStoreClientError(f"Invalid JSON from browser search terms: {raw[:200]}")

        if "error" in data:
            raise PlayStoreClientError(f"Browser error: {data['error']}")

        # Response: data["1"]["3"] = list of search term rows.
        # Each row: "1"={"1": term_id, "2": display_name}, "2"={"1": visitors}, "3"={"1": installs}.
        # Row "1"."1" == "REMOVED_BY_THRESHOLDING_STORE_QUERY" means data below privacy threshold.
        terms: list[SearchTermResult] = []
        inner = data.get("1", {})
        for row in inner.get("3", []):
            label = row.get("1", {})
            term_id = label.get("1", "")
            term_display = label.get("2", term_id)
            if term_id == "REMOVED_BY_THRESHOLDING_STORE_QUERY":
                term_str = f"(other: {term_display})"
            else:
                term_str = term_display or term_id
            visitors = int(row.get("2", {}).get("1") or 0)
            installs = int(row.get("3", {}).get("1") or 0)
            if term_str:
                terms.append(SearchTermResult(term=term_str, installs=installs, store_listing_visitors=visitors))

        terms.sort(key=lambda t: t.installs, reverse=True)

        return SearchTermsStats(
            package_name=package_name,
            start_date=start_date,
            end_date=end_date,
            terms=terms,
        )

    def get_acquisition_funnel(
        self,
        package_name: str,
        developer_id: str,
        app_id: str,
        start_date: str,
        end_date: str,
    ) -> AcquisitionFunnelResult:
        """Get user acquisition funnel from Play Console via browser session.

        Calls the stats/acquisition:getAcquisitionSummary endpoint.
        Requires OpenCLI with an active Play Console browser session.

        Args:
            package_name: App package name (display only).
            developer_id: Numeric developer ID from Play Console URL.
            app_id: Numeric app ID from Play Console URL.
            start_date: Start date YYYY-MM-DD.
            end_date: End date YYYY-MM-DD.

        Returns:
            AcquisitionFunnelResult with stages: impressions → store_listing_visitors → installers → buyers.
        """
        from datetime import date as date_cls

        def parse_date(s: str) -> tuple[int, int, int]:
            d = date_cls.fromisoformat(s)
            return d.year, d.month, d.day

        sy, sm, sd = parse_date(start_date)
        ey, em, ed = parse_date(end_date)

        self._logger.info("Fetching acquisition funnel via browser", package_name=package_name)

        js = f"""
(async function() {{
  const SAPISID = document.cookie.match(/SAPISID=([^;]+)/)?.[1];
  if (!SAPISID) return JSON.stringify({{error: 'Not logged into Play Console'}});
  const ts = Date.now();
  const msgBuffer = new TextEncoder().encode(ts + ' ' + SAPISID + ' https://play.google.com');
  const hashBuffer = await crypto.subtle.digest('SHA-1', msgBuffer);
  const sha1 = Array.from(new Uint8Array(hashBuffer)).map(b=>b.toString(16).padStart(2,'0')).join('');
  const auth = 'SAPISIDHASH ' + ts + '_' + sha1;
  const DEV_ID = '{developer_id}';
  const APP_ID = '{app_id}';
  const API_KEY = 'AIzaSyBAha_rcoO_aGsmiR5fWbNfdOjqT0gXwbk';
  const httpHeaders = 'Content-Type:application/json+protobuf\\r\\nX-Goog-AuthUser:0\\r\\nAuthorization:' + auth + '\\r\\nX-Goog-Api-Key:' + API_KEY + '\\r\\n';
  const url = 'https://playconsolestatsfrontend-pa.clients6.google.com/v1/developers/' + DEV_ID + '/apps/' + APP_ID + '/stats/acquisition:getAcquisitionSummary?$httpHeaders=' + encodeURIComponent(httpHeaders);
  const body = JSON.stringify({{'1':{{'1':{{'1':DEV_ID}},'2':{{'1':APP_ID}}}},'2':{{'1':{{'1':{sy},'2':{sm},'3':{sd}}},'2':{{'1':{ey},'2':{em},'3':{ed}}}}}}});
  const resp = await fetch(url, {{method:'POST', body:body, credentials:'include'}});
  const data = await resp.json();
  return JSON.stringify(data);
}})()
"""
        raw = self._run_browser_js(js)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise PlayStoreClientError(f"Invalid JSON from browser acquisition funnel: {raw[:200]}")

        if "error" in data:
            raise PlayStoreClientError(f"Browser error: {data['error']}")

        # Response structure (from live reverse-engineering):
        #   "1" = array of traffic sources: [overall, STORE_SEARCH, STORE_BROWSE, DEEPLINK, ...]
        #         each: "1"."1"=source_id, "2"."1"=install_count
        #   "2" = conversion summary:
        #         "2"."1"."1" = store_listing_visitors (total)
        #         "2"."2"."1" = installers (total)
        #         "2"."3"."1" = conversion_rate (float)
        # We build a 2-stage funnel from "2" plus the traffic-source breakdown from "1".
        summary = data.get("2", {})
        visitors_val = int(summary.get("1", {}).get("1") or 0)
        installers_val = int(summary.get("2", {}).get("1") or 0)
        conversion_val = float(summary.get("3", {}).get("1") or 0.0)

        stages: list[AcquisitionFunnelStage] = [
            AcquisitionFunnelStage(stage="store_listing_visitors", value=visitors_val, conversion_rate=0.0),
            AcquisitionFunnelStage(stage="installers", value=installers_val, conversion_rate=round(conversion_val, 4)),
        ]

        # Append traffic-source breakdown as additional pseudo-stages (source@installs).
        source_map = {"STORE_SEARCH": "search", "STORE_BROWSE": "explore", "DEEPLINK": "ads_referral"}
        for src_item in data.get("1", []):
            src_id = src_item.get("1", {}).get("1", "")
            src_count = int(src_item.get("2", {}).get("1") or 0)
            if src_id and src_id != "@OVERALL@":
                label = source_map.get(src_id, src_id.lower())
                conv = round(src_count / installers_val, 4) if installers_val > 0 else 0.0
                stages.append(AcquisitionFunnelStage(stage=f"src:{label}", value=src_count, conversion_rate=conv))

        return AcquisitionFunnelResult(
            package_name=package_name,
            start_date=start_date,
            end_date=end_date,
            stages=stages,
        )
