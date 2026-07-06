# Deferred Audit Backlog — Handoff

> **Purpose:** every finding from the two full audits (v0.4.0 pre-refactor + v0.5.0 re-audit)
> that was **deliberately deferred** rather than fixed, grouped into pick-up-able workstreams.
> Each item has file:line, why it was deferred, the recommended fix, whether it's breaking,
> and rough effort. Nothing here is a live CRITICAL/HIGH regression — the real defects were
> fixed (see "Already done"). Line numbers are as of `main` @ v0.5.0; re-verify before editing.

## Already done (baseline — do NOT re-open)
- **#87** pre-refactor bug fixes (orders v3 shape, pagination, `delete_subscription_offer`, atomic downloads); removed non-functional Vitals tools.
- **#88** migrated to the standalone `fastmcp` v3 package.
- **#89** opt-in `CODE_MODE` code-mode transform (default-off).
- **#90** shared-client thread-safety lock (`_http_lock`), test-suite speedup, credential-isolation docs.
- **#92** (pending) 0.5.0 version bump + changelog cut.
- **#93** download per-chunk lock (H1 gap), `PLAY_STORE_MCP_DOWNLOAD_DIR` confinement, `update_testers` assertion, image_type docstrings.
- **Adversarially verified clean (leave alone):** code-mode sandbox isolation (no env/creds/fs/net/subprocess; read-only enforced through the sandbox; 30s/100MB/50-call limits), retry idempotency, edit-transaction cleanup, `_shared_state` swap atomicity, DNS-rebinding, admin-token constant-time compare, pagination, `pip-audit` clean at 0.5.0, 100% branch coverage.

---

## Workstream 1 — Tool-consolidation refactor (the big planned effort)
Tracked in the CHANGELOG `[Unreleased] → Planned` note. Needs its own plan (use `writing-plans`). Several items change the public output contract, so bundle with a **minor/major bump**.

| # | Item | Location | Fix | Breaking? | Effort |
|---|------|----------|-----|-----------|--------|
| 1 | 3 tools return raw `dict[str, Any]` instead of a typed `*Result` model | `update_testers` (`client.py:4045`, wrapper `server.py:2317`), `migrate_base_plan_prices` (`server.py:1782`), `batch_migrate_base_plan_prices` (`server.py:1815`) | Add typed result models like their siblings; return `.model_dump()` | Yes (output keys change) | M |
| 2 | Exact-duplicate Result model | `SubscriptionCatalogResult` (`models.py:349`) == `OneTimeProductActionResult` (`models.py:395`) — identical fields | Merge into one shared model | Yes (type name) | S |
| 3 | 15 near-duplicate `*Result` models (`success`/`message`/`error`) | `models.py` | Extract an `ActionResult` base | No (fields unchanged) | M |
| 4 | ~88 client methods share the `_get_service → _execute → _parse → wrap` skeleton | `client.py` (whole file) | A `_call(request, parse=, on_error=)` helper + an `_edit()` context manager (removes ~13 dual-`except` blocks) | No | L |
| 5 | 114/117 server tool wrappers are pure passthroughs | `server.py` | Generate wrappers from a `(name, client_method, is_write, return_kind)` table | No | L |
| 6 | Batch input styles inconsistent: 6 tools take `list[str]` ids, 14 take `list[dict]` bodies — not clean by verb | e.g. `batch_delete_in_app_products` (`list[str]`) vs `batch_delete_one_time_products` (`list[dict]`) | Normalize batch inputs per family | Yes (param shape) | M |
| 7 | Untyped module-global `_shared_state: dict[str, Any]` with magic-string keys | `server.py:88` | Replace with a typed `@dataclass ServerState` holder (still module-global, monkeypatch-friendly) | No (internal) | S |

---

## Workstream 2 — Breaking API renames (need a version decision)
All rename shipped 0.5.0 tools/params → break existing clients. Batch into the next **major/minor** (ideally folded into Workstream 1 so the surface changes once).

| # | Item | Location | Fix | Effort |
|---|------|----------|-----|--------|
| 8 | `get_releases` / `get_reviews` are `get_*` but return lists | `server.py` (`get_releases` ~328, `get_reviews` ~439) | Rename → `list_releases` / `list_reviews` | S |
| 9 | `sku`/`skus` params vs `product_id` for the same value | in-app-product tools (`server.py:851, 896, 930, 979, 999`) | Unify on `product_id` | S |
| 10 | `get_subscription_status` uses `subscription_id` where ~17 siblings use `product_id` | `server.py:545` | Rename param → `product_id` | S |
| 11 | `set_data_safety` is the lone domain `set_` verb (others are `update_*`) | `server.py` (`set_data_safety`) | Rename → `update_data_safety` | S |
| 12 | 8× tools with 6-7 positional params (PLR0913) | deploy/listing tools | Introduce params model (also changes the tool input schema) | M |

---

## Workstream 3 — Concurrency / availability follow-ups

| # | Item | Location | Fix | Severity | Effort |
|---|------|----------|-----|----------|--------|
| 13 | Resumable uploads hold `_http_lock` for the entire multi-round-trip upload (a big AAB head-of-line-blocks every other call on the shared client) | `client.py:_execute` (452) wraps the whole `execute()`; upload sites `client.py:615/621, 4326, 4368, 4422, 4478, 4605, 5865, 5905` | Drive uploads chunk-by-chunk with **per-chunk** `_http_lock` (like `_download_to_file` now does), preserving 429-retry/error handling | MEDIUM (availability only — correctness is fine, uploads are serialized) | M |
| 14 | Lazy `_get_service()` build is not synchronized (double-build race) | `client.py:372-428` | Guard the build with `_http_lock` (double-checked). Effectively unreachable today (shared client warmed once in `lifespan`) | LOW | S |

