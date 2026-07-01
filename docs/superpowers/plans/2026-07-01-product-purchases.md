# In-App Product Purchases (get / acknowledge / consume) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the complete `purchases.products` family — `get_product_purchase` (read), `acknowledge_product_purchase` (write), `consume_product_purchase` (write) — closing issue #60 and rounding out in-app product purchase support.

**Architecture:** Add two Pydantic models, three `PlayStoreClient` methods that wrap `service.purchases().products().{get,acknowledge,consume}`, and three `@mcp.tool()` wrappers. The two write tools are gated by the existing read-only flag (`_read_only_block`) exactly like the other write tools, and are added to the read-only test's `WRITE_TOOLS` list so their guard is covered.

**Tech Stack:** Python 3.11+, `google-api-python-client` (Android Publisher v3), `pydantic`, `structlog`, `mcp` (FastMCP), `pytest`, `ruff`, `mypy`, `uv`.

## Global Constraints

- Python `>=3.11`; must pass `uv run --frozen ruff check`, `uv run --frozen ruff format --check`, `uv run --frozen mypy src/play_store_mcp`.
- No new runtime dependencies.
- Coverage: keep `src/play_store_mcp` at 100% statements. Every new branch (success + `HttpError`) must be tested.
- Follow existing conventions exactly:
  - Read client methods return a model; on `HttpError` they `raise PlayStoreClientError(f"Failed to ...: {e.reason}") from e` (see `get_subscription_purchase`).
  - Write client methods return a small result model with `success`/`message`/`error` (see `ReviewReplyResult`).
  - Read tools: `return model.model_dump()`. Write tools: **first statement** is `if blocked := _read_only_block("<tool>"): return blocked`, then `client = get_client_from_context()`.
  - Tool functions are synchronous `def` returning `dict[str, Any]`; the Play client is obtained via `get_client_from_context()`.
- API facts (authoritative, Android Publisher v3):
  - `products.get` → `GET .../purchases/products/{productId}/tokens/{token}` → 200 with a `ProductPurchase` JSON body.
  - `products.acknowledge` → `POST .../:acknowledge` with body `{"developerPayload": <str>}` → **200, empty body**.
  - `products.consume` → `POST .../:consume`, no body → **200, empty body**.
  - Success = `.execute()` returns without raising; do NOT assert on HTTP status/204.
- Commit trailers on every commit:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01VtR3xYVpG3HwYJMASGbus2
  ```

---

## File Structure

- `src/play_store_mcp/models.py` (modify) — append `ProductPurchase` and `ProductPurchaseActionResult`.
- `src/play_store_mcp/client.py` (modify) — add `get_product_purchase`, `acknowledge_product_purchase`, `consume_product_purchase` after `list_voided_purchases`; import the two new models.
- `src/play_store_mcp/server.py` (modify) — add the three `@mcp.tool()` wrappers after the `list_voided_purchases` tool; read-only-guard the two writes.
- `tests/test_product_purchases.py` (create) — model, client (success + HttpError), and server tool tests.
- `tests/test_read_only.py` (modify) — add the two new write tools to `WRITE_TOOLS`.
- `docs/tools/subscriptions.md` (modify) — document the three tools.
- `docs/tools-reference.md` (modify) — add the three tools to the reference list.

---

### Task 1: Models

**Files:**
- Modify: `src/play_store_mcp/models.py` (append after the `ExpansionFile` class, end of file)
- Test: `tests/test_product_purchases.py` (create)

**Interfaces:**
- Produces:
  - `ProductPurchase` — fields: `package_name: str`, `product_id: str`, `purchase_token: str`, `order_id: str | None`, `purchase_state: int | None`, `consumption_state: int | None`, `acknowledgement_state: int | None`, `purchase_time: datetime | None`, `purchase_type: int | None`, `quantity: int | None`, `region_code: str | None`, `developer_payload: str | None`.
  - `ProductPurchaseActionResult` — fields: `success: bool`, `package_name: str`, `product_id: str`, `purchase_token: str`, `action: str`, `message: str`, `error: str | None`.

- [ ] **Step 1: Write the failing test (create `tests/test_product_purchases.py`)**

```python
"""Tests for in-app product purchase tools (get / acknowledge / consume)."""

