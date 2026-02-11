"""Google Play Developer API client."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from play_store_mcp.models import (
    AppDetails,
    AppInfo,
    DeploymentResult,
    InAppProduct,
    Release,
    Review,
    ReviewReplyResult,
    SubscriptionProduct,
    SubscriptionPurchase,
    TrackInfo,
    VitalsMetric,
    VitalsOverview,
    VoidedPurchase,
)

if TYPE_CHECKING:
    from googleapiclient._apis.androidpublisher.v3 import AndroidPublisherResource

logger = structlog.get_logger(__name__)

# API scopes required for Play Developer API
SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]


class PlayStoreClientError(Exception):
    """Base exception for Play Store client errors."""

    pass


class PlayStoreClient:
    """Client for interacting with Google Play Developer API."""

    def __init__(
        self,
        credentials_path: str | None = None,
        application_name: str = "Play Store MCP Server",
    ) -> None:
        """Initialize the Play Store client.

        Args:
            credentials_path: Path to service account JSON key.
                             Defaults to GOOGLE_APPLICATION_CREDENTIALS env var.
            application_name: Application name for API requests.
        """
        self._credentials_path = credentials_path or os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )
        self._application_name = application_name
        self._service: AndroidPublisherResource | None = None
        self._logger = logger.bind(component="PlayStoreClient")

    def _get_service(self) -> AndroidPublisherResource:
        """Get or create the API service instance."""
        if self._service is not None:
            return self._service

        if not self._credentials_path:
            raise PlayStoreClientError(
                "No credentials provided. Set GOOGLE_APPLICATION_CREDENTIALS "
                "environment variable or pass credentials_path."
            )

        creds_path = Path(self._credentials_path)
        if not creds_path.exists():
            raise PlayStoreClientError(f"Credentials file not found: {self._credentials_path}")

        self._logger.info("Initializing Google Play Developer API client")

        try:
            credentials = service_account.Credentials.from_service_account_file(
                str(creds_path), scopes=SCOPES
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
            self._logger.error("Failed to initialize API client", error=str(e))
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
                        {"language": lang, "text": text}
                        for lang, text in release_notes.items()
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
            self._logger.error("Deployment failed", error=str(e))
            self._delete_edit(package_name, edit_id)
            return DeploymentResult(
                success=False,
                package_name=package_name,
                track=track,
                message=f"Deployment failed: {e.reason}",
                error=str(e),
            )
        except Exception as e:
            self._logger.error("Deployment failed", error=str(e))
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
            self._logger.error("Promotion failed", error=str(e))
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
            self._logger.error("Promotion failed", error=str(e))
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
            self._logger.error("Halt failed", error=str(e))
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
            self._logger.error("Halt failed", error=str(e))
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
            self._logger.error("Rollout update failed", error=str(e))
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
            self._logger.error("Rollout update failed", error=str(e))
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
                developer_name=details.get("contactWebsite"),
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
                            android_version=user_comment.get("androidOsVersion"),
                            app_version_code=user_comment.get("appVersionCode"),
                            app_version_name=user_comment.get("appVersionName"),
                            developer_reply=dev_comment.get("text") if dev_comment else None,
                        )
                    )

            return reviews

        except HttpError as e:
            self._logger.error("Failed to fetch reviews", error=str(e))
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
            self._logger.error("Failed to reply to review", error=str(e))
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

            subscriptions: list[SubscriptionProduct] = []
            for sub_data in result.get("subscriptions", []):
                subscriptions.append(
                    SubscriptionProduct(
                        product_id=sub_data.get("productId", ""),
                        package_name=package_name,
                        base_plans=sub_data.get("basePlans", []),
                    )
                )

            return subscriptions

        except HttpError as e:
            self._logger.error("Failed to list subscriptions", error=str(e))
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
            self._logger.error("Failed to get subscription status", error=str(e))
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

            voided: list[VoidedPurchase] = []
            for purchase in result.get("voidedPurchases", []):
                voided.append(
                    VoidedPurchase(
                        package_name=package_name,
                        purchase_token=purchase.get("purchaseToken", ""),
                        order_id=purchase.get("orderId"),
                        voided_reason=purchase.get("voidedReason"),
                        voided_source=purchase.get("voidedSource"),
                    )
                )

            return voided

        except HttpError as e:
            self._logger.error("Failed to list voided purchases", error=str(e))
            raise PlayStoreClientError(f"Failed to list voided purchases: {e.reason}") from e

    # =========================================================================
    # Vitals API
    # =========================================================================

    def get_vitals_overview(self, package_name: str) -> VitalsOverview:
        """Get Android Vitals overview.

        Note: The full Vitals API requires additional setup.
        This provides a basic overview structure.

        Args:
            package_name: App package name.

        Returns:
            Vitals overview (may be partial without full API access).
        """
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

        Note: Full implementation requires Play Developer Reporting API setup.
        This is a placeholder implementation.

        Args:
            package_name: App package name.
            metric_type: Type of metric (crashRate, anrRate, etc.).

        Returns:
            List of vitals metrics (placeholder).
        """
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

            products: list[InAppProduct] = []
            for product_data in result.get("inappproduct", []):
                # Get default price if available
                default_price = None
                if "defaultPrice" in product_data:
                    default_price = product_data["defaultPrice"]

                # Get localized listings
                listings = product_data.get("listings", {})
                default_listing = listings.get(
                    product_data.get("defaultLanguage", "en-US"), {}
                )

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
            self._logger.error("Failed to list in-app products", error=str(e))
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
            product_data = (
                service.inappproducts().get(packageName=package_name, sku=sku).execute()
            )

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
            self._logger.error("Failed to get in-app product", error=str(e))
            raise PlayStoreClientError(f"Failed to get in-app product: {e.reason}") from e