---

## Workstream 4 — CI-workflow hardening
**Cannot be validated locally** — must be iterated in CI (a wrong egress allowlist or perms split red-lines the pipeline). Do these one workflow at a time with a test PR.

| # | Item | Location | Fix | Severity |
|---|------|----------|-----|----------|
| 15 | `packages/id-token/attestations: write` in scope during PR-triggered image builds | `.github/workflows/docker.yml:13-28` (perms), build runs on `pull_request` | Split publish/attest into a push-only job; keep the PR build at `contents: read` (+ `security-events: write`) | LOW–MED |
| 16 | Build job holds unused `pages/id-token: write` | `.github/workflows/docs.yml:11-14` | Move those to the `deploy` job; `build` gets `contents: read` | LOW |
| 17 | `harden-runner` `egress-policy: audit` (log-only) on secret-bearing jobs | all workflows (release/snyk/sonarcloud/safety/qlty/discord/docker) | Switch token-bearing jobs to `egress-policy: block` + an explicit allowlist (pypi/ghcr/github/google/scanner APIs) — **iterate the allowlist in CI** | LOW (defense-in-depth) |

---

## Workstream 5 — Security hardening opt-ins (LOW, by-design)

| # | Item | Location | Fix | Notes |
|---|------|----------|-----|-------|
| 18 | BYO service-account JSON `token_uri` is a mild SSRF primitive (google-auth POSTs a signed JWT to the caller-supplied `token_uri`) | `client.py:378-403` (`from_service_account_info`) | Optionally allowlist `token_uri` host to `*.googleapis.com` | Supplying creds is already privileged; watch for legit regional endpoints |
| 19 | Multi-tenant credential fallback confused-deputy: a header-less request silently uses the shared/operator identity | `server.py:74-76` | Optionally add a switch to disable the shared fallback (missing header → fail closed). Docs already advise multi-tenant deployments to unset fallback env creds | Non-issue for single-tenant local |

---

## Workstream 6 — Low-risk cleanup batch (one small non-breaking PR)
All safe, locally verifiable, no contract change. Good "good-first-PR" batch.

| # | Item | Location | Fix |
|---|------|----------|-----|
| 20 | `update_credentials` over the (ungated) complexity threshold + duplicates the credential-parsing ladder in `get_client_from_context` | `server.py:3604` (parsing 3665-3707) vs `server.py:55-72` | Extract `_client_from_credentials(value, is_base64) -> PlayStoreClient` (raises `PlayStoreClientError`); both callers use it, `update_credentials` maps the error to a 400 |
| 21 | Dead `credentials_updated` key — written, never read; a test asserts it | init `server.py:88`, write `server.py:3731`, assert `test_server_extended.py:1192` | Remove the key, the write, and the assertion (also touches the 11 rebind sites in #25) |
| 22 | `Order.product_ids` is derived-redundant (drift risk) | `models.py:197` | Make it a `@computed_field` from `line_items`; drop the explicit population in `client.py:_parse_order` and the `product_ids=` kwargs in Order constructions/tests |
| 23 | `_make_http_error` duplicated across 21 test files, 2 signatures | `tests/*.py` (`test_audit_fixes.py:26` + `test_client_extended.py:23` use `(status, reason)`; 19 others use `(reason)`) | Consolidate one `(status=..., reason=...)` helper into `conftest.py`; migrate call sites |
| 24 | `_reset_shared_state` fixture defeated by rebinding | `tests/conftest.py:38` fixture; rebinds at `test_credentials_endpoint.py` (×10) + `test_audit_fixes.py:871` | Mutate in place / `monkeypatch.setitem` instead of `server._shared_state = {...}` |
| 25 | 11× magic values (429/404/50/100.0…) inline | retry/status/validation code in `client.py` + `server.py` | Name module constants (`HTTP_TOO_MANY_REQUESTS`, `MAX_ROLLOUT_PCT`, …). Note: PLR2004 is **not** in the ruff `select`, so not gated |
| 26 | Code-mode docstring discoverability: "IAP" 0 hits in docstrings | in-app-product tool docstrings (`server.py`) | Add "in-app product (IAP)" to the relevant first lines so code-mode `search` finds them by "IAP". (The `image_type`-enum gap on delete-image tools was fixed in #93.) |

---

## Explicitly won't-fix (with reason)
- **Read-only gating on download tools** (audit suggested it): a download is a *read* from the Play Store (no store mutation); gating it under `--read-only` would break the legitimate "inspect a prod app in read-only mode and grab the APK" flow. The host-write risk is addressed by the `PLAY_STORE_MCP_DOWNLOAD_DIR` confinement shipped in #93.
- **Vestigial `yield _shared_state`** in `lifespan` (`server.py:106`): the yielded value is unused by production code, but the lifespan tests read it and it's harmless — not worth the test churn.
- **`pydantic-monty 0.0.17`** (code-mode sandbox): early version; no advisory (`pip-audit` clean), and it's absent from the published Docker image (base wheel only). Informational — track as it matures; no action.

## Suggested sequencing
1. **Workstream 6** (cleanup) — quick, non-breaking, unblocks nothing but reduces noise.
2. **Workstream 3 #13** (upload per-chunk lock) — completes the shared-client thread-safety story started by #90/#93.
3. **Workstream 1 + 2** together as the planned tool-consolidation refactor, shipped in one breaking minor/major (write a `writing-plans` plan first).
4. **Workstream 4** (CI hardening) — independent, iterate in CI.
5. **Workstream 5** — opt-in security hardening, as capacity allows.
