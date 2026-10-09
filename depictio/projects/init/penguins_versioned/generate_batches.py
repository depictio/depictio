#!/usr/bin/env python3
"""Generate the five ingestion batches of the penguins_versioned demo.

Source: the bundled `penguins` project's CSVs (depictio/projects/init/penguins/
data/run_*/), which are the palmerpenguins observations split by species. Here
they are re-cut by **field season** instead, because the `year` column gives the
data a natural arrival order: 2007, then 2008, then 2009.

Each batch directory is the *complete* state of the survey at that point, laid
out as one run per season (`season_2007/`, ...), each run holding the two
datasets:

  physical_features.csv  individual_id, species, island, year,
                         bill_length_mm, bill_depth_mm, flipper_length_mm, body_mass_g
  demographic_data.csv   individual_id, species, island, year, sex

`species`, `island` and `year` are carried by both files on purpose. Without a
join, a dashboard filter reaches another collection only through a column of the
same name, so these three are what let one Species or Season filter narrow both
datasets at once.

Two batches are corrections rather than arrivals, and both are SYNTHETIC:

  batch 3  every 2007 body mass x 1.05, plus a seeded jitter of up to +/- 20 g,
           as if the 2007 scale had been found to read low. physical_features
           only; demographic_data is byte-identical to batch 2.
  batch 5  the 9 birds with no recorded sex get one, imputed from body mass
           (heavier than their species' median: male, else female).
           demographic_data only; physical_features is byte-identical to batch 4.

Neither correction exists in the real dataset. They exist so that each dataset
moves once while the other stands still, with the row count unchanged: the case
where only a correct data pin can tell two versions apart.

Deterministic: fixed seed, fixed row order, and re-running rewrites the same
bytes.

Usage:
    python depictio/projects/init/penguins_versioned/generate_batches.py
"""

from __future__ import annotations

import csv
import random
import shutil
import statistics

from penguins_story import (
    BATCHES_DIR,
    HERE,
    RECALIBRATION_FACTOR,
    RECALIBRATION_JITTER_G,
    SEASONS,
    SEED,
    STEPS,
)

SOURCE_DIR = HERE.parent / "penguins" / "data"

PF_COLUMNS = [
    "individual_id",
    "species",
    "island",
    "year",
    "bill_length_mm",
    "bill_depth_mm",
    "flipper_length_mm",
    "body_mass_g",
]
DD_COLUMNS = ["individual_id", "species", "island", "year", "sex"]


def read_source() -> list[dict[str, str]]:
    """Every bird, physical and demographic fields merged, in source order."""
    birds: list[dict[str, str]] = []
    for run_dir in sorted(SOURCE_DIR.glob("run_*")):
        with (run_dir / "demographic_data.csv").open() as handle:
            demographic = {row["individual_id"]: row for row in csv.DictReader(handle)}
        with (run_dir / "physical_features.csv").open() as handle:
            for row in csv.DictReader(handle):
                birds.append({**row, **demographic[row["individual_id"]]})
    return birds


def recalibrate(birds: list[dict[str, str]]) -> list[dict[str, str]]:
    """Batch 3's synthetic correction: 2007 body masses scaled up by 5%."""
    rng = random.Random(SEED)
    corrected = []
    for bird in birds:
        bird = dict(bird)
        if bird["year"] == "2007":
            mass = float(bird["body_mass_g"]) * RECALIBRATION_FACTOR
            mass += rng.uniform(-RECALIBRATION_JITTER_G, RECALIBRATION_JITTER_G)
            bird["body_mass_g"] = f"{round(mass):.1f}"
        corrected.append(bird)
    return corrected


def complete_sex(birds: list[dict[str, str]]) -> list[dict[str, str]]:
    """Batch 5's synthetic correction: a sex for every bird that had none.

    Imputed from body mass against the species median of the sexed birds, from
    the source masses so the rule does not depend on batch 3's correction.
    """
    source_mass = {bird["individual_id"]: float(bird["body_mass_g"]) for bird in read_source()}
    medians = {
        species: statistics.median(
            source_mass[b["individual_id"]] for b in birds if b["species"] == species and b["sex"]
        )
        for species in sorted({b["species"] for b in birds})
    }
    completed = []
    for bird in birds:
        bird = dict(bird)
        if not bird["sex"]:
            heavier = source_mass[bird["individual_id"]] > medians[bird["species"]]
            bird["sex"] = "male" if heavier else "female"
        completed.append(bird)
    return completed


def write_batch(name: str, birds: list[dict[str, str]], seasons: tuple[int, ...]) -> None:
    out = BATCHES_DIR / name
    if out.exists():
        shutil.rmtree(out)
    for season in seasons:
        run_dir = out / f"season_{season}"
        run_dir.mkdir(parents=True)
        rows = [b for b in birds if b["year"] == str(season)]
        for filename, columns in (
            ("physical_features.csv", PF_COLUMNS),
            ("demographic_data.csv", DD_COLUMNS),
        ):
            with (run_dir / filename).open("w", newline="") as handle:
                # QUOTE_MINIMAL: QUOTE_NONNUMERIC would quote every value (they
                # are all str here) and the measurements would land in Delta
                # as text.
                writer = csv.DictWriter(
                    handle,
                    fieldnames=columns,
                    quoting=csv.QUOTE_MINIMAL,
                    extrasaction="ignore",
                    lineterminator="\n",
                )
                writer.writeheader()
                writer.writerows(rows)
    total = sum(1 for b in birds if int(b["year"]) in seasons)
    unsexed = sum(1 for b in birds if int(b["year"]) in seasons and not b["sex"])
    mass_2007 = statistics.mean(float(b["body_mass_g"]) for b in birds if b["year"] == "2007")
    print(
        f"  {name:30} {total:>4} birds  seasons {','.join(map(str, seasons)):15}"
        f"  2007 mean mass {mass_2007:7.1f} g  unsexed {unsexed}"
    )


def main() -> None:
    source = read_source()
    recalibrated = recalibrate(source)
    completed = complete_sex(recalibrated)

    states = {
        1: (source, SEASONS[:1]),
        2: (source, SEASONS[:2]),
        3: (recalibrated, SEASONS[:2]),
        4: (recalibrated, SEASONS),
        5: (completed, SEASONS),
    }
    print("Writing penguins_versioned batches:")
    for story_step in STEPS:
        birds, seasons = states[story_step.n]
        write_batch(story_step.batch, birds, seasons)
    print("\nStage one with: python stage_batch.py N   (see README.md)")


if __name__ == "__main__":
    main()
