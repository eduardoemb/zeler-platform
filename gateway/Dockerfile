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

RUN test -f .venv/bin/uvicorn

RUN useradd --system --create-home --uid 1001 appuser
RUN chown -R appuser:appuser /app
USER appuser

CMD ["sh", "-c", ".venv/bin/uvicorn zeler_gateway.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import os,sys,urllib.request; port=os.environ.get('PORT','8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=5).status == 200 else 1)"
