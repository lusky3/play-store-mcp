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

## [0.7.0] - 2026-10-29

> **Breaking — code-mode is now enabled by default.** Clients that expect the
> full 117-tool list (e.g. anything enumerating tools by name) will instead
> see three meta-tools (`search`/`get_schema`/`execute`) unless `CODE_MODE=0`
> is set. See Changed below.

This is the first published release since 0.6.1. It also ships 0.6.3 and 0.6.4,
which were never tagged (0.6.2, also untagged, is listed separately below).

### Security
- Blocked SSRF via a spoofed `token_uri` in credential JSON. Credentials passed
  in the `X-Google-Credentials`/`X-Google-Credentials-Base64` headers (accepted
  on any request) could name an arbitrary `token_uri`, which google-auth POSTs
  to on token refresh. Credentials are now rejected unless `token_uri` is
  Google's own `https://oauth2.googleapis.com/token`.
- Upgraded `pyjwt` 2.13.0 → 2.15.1 (14 known vulnerabilities, 2 critical, fixed;
  declared floor raised to `>=2.15.1` so published metadata carries the fix),
  `urllib3` 2.7.0 → 2.8.0 (3 known vulnerabilities), and `authlib` 1.7.2 → 1.9.1
  (7 known vulnerabilities in 1.8.0, 1 critical).
- The server warns at startup if `PLAY_STORE_MCP_ADMIN_TOKEN` is set but shorter
  than 16 characters, and the docs warn that `--host 0.0.0.0` exposes the
  unauthenticated `/mcp` endpoint.

