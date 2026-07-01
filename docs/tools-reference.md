# Tools Reference

Complete reference for all MCP tools provided by the Play Store MCP server.

## Publishing Tools

| Tool | Description |
|---|---|
| [`deploy_app`](tools/publishing.md#deploy_app) | Deploy an APK/AAB to a track with optional staged rollout |
| [`deploy_app_multilang`](tools/publishing.md#deploy_app_multilang) | Deploy with multi-language release notes |
| [`promote_release`](tools/publishing.md#promote_release) | Promote a release between tracks |
| [`get_releases`](tools/publishing.md#get_releases) | Get release status for all tracks |
| [`halt_release`](tools/publishing.md#halt_release) | Halt a staged rollout |
| [`update_rollout`](tools/publishing.md#update_rollout) | Update rollout percentage |
| [`get_app_details`](tools/publishing.md#get_app_details) | Get app metadata |

## Store Listings Tools

| Tool | Description |
|---|---|
| [`get_listing`](tools/store-listings.md#get_listing) | Get store listing for a language |
| [`update_listing`](tools/store-listings.md#update_listing) | Update store listing text and video |
| [`list_all_listings`](tools/store-listings.md#list_all_listings) | List all store listings across languages |
| [`list_images`](tools/store-listings.md#list_images) | List store-listing images for a language and image type |
| `upload_image` | Upload a store-listing image (PNG/JPEG) and commit the edit (write) |
| `delete_image` | Delete a single store-listing image by ID (write) |
| `delete_all_images` | Delete all store-listing images for a language and image type (write) |

## Review Tools

| Tool | Description |
|---|---|
| [`get_reviews`](tools/reviews.md#get_reviews) | Fetch recent reviews with optional filters |
| [`get_review`](tools/reviews.md#get_review) | Fetch a single review by ID |
| [`reply_to_review`](tools/reviews.md#reply_to_review) | Reply to a user review |

## Subscription Tools

| Tool | Description |
|---|---|
| [`list_subscriptions`](tools/subscriptions.md#list_subscriptions) | List subscription products |
| [`get_subscription`](tools/subscriptions.md#get_subscription) | Get details of a specific subscription product |
| [`batch_get_subscriptions`](tools/subscriptions.md#batch_get_subscriptions) | Get details for multiple subscription products at once |
| `create_subscription` | Create a new subscription product (write) |
| `patch_subscription` | Partially update a subscription product (write) |
| `delete_subscription` | Delete a subscription product (write) |
| `batch_update_subscriptions` | Update multiple subscription products at once (write) |
| `activate_base_plan` | Activate a subscription base plan (write) |
| `deactivate_base_plan` | Deactivate a subscription base plan (write) |
| `delete_base_plan` | Delete a subscription base plan (write) |
| `migrate_base_plan_prices` | Migrate subscribers to current base plan prices (write) |
| `batch_migrate_base_plan_prices` | Migrate prices for multiple base plans at once (write) |
| `batch_update_base_plan_states` | Activate/deactivate multiple base plans at once (write) |
| [`get_subscription_offer`](tools/subscriptions.md#get_subscription_offer) | Get details of a specific subscription offer |
| [`list_subscription_offers`](tools/subscriptions.md#list_subscription_offers) | List all offers for a base plan |
| [`batch_get_subscription_offers`](tools/subscriptions.md#batch_get_subscription_offers) | Get details for multiple subscription offers at once |
| `create_subscription_offer` | Create a new subscription offer (write) |
| `patch_subscription_offer` | Partially update a subscription offer (write) |
| `activate_subscription_offer` | Activate a subscription offer (write) |
| `deactivate_subscription_offer` | Deactivate a subscription offer (write) |
| `delete_subscription_offer` | Delete a subscription offer (write) |
| `batch_update_subscription_offers` | Update multiple subscription offers at once (write) |
| `batch_update_subscription_offer_states` | Activate/deactivate multiple subscription offers at once (write) |
| [`get_subscription_status`](tools/subscriptions.md#get_subscription_status) | Check subscription purchase status |
| [`list_voided_purchases`](tools/subscriptions.md#list_voided_purchases) | List voided purchases |

## In-App Products Tools

| Tool | Description |
|---|---|
| [`list_in_app_products`](tools/subscriptions.md#list_in_app_products) | List all in-app products |
| [`get_in_app_product`](tools/subscriptions.md#get_in_app_product) | Get details of a specific product |
| [`batch_get_in_app_products`](tools/subscriptions.md#batch_get_in_app_products) | Get details for multiple products at once |
| `create_in_app_product` | Create a new in-app product (write) |
| `update_in_app_product` | Update (replace) an in-app product (write) |
| `patch_in_app_product` | Partially update an in-app product (write) |
| `delete_in_app_product` | Delete an in-app product (write) |
| `batch_delete_in_app_products` | Delete multiple in-app products at once (write) |
| [`get_product_purchase`](tools/subscriptions.md#get_product_purchase) | Check status of an in-app product purchase |
| [`acknowledge_product_purchase`](tools/subscriptions.md#acknowledge_product_purchase) | Acknowledge an in-app product purchase (write) |
| [`consume_product_purchase`](tools/subscriptions.md#consume_product_purchase) | Consume an in-app product purchase (write) |

## One-Time Product Tools

| Tool | Description |
|---|---|
| [`get_one_time_product`](tools/subscriptions.md#get_one_time_product) | Get details of a specific one-time product |
| [`list_one_time_products`](tools/subscriptions.md#list_one_time_products) | List all one-time products |
| [`batch_get_one_time_products`](tools/subscriptions.md#batch_get_one_time_products) | Get details for multiple one-time products at once |
| `patch_one_time_product` | Create or update a one-time product (write) |
| `delete_one_time_product` | Delete a one-time product (write) |
| `batch_update_one_time_products` | Update multiple one-time products at once (write) |
| `batch_delete_one_time_products` | Delete multiple one-time products at once (write) |

## One-Time Product Offer Tools

| Tool | Description |
|---|---|
| [`list_purchase_option_offers`](tools/subscriptions.md#list_purchase_option_offers) | List all offers for a purchase option |
| [`batch_get_purchase_option_offers`](tools/subscriptions.md#batch_get_purchase_option_offers) | Get details for multiple one-time product offers at once |
| `batch_delete_purchase_options` | Delete multiple purchase options at once (write) |
| `batch_update_purchase_option_states` | Activate/deactivate multiple purchase options at once (write) |
| `activate_purchase_option_offer` | Activate a one-time product offer (write) |
| `deactivate_purchase_option_offer` | Deactivate a one-time product offer (write) |
| `cancel_purchase_option_offer` | Cancel a one-time product offer (write) |
| `batch_update_purchase_option_offers` | Update multiple one-time product offers at once (write) |
| `batch_update_purchase_option_offer_states` | Activate/deactivate/cancel multiple one-time product offers at once (write) |
| `batch_delete_purchase_option_offers` | Delete multiple one-time product offers at once (write) |

## Purchase Management Tools

| Tool | Description |
|---|---|
| [`get_product_purchase_v2`](tools/subscriptions.md#get_product_purchase_v2) | Read an in-app product purchase (v2, token only) |
| [`refund_order`](tools/subscriptions.md#refund_order) | Refund an order, optionally revoking entitlement (write) |
| [`cancel_subscription_purchase`](tools/subscriptions.md#cancel_subscription_purchase) | Cancel a subscription (write) |
| [`defer_subscription_purchase`](tools/subscriptions.md#defer_subscription_purchase) | Defer a subscription's next renewal (write) |
| [`revoke_subscription_purchase`](tools/subscriptions.md#revoke_subscription_purchase) | Revoke/refund a subscription (write) |

## External Transactions Tools

| Tool | Description |
|---|---|
| [`get_external_transaction`](tools/subscriptions.md#get_external_transaction) | Get an external (alternative billing) transaction |
| `create_external_transaction` | Create an external transaction (write) |
| `refund_external_transaction` | Refund an external transaction (write) |

## Device Tier Config Tools

| Tool | Description |
|---|---|
| [`get_device_tier_config`](tools/subscriptions.md#get_device_tier_config) | Get a device tier config |
| [`list_device_tier_configs`](tools/subscriptions.md#list_device_tier_configs) | List device tier configs for an app |
| `create_device_tier_config` | Create a device tier config (write) |

## Account Access Tools

| Tool | Description |
|---|---|
| [`list_users`](tools/subscriptions.md#list_users) | List users with access to a developer account |
| `create_user` | Grant a user access to a developer account (write) |
| `update_user` | Update a user's account access (write) |
| `delete_user` | Remove a user's access to a developer account (write) |
| `create_grant` | Grant a user app-level access (write) |
| `update_grant` | Update a user's app-level access (write) |
| `delete_grant` | Remove a user's app-level access (write) |

## Generated APKs Tools

| Tool | Description |
|---|---|
| [`list_generated_apks`](tools/subscriptions.md#list_generated_apks) | List the APKs Google Play generated from an app bundle version |
| [`download_generated_apk`](tools/subscriptions.md#download_generated_apk) | Download a single generated APK to a local file |

## System APK Variants Tools

| Tool | Description |
|---|---|
| [`get_system_apk_variant`](tools/subscriptions.md#get_system_apk_variant) | Get a previously created system APK variant |
| [`list_system_apk_variants`](tools/subscriptions.md#list_system_apk_variants) | List previously created system APK variants for an app bundle version |
| `create_system_apk_variant` | Create a system APK variant from an uploaded app bundle (write) |
| [`download_system_apk_variant`](tools/subscriptions.md#download_system_apk_variant) | Download a system APK variant to a local file |

## Edit Uploads Tools

| Tool | Description |
|---|---|
| [`list_apks`](tools/subscriptions.md#list_apks) | List the APKs currently uploaded for an app |
| [`list_bundles`](tools/subscriptions.md#list_bundles) | List the Android App Bundles currently uploaded for an app |
| [`upload_apk`](tools/subscriptions.md#upload_apk) | Upload an APK and commit the edit (write) |
| [`upload_bundle`](tools/subscriptions.md#upload_bundle) | Upload an app bundle (.aab) and commit the edit (write) |
| [`upload_deobfuscation_file`](tools/subscriptions.md#upload_deobfuscation_file) | Upload a ProGuard mapping / native symbols file (write) |
| [`upload_expansion_file`](tools/subscriptions.md#upload_expansion_file) | Upload an APK expansion (OBB) file (write) |

## Internal App Sharing Tools

| Tool | Description |
|---|---|
| `upload_internal_app_sharing_apk` | Upload an APK to internal app sharing (write) |
| `upload_internal_app_sharing_bundle` | Upload an app bundle (.aab) to internal app sharing (write) |

## App Management Tools

| Tool | Description |
|---|---|
| `set_data_safety` | Write an app's data safety labels declaration (write) |
| [`list_app_recoveries`](tools/subscriptions.md#list_app_recoveries) | List app recovery actions for an app |
| `create_app_recovery` | Create a draft app recovery action (write) |
| `deploy_app_recovery` | Deploy an app recovery action to users (write) |
| `cancel_app_recovery` | Cancel an app recovery action (write) |
| `add_app_recovery_targeting` | Add targeting to an app recovery action (write) |

## Testers Tools

| Tool | Description |
|---|---|
| [`get_testers`](tools/testers.md#get_testers) | Get testers for a track |
| [`update_testers`](tools/testers.md#update_testers) | Update testers for a track |

## Orders & Expansion Files

| Tool | Description |
|---|---|
| [`get_order`](#get_order) | Get order/transaction details |
| `batch_get_orders` | Get details for multiple orders at once |
| [`get_expansion_file`](#get_expansion_file) | Get APK expansion file info |

## Validation Tools

| Tool | Description |
|---|---|
| [`validate_package_name`](tools/validation.md#validate_package_name) | Validate package name format |
| [`validate_track`](tools/validation.md#validate_track) | Validate track name |
| [`validate_listing_text`](tools/validation.md#validate_listing_text) | Validate store listing text lengths |

## Batch Operations Tools

| Tool | Description |
|---|---|
| [`batch_deploy`](tools/batch.md#batch_deploy) | Deploy to multiple tracks at once |

## Vitals Tools

| Tool | Description |
|---|---|
| [`get_vitals_overview`](tools/vitals.md#get_vitals_overview) | Get Android Vitals overview |
| [`get_vitals_metrics`](tools/vitals.md#get_vitals_metrics) | Get specific vitals metrics |

---

## get_order

Retrieve detailed order and transaction information for a specific order ID.

**Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name (e.g., `com.example.app`) |
| `order_id` | string | Yes | The order ID to look up |

## get_expansion_file

Get information about APK expansion files (main or patch) for a specific APK version.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `version_code` | integer | Yes | — | The APK version code |
| `expansion_file_type` | string | No | `main` | Type: `main` or `patch` |

> **Note:** The client manages edit sessions internally — you do not need to supply an `edit_id`.