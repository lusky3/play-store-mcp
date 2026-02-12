# Troubleshooting

Common errors and how to resolve them.

## Authentication Errors

### "No credentials provided"

```
PlayStoreClientError: No credentials provided. Set GOOGLE_APPLICATION_CREDENTIALS
environment variable or pass credentials_path.
```

!!! success "Fix"
    Set the environment variable pointing to your service account JSON key:

    ```bash
    export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
    ```

    Make sure this is set in your MCP client configuration's `env` block as well.

### "Credentials file not found"

```
PlayStoreClientError: Credentials file not found: /path/to/key.json
```

!!! success "Fix"
    Verify the file exists and the path is correct:

    ```bash
    ls -la $GOOGLE_APPLICATION_CREDENTIALS
    ```

### "The caller does not have permission"

!!! success "Fix"
    1. Go to [Play Console](https://play.google.com/console/) → **Users and permissions**
    2. Find the service account email
    3. Grant the required permissions (see [Getting Started](getting-started.md#2-grant-play-console-access))

---

## API Errors

### "Package name not found"

The app doesn't exist in Play Console, or the service account doesn't have access to it.

!!! success "Fix"
    - Verify the package name is correct (use `validate_package_name` to check format)
    - Ensure the app exists in Play Console
    - Confirm the service account has access to the app

### "File not found"

```
File not found: /path/to/app.aab
```

!!! success "Fix"
    Provide the absolute path to the APK or AAB file. Relative paths may not resolve correctly in the MCP server context.

### Rate Limiting (HTTP 429)

The server automatically retries with exponential backoff on rate limit errors. If you're hitting limits frequently:

- Space out batch operations
- Reduce `max_results` on list operations
- The server retries up to 3 times with increasing delays

### Server Errors (HTTP 500/503)

Transient Google API errors. The server retries automatically. If persistent:

- Check [Google Cloud Status](https://status.cloud.google.com/) for outages
- Try again after a few minutes

---

## Additional Tools

### get_order

Get detailed order/transaction information.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `order_id` | string | Yes | Order ID to retrieve |

```python
get_order("com.example.myapp", order_id="GPA.1234-5678-9012")
```

Returns: `order_id`, `product_id`, `purchase_time`, `purchase_state`, `purchase_token`, `quantity`

### get_expansion_file

Get APK expansion file information. Used for large apps (especially games) exceeding the 100MB APK limit.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `version_code` | int | Yes | — | APK version code |
| `expansion_file_type` | string | No | `main` | `main` or `patch` |

```python
get_expansion_file("com.example.myapp", version_code=42, expansion_file_type="main")
```

Returns: `version_code`, `expansion_file_type`, `file_size`, `references_version`

---

## Debug Logging

Enable debug logging for more detailed output:

```bash
export PLAY_STORE_MCP_LOG_LEVEL=DEBUG
```

Logs are written to stderr and include structured information about API calls, retries, and errors.

---

## Getting Help

- [Open a bug report](https://github.com/lusky3/play-store-mcp/issues/new?template=bug_report.yml)
- [Request a feature](https://github.com/lusky3/play-store-mcp/issues/new?template=feature_request.yml)
- [Security issues](https://github.com/lusky3/play-store-mcp/security/advisories/new) — report privately
