"""The market screener (docs/SCREENER.md): Stage 1 (stage1.py) judges the
financial statements, Stage 2 (stage2.py) the price; run.py runs both and saves the run."""

from .run import result_rows, run

__all__ = ["result_rows", "run"]
