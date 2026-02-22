#!/usr/bin/env python3
"""Integration test for the remote credentials feature."""

import subprocess
import sys
import time

import requests


def test_credentials_endpoint():
    """Test the credentials endpoint with a running server."""
    # Start the server in the background
    print("Starting MCP server...")
    process = subprocess.Popen(
        ["play-store-mcp", "--transport", "streamable-http", "--port", "8001"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to start
    time.sleep(2)

    try:
        # Test 1: Missing credentials
        print("\nTest 1: Missing credentials (should fail)")
        response = requests.post(
            "http://localhost:8001/credentials",
            json={},
            timeout=5,
        )
        assert response.status_code == 400
        assert not response.json()["success"]
        print("✓ Test 1 passed")

        # Test 2: Invalid JSON string
        print("\nTest 2: Invalid JSON string (should fail)")
        response = requests.post(
            "http://localhost:8001/credentials",
            json={"credentials": "not valid json"},
            timeout=5,
        )
        assert response.status_code == 400
        assert not response.json()["success"]
        print("✓ Test 2 passed")

        # Test 3: Invalid type
        print("\nTest 3: Invalid type (should fail)")
        response = requests.post(
            "http://localhost:8001/credentials",
            json={"credentials": 123},
            timeout=5,
        )
        assert response.status_code == 400
        assert not response.json()["success"]
        print("✓ Test 3 passed")

        print("\n✓ All integration tests passed!")

    finally:
        # Stop the server
        print("\nStopping server...")
        process.terminate()
        process.wait(timeout=5)


if __name__ == "__main__":
    try:
        test_credentials_endpoint()
    except Exception as e:
        print(f"\n✗ Integration test failed: {e}")
        sys.exit(1)
