# Getting Started

## Prerequisites

1. **Google Cloud Project** with the Google Play Developer API enabled
2. **Service Account** with access to your Play Console
3. **Python 3.11+** or `uvx` installed

## Installation

=== "uvx (Recommended)"

    ```bash
    uvx play-store-mcp
    ```

    No installation needed — uvx downloads and runs it directly.

=== "pip"

    ```bash
    pip install play-store-mcp
    play-store-mcp
    ```

=== "From Source"

    ```bash
    git clone https://github.com/lusky3/play-store-mcp.git
    cd play-store-mcp
    pip install -e .
    play-store-mcp
    ```

## Google Cloud Setup

### 1. Create a Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable the **Google Play Developer API**
4. Navigate to **IAM & Admin** → **Service Accounts**
5. Create a new service account
6. Download the JSON key file

### 2. Grant Play Console Access

1. Go to [Google Play Console](https://play.google.com/console/)
2. Navigate to **Users and permissions**
3. Click **Invite new users**
4. Enter the service account email (found in the JSON key file)
5. Grant permissions based on what you need:

| Permission | Required For |
|---|---|
| Release apps to testing tracks | Internal, alpha, beta deployments |
| Release apps to production | Production releases |
| Reply to reviews | Review management |
| View app information and download bulk reports | Vitals, app details |

### 3. Set Credentials

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

Add this to your shell profile (`.bashrc`, `.zshrc`, etc.) to persist it.

## Verify Setup

Once configured with an MCP client, try a simple tool call:

```
validate_package_name("com.example.myapp")
```

If credentials are working, try:

```
get_app_details("com.your.actual.app")
```
