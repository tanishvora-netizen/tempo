"""Load the committed synthetic datasets (the host never generates data)."""

from functools import cache
from pathlib import Path

from tempo.models import Dataset
from tempo.serde import load_json

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@cache
def load_dataset(regime: str = "demo") -> Dataset:
    """Read data/<regime>/dataset.json (cached per process)."""
    return load_json(Dataset, DATA_DIR / regime / "dataset.json")
