"""Predictive analysis: point-in-time features, "goodness" labels and walk-forward models.

See docs/PREDICT.md and reports/15-predictive-analysis.md.
"""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config/predict.toml"
CACHE = ROOT / ".cache/predict"
DATA = ROOT / "data/predict"


def load_config(path: Path = CONFIG) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)
