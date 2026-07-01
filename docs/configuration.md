# Configuration

## MCP Client Setup

=== "Claude Desktop"

    Add to your `claude_desktop_config.json`:

    ```json
    {
      "mcpServers": {
        "play-store": {
          "command": "uvx",
          "args": ["play-store-mcp"],
          "env": {
            "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json"
          }
        }
      }
    }
    ```

=== "Kiro"

    Add to `.kiro/settings/mcp.json`:

    ```json
    {
      "mcpServers": {
        "play-store": {
          "command": "uvx",
          "args": ["play-store-mcp"],
          "env": {
            "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json"
          }
        }
      }
    }
    ```

=== "Gemini CLI / Other"

    Most MCP clients use the same configuration format:

    ```json
    {
      "mcpServers": {
        "play-store": {
          "command": "uvx",
          "args": ["play-store-mcp"],
          "env": {
            "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json"
          }
        }
      }
    }
    ```

## Docker

```bash
docker run -e GOOGLE_APPLICATION_CREDENTIALS=/creds/key.json \
  -v /path/to/service-account.json:/creds/key.json:ro \
  ghcr.io/lusky3/play-store-mcp:latest
```

For HTTP transport with Docker:

```bash
docker run -p 8000:8000 \
  -e GOOGLE_APPLICATION_CREDENTIALS=/creds/key.json \
  -v /path/to/service-account.json:/creds/key.json:ro \
  ghcr.io/lusky3/play-store-mcp:latest \
  --transport streamable-http --host 0.0.0.0 --port 8000
```

## Environment Variables

| Variable | Description | Required | Default |
|---|---|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON key file | Yes (or use per-request credentials) | — |
| `GOOGLE_PLAY_STORE_CREDENTIALS` | Inline JSON credentials string | Alternative to file path | — |
| `PLAY_STORE_MCP_LOG_LEVEL` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` | No | `INFO` |
| `PLAY_STORE_MCP_DISABLE_DNS_REBINDING` | Disable DNS rebinding protection (for cloud/reverse-proxy deployments) | No | — |
| `PLAY_STORE_MCP_READ_ONLY` | Disable all write operations | No | — |

## HTTP Transport

For remote access or public deployments:

```bash
play-store-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

The server exposes a `/health` endpoint for monitoring.

See [Remote Credentials](remote-credentials.md) for per-request credential configuration.

## Per-Request Credentials

For multi-tenant deployments, clients can pass their own Google service account credentials on each request via HTTP headers. This is the primary mechanism for public instances where each user brings their own credentials.

| Header | Description |
|---|---|
| `X-Google-Credentials-Base64` | Base64-encoded service account JSON key (recommended) |
| `X-Google-Credentials` | Raw JSON service account key string |

To encode your credentials:

```bash
base64 -w 0 < service-account.json
```

Configure your MCP client to send the header:

```json
{
  "mcpServers": {
    "play-store": {
      "url": "https://your-server.com/mcp",
      "transport": "http",
      "headers": {
        "X-Google-Credentials-Base64": "YOUR_BASE64_ENCODED_CREDENTIALS"
      }
    }
  }
}
```

Per-request credentials are isolated — each request uses only the credentials provided in its headers. No credentials are stored server-side or shared between requests.

## Read-Only Mode

Enable read-only mode to guarantee the server performs no writes against the Play Developer API — useful for demos, audits, or pointing at a production app. When active, every write tool (`deploy_app`, `deploy_app_multilang`, `promote_release`, `halt_release`, `update_rollout`, `reply_to_review`, `update_listing`, `update_testers`, `batch_deploy`) returns an error and never contacts the API; all read and validation tools work normally.

Enable it with the CLI flag:

```bash
play-store-mcp --read-only
```

Or the environment variable (truthy values: `1`, `true`, `yes`, `on`):

```bash
export PLAY_STORE_MCP_READ_ONLY=1
```

## Logging

Logs are written to stderr (stdout is reserved for MCP JSON-RPC communication). The server uses `structlog` for structured logging.

To enable debug logging:

```bash
export PLAY_STORE_MCP_LOG_LEVEL=DEBUG
```

Or set it in your MCP client config:

```json
{
  "mcpServers": {
    "play-store": {
      "command": "uvx",
      "args": ["play-store-mcp"],
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json",
        "PLAY_STORE_MCP_LOG_LEVEL": "DEBUG"
      }
    }
  }
}
```

## Retry Behavior

The client automatically retries failed API calls with exponential backoff:

- Retries on HTTP 429 (rate limit), 500, and 503 errors
- Maximum 3 retries per request
- Backoff starts at 1 second, doubles each retry (max 32 seconds)
- Random jitter is added to prevent thundering herd

## Docker Environment Variables

When running in Docker, the following additional environment variables control the MCP transport:

| Variable | Description | Default |
|---|---|---|
| `MCP_TRANSPORT` | Transport mode: `stdio`, `sse`, or `streamable-http` | `stdio` |
| `MCP_HOST` | Host address to bind to | `0.0.0.0` |
| `MCP_PORT` | Port to listen on | `8000` |

Note: `MCP_HOST` and `MCP_PORT` only apply when using a network transport (`streamable-http` or `sse`). The Dockerfile defaults to `stdio`.
