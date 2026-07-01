# Read Siblings (get_review, batch_get_orders) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]` checkboxes.

**Goal:** Add two read endpoints that complete existing families — `get_review` (reviews.get) and `batch_get_orders` (orders.batchget).

**Architecture:** Reuse existing models (`Review`, `Order`) — no new models. Extract a shared `_parse_review` helper (used by both `get_reviews` and the new `get_review`). Two read MCP tools (no read-only gating).

**Tech Stack:** Python 3.11+, google-api-python-client (Android Publisher v3), pydantic, pytest, ruff, mypy, uv.

## Global Constraints
- Pass ruff/format/mypy; 100% new-code coverage; no new deps.
- Reads raise `PlayStoreClientError(f"Failed to ...: {e.reason}") from e` on HttpError.
- **API shapes (discovery rev 20260701):**
  - `reviews.get` → `service.reviews().get(packageName=, reviewId=, translationLanguage=<opt>)` → `Review` resource.
  - `orders.batchget` → `service.orders().batchget(packageName=, orderIds=[...])` — **lowercase `batchget`** — → `{"orders": [Order]}`.
- Commit trailers: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` / `Claude-Session: https://claude.ai/code/session_01VtR3xYVpG3HwYJMASGbus2`.

## Tasks
### Task 1: Client — extract `_parse_review`, add `get_review` + `batch_get_orders`
- Extract module-level `_parse_review(review_data) -> Review | None`; refactor `get_reviews` loop to use it (behavior-preserving).
- `get_review(package_name, review_id, translation_language=None) -> Review`: calls `reviews().get(...)`; if `_parse_review` returns None raise `PlayStoreClientError("Review ... has no user comment")`; HttpError → `PlayStoreClientError`.
- `batch_get_orders(package_name, order_ids) -> list[Order]`: calls `orders().batchget(...)` (lowercase); maps each order via the existing `get_order` field convention (order_id/product_id/purchase_state/purchase_token). NOTE: the v3 Order schema differs (uses `state`/`lineItems`); this keeps parity with the existing `get_order` mapping — a fuller Order remap is a separate follow-up.
- Tests: get_review success / with-translation / no-user-comment-raises / HttpError; batch success / empty / HttpError. Verify existing `get_reviews` tests still pass (refactor safe).

### Task 2: MCP tools
- `get_review(package_name, review_id, translation_language=None)` (read) after the `reply_to_review` tool.
- `batch_get_orders(package_name, order_ids)` (read) after the `get_order` tool.
- Tests: both tools delegate to the client with correct kwargs.

### Task 3: Docs
- `docs/tools/reviews.md` — add `get_review` section.
- `docs/tools-reference.md` — add `get_review` (Review Tools) and `batch_get_orders` (Orders).

### Task 4: Verification gate
- `pytest --cov` (100% new-code), `ruff check`, `ruff format --check`, `mypy` — all clean.

## Self-Review
Both endpoints covered; no new models (reuse Review/Order); `_parse_review` shared DRY between get_reviews and get_review; `batchget` lowercase gotcha captured; reads not gated. Known limitation noted: batch_get_orders inherits get_order's flat Order mapping (v3 Order schema richer) — deferred.
