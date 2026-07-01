# Purchase Management & Refunds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add purchase lifecycle management — `refund_order`, `cancel_subscription_purchase`, `defer_subscription_purchase`, `revoke_subscription_purchase` (writes), and `get_product_purchase_v2` (read) — completing the money-sensitive purchase surface.

**Architecture:** Three new Pydantic models, five `PlayStoreClient` methods wrapping `orders.refund`, `purchases.subscriptionsv2.{cancel,defer,revoke}`, and `purchases.productsv2.getproductpurchasev2`, and five `@mcp.tool()` wrappers. The four write tools are gated by the existing read-only flag (`_read_only_block`) and added to the read-only test's `WRITE_TOOLS`.

**Tech Stack:** Python 3.11+, `google-api-python-client` (Android Publisher v3), `pydantic`, `structlog`, `mcp` (FastMCP), `pytest`, `ruff`, `mypy`, `uv`.

## Global Constraints

- Python `>=3.11`; must pass `uv run --frozen ruff check`, `uv run --frozen ruff format --check`, `uv run --frozen mypy src/play_store_mcp`.
- No new runtime dependencies.
- Coverage: keep `src/play_store_mcp` at 100% statements. Every new branch (success + `HttpError` + validation) must be tested.
- Follow existing conventions exactly:
  - Read methods return a model; on `HttpError` → `raise PlayStoreClientError(f"Failed to ...: {e.reason}") from e` (see `get_order`, `get_subscription_purchase`).
  - Write methods return a result model with `success`/`message`; success = `.execute()` returns without raising (these APIs return empty bodies — do NOT assert status codes).
  - Read tools return `model.model_dump()`. Write tools: **first statement** is `if blocked := _read_only_block("<tool>"): return blocked`, then any input validation returning `{"error": ...}`, then `client = get_client_from_context()`.
  - Tool functions are synchronous `def` returning `dict[str, Any]`; MCP tool param for the purchase token is `purchase_token`, passed to the client as `token=` (matches `get_subscription_status`).
- **Authoritative API shapes (Android Publisher v3, discovery rev 20260701):**
  - `orders.refund` → `service.orders().refund(packageName=, orderId=, revoke=<bool>)` — `revoke` is a QUERY param, **no body**, empty response.
  - `subscriptionsv2.revoke` → `service.purchases().subscriptionsv2().revoke(packageName=, token=, body={"revocationContext": {"fullRefund": {}}})` (or `{"proratedRefund": {}}`) — empty response.
  - `subscriptionsv2.cancel` → `service.purchases().subscriptionsv2().cancel(packageName=, token=, body={"cancellationContext": {"cancellationType": "<enum>"}})` — enum ∈ `USER_REQUESTED_STOP_RENEWALS`, `DEVELOPER_REQUESTED_STOP_PAYMENTS`, `CANCELLATION_TYPE_UNSPECIFIED`; empty response.
  - `subscriptionsv2.defer` → `service.purchases().subscriptionsv2().defer(packageName=, token=, body={"deferralContext": {"deferDuration": "<e.g. 604800s>", "etag": "<etag>"}})` — response `{"itemExpiryTimeDetails": [{"productId","expiryTime"}]}`.
  - `productsv2.getproductpurchasev2` → `service.purchases().productsv2().getproductpurchasev2(packageName=, token=)` — **token only, no productId**; response fields: `orderId`, `acknowledgementState` (enum string), `purchaseCompletionTime` (RFC3339 string), `regionCode`, `productLineItem` (array), `obfuscatedExternalAccountId`, `obfuscatedExternalProfileId`, `testPurchaseContext` (presence ⇒ test purchase).
- Commit trailers on every commit:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01VtR3xYVpG3HwYJMASGbus2
  ```

---

## File Structure

- `src/play_store_mcp/models.py` (modify) — append `OrderRefundResult`, `SubscriptionActionResult`, `ProductPurchaseV2`.
- `src/play_store_mcp/client.py` (modify) — import the 3 models; add module constant `_REVOCATION_CONTEXTS`; add 5 methods after `get_product_purchase`/`acknowledge`/`consume` block (i.e. after `consume_product_purchase`, before the `# Batch Operations` divider).
- `src/play_store_mcp/server.py` (modify) — add 5 `@mcp.tool()` wrappers after `consume_product_purchase`; read-only-guard the 4 writes; `revoke_order`... (see Task 3).
- `tests/test_purchase_management.py` (create) — model, client, and server tool tests.
- `tests/test_read_only.py` (modify) — add the 4 new writes to `WRITE_TOOLS`.
- `docs/tools/subscriptions.md` (modify) — document the 5 tools.
- `docs/tools-reference.md` (modify) — add the 5 tools to the reference.

---

### Task 1: Models

