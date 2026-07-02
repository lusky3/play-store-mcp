#!/usr/bin/env python3
"""Example script demonstrating how to update credentials remotely via HTTP."""

import json
import os
import sys
from pathlib import Path

import requests


def _auth_headers(token: str | None = None) -> dict[str, str]:
    """Build request headers, adding an admin bearer token when configured.

    Uses the given token or the PLAY_STORE_MCP_ADMIN_TOKEN environment variable,
    matching the server's optional /credentials authentication (required when
    the server is exposed through a reverse proxy).
    """
    token = token or os.environ.get("PLAY_STORE_MCP_ADMIN_TOKEN")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def update_credentials_from_file(
    server_url: str, credentials_path: str, token: str | None = None
) -> None:
    """Update server credentials from a local service account JSON file.

    The /credentials endpoint accepts credential *contents* ("credentials" or
    "credentials_base64"), not a server-side file path, so this loads the file
    locally and sends its contents.

    Args:
        server_url: Base URL of the MCP server (e.g., http://localhost:8000)
        credentials_path: Path to the service account JSON file
        token: Optional admin token (falls back to PLAY_STORE_MCP_ADMIN_TOKEN)
    """
    with Path(credentials_path).open() as f:
        credentials = json.load(f)

    update_credentials_from_json(server_url, credentials, token=token)


def update_credentials_from_json(
    server_url: str, credentials_json: dict, token: str | None = None
) -> None:
    """Update server credentials using a credentials JSON object.

    Args:
        server_url: Base URL of the MCP server (e.g., http://localhost:8000)
        credentials_json: Service account credentials as a dictionary
        token: Optional admin token (falls back to PLAY_STORE_MCP_ADMIN_TOKEN)
    """
    response = requests.post(
        f"{server_url}/credentials",
        json={"credentials": credentials_json},
        headers=_auth_headers(token),
        timeout=10,
    )
    
    if response.status_code == 200:
        print("✓ Credentials updated successfully")
        print(f"  Response: {response.json()}")
    else:
        print(f"✗ Failed to update credentials: {response.status_code}")
        print(f"  Error: {response.json()}")
        sys.exit(1)


def main():
    """Main function."""
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python example_update_credentials.py <server_url> <credentials_file>")
        print()
        print("Example:")
        print("  python example_update_credentials.py http://localhost:8000 /path/to/credentials.json")
        sys.exit(1)
    
    server_url = sys.argv[1]
    credentials_file = sys.argv[2]
    
    print(f"Updating credentials on server: {server_url}")
    print(f"Using credentials file: {credentials_file}")
    print()
    
    # Option 1: Load the file locally and send its contents
    # update_credentials_from_file(server_url, credentials_file)
    
    # Option 2: Send credentials JSON directly (more secure for remote servers)
    with Path(credentials_file).open() as f:
        credentials = json.load(f)
    
    update_credentials_from_json(server_url, credentials)


if __name__ == "__main__":
    main()
