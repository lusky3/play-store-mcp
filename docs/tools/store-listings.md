# Store Listings

Tools for managing app store listings across languages.

!!! info "Text Limits"
    | Field | Max Length |
    |---|---|
    | Title | 50 characters |
    | Short description | 80 characters |
    | Full description | 4,000 characters |

    Use [`validate_listing_text`](validation.md#validate_listing_text) to check lengths before updating.

---

## get_listing

Get the store listing for a specific language.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `language` | string | No | `en-US` | Language code (e.g., `en-US`, `es-ES`, `fr-FR`) |

Returns: `language`, `title`, `short_description`, `full_description`, `video`

```python
get_listing("com.example.myapp", language="es-ES")
```

---

## update_listing

Update the store listing for a specific language. Only provided fields are updated.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `language` | string | Yes | Language code |
| `title` | string | No | App title (max 50 chars) |
| `full_description` | string | No | Full description (max 4,000 chars) |
| `short_description` | string | No | Short description (max 80 chars) |
| `video` | string | No | YouTube video URL |

```python
update_listing(
    package_name="com.example.myapp",
    language="en-US",
    title="My Awesome App",
    short_description="The best app for productivity",
    full_description="A comprehensive productivity app that helps you..."
)
```

---

## list_all_listings

List store listings for all configured languages.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |

```python
list_all_listings("com.example.myapp")
```

Returns a list of listings for every language configured in the Play Console.

---

## Store Listing Images

Tools for managing the graphic assets (screenshots, icon, feature graphic, etc.)
shown on a store listing for a given language.

!!! info "Image types"
    `image_type` is one of: `phoneScreenshots`, `sevenInchScreenshots`,
    `tenInchScreenshots`, `tvScreenshots`, `wearScreenshots`, `icon`,
    `featureGraphic`, `tvBanner`.

### list_images

List the images currently attached for a language and image type.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `language` | string | Yes | Language localization code (BCP-47 tag, e.g. `en-US`) |
| `image_type` | string | Yes | Image type (see above) |

Returns a list of images, each with `image_id`, `url`, `sha1` and `sha256`.

```python
list_images("com.example.myapp", language="en-US", image_type="phoneScreenshots")
```

### upload_image

Upload a store-listing image (PNG or JPEG) and commit the edit. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `language` | string | Yes | Language localization code |
| `image_type` | string | Yes | Image type (see above) |
| `image_path` | string | Yes | Local path to the image file (PNG or JPEG) |

```python
upload_image(
    package_name="com.example.myapp",
    language="en-US",
    image_type="icon",
    image_path="/data/assets/icon.png",
)
```

### delete_image

Delete a single image by ID and commit the edit. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `language` | string | Yes | Language localization code |
| `image_type` | string | Yes | Image type the image belongs to |
| `image_id` | string | Yes | Unique identifier of the image to delete |

```python
delete_image("com.example.myapp", language="en-US", image_type="icon", image_id="abc123")
```

### delete_all_images

Delete all images for a language and image type, then commit the edit. **Write.** Disabled in [read-only mode](../configuration.md#read-only-mode).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `language` | string | Yes | Language localization code |
| `image_type` | string | Yes | Image type to clear all images for |

```python
delete_all_images("com.example.myapp", language="en-US", image_type="phoneScreenshots")
```
