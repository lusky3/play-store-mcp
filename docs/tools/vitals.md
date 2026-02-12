# Android Vitals

Tools for monitoring app health metrics — crashes, ANRs, and other performance indicators.

!!! note
    Full Vitals API access may require additional Google Play Developer Reporting API setup beyond the standard Play Developer API.

---

## get_vitals_overview

Get an overview of Android Vitals for an app.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |

Returns: `crash_rate`, `anr_rate`, `excessive_wakeups`, `stuck_wake_locks`, `freshness_info`

```python
get_vitals_overview("com.example.myapp")
```

---

## get_vitals_metrics

Get specific Android Vitals metrics with more detail.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `metric_type` | string | No | `crashRate` | Metric type (see below) |

Each metric includes: `metric_type`, `value`, `benchmark`, `is_below_threshold`, `dimension`, `dimension_value`

| Metric | Description |
|---|---|
| `crashRate` | User-perceived crash rate |
| `anrRate` | User-perceived ANR rate |

```python
# Get crash rate metrics
get_vitals_metrics("com.example.myapp", metric_type="crashRate")

# Get ANR metrics
get_vitals_metrics("com.example.myapp", metric_type="anrRate")
```

!!! info "Required Permissions"
    The service account needs "View app information and download bulk reports" permission in Play Console to access Vitals data.
