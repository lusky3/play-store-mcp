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

## Environment Variables

| Variable | Description | Required | Default |
|---|---|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON key file | Yes | — |
| `PLAY_STORE_MCP_LOG_LEVEL` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` | No | `INFO` |

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
