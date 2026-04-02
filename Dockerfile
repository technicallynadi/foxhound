FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first (cache layer)
COPY pyproject.toml uv.lock ./

# Skip Playwright browser download — we only use connect_over_cdp()
# which connects to TinyFish's remote browser, no local browser needed
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# Install Python deps
RUN uv pip install --system --no-cache -r pyproject.toml

# Copy application code
COPY app/ app/
COPY .foxhound/skills.yaml .foxhound/skills.yaml

# Create static directory if it doesn't exist
RUN mkdir -p app/static

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run with single worker (required for in-memory token store)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--timeout-keep-alive", "120"]
