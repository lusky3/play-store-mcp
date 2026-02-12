# Testers

Tools for managing tester access on testing tracks.

Testers can be individual email addresses or Google Group emails. They apply to the `internal`, `alpha`, and `beta` tracks.

---

## get_testers

Get the current list of testers for a specific testing track.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `track` | string | Yes | Track name: `internal`, `alpha`, or `beta` |

Returns: `track`, `tester_emails`

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
| `tester_emails` | list[string] | Yes | Email addresses or Google Group emails |

```python
update_testers(
    package_name="com.example.myapp",
    track="beta",
    tester_emails=[
        "tester1@example.com",
        "tester2@example.com",
        "beta-testers@googlegroups.com"
    ]
)
```

!!! warning
    This **replaces** the entire tester list — include all testers you want to keep. Google Group emails give access to all members of the group.
