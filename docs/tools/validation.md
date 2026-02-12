# Validation

Tools for validating inputs before making API calls. Use these to catch errors early and get clear feedback.

---

## validate_package_name

Validate that a package name follows the correct format.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | Package name to validate |

Rules:

- Must not be empty
- Must contain at least one dot (e.g., `com.example.app`)
- Must start with a lowercase letter
- Can only contain lowercase letters, numbers, underscores, and dots
- Each segment after a dot must start with a lowercase letter

```python
validate_package_name("com.example.myapp")
```

Returns:

```json
{
  "valid": true,
  "errors": [],
  "package_name": "com.example.myapp"
}
```

---

## validate_track

Validate that a track name is valid.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `track` | string | Yes | Track name to validate |

Valid tracks: `internal`, `alpha`, `beta`, `production`

```python
validate_track("beta")       # valid
validate_track("staging")    # invalid
```

---

## validate_listing_text

Validate store listing text lengths before updating.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `title` | string | No | App title (max 50 characters) |
| `short_description` | string | No | Short description (max 80 characters) |
| `full_description` | string | No | Full description (max 4,000 characters) |

```python
validate_listing_text(
    title="My App",
    short_description="A great productivity app",
    full_description="Full description text here..."
)
```

!!! tip
    Run this before `update_listing` to catch text length issues without making an API call.
