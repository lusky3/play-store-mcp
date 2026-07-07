<!-- markdownlint-disable-file MD024 -->
<!-- Keep a Changelog repeats "### Added"/"### Changed"/etc. across versions;
     MD024 (no-duplicate-headings) is disabled for this file by design. -->

# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Consolidate and reduce the MCP tool surface (now 117 tools) by grouping
  related operations, to lower per-request tool-list overhead — with no planned
  loss of functionality.

## [0.5.0] - 2026-07-06

Adds opt-in **code-mode**, migrates the server onto the standalone **`fastmcp`**
package, hardens shared-client concurrency, and removes the non-functional Vitals
tools.

> **Breaking — Vitals tools removed.** `get_vitals_overview` and
> `get_vitals_metrics` no longer exist (see Removed); they returned placeholder
> data and never called an API.

### Added
- **Experimental code-mode (opt-in):** set `CODE_MODE=1` to expose tools through
  FastMCP's code-mode transform (`search`/`get_schema`/`execute` meta-tools with a
  sandboxed executor) instead of the full tool list, reducing per-request tool-list
  token overhead. Off by default; requires the `play-store-mcp[code-mode]` extra
  (Monty sandbox) for the `execute` tool. This is the first step of the tool-surface
  reduction noted under Planned.

### Changed
- Migrated the server framework from the official MCP SDK's `FastMCP`
  (`mcp.server.fastmcp`) to the standalone `fastmcp` package (v3). Behavior is
  unchanged — all 117 tools, the `/health` and `/credentials` routes,
  per-request header credentials, admin-token auth, read-only mode, and
  DNS-rebinding protection (`PLAY_STORE_MCP_DISABLE_DNS_REBINDING`) are
  preserved. This unblocks the upcoming code-mode capability, which lives only
  in `fastmcp`.

### Removed
- **Breaking:** removed the non-functional `get_vitals_overview` and
  `get_vitals_metrics` tools. They never called an API and returned hardcoded
  placeholder data; Android Vitals requires the separate Play Developer
  Reporting API, which is out of scope for this server.

### Fixed
- `get_order` / `batch_get_orders` now read the real v3 `Order` resource:
  product IDs from `lineItems[].productId` (exposed as `product_ids` /
  `line_items`) and status from the `state` string enum. Previously they read
  non-existent top-level `productId` / `purchaseState` fields, so those values
  were always null against the live API and order state was lost.
- `list_in_app_products` now follows `tokenPagination.nextPageToken` instead of
  returning only the first page (apps with many SKUs were silently truncated).
- `get_reviews` and `list_voided_purchases` now paginate to `max_results`
  across pages via `tokenPagination`, rather than returning a single page.
- `delete_subscription_offer` now returns the parent `product_id` instead of
  mislabeling the deleted `offer_id` as `product_id`.
- Media downloads (`download_generated_apk` / `download_system_apk_variant`) now
  acquire the client's transport lock per chunk, closing a gap in the shared-client
  thread-safety fix: a download concurrent with another call on the shared client
  no longer races on the non-thread-safe `httplib2` transport (which could corrupt
  the downloaded file or raise `ResponseNotReady`).
- The shared (env / `/credentials`) client now serializes its HTTP transport with
  a per-client lock, so concurrent tool calls under network transports no longer
  race on the non-thread-safe `httplib2` connection (which could interleave
  requests or deliver a response to the wrong caller). Per-request header-auth
  clients each get their own client and stay fully concurrent.

### Security
- APK/AAB downloads (`download_generated_apk`, `download_system_apk_variant`)
  now write to a temporary file and atomically rename on success, so a failed
  or unauthorized download can no longer truncate an existing file or leave a
  partial one at the destination.
- Optional `PLAY_STORE_MCP_DOWNLOAD_DIR` confines download destinations to an
  allowlisted directory — recommended for network-exposed deployments so a caller
  cannot write outside it (path traversal / arbitrary-file overwrite). Unset (the
  default, single-user local case) allows any path, preserving existing behavior.
- Documented that the server-side credential fallback
  (`GOOGLE_PLAY_STORE_CREDENTIALS` / `/credentials`) is a process-global client
  shared by every request that omits a credential header; multi-tenant
  deployments should leave it unset so a missing header fails closed rather than
  running under a shared identity.
