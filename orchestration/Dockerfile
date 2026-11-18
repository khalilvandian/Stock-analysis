# Airflow for the nightly pipeline (issue #30, docs/ORCHESTRATION.md), with this project's
# dependencies in their own environment (/opt/stock-venv): Airflow and the project pin
# different SQLAlchemy versions, so the DAG runs the project's commands with that
# interpreter instead of importing them. The code itself is mounted at /opt/stock.
FROM apache/airflow:3.4.0-python3.12

USER root
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /bin/uv
RUN mkdir -p /opt/stock-venv && chown airflow: /opt/stock-venv
USER airflow

ENV UV_PROJECT_ENVIRONMENT=/opt/stock-venv UV_PYTHON=/usr/python/bin/python3.12 \
    UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /tmp/stock
COPY --chown=airflow pyproject.toml uv.lock README.md ./
RUN VIRTUAL_ENV= uv sync --frozen --no-dev --no-install-project && rm -rf /home/airflow/.cache/uv
WORKDIR /opt/airflow
ENV STOCK_PYTHON=/opt/stock-venv/bin/python STOCK_PROJECT=/opt/stock