### Added
- Opt-in tool-failure log. Set `PLAY_STORE_MCP_FAILURE_LOG=1` to record each
  failed tool call (raised errors, argument-validation failures, and results
  with `success: false` or an `error`) to a JSON-lines file at
  `PLAY_STORE_MCP_FAILURE_LOG_PATH` (default
  `$XDG_STATE_HOME/play-store-mcp/tool-failures.jsonl`). MCP clients log such
  calls as successes, so this is the only record of why they failed. Off by
  default for every transport. Secret-named arguments are redacted (including
  from error text), long values are truncated, and the file is `0600` and
  rotates at 5MB. With code-mode on, calls inside `execute` are recorded under
  their own tool names. The idea came from
  [abd3lraouf-studios/google-play-console-mcp](https://github.com/abd3lraouf-studios/google-play-console-mcp)
  and was implemented independently here.
- `list_subscriptions` gains `include_regional_prices` (see Changed).

### Changed
- **Breaking:** `CODE_MODE` now defaults to **enabled** (was opt-in/default-off).
  Set `CODE_MODE=0` (or `false`/`no`/`off`, case-insensitive) to opt out and
  get the classic 117-tool list back. The `execute` meta-tool's sandbox
  (Monty) is now a base dependency — not an optional extra — so every
  install path (`pip install play-store-mcp`, `uvx play-store-mcp`, Docker)
  works out of the box with no separate install step. Read-only enforcement
  still applies inside the sandbox.
- `list_subscriptions` no longer returns each base plan's per-region price
  table by default (see Fixed); pass `include_regional_prices=True` for it.
- The Docker image now runs on Python 3.15 (`python:3.15-alpine`, was 3.14).

### Fixed
- `get_reviews` and `get_review` failed on every real response with a pydantic
  `string_type` error: the Reviews API sends `androidOsVersion` as an integer
  SDK level (e.g. `34`), while `Review.android_version` is a string. It is now
  converted; a missing value is still `None`. Reported and fixed by @j4velin
  (#178).
- `deploy_app`, `promote_release`, `halt_release`, `update_rollout`,
  `update_listing` and `update_testers` raised instead of returning their
  documented failure result when setting up the edit failed (bad package name,
  missing permission, edit quota, transient API errors).
- A pooled keep-alive connection that Google closed while idle made calls fail
  with `BrokenPipeError` or an SSL EOF, and kept failing: httplib2 leaves a
  connection whose send failed in its pool, so the next call reused the dead
  socket. Transport errors now drop the pool so the next request reconnects,
  and are retried on the same terms as a 500/503 (idempotent requests only,
  plus edit creation, where a duplicate uncommitted edit is harmless). This
  mostly hit long-running HTTP deployments. The bug was reported in
  [abd3lraouf-studios/google-play-console-mcp](https://github.com/abd3lraouf-studios/google-play-console-mcp)
  and fixed independently here.
- `list_subscriptions` returned every base plan's full per-region price table
  (`regionalConfigs`, ~170 regions each), so a handful of subscriptions exceeded
  a tool result's size limit. One subscription with two base plans was already
  ~40KB. Each base plan now reports `regionalConfigCount` instead, cutting that
  to ~1.2KB; `include_regional_prices=True` restores the full table, and
  `get_subscription` still returns one product's prices. The bug was reported
  in [abd3lraouf-studios/google-play-console-mcp](https://github.com/abd3lraouf-studios/google-play-console-mcp)
  and fixed independently here.
- Concurrent first tool calls could each build their own API client (a race in
  the lazy client setup); the client is now built once.

### Dependencies
- `fastmcp` 4.0.2 → 4.1.4, `mcp` 2.1.1 → 2.3.0, the code-mode sandbox
  `pydantic-monty` 0.0.18 → 1.4.0, `starlette` 1.3.1 → 1.10.0,
  `google-api-python-client` 2.198.0 → 2.201.0, `google-auth` 2.55.1 → 2.62.0,
  `cryptography` 50.0.0 → 50.0.2, and the rest of the lockfile.
- Container: newer base image digest, plus `apk upgrade` in the runtime stage to
  pick up Alpine fixes that the base image hasn't yet.
- CI: `uv` 0.13.6; GitHub Actions updated (all `github/codeql-action` refs pinned
  to one version and grouped in Dependabot); runners on `ubuntu-26.04` with
  Python 3.14.9; Grype/Trivy suppress only no-fix-yet CVEs, using each
  scanner's native mechanism (state-based or with an expiry).

## [0.6.2] - 2026-09-05

### Fixed
- `stable`'s copied CI/security workflows (`ci`, `codeql`, `sonarcloud`, `snyk`,
  `safety`, `dependency-review`, `qlty-coverage`, `docker`) still filtered on
  `branches: [main]` — a leftover from copying them from `main` — so none of
  them ever actually ran on a PR or push targeting `stable`. Retargeted all
  eight to `branches: [stable]`. (`docs` and `scorecard` deliberately left
  unchanged: `docs` deploys to the single shared GitHub Pages site and
  `scorecard` isn't a PR gate on either branch, so both need their own
  ownership decision rather than a mechanical fix here.)
- `Dockerfile` still used the pre-`uv.lock`-aware build pattern
  (`uv build --wheel` + `uv pip install` into a fresh venv), already fixed on
  `main`: that pattern re-resolves dependencies instead of honoring the
  lockfile, and can fail to reproduce a pin `uv.lock` already settled on.
  Ported `main`'s fix (`uv sync --frozen --no-editable` straight into the
  runtime venv path). Verified with a real local `docker build` + boot.

## [0.6.1] - 2026-09-04

### Added
- `release.yml` now has a `Verify Version & Changelog` gate that runs before
  any test/build/publish step: it fails the whole release if `pyproject.toml`'s
  version doesn't exactly match the pushed tag, or if `CHANGELOG.md` has no
  matching `## [X.Y.Z]` heading. Complements the PR-time `Version Bump Check`
  (which only runs on PRs into `stable`) by also guarding the tag-push
  trigger itself — nothing stops a tag from being pushed independently of a
  PR. Verified live: a deliberately mismatched test tag failed at this gate
  and never reached the Publish to PyPI step.

## [0.6.0] - 2026-09-04

Upgrades to **FastMCP 4** and the new **MCP 2026-07-28 spec**, now that
FastMCP 4 has reached a stable GA release (`4.0.0`, `4.0.1`, `4.0.2`).

### Changed
- Bumped `fastmcp` from the `<4.0` cap to `>=4.0.0,<5.0`, which migrates to
  MCP Python SDK v2 and the new MCP 2026-07-28 spec (stateless protocol
  core; no more mandatory `initialize`/`Mcp-Session-Id`). FastMCP 4
  negotiates the best mutual protocol era per client by default, so
  existing clients still on the older handshake keep working unchanged —
  verified: full unit suite (728 tests), lint, mypy, both transports
  (`stdio` and `streamable-http`) boot and complete a legacy `initialize` →
  `notifications/initialized` → `tools/list` round trip, the live
  read-only integration suite against a real Play Console app, and the
  Docker build all pass unmodified. This was soaked on `main` first (see
  the nightly-only beta trial and this GA follow-up) before promotion here.

## [0.5.1] - 2026-08-19

### Added
- CI now requires a version bump and a matching `CHANGELOG.md` entry on every
  pull request into `stable`, so a dependency or config change can no longer
  slip onto the production branch without a corresponding release.

### Dependencies
- Capped `fastmcp` to `<4.0` (was open-ended `>=3.4.2`). FastMCP 4 targets the
  new, backward-incompatible MCP 2026-07-28 spec (stateless protocol core,
  no more `initialize`/`Mcp-Session-Id`) and is still in beta upstream. This
  keeps Dependabot from silently proposing/merging a major protocol jump;
  the migration will be a deliberate, manually-verified upgrade instead.

## [0.5.0] - 2026-08-14

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
- **Breaking:** APK/AAB downloads are now **always confined to a directory** —
  there is no "write anywhere" mode. The base directory is
  `PLAY_STORE_MCP_DOWNLOAD_DIR` when set, otherwise the server's current working
  directory; a `destination_path` that resolves outside it is rejected. On
  network transports (`--transport sse` / `streamable-http`), setting
  `PLAY_STORE_MCP_DOWNLOAD_DIR` is **recommended** but not required — the server
  logs a warning (rather than refusing to start) when it is unset and falls back
  to the working directory. Point it at a writable directory on cloud/hosted
  deployments (e.g. `/tmp/play-store-downloads` on Render), where the working
  directory may be read-only.

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
- Download-destination confinement lives in `PlayStoreClient` and applies to both
  the temporary `.part` file and the final file: every destination is canonicalized
  and verified to stay within the (always-present) base directory before anything
  is written, closing the path-traversal / arbitrary-file-overwrite vector
  (SonarCloud `S2083`). Downloads are always confined — `PLAY_STORE_MCP_DOWNLOAD_DIR`
  when set, otherwise the working directory.
- Documented that the server-side credential fallback
  (`GOOGLE_PLAY_STORE_CREDENTIALS` / `/credentials`) is a process-global client
  shared by every request that omits a credential header; multi-tenant
  deployments should leave it unset so a missing header fails closed rather than
  running under a shared identity.
- Recommend pairing code-mode with `--read-only` / `PLAY_STORE_MCP_READ_ONLY=1`
  unless writes are needed: one `execute` can invoke up to 50 tool calls
  (including mutations) behind a single approval. Read-only enforcement still
  applies inside the sandbox.

### Dependencies
- Bumped `pyasn1` 0.6.3 → 0.6.4 (CVE-2026-59885, CVE-2026-59886) and
  `cryptography` 49.0.0 → 50.0.0 (PYSEC-2026-3552) — HIGH-severity advisories in
  transitive dependencies (via `google-auth` / `pyjwt[crypto]`). `pip-audit` clean.

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