**Files:**
- Modify: `src/play_store_mcp/models.py` (append after `ProductPurchaseActionResult`, end of file)
- Test: `tests/test_purchase_management.py` (create)

**Interfaces:**
- Produces:
  - `OrderRefundResult` — `success: bool`, `package_name: str`, `order_id: str`, `revoked: bool`, `message: str`, `error: str | None`.
  - `SubscriptionActionResult` — `success: bool`, `package_name: str`, `purchase_token: str`, `action: str`, `message: str`, `details: dict[str, Any] | None`, `error: str | None`.
  - `ProductPurchaseV2` — `package_name: str`, `purchase_token: str`, `order_id: str | None`, `acknowledgement_state: str | None`, `purchase_completion_time: str | None`, `region_code: str | None`, `product_line_items: list[dict[str, Any]]`, `obfuscated_external_account_id: str | None`, `obfuscated_external_profile_id: str | None`, `test_purchase: bool`.

- [ ] **Step 1: Write the failing tests (create `tests/test_purchase_management.py`)**

```python
"""Tests for purchase management tools (refund / cancel / defer / revoke / v2 read)."""

from __future__ import annotations

from play_store_mcp.models import OrderRefundResult, ProductPurchaseV2, SubscriptionActionResult


def test_order_refund_result():
    r = OrderRefundResult(
        success=True, package_name="com.example.app", order_id="GPA.1", revoked=True, message="ok"
    )
    assert r.success is True
    assert r.revoked is True
    assert r.error is None


def test_subscription_action_result_defaults():
    r = SubscriptionActionResult(
        success=True,
        package_name="com.example.app",
        purchase_token="tok",
        action="cancel",
        message="ok",
    )
    assert r.action == "cancel"
    assert r.details is None
    assert r.error is None


def test_product_purchase_v2_defaults():
    p = ProductPurchaseV2(package_name="com.example.app", purchase_token="tok")
    assert p.order_id is None
    assert p.product_line_items == []
    assert p.test_purchase is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --frozen pytest tests/test_purchase_management.py -v`
Expected: FAIL — `ImportError: cannot import name 'OrderRefundResult'`.

- [ ] **Step 3: Append the models to `src/play_store_mcp/models.py`**

Add at the end of the file (after `ProductPurchaseActionResult`):

```python
class OrderRefundResult(BaseModel):
    """Result of refunding an order."""

    success: bool = Field(..., description="Whether the refund succeeded")
    package_name: str = Field(..., description="App package name")
    order_id: str = Field(..., description="Order ID")
    revoked: bool = Field(..., description="Whether the entitlement was also revoked")
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")


class SubscriptionActionResult(BaseModel):
    """Result of a cancel/defer/revoke action on a subscription purchase."""

    success: bool = Field(..., description="Whether the action succeeded")
    package_name: str = Field(..., description="App package name")
    purchase_token: str = Field(..., description="Purchase token")
    action: str = Field(..., description="Action performed (cancel, defer, or revoke)")
    message: str = Field(..., description="Status message")
    details: dict[str, Any] | None = Field(None, description="Extra result data (e.g. defer expiry)")
    error: str | None = Field(None, description="Error details if failed")


class ProductPurchaseV2(BaseModel):
    """Status of an in-app product purchase (Purchases.productsv2)."""

    package_name: str = Field(..., description="App package name")
    purchase_token: str = Field(..., description="Purchase token")
    order_id: str | None = Field(None, description="Order ID")
    acknowledgement_state: str | None = Field(None, description="Acknowledgement state (enum)")
    purchase_completion_time: str | None = Field(
        None, description="Purchase completion time (RFC3339)"
    )
    region_code: str | None = Field(None, description="Billing region code")
    product_line_items: list[dict[str, Any]] = Field(
        default_factory=list, description="Purchased product line items"
    )
    obfuscated_external_account_id: str | None = Field(
        None, description="Obfuscated external account ID"
    )
    obfuscated_external_profile_id: str | None = Field(
        None, description="Obfuscated external profile ID"
    )
    test_purchase: bool = Field(False, description="Whether this is a test purchase")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --frozen pytest tests/test_purchase_management.py -v`
Expected: PASS (3 model tests).

- [ ] **Step 5: Commit**

```bash
git add src/play_store_mcp/models.py tests/test_purchase_management.py
git commit -m "feat: add purchase-management result models

<trailers>"
```

---

### Task 2: Client methods

**Files:**
- Modify: `src/play_store_mcp/client.py` (import 3 models; add `_REVOCATION_CONTEXTS` constant near the top after `logger = ...`; add 5 methods after `consume_product_purchase`, before the `# Batch Operations` divider)
- Test: `tests/test_purchase_management.py` (append)

