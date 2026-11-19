# The ingest job's container (issue #18, docs/INGEST.md): this repository's package and its
# config/, nothing else. It runs one ingest (fetch, build, coverage snapshot) and exits.
# Azure Container Apps runs it on a schedule as a Job; locally:
#   docker build -t stock-ingest .
#   docker run --rm --env-file .env -e STOCK_DB_TARGET=local-writer \
#     --add-host=host.docker.internal:host-gateway stock-ingest
# Secrets come from the environment only (SEC_USER_AGENT, STOCK_WRITER_DB_PASSWORD, ...).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Dependencies first (cached until pyproject.toml or uv.lock change), then the code.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY config ./config
RUN uv sync --frozen --no-dev

# yfinance keeps a small cache; give it a writable place.
ENV XDG_CACHE_HOME=/tmp/cache
# Which database: a target in config/database.toml (server-writer on Azure).
ENV STOCK_DB_TARGET=server-writer
ENTRYPOINT ["/app/.venv/bin/python", "-m", "stock_analysis.db"]
CMD ["ingest"]
