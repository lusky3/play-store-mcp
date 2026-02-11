#!/bin/bash
# Test runner script for Play Store MCP Server

set -e

# Ensure we're running from the project root
cd "$(dirname "$0")/.."

echo "=== Play Store MCP Server Test Suite ==="
echo ""

# Check if uv is available
if command -v uv &> /dev/null; then
    echo "✓ Using uv to run tests"
    uv run pytest tests/ -v --tb=short --cov=src/play_store_mcp --cov-report=term-missing
elif [ -f .venv/bin/python ]; then
    echo "✓ Using virtual environment"
    .venv/bin/python -m pytest tests/ -v --tb=short --cov=src/play_store_mcp --cov-report=term-missing
else
    echo "✗ Neither uv nor virtual environment found"
    echo "Please run: uv sync --extra dev"
    exit 1
fi

echo ""
echo "=== Test Summary ==="
echo "All tests use mocked Google Play API - no live changes are made"
echo "Tests verify:"
echo "  - API client methods work correctly with mocked responses"
echo "  - MCP server tools are properly defined"
echo "  - Data models validate correctly"
echo "  - Error handling works as expected"
echo "  - Validation logic catches invalid inputs"
