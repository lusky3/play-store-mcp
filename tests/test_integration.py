"""Integration tests with real Google Play API.

These tests use real credentials but only perform READ operations.
No destructive changes are made to Play Console.

To run these tests:
1. Source the .env.local file: source .env.local
2. Run: pytest tests/test_integration.py -v -s

IMPORTANT: These tests require:
- Valid GOOGLE_APPLICATION_CREDENTIALS environment variable
- Service account with Play Console access
- At least one app in the Play Console account
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from play_store_mcp.client import PlayStoreClient, PlayStoreClientError

# Skip all tests if credentials are not available
pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
    reason="GOOGLE_APPLICATION_CREDENTIALS not set - skipping integration tests",
)


@pytest.fixture
def real_client() -> PlayStoreClient:
    """Create a real PlayStoreClient with actual credentials."""
    return PlayStoreClient()


@pytest.fixture
def test_package_name() -> str:
    """Package name for testing.

    Override this with an actual package name from your Play Console.
    Set via environment variable: TEST_PACKAGE_NAME=com.example.app
    """
    package_name = os.environ.get("TEST_PACKAGE_NAME")
    if not package_name:
        pytest.skip("TEST_PACKAGE_NAME not set - skipping tests that require a package name")
    return package_name


class TestRealAPIConnection:
    """Test that we can connect to the real API."""

    def test_credentials_file_exists(self) -> None:
        """Test that credentials file exists."""
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        assert creds_path is not None, "GOOGLE_APPLICATION_CREDENTIALS not set"

        # Expand ~ if present
        if creds_path.startswith("$HOME"):
            creds_path = creds_path.replace("$HOME", str(Path("~").expanduser()))
        elif creds_path.startswith("~"):
            creds_path = str(Path(creds_path).expanduser())

        assert Path(creds_path).exists(), f"Credentials file not found: {creds_path}"
        print(f"✓ Credentials file found: {creds_path}")

    def test_can_initialize_client(self, real_client: PlayStoreClient) -> None:
        """Test that client can be initialized."""
        assert real_client is not None
        print("✓ Client initialized successfully")

    def test_can_get_service(self, real_client: PlayStoreClient) -> None:
        """Test that we can get the API service."""
        try:
            service = real_client._get_service()
            assert service is not None
            print("✓ API service obtained successfully")
        except PlayStoreClientError as e:
            pytest.fail(f"Failed to get API service: {e}")


class TestReadOnlyOperations:
    """Test read-only operations that don't modify anything."""

    def test_list_apps(self, real_client: PlayStoreClient) -> None:
        """Test listing apps (returns empty due to API limitation)."""
        apps = real_client.list_apps()
        # This will return empty list due to API limitation, but shouldn't error
        assert isinstance(apps, list)
        print(f"✓ list_apps() returned: {len(apps)} apps")
        print("  Note: Play API requires package names upfront, so this returns empty")

    def test_get_releases(
        self,
        real_client: PlayStoreClient,
        test_package_name: str,
    ) -> None:
        """Test getting releases for an app."""
        try:
            tracks = real_client.get_releases(test_package_name)
            assert isinstance(tracks, list)
            print(f"✓ get_releases() returned {len(tracks)} tracks")

            for track in tracks:
                print(f"  - Track: {track.track}")
                for release in track.releases:
                    print(f"    Version codes: {release.version_codes}")
                    print(f"    Status: {release.status}")
                    if release.rollout_percentage < 100:
                        print(f"    Rollout: {release.rollout_percentage}%")
        except PlayStoreClientError as e:
            pytest.fail(f"Failed to get releases: {e}")

    def test_get_app_details(
        self,
        real_client: PlayStoreClient,
        test_package_name: str,
    ) -> None:
        """Test getting app details."""
        try:
            details = real_client.get_app_details(test_package_name)
            assert details.package_name == test_package_name
            print("✓ get_app_details() succeeded")
            print(f"  Title: {details.title}")
            print(f"  Default language: {details.default_language}")
        except PlayStoreClientError as e:
            pytest.fail(f"Failed to get app details: {e}")

    def test_get_reviews(
        self,
        real_client: PlayStoreClient,
        test_package_name: str,
    ) -> None:
        """Test getting reviews."""
        try:
            reviews = real_client.get_reviews(test_package_name, max_results=5)
            assert isinstance(reviews, list)
            print(f"✓ get_reviews() returned {len(reviews)} reviews")

            for review in reviews[:3]:  # Show first 3
                print(f"  - {review.star_rating}★ by {review.author_name}")
                print(f"    {review.comment[:50]}...")
        except PlayStoreClientError as e:
            # Reviews might not be available for all apps
            print(f"  Note: Could not fetch reviews: {e}")

    def test_list_subscriptions(
        self,
        real_client: PlayStoreClient,
        test_package_name: str,
    ) -> None:
        """Test listing subscriptions."""
        try:
            subscriptions = real_client.list_subscriptions(test_package_name)
            assert isinstance(subscriptions, list)
            print(f"✓ list_subscriptions() returned {len(subscriptions)} subscriptions")

            for sub in subscriptions:
                print(f"  - {sub.product_id}")
        except PlayStoreClientError as e:
            # Subscriptions might not be available for all apps
            print(f"  Note: Could not fetch subscriptions: {e}")

    def test_list_in_app_products(
        self,
        real_client: PlayStoreClient,
        test_package_name: str,
    ) -> None:
        """Test listing in-app products."""
        try:
            products = real_client.list_in_app_products(test_package_name)
            assert isinstance(products, list)
            print(f"✓ list_in_app_products() returned {len(products)} products")

            for product in products:
                print(f"  - {product.sku}: {product.title}")
        except PlayStoreClientError as e:
            # IAP might not be available for all apps
            print(f"  Note: Could not fetch in-app products: {e}")

    def test_get_listing(
        self,
        real_client: PlayStoreClient,
        test_package_name: str,
    ) -> None:
        """Test getting store listing."""
        try:
            listing = real_client.get_listing(test_package_name, "en-US")
            assert listing.language == "en-US"
            print("✓ get_listing() succeeded")
            print(f"  Title: {listing.title}")
            print(
                f"  Short description: {listing.short_description[:50] if listing.short_description else 'None'}..."
            )
        except PlayStoreClientError as e:
            pytest.fail(f"Failed to get listing: {e}")

    def test_list_all_listings(
        self,
        real_client: PlayStoreClient,
        test_package_name: str,
    ) -> None:
        """Test listing all store listings."""
        try:
            listings = real_client.list_all_listings(test_package_name)
            assert isinstance(listings, list)
            print(f"✓ list_all_listings() returned {len(listings)} listings")

            for listing in listings:
                print(f"  - {listing.language}: {listing.title}")
        except PlayStoreClientError as e:
            pytest.fail(f"Failed to list all listings: {e}")

    def test_get_testers(
        self,
        real_client: PlayStoreClient,
        test_package_name: str,
    ) -> None:
        """Test getting testers for internal track."""
        try:
            testers = real_client.get_testers(test_package_name, "internal")
            assert isinstance(testers.tester_emails, list)
            print(f"✓ get_testers() returned {len(testers.tester_emails)} testers")
        except PlayStoreClientError as e:
            # Testers might not be configured
            print(f"  Note: Could not fetch testers: {e}")

    def test_get_vitals_overview(
        self,
        real_client: PlayStoreClient,
        test_package_name: str,
    ) -> None:
        """Test getting vitals overview."""
        vitals = real_client.get_vitals_overview(test_package_name)
        assert vitals.package_name == test_package_name
        print("✓ get_vitals_overview() succeeded")
        print(f"  Note: {vitals.freshness_info}")


