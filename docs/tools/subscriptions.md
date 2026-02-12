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
