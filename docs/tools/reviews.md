# Reviews

Tools for fetching and responding to user reviews.

## get_reviews

Fetch recent reviews for an app.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `max_results` | int | No | `50` | Maximum reviews to return (max 100) |
| `translation_language` | string | No | `null` | Language code to translate reviews into |

Each review includes:

- `review_id` — Unique review ID (needed for replies)
- `author_name` — Reviewer's name
- `star_rating` — Rating from 1 to 5
- `comment` — Review text
- `language` — Original language
- `device` — Device name
- `android_version` — Android OS version
- `app_version_code` / `app_version_name` — App version
- `last_modified` — Timestamp
- `developer_reply` — Existing reply (if any)

```python
# Get latest 20 reviews
get_reviews("com.example.myapp", max_results=20)

# Get reviews translated to English
get_reviews(
    "com.example.myapp",
    max_results=50,
    translation_language="en-US"
)
```

---

## reply_to_review

Reply to a user review. The reply is visible to the reviewer and publicly on the Play Store.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `review_id` | string | Yes | Review ID (from `get_reviews`) |
| `reply_text` | string | Yes | Reply text |

```python
reply_to_review(
    package_name="com.example.myapp",
    review_id="abc123",
    reply_text="Thank you for your feedback! We've fixed this in the latest update."
)
```

!!! tip "Best Practices"
    - Replies are public — keep them professional and helpful
    - Address the user's specific concern
    - Mention if a fix is available in a newer version
    - The service account needs "Reply to reviews" permission in Play Console
