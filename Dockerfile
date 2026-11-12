FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH"

RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependencies first, so editing code does not reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY seed ./seed
COPY scripts ./scripts
RUN uv sync --frozen --no-dev

# Run as a normal user. The scoring cache and call ledger live in /app/.cache.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/.cache \
    && chown app:app /app/.cache
USER app

# Hosts set PORT themselves; 8000 is the default.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn critisizer.main:app --host 0.0.0.0 --port ${PORT}"]