**Interfaces:**
- Consumes: `OrderRefundResult`, `SubscriptionActionResult`, `ProductPurchaseV2` (Task 1); existing `self._get_service()`, `PlayStoreClientError`, `HttpError`.
- Produces:
  - `refund_order(package_name: str, order_id: str, revoke: bool = False) -> OrderRefundResult`
  - `cancel_subscription_purchase(package_name: str, token: str, cancellation_type: str = "USER_REQUESTED_STOP_RENEWALS") -> SubscriptionActionResult`
  - `defer_subscription_purchase(package_name: str, token: str, defer_duration: str, etag: str) -> SubscriptionActionResult`
  - `revoke_subscription_purchase(package_name: str, token: str, refund_type: str = "full") -> SubscriptionActionResult`
  - `get_product_purchase_v2(package_name: str, token: str) -> ProductPurchaseV2`
  - Module constant `_REVOCATION_CONTEXTS: dict[str, dict]` = `{"full": {"fullRefund": {}}, "prorated": {"proratedRefund": {}}}`.

- [ ] **Step 1: Write the failing tests (append to `tests/test_purchase_management.py`)**

```python
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from play_store_mcp.client import PlayStoreClient, PlayStoreClientError


def _make_http_error(reason: str = "boom") -> HttpError:
    resp = MagicMock()
    resp.status = 400
    resp.reason = reason
    err = HttpError(resp, b"{}")
    err.reason = reason
    return err


def _client(service: MagicMock) -> PlayStoreClient:
    client = PlayStoreClient(credentials_json={"type": "service_account"})
    client._service = service
    return client


def test_refund_order_success_with_revoke():
    service = MagicMock()
    client = _client(service)

    result = client.refund_order("com.example.app", "GPA.1", revoke=True)

    assert result.success is True
    assert result.revoked is True
    service.orders.return_value.refund.assert_called_once_with(
        packageName="com.example.app", orderId="GPA.1", revoke=True
    )


def test_refund_order_default_no_revoke():
    service = MagicMock()
    client = _client(service)

    result = client.refund_order("com.example.app", "GPA.1")

    assert result.revoked is False
    service.orders.return_value.refund.assert_called_once_with(
        packageName="com.example.app", orderId="GPA.1", revoke=False
    )


def test_refund_order_http_error():
    service = MagicMock()
    service.orders.return_value.refund.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to refund order"):
        client.refund_order("com.example.app", "GPA.1")


def _subs_v2(service: MagicMock) -> MagicMock:
    return service.purchases.return_value.subscriptionsv2.return_value


def test_cancel_subscription_success():
    service = MagicMock()
    client = _client(service)

    result = client.cancel_subscription_purchase("com.example.app", "tok")

    assert result.action == "cancel"
    _subs_v2(service).cancel.assert_called_once_with(
        packageName="com.example.app",
        token="tok",
        body={"cancellationContext": {"cancellationType": "USER_REQUESTED_STOP_RENEWALS"}},
    )


def test_cancel_subscription_http_error():
    service = MagicMock()
    _subs_v2(service).cancel.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to cancel subscription"):
        client.cancel_subscription_purchase("com.example.app", "tok")


def test_defer_subscription_success():
    service = MagicMock()
    _subs_v2(service).defer.return_value.execute.return_value = {
        "itemExpiryTimeDetails": [{"productId": "sub1", "expiryTime": "2026-02-01T00:00:00Z"}]
    }
    client = _client(service)

    result = client.defer_subscription_purchase("com.example.app", "tok", "604800s", "etag123")

    assert result.action == "defer"
    assert result.details == {
        "itemExpiryTimeDetails": [{"productId": "sub1", "expiryTime": "2026-02-01T00:00:00Z"}]
    }
    _subs_v2(service).defer.assert_called_once_with(
        packageName="com.example.app",
        token="tok",
        body={"deferralContext": {"deferDuration": "604800s", "etag": "etag123"}},
    )


def test_defer_subscription_http_error():
    service = MagicMock()
    _subs_v2(service).defer.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to defer subscription"):
        client.defer_subscription_purchase("com.example.app", "tok", "604800s", "etag")


def test_revoke_subscription_full():
    service = MagicMock()
    client = _client(service)

    result = client.revoke_subscription_purchase("com.example.app", "tok", refund_type="full")

    assert result.action == "revoke"
    _subs_v2(service).revoke.assert_called_once_with(
        packageName="com.example.app", token="tok", body={"revocationContext": {"fullRefund": {}}}
    )


def test_revoke_subscription_prorated():
    service = MagicMock()
    client = _client(service)

    client.revoke_subscription_purchase("com.example.app", "tok", refund_type="prorated")

    _subs_v2(service).revoke.assert_called_once_with(
        packageName="com.example.app",
        token="tok",
        body={"revocationContext": {"proratedRefund": {}}},
    )


def test_revoke_subscription_http_error():
    service = MagicMock()
    _subs_v2(service).revoke.return_value.execute.side_effect = _make_http_error("bad")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to revoke subscription"):
        client.revoke_subscription_purchase("com.example.app", "tok")


def _products_v2(service: MagicMock) -> MagicMock:
    return service.purchases.return_value.productsv2.return_value


def test_get_product_purchase_v2_success():
    service = MagicMock()
    _products_v2(service).getproductpurchasev2.return_value.execute.return_value = {
        "orderId": "GPA.2",
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        "purchaseCompletionTime": "2026-01-01T00:00:00Z",
        "regionCode": "US",
        "productLineItem": [{"productId": "coins"}],
        "testPurchaseContext": {},
    }
    client = _client(service)

    result = client.get_product_purchase_v2("com.example.app", "tok")

    assert result.order_id == "GPA.2"
    assert result.acknowledgement_state == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
    assert result.product_line_items == [{"productId": "coins"}]
    assert result.test_purchase is True
    _products_v2(service).getproductpurchasev2.assert_called_once_with(
        packageName="com.example.app", token="tok"
    )


def test_get_product_purchase_v2_minimal():
    service = MagicMock()
    _products_v2(service).getproductpurchasev2.return_value.execute.return_value = {}
    client = _client(service)

    result = client.get_product_purchase_v2("com.example.app", "tok")

    assert result.order_id is None
    assert result.product_line_items == []
    assert result.test_purchase is False


def test_get_product_purchase_v2_http_error():
    service = MagicMock()
    _products_v2(service).getproductpurchasev2.return_value.execute.side_effect = _make_http_error(
        "nope"
    )
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to get product purchase"):
        client.get_product_purchase_v2("com.example.app", "tok")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --frozen pytest tests/test_purchase_management.py -k "refund or cancel or defer or revoke or v2" -v`
