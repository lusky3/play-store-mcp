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

## Subscription Catalog Management

Create, patch, and delete subscription products (`monetization.subscriptions`) in
your catalog. All tools here except `get_subscription` and
`batch_get_subscriptions` are writes and are disabled in
[read-only mode](../configuration.md#read-only-mode).

The `subscription` parameter is a
[Subscription](https://developers.google.com/android-publisher/api-ref/rest/v3/monetization.subscriptions)
resource body — for example `basePlans` and `listings`. Write operations take a
`regions_version` (default `"2022/02"`) identifying the version of available
regions used for regional prices.

### get_subscription

Get details of a specific subscription product. Read-only (available in read-only mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Subscription product ID |

```python
get_subscription("com.example.myapp", product_id="premium_monthly")
```

### create_subscription

Create a new subscription product. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `product_id` | string | Yes | — | Subscription product ID |
| `subscription` | object | Yes | — | Subscription resource body |
| `regions_version` | string | No | `"2022/02"` | Version of available regions for regional prices |

```python
create_subscription(
    package_name="com.example.myapp",
    product_id="premium_monthly",
    subscription={
        "basePlans": [
            {
                "basePlanId": "monthly",
                "autoRenewingBasePlanType": {"billingPeriodDuration": "P1M"},
            }
        ],
        "listings": [{"languageCode": "en-US", "title": "Premium Monthly"}],
    },
)
```

### patch_subscription

Partially update an existing subscription product. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `product_id` | string | Yes | — | Subscription product ID |
| `subscription` | object | Yes | — | Partial Subscription body with only the fields to change |
| `update_mask` | string | Yes | — | Comma-separated list of fields to update |
| `regions_version` | string | No | `"2022/02"` | Version of available regions for regional prices |

```python
patch_subscription(
    package_name="com.example.myapp",
    product_id="premium_monthly",
    subscription={"listings": [{"languageCode": "en-US", "title": "Premium (Monthly)"}]},
    update_mask="listings",
)
```

### delete_subscription

Delete a subscription product from the catalog. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Subscription product ID |

```python
delete_subscription("com.example.myapp", product_id="premium_monthly")
```

### batch_get_subscriptions

Get details for multiple subscription products at once. Read-only (available in read-only mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_ids` | array of string | Yes | Subscription product IDs to retrieve (up to 100) |

```python
batch_get_subscriptions("com.example.myapp", product_ids=["premium_monthly", "premium_yearly"])
```

### batch_update_subscriptions

Update multiple subscription products in a single operation. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `requests` | array of object | Yes | UpdateSubscriptionRequest bodies (each with `subscription`, `updateMask`, and optional `regionsVersion`) |

```python
batch_update_subscriptions(
    package_name="com.example.myapp",
    requests=[
        {
            "subscription": {
                "packageName": "com.example.myapp",
                "productId": "premium_monthly",
                "listings": [{"languageCode": "en-US", "title": "Premium Monthly"}],
            },
            "updateMask": "listings",
            "regionsVersion": {"version": "2022/02"},
        }
    ],
)
```

---

## Subscription Base Plans

Manage base plans within a subscription (`monetization.subscriptions.basePlans`).
All tools here are writes and are disabled in
[read-only mode](../configuration.md#read-only-mode).

Activating and deactivating (including the batch state update) return the updated
[Subscription](https://developers.google.com/android-publisher/api-ref/rest/v3/monetization.subscriptions)
as a subscription product. The price-migration tools take/return raw
[MigrateBasePlanPrices](https://developers.google.com/android-publisher/api-ref/rest/v3/monetization.subscriptions.basePlans/migratePrices)
request/response bodies.

### activate_base_plan

Activate a base plan, making it available to new subscribers. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent subscription product ID |
| `base_plan_id` | string | Yes | Base plan ID to activate |

```python
activate_base_plan("com.example.myapp", product_id="premium", base_plan_id="monthly")
```

### deactivate_base_plan

Deactivate a base plan so it is unavailable to new subscribers (existing subscribers keep it). **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent subscription product ID |
| `base_plan_id` | string | Yes | Base plan ID to deactivate |

```python
deactivate_base_plan("com.example.myapp", product_id="premium", base_plan_id="monthly")
```

### delete_base_plan

Delete a base plan (must be inactive with no active subscribers). **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent subscription product ID |
| `base_plan_id` | string | Yes | Base plan ID to delete |

```python
delete_base_plan("com.example.myapp", product_id="premium", base_plan_id="monthly")
```

### migrate_base_plan_prices

Migrate subscribers to the base plan's current prices. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent subscription product ID |
| `base_plan_id` | string | Yes | Base plan ID whose prices to migrate |
| `request` | object | Yes | MigrateBasePlanPricesRequest body (`regionalPriceMigrations`, `regionsVersion`) |

Returns the raw `MigrateBasePlanPricesResponse` dict.

```python
migrate_base_plan_prices(
    package_name="com.example.myapp",
    product_id="premium",
    base_plan_id="monthly",
    request={
        "regionalPriceMigrations": [
            {"regionCode": "US", "oldestAllowedPriceVersionTime": "2023-01-01T00:00:00Z"}
        ],
        "regionsVersion": {"version": "2022/02"},
    },
)
```

### batch_migrate_base_plan_prices

Migrate prices for multiple base plans in a single operation. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent subscription product ID |
| `requests` | array of object | Yes | MigrateBasePlanPricesRequest bodies |

Returns the raw `BatchMigrateBasePlanPricesResponse` dict.

```python
batch_migrate_base_plan_prices(
    package_name="com.example.myapp",
    product_id="premium",
    requests=[
        {
            "basePlanId": "monthly",
            "regionalPriceMigrations": [],
            "regionsVersion": {"version": "2022/02"},
        }
    ],
)
```

### batch_update_base_plan_states

Activate or deactivate multiple base plans in a single operation. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent subscription product ID |
| `requests` | array of object | Yes | UpdateBasePlanStateRequest bodies (each with a nested `activateBasePlanRequest` or `deactivateBasePlanRequest`) |

Returns the updated subscription product.

```python
batch_update_base_plan_states(
    package_name="com.example.myapp",
    product_id="premium",
    requests=[
        {"activateBasePlanRequest": {"basePlanId": "monthly"}},
        {"deactivateBasePlanRequest": {"basePlanId": "yearly"}},
    ],
)
```

---

## Subscription Offers

Manage offers within a base plan
(`monetization.subscriptions.basePlans.offers`). The read tools
(`get_subscription_offer`, `list_subscription_offers`, and
`batch_get_subscription_offers`) are available in read-only mode; all other
tools here are writes and are disabled in
[read-only mode](../configuration.md#read-only-mode).

The `offer` parameter is a
[SubscriptionOffer](https://developers.google.com/android-publisher/api-ref/rest/v3/monetization.subscriptions.basePlans.offers)
resource body — for example `phases`, `regionalConfigs`, `offerTags`, and
`targeting`. Create/patch operations take a `regions_version` (default
`"2022/02"`) identifying the version of available regions used for regional
prices. Offer-returning tools include: `offer_id`, `base_plan_id`, `state`,
`offer_tags`, `phases`, `regions_version`.

### get_subscription_offer

Get details of a specific subscription offer. Read-only (available in read-only mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent subscription product ID |
| `base_plan_id` | string | Yes | Parent base plan ID |
| `offer_id` | string | Yes | Subscription offer ID |

```python
get_subscription_offer("com.example.myapp", product_id="premium", base_plan_id="monthly", offer_id="intro")
```

### list_subscription_offers

List all offers for a base plan. Read-only (available in read-only mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent subscription product ID |
| `base_plan_id` | string | Yes | Parent base plan ID (`-` wildcard lists offers across base plans) |

```python
list_subscription_offers("com.example.myapp", product_id="premium", base_plan_id="monthly")
```

### create_subscription_offer

Create a new subscription offer. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `product_id` | string | Yes | — | Parent subscription product ID |
| `base_plan_id` | string | Yes | — | Parent base plan ID |
| `offer_id` | string | Yes | — | Subscription offer ID |
| `offer` | object | Yes | — | SubscriptionOffer resource body |
| `regions_version` | string | No | `"2022/02"` | Version of available regions for regional prices |

```python
create_subscription_offer(
    package_name="com.example.myapp",
    product_id="premium",
    base_plan_id="monthly",
    offer_id="intro",
    offer={
        "phases": [
            {
                "duration": "P1M",
                "recurrenceCount": 1,
                "regionalConfigs": [
                    {"regionCode": "US", "price": {"priceMicros": "0", "currency": "USD"}}
                ],
            }
        ],
        "offerTags": [{"tag": "intro"}],
    },
)
```

### patch_subscription_offer

Partially update an existing subscription offer. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `product_id` | string | Yes | — | Parent subscription product ID |
| `base_plan_id` | string | Yes | — | Parent base plan ID |
| `offer_id` | string | Yes | — | Subscription offer ID |
| `offer` | object | Yes | — | Partial SubscriptionOffer body with only the fields to change |
| `update_mask` | string | Yes | — | Comma-separated list of fields to update |
| `regions_version` | string | No | `"2022/02"` | Version of available regions for regional prices |

```python
patch_subscription_offer(
    package_name="com.example.myapp",
    product_id="premium",
    base_plan_id="monthly",
    offer_id="intro",
    offer={"offerTags": [{"tag": "promo"}]},
    update_mask="offerTags",
)
```

### activate_subscription_offer

Activate an offer, making it available to eligible subscribers. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent subscription product ID |
| `base_plan_id` | string | Yes | Parent base plan ID |
| `offer_id` | string | Yes | Subscription offer ID to activate |

```python
activate_subscription_offer("com.example.myapp", product_id="premium", base_plan_id="monthly", offer_id="intro")
```

### deactivate_subscription_offer

Deactivate an offer so it is unavailable to new subscribers. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent subscription product ID |
| `base_plan_id` | string | Yes | Parent base plan ID |
| `offer_id` | string | Yes | Subscription offer ID to deactivate |

```python
deactivate_subscription_offer("com.example.myapp", product_id="premium", base_plan_id="monthly", offer_id="intro")
```

### delete_subscription_offer

Delete an offer (must be inactive with no active subscribers). **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent subscription product ID |
| `base_plan_id` | string | Yes | Parent base plan ID |
| `offer_id` | string | Yes | Subscription offer ID to delete |

```python
delete_subscription_offer("com.example.myapp", product_id="premium", base_plan_id="monthly", offer_id="intro")
```

### batch_get_subscription_offers

Get details for multiple offers in a single operation. Read-only (available in read-only mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent subscription product ID |
| `base_plan_id` | string | Yes | Parent base plan ID (`-` wildcard allowed) |
| `requests` | array of object | Yes | GetSubscriptionOfferRequest bodies |

```python
batch_get_subscription_offers(
    package_name="com.example.myapp",
    product_id="premium",
    base_plan_id="monthly",
    requests=[{"offerId": "intro"}, {"offerId": "winback"}],
)
```

### batch_update_subscription_offers

Update multiple offers in a single operation. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent subscription product ID |
| `base_plan_id` | string | Yes | Parent base plan ID (`-` wildcard allowed) |
| `requests` | array of object | Yes | UpdateSubscriptionOfferRequest bodies (each with `subscriptionOffer`, `updateMask`, and optional `regionsVersion`) |

```python
batch_update_subscription_offers(
    package_name="com.example.myapp",
    product_id="premium",
    base_plan_id="monthly",
    requests=[
        {
            "subscriptionOffer": {
                "packageName": "com.example.myapp",
                "productId": "premium",
                "basePlanId": "monthly",
                "offerId": "intro",
                "offerTags": [{"tag": "promo"}],
            },
            "updateMask": "offerTags",
            "regionsVersion": {"version": "2022/02"},
        }
    ],
)
```

### batch_update_subscription_offer_states

Activate or deactivate multiple offers in a single operation. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent subscription product ID |
| `base_plan_id` | string | Yes | Parent base plan ID (`-` wildcard allowed) |
| `requests` | array of object | Yes | UpdateSubscriptionOfferStateRequest bodies (each with a nested `activateSubscriptionOfferRequest` or `deactivateSubscriptionOfferRequest`) |

```python
batch_update_subscription_offer_states(
    package_name="com.example.myapp",
    product_id="premium",
    base_plan_id="monthly",
    requests=[
        {"activateSubscriptionOfferRequest": {"offerId": "intro"}},
        {"deactivateSubscriptionOfferRequest": {"offerId": "winback"}},
    ],
)
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

## One-Time Products

Manage one-time products (`monetization.oneTimeProducts`) in your catalog. The
read tools (`get_one_time_product`, `list_one_time_products`, and
`batch_get_one_time_products`) are available in read-only mode; all other tools
here are writes and are disabled in
[read-only mode](../configuration.md#read-only-mode).

The `product` parameter is a
[OneTimeProduct](https://developers.google.com/android-publisher/api-ref/rest/v3/monetization.onetimeproducts)
resource body — for example `listings`, `purchaseOptions`, `offerTags`, and
`restrictedPaymentCountries`. Write operations take a `regions_version` (default
`"2022/02"`) identifying the version of available regions used for regional
prices. One-time-product-returning tools include: `product_id`, `package_name`,
`listings`, `purchase_options`, `offer_tags`, and `restricted_payment_countries`.

### get_one_time_product

Get details of a specific one-time product. Read-only (available in read-only mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | One-time product ID |

```python
get_one_time_product("com.example.myapp", product_id="coins_pack")
```

### list_one_time_products

List all one-time products for an app. Read-only (available in read-only mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |

```python
list_one_time_products("com.example.myapp")
```

### batch_get_one_time_products

Get details for multiple one-time products at once. Read-only (available in read-only mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_ids` | array of string | Yes | One-time product IDs to retrieve |

```python
batch_get_one_time_products("com.example.myapp", product_ids=["coins_pack", "gems_pack"])
```

### patch_one_time_product

Create or update a one-time product — for one-time products, `patch` is
create-or-update. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `product_id` | string | Yes | — | One-time product ID |
| `product` | object | Yes | — | Partial OneTimeProduct body with the fields to change |
| `update_mask` | string | Yes | — | Comma-separated list of fields to update |
| `regions_version` | string | No | `"2022/02"` | Version of available regions for regional prices |

```python
patch_one_time_product(
    package_name="com.example.myapp",
    product_id="coins_pack",
    product={"listings": [{"languageCode": "en-US", "title": "Coins Pack"}]},
    update_mask="listings",
)
```

### delete_one_time_product

Delete a one-time product from the catalog. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | One-time product ID |

```python
delete_one_time_product("com.example.myapp", product_id="coins_pack")
```

### batch_update_one_time_products

Update multiple one-time products in a single operation. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `requests` | array of object | Yes | UpdateOneTimeProductRequest bodies (each with `oneTimeProduct`, `updateMask`, and optional `regionsVersion` / `allowMissing`) |

```python
batch_update_one_time_products(
    package_name="com.example.myapp",
    requests=[
        {
            "oneTimeProduct": {
                "packageName": "com.example.myapp",
                "productId": "coins_pack",
                "listings": [{"languageCode": "en-US", "title": "Coins Pack"}],
            },
            "updateMask": "listings",
            "regionsVersion": {"version": "2022/02"},
        }
    ],
)
```

### batch_delete_one_time_products

Delete multiple one-time products in a single operation. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `requests` | array of object | Yes | DeleteOneTimeProductRequest bodies (each with `productId` and optional `packageName` / `latencyTolerance`) |

```python
batch_delete_one_time_products(
    package_name="com.example.myapp",
    requests=[{"productId": "coins_pack"}, {"productId": "gems_pack"}],
)
```

---

## One-Time Product Offers

Manage purchase options and their offers for one-time products
(`monetization.onetimeproducts.purchaseOptions` and
`monetization.onetimeproducts.purchaseOptions.offers`). The read tools
(`list_purchase_option_offers` and `batch_get_purchase_option_offers`) are
available in read-only mode; all other tools here are writes and are disabled in
[read-only mode](../configuration.md#read-only-mode).

Offer-returning tools include: `package_name`, `product_id`,
`purchase_option_id`, `offer_id`, `state`, `offer_tags`, and `regions_version`.
Where noted, `product_id` and `purchase_option_id` accept the `-` wildcard to
operate across products / purchase options.

### batch_delete_purchase_options

Delete multiple purchase options from a one-time product in a single operation. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent one-time product ID |
| `requests` | array of object | Yes | DeletePurchaseOptionRequest bodies (each with `purchaseOptionId` and optional `latencyTolerance`) |

```python
batch_delete_purchase_options(
    package_name="com.example.myapp",
    product_id="coins_pack",
    requests=[{"purchaseOptionId": "opt1"}, {"purchaseOptionId": "opt2"}],
)
```

### batch_update_purchase_option_states

Activate or deactivate multiple purchase options in a single operation. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent one-time product ID |
| `requests` | array of object | Yes | UpdatePurchaseOptionStateRequest bodies (each with a nested `activatePurchaseOptionRequest` or `deactivatePurchaseOptionRequest`) |

```python
batch_update_purchase_option_states(
    package_name="com.example.myapp",
    product_id="coins_pack",
    requests=[{"activatePurchaseOptionRequest": {"purchaseOptionId": "opt1"}}],
)
```

### list_purchase_option_offers

List all offers for a one-time product purchase option. Read-only (available in read-only mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent one-time product ID (`-` wildcard lists across products) |
| `purchase_option_id` | string | Yes | Parent purchase option ID (`-` wildcard lists across purchase options) |

```python
list_purchase_option_offers("com.example.myapp", product_id="coins_pack", purchase_option_id="opt1")
```

### batch_get_purchase_option_offers

Get details for multiple one-time product offers at once. Read-only (available in read-only mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent one-time product ID (`-` wildcard allowed) |
| `purchase_option_id` | string | Yes | Parent purchase option ID (`-` wildcard allowed) |
| `requests` | array of object | Yes | GetOneTimeProductOfferRequest bodies (each with `offerId` and optional `purchaseOptionId` / `productId`) |

```python
batch_get_purchase_option_offers(
    package_name="com.example.myapp",
    product_id="coins_pack",
    purchase_option_id="opt1",
    requests=[{"offerId": "intro"}],
)
```

### activate_purchase_option_offer

Activate a one-time product offer, making it available to eligible buyers. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent one-time product ID |
| `purchase_option_id` | string | Yes | Parent purchase option ID |
| `offer_id` | string | Yes | One-time product offer ID |

```python
activate_purchase_option_offer(
    package_name="com.example.myapp",
    product_id="coins_pack",
    purchase_option_id="opt1",
    offer_id="intro",
)
```

### deactivate_purchase_option_offer

Deactivate a one-time product offer so it is unavailable to new buyers. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent one-time product ID |
| `purchase_option_id` | string | Yes | Parent purchase option ID |
| `offer_id` | string | Yes | One-time product offer ID |

```python
deactivate_purchase_option_offer(
    package_name="com.example.myapp",
    product_id="coins_pack",
    purchase_option_id="opt1",
    offer_id="intro",
)
```

### cancel_purchase_option_offer

Cancel a one-time product offer (for example, a pre-order offer). **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent one-time product ID |
| `purchase_option_id` | string | Yes | Parent purchase option ID |
| `offer_id` | string | Yes | One-time product offer ID |

```python
cancel_purchase_option_offer(
    package_name="com.example.myapp",
    product_id="coins_pack",
    purchase_option_id="opt1",
    offer_id="preorder",
)
```

### batch_update_purchase_option_offers

Create or update multiple one-time product offers in a single operation. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent one-time product ID (`-` wildcard allowed) |
| `purchase_option_id` | string | Yes | Parent purchase option ID (`-` wildcard allowed) |
| `requests` | array of object | Yes | UpdateOneTimeProductOfferRequest bodies (each with `oneTimeProductOffer`, `updateMask`, and optional `allowMissing` / `latencyTolerance`) |

```python
batch_update_purchase_option_offers(
    package_name="com.example.myapp",
    product_id="coins_pack",
    purchase_option_id="opt1",
    requests=[
        {
            "oneTimeProductOffer": {
                "packageName": "com.example.myapp",
                "productId": "coins_pack",
                "purchaseOptionId": "opt1",
                "offerId": "intro",
            },
            "updateMask": "regionalPricingAndAvailabilityConfigs",
        }
    ],
)
```

### batch_update_purchase_option_offer_states

Activate, deactivate, or cancel multiple one-time product offers in a single operation. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent one-time product ID (`-` wildcard allowed) |
| `purchase_option_id` | string | Yes | Parent purchase option ID (`-` wildcard allowed) |
| `requests` | array of object | Yes | UpdateOneTimeProductOfferStateRequest bodies (each with a nested activate / deactivate / cancel one-time product offer request) |

```python
batch_update_purchase_option_offer_states(
    package_name="com.example.myapp",
    product_id="coins_pack",
    purchase_option_id="opt1",
    requests=[{"activateOneTimeProductOfferRequest": {"offerId": "intro"}}],
)
```

### batch_delete_purchase_option_offers

Delete multiple one-time product offers in a single operation. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `product_id` | string | Yes | Parent one-time product ID (`-` wildcard allowed) |
| `purchase_option_id` | string | Yes | Parent purchase option ID (`-` wildcard allowed) |
| `requests` | array of object | Yes | DeleteOneTimeProductOfferRequest bodies (each with `offerId` and optional `latencyTolerance`) |

```python
batch_delete_purchase_option_offers(
    package_name="com.example.myapp",
    product_id="coins_pack",
    purchase_option_id="opt1",
    requests=[{"offerId": "intro"}],
)
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

## External Transactions

Manage external (alternative billing) transactions
([externaltransactions](https://developers.google.com/android-publisher/api-ref/rest/v3/externaltransactions)).
`get_external_transaction` is read-only; `create_external_transaction` and
`refund_external_transaction` are writes and are disabled in
[read-only mode](../configuration.md#read-only-mode).

The `transaction` parameter is an
[ExternalTransaction](https://developers.google.com/android-publisher/api-ref/rest/v3/externaltransactions#ExternalTransaction)
resource body; the `refund` parameter is a
[RefundExternalTransactionRequest](https://developers.google.com/android-publisher/api-ref/rest/v3/externaltransactions/refundexternaltransaction#request-body)
body. The client builds the `applications/{packageName}/externalTransactions/{externalTransactionId}`
resource name for you from `package_name` and `external_transaction_id`.

### get_external_transaction

Get an external transaction. Read-only (available in read-only mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `external_transaction_id` | string | Yes | External transaction ID |

```python
get_external_transaction("com.example.myapp", external_transaction_id="tx123")
```

### create_external_transaction

Create an external transaction. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `external_transaction_id` | string | Yes | External transaction ID to assign |
| `transaction` | object | Yes | ExternalTransaction resource body |

```python
create_external_transaction(
    package_name="com.example.myapp",
    external_transaction_id="tx123",
    transaction={
        "originalPreTaxAmount": {"currencyCode": "USD", "units": "1", "nanos": 990000000},
        "originalTaxAmount": {"currencyCode": "USD", "units": "0", "nanos": 100000000},
        "transactionTime": "2026-01-01T00:00:00Z",
        "oneTimeTransaction": {"externalTransactionToken": "token123"},
    },
)
```

### refund_external_transaction

Refund an external transaction. **Write / money.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `external_transaction_id` | string | Yes | External transaction ID to refund |
| `refund` | object | Yes | RefundExternalTransactionRequest body (`refundTime` plus `fullRefund` or `partialRefund`) |

```python
refund_external_transaction(
    package_name="com.example.myapp",
    external_transaction_id="tx123",
    refund={"refundTime": "2026-01-02T00:00:00Z", "fullRefund": {}},
)
```

## Device Tier Configs

Manage device tier configs
([applications.deviceTierConfigs](https://developers.google.com/android-publisher/api-ref/rest/v3/applications.deviceTierConfigs)).
A device tier config groups devices (by RAM, system features, etc.) and assigns
them to tiers so you can ship device-targeted content. `get_device_tier_config`
and `list_device_tier_configs` are read-only; `create_device_tier_config` is a
write and is disabled in [read-only mode](../configuration.md#read-only-mode).

The `config` parameter is a
[DeviceTierConfig](https://developers.google.com/android-publisher/api-ref/rest/v3/applications.deviceTierConfigs#DeviceTierConfig)
resource body (`deviceGroups`, `deviceTierSet`, `userCountrySets`). Device tier
configs are immutable and cannot be updated or deleted once created — create a
new one to make changes.

### get_device_tier_config

Get a device tier config. Read-only (available in read-only mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `device_tier_config_id` | string | Yes | Device tier config ID |

```python
get_device_tier_config("com.example.myapp", device_tier_config_id="12345")
```

### list_device_tier_configs

List device tier configs for an app. Read-only (available in read-only mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |

```python
list_device_tier_configs("com.example.myapp")
```

### create_device_tier_config

Create a device tier config. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `config` | object | Yes | — | DeviceTierConfig resource body (`deviceGroups`, `deviceTierSet`, `userCountrySets`) |
| `allow_unknown_devices` | boolean | No | `false` | Accept device IDs unknown to Play's catalog rather than rejecting them |

```python
create_device_tier_config(
    package_name="com.example.myapp",
    config={
        "deviceGroups": [
            {
                "name": "high_ram",
                "deviceSelectors": [{"deviceRam": {"minBytes": "6000000000"}}],
            }
        ],
        "deviceTierSet": {
            "deviceTiers": [{"level": 1, "deviceGroupNames": ["high_ram"]}]
        },
    },
    allow_unknown_devices=False,
)
```

## Data Safety

### set_data_safety

Write the data safety labels declaration of an app. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `safety_labels` | object | Yes | `SafetyLabelsUpdateRequest` body containing a `safetyLabels` string with the contents of the Data Safety CSV file |

```python
set_data_safety(
    package_name="com.example.myapp",
    safety_labels={"safetyLabels": "<contents of Data Safety CSV>"},
)
```

## App Recovery

Manage app recovery actions
([applications.appRecoveries](https://developers.google.com/android-publisher/api-ref/rest/v3/applications.appRecoveries)).
An app recovery action lets you push a Remote In-App Update to devices already
running a released version, so you can recover from a bad rollout without
shipping a new release. `list_app_recoveries` is read-only; `create_app_recovery`,
`deploy_app_recovery`, `cancel_app_recovery`, and `add_app_recovery_targeting`
are writes and are disabled in
[read-only mode](../configuration.md#read-only-mode).

### list_app_recoveries

List app recovery actions for an app. Read-only (available in read-only mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |

```python
list_app_recoveries("com.example.myapp")
```

### create_app_recovery

Create a draft app recovery action. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `recovery` | object | Yes | `CreateDraftAppRecoveryRequest` body (e.g. `remoteInAppUpdate` plus `targeting`) |

```python
create_app_recovery(
    package_name="com.example.myapp",
    recovery={
        "remoteInAppUpdate": {"isRemoteInAppUpdateRequested": True},
        "targeting": {"allUsers": {}},
    },
)
```

### deploy_app_recovery

Deploy an app recovery action to users. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `app_recovery_id` | string | Yes | App recovery action ID |

```python
deploy_app_recovery(package_name="com.example.myapp", app_recovery_id="123")
```

### cancel_app_recovery

Cancel an app recovery action. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `app_recovery_id` | string | Yes | App recovery action ID |

```python
cancel_app_recovery(package_name="com.example.myapp", app_recovery_id="123")
```

### add_app_recovery_targeting

Add targeting to an app recovery action. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `app_recovery_id` | string | Yes | App recovery action ID |
| `targeting` | object | Yes | `AddTargetingRequest` body (e.g. a `targetingUpdate` object) |

```python
add_app_recovery_targeting(
    package_name="com.example.myapp",
    app_recovery_id="123",
    targeting={"targetingUpdate": {"allUsers": {}}},
)
```
