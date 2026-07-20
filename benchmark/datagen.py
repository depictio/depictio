"""Synthetic dataset generation — Polars, chunked and sharded, scales to 10 GB.

Design goals:

- **No OOM at scale.** Data is written in bounded row-batches (each shard capped
  at ~64 MB) so the process never materializes a full 10 GB frame. This is why
  we do *not* reuse the old ``benchmark_dataset_generator.py`` pandas approach,
  which built the whole ``np.random`` array in memory.
- **Matches the recursive ``run_*`` scan.** Each cell's data collections are
  written as ``run_00000/dc_0.csv``, ``run_00000/dc_1.csv``, … so the generated
  ``project.yaml`` can use ``data_location.structure: sequencing-runs`` +
  ``runs_regex: run_*`` and a per-DC recursive scan (see ``configgen.py``).
- **Real joins/links.** Every DC in a run shares the same ``individual_id`` set,
  so an inner join on ``individual_id`` is 1:1 and cross-filter links resolve.

The canonical schema (a superset that satisfies every visualization the harness
renders) is defined in :data:`COLUMNS`. Column descriptions for the YAML config
live in :data:`COLUMN_DESCRIPTIONS`.
"""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass
from pathlib import Path

# Real MultiQC parquet fixtures shipped in the repo, scaled by *count* (parse +
# per-file HTTP cost dominates, not the byte size of one parquet). Synthesising a
# parquet that satisfies ``multiqc.parse_logs`` from scratch is fragile, so we
# copy a known-good report instead. Resolved relative to the repo root.
_MULTIQC_FIXTURES: dict[str, str] = {
    "small": "depictio/projects/nf-core/ampliseq/2.16.0/multiqc/multiqc_data/multiqc.parquet",  # ~2.6M
    "large": "depictio/projects/nf-core/viralrecon/3.0.0/run_1/multiqc/multiqc_data/multiqc.parquet",  # ~24M
}

# Ordered canonical columns shared by every data collection. Kept as a superset
# so figure (scatter/bar/box), table, and advanced_viz (volcano/ma/dot_plot) all
# have valid columns to bind to.
COLUMNS: tuple[str, ...] = (
    "individual_id",  # join key (string)
    "species",  # categorical
    "island",  # categorical
    "sex",  # categorical
    "year",  # int
    "bill_length_mm",  # float
    "bill_depth_mm",  # float
    "flipper_length_mm",  # int
    "body_mass_g",  # int
    "effect_size",  # float  (volcano/ma x)
    "neg_log10_p",  # float  (volcano y)
    "mean_expression",  # float  (ma x)
)

COLUMN_DESCRIPTIONS: dict[str, str] = {
    "individual_id": "Unique individual ID (shared join key across data collections)",
    "species": "Species category (Adelie, Gentoo, Chinstrap)",
    "island": "Island location (Torgersen, Biscoe, Dream)",
    "sex": "Sex (male, female)",
    "year": "Observation year",
    "bill_length_mm": "Bill length in millimeters",
    "bill_depth_mm": "Bill depth in millimeters",
    "flipper_length_mm": "Flipper length in millimeters",
    "body_mass_g": "Body mass in grams",
    "effect_size": "Synthetic log2 fold-change style effect size",
    "neg_log10_p": "Synthetic -log10(p-value) for volcano plots",
    "mean_expression": "Synthetic mean expression for MA plots",
}

_SPECIES = ("Adelie", "Gentoo", "Chinstrap")
_ISLANDS = ("Torgersen", "Biscoe", "Dream")
_SEX = ("male", "female")

# Target on-disk size per shard file. Bounds peak memory per batch and keeps
# each ``run_*`` file small enough for Polars to stream.
SHARD_TARGET_BYTES = 64 * 1024**2


@dataclass
class DatasetManifest:
    """What was generated for one cell (returned by :func:`generate_dataset`)."""

    dataset_dir: str
    n_dcs: int
    n_runs: int
    rows_total: int
    bytes_per_row: float
    approx_bytes_per_dc: int


