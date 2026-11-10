"""Generate the committed synthetic datasets: data/demo/ and data/ample/. ALL DATA IS SYNTHETIC.

The demo regime's starting cash comes from data/demo/calibration.json (written by scripts/calibrate_cash.py,
which sweeps at most 6 starting-cash values on seed D); nothing else is tuned.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.data.generator import DEFAULT_STARTING_CASH_CENTS, GeneratorConfig, generate
from tempo.serde import dump_json

DATA = Path(__file__).resolve().parents[1] / "data"
CALIBRATION = DATA / "demo" / "calibration.json"


def calibrated_cash() -> int:
    if CALIBRATION.exists():
        return int(json.loads(CALIBRATION.read_text())["starting_cash_cents"])
    return DEFAULT_STARTING_CASH_CENTS


def main() -> None:
    cash = calibrated_cash()
    for regime in ("demo", "ample"):
        dataset = generate(GeneratorConfig(regime=regime, starting_cash_cents=cash))
        dump_json(dataset, DATA / regime / "dataset.json")
        print(
            f"{regime}: {len(dataset.invoices)} bills, starting cash ${dataset.company.starting_cash_cents / 100:,.0f}"
        )


if __name__ == "__main__":
    main()
