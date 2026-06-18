# Build stage
FROM python:3.14-alpine@sha256:26730869004e2b9c4b9ad09cab8625e81d256d1ce97e72df5520e806b1709f92 AS builder

WORKDIR /build

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock README.md ./
COPY src/ src/

# Build wheel, then install into venv at the final runtime path
# so shebangs point to /app/.venv/bin/python
RUN uv build --wheel --out-dir /build/dist && \
    uv venv /app/.venv && \
    uv pip install --no-cache /build/dist/*.whl --python /app/.venv/bin/python

# Runtime stage
FROM python:3.14-alpine@sha256:26730869004e2b9c4b9ad09cab8625e81d256d1ce97e72df5520e806b1709f92

LABEL org.opencontainers.image.source="https://github.com/lusky3/play-store-mcp"
LABEL org.opencontainers.image.url="https://github.com/lusky3/play-store-mcp"
LABEL org.opencontainers.image.documentation="https://lusky3.github.io/play-store-mcp"
LABEL org.opencontainers.image.description="MCP server for Google Play Developer API — deploy apps, manage releases, reviews, and more"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.title="play-store-mcp"

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
