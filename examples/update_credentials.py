#!/usr/bin/env python3
"""Example script demonstrating how to update credentials remotely via HTTP."""

import json
import sys

import requests


def update_credentials_from_file(server_url: str, credentials_path: str) -> None:
    """Update server credentials using a credentials file path.
    
    Args:
        server_url: Base URL of the MCP server (e.g., http://localhost:8000)
        credentials_path: Path to the service account JSON file
    """
    response = requests.post(
        f"{server_url}/credentials",
        json={"credentials_path": credentials_path},
        timeout=10,
    )
    
    if response.status_code == 200:
        print("✓ Credentials updated successfully")
        print(f"  Response: {response.json()}")
    else:
        print(f"✗ Failed to update credentials: {response.status_code}")
        print(f"  Error: {response.json()}")
        sys.exit(1)


def update_credentials_from_json(server_url: str, credentials_json: dict) -> None:
    """Update server credentials using a credentials JSON object.
    
    Args:
        server_url: Base URL of the MCP server (e.g., http://localhost:8000)
        credentials_json: Service account credentials as a dictionary
    """
    response = requests.post(
        f"{server_url}/credentials",
        json={"credentials": credentials_json},
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
    
    # Option 1: Send file path (server must have access to the file)
    # update_credentials_from_file(server_url, credentials_file)
    
    # Option 2: Send credentials JSON directly (more secure for remote servers)
    with open(credentials_file) as f:
        credentials = json.load(f)
    
    update_credentials_from_json(server_url, credentials)


if __name__ == "__main__":
    main()
