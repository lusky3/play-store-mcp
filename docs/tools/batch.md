# Batch Operations

Deploy to multiple tracks in a single operation.

## batch_deploy

Deploy an app to multiple tracks simultaneously. Useful for deploying to `internal` and `alpha` at the same time, or pushing to all testing tracks at once.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `file_path` | string | Yes | — | Absolute path to APK or AAB file |
| `tracks` | list[string] | Yes | — | List of tracks to deploy to |
| `release_notes` | string | No | `null` | Release notes (applied to all tracks) |
| `rollout_percentages` | dict | No | `null` | Track name → rollout percentage mapping |

Returns: `success`, `results` (per-track), `successful_count`, `failed_count`, `message`

### Deploy to multiple testing tracks

```python
batch_deploy(
    package_name="com.example.myapp",
    file_path="/path/to/app-release.aab",
    tracks=["internal", "alpha"],
    release_notes="New feature: dark mode"
)
```

### Different rollout percentages per track

```python
batch_deploy(
    package_name="com.example.myapp",
    file_path="/path/to/app-release.aab",
    tracks=["internal", "alpha", "beta"],
    release_notes="Performance improvements",
    rollout_percentages={
        "internal": 100.0,
        "alpha": 100.0,
        "beta": 50.0
    }
)
```

!!! info
    Each track deployment is independent — if one fails, others may still succeed. Check individual `results` entries for per-track status. If `rollout_percentages` is not provided, defaults to 100% for all tracks.
