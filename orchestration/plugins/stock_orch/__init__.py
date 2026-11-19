"""Airflow pieces for the stock pipeline (issue #30, docs/ORCHESTRATION.md).

- azure_jobs: start an Azure Container Apps Job run and wait for it in the triggerer.
- github: wait for the Claude session's commit and its published site in the triggerer.
- runlog: the run log (ops_pipeline_run, ops_pipeline_step), the checks and the alert,
  through stock_analysis.pipeline, which needs only psycopg and httpx.

This folder is Airflow's plugins folder, so the scheduler, the triggerer and the task
processes all import `stock_orch` the same way.
"""
