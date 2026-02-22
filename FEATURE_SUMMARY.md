# Remote Credentials Feature

## Summary

Added the ability for the streamable HTTP/MCP server to accept JSON file credentials remotely via a new `/credentials` HTTP endpoint. This allows dynamic credential updates without server restarts.

## Changes Made

### 1. Server Implementation (`src/play_store_mcp/server.py`)

- Added imports for `json`, `Request`, and `JSONResponse` from Starlette
- Modified `lifespan` context manager to store shared state in the server instance
- Added new `/credentials` POST endpoint that accepts credentials in three formats:
  - JSON object: `{"credentials": {...}}`
  - JSON string: `{"credentials": "..."}`
  - File path: `{"credentials_path": "..."}`
- Endpoint validates credentials before accepting them
- Returns appropriate HTTP status codes (200, 400, 401, 500)

### 2. Documentation

- Updated `README.md` with:
  - Section on running with HTTP transport
  - Instructions for providing credentials remotely
  - Example curl commands for all three credential formats
  - Response code documentation

- Created `docs/remote-credentials.md` with:
  - Comprehensive usage guide
  - Security considerations
  - Python examples
  - Troubleshooting section
  - nginx authentication example

### 3. Tests (`tests/test_credentials_endpoint.py`)

- Created comprehensive test suite with 8 test cases:
  - Test credentials with JSON object
  - Test credentials with JSON string
  - Test credentials with file path
  - Test missing credentials error
  - Test invalid JSON string error
  - Test invalid type error
  - Test invalid credentials error
  - Test malformed request error

### 4. Examples (`examples/update_credentials.py`)

- Created example Python script demonstrating:
  - How to update credentials from a file
  - How to update credentials from JSON
  - Command-line usage
  - Error handling

## Usage

### Start Server

```bash
play-store-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

### Update Credentials

```bash
# Using JSON object
curl -X POST http://localhost:8000/credentials \
  -H "Content-Type: application/json" \
  -d '{"credentials": {...}}'

# Using JSON string
curl -X POST http://localhost:8000/credentials \
  -H "Content-Type: application/json" \
  -d '{"credentials": "{...}"}'

# Using file path
curl -X POST http://localhost:8000/credentials \
  -H "Content-Type: application/json" \
  -d '{"credentials_path": "/path/to/credentials.json"}'
```

## Benefits

1. **No Downtime**: Update credentials without restarting the server
2. **Multi-Tenant**: Support multiple clients with different service accounts
3. **Remote Deployment**: Update credentials on remote servers without file access
4. **Testing**: Easily switch between test and production accounts
5. **Security**: Credentials can be sent over HTTPS without file system access

## Security Considerations

- Always use HTTPS in production
- Add authentication via reverse proxy
- Run in private network or use VPN
- Regularly rotate credentials
- Monitor credential update requests

## Testing

All tests pass:

```bash
pytest tests/test_credentials_endpoint.py -v
# 8 passed in 0.05s
```

Existing tests still pass:

```bash
pytest tests/test_server.py -v
# 2 passed in 0.01s
```
