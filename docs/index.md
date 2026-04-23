# Play Store MCP Server

An MCP (Model Context Protocol) server that connects to the Google Play Developer API. Deploy apps, manage releases, respond to reviews, and monitor app health — all through your AI assistant.

## Features

- 🚀 **App Deployment** — Deploy APK/AAB files to any track with staged rollouts
- ⚡ **Batch Operations** — Deploy to multiple tracks simultaneously
- 🌐 **Multi-Language Support** — Release notes and listings in multiple languages
- ✅ **Input Validation** — Validate inputs before making API calls
- 🔄 **Automatic Retries** — Exponential backoff for transient failures
- 📝 **Store Listings** — Update titles, descriptions, and videos
- 📈 **Release Management** — Promote releases, manage staged rollouts
- 👥 **Tester Management** — Add and manage testers for testing tracks
- ⭐ **Review Management** — Fetch and reply to user reviews
- 📊 **Android Vitals** — Monitor crashes, ANRs, and app health
- 💳 **Subscriptions** — List subscriptions and check purchase status
- 🛒 **In-App Products** — List and manage in-app products
- 📦 **Expansion Files** — Manage APK expansion files for large apps
- 🧾 **Orders** — Retrieve detailed transaction information
- 🐳 **Docker Support** — Run as a container with health checks
- 🔑 **Per-Request Credentials** — Bring-your-own-credentials for multi-tenant deployments
- 🔒 **Secure** — Google Cloud service account authentication

## Requirements

- Python 3.11+
- Google Cloud service account with Play Developer API access
- An MCP-compatible client (Claude Desktop, Kiro, Gemini CLI, etc.)

## Quick Start

```bash
# Run directly with uvx (no install needed)
uvx play-store-mcp

# Or install with pip
pip install play-store-mcp
play-store-mcp
```

Set your credentials:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

See [Getting Started](getting-started.md) for full setup instructions.
