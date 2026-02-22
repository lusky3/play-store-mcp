# Play Store MCP Server

[![CI](https://github.com/lusky3/play-store-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/lusky3/play-store-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/github/lusky3/play-store-mcp/graph/badge.svg?token=iDdVHHp5Jw)](https://codecov.io/github/lusky3/play-store-mcp)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=lusky3_play-store-mcp&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=lusky3_play-store-mcp)
[![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=lusky3_play-store-mcp&metric=reliability_rating)](https://sonarcloud.io/summary/new_code?id=lusky3_play-store-mcp)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=lusky3_play-store-mcp&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=lusky3_play-store-mcp)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=lusky3_play-store-mcp&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=lusky3_play-store-mcp)

[![PyPI version](https://badge.fury.io/py/play-store-mcp.svg)](https://badge.fury.io/py/play-store-mcp)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Lines of Code](https://sonarcloud.io/api/project_badges/measure?project=lusky3_play-store-mcp&metric=ncloc)](https://sonarcloud.io/summary/new_code?id=lusky3_play-store-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An MCP (Model Context Protocol) server that connects to the Google Play Developer API. Deploy apps, manage releases, respond to reviews, and monitor app health - all through your AI assistant.

## ✨ Features

- **🚀 App Deployment**: Deploy APK/AAB files to any track (internal, alpha, beta, production)
- **Batch Operations**: Deploy to multiple tracks simultaneously
- **Multi-Language Support**: Deploy with release notes in multiple languages
- **Input Validation**: Validate package names, tracks, and text before API calls
- **Automatic Retries**: Built-in retry logic with exponential backoff for transient failures
- **Store Listings**: Update app titles, descriptions, and videos for any language
- **Release Management**: Promote releases between tracks, manage staged rollouts
- **Tester Management**: Add and manage testers for testing tracks
- **Review Management**: Fetch and reply to user reviews
- **Android Vitals**: Monitor crashes, ANRs, and app health metrics
- **Subscription Management**: List subscriptions and check purchase status
- **In-App Products**: List and manage in-app products
- **Expansion Files**: Manage APK expansion files for large apps
- **Orders**: Retrieve detailed transaction information
- **Secure**: Uses Google Cloud service account authentication

## 🚀 Quick Start

### Prerequisites

1. **Google Cloud Project** with the Google Play Developer API enabled
2. **Service Account** with access to your Play Console
3. **Python 3.11+** or `uvx` installed

### Installation

#### Using uvx (Recommended)

```bash
# Run directly without installation
uvx play-store-mcp
```

#### Using pip

```bash
pip install play-store-mcp
play-store-mcp
```

#### From source

```bash
git clone https://github.com/lusky3/play-store-mcp.git
cd play-store-mcp
pip install -e .
play-store-mcp
```

### Configuration

Set the path to your service account key:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

### Running with HTTP Transport

For remote access, you can run the server with streamable-http transport:

```bash
play-store-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

#### Providing Credentials Remotely

When using streamable-http transport, you can provide credentials via HTTP POST to the `/credentials` endpoint:

```bash
# Using credentials file path
curl -X POST http://localhost:8000/credentials \
  -H "Content-Type: application/json" \
  -d '{"credentials_path": "/path/to/service-account.json"}'

# Using credentials JSON directly
curl -X POST http://localhost:8000/credentials \
  -H "Content-Type: application/json" \
  -d '{
    "credentials": {
      "type": "service_account",
      "project_id": "your-project",
      "private_key_id": "...",
      "private_key": "...",
      "client_email": "...",
      "client_id": "...",
      "auth_uri": "https://accounts.google.com/o/oauth2/auth",
      "token_uri": "https://oauth2.googleapis.com/token",
      "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
      "client_x509_cert_url": "..."
    }
  }'

# Using credentials JSON as string
curl -X POST http://localhost:8000/credentials \
  -H "Content-Type: application/json" \
  -d '{"credentials": "{\"type\":\"service_account\",\"project_id\":\"...\"}"}'

# Using base64-encoded credentials (useful for environment variables)
CREDS_B64=$(cat /path/to/service-account.json | base64 -w 0)
curl -X POST http://localhost:8000/credentials \
  -H "Content-Type: application/json" \
  -d "{\"credentials_base64\": \"$CREDS_B64\"}"
```

The endpoint returns:
- `200 OK` with `{"success": true, "message": "Credentials updated successfully"}` on success
- `400 Bad Request` if the request is malformed
- `401 Unauthorized` if the credentials are invalid
- `500 Internal Server Error` for other errors

## 🔧 MCP Client Configuration

### Claude Desktop

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

### Gemini / Other MCP Clients

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

## 🛠️ Available Tools

### Publishing Tools

| Tool | Description |
| --- | --- |
| `deploy_app` | Deploy an APK/AAB to a track with optional staged rollout and single-language release notes |
| `deploy_app_multilang` | Deploy an APK/AAB with multi-language release notes |
| `promote_release` | Promote a release from one track to another |
| `get_releases` | Get release status for all tracks |
| `halt_release` | Halt a staged rollout |
| `update_rollout` | Update rollout percentage for a staged release |
| `list_apps` | List all apps in the developer account (limited by API) |
| `get_app_details` | Get app metadata (title, description, etc.) |

### Store Listings Tools

| Tool | Description |
| --- | --- |
| `get_listing` | Get store listing for a specific language |
| `update_listing` | Update store listing (title, descriptions, video) |
| `list_all_listings` | List all store listings for all languages |

### Review Tools

| Tool | Description |
| --- | --- |
| `get_reviews` | Fetch recent reviews with optional filters |
| `reply_to_review` | Reply to a user review |

### Subscription Tools

| Tool | Description |
| --- | --- |
| `list_subscriptions` | List subscription products for an app |
| `get_subscription_status` | Check subscription purchase status |
| `list_voided_purchases` | List voided purchases |

### In-App Products Tools

| Tool | Description |
| --- | --- |
| `list_in_app_products` | List all in-app products for an app |
| `get_in_app_product` | Get details of a specific in-app product |

### Testers Management Tools

| Tool | Description |
| --- | --- |
| `get_testers` | Get testers for a specific testing track |
| `update_testers` | Update testers for a testing track |

### Orders Tools

| Tool | Description |
| --- | --- |
| `get_order` | Get detailed order/transaction information |

### Expansion Files Tools

| Tool | Description |
| --- | --- |
| `get_expansion_file` | Get APK expansion file information |

### Validation Tools

| Tool | Description |
| --- | --- |
| `validate_package_name` | Validate package name format |
| `validate_track` | Validate track name |
| `validate_listing_text` | Validate store listing text lengths |

### Batch Operations Tools

| Tool | Description |
| --- | --- |
| `batch_deploy` | Deploy to multiple tracks simultaneously |

### Vitals Tools

| Tool | Description |
| --- | --- |
| `get_vitals_overview` | Get Android Vitals overview (crashes, ANRs) |
| `get_vitals_metrics` | Get specific vitals metrics |

## 📋 Google Cloud Setup

### 1. Create a Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the **Google Play Developer API**
4. Go to **IAM & Admin** > **Service Accounts**
5. Create a new service account
6. Download the JSON key file

### 2. Grant Play Console Access

1. Go to [Google Play Console](https://play.google.com/console/)
2. Navigate to **Users and permissions**
3. Click **Invite new users**
4. Enter the service account email (from the JSON file)
5. Grant the following permissions:
   - **Release apps to testing tracks** (for internal/alpha/beta)
   - **Release apps to production** (for production releases)
   - **Reply to reviews** (for review management)
   - **View app information and download bulk reports** (for vitals)

## 💡 Usage Examples

### Deploy an App

```python
# Deploy to internal testing
deploy_app(
    package_name="com.example.myapp",
    track="internal",
    file_path="/path/to/app-release.aab",
    release_notes="Bug fixes and performance improvements"
)

# Deploy with multi-language release notes
deploy_app_multilang(
    package_name="com.example.myapp",
    track="production",
    file_path="/path/to/app-release.aab",
    release_notes={
        "en-US": "Bug fixes and improvements",
        "es-ES": "Corrección de errores y mejoras",
        "fr-FR": "Corrections de bugs et améliorations"
    },
    rollout_percentage=10.0  # Staged rollout to 10%
)
```

### Manage Store Listings

```python
# Update app description
update_listing(
    package_name="com.example.myapp",
    language="en-US",
    title="My Awesome App",
    short_description="The best app for productivity",
    full_description="A comprehensive description of your app..."
)

# Get all listings
listings = list_all_listings(package_name="com.example.myapp")
```

### Manage Testers

```python
# Add testers to beta track
update_testers(
    package_name="com.example.myapp",
    track="beta",
    tester_emails=["beta-testers@example.com", "qa-team@example.com"]
)

# Get current testers
testers = get_testers(package_name="com.example.myapp", track="alpha")
```

### Handle Reviews

```python
# Get recent reviews
reviews = get_reviews(
    package_name="com.example.myapp",
    max_results=50
)

# Reply to a review
reply_to_review(
    package_name="com.example.myapp",
    review_id="review-123",
    reply_text="Thank you for your feedback! We've fixed this in the latest update."
)
```

### Promote Releases

```python
# Promote from beta to production
promote_release(
    package_name="com.example.myapp",
    from_track="beta",
    to_track="production",
    version_code=100,
    rollout_percentage=20.0  # Start with 20% rollout
)

# Increase rollout percentage
update_rollout(
    package_name="com.example.myapp",
    track="production",
    version_code=100,
    rollout_percentage=50.0
)
```

### Batch Operations

```python
# Deploy to multiple tracks at once
batch_deploy(
    package_name="com.example.myapp",
    file_path="/path/to/app-release.aab",
    tracks=["internal", "alpha"],
    release_notes="Testing new features",
    rollout_percentages={
        "internal": 100.0,
        "alpha": 50.0
    }
)
```

### Input Validation

```python
# Validate before deploying
validation = validate_package_name("com.example.myapp")
if validation["valid"]:
    deploy_app(...)
else:
    print("Invalid package name:", validation["errors"])

# Validate listing text
validation = validate_listing_text(
    title="My App",
    short_description="A great app for productivity"
)
```

## 🔒 Environment Variables

| Variable | Description | Required |
| --- | --- | --- |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON key | Yes |
| `PLAY_STORE_MCP_LOG_LEVEL` | Log level (DEBUG, INFO, WARNING, ERROR) | No (default: INFO) |

## 🧪 Development

### Setup

```bash
git clone https://github.com/lusky3/play-store-mcp.git
cd play-store-mcp
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest -v --cov=src/play_store_mcp
```

### Linting

```bash
ruff check src/ tests/
ruff format src/ tests/
```

### Type Checking

```bash
mypy src/
```

## 🐛 Troubleshooting

### Error: "Service account key not found"

Ensure `GOOGLE_APPLICATION_CREDENTIALS` points to a valid JSON file:

```bash
ls -la $GOOGLE_APPLICATION_CREDENTIALS
```

### Error: "The caller does not have permission"

Verify the service account has been granted access in Play Console with the required permissions.

### Error: "Package name not found"

Ensure the app exists in Play Console and the service account has access to it.

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

- Inspired by [antoniolg/play-store-mcp](https://github.com/antoniolg/play-store-mcp) (Kotlin)
- Built with the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- Uses the [Google Play Developer API](https://developers.google.com/android-publisher)

## 🤖 AI Usage Disclaimer

Portions of this codebase were generated with the assistance of Large Language Models (LLMs). All AI-generated code has been reviewed and tested to ensure quality and correctness.