Expected: FAIL — `AttributeError: 'PlayStoreClient' object has no attribute 'refund_order'`.

- [ ] **Step 3a: Import the models + add the constant in `client.py`**

In the `from play_store_mcp.models import (` block add (alphabetical): `OrderRefundResult,` (after `Order,`), `ProductPurchaseV2,` (after `ProductPurchaseActionResult,`), `SubscriptionActionResult,` (before `SubscriptionProduct,`).

After the `logger = structlog.get_logger(__name__)` line near the top of the file, add:

```python
_REVOCATION_CONTEXTS: dict[str, dict[str, dict]] = {
    "full": {"fullRefund": {}},
    "prorated": {"proratedRefund": {}},
}
```

- [ ] **Step 3b: Add the five methods after `consume_product_purchase`**

Insert immediately after the end of `consume_product_purchase` (before the `# =====...# Batch Operations` divider):

```python
    def refund_order(
        self,
        package_name: str,
        order_id: str,
        revoke: bool = False,
    ) -> OrderRefundResult:
        """Refund an order, optionally revoking the entitlement.

        Args:
            package_name: App package name.
            order_id: Order ID to refund.
            revoke: If True, also revoke the user's entitlement.

        Returns:
            Refund result with success status.
        """
        self._logger.info("Refunding order", package_name=package_name, order_id=order_id)
        service = self._get_service()

        try:
            service.orders().refund(
                packageName=package_name, orderId=order_id, revoke=revoke
            ).execute()

            message = "Order refunded successfully"
            if revoke:
                message += " and entitlement revoked"
            return OrderRefundResult(
                success=True,
                package_name=package_name,
                order_id=order_id,
                revoked=revoke,
                message=message,
            )

        except HttpError as e:
            self._logger.exception("Failed to refund order", error=str(e))
            raise PlayStoreClientError(f"Failed to refund order: {e.reason}") from e

    def cancel_subscription_purchase(
        self,
        package_name: str,
        token: str,
        cancellation_type: str = "USER_REQUESTED_STOP_RENEWALS",
    ) -> SubscriptionActionResult:
        """Cancel a subscription purchase.

        Args:
            package_name: App package name.
            token: Purchase token.
            cancellation_type: One of USER_REQUESTED_STOP_RENEWALS,
                DEVELOPER_REQUESTED_STOP_PAYMENTS, CANCELLATION_TYPE_UNSPECIFIED.

        Returns:
            Action result with success status.
        """
        self._logger.info("Cancelling subscription purchase", package_name=package_name)
        service = self._get_service()

        try:
            service.purchases().subscriptionsv2().cancel(
                packageName=package_name,
                token=token,
                body={"cancellationContext": {"cancellationType": cancellation_type}},
            ).execute()

            return SubscriptionActionResult(
                success=True,
                package_name=package_name,
                purchase_token=token,
                action="cancel",
                message="Subscription cancellation scheduled",
            )

        except HttpError as e:
            self._logger.exception("Failed to cancel subscription", error=str(e))
            raise PlayStoreClientError(f"Failed to cancel subscription: {e.reason}") from e

    def defer_subscription_purchase(
        self,
        package_name: str,
        token: str,
        defer_duration: str,
        etag: str,
    ) -> SubscriptionActionResult:
        """Defer a subscription purchase's next renewal.

        Args:
            package_name: App package name.
            token: Purchase token.
            defer_duration: Duration to defer, e.g. "604800s" (7 days).
            etag: Current etag of the subscription purchase.

        Returns:
            Action result with success status and new expiry details.
        """
        self._logger.info("Deferring subscription purchase", package_name=package_name)
        service = self._get_service()

        try:
            result = (
                service.purchases()
                .subscriptionsv2()
                .defer(
                    packageName=package_name,
                    token=token,
                    body={"deferralContext": {"deferDuration": defer_duration, "etag": etag}},
                )
                .execute()
            )

            return SubscriptionActionResult(
                success=True,
                package_name=package_name,
                purchase_token=token,
                action="defer",
                message="Subscription deferred",
                details={"itemExpiryTimeDetails": result.get("itemExpiryTimeDetails", [])},
            )

        except HttpError as e:
            self._logger.exception("Failed to defer subscription", error=str(e))
            raise PlayStoreClientError(f"Failed to defer subscription: {e.reason}") from e

    def revoke_subscription_purchase(
        self,
        package_name: str,
        token: str,
        refund_type: str = "full",
    ) -> SubscriptionActionResult:
        """Revoke (refund) a subscription purchase.

        Args:
            package_name: App package name.
            token: Purchase token.
            refund_type: "full" or "prorated".

        Returns:
            Action result with success status.
        """
        self._logger.info(
            "Revoking subscription purchase", package_name=package_name, refund_type=refund_type
        )
        service = self._get_service()

        try:
            service.purchases().subscriptionsv2().revoke(
                packageName=package_name,
                token=token,
                body={"revocationContext": _REVOCATION_CONTEXTS[refund_type]},
            ).execute()

            return SubscriptionActionResult(
                success=True,
                package_name=package_name,
                purchase_token=token,
                action="revoke",
                message=f"Subscription revoked ({refund_type} refund)",
            )

        except HttpError as e:
            self._logger.exception("Failed to revoke subscription", error=str(e))
            raise PlayStoreClientError(f"Failed to revoke subscription: {e.reason}") from e

    def get_product_purchase_v2(
        self,
        package_name: str,
        token: str,
    ) -> ProductPurchaseV2:
        """Get the status of an in-app product purchase (v2 API).

        Args:
            package_name: App package name.
            token: Purchase token (identifies the purchase; no product ID needed).

        Returns:
            Product purchase (v2) details.
        """
        self._logger.info("Getting product purchase (v2)", package_name=package_name)
        service = self._get_service()

        try:
            result = (
                service.purchases()
                .productsv2()
                .getproductpurchasev2(packageName=package_name, token=token)
                .execute()
            )

            return ProductPurchaseV2(
                package_name=package_name,
                purchase_token=token,
                order_id=result.get("orderId"),
                acknowledgement_state=result.get("acknowledgementState"),
                purchase_completion_time=result.get("purchaseCompletionTime"),
                region_code=result.get("regionCode"),
                product_line_items=result.get("productLineItem", []),
                obfuscated_external_account_id=result.get("obfuscatedExternalAccountId"),
                obfuscated_external_profile_id=result.get("obfuscatedExternalProfileId"),
                test_purchase="testPurchaseContext" in result,
            )

        except HttpError as e:
            self._logger.exception("Failed to get product purchase (v2)", error=str(e))
            raise PlayStoreClientError(f"Failed to get product purchase: {e.reason}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --frozen pytest tests/test_purchase_management.py -v`
