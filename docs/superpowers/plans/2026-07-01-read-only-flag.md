# Read-Only Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in read-only mode that disables every write/mutating MCP tool so the server can be pointed at a live Play Console safely.

**Architecture:** A module-level `READ_ONLY` flag in `server.py` is initialized from the `PLAY_STORE_MCP_READ_ONLY` environment variable at import time and can be overridden by a new `--read-only` CLI flag in `main()`. A tiny guard helper `_read_only_block(operation)` is called as the first statement of each of the 9 write tools; when read-only is active it returns a structured `{"error": ...}` (mirroring the existing `if err := _validate_...(): return {"error": err}` pattern) without touching the Play API client. Read tools are untouched.

**Tech Stack:** Python 3.11+, `mcp` (FastMCP), `structlog`, `pytest` / `pytest-asyncio`, `ruff`, `mypy`, `uv`.

## Global Constraints

- Python `>=3.11`; code must pass `uv run --frozen ruff check`, `uv run --frozen ruff format --check`, and `uv run --frozen mypy src/play_store_mcp`.
- No new runtime dependencies.
- Coverage target: keep `src/play_store_mcp` at 100% statements (project currently at 99–100%). Every new branch must be tested.
- All tool functions are synchronous `def` and return `dict[str, Any]` (writes) or `list[dict[str, Any]]` (some reads). The read-only error object is `{"error": "<message>"}` — same shape existing validators return.
- Env truthiness for `PLAY_STORE_MCP_READ_ONLY`: case-insensitive membership in `{"1", "true", "yes", "on"}`; everything else (including unset and `"0"`/`"false"`) is False.
- `tests/**` is excluded from Codacy/qlty static analysis (`.codacy.yaml`, `.qlty/qlty.toml`) and has ruff per-file ignores in `pyproject.toml`; put tests under `tests/`.
- Commit trailers on every commit:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01VtR3xYVpG3HwYJMASGbus2
  ```

---

## File Structure

- `src/play_store_mcp/server.py` (modify) — add the flag, env parser, guard helper, setter; add `if blocked := _read_only_block("<name>"): return blocked` to the 9 write tools; add `--read-only` CLI arg + startup-log field in `main()`.
- `tests/test_read_only.py` (create) — all tests for the new behavior.
- `README.md` (modify) — Environment Variables table + a short "Read-Only Mode" subsection.
- `docs/configuration.md` (modify) — Environment Variables table + a "Read-Only Mode" section.

The 9 write tools to gate (all in `server.py`): `deploy_app`, `deploy_app_multilang`, `promote_release`, `halt_release`, `update_rollout`, `reply_to_review`, `update_listing`, `update_testers`, `batch_deploy`. Read tools (unchanged): `get_releases`, `get_app_details`, `get_reviews`, `list_subscriptions`, `get_subscription_status`, `list_voided_purchases`, `get_vitals_overview`, `get_vitals_metrics`, `list_in_app_products`, `get_in_app_product`, `get_listing`, `list_all_listings`, `get_testers`, `get_order`, `get_expansion_file`, `validate_package_name`, `validate_track`, `validate_listing_text`.

---

### Task 1: Read-only core (flag, env parser, guard helper, setter)

**Files:**
- Modify: `src/play_store_mcp/server.py` (insert after the `_validate_rollout` function, before the `mcp = FastMCP(...)` block at line ~141)
- Test: `tests/test_read_only.py`

**Interfaces:**
- Produces:
  - `READ_ONLY: bool` — module global, initialized from env at import.
  - `_env_read_only() -> bool` — reads `PLAY_STORE_MCP_READ_ONLY` truthiness.
  - `set_read_only(value: bool) -> None` — reassigns the module global.
  - `_read_only_block(operation: str) -> dict[str, Any] | None` — returns `{"error": ...}` when read-only, else `None`.
  - `READ_ONLY_ERROR: str` — the message text (contains the phrase "read-only").

- [ ] **Step 1: Write the failing tests**

Create `tests/test_read_only.py`:

```python
"""Tests for read-only mode (flag, env parsing, guard helper)."""

from __future__ import annotations

import pytest

import play_store_mcp.server as server


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("Yes", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("", False),
        ("maybe", False),
    ],
)
def test_env_read_only_parsing(monkeypatch, value, expected):
    monkeypatch.setenv("PLAY_STORE_MCP_READ_ONLY", value)
    assert server._env_read_only() is expected


