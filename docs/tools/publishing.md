# Publishing & Deployment

Tools for deploying apps, promoting releases, and managing rollouts.

## Tracks

The Play Store uses four release tracks:

| Track | Purpose |
|---|---|
| `internal` | Internal testing (up to 100 testers) |
| `alpha` | Closed testing |
| `beta` | Open testing |
| `production` | Public release |

Releases typically flow: `internal` → `alpha` → `beta` → `production`

---

## deploy_app

Deploy an APK or AAB file to a Play Store track.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name (e.g., `com.example.myapp`) |
| `track` | string | Yes | — | Release track: `internal`, `alpha`, `beta`, `production` |
| `file_path` | string | Yes | — | Absolute path to APK or AAB file |
| `release_notes` | string | No | `null` | Release notes for this version |
| `release_notes_language` | string | No | `en-US` | Language code for release notes |
| `rollout_percentage` | float | No | `100.0` | Rollout percentage (0–100) |

```python
deploy_app(
    package_name="com.example.myapp",
    track="internal",
    file_path="/path/to/app-release.aab",
    release_notes="Bug fixes and performance improvements",
    rollout_percentage=100.0
)
```

!!! tip "Staged Rollout"
    Set `rollout_percentage` to less than 100 for a staged rollout. Use `update_rollout` to increase later.

    ```python
    deploy_app(
        package_name="com.example.myapp",
        track="production",
        file_path="/path/to/app-release.aab",
        rollout_percentage=10.0
    )
    ```

---

## deploy_app_multilang

Deploy with release notes in multiple languages.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `track` | string | Yes | — | Release track |
| `file_path` | string | Yes | — | Absolute path to APK or AAB file |
| `release_notes` | dict | Yes | — | Language code → release notes mapping |
| `rollout_percentage` | float | No | `100.0` | Rollout percentage (0–100) |

```python
deploy_app_multilang(
    package_name="com.example.myapp",
    track="production",
    file_path="/path/to/app-release.aab",
    release_notes={
        "en-US": "Bug fixes and improvements",
        "es-ES": "Corrección de errores y mejoras",
        "fr-FR": "Corrections de bugs et améliorations",
        "de-DE": "Fehlerbehebungen und Verbesserungen"
    },
    rollout_percentage=25.0
)
```

---

## promote_release

Promote a release from one track to another.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `from_track` | string | Yes | — | Source track |
| `to_track` | string | Yes | — | Destination track |
| `version_code` | int | Yes | — | Version code to promote |
| `rollout_percentage` | float | No | `100.0` | Rollout percentage on target track |

```python
promote_release(
    package_name="com.example.myapp",
    from_track="beta",
    to_track="production",
    version_code=42,
    rollout_percentage=20.0
)
```

---

## get_releases

Get release status for all tracks of an app.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |

Returns a list of tracks, each containing their releases with status, version codes, rollout percentage, and release notes.

```python
get_releases("com.example.myapp")
```

---

## halt_release

Halt a staged rollout. Stops the release so users stop receiving updates.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `track` | string | Yes | Track containing the release |
| `version_code` | int | Yes | Version code to halt |

```python
halt_release(
    package_name="com.example.myapp",
    track="production",
    version_code=42
)
```

---

## update_rollout

Update the rollout percentage for a staged release. Set to 100 to complete the rollout.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `track` | string | Yes | Track containing the release |
| `version_code` | int | Yes | Version code of the staged release |
| `rollout_percentage` | float | Yes | New rollout percentage (0–100) |

```python
# Increase rollout to 50%
update_rollout(
    package_name="com.example.myapp",
    track="production",
    version_code=42,
    rollout_percentage=50.0
)

# Complete the rollout
update_rollout(
    package_name="com.example.myapp",
    track="production",
    version_code=42,
    rollout_percentage=100.0
)
```

---

## get_app_details

Get app metadata including title, description, and developer info.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `language` | string | No | `en-US` | Language code for localized content |

Returns: `title`, `short_description`, `full_description`, `default_language`, `developer_name`, `developer_email`, `developer_website`

```python
get_app_details("com.example.myapp", language="en-US")
```
