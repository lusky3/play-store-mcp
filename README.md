# Play Store MCP Server

[![CI](https://github.com/lusky3/play-store-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/lusky3/play-store-mcp/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/play-store-mcp.svg)](https://badge.fury.io/py/play-store-mcp)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An MCP (Model Context Protocol) server that connects to the Google Play Developer API. Deploy apps, manage releases, respond to reviews, and monitor app health - all through your AI assistant.

## ✨ Features

- **🚀 App Deployment**: Deploy APK/AAB files to any track (internal, alpha, beta, production)
- **📈 Release Management**: Promote releases between tracks, manage staged rollouts
- **⭐ Review Management**: Fetch and reply to user reviews
- **📊 Android Vitals**: Monitor crashes, ANRs, and app health metrics
- **💳 Subscription Management**: List subscriptions and check purchase status
- **🔐 Secure**: Uses Google Cloud service account authentication

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
|------|-------------|
| `deploy_app` | Deploy an APK/AAB to a track with optional staged rollout |
| `promote_release` | Promote a release from one track to another |
| `get_releases` | Get release status for all tracks |
| `halt_release` | Halt a staged rollout |
| `update_rollout` | Update rollout percentage for a staged release |
| `list_apps` | List all apps in the developer account |
| `get_app_details` | Get app metadata (title, description, etc.) |

### Review Tools

| Tool | Description |
|------|-------------|
| `get_reviews` | Fetch recent reviews with optional filters |
| `reply_to_review` | Reply to a user review |

### Subscription Tools

| Tool | Description |
|------|-------------|
| `list_subscriptions` | List subscription products for an app |
| `get_subscription_status` | Check subscription purchase status |
| `list_voided_purchases` | List voided purchases |

### Vitals Tools

| Tool | Description |
|------|-------------|
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

## 🔒 Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
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
