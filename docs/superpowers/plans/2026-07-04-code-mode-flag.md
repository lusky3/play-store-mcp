# Code-Mode Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `CODE_MODE` flag that wraps the server's tool surface in FastMCP's experimental `CodeMode` transform (discovery meta-tools + sandboxed `execute`), cutting per-request tool-list token overhead — shipping **default-off** while the feature is experimental.

**Architecture:** Plan 2 of 2 (Plan 1 — the fastmcp v3 migration — is merged in #88). `CodeMode` lives in `fastmcp.experimental.transforms.code_mode` and is applied via the `FastMCP(..., transforms=[...])` constructor arg. When `CODE_MODE` is truthy, the server is built with `transforms=[CodeMode()]`, which replaces the 117 individual tools with three meta-tools (`search`, `get_schema`, `execute`); the LLM discovers tools and runs a script that calls them in a sandbox, returning only the final result. When off (default), `transforms=[]` and the classic 117-tool surface is unchanged. Because `transforms` is fixed at construction (module import, before `main()` parses argv), the flag is **environment-only** (`CODE_MODE`), unlike the call-time `--read-only`.

**Tech Stack:** Python ≥3.11, `fastmcp` ≥3.4.2 (already a dep), the `fastmcp[code-mode]` extra (Monty sandbox — only needed at runtime for `execute`), `uv`/`uv.lock`, `pytest`+`pytest-cov` (branch), `ruff`, `mypy`, `bandit`.

## Global Constraints

- **Default OFF.** `CODE_MODE` unset / `0` / `false` / `no` / `off` → classic 117-tool surface, byte-for-byte current behavior. Only `1`/`true`/`yes`/`on` (case-insensitive) enable it. Mirror `_env_read_only()`'s parsing exactly.
- **Environment-only flag** named `CODE_MODE` (no CLI flag — `transforms` is set at construction/import, before `main()`; document this).
- **Experimental.** `CodeMode` is marked experimental by FastMCP; the startup log and docs must say so.
- **Sandbox extra is opt-in.** The `execute` meta-tool's sandbox needs `fastmcp[code-mode]` (Monty). Keep it OUT of the base runtime deps (base install stays lean while default-off); expose it as a `code-mode` optional extra and add it to `dev` so tests/CI can exercise it.
- **No behavior change when off.** All 117 tools, `/health` + `/credentials`, per-request credentials, admin-token auth, `--read-only`, and DNS-rebinding are untouched in the default path. Read-only gating still applies under code-mode (the guards run inside each tool wrapper, which the sandbox's `call_tool` still invokes).
- **Coverage:** keep **100% branch coverage**. **Gates before push:** `ruff check`, `ruff format --check`, `mypy src/`, `bandit -r src/`, `pip-audit` — all clean, mirroring CI.
- **Commits/PRs carry no Claude attribution.**

## Verified against the installed fastmcp 3.4.2 (do not re-derive)

- `from fastmcp.experimental.transforms.code_mode import CodeMode` imports cleanly (even without the Monty extra).
- `CodeMode.__init__(*, sandbox_provider=None, discovery_tools=None, execute_tool_name="execute", execute_description=None, max_tool_calls=50)`.
- `FastMCP.__init__` accepts `transforms: Sequence[Transform] | None`.
- `FastMCP("x", transforms=[CodeMode()])` then registering tools via `@mcp.tool` → `await mcp.list_tools()` returns exactly `["search", "get_schema", "execute"]` (underlying tools hidden behind the meta-tools). Tools registered *after* construction are picked up. Without the transform, `list_tools()` returns the real tools.
- `monty` is NOT installed in the current env; `CodeMode()`/`MontySandboxProvider()` still construct (sandbox is created lazily at `execute` time), so enabling + listing works without the extra, but `execute` needs it.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `pyproject.toml` | Add `code-mode` optional extra; add `fastmcp[code-mode]` to `dev` | Modify |
| `uv.lock` | Locked resolution incl. the sandbox extra for dev | Regenerated |
| `src/play_store_mcp/server.py` | `_code_mode_enabled()`, `_build_transforms()`, `transforms=` in the `FastMCP(...)` constructor, startup log | Modify (near lines 143-160) |
| `tests/test_server_extended.py` | Flag parsing + transform-building tests | Modify |
| `CHANGELOG.md`, `docs/configuration.md`, `README.md` | Document `CODE_MODE` + the extra | Modify |

`client.py` and `models.py` are untouched.

---

## Task 1: Add the `CODE_MODE` flag, the transform wiring, and the optional sandbox extra

**Files:**
- Modify: `pyproject.toml` (`[project.optional-dependencies]`, ~lines 47-54)
- Modify: `src/play_store_mcp/server.py` (add helpers above the `mcp = FastMCP(...)` construction ~line 158; add `transforms=` to the constructor)
- Test: `tests/test_server_extended.py`

**Interfaces:**
- Produces: `_code_mode_enabled() -> bool`; `_build_transforms() -> list[Any]` (empty when off, `[CodeMode()]` when on); `mcp` constructed with `transforms=_build_transforms()`.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Add the `code-mode` optional extra and put it in `dev`**

In `pyproject.toml`, under `[project.optional-dependencies]`, add a `code-mode` extra and include it in `dev` so tests can exercise the sandbox:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.25.0",
    "pytest-cov>=6.0.0",
    "ruff>=0.9.0",
    "mypy>=1.14.0",
    "fastmcp[code-mode]>=3.4.2",
]
code-mode = [
    "fastmcp[code-mode]>=3.4.2",
]
```

- [ ] **Step 2: Lock and sync**

Run: `uv lock && uv sync --extra dev`
Expected: resolves the `fastmcp[code-mode]` extra (pulls the Monty sandbox), exit 0.

- [ ] **Step 3: Write the failing tests**

Add to `tests/test_server_extended.py`:

```python
@pytest.mark.parametrize(
    ("val", "expected"),
    [("1", True), ("true", True), ("YES", True), ("on", True),
     ("0", False), ("false", False), ("no", False), ("", False)],
)
def test_code_mode_flag_parsing(monkeypatch: pytest.MonkeyPatch, val: str, expected: bool) -> None:
    """CODE_MODE parses like the read-only flag (case-insensitive truthy set)."""
    from play_store_mcp import server

    monkeypatch.setenv("CODE_MODE", val)
    assert server._code_mode_enabled() is expected


def test_code_mode_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """With CODE_MODE unset, no transforms are built (classic tool surface)."""
    from play_store_mcp import server

    monkeypatch.delenv("CODE_MODE", raising=False)
    assert server._code_mode_enabled() is False
    assert server._build_transforms() == []


def test_build_transforms_enabled_wraps_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """When enabled, _build_transforms() yields a CodeMode that exposes meta-tools."""
    import asyncio

    from fastmcp import FastMCP

    from play_store_mcp import server

    monkeypatch.setenv("CODE_MODE", "1")
    transforms = server._build_transforms()
    assert len(transforms) == 1

    probe = FastMCP("probe", transforms=transforms)

    @probe.tool
    def sample(x: int) -> int:
        return x

    names = {t.name for t in asyncio.run(probe.list_tools())}
    assert names == {"search", "get_schema", "execute"}
```

- [ ] **Step 4: Run to verify they fail**

Run: `uv run pytest tests/test_server_extended.py -k "code_mode or build_transforms" -v`
Expected: FAIL — `server._code_mode_enabled` / `server._build_transforms` do not exist yet.

- [ ] **Step 5: Add the helpers and wire the constructor**

In `src/play_store_mcp/server.py`, immediately above the `mcp = FastMCP(...)` construction (currently ~line 158), add:

```python
def _code_mode_enabled() -> bool:
    """Return True if CODE_MODE enables the experimental code-mode transform."""
    return os.environ.get("CODE_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def _build_transforms() -> list[Any]:
    """Return the FastMCP transforms for this process.

    When CODE_MODE is enabled, wrap the tool surface in the experimental CodeMode
    transform (search/get_schema/execute meta-tools + sandboxed execution), which
    cuts per-request tool-list overhead. Default: no transforms — the classic
    117-tool surface, unchanged.
    """
    if not _code_mode_enabled():
        return []
    # Imported lazily so the base install (without the code-mode extra) never
    # pays for it when the flag is off.
    from fastmcp.experimental.transforms.code_mode import CodeMode

    logger.warning(
        "CODE_MODE enabled: exposing tools via the experimental code-mode transform "
        "(search/get_schema/execute). The 'execute' sandbox requires the code-mode "
        "extra — install play-store-mcp[code-mode]."
    )
    return [CodeMode()]
```

Then change the constructor (currently `mcp = FastMCP("Play Store MCP Server", lifespan=lifespan)`) to:

```python
mcp = FastMCP(
    "Play Store MCP Server",
    lifespan=lifespan,
    transforms=_build_transforms(),
)
```

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/test_server_extended.py -k "code_mode or build_transforms" -v`
Expected: PASS. The module-level `mcp` is still built with `CODE_MODE` unset in the test process, so the existing 117-tool tests are unaffected.

- [ ] **Step 7: Full suite + coverage**

Run: `uv run pytest -q --cov=src/play_store_mcp --cov-branch --cov-report=term-missing`
Expected: all pass, **100%**. Both `_build_transforms()` branches (off → `[]`, on → `[CodeMode()]`) and `_code_mode_enabled()` truthy/falsy are covered by the three tests above.

- [ ] **Step 8: Lint/type/security**

Run: `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, `uv run mypy src/`, `uv run --with bandit bandit -r src/ -q`.
Expected: clean. (`_build_transforms() -> list[Any]` satisfies mypy against `transforms: Sequence[Transform] | None`.)

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock src/play_store_mcp/server.py tests/test_server_extended.py
git commit -m "feat: add opt-in CODE_MODE flag wrapping tools in the fastmcp code-mode transform"
```

---

## Task 2: Integration check, docs, changelog, and PR

**Files:**
- Modify: `CHANGELOG.md`, `docs/configuration.md`, `README.md`

- [ ] **Step 1: Sandbox integration smoke (best-effort, documented)**

With the `code-mode` extra installed (Task 1 Step 2), verify the meta-tools appear and — if the sandbox can initialize in this environment — that `execute` runs:

Run:
```bash
CODE_MODE=1 uv run play-store-mcp --transport streamable-http --host 127.0.0.1 --port 8801 &
sleep 3
# The MCP tools/list should now advertise search/get_schema/execute rather than 117 tools.
curl -s http://127.0.0.1:8801/health -w " (%{http_code})\n"
kill %1
```
Confirm `/health` returns 200 and the server starts with the code-mode startup warning in stderr. A full `execute` round-trip depends on the Monty sandbox being runnable in the host (WASM/subprocess); if it cannot initialize here, record that the transform-level tests (Task 1) plus fastmcp's own upstream sandbox tests are the coverage, and note the limitation in the PR. Do **not** fabricate a passing sandbox run.

- [ ] **Step 2: Document `CODE_MODE` in `docs/configuration.md`**

Add a row to the environment-variable table and a short section:

```markdown
| `CODE_MODE` | Enable the experimental code-mode transform (opt-in; requires the `code-mode` extra) | No (default: off) |
```

And a subsection explaining: code-mode replaces the individual tools with `search`/`get_schema`/`execute` meta-tools to reduce per-request token overhead; it is experimental and off by default; enabling it requires installing `play-store-mcp[code-mode]` (Monty sandbox) and setting `CODE_MODE=1`; it is env-only (not a CLI flag) because the transform is fixed when the server is constructed.

- [ ] **Step 3: Mention code-mode in `README.md`**

Add a short line under the configuration/usage section noting the opt-in `CODE_MODE` flag and the `play-store-mcp[code-mode]` install extra, flagged experimental.

- [ ] **Step 4: Update the changelog**

In `CHANGELOG.md` under `## [Unreleased]`, add:

```markdown
### Added
- **Experimental code-mode (opt-in):** set `CODE_MODE=1` to expose tools through
  FastMCP's code-mode transform (`search`/`get_schema`/`execute` meta-tools with a
  sandboxed executor) instead of the full tool list, reducing per-request tool-list
  token overhead. Off by default; requires the `play-store-mcp[code-mode]` extra
  (Monty sandbox) for the `execute` tool. This is the first step of the tool-surface
  reduction noted under Planned.
```

- [ ] **Step 5: Full gate**

Run the complete CI mirror: `uv run pytest -q --cov=src/play_store_mcp --cov-branch` (100%), `ruff check`, `ruff format --check`, `mypy src/`, `bandit -r src/`, `pip-audit`. All clean.

- [ ] **Step 6: Commit, push, draft PR**

```bash
git add CHANGELOG.md docs/configuration.md README.md
git commit -m "docs: document the opt-in CODE_MODE flag and code-mode extra"
git push -u origin feat/code-mode
```
Open a **draft** PR titled `feat: opt-in CODE_MODE flag (experimental code-mode transform)`, body covering the flag, default-off rationale, the optional sandbox extra, the env-only design, and the integration-check result. Do not mark ready / merge until CI is green.

---

## Self-Review

**Spec coverage:** the `CODE_MODE` flag (env-only, default-off) → T1; the transform wiring + optional extra → T1; experimental/sandbox documentation → T2; changelog → T2. The user's stated requirement ("flag `CODE_MODE=` where true/1 uses code mode and false/0 off", default-off per the later rollout decision) is met by `_code_mode_enabled()` + the default-empty `_build_transforms()`.

**Placeholders:** the only non-deterministic step is Task 2 Step 1 (whether the Monty sandbox can execute in the host), which ships with a concrete command, a pass criterion (`/health` 200 + startup warning + meta-tools advertised), and an explicit documented fallback — not a TBD.

**Type consistency:** `_code_mode_enabled() -> bool` and `_build_transforms() -> list[Any]` are used consistently; the constructor receives `transforms=_build_transforms()`. All fastmcp APIs used (`CodeMode`, `transforms=`, `list_tools`) were verified against the installed 3.4.2 in the section above.

**Note vs Plan 1:** unlike `--read-only` (a call-time mutable global), `CODE_MODE` must be read at construction/import because `transforms` is a constructor arg — hence env-only. A future CLI `--code-mode` would require building `mcp` lazily inside `main()`; out of scope here.