Expected: PASS (models + all client tests).

- [ ] **Step 5: Lint / type-check**

Run: `uv run --frozen ruff check src tests && uv run --frozen mypy src/play_store_mcp`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/play_store_mcp/client.py tests/test_purchase_management.py
git commit -m "feat: add purchase-management client methods (refund/cancel/defer/revoke/v2)

<trailers>"
```

---

### Task 3: MCP tools + read-only gating

**Files:**
- Modify: `src/play_store_mcp/server.py` (add 5 tools after `consume_product_purchase`; guard the 4 writes)
- Modify: `tests/test_read_only.py` (add the 4 new writes to `WRITE_TOOLS`)
- Test: `tests/test_purchase_management.py` (append server-tool tests)

**Interfaces:**
- Consumes: client methods (Task 2); existing `get_client_from_context`, `_read_only_block`.
- Produces MCP tools (all return `dict[str, Any]`): `refund_order(package_name, order_id, revoke=False)`, `cancel_subscription_purchase(package_name, purchase_token, cancellation_type="USER_REQUESTED_STOP_RENEWALS")`, `defer_subscription_purchase(package_name, purchase_token, defer_duration, etag)`, `revoke_subscription_purchase(package_name, purchase_token, refund_type="full")`, `get_product_purchase_v2(package_name, purchase_token)`.

- [ ] **Step 1: Write failing tests (append server-tool tests to `tests/test_purchase_management.py`)**

```python
import play_store_mcp.server as server
from play_store_mcp.models import OrderRefundResult as _ORR
from play_store_mcp.models import ProductPurchaseV2 as _PPV2
from play_store_mcp.models import SubscriptionActionResult as _SAR


