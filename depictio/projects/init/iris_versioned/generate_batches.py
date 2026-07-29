#!/usr/bin/env python3
"""Generate the three ingestion batches for the iris-versioned demo project.

Three batches, each a directory the ``sequencing-runs`` scanner picks up as its
own ``depictio_run_id``. Ingesting them one at a time with
``--write-mode replace-runs`` produces three Delta versions whose *content*
genuinely differs, which is the point: a versioning demo where every version
holds the same rows demonstrates nothing.

The batches tell a story a reviewer can check by eye:

  batch_01  Setosa + Versicolor, 100 rows      — the original survey
  batch_02  adds Virginica, 150 rows           — a new variety arrives
  batch_03  Virginica re-measured, 150 rows    — a correction, same row count

Batch 3 matters most. It has the same shape as batch 2 and the same varieties,
so the only way to tell them apart is the values — exactly the case where "which
data version was this chart built on" stops being a rhetorical question.

Derived from the bundled ``iris.csv`` rather than random draws, so the demo
still looks like the dataset people recognise. Deterministic: fixed seed, and
re-running overwrites byte-identically.

Usage:
    python depictio/projects/init/iris_versioned/generate_batches.py
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

HERE = Path(__file__).parent
SOURCE = HERE.parent / "iris" / "data" / "iris.csv"

#: The batch library. `stage_batch.sh` copies from here into `data/`, which is
#: what the project's `locations` actually point at — so a batch only becomes
#: visible to `depictio run` once it has been staged.
BATCHES_DIR = HERE / "batches"

#: Fixed so regeneration is reproducible; the jitter only needs to be
#: *plausible*, not novel.
SEED = 20260729

#: Batch 3 re-measures Virginica after a calibration fix. Large enough to move
#: a median visibly on a chart, small enough to stay biologically sensible.
PETAL_CALIBRATION_CM = 0.6


def read_source() -> tuple[list[str], list[dict[str, str]]]:
    with SOURCE.open() as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        assert reader.fieldnames is not None
        return list(reader.fieldnames), rows


def write_batch(name: str, header: list[str], rows: list[dict[str, str]]) -> None:
    out_dir = BATCHES_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "iris.csv"
    with target.open("w", newline="") as handle:
        # Quote only the non-numeric field. `QUOTE_NONNUMERIC` would quote
        # everything, since every value is a `str` at this point — and a quoted
        # "5.1" is read back as a string, so the measurement columns would land
        # in Delta as text and every numeric aggregation would fail.
        writer = csv.DictWriter(handle, fieldnames=header, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)
    varieties = sorted({r["variety"] for r in rows})
    print(f"  {name:34} {len(rows):>4} rows  {', '.join(varieties)}")


def main() -> None:
    random.seed(SEED)
    header, rows = read_source()

    # Batch 1 — the original survey: two varieties only.
    batch_1 = [r for r in rows if r["variety"] in {"Setosa", "Versicolor"}]

    # Batch 2 — Virginica arrives. Everything from batch 1 is unchanged, so a
    # diff between v0 and v1 is purely additive.
    batch_2 = list(rows)

    # Batch 3 — Virginica petal lengths re-measured after a calibration fix.
    # Same rows, same count, different values: only the data version tells them
    # apart.
    batch_3 = []
    for row in rows:
        updated = dict(row)
        if row["variety"] == "Virginica":
            corrected = float(row["petal.length"]) - PETAL_CALIBRATION_CM
            # A little jitter so it reads as a re-measurement rather than a
            # constant offset applied in a spreadsheet.
            corrected += random.uniform(-0.05, 0.05)
            updated["petal.length"] = f"{corrected:.2f}"
        batch_3.append(updated)

    print("Writing iris_versioned batches:")
    write_batch("batch_01_initial_survey", header, batch_1)
    write_batch("batch_02_virginica_added", header, batch_2)
    write_batch("batch_03_virginica_recalibrated", header, batch_3)
    print("\nStage them into data/ with ./stage_batch.sh 1|2|3 — see README.md.")


if __name__ == "__main__":
    main()
