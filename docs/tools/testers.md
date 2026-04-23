# Testers

Tools for managing tester access on testing tracks.

Testers can be managed via Google Group email addresses. They apply to the `internal`, `alpha`, and `beta` tracks.

---

## get_testers

Get the current list of testers for a specific testing track.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `track` | string | Yes | Track name: `internal`, `alpha`, or `beta` |

Returns: `track`, `google_groups`

```python
get_testers("com.example.myapp", track="alpha")
```

---

## update_testers

Update the tester list for a testing track.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `track` | string | Yes | Track name: `internal`, `alpha`, or `beta` |
| `google_groups` | list[string] | Yes | Google Group email addresses |

```python
update_testers(
    package_name="com.example.myapp",
    track="beta",
    google_groups=[
        "beta-testers@googlegroups.com",
        "qa-team@googlegroups.com"
    ]
)
```

!!! warning
    This **replaces** the entire tester list — include all testers you want to keep. Google Group emails give access to all members of the group.