def test_tool_refund_order(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.refund_order.return_value = _ORR(
        success=True, package_name="com.example.app", order_id="GPA.1", revoked=True, message="ok"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.refund_order("com.example.app", "GPA.1", revoke=True)

    assert result["success"] is True
    mc.refund_order.assert_called_once_with(
        package_name="com.example.app", order_id="GPA.1", revoke=True
    )


def test_tool_cancel_subscription(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.cancel_subscription_purchase.return_value = _SAR(
        success=True, package_name="com.example.app", purchase_token="tok", action="cancel", message="ok"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.cancel_subscription_purchase("com.example.app", "tok")

    assert result["action"] == "cancel"
    mc.cancel_subscription_purchase.assert_called_once_with(
        package_name="com.example.app", token="tok", cancellation_type="USER_REQUESTED_STOP_RENEWALS"
    )


def test_tool_defer_subscription(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.defer_subscription_purchase.return_value = _SAR(
        success=True, package_name="com.example.app", purchase_token="tok", action="defer", message="ok"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.defer_subscription_purchase("com.example.app", "tok", "604800s", "etag")

    assert result["success"] is True
    mc.defer_subscription_purchase.assert_called_once_with(
        package_name="com.example.app", token="tok", defer_duration="604800s", etag="etag"
    )


def test_tool_revoke_subscription(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.revoke_subscription_purchase.return_value = _SAR(
        success=True, package_name="com.example.app", purchase_token="tok", action="revoke", message="ok"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.revoke_subscription_purchase("com.example.app", "tok", refund_type="prorated")

    assert result["success"] is True
    mc.revoke_subscription_purchase.assert_called_once_with(
        package_name="com.example.app", token="tok", refund_type="prorated"
    )


def test_tool_revoke_subscription_invalid_type(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.revoke_subscription_purchase("com.example.app", "tok", refund_type="bogus")

    assert "error" in result
    assert "full" in result["error"] and "prorated" in result["error"]
    mc.revoke_subscription_purchase.assert_not_called()


def test_tool_get_product_purchase_v2(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.get_product_purchase_v2.return_value = _PPV2(
        package_name="com.example.app", purchase_token="tok", order_id="GPA.2"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.get_product_purchase_v2("com.example.app", "tok")

    assert result["order_id"] == "GPA.2"
    mc.get_product_purchase_v2.assert_called_once_with(package_name="com.example.app", token="tok")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --frozen pytest tests/test_purchase_management.py -k tool -v`
Expected: FAIL — `AttributeError: module 'play_store_mcp.server' has no attribute 'refund_order'`.

- [ ] **Step 3a: Add the five tools to `server.py`**

Insert after the `consume_product_purchase` tool (before the next `# ===` section divider):

```python
@mcp.tool()
def refund_order(
    package_name: str,
    order_id: str,
    revoke: bool = False,
) -> dict[str, Any]:
    """Refund an order, optionally revoking the user's entitlement.

    Args:
        package_name: App package name
        order_id: Order ID to refund
        revoke: If True, also revoke the user's entitlement (default: False)

    Returns:
        Result with success status and details
    """
    if blocked := _read_only_block("refund_order"):
        return blocked
    client = get_client_from_context()

    result = client.refund_order(package_name=package_name, order_id=order_id, revoke=revoke)

    return result.model_dump()


@mcp.tool()
def cancel_subscription_purchase(
    package_name: str,
    purchase_token: str,
    cancellation_type: str = "USER_REQUESTED_STOP_RENEWALS",
) -> dict[str, Any]:
    """Cancel a subscription purchase.

    Args:
        package_name: App package name
        purchase_token: The purchase token from the client app
        cancellation_type: USER_REQUESTED_STOP_RENEWALS (default),
            DEVELOPER_REQUESTED_STOP_PAYMENTS, or CANCELLATION_TYPE_UNSPECIFIED

    Returns:
        Result with success status and details
    """
    if blocked := _read_only_block("cancel_subscription_purchase"):
        return blocked
    client = get_client_from_context()

    result = client.cancel_subscription_purchase(
        package_name=package_name,
        token=purchase_token,
        cancellation_type=cancellation_type,
    )

    return result.model_dump()


@mcp.tool()
def defer_subscription_purchase(
    package_name: str,
    purchase_token: str,
    defer_duration: str,
    etag: str,
) -> dict[str, Any]:
    """Defer a subscription purchase's next renewal.

    Args:
        package_name: App package name
        purchase_token: The purchase token from the client app
        defer_duration: Duration to defer, e.g. "604800s" for 7 days
        etag: Current etag of the subscription purchase

    Returns:
        Result with success status and new expiry details
    """
    if blocked := _read_only_block("defer_subscription_purchase"):
        return blocked
    client = get_client_from_context()

    result = client.defer_subscription_purchase(
        package_name=package_name,
        token=purchase_token,
        defer_duration=defer_duration,
        etag=etag,
    )

    return result.model_dump()


@mcp.tool()
def revoke_subscription_purchase(
    package_name: str,
    purchase_token: str,
    refund_type: str = "full",
) -> dict[str, Any]:
    """Revoke (refund) a subscription purchase.

    Args:
        package_name: App package name
        purchase_token: The purchase token from the client app
        refund_type: "full" or "prorated" (default: full)

    Returns:
        Result with success status and details
    """
    if blocked := _read_only_block("revoke_subscription_purchase"):
        return blocked
    if refund_type not in ("full", "prorated"):
        return {"error": "refund_type must be 'full' or 'prorated'"}
    client = get_client_from_context()

    result = client.revoke_subscription_purchase(
        package_name=package_name,
        token=purchase_token,
        refund_type=refund_type,
    )

    return result.model_dump()


@mcp.tool()
def get_product_purchase_v2(
    package_name: str,
    purchase_token: str,
) -> dict[str, Any]:
    """Get the status of an in-app product purchase using the v2 API.

    Unlike get_product_purchase, this identifies the purchase by token alone
    (no product ID) and returns line items and acknowledgement state.

    Args:
        package_name: App package name
        purchase_token: The purchase token from the client app

    Returns:
        Product purchase (v2) status
    """
    client = get_client_from_context()

    purchase = client.get_product_purchase_v2(package_name=package_name, token=purchase_token)

    return purchase.model_dump()
```

- [ ] **Step 3b: Add the four new writes to `tests/test_read_only.py` `WRITE_TOOLS`**

Append these four tuples to the `WRITE_TOOLS` list:

```python
    ("refund_order", {"package_name": "com.example.app", "order_id": "GPA.1"}),
    (
        "cancel_subscription_purchase",
        {"package_name": "com.example.app", "purchase_token": "tok"},
    ),
    (
        "defer_subscription_purchase",
        {"package_name": "com.example.app", "purchase_token": "tok", "defer_duration": "604800s", "etag": "e"},
    ),
    (
        "revoke_subscription_purchase",
        {"package_name": "com.example.app", "purchase_token": "tok"},
    ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --frozen pytest tests/test_purchase_management.py tests/test_read_only.py -v`
Expected: PASS — 6 new tool tests pass; the read-only parametrized test now covers the 4 new writes (guard returns before `get_client_from_context`; for `revoke_subscription_purchase` the read-only guard precedes the refund_type check, so it returns the read-only error).

- [ ] **Step 5: Full suite + coverage + lint + types**

Run:
```bash
uv run --frozen pytest --cov=play_store_mcp --cov-report=term-missing -q
uv run --frozen ruff check src tests && uv run --frozen ruff format --check src tests
uv run --frozen mypy src/play_store_mcp
```
Expected: all pass; `client.py`/`server.py` show no newly-uncovered lines (100% statements; only the two pre-existing unreachable branch arcs remain); ruff + mypy clean.

- [ ] **Step 6: Commit**

```bash
git add src/play_store_mcp/server.py tests/test_read_only.py tests/test_purchase_management.py
git commit -m "feat: add purchase-management MCP tools, gate writes with read-only

<trailers>"
```

---

### Task 4: Documentation

**Files:**
- Modify: `docs/tools/subscriptions.md` (append a "Purchase Management" section)
- Modify: `docs/tools-reference.md` (add the 5 tools)

- [ ] **Step 1: Append to `docs/tools/subscriptions.md`**

```markdown
## Purchase Management

Manage and refund purchases. All actions except `get_product_purchase_v2` are
writes and are disabled in [read-only mode](../configuration.md#read-only-mode).

### get_product_purchase_v2

Read a product purchase using the v2 API (token only — no product ID).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `purchase_token` | string | Yes | Purchase token from the client app |

### refund_order

Refund an order, optionally revoking the entitlement. **Write / money.**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `order_id` | string | Yes | Order ID to refund |
| `revoke` | boolean | No | Also revoke the user's entitlement (default: false) |

### cancel_subscription_purchase

Cancel a subscription. **Write.**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `purchase_token` | string | Yes | Purchase token |
| `cancellation_type` | string | No | `USER_REQUESTED_STOP_RENEWALS` (default), `DEVELOPER_REQUESTED_STOP_PAYMENTS`, or `CANCELLATION_TYPE_UNSPECIFIED` |

### defer_subscription_purchase

Defer a subscription's next renewal. **Write.**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `purchase_token` | string | Yes | Purchase token |
| `defer_duration` | string | Yes | Duration, e.g. `604800s` (7 days) |
| `etag` | string | Yes | Current etag of the subscription purchase |

### revoke_subscription_purchase

Revoke (refund) a subscription. **Write / money.**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `purchase_token` | string | Yes | Purchase token |
| `refund_type` | string | No | `full` (default) or `prorated` |
```

- [ ] **Step 2: Add the tools to `docs/tools-reference.md`**

Add a new section after the "In-App Products Tools" table:

```markdown
## Purchase Management Tools

| Tool | Description |
|---|---|
| [`get_product_purchase_v2`](tools/subscriptions.md#get_product_purchase_v2) | Read an in-app product purchase (v2, token only) |
| [`refund_order`](tools/subscriptions.md#refund_order) | Refund an order, optionally revoking entitlement (write) |
| [`cancel_subscription_purchase`](tools/subscriptions.md#cancel_subscription_purchase) | Cancel a subscription (write) |
| [`defer_subscription_purchase`](tools/subscriptions.md#defer_subscription_purchase) | Defer a subscription's next renewal (write) |
| [`revoke_subscription_purchase`](tools/subscriptions.md#revoke_subscription_purchase) | Revoke/refund a subscription (write) |
```

- [ ] **Step 3: Verify**

Run: `grep -rn "refund_order\|cancel_subscription_purchase\|defer_subscription_purchase\|revoke_subscription_purchase\|get_product_purchase_v2" docs/`
Expected: matches in both docs files.

- [ ] **Step 4: Commit**

```bash
git add docs/tools/subscriptions.md docs/tools-reference.md
git commit -m "docs: document purchase-management tools

<trailers>"
```

---

### Task 5: Final verification gate (before PR)

- [ ] **Step 1: Full quality gate**

Run:
```bash
uv run --frozen pytest --cov=play_store_mcp --cov-report=term-missing -q
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv run --frozen mypy src/play_store_mcp
```
Expected: all pass; 100% statements (only the two known unreachable branch arcs remain); ruff + format + mypy clean.

- [ ] **Step 2: Read-only smoke (no live API)**

Run:
```bash
PLAY_STORE_MCP_READ_ONLY=1 uv run --frozen python -c "
import play_store_mcp.server as s
for name in ('refund_order','cancel_subscription_purchase','defer_subscription_purchase','revoke_subscription_purchase'):
    fn = getattr(s, name)
    import inspect
    kwargs = {p: 'x' for p in inspect.signature(fn).parameters}
    print(name, '->', fn(**kwargs).get('error','NO-ERROR')[:30])
"
```
Expected: each of the 4 writes prints a `...read-only...` error (gated before any client/validation).

---

## Self-Review

**Spec coverage:** The chosen subsystem = purchase management & refunds: `refund_order` (orders.refund), `cancel_subscription_purchase` (subscriptionsv2.cancel), `defer_subscription_purchase` (subscriptionsv2.defer), `revoke_subscription_purchase` (subscriptionsv2.revoke), `get_product_purchase_v2` (productsv2). All five covered by Tasks 1–4; read-only gating for the 4 writes in Task 3; docs in Task 4. No gaps.

**Placeholder scan:** No TBD/TODO/"handle edge cases". Every code step shows full code; `<trailers>` is the literal commit-trailer block from Global Constraints. Every run step has an exact command + expected result.

**Type consistency:** Client methods take `token`; MCP tools expose `purchase_token` → passed as `token=` (matches `get_subscription_status`). Result types: `refund_order → OrderRefundResult`; `cancel/defer/revoke → SubscriptionActionResult`; `get_product_purchase_v2 → ProductPurchaseV2`. `refund_type` validated in the tool (`full`/`prorated`) and mapped via `_REVOCATION_CONTEXTS` in the client (same two keys). The read-only guard precedes the `refund_type` validation in `revoke_subscription_purchase`, so the read-only test (which sets `READ_ONLY=True` with default kwargs) exercises the guard branch. All four writes are added to both the server guard set and the read-only `WRITE_TOOLS`.
