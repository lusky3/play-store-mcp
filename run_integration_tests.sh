#!/bin/bash
# Integration test runner for Play Store MCP Server
# These tests use REAL credentials but only perform READ operations

set -e

echo "=========================================="
echo "Play Store MCP - Integration Tests"
echo "=========================================="
echo ""

# Check if .env.local exists
if [ ! -f .env.local ]; then
    echo "❌ Error: .env.local file not found"
    echo "Please create .env.local with:"
    echo "  export GOOGLE_APPLICATION_CREDENTIALS=\"/path/to/credentials.json\""
    exit 1
fi

# Source credentials
echo "Loading credentials from .env.local..."
source .env.local

# Expand $HOME in the path if present
if [[ "$GOOGLE_APPLICATION_CREDENTIALS" == \$HOME* ]]; then
    GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS/\$HOME/$HOME}"
fi

# Check if credentials file exists
if [ ! -f "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    echo "❌ Error: Credentials file not found: $GOOGLE_APPLICATION_CREDENTIALS"
    exit 1
fi

echo "✓ Credentials file found: $GOOGLE_APPLICATION_CREDENTIALS"
echo ""

# Check if TEST_PACKAGE_NAME is set
if [ -z "$TEST_PACKAGE_NAME" ]; then
    echo "⚠️  Warning: TEST_PACKAGE_NAME not set"
    echo "Some tests will be skipped. To run all tests, set:"
    echo "  export TEST_PACKAGE_NAME=com.your.app.package"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✓ Testing with package: $TEST_PACKAGE_NAME"
fi

echo ""
echo "=========================================="
echo "IMPORTANT: Read-Only Tests"
echo "=========================================="
echo "These tests will:"
echo "  ✓ Read app information"
echo "  ✓ List releases and reviews"
echo "  ✓ Get store listings"
echo "  ✓ Test validation functions"
echo ""
echo "These tests will NOT:"
echo "  ✗ Deploy any apps"
echo "  ✗ Modify releases"
echo "  ✗ Update store listings"
echo "  ✗ Reply to reviews"
echo "  ✗ Make any changes to Play Console"
echo ""
read -p "Proceed with integration tests? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "Running integration tests..."
echo ""

# Run tests
if command -v uv &> /dev/null; then
    uv run pytest tests/test_integration.py -v -s --tb=short
else
    python3 -m pytest tests/test_integration.py -v -s --tb=short
fi

echo ""
echo "=========================================="
echo "Integration Tests Complete"
echo "=========================================="
echo ""
echo "Summary:"
echo "  - All tests used real Google Play API"
echo "  - Only read operations were performed"
echo "  - No changes were made to Play Console"
echo ""