- Recommend pairing code-mode with `--read-only` / `PLAY_STORE_MCP_READ_ONLY=1`
  unless writes are needed: one `execute` can invoke up to 50 tool calls
  (including mutations) behind a single approval. Read-only enforcement still
  applies inside the sandbox.

## [0.4.0] - 2026-07-02

Major feature expansion: grows from ~24 to **119 MCP tools**, adding broad
coverage of the Google Play Developer API, plus reliability/security hardening
and a full dependency refresh.

> **Note — write endpoints are beta.** The new write/mutating tools in this
> release are covered by unit tests (mocked), but only read-only paths have been
> exercised against the live Play API. Treat create/update/patch/delete/upload/
> purchase-action/migrate tools as beta and
> [open an issue](https://github.com/lusky3/play-store-mcp/issues) for any
> problems. Run with `--read-only` / `PLAY_STORE_MCP_READ_ONLY=1` to disable all
> write operations.

> **Note — tool count.** 119 tools is a large surface for a single MCP server:
> it increases per-request token usage and some clients cap/truncate large tool
> lists. A follow-up release will reduce this.

### Added
- **Purchases & orders:** in-app product purchases (`get`/`acknowledge`/`consume`);
  purchase management (`refund_order`, `cancel`/`defer`/`revoke_subscription_purchase`,
  `get_product_purchase_v2`); `get_review`, `batch_get_orders`.
- **Monetization catalog:** in-app products, subscriptions, subscription base
  plans (incl. price migration), subscription offers, one-time products, and
  one-time product purchase options & offers.
- **Artifacts & uploads:** edit upload pipeline (APKs, app bundles, deobfuscation
  and expansion files); store-listing images; generated APK list + download;
  system APK variants; internal app sharing uploads.
- **Account & configuration:** external transactions (alternative billing);
  device tier configs; app data safety labels; app recovery actions; Play Console
  account access (users & grants).
- **Read-only mode:** `--read-only` / `PLAY_STORE_MCP_READ_ONLY` disables all write
  operations.

### Changed
- Transient errors (429/500/503) are retried with exponential backoff on real API
  calls, and the retry is idempotency-aware — non-idempotent (POST) mutations are
  not retried on an ambiguous 5xx, to avoid duplicate side effects.
- `/credentials` endpoint hardened: optional `PLAY_STORE_MCP_ADMIN_TOKEN`
  (constant-time bearer check) for deployments behind a reverse proxy; blocking
  credential validation moved off the event loop.
- Consistent error contract: read methods raise `PlayStoreClientError` instead of
  leaking raw `HttpError`, and edit transactions are always cleaned up on failure.
- List endpoints now follow `nextPageToken` — fixes silent truncation (including
  the account-access user list).
- CI: PyPI publish gated on tests/lint/type-check; least-privilege Docker workflow
  permissions; pinned `uv`.

### Fixed
- `list_app_recoveries` now sends the API-required `versionCode` (previously
  rejected).
- `__version__` is single-sourced from package metadata (was a stale `0.2.0`).
- Case-insensitive `.aab` detection.
- Subscription `start_time` / `expiry_time` populated from the v2 response.

### Security
- `pyjwt[crypto]>=2.12.0` is now a declared dependency so the CVE-2026-32597 fix
  reaches installs, not just the lockfile.
- Credential-update error responses no longer leak exception text.

### Dependencies
- Refreshed all dependencies to latest, including the majors **mypy 2.x** and
  **protobuf 7.x**. Validated: 697 tests / 100% branch coverage, ruff/mypy clean,
  pip-audit clean, and a live read-only API smoke.

## [0.3.0] - 2026-06-19

Security hardening, dependency upgrades, and CI improvements.

### Added
- Configurable DNS-rebinding protection via the
  `PLAY_STORE_MCP_DISABLE_DNS_REBINDING` environment variable (for cloud /
  reverse-proxy deployments).

### Changed
- Upgraded `mcp` 1.26.0 → 1.28.0 and `cryptography` 46.0.7 → 49.0.0.
- Hardened CI workflows, suppressed scanner false positives, and addressed
  code-review findings.

## [0.2.0] and earlier

See the [GitHub Releases](https://github.com/lusky3/play-store-mcp/releases) page.

[Unreleased]: https://github.com/lusky3/play-store-mcp/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/lusky3/play-store-mcp/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/lusky3/play-store-mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/lusky3/play-store-mcp/compare/v0.2.0...v0.3.0
