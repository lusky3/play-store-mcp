# Contributing to Play Store MCP Server

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## Development Setup

1. **Clone the repository**

   ```bash
   git clone https://github.com/play-store-mcp/play-store-mcp.git
   cd play-store-mcp
   ```

2. **Install uv** (recommended) or use pip

   ```bash
   # Using uv (recommended)
   curl -LsSf https://astral.sh/uv/install.sh | sh
   
   # Install dependencies
   uv sync --extra dev
   ```

3. **Run tests**

   ```bash
   uv run pytest -v
   ```

## Code Style

We use **ruff** for linting and formatting. Code must pass all checks before merging.

```bash
# Check for issues
uv run ruff check src/ tests/

# Auto-fix issues
uv run ruff check --fix src/ tests/

# Format code
uv run ruff format src/ tests/
```

## Type Checking

We use **mypy** for static type checking with strict mode enabled.

```bash
uv run mypy src/
```

## Testing

- Write tests for all new features
- Maintain or improve test coverage
- Use pytest fixtures from `conftest.py`
- Mock external API calls

```bash
# Run with coverage
uv run pytest -v --cov=src/play_store_mcp --cov-report=term-missing
```

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Ensure tests pass and code is formatted
5. Commit with clear messages
6. Push and create a Pull Request

## Commit Messages

Use clear, descriptive commit messages:

- `feat: add new tool for listing in-app products`
- `fix: handle API timeout errors gracefully`
- `docs: update README with new configuration options`
- `test: add tests for subscription status checking`

## Adding New Tools

When adding a new MCP tool:

1. Add any required models to `models.py`
2. Implement the API method in `client.py`
3. Add the tool decorator in `server.py`
4. Write tests in `tests/`
5. Update README.md with tool documentation

## Questions?

Open an issue for questions or discussion about potential contributions.
