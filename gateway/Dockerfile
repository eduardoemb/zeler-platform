FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY core ./core
COPY gateway ./gateway

RUN uv sync --frozen --package zeler-gateway --no-dev

RUN useradd --system --create-home --uid 1001 appuser
RUN chown -R appuser:appuser /app
USER appuser

CMD ["sh", "-c", "uv run uvicorn zeler_gateway.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