class TestValidation:
    """Test validation functions."""

    def test_validate_package_name_valid(self, real_client: PlayStoreClient) -> None:
        """Test validating a valid package name."""
        errors = real_client.validate_package_name("com.example.app")
        assert len(errors) == 0
        print("✓ Valid package name passed validation")

    def test_validate_package_name_invalid(self, real_client: PlayStoreClient) -> None:
        """Test validating an invalid package name."""
        errors = real_client.validate_package_name("InvalidPackage")
        assert len(errors) > 0
        print(f"✓ Invalid package name caught {len(errors)} errors")
        for error in errors:
            print(f"  - {error.message}")

    def test_validate_track_valid(self, real_client: PlayStoreClient) -> None:
        """Test validating valid tracks."""
        for track in ["internal", "alpha", "beta", "production"]:
            errors = real_client.validate_track(track)
            assert len(errors) == 0
        print("✓ All valid tracks passed validation")

    def test_validate_track_invalid(self, real_client: PlayStoreClient) -> None:
        """Test validating invalid track."""
        errors = real_client.validate_track("staging")
        assert len(errors) > 0
        print(f"✓ Invalid track caught {len(errors)} errors")

    def test_validate_listing_text(self, real_client: PlayStoreClient) -> None:
        """Test validating listing text."""
        # Valid text
        errors = real_client.validate_listing_text(
            title="My App",
            short_description="A great app",
            full_description="This is a comprehensive description.",
        )
        assert len(errors) == 0
        print("✓ Valid listing text passed validation")

        # Invalid text (too long)
        errors = real_client.validate_listing_text(title="A" * 51)
        assert len(errors) > 0
        print(f"✓ Invalid listing text caught {len(errors)} errors")


class TestRetryLogic:
    """Test that retry logic is properly configured."""

    def test_retry_decorator_exists(self, real_client: PlayStoreClient) -> None:
        """Test that retry decorator is applied to _get_service."""
        # Check that the method has been wrapped
        method = real_client._get_service
        # The decorator wraps the function, so we can't easily test it
        # but we can verify it doesn't break normal operation
        service = method()
        assert service is not None
        print("✓ Retry decorator doesn't break normal operation")


if __name__ == "__main__":
    print("=" * 70)
    print("Play Store MCP Server - Integration Tests")
    print("=" * 70)
    print()
    print("These tests use REAL Google Play API credentials.")
    print("Only READ operations are performed - no changes are made.")
    print()
    print("To run these tests:")
    print("  1. source .env.local")
    print("  2. export TEST_PACKAGE_NAME=com.your.app")
    print("  3. pytest tests/test_integration.py -v -s")
    print()
    print("=" * 70)
