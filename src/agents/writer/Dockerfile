FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency manifests first for better Docker layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (including pre-releases required by Agent Framework)
RUN uv sync --frozen --prerelease=allow

# Copy source
COPY src ./src

ENV PYTHONPATH=/app/src

ENV PYTHONUNBUFFERED=1

# Azure Container Apps sets $PORT
CMD ["sh", "-c", "uv run --prerelease=allow uvicorn agents.writer.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
