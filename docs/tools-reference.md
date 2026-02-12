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

## Review Tools

| Tool | Description |
|---|---|
| [`get_reviews`](tools/reviews.md#get_reviews) | Fetch recent reviews with optional filters |
| [`reply_to_review`](tools/reviews.md#reply_to_review) | Reply to a user review |

## Subscription Tools

| Tool | Description |
|---|---|
| [`list_subscriptions`](tools/subscriptions.md#list_subscriptions) | List subscription products |
| [`get_subscription_status`](tools/subscriptions.md#get_subscription_status) | Check subscription purchase status |
| [`list_voided_purchases`](tools/subscriptions.md#list_voided_purchases) | List voided purchases |

## In-App Products Tools

| Tool | Description |
|---|---|
| [`list_in_app_products`](tools/subscriptions.md#list_in_app_products) | List all in-app products |
| [`get_in_app_product`](tools/subscriptions.md#get_in_app_product) | Get details of a specific product |

## Testers Tools

| Tool | Description |
|---|---|
| [`get_testers`](tools/testers.md#get_testers) | Get testers for a track |
| [`update_testers`](tools/testers.md#update_testers) | Update testers for a track |

## Orders & Expansion Files

| Tool | Description |
|---|---|
| [`get_order`](troubleshooting.md#get_order) | Get order/transaction details |
| [`get_expansion_file`](troubleshooting.md#get_expansion_file) | Get APK expansion file info |

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