def test_env_read_only_unset(monkeypatch):
    monkeypatch.delenv("PLAY_STORE_MCP_READ_ONLY", raising=False)
    assert server._env_read_only() is False


def test_read_only_block_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    assert server._read_only_block("deploy_app") is None


def test_read_only_block_returns_error_when_enabled(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", True)
    result = server._read_only_block("deploy_app")
    assert result is not None
    assert "read-only" in result["error"].lower()
    assert "deploy_app" in result["error"]


def test_set_read_only_updates_global(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    server.set_read_only(True)
    assert server.READ_ONLY is True
    server.set_read_only(False)
    assert server.READ_ONLY is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --frozen pytest tests/test_read_only.py -v`
Expected: FAIL — `AttributeError: module 'play_store_mcp.server' has no attribute '_env_read_only'` (and the other new names).

- [ ] **Step 3: Implement the core in `server.py`**

Insert this block immediately after `_validate_rollout` (after line 138, before the `# Initialize the MCP server` comment at line ~140):

```python
def _env_read_only() -> bool:
    """Return True if PLAY_STORE_MCP_READ_ONLY is set to a truthy value."""
    return os.environ.get("PLAY_STORE_MCP_READ_ONLY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# When True, all write/mutating tools are disabled. Initialized from the
# environment at import time; may be overridden by the --read-only CLI flag.
READ_ONLY: bool = _env_read_only()

READ_ONLY_ERROR = (
    "Server is running in read-only mode; write operations are disabled. "
    "Unset PLAY_STORE_MCP_READ_ONLY (or omit --read-only) to enable writes."
)


def set_read_only(value: bool) -> None:
    """Set the process-wide read-only flag."""
    global READ_ONLY
    READ_ONLY = value


def _read_only_block(operation: str) -> dict[str, Any] | None:
    """Return an error object if read-only mode blocks a write, else None."""
    if READ_ONLY:
        logger.warning("Blocked write operation in read-only mode", operation=operation)
        return {"error": f"{READ_ONLY_ERROR} (attempted: {operation})"}
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --frozen pytest tests/test_read_only.py -v`
Expected: PASS (all Task-1 tests green).

- [ ] **Step 5: Lint / type-check the new code**

Run: `uv run --frozen ruff check src tests && uv run --frozen mypy src/play_store_mcp`
Expected: "All checks passed!" and "Success: no issues found".

- [ ] **Step 6: Commit**

```bash
git add src/play_store_mcp/server.py tests/test_read_only.py
git commit -m "feat: add read-only flag core (env parsing + guard helper)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VtR3xYVpG3HwYJMASGbus2"
```

---

### Task 2: Gate the 9 write tools

**Files:**
- Modify: `src/play_store_mcp/server.py` (add one guard line as the first statement of each write tool)
- Test: `tests/test_read_only.py` (append)

**Interfaces:**
- Consumes: `_read_only_block(operation)` and `READ_ONLY` from Task 1; `get_client_from_context()` (existing).
- Produces: no new symbols — behavior change only.

- [ ] **Step 1: Write the failing tests (append to `tests/test_read_only.py`)**

```python
from unittest.mock import MagicMock

# (tool_name, kwargs) — kwargs satisfy each signature; the guard returns
# before any argument is used, so values are arbitrary but well-typed.
WRITE_TOOLS = [
    ("deploy_app", {"package_name": "com.example.app", "track": "internal", "file_path": "/tmp/app.aab"}),
    ("deploy_app_multilang", {"package_name": "com.example.app", "track": "internal", "file_path": "/tmp/app.aab", "release_notes": {"en-US": "notes"}}),
    ("promote_release", {"package_name": "com.example.app", "from_track": "internal", "to_track": "alpha", "version_code": 1}),
    ("halt_release", {"package_name": "com.example.app", "track": "production", "version_code": 1}),
    ("update_rollout", {"package_name": "com.example.app", "track": "production", "version_code": 1, "rollout_percentage": 50.0}),
    ("reply_to_review", {"package_name": "com.example.app", "review_id": "r1", "reply_text": "thanks"}),
    ("update_listing", {"package_name": "com.example.app", "language": "en-US"}),
    ("update_testers", {"package_name": "com.example.app", "track": "internal", "google_groups": []}),
    ("batch_deploy", {"package_name": "com.example.app", "file_path": "/tmp/app.aab", "tracks": ["internal"]}),
]


@pytest.mark.parametrize(("tool_name", "kwargs"), WRITE_TOOLS)
def test_write_tool_blocked_in_read_only(monkeypatch, tool_name, kwargs):
    monkeypatch.setattr(server, "READ_ONLY", True)
    mock_ctx = MagicMock()  # get_client_from_context must NOT be called
    monkeypatch.setattr(server, "get_client_from_context", mock_ctx)

    result = getattr(server, tool_name)(**kwargs)

    assert "error" in result
    assert "read-only" in result["error"].lower()
    assert tool_name in result["error"]
    mock_ctx.assert_not_called()


def test_read_tool_not_blocked_in_read_only(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", True)
    mock_client = MagicMock()
    mock_client.get_releases.return_value = []
    monkeypatch.setattr(server, "get_client_from_context", lambda: mock_client)

    result = server.get_releases("com.example.app")

    assert result == []
    mock_client.get_releases.assert_called_once_with("com.example.app")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --frozen pytest tests/test_read_only.py -k "blocked_in_read_only" -v`
Expected: FAIL — write tools currently call `get_client_from_context` (mock IS called) / don't return the read-only error, so assertions fail.

- [ ] **Step 3: Add the guard line to each of the 9 write tools**

Insert `if blocked := _read_only_block("<tool_name>"): return blocked` as the FIRST statement of each write tool (before any existing `_validate_*` call). Exact edits:

`deploy_app` (before line 179 `if err := _validate_deploy_file(...)`):
```python
    if blocked := _read_only_block("deploy_app"):
        return blocked
    if err := _validate_deploy_file(file_path):
        return {"error": err}
```

`deploy_app_multilang` (before its `_validate_deploy_file`):
```python
    if blocked := _read_only_block("deploy_app_multilang"):
        return blocked
    if err := _validate_deploy_file(file_path):
        return {"error": err}
```

`promote_release` (before its `_validate_rollout`):
```python
    if blocked := _read_only_block("promote_release"):
        return blocked
    if err := _validate_rollout(rollout_percentage):
        return {"error": err}
```

`halt_release` (before `client = get_client_from_context()`):
```python
    if blocked := _read_only_block("halt_release"):
        return blocked
    client = get_client_from_context()
```

`update_rollout` (before its `_validate_rollout`):
```python
    if blocked := _read_only_block("update_rollout"):
        return blocked
    if err := _validate_rollout(rollout_percentage):
        return {"error": err}
```

`reply_to_review` (before `client = get_client_from_context()`):
```python
    if blocked := _read_only_block("reply_to_review"):
        return blocked
    client = get_client_from_context()
```

`update_listing` (before `client = get_client_from_context()`):
```python
    if blocked := _read_only_block("update_listing"):
        return blocked
    client = get_client_from_context()
```

`update_testers` (before `client = get_client_from_context()`):
```python
    if blocked := _read_only_block("update_testers"):
        return blocked
    client = get_client_from_context()
```

`batch_deploy` (before its `_validate_deploy_file` at line ~870):
```python
    if blocked := _read_only_block("batch_deploy"):
        return blocked
    if err := _validate_deploy_file(file_path):
        return {"error": err}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --frozen pytest tests/test_read_only.py -v`
Expected: PASS (all 9 parametrized block cases + read-tool case + Task-1 tests).

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `uv run --frozen pytest -q`
Expected: all previously-passing tests still pass (existing write-tool tests set `READ_ONLY` False by default, so they are unaffected), plus the new ones.

- [ ] **Step 6: Lint / type-check**

Run: `uv run --frozen ruff check src tests && uv run --frozen ruff format --check src tests && uv run --frozen mypy src/play_store_mcp`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add src/play_store_mcp/server.py tests/test_read_only.py
git commit -m "feat: block write tools when read-only mode is enabled

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VtR3xYVpG3HwYJMASGbus2"
```

---

### Task 3: CLI `--read-only` flag + startup log

**Files:**
- Modify: `src/play_store_mcp/server.py` (`main()`, lines ~1022–1063)
- Test: `tests/test_read_only.py` (append)

**Interfaces:**
- Consumes: `_env_read_only()`, `set_read_only()`, `READ_ONLY` (Task 1); `mcp.run` (existing).
- Produces: `--read-only` CLI flag; `read_only` field on the startup log line.

- [ ] **Step 1: Write the failing tests (append to `tests/test_read_only.py`)**

```python
def test_main_read_only_flag_sets_global(monkeypatch):
    monkeypatch.delenv("PLAY_STORE_MCP_READ_ONLY", raising=False)
    monkeypatch.setattr(server, "READ_ONLY", False)
    monkeypatch.setattr(server.mcp, "run", MagicMock())

    server.main(["--read-only"])

    assert server.READ_ONLY is True


def test_main_defaults_to_env_read_only(monkeypatch):
    monkeypatch.setenv("PLAY_STORE_MCP_READ_ONLY", "1")
    monkeypatch.setattr(server, "READ_ONLY", False)
    monkeypatch.setattr(server.mcp, "run", MagicMock())

    server.main([])

    assert server.READ_ONLY is True


def test_main_not_read_only_by_default(monkeypatch):
    monkeypatch.delenv("PLAY_STORE_MCP_READ_ONLY", raising=False)
    monkeypatch.setattr(server, "READ_ONLY", True)  # ensure main() actively clears it
    monkeypatch.setattr(server.mcp, "run", MagicMock())

    server.main([])

    assert server.READ_ONLY is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --frozen pytest tests/test_read_only.py -k "main" -v`
Expected: FAIL — `--read-only` is not a recognized argument (SystemExit from argparse) / `READ_ONLY` not reconciled.

- [ ] **Step 3: Add the CLI flag, reconcile the global, and log it in `main()`**

Add the argument after the existing `--credentials` argument block (before `args = parser.parse_args(argv)`):

```python
    parser.add_argument(
        "--read-only",
        action="store_true",
        default=_env_read_only(),
        help="Disable all write operations (or set PLAY_STORE_MCP_READ_ONLY=1)",
    )
```

After `args = parser.parse_args(argv)` and the existing `if args.credentials:` block, add:

```python
    set_read_only(args.read_only)
```

Update the existing `logger.info("Starting Play Store MCP Server", ...)` call to include the flag:

```python
    logger.info(
        "Starting Play Store MCP Server",
        transport=args.transport,
        host=args.host if args.transport != "stdio" else None,
        port=args.port if args.transport != "stdio" else None,
        read_only=READ_ONLY,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --frozen pytest tests/test_read_only.py -k "main" -v`
Expected: PASS.

- [ ] **Step 5: Full suite + lint + types + coverage**

Run:
```bash
uv run --frozen pytest --cov=play_store_mcp --cov-report=term-missing -q
uv run --frozen ruff check src tests && uv run --frozen ruff format --check src tests
uv run --frozen mypy src/play_store_mcp
```
Expected: all tests pass; `server.py` shows no newly-uncovered lines (100% statements, only the two pre-existing unreachable branch arcs may remain); ruff + mypy clean.

- [ ] **Step 6: Commit**

```bash
git add src/play_store_mcp/server.py tests/test_read_only.py
git commit -m "feat: add --read-only CLI flag and log read-only state on startup

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VtR3xYVpG3HwYJMASGbus2"
```

---

### Task 4: Documentation

**Files:**
- Modify: `README.md` (Environment Variables table ~line 300; add a "Read-Only Mode" subsection under Configuration)
- Modify: `docs/configuration.md` (Environment Variables table ~line 84; add a "Read-Only Mode" section)

**Interfaces:** none (docs only).

- [ ] **Step 1: Add the env var to the README table**

In `README.md`, in the `## 🔒 Environment Variables` table (after the `PLAY_STORE_MCP_DISABLE_DNS_REBINDING` row at line ~305), add:

```markdown
| `PLAY_STORE_MCP_READ_ONLY` | Disable all write operations (deploy, promote, rollout, reply, listing/tester updates) | No (default: off) |
```

- [ ] **Step 2: Add a Read-Only Mode subsection to the README**

In `README.md`, immediately before the `## 🔧 MCP Client Configuration` heading (line ~137), add:

```markdown
### Read-Only Mode

To point the server at a live Play Console without any risk of mutating it,
run in read-only mode. All write tools (deploy, promote, halt, rollout, reply
to reviews, listing/tester updates) return an error instead of calling the API;
read tools are unaffected.

```bash
play-store-mcp --read-only
# or
export PLAY_STORE_MCP_READ_ONLY=1
```

```

- [ ] **Step 3: Add the env var to the docs/configuration.md table**

In `docs/configuration.md`, in the `## Environment Variables` table (after the `PLAY_STORE_MCP_DISABLE_DNS_REBINDING` row at line ~84), add:

```markdown
| `PLAY_STORE_MCP_READ_ONLY` | Disable all write operations | No | — |
```

- [ ] **Step 4: Add a Read-Only Mode section to docs/configuration.md**

In `docs/configuration.md`, immediately before the `## Logging` heading (line ~131), add:

```markdown
## Read-Only Mode

Enable read-only mode to guarantee the server performs no writes against the
Play Developer API — useful for demos, audits, or pointing at a production app.
When active, every write tool (`deploy_app`, `deploy_app_multilang`,
`promote_release`, `halt_release`, `update_rollout`, `reply_to_review`,
`update_listing`, `update_testers`, `batch_deploy`) returns an error and never
contacts the API; all read/validation tools work normally.

Enable it with the CLI flag:

```bash
play-store-mcp --read-only
```

Or the environment variable (truthy values: `1`, `true`, `yes`, `on`):

```bash
export PLAY_STORE_MCP_READ_ONLY=1
```

```

- [ ] **Step 5: Verify the docs mention the flag**

Run: `grep -rn "PLAY_STORE_MCP_READ_ONLY\|Read-Only" README.md docs/configuration.md`
Expected: matches in both files (table row + section in each).

- [ ] **Step 6: Commit**

```bash
git add README.md docs/configuration.md
git commit -m "docs: document read-only mode (--read-only / PLAY_STORE_MCP_READ_ONLY)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VtR3xYVpG3HwYJMASGbus2"
```

---

### Task 5: Final verification gate (before PR)

**Files:** none (verification only).

- [ ] **Step 1: Full quality gate**

Run:
```bash
uv run --frozen pytest --cov=play_store_mcp --cov-report=term-missing -q
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv run --frozen mypy src/play_store_mcp
```
Expected: all tests pass (existing + new read-only tests), `src/play_store_mcp` at 100% statements (only the two known unreachable branch arcs may remain: `client.py:86->exit`, `server.py:964->984`), ruff + format + mypy all clean.

- [ ] **Step 2: Manual smoke — read-only blocks a write, allows a read (no live API)**

Run:
```bash
PLAY_STORE_MCP_READ_ONLY=1 uv run --frozen python -c "
import play_store_mcp.server as s
print('READ_ONLY at import:', s.READ_ONLY)
print('write ->', s.deploy_app(package_name='com.x', track='internal', file_path='/tmp/x.aab'))
"
```
Expected: `READ_ONLY at import: True` and a `{'error': '...read-only...deploy_app...'}` dict (no credentials error, proving the guard short-circuits before the client).

- [ ] **Step 3: Manual smoke — /health still serves in read-only (starlette path unaffected)**

Optional if time permits; otherwise covered by existing tests. Not required for the gate.

---

## Self-Review

**Spec coverage:** The feature = "a read-only flag." Covered: env var (`PLAY_STORE_MCP_READ_ONLY`, Task 1), CLI flag (`--read-only`, Task 3), enforcement across all 9 write tools (Task 2), reads unaffected (Task 2 test), startup visibility (Task 3 log), docs (Task 4), verification (Task 5). No gaps.

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to". Every code step shows the exact code; every run step shows the exact command and expected result.

**Type consistency:** `_env_read_only() -> bool`, `set_read_only(value: bool) -> None`, `_read_only_block(operation: str) -> dict[str, Any] | None`, module `READ_ONLY: bool`, `READ_ONLY_ERROR: str` — used consistently across Tasks 1–3 and the tests. The `--read-only` default uses `_env_read_only()` (evaluated at `main()` runtime so tests can toggle the env), not the import-time `READ_ONLY` constant — this is required for `test_main_defaults_to_env_read_only` to pass.
