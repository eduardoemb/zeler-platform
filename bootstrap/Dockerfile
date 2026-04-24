FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY core ./core
COPY bootstrap ./bootstrap

RUN uv sync --frozen --package zeler-bootstrap --no-dev

ENTRYPOINT ["uv", "run", "python", "-m", "zeler_bootstrap"]
