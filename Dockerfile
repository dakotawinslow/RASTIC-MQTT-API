FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install runtime dependencies (separate layer for cache efficiency)
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

# Copy application
COPY mqtt_api.py .

EXPOSE 8443

CMD ["uv", "run", "python", "mqtt_api.py"]
