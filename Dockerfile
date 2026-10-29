# Build stage
FROM python:3.15-alpine@sha256:0aa144e9ec2ae8fd80dfd94070ef3e432a0df17b6e5e0091dc05323974ce9913 AS builder

WORKDIR /build

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock README.md ./
COPY src/ src/

# Sync straight from the lockfile into the final runtime venv path (so
# shebangs point to /app/.venv/bin/python), instead of building a wheel and
# letting `uv pip install` re-resolve deps fresh — that re-resolution doesn't
# see uv.lock's already-decided prerelease pins and can fail to reproduce it.
RUN UV_PROJECT_ENVIRONMENT=/app/.venv uv sync --frozen --no-editable

# Runtime stage
FROM python:3.15-alpine@sha256:0aa144e9ec2ae8fd80dfd94070ef3e432a0df17b6e5e0091dc05323974ce9913

LABEL org.opencontainers.image.source="https://github.com/lusky3/play-store-mcp"
LABEL org.opencontainers.image.url="https://github.com/lusky3/play-store-mcp"
LABEL org.opencontainers.image.documentation="https://lusky3.github.io/play-store-mcp"
LABEL org.opencontainers.image.description="MCP server for Google Play Developer API — deploy apps, manage releases, reviews, and more"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.title="play-store-mcp"

# Pick up any Alpine security patches released since this base image digest
# was built (e.g. libuuid), without waiting on a new upstream base-image
# build to bump the pin.
RUN apk upgrade --no-cache

# Security hardening: non-root user, no shell
RUN addgroup -S mcp && \
    adduser -S -G mcp -h /app -s /sbin/nologin mcp

WORKDIR /app

# Copy virtual environment from builder (already at /app/.venv)
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=stdio \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

EXPOSE 8000

USER mcp

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
  CMD if [ "$MCP_TRANSPORT" = "streamable-http" ]; then wget -qO- http://localhost:${MCP_PORT:-8000}/health || exit 1; else exit 0; fi

ENTRYPOINT ["play-store-mcp"]
