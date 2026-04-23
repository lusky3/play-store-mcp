#!/usr/bin/env python3
"""Integration test for the remote credentials feature."""

import socket
import subprocess
import sys
import time

import requests


def _find_free_port() -> int:
    """Find a free port by binding to port 0."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(host: str, port: int, timeout: float = 10.0) -> None:
    """Poll until the server is accepting connections, or raise on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"Server on {host}:{port} not ready after {timeout}s")


def test_credentials_endpoint():
    """Test the credentials endpoint with a running server."""
    port = _find_free_port()
    host = "127.0.0.1"

    # Start the server in the background
    print(f"Starting MCP server on port {port}...")
    process = subprocess.Popen(  # noqa: S603
        ["play-store-mcp", "--transport", "streamable-http", "--host", host, "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        _wait_for_server(host, port)

        base_url = f"http://{host}:{port}"

        # Test 1: Missing credentials
        print("\nTest 1: Missing credentials (should fail)")
        response = requests.post(
            f"{base_url}/credentials",
            json={},
            timeout=5,
        )
        assert response.status_code == 400
        assert not response.json()["success"]
        print("✓ Test 1 passed")

        # Test 2: Invalid JSON string
        print("\nTest 2: Invalid JSON string (should fail)")
        response = requests.post(
            f"{base_url}/credentials",
            json={"credentials": "not valid json"},
            timeout=5,
        )
        assert response.status_code == 400
        assert not response.json()["success"]
        print("✓ Test 2 passed")

        # Test 3: Invalid type
        print("\nTest 3: Invalid type (should fail)")
        response = requests.post(
            f"{base_url}/credentials",
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
