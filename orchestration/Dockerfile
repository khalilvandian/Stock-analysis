# Airflow for the stock pipeline (issue #30, docs/ORCHESTRATION.md). The official image
# already has what the pipeline's code needs (httpx, psycopg 3, azure-identity): the tasks
# only start Azure jobs, run a few SQL checks and call GitHub and Brevo, so the project's
# heavy dependencies (pandas, ...) stay in the jobs' own image.
#
# The code is copied in for the VM (production); locally compose mounts the repository over
# /opt/stock instead, so a change needs no rebuild.
FROM apache/airflow:3.4.0-python3.12

COPY --chown=airflow config /opt/stock/config
COPY --chown=airflow src/stock_analysis/__init__.py /opt/stock/src/stock_analysis/__init__.py
COPY --chown=airflow src/stock_analysis/pipeline /opt/stock/src/stock_analysis/pipeline
COPY --chown=airflow orchestration/dags /opt/stock/orchestration/dags
COPY --chown=airflow orchestration/plugins /opt/stock/orchestration/plugins

ENV PYTHONPATH=/opt/stock/src \
    AIRFLOW__CORE__DAGS_FOLDER=/opt/stock/orchestration/dags \
    AIRFLOW__CORE__PLUGINS_FOLDER=/opt/stock/orchestration/plugins \
    AIRFLOW__CORE__LOAD_EXAMPLES=false