def _make_batch(individual_ids: list[str], seed: int):
    """Build one Polars DataFrame for the given IDs with reproducible randoms."""
    import numpy as np
    import polars as pl

    rng = np.random.default_rng(seed)
    n = len(individual_ids)
    return pl.DataFrame(
        {
            "individual_id": individual_ids,
            "species": rng.choice(_SPECIES, n),
            "island": rng.choice(_ISLANDS, n),
            "sex": rng.choice(_SEX, n),
            "year": rng.integers(2007, 2024, n),
            "bill_length_mm": rng.uniform(32.0, 60.0, n).round(1),
            "bill_depth_mm": rng.uniform(13.0, 22.0, n).round(1),
            "flipper_length_mm": rng.integers(172, 231, n),
            "body_mass_g": rng.integers(2700, 6300, n),
            "effect_size": rng.normal(0.0, 2.5, n).round(3),
            "neg_log10_p": rng.exponential(1.5, n).round(3),
            "mean_expression": rng.uniform(0.0, 14.0, n).round(3),
        }
    )


def _calibrate_bytes_per_row() -> float:
    """Write a 2000-row sample to memory and measure real CSV bytes/row."""
    import io

    ids = [f"CAL_{i:07d}" for i in range(2000)]
    df = _make_batch(ids, seed=0)
    buf = io.BytesIO()
    df.write_csv(buf)
    body_bytes = buf.tell() - (len(",".join(COLUMNS)) + 1)  # subtract header line
    return max(1.0, body_bytes / df.height)


def rows_for_bytes(size_bytes: int, bytes_per_row: float) -> int:
    return max(1, math.ceil(size_bytes / bytes_per_row))


def generate_dataset(
    size_bytes: int,
    n_dcs: int,
    dataset_dir: str | Path,
    *,
    shard_target_bytes: int = SHARD_TARGET_BYTES,
    force: bool = False,
) -> DatasetManifest:
    """Generate ``n_dcs`` data collections of ~``size_bytes`` each under runs.

    Each ``run_XXXXX/`` directory contains one ``dc_<i>.csv`` per data
    collection, all sharing the same ``individual_id`` set for that run so
    joins/links across DCs are 1:1.

    Idempotent: if a ``.manifest`` marker already records the same parameters and
    ``force`` is false, generation is skipped (datasets are large — don't rebuild
    needlessly).
    """
    import polars as pl  # noqa: F401  (ensures a clear error if polars is absent)

    dataset_dir = Path(dataset_dir)
    marker = dataset_dir / ".manifest"
    if marker.exists() and not force:
        # Cheap resume: trust an existing marker with matching params.
        existing = dict(
            line.split("=", 1) for line in marker.read_text().splitlines() if "=" in line
        )
        if existing.get("size_bytes") == str(size_bytes) and existing.get("n_dcs") == str(n_dcs):
            return DatasetManifest(
                dataset_dir=str(dataset_dir),
                n_dcs=n_dcs,
                n_runs=int(existing.get("n_runs", 0)),
                rows_total=int(existing.get("rows_total", 0)),
                bytes_per_row=float(existing.get("bytes_per_row", 0.0)),
                approx_bytes_per_dc=size_bytes,
            )

    dataset_dir.mkdir(parents=True, exist_ok=True)

    bytes_per_row = _calibrate_bytes_per_row()
    rows_total = rows_for_bytes(size_bytes, bytes_per_row)
    rows_per_run = min(rows_total, rows_for_bytes(shard_target_bytes, bytes_per_row))
    n_runs = math.ceil(rows_total / rows_per_run)

    written = 0
    for run in range(n_runs):
        rows_this_run = min(rows_per_run, rows_total - written)
        if rows_this_run <= 0:
            break
        run_dir = dataset_dir / f"run_{run:05d}"
        run_dir.mkdir(exist_ok=True)
        ids = [f"IND_{run:05d}_{i:07d}" for i in range(rows_this_run)]
        for dc_i in range(n_dcs):
            # Distinct seed per (run, dc) -> different measurements, same ids.
            df = _make_batch(ids, seed=run * 1_000 + dc_i)
            df.write_csv(run_dir / f"dc_{dc_i}.csv")
        written += rows_this_run

    marker.write_text(
        "\n".join(
            [
                f"size_bytes={size_bytes}",
                f"n_dcs={n_dcs}",
                f"n_runs={n_runs}",
                f"rows_total={rows_total}",
                f"bytes_per_row={bytes_per_row:.4f}",
            ]
        )
    )

    return DatasetManifest(
        dataset_dir=str(dataset_dir),
        n_dcs=n_dcs,
        n_runs=n_runs,
        rows_total=rows_total,
        bytes_per_row=bytes_per_row,
        approx_bytes_per_dc=size_bytes,
    )


# ── MultiQC + image ingestion datasets ──────────────────────────────────────
def _repo_root() -> Path:
    """Repo root — this file lives at ``<root>/benchmark/datagen.py``."""
    return Path(__file__).resolve().parent.parent


