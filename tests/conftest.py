"""Pytest configuration and fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from collections.abc import Generator

import pytest

from play_store_mcp.client import PlayStoreClient


@pytest.fixture
def _mock_credentials() -> Generator[MagicMock, None, None]:
    """Mock Google credentials."""
    with patch(
        "play_store_mcp.client.service_account.Credentials.from_service_account_file"
    ) as mock:
        mock.return_value = MagicMock()
        yield mock


@pytest.fixture
def _mock_service() -> Generator[MagicMock, None, None]:
    """Mock the Google API service."""
    with patch("play_store_mcp.client.build") as mock_build:
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        yield mock_service


@pytest.fixture
def client(
    _mock_credentials: MagicMock,
    _mock_service: MagicMock,
    tmp_path: Any,
) -> PlayStoreClient:
    """Create a PlayStoreClient with mocked dependencies."""
    # Create a fake credentials file
    creds_file = tmp_path / "service-account.json"
    creds_file.write_text('{"type": "service_account"}')

    return PlayStoreClient(credentials_path=str(creds_file))


@pytest.fixture
def sample_track_response() -> dict[str, Any]:
    """Sample response from tracks().list()."""
    return {
        "tracks": [
            {
                "track": "production",
                "releases": [
                    {
                        "status": "completed",
                        "versionCodes": ["100"],
                        "name": "1.0.0",
                        "releaseNotes": [{"language": "en-US", "text": "Initial release"}],
                    }
                ],
            },
            {
                "track": "beta",
                "releases": [
                    {
                        "status": "inProgress",
                        "versionCodes": ["101"],
                        "name": "1.1.0-beta",
                        "userFraction": 0.5,
                        "releaseNotes": [{"language": "en-US", "text": "Beta features"}],
                    }
                ],
            },
        ]
    }


@pytest.fixture
def sample_reviews_response() -> dict[str, Any]:
    """Sample response from reviews().list()."""
    return {
        "reviews": [
            {
                "reviewId": "review-123",
                "authorName": "Test User",
                "comments": [
                    {
                        "userComment": {
                            "starRating": 5,
                            "text": "Great app!",
                            "reviewerLanguage": "en",
                            "device": "Pixel 6",
                            "androidOsVersion": "13",
                            "appVersionCode": 100,
                            "appVersionName": "1.0.0",
                        }
                    }
                ],
            },
            {
                "reviewId": "review-456",
                "authorName": "Another User",
                "comments": [
                    {
                        "userComment": {
                            "starRating": 3,
                            "text": "Needs improvement",
                            "reviewerLanguage": "en",
                        }
                    },
                    {
                        "developerComment": {
                            "text": "Thanks for the feedback!",
                        }
                    },
                ],
            },
        ]
    }


@pytest.fixture
def sample_subscriptions_response() -> dict[str, Any]:
    """Sample response from monetization().subscriptions().list()."""
    return {
        "subscriptions": [
            {
                "productId": "premium_monthly",
                "basePlans": [
                    {
                        "basePlanId": "monthly",
                        "state": "ACTIVE",
                    }
                ],
            },
            {
                "productId": "premium_yearly",
                "basePlans": [
                    {
                        "basePlanId": "yearly",
                        "state": "ACTIVE",
                    }
                ],
            },
        ]
    }
