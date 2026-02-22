## Remote Credentials Management

When running the Play Store MCP server with `streamable-http` transport, you can dynamically update credentials without restarting the server. This is useful for:

- Multi-tenant deployments where different clients use different service accounts
- Rotating credentials without downtime
- Testing with different accounts
- Remote server deployments where file access is restricted

### Starting the Server

Start the server with HTTP transport:

```bash
play-store-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

Or with environment variables:

```bash
export MCP_TRANSPORT=streamable-http
export MCP_HOST=0.0.0.0
export MCP_PORT=8000
play-store-mcp
```

### Updating Credentials

The server exposes a `/credentials` endpoint that accepts POST requests with credentials in various formats.

#### Method 1: Send Credentials JSON Object

Send the service account credentials directly as a JSON object:

```bash
curl -X POST http://localhost:8000/credentials \
  -H "Content-Type: application/json" \
  -d '{
    "credentials": {
      "type": "service_account",
      "project_id": "your-project-id",
      "private_key_id": "your-key-id",
      "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
      "client_email": "your-service-account@your-project.iam.gserviceaccount.com",
      "client_id": "123456789",
      "auth_uri": "https://accounts.google.com/o/oauth2/auth",
      "token_uri": "https://oauth2.googleapis.com/token",
      "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
      "client_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs/your-service-account"
    }
  }'
```

#### Method 2: Send Credentials JSON String

Send the credentials as a JSON string:

```bash
CREDS=$(cat /path/to/service-account.json | jq -c .)
curl -X POST http://localhost:8000/credentials \
  -H "Content-Type: application/json" \
  -d "{\"credentials\": \"$CREDS\"}"
```

#### Method 3: Send Base64-Encoded Credentials

Send the credentials as a base64-encoded string (useful for environment variables):

```bash
CREDS_B64=$(cat /path/to/service-account.json | base64 -w 0)
curl -X POST http://localhost:8000/credentials \
  -H "Content-Type: application/json" \
  -d "{\"credentials_base64\": \"$CREDS_B64\"}"
```

#### Method 4: Send File Path

If the server has access to the credentials file, you can send just the path:

```bash
curl -X POST http://localhost:8000/credentials \
  -H "Content-Type: application/json" \
  -d '{"credentials_path": "/path/to/service-account.json"}'
```

### Response Codes

- `200 OK`: Credentials updated successfully
- `400 Bad Request`: Invalid request format or malformed JSON
- `401 Unauthorized`: Credentials are invalid or cannot be authenticated
- `500 Internal Server Error`: Server error during credential update

### Success Response

```json
{
  "success": true,
  "message": "Credentials updated successfully"
}
```

### Error Response

```json
{
  "success": false,
  "error": "Error description"
}
```

### Python Example

```python
import json
import requests

# Load credentials from file
with open('/path/to/service-account.json') as f:
    credentials = json.load(f)

# Update server credentials
response = requests.post(
    'http://localhost:8000/credentials',
    json={'credentials': credentials}
)

if response.status_code == 200:
    print("Credentials updated successfully")
else:
    print(f"Error: {response.json()['error']}")
```

### Security Considerations

1. **Use HTTPS in production**: Always use HTTPS when sending credentials over the network
2. **Restrict endpoint access**: Use a reverse proxy (nginx, Apache) to add authentication
3. **Network isolation**: Run the server in a private network or use VPN
4. **Credential rotation**: Regularly rotate service account keys
5. **Audit logging**: Monitor credential update requests

### Example with Authentication

Use a reverse proxy like nginx to add basic authentication:

```nginx
location /credentials {
    auth_basic "Restricted";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass http://localhost:8000;
}
```

Then update credentials with authentication:

```bash
curl -X POST https://your-server.com/credentials \
  -u username:password \
  -H "Content-Type: application/json" \
  -d @credentials.json
```

### Troubleshooting

**Error: "Missing 'credentials' or 'credentials_path' in request body"**
- Ensure your request includes either `credentials` or `credentials_path` field

**Error: "Invalid JSON in credentials string"**
- Verify the credentials JSON is properly formatted
- Use `jq` to validate: `cat credentials.json | jq .`

**Error: "Invalid credentials"**
- Verify the service account has the necessary permissions
- Check that the credentials file is not corrupted
- Ensure the service account is enabled in Google Cloud Console

**Error: "credentials must be a string or object"**
- The `credentials` field must be either a JSON object or a JSON string
- Don't send other types like numbers or arrays
