#!/usr/bin/env python3
"""Generate the four ingestion batches for the iris-versioned demo project.

Four batches, each a directory the ``sequencing-runs`` scanner picks up as its
own ``depictio_run_id``. Ingesting them one at a time produces four Delta
versions whose *content* genuinely differs, which is the point: a versioning
demo where every version holds the same rows demonstrates nothing.

The row counts are deliberately 50 / 100 / 100 / 150:

  batch_01  Setosa only,                50 rows   — the first collection
  batch_02  adds Versicolor,           100 rows   — the survey grows
  batch_03  Setosa re-measured,        100 rows   — a correction, SAME count
  batch_04  adds Virginica,            150 rows   — the full dataset

Every step changes the number *except* batch 3, and that asymmetry is the
design. A row count moving 50 → 100 → 150 makes time travel obvious at a
glance, so a demo made only of those steps would pass while being wrong in the
one way that matters: batch 3 has the same count and the same varieties as
batch 2, so the only thing distinguishing them is the values. That is the case
where "which data version was this chart built on" stops being rhetorical, and
the case a row-count check cannot catch.

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

#: Batch 3 re-measures Setosa after a calibration fix. Large enough to move a
#: mean visibly on a chart, small enough to stay biologically sensible.
#:
#: Applied to Setosa specifically because Setosa is present from batch 1: the
#: correction therefore changes a value the earlier versions already had,
#: rather than one that arrived with the batch. Time travel that only ever
#: adds rows is the easy half.
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

    # Batch 1 — the first collection: Setosa only.
    batch_1 = [r for r in rows if r["variety"] == "Setosa"]

    # Batch 2 — Versicolor arrives. Batch 1's rows are untouched, so the diff
    # from v0 to v1 is purely additive.
    batch_2 = [r for r in rows if r["variety"] in {"Setosa", "Versicolor"}]

    # Batch 3 — Setosa petal lengths re-measured after a calibration fix. Same
    # rows, same count, same varieties as batch 2: only the values differ, so
    # only the data version tells them apart. This is the batch that catches a
    # time-travel bug a row count would sail past.
    batch_3 = []
    for row in batch_2:
        updated = dict(row)
        if row["variety"] == "Setosa":
            corrected = float(row["petal.length"]) + PETAL_CALIBRATION_CM
            # A little jitter so it reads as a re-measurement rather than a
            # constant offset applied in a spreadsheet.
            corrected += random.uniform(-0.05, 0.05)
            updated["petal.length"] = f"{corrected:.2f}"
        batch_3.append(updated)

    # Batch 4 — Virginica arrives, on top of the corrected Setosa values, so
    # the final state carries both kinds of change.
    corrected_by_key = {(r["sepal.length"], r["sepal.width"], r["variety"]): r for r in batch_3}
    batch_4 = []
    for row in rows:
        key = (row["sepal.length"], row["sepal.width"], row["variety"])
        batch_4.append(dict(corrected_by_key.get(key, row)))

    print("Writing iris_versioned batches:")
    write_batch("batch_01_setosa_only", header, batch_1)
    write_batch("batch_02_versicolor_added", header, batch_2)
    write_batch("batch_03_setosa_recalibrated", header, batch_3)
    write_batch("batch_04_virginica_added", header, batch_4)
    print("\nStage them into data/ with ./stage_batch.sh 1|2|3|4 — see README.md.")


if __name__ == "__main__":
    main()
