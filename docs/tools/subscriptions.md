# Subscriptions & In-App Products

Tools for managing monetization — subscriptions, in-app products, and voided purchases.

---

## list_subscriptions

List all subscription products for an app.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |

Each subscription includes: `product_id`, `status`, `base_plans`

```python
list_subscriptions("com.example.myapp")
```

---

## get_subscription_status

Check the status of a specific subscription purchase.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `subscription_id` | string | Yes | Subscription product ID |
| `purchase_token` | string | Yes | Purchase token from the client app |

Returns: `order_id`, `start_time`, `expiry_time`, `auto_renewing`, `cancel_reason`, `payment_state`, `price_currency`, `price_amount_micros`

```python
get_subscription_status(
    package_name="com.example.myapp",
    subscription_id="premium_monthly",
    purchase_token="token-from-client-app"
)
```

---

## list_voided_purchases

List voided purchases (refunds, chargebacks).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `max_results` | int | No | `100` | Maximum results to return |

Each voided purchase includes: `purchase_token`, `order_id`, `voided_time`, `voided_reason`, `voided_source`

```python
list_voided_purchases("com.example.myapp", max_results=50)
```

---

## list_in_app_products

List all in-app products (managed products) for an app.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |

Each product includes: `sku`, `product_type`, `status`, `title`, `description`, `default_price`

```python
list_in_app_products("com.example.myapp")
```

---

## get_in_app_product

Get details of a specific in-app product.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `sku` | string | Yes | Product SKU identifier |

```python
get_in_app_product("com.example.myapp", sku="premium_upgrade")
```

---

## get_product_purchase

Check the status of a one-time (managed) in-app product purchase using a purchase token from the client app.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | In-app product SKU |
| `purchase_token` | string | Yes | Purchase token from the client app |

Returns purchase state, consumption state, acknowledgement state, order ID, and region.

```python
get_product_purchase("com.example.myapp", product_id="premium_upgrade", purchase_token="tok...")
```

---

## acknowledge_product_purchase

Acknowledge a product purchase. **Purchases not acknowledged within 3 days are automatically refunded.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | In-app product SKU |
| `purchase_token` | string | Yes | Purchase token from the client app |
| `developer_payload` | string | No | Optional payload to associate with the purchase |

```python
acknowledge_product_purchase("com.example.myapp", product_id="premium_upgrade", purchase_token="tok...")
```

---

## consume_product_purchase

Consume a product purchase so a consumable product can be purchased again. Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | In-app product SKU |
| `purchase_token` | string | Yes | Purchase token from the client app |

```python
consume_product_purchase("com.example.myapp", product_id="coins_100", purchase_token="tok...")
```

---

## In-App Product Management

Create, update, and delete in-app products (managed products) in your catalog.
All tools here except `batch_get_in_app_products` are writes and are disabled in
[read-only mode](../configuration.md#read-only-mode).

The `product` parameter is an
[InAppProduct](https://developers.google.com/android-publisher/api-ref/rest/v3/inappproducts)
resource body — for example `sku`, `purchaseType` (`managedProduct` or
`subscription`), `defaultLanguage`, `defaultPrice`, `prices`, `listings`, and
`status`.

### create_in_app_product

Create a new in-app product. **Write.**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product` | object | Yes | InAppProduct resource body |

```python
create_in_app_product(
    package_name="com.example.myapp",
    product={
        "sku": "premium_upgrade",
        "purchaseType": "managedProduct",
        "defaultLanguage": "en-US",
        "status": "active",
        "defaultPrice": {"priceMicros": "990000", "currency": "USD"},
        "listings": {"en-US": {"title": "Premium Upgrade", "description": "Unlock everything"}},
    },
)
```

### update_in_app_product

Update (replace) an existing in-app product. **Write.**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `sku` | string | Yes | — | Product SKU identifier |
| `product` | object | Yes | — | InAppProduct resource body |
| `auto_convert_missing_prices` | boolean | No | `false` | Auto-convert prices for regions without a specified price from the default price |

```python
update_in_app_product(
    package_name="com.example.myapp",
    sku="premium_upgrade",
    product={"sku": "premium_upgrade", "status": "active", "defaultPrice": {"priceMicros": "1990000", "currency": "USD"}},
    auto_convert_missing_prices=True,
)
```

### patch_in_app_product

Partially update an existing in-app product. **Write.**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `sku` | string | Yes | Product SKU identifier |
| `product` | object | Yes | Partial InAppProduct body with only the fields to change |

```python
patch_in_app_product("com.example.myapp", sku="premium_upgrade", product={"status": "inactive"})
```

### delete_in_app_product

Delete an in-app product from the catalog. **Write.**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `sku` | string | Yes | Product SKU identifier |

```python
delete_in_app_product("com.example.myapp", sku="premium_upgrade")
```

### batch_get_in_app_products

Get details for multiple in-app products at once. Read-only (available in read-only mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `skus` | array of string | Yes | Product SKUs to retrieve |

Returns a list of products in the same order as requested.

```python
batch_get_in_app_products("com.example.myapp", skus=["premium_upgrade", "coins_100"])
```

### batch_delete_in_app_products

Delete multiple in-app products in a single operation (up to 100). **Write.**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `skus` | array of string | Yes | Product SKUs to delete |

```python
batch_delete_in_app_products("com.example.myapp", skus=["premium_upgrade", "coins_100"])
```

---

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