@dataclass
class MultiQCManifest:
    dataset_dir: str
    n_files: int
    source_bytes: int  # bytes of one fixture parquet
    total_bytes: int  # n_files * source_bytes


@dataclass
class ImageManifest:
    dataset_dir: str
    images_dir: str
    metadata_csv: str
    n_images: int
    total_bytes: int


def generate_multiqc_dataset(
    n_files: int,
    dataset_dir: str | Path,
    *,
    fixture: str = "small",
    force: bool = False,
) -> MultiQCManifest:
    """Stage ``n_files`` copies of a real ``multiqc.parquet`` under ``run_*`` dirs.

    Layout matches a ``sequencing-runs`` scan (``runs_regex: run_*`` + a recursive
    ``multiqc_data/multiqc.parquet`` pattern), so each run contributes one MultiQC
    file — the axis that actually drives parse + per-file HTTP cost. Idempotent via
    a ``.manifest`` marker.
    """
    dataset_dir = Path(dataset_dir)
    src = _repo_root() / _MULTIQC_FIXTURES[fixture]
    if not src.exists():
        raise FileNotFoundError(f"MultiQC fixture not found: {src}")
    source_bytes = src.stat().st_size

    marker = dataset_dir / ".manifest"
    if marker.exists() and not force:
        existing = dict(
            line.split("=", 1) for line in marker.read_text().splitlines() if "=" in line
        )
        if existing.get("n_files") == str(n_files) and existing.get("fixture") == fixture:
            return MultiQCManifest(
                dataset_dir=str(dataset_dir),
                n_files=n_files,
                source_bytes=source_bytes,
                total_bytes=source_bytes * n_files,
            )

    dataset_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n_files):
        run_dir = dataset_dir / f"run_{i:05d}" / "multiqc_data"
        run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, run_dir / "multiqc.parquet")

    marker.write_text(f"n_files={n_files}\nfixture={fixture}\nsource_bytes={source_bytes}\n")
    return MultiQCManifest(
        dataset_dir=str(dataset_dir),
        n_files=n_files,
        source_bytes=source_bytes,
        total_bytes=source_bytes * n_files,
    )


def generate_image_dataset(
    n_images: int,
    dataset_dir: str | Path,
    *,
    image_px: int = 16,
    force: bool = False,
) -> ImageManifest:
    """Generate ``n_images`` tiny PNGs + a metadata CSV with an ``image_path`` column.

    Images are small (default 16×16) — the ingestion cost being measured is the
    per-object S3 traffic (N HEAD + N PUT), not pixel volume. Idempotent via a
    ``.manifest`` marker. Requires Pillow + numpy.
    """
    import numpy as np
    import polars as pl
    from PIL import Image

    dataset_dir = Path(dataset_dir)
    images_dir = dataset_dir / "images"
    metadata_csv = dataset_dir / "images_data.csv"

    marker = dataset_dir / ".manifest"
    if marker.exists() and not force:
        existing = dict(
            line.split("=", 1) for line in marker.read_text().splitlines() if "=" in line
        )
        if existing.get("n_images") == str(n_images):
            total = (
                sum(p.stat().st_size for p in images_dir.rglob("*.png"))
                if images_dir.exists()
                else 0
            )
            return ImageManifest(
                dataset_dir=str(dataset_dir),
                images_dir=str(images_dir),
                metadata_csv=str(metadata_csv),
                n_images=n_images,
                total_bytes=total,
            )

    images_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    categories = ("A", "B", "C")
    rows = {"sample_id": [], "image_path": [], "category": [], "quality_score": []}
    total_bytes = 0
    for i in range(n_images):
        name = f"img_{i:07d}.png"
        arr = rng.integers(0, 256, size=(image_px, image_px, 3), dtype="uint8")
        out = images_dir / name
        Image.fromarray(arr, "RGB").save(out, "PNG")
        total_bytes += out.stat().st_size
        rows["sample_id"].append(f"S{i:07d}")
        rows["image_path"].append(name)  # relative to images_dir (image_column)
        rows["category"].append(categories[i % len(categories)])
        rows["quality_score"].append(round(float(rng.uniform(0.5, 1.0)), 3))

    pl.DataFrame(rows).write_csv(metadata_csv)
    marker.write_text(f"n_images={n_images}\nimage_px={image_px}\n")
    return ImageManifest(
        dataset_dir=str(dataset_dir),
        images_dir=str(images_dir),
        metadata_csv=str(metadata_csv),
        n_images=n_images,
        total_bytes=total_bytes,
    )
