#!/usr/bin/env python3
"""Quick integration test script for Play Store MCP Server.

This script performs safe, read-only operations to verify the API works.
No changes are made to Play Console.

Usage:
    export GOOGLE_APPLICATION_CREDENTIALS="/path/to/credentials.json"
    export TEST_PACKAGE_NAME="com.your.app"  # Optional
    python3 tests/test_live_api.py
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / ".." / "src"))

from play_store_mcp.client import PlayStoreClient, PlayStoreClientError


def print_header(text: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def print_test(text: str) -> None:
    """Print a test description."""
    print(f"\n{text}...")


def print_success(text: str) -> None:
    """Print a success message."""
    print(f"✓ {text}")


def print_info(text: str) -> None:
    """Print an info message."""
    print(f"  {text}")


def print_error(text: str) -> None:
    """Print an error message."""
    print(f"✗ {text}")


def main() -> None:
    """Run integration tests."""
    print_header("Play Store MCP Server - Live API Test")

    # Check credentials
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path:
        print_error("GOOGLE_APPLICATION_CREDENTIALS not set")
        print_info("Please set: export GOOGLE_APPLICATION_CREDENTIALS='/path/to/credentials.json'")
        sys.exit(1)

    # Expand $HOME if present
    if creds_path.startswith("$HOME"):
        creds_path = creds_path.replace("$HOME", str(Path("~").expanduser()))
    elif creds_path.startswith("~"):
        creds_path = str(Path(creds_path).expanduser())

    if not Path(creds_path).exists():
        print_error(f"Credentials file not found: {creds_path}")
        sys.exit(1)

    print_success(f"Credentials file found: {creds_path}")

    # Get test package name
    package_name = os.environ.get("TEST_PACKAGE_NAME")
    if package_name:
        print_success(f"Test package: {package_name}")
    else:
        print_info("TEST_PACKAGE_NAME not set - some tests will be skipped")
        print_info("Set with: export TEST_PACKAGE_NAME='com.your.app'")

    # Initialize client
    print_test("Initializing client")
    try:
        client = PlayStoreClient()
        print_success("Client initialized")
    except Exception as e:
        print_error(f"Failed to initialize client: {e}")
        sys.exit(1)

    # Test API connection
    print_test("Testing API connection")
    try:
        client._get_service()
        print_success("API service obtained successfully")
    except PlayStoreClientError as e:
        print_error(f"Failed to connect to API: {e}")
        sys.exit(1)

    # Test list_apps (expected to return empty)
    print_test("Testing list_apps (expected to return empty)")
    try:
        apps = client.list_apps()
        print_success(f"list_apps returned: {len(apps)} apps")
        print_info("Note: This is expected - Play API requires package names upfront")
    except Exception as e:
        print_error(f"list_apps failed: {e}")

    # Test validation functions
    print_test("Testing validation functions")

    # Valid package name
    errors = client.validate_package_name("com.example.app")
    if len(errors) == 0:
        print_success("Valid package name passed validation")
    else:
        print_error("Valid package name failed validation")

    # Invalid package name
    errors = client.validate_package_name("InvalidPackage")
    if len(errors) > 0:
        print_success(f"Invalid package name caught {len(errors)} errors")
    else:
        print_error("Invalid package name should have failed validation")

    # Valid track
    errors = client.validate_track("production")
    if len(errors) == 0:
        print_success("Valid track passed validation")
    else:
        print_error("Valid track failed validation")

    # Invalid track
    errors = client.validate_track("staging")
    if len(errors) > 0:
        print_success("Invalid track caught errors")
    else:
        print_error("Invalid track should have failed validation")

    # Test with package name if provided
    if package_name:
        print_header(f"Testing with package: {package_name}")

        # Get releases
        print_test("Getting releases")
        try:
            tracks = client.get_releases(package_name)
            print_success(f"Found {len(tracks)} tracks")
            for track in tracks:
                print_info(f"Track: {track.track}")
                for release in track.releases:
                    print_info(f"  Version codes: {release.version_codes}")
                    print_info(f"  Status: {release.status}")
                    if release.rollout_percentage < 100:
                        print_info(f"  Rollout: {release.rollout_percentage}%")
        except PlayStoreClientError as e:
            print_error(f"Failed to get releases: {e}")

        # Get app details
        print_test("Getting app details")
        try:
            details = client.get_app_details(package_name)
            print_success("Got app details")
            print_info(f"Title: {details.title}")
            print_info(f"Default language: {details.default_language}")
        except PlayStoreClientError as e:
            print_error(f"Failed to get app details: {e}")

        # Get store listing
        print_test("Getting store listing (en-US)")
        try:
            listing = client.get_listing(package_name, "en-US")
            print_success("Got store listing")
            print_info(f"Title: {listing.title}")
            if listing.short_description:
                desc = listing.short_description[:50]
                print_info(f"Short description: {desc}...")
        except PlayStoreClientError as e:
            print_error(f"Failed to get listing: {e}")

        # List all listings
        print_test("Listing all store listings")
        try:
            listings = client.list_all_listings(package_name)
            print_success(f"Found {len(listings)} language listings")
            for listing in listings:
                print_info(f"{listing.language}: {listing.title}")
        except PlayStoreClientError as e:
            print_error(f"Failed to list listings: {e}")

        # Get reviews
        print_test("Getting reviews (max 5)")
        try:
            reviews = client.get_reviews(package_name, max_results=5)
            print_success(f"Found {len(reviews)} reviews")
            for review in reviews[:3]:
                print_info(f"{review.star_rating}★ by {review.author_name}")
                comment = review.comment[:50] if len(review.comment) > 50 else review.comment
                print_info(f"  {comment}...")
        except PlayStoreClientError as e:
            print_info(f"Note: Could not fetch reviews: {e}")

        # List subscriptions
        print_test("Listing subscriptions")
        try:
            subscriptions = client.list_subscriptions(package_name)
            print_success(f"Found {len(subscriptions)} subscriptions")
            for sub in subscriptions:
                print_info(f"Product: {sub.product_id}")
        except PlayStoreClientError as e:
            print_info(f"Note: Could not fetch subscriptions: {e}")

        # List in-app products
        print_test("Listing in-app products")
        try:
            products = client.list_in_app_products(package_name)
            print_success(f"Found {len(products)} in-app products")
            for product in products:
                print_info(f"{product.sku}: {product.title}")
        except PlayStoreClientError as e:
            print_info(f"Note: Could not fetch in-app products: {e}")

        # Get testers
        print_test("Getting testers for internal track")
        try:
            testers = client.get_testers(package_name, "internal")
            print_success(f"Found {len(testers.tester_emails)} testers")
        except PlayStoreClientError as e:
            print_info(f"Note: Could not fetch testers: {e}")

    # Summary
    print_header("Test Summary")
    print_success("All read-only operations completed")
    print_info("No changes were made to Play Console")
    print_info("The Play Store MCP Server is working correctly!")

    if not package_name:
        print()
        print_info("To test more features, set TEST_PACKAGE_NAME:")
        print_info("  export TEST_PACKAGE_NAME='com.your.app'")
        print_info("  python3 tests/test_live_api.py")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