from __future__ import annotations

from datetime import UTC, datetime

from play_store_mcp.models import ProductPurchase, ProductPurchaseActionResult


def test_product_purchase_model_defaults():
    p = ProductPurchase(package_name="com.example.app", product_id="sku1", purchase_token="tok")
    assert p.package_name == "com.example.app"
    assert p.product_id == "sku1"
    assert p.purchase_token == "tok"
    assert p.order_id is None
    assert p.purchase_state is None
    assert p.consumption_state is None
    assert p.acknowledgement_state is None


def test_product_purchase_model_full():
    p = ProductPurchase(
        package_name="com.example.app",
        product_id="sku1",
        purchase_token="tok",
        order_id="GPA.1",
        purchase_state=0,
        consumption_state=0,
        acknowledgement_state=1,
        purchase_time=datetime(2026, 1, 1, tzinfo=UTC),
        purchase_type=0,
        quantity=1,
        region_code="US",
        developer_payload="payload",
    )
    assert p.acknowledgement_state == 1
    assert p.region_code == "US"


def test_product_purchase_action_result():
    r = ProductPurchaseActionResult(
        success=True,
        package_name="com.example.app",
        product_id="sku1",
        purchase_token="tok",
        action="consume",
        message="ok",
    )
    assert r.success is True
    assert r.action == "consume"
    assert r.error is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --frozen pytest tests/test_product_purchases.py -v`
Expected: FAIL — `ImportError: cannot import name 'ProductPurchase' from 'play_store_mcp.models'`.

- [ ] **Step 3: Append the models to `src/play_store_mcp/models.py`**

Add at the end of the file (after the `ExpansionFile` class):

```python
class ProductPurchase(BaseModel):
    """Status of an in-app product purchase."""

    package_name: str = Field(..., description="App package name")
    product_id: str = Field(..., description="In-app product SKU")
    purchase_token: str = Field(..., description="Purchase token")
    order_id: str | None = Field(None, description="Order ID")
    purchase_state: int | None = Field(
        None, description="Purchase state (0=purchased, 1=canceled, 2=pending)"
    )
    consumption_state: int | None = Field(
        None, description="Consumption state (0=yet to be consumed, 1=consumed)"
    )
    acknowledgement_state: int | None = Field(
        None, description="Acknowledgement state (0=not acknowledged, 1=acknowledged)"
    )
    purchase_time: datetime | None = Field(None, description="Purchase time")
    purchase_type: int | None = Field(
        None, description="Purchase type (0=test, 1=promo, 2=rewarded)"
    )
    quantity: int | None = Field(None, description="Quantity purchased")
    region_code: str | None = Field(None, description="Billing region code")
    developer_payload: str | None = Field(None, description="Developer-supplied payload")


