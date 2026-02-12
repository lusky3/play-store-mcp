# Play Store MCP Server

An MCP (Model Context Protocol) server that connects to the Google Play Developer API. Deploy apps, manage releases, respond to reviews, and monitor app health — all through your AI assistant.

## Features

- :rocket: **App Deployment** — Deploy APK/AAB files to any track with staged rollouts
- :zap: **Batch Operations** — Deploy to multiple tracks simultaneously
- :globe_with_meridians: **Multi-Language Support** — Release notes and listings in multiple languages
- :white_check_mark: **Input Validation** — Validate inputs before making API calls
- :arrows_counterclockwise: **Automatic Retries** — Exponential backoff for transient failures
- :memo: **Store Listings** — Update titles, descriptions, and videos
- :chart_with_upwards_trend: **Release Management** — Promote releases, manage staged rollouts
- :busts_in_silhouette: **Tester Management** — Add and manage testers for testing tracks
- :star: **Review Management** — Fetch and reply to user reviews
- :bar_chart: **Android Vitals** — Monitor crashes, ANRs, and app health
- :credit_card: **Subscriptions** — List subscriptions and check purchase status
- :shopping_cart: **In-App Products** — List and manage in-app products
- :lock: **Secure** — Google Cloud service account authentication

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
