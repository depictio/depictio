#!/usr/bin/env python3
"""Stage one batch of the penguins_versioned demo into the data root.

`depictio ingest` scans everything under the project's `locations`; there is no
flag to ingest one batch. So the batches live in `batches/` and this copies one
of them into the data root (`data/` by default), replacing whatever was there.

Exactly one batch is staged at a time, never accumulated: each batch directory
is already the complete state of the survey at that point, one `season_YYYY/`
run per field season. Staging two side by side would make the scanner read the
same birds twice.

Written in Python rather than shell so the rebuild script can call it as a
function, and so it runs the same in a container and on a laptop.

Usage:
    python stage_batch.py 3                      # data/ now holds batch 3
    python stage_batch.py reset                  # data/ empty again
    python stage_batch.py 3 --data-root /some/dir
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from penguins_story import BATCHES_DIR, DEFAULT_DATA_ROOT, STEPS


def reset(data_root: Path) -> None:
    """Empty the data root, keeping the directory and its .gitkeep marker.

    The directory has to exist: the project's `locations` are validated as an
    existing directory before anything is scanned.
    """
    if data_root.exists():
        for child in data_root.iterdir():
            if child.name == ".gitkeep":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    data_root.mkdir(parents=True, exist_ok=True)
    if data_root.resolve() == DEFAULT_DATA_ROOT.resolve():
        (data_root / ".gitkeep").touch()


def _data_rows(csv_path: Path) -> int:
    with csv_path.open() as handle:
        return sum(1 for _ in handle) - 1


def stage(n: int, data_root: Path = DEFAULT_DATA_ROOT) -> str:
    """Copy batch ``n`` (1-based) into ``data_root``. Returns a one-line summary."""
    if not 1 <= n <= len(STEPS):
        raise ValueError(f"batch must be 1..{len(STEPS)}, got {n}")
    batch = STEPS[n - 1].batch
    source = BATCHES_DIR / batch
    if not source.is_dir():
        raise FileNotFoundError(f"{source} is missing: run generate_batches.py first")
    reset(data_root)
    runs = sorted(p for p in source.iterdir() if p.is_dir())
    for run in runs:
        shutil.copytree(run, data_root / run.name)
    birds = sum(_data_rows(run / "physical_features.csv") for run in runs)
    return f"staged {batch}: {', '.join(r.name for r in runs)} ({birds} birds)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("batch", help=f"1..{len(STEPS)}, or 'reset'")
    ap.add_argument(
        "--data-root",
        type=Path,
        default=DEFAULT_DATA_ROOT,
        help="directory the project's locations point at (default: data/ next to this file)",
    )
    args = ap.parse_args()

    if args.batch == "reset":
        reset(args.data_root)
        print(f"reset: {args.data_root} is empty")
        return 0
    try:
        print(stage(int(args.batch), args.data_root))
    except (ValueError, FileNotFoundError) as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