class ProductPurchaseActionResult(BaseModel):
    """Result of an acknowledge/consume action on an in-app product purchase."""

    success: bool = Field(..., description="Whether the action succeeded")
    package_name: str = Field(..., description="App package name")
    product_id: str = Field(..., description="In-app product SKU")
    purchase_token: str = Field(..., description="Purchase token")
    action: str = Field(..., description="Action performed (acknowledge or consume)")
    message: str = Field(..., description="Status message")
    error: str | None = Field(None, description="Error details if failed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --frozen pytest tests/test_product_purchases.py -v`
Expected: PASS (3 model tests).

- [ ] **Step 5: Commit**

```bash
git add src/play_store_mcp/models.py tests/test_product_purchases.py
git commit -m "feat: add ProductPurchase and ProductPurchaseActionResult models

<trailers>"
```

---

### Task 2: Client methods

**Files:**
- Modify: `src/play_store_mcp/client.py` (add 3 methods immediately after `list_voided_purchases`, before the `# Batch Operations` section divider; add the 2 new models to the `from play_store_mcp.models import (...)` block)
- Test: `tests/test_product_purchases.py` (append)

**Interfaces:**
- Consumes: `ProductPurchase`, `ProductPurchaseActionResult` (Task 1); existing `self._get_service()`, `PlayStoreClientError`, `HttpError`, `datetime`, `UTC`.
- Produces:
  - `PlayStoreClient.get_product_purchase(package_name: str, product_id: str, token: str) -> ProductPurchase`
  - `PlayStoreClient.acknowledge_product_purchase(package_name: str, product_id: str, token: str, developer_payload: str | None = None) -> ProductPurchaseActionResult`
  - `PlayStoreClient.consume_product_purchase(package_name: str, product_id: str, token: str) -> ProductPurchaseActionResult`

- [ ] **Step 1: Write the failing tests (append to `tests/test_product_purchases.py`)**

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


def _client_with_products(products_mock: MagicMock) -> PlayStoreClient:
    client = PlayStoreClient(credentials_json={"type": "service_account"})
    service = MagicMock()
    service.purchases.return_value.products.return_value = products_mock
    client._service = service
    return client


def test_get_product_purchase_success():
    products = MagicMock()
    products.get.return_value.execute.return_value = {
        "orderId": "GPA.1",
        "purchaseState": 0,
        "consumptionState": 0,
        "acknowledgementState": 1,
        "purchaseTimeMillis": "1767225600000",
        "purchaseType": 0,
        "quantity": 1,
        "regionCode": "US",
        "developerPayload": "pl",
    }
    client = _client_with_products(products)

    result = client.get_product_purchase("com.example.app", "sku1", "tok")

    assert result.order_id == "GPA.1"
    assert result.acknowledgement_state == 1
    assert result.region_code == "US"
    assert result.purchase_time is not None
    products.get.assert_called_once_with(packageName="com.example.app", productId="sku1", token="tok")


def test_get_product_purchase_no_time():
    products = MagicMock()
    products.get.return_value.execute.return_value = {"purchaseState": 2}
    client = _client_with_products(products)

    result = client.get_product_purchase("com.example.app", "sku1", "tok")

    assert result.purchase_time is None
    assert result.purchase_state == 2


def test_get_product_purchase_http_error():
    products = MagicMock()
    products.get.return_value.execute.side_effect = _make_http_error("not found")
    client = _client_with_products(products)

    with pytest.raises(PlayStoreClientError, match="Failed to get product purchase"):
        client.get_product_purchase("com.example.app", "sku1", "tok")


def test_acknowledge_product_purchase_success_with_payload():
    products = MagicMock()
    client = _client_with_products(products)

    result = client.acknowledge_product_purchase("com.example.app", "sku1", "tok", developer_payload="pl")

    assert result.success is True
    assert result.action == "acknowledge"
    products.acknowledge.assert_called_once_with(
        packageName="com.example.app", productId="sku1", token="tok", body={"developerPayload": "pl"}
    )


def test_acknowledge_product_purchase_success_no_payload():
    products = MagicMock()
    client = _client_with_products(products)

    result = client.acknowledge_product_purchase("com.example.app", "sku1", "tok")

    assert result.success is True
    products.acknowledge.assert_called_once_with(
        packageName="com.example.app", productId="sku1", token="tok", body={}
    )


def test_acknowledge_product_purchase_http_error():
    products = MagicMock()
    products.acknowledge.return_value.execute.side_effect = _make_http_error("bad")
    client = _client_with_products(products)

    with pytest.raises(PlayStoreClientError, match="Failed to acknowledge product purchase"):
        client.acknowledge_product_purchase("com.example.app", "sku1", "tok")


def test_consume_product_purchase_success():
    products = MagicMock()
    client = _client_with_products(products)

    result = client.consume_product_purchase("com.example.app", "sku1", "tok")

    assert result.success is True
    assert result.action == "consume"
    products.consume.assert_called_once_with(packageName="com.example.app", productId="sku1", token="tok")


def test_consume_product_purchase_http_error():
    products = MagicMock()
    products.consume.return_value.execute.side_effect = _make_http_error("bad")
    client = _client_with_products(products)

    with pytest.raises(PlayStoreClientError, match="Failed to consume product purchase"):
        client.consume_product_purchase("com.example.app", "sku1", "tok")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --frozen pytest tests/test_product_purchases.py -k "product_purchase and (success or error or no_time)" -v`
Expected: FAIL — `AttributeError: 'PlayStoreClient' object has no attribute 'get_product_purchase'`.

- [ ] **Step 3a: Import the new models in `client.py`**

In the `from play_store_mcp.models import (` block, add `ProductPurchase,` and `ProductPurchaseActionResult,` (keep alphabetical/consistent with the existing list).

- [ ] **Step 3b: Add the three methods after `list_voided_purchases`**

Insert immediately after the end of `list_voided_purchases` and before the `# =====...` / `# Batch Operations` divider that follows it:

```python
    def get_product_purchase(
        self,
        package_name: str,
        product_id: str,
        token: str,
    ) -> ProductPurchase:
        """Get the status of an in-app product purchase.

        Args:
            package_name: App package name.
            product_id: In-app product SKU.
            token: Purchase token.

        Returns:
            Product purchase details.
        """
        self._logger.info(
            "Getting product purchase", package_name=package_name, product_id=product_id
        )
        service = self._get_service()

        try:
            result = (
                service.purchases()
                .products()
                .get(packageName=package_name, productId=product_id, token=token)
                .execute()
            )

            purchase_time = (
                datetime.fromtimestamp(int(result["purchaseTimeMillis"]) / 1000, tz=UTC)
                if result.get("purchaseTimeMillis")
                else None
            )

            return ProductPurchase(
                package_name=package_name,
                product_id=product_id,
                purchase_token=token,
                order_id=result.get("orderId"),
                purchase_state=result.get("purchaseState"),
                consumption_state=result.get("consumptionState"),
                acknowledgement_state=result.get("acknowledgementState"),
                purchase_time=purchase_time,
                purchase_type=result.get("purchaseType"),
                quantity=result.get("quantity"),
                region_code=result.get("regionCode"),
                developer_payload=result.get("developerPayload"),
            )

        except HttpError as e:
            self._logger.exception("Failed to get product purchase", error=str(e))
            raise PlayStoreClientError(f"Failed to get product purchase: {e.reason}") from e

    def acknowledge_product_purchase(
        self,
        package_name: str,
        product_id: str,
        token: str,
        developer_payload: str | None = None,
    ) -> ProductPurchaseActionResult:
        """Acknowledge an in-app product purchase.

        Args:
            package_name: App package name.
            product_id: In-app product SKU.
            token: Purchase token.
            developer_payload: Optional payload to attach to the purchase.

        Returns:
            Action result with success status.
        """
        self._logger.info(
            "Acknowledging product purchase", package_name=package_name, product_id=product_id
        )
        service = self._get_service()
        body = {"developerPayload": developer_payload} if developer_payload else {}

        try:
            service.purchases().products().acknowledge(
                packageName=package_name,
                productId=product_id,
                token=token,
                body=body,
            ).execute()

            return ProductPurchaseActionResult(
                success=True,
                package_name=package_name,
                product_id=product_id,
                purchase_token=token,
                action="acknowledge",
                message="Purchase acknowledged successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to acknowledge product purchase", error=str(e))
            raise PlayStoreClientError(
                f"Failed to acknowledge product purchase: {e.reason}"
            ) from e

    def consume_product_purchase(
        self,
        package_name: str,
        product_id: str,
        token: str,
    ) -> ProductPurchaseActionResult:
        """Consume an in-app product purchase.

        Args:
            package_name: App package name.
            product_id: In-app product SKU.
            token: Purchase token.

        Returns:
            Action result with success status.
        """
        self._logger.info(
            "Consuming product purchase", package_name=package_name, product_id=product_id
        )
        service = self._get_service()

        try:
            service.purchases().products().consume(
                packageName=package_name,
                productId=product_id,
                token=token,
            ).execute()

            return ProductPurchaseActionResult(
                success=True,
                package_name=package_name,
                product_id=product_id,
                purchase_token=token,
                action="consume",
                message="Purchase consumed successfully",
            )

        except HttpError as e:
            self._logger.exception("Failed to consume product purchase", error=str(e))
            raise PlayStoreClientError(f"Failed to consume product purchase: {e.reason}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --frozen pytest tests/test_product_purchases.py -v`
Expected: PASS (all model + client tests).

- [ ] **Step 5: Lint / type-check**

Run: `uv run --frozen ruff check src tests && uv run --frozen mypy src/play_store_mcp`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/play_store_mcp/client.py tests/test_product_purchases.py
git commit -m "feat: add product purchase client methods (get/acknowledge/consume)

<trailers>"
```

---

### Task 3: MCP tools + read-only gating

**Files:**
- Modify: `src/play_store_mcp/server.py` (add 3 tools after the `list_voided_purchases` tool at line ~549; guard the 2 writes)
- Modify: `tests/test_read_only.py` (add the 2 new writes to `WRITE_TOOLS`)
- Test: `tests/test_product_purchases.py` (append server-tool tests)

**Interfaces:**
- Consumes: client methods (Task 2); existing `get_client_from_context`, `_read_only_block`.
- Produces MCP tools: `get_product_purchase(package_name, product_id, purchase_token)`, `acknowledge_product_purchase(package_name, product_id, purchase_token, developer_payload=None)`, `consume_product_purchase(package_name, product_id, purchase_token)` — each returns `dict[str, Any]`.

- [ ] **Step 1: Write failing tests (append server-tool tests to `tests/test_product_purchases.py`)**

```python
import play_store_mcp.server as server
from play_store_mcp.models import ProductPurchase as _PP
from play_store_mcp.models import ProductPurchaseActionResult as _PPR


def test_tool_get_product_purchase(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mock_client = MagicMock()
    mock_client.get_product_purchase.return_value = _PP(
        package_name="com.example.app", product_id="sku1", purchase_token="tok", purchase_state=0
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mock_client)

    result = server.get_product_purchase("com.example.app", "sku1", "tok")

    assert result["purchase_state"] == 0
    mock_client.get_product_purchase.assert_called_once_with(
        package_name="com.example.app", product_id="sku1", token="tok"
    )


def test_tool_acknowledge_product_purchase(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mock_client = MagicMock()
    mock_client.acknowledge_product_purchase.return_value = _PPR(
        success=True, package_name="com.example.app", product_id="sku1",
        purchase_token="tok", action="acknowledge", message="ok",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mock_client)

    result = server.acknowledge_product_purchase("com.example.app", "sku1", "tok", developer_payload="pl")

    assert result["success"] is True
    mock_client.acknowledge_product_purchase.assert_called_once_with(
        package_name="com.example.app", product_id="sku1", token="tok", developer_payload="pl"
    )


def test_tool_consume_product_purchase(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mock_client = MagicMock()
    mock_client.consume_product_purchase.return_value = _PPR(
        success=True, package_name="com.example.app", product_id="sku1",
        purchase_token="tok", action="consume", message="ok",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mock_client)

    result = server.consume_product_purchase("com.example.app", "sku1", "tok")

    assert result["success"] is True
    mock_client.consume_product_purchase.assert_called_once_with(
        package_name="com.example.app", product_id="sku1", token="tok"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --frozen pytest tests/test_product_purchases.py -k tool -v`
Expected: FAIL — `AttributeError: module 'play_store_mcp.server' has no attribute 'get_product_purchase'`.

- [ ] **Step 3a: Add the three tools to `server.py`**

Insert after the `list_voided_purchases` tool (after line ~549, before the next `# ===` section divider):

```python
@mcp.tool()
def get_product_purchase(
    package_name: str,
    product_id: str,
    purchase_token: str,
) -> dict[str, Any]:
    """Get the status of an in-app product purchase.

    Args:
        package_name: App package name
        product_id: In-app product SKU
        purchase_token: The purchase token from the client app

    Returns:
        Product purchase status (purchase/consumption/acknowledgement state, order, region)
    """
    client = get_client_from_context()

    purchase = client.get_product_purchase(
        package_name=package_name,
        product_id=product_id,
        token=purchase_token,
    )

    return purchase.model_dump()


@mcp.tool()
def acknowledge_product_purchase(
    package_name: str,
    product_id: str,
    purchase_token: str,
    developer_payload: str | None = None,
) -> dict[str, Any]:
    """Acknowledge an in-app product purchase.

    Purchases not acknowledged within 3 days are automatically refunded.

    Args:
        package_name: App package name
        product_id: In-app product SKU
        purchase_token: The purchase token from the client app
        developer_payload: Optional payload to associate with the purchase

    Returns:
        Result with success status and details
    """
    if blocked := _read_only_block("acknowledge_product_purchase"):
        return blocked
    client = get_client_from_context()

    result = client.acknowledge_product_purchase(
        package_name=package_name,
        product_id=product_id,
        token=purchase_token,
        developer_payload=developer_payload,
    )

    return result.model_dump()


@mcp.tool()
def consume_product_purchase(
    package_name: str,
    product_id: str,
    purchase_token: str,
) -> dict[str, Any]:
    """Consume an in-app product purchase (for consumable products).

    Marks the product as consumed so the user can purchase it again.

    Args:
        package_name: App package name
        product_id: In-app product SKU
        purchase_token: The purchase token from the client app

    Returns:
        Result with success status and details
    """
    if blocked := _read_only_block("consume_product_purchase"):
        return blocked
    client = get_client_from_context()

    result = client.consume_product_purchase(
        package_name=package_name,
        product_id=product_id,
        token=purchase_token,
    )

    return result.model_dump()
```

- [ ] **Step 3b: Add the two new writes to `tests/test_read_only.py` `WRITE_TOOLS`**

Add these two tuples to the `WRITE_TOOLS` list (so their read-only guard lines are exercised):

```python
    (
        "acknowledge_product_purchase",
        {"package_name": "com.example.app", "product_id": "sku1", "purchase_token": "tok"},
    ),
    (
        "consume_product_purchase",
        {"package_name": "com.example.app", "product_id": "sku1", "purchase_token": "tok"},
    ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --frozen pytest tests/test_product_purchases.py tests/test_read_only.py -v`
Expected: PASS — the 3 new tool tests pass, and the read-only parametrized test now covers 11 write tools including the two new ones.

- [ ] **Step 5: Full suite + coverage + lint + types**

Run:
```bash
uv run --frozen pytest --cov=play_store_mcp --cov-report=term-missing -q
uv run --frozen ruff check src tests && uv run --frozen ruff format --check src tests
uv run --frozen mypy src/play_store_mcp
```
Expected: all pass; `client.py` and `server.py` show no newly-uncovered lines (100% statements; only the two pre-existing unreachable branch arcs remain); ruff + mypy clean.

- [ ] **Step 6: Commit**

```bash
git add src/play_store_mcp/server.py tests/test_read_only.py tests/test_product_purchases.py
git commit -m "feat: add product purchase MCP tools (get/acknowledge/consume), gate writes

<trailers>"
```

---

### Task 4: Documentation

**Files:**
- Modify: `docs/tools/subscriptions.md`
- Modify: `docs/tools-reference.md`

**Interfaces:** none (docs).

- [ ] **Step 1: Document the tools in `docs/tools/subscriptions.md`**

Append a new section at the end of the file:

```markdown
## In-App Product Purchases

Tools for verifying and managing one-time (managed) in-app product purchases via
purchase tokens obtained from the client app.

### `get_product_purchase`

Read the status of a product purchase.

- `package_name` — app package name
- `product_id` — in-app product SKU
- `purchase_token` — purchase token from the client app

Returns purchase state, consumption state, acknowledgement state, order ID, and region.

### `acknowledge_product_purchase`

Acknowledge a purchase. **Purchases not acknowledged within 3 days are automatically refunded.**

- `package_name`, `product_id`, `purchase_token`
- `developer_payload` — optional payload to associate with the purchase

Disabled in [read-only mode](../configuration.md#read-only-mode).

### `consume_product_purchase`

Consume a purchase so a consumable product can be bought again.

- `package_name`, `product_id`, `purchase_token`

Disabled in [read-only mode](../configuration.md#read-only-mode).
```

- [ ] **Step 2: Add the tools to `docs/tools-reference.md`**

Add these three entries to the tool listing (match the file's existing formatting — bullet or table row per tool):

```markdown
- `get_product_purchase` — Get the status of an in-app product purchase
- `acknowledge_product_purchase` — Acknowledge an in-app product purchase (write)
- `consume_product_purchase` — Consume an in-app product purchase (write)
```

- [ ] **Step 3: Verify docs mention the tools**

Run: `grep -rn "consume_product_purchase\|acknowledge_product_purchase\|get_product_purchase" docs/`
Expected: matches in both `docs/tools/subscriptions.md` and `docs/tools-reference.md`.

- [ ] **Step 4: Commit**

```bash
git add docs/tools/subscriptions.md docs/tools-reference.md
git commit -m "docs: document in-app product purchase tools

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
Expected: all tests pass; `src/play_store_mcp` at 100% statements (only the two known unreachable branch arcs remain); ruff + format + mypy clean.

- [ ] **Step 2: Read-only parity smoke (no live API)**

Run:
```bash
PLAY_STORE_MCP_READ_ONLY=1 uv run --frozen python -c "
import play_store_mcp.server as s
print('consume (read-only) ->', s.consume_product_purchase('com.x','sku','tok'))
print('acknowledge (read-only) ->', s.acknowledge_product_purchase('com.x','sku','tok'))
"
```
Expected: both return `{'error': '...read-only...'}` (writes gated; no client/creds needed).

---

## Deferred (research output — file as separate issues, NOT in this PR)

The full Android Publisher v3 audit (see the research summary in the session) found many more missing endpoints beyond `purchases.products`. Per the issue's own "split into separate issues" guidance and the writing-plans scope rule (one subsystem per plan), these are **out of scope here** and should each become their own issue/plan:

- Subscription catalog CRUD (`monetization.subscriptions` create/patch/delete/batch*/get/batchGet)
- Subscription base plans (`basePlans` activate/deactivate/delete/migratePrices/batch*)
- Subscription offers (`basePlans.offers` full tree)
- One-time products + purchase options + offers (`monetization.onetimeproducts` tree)
- In-app products write/batch ops (`inappproducts` insert/update/patch/delete/batch*)
- External transactions / alt-billing (`externaltransactions` create/get/refund)
- Edit upload pipeline (`edits.apks`/`bundles`/`deobfuscationfiles`/`expansionfiles` upload)
- Edit store-listing images (`edits.images` list/upload/delete/deleteall)
- Publisher account access (`users` + `grants`)
- Device tier configs (`applications.deviceTierConfigs`)
- App data safety (`applications.dataSafety`)
- App recovery actions (`apprecovery`)
- Generated APKs (`generatedapks` list/download)
- System APK variants (`systemapks.variants`)
- Internal app sharing uploads (`internalappsharingartifacts`)
- Money-sensitive purchase siblings (`orders.refund`, `purchases.subscriptionsv2` cancel/defer/revoke) — need extra guardrails; the new `--read-only` flag will gate them.

Small read-only siblings that could be quick wins in a later batch: `reviews.get`, `edits.get`, `edits.listings.get`, `edits.tracks.get`, `edits.testers.get`, `orders.batchget`, `purchases.productsv2.getproductpurchasev2`, `monetization.subscriptions.get/batchGet`.

---

## Self-Review

**Spec coverage:** Issue #60 asks for a `consume_product_purchase` client method + MCP tool returning a structured result (package, product, token, success, message, error) + tests + docs. Covered by Tasks 1–4, plus the natural `get`/`acknowledge` siblings that complete the family. The "research other gaps" ask is satisfied by the Deferred section + the session research report. No gaps.

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to". Every code step contains full code; the `<trailers>` token in commit messages is the literal commit trailer block from Global Constraints. Every run step has an exact command + expected result.

**Type consistency:** `get_product_purchase(...) -> ProductPurchase`; `acknowledge_product_purchase(..., developer_payload=None) -> ProductPurchaseActionResult`; `consume_product_purchase(...) -> ProductPurchaseActionResult`. Client methods take `token`; MCP tools expose `purchase_token` and pass it as `token=` (matching the existing `get_subscription_status` → `get_subscription_purchase(token=...)` convention). Model field names (`purchase_state`, `consumption_state`, `acknowledgement_state`, `region_code`, `developer_payload`, `action`) are used identically in models, client construction, and tests. The two writes are added to both the server guard set and the read-only test's `WRITE_TOOLS`.
