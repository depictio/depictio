"""Three linked data collections with a *realistic* join-key cardinality.

:mod:`benchmark.datagen` generates symmetric collections whose join key is unique
per row. For ``joins`` that is fine; for ``links`` it is a worst case that does
not occur in practice — translating a filter on a 3-value column then yields a
third of the table (millions of values, materialised as a Python list and sent
over HTTP). The numbers it produces describe a pathological topology, not the
cost of cross-filtering.

This module generates what a real project looks like instead:

===========  ======================  ==========================================
collection   grain                   role
===========  ======================  ==========================================
``metadata`` one row per sample       sample attributes (the filter origin)
``metrics``  one row per sample+tool  QC metrics (the middle of the chain)
``features`` one row per sample+feat  the heavy one (the render target)
===========  ======================  ==========================================

The essential property: ``sample_id`` has ``n_samples`` distinct values —
hundreds — regardless of the size tier. Rows scale with the tier through the
per-sample fan-out (``features_per_sample``), the join key does not. That is the
whole point of the exercise, so it is asserted by the tests rather than assumed.

Layout matches the recursive ``run_*`` scan the generated ``project.yaml`` uses
(see :mod:`benchmark.configgen`): each ``run_XXXXX/`` holds a *slice of samples*
with all three CSVs, so a run is a bounded shard and no full frame is ever
materialised.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from pathlib import Path

from benchmark.datagen import SHARD_TARGET_BYTES, rows_for_bytes

# Tag -> ordered columns. These are the tags the scan patterns and the dashboard
# bind to, so they are part of the contract with configgen.
METADATA_TAG = "metadata"
METRICS_TAG = "metrics"
FEATURES_TAG = "features"
LINKED_TAGS: tuple[str, ...] = (METADATA_TAG, METRICS_TAG, FEATURES_TAG)

# The join key, shared by all three collections.
JOIN_COLUMN = "sample_id"

LINKED_COLUMN_DESCRIPTIONS: dict[str, dict[str, str]] = {
    METADATA_TAG: {
        "sample_id": "Sample identifier (join key shared across collections)",
        "condition": "Experimental condition",
        "batch": "Processing batch",
        "timepoint": "Collection timepoint",
        "tissue": "Tissue of origin",
        "sex": "Donor sex",
        "age": "Donor age in years",
    },
    METRICS_TAG: {
        "sample_id": "Sample identifier (join key shared across collections)",
        "tool": "QC tool that produced the metric",
        "metric": "Metric name",
        "value": "Metric value",
        "duplication_pct": "Duplicate read percentage",
        "gc_pct": "GC content percentage",
        "mapped_pct": "Mapped read percentage",
    },
    FEATURES_TAG: {
        "sample_id": "Sample identifier (join key shared across collections)",
        "feature_id": "Feature identifier (gene/transcript)",
        "expression": "Normalised expression value",
        "effect_size": "log2 fold-change style effect size (volcano/MA x)",
        "neg_log10_p": "-log10(p-value) for volcano plots",
        "mean_expression": "Mean expression for MA plots",
        "feature_class": "Feature class — a categorical local to this collection",
        "chr": "Synthetic chromosome label (manhattan/lollipop)",
        "position": "Synthetic 1-based genomic position (manhattan/lollipop)",
        "frac_expressing": "Fraction expressing in [0,1] (dot_plot)",
        "rank": "Synthetic taxonomic rank label (stacked_taxonomy)",
    },
}

_CONDITIONS = ("control", "treated", "recovery")
_BATCHES = ("batch_A", "batch_B", "batch_C", "batch_D")
_TIMEPOINTS = ("T0", "T6", "T24")
_TISSUES = ("liver", "kidney", "lung")
_SEX = ("male", "female")
_METRICS = ("reads", "coverage", "insert_size", "error_rate")
_FEATURE_CLASSES = ("protein_coding", "lncRNA", "pseudogene")
# Synthetic genomic + taxonomy columns on the features grain. They exist so the
# diverse benchmark dashboard can bind the viz kinds whose canonical schema
# needs them (manhattan/lollipop want chr+position, dot_plot wants a fraction in
# [0, 1], stacked_taxonomy wants a rank label). They are not biologically
# meaningful — the point is a valid binding of the right dtype at scale, not a
# real genome.
_CHROMOSOMES = tuple(f"chr{i}" for i in range(1, 23)) + ("chrX", "chrY")
_TAXO_RANKS = ("phylum", "class", "order", "family", "genus")

# ── Per-sample structure ────────────────────────────────────────────────────
# The categorical columns of ``metrics`` and ``features`` are NOT drawn
# independently per row. If they were, every sample would carry every value, and
# translating a filter on one of them back to the sample sheet would return all
# ``n_samples`` — a link that resolves successfully and narrows nothing. Half the
# dashboard would then sit at its unfiltered value whenever the user touched a
# QC or feature attribute, which is exactly the behaviour the reverse links in
# ``configgen.LINKED_ROUTES`` exist to remove.
#
# So each sample is assigned a *panel* of tools and a *palette* of feature
# classes / taxonomic ranks, deterministically from its index. Filtering on a
# value not shared by every panel selects a strict subset of samples, and the
# reverse translation has something real to say. This is also how projects
# actually look: not every sample goes through every tool.
_TOOL_PANELS: tuple[tuple[str, ...], ...] = (
    ("fastqc", "samtools", "picard", "qualimap"),
    ("fastqc", "samtools", "bcftools", "mosdepth"),
)
# Tools common to every panel — a filter on one of these selects every sample,
# which is a legitimate outcome and worth keeping representable.
_TOOLS: tuple[str, ...] = tuple(dict.fromkeys(t for panel in _TOOL_PANELS for t in panel))

_FEATURE_CLASS_PALETTES: tuple[tuple[str, ...], ...] = (
    ("protein_coding", "lncRNA"),
    ("protein_coding", "pseudogene"),
    ("lncRNA", "pseudogene"),
)
# Three consecutive ranks per sample, so each rank is present in a subset.
_RANK_PALETTES: tuple[tuple[str, ...], ...] = tuple(
    _TAXO_RANKS[i : i + 3] for i in range(len(_TAXO_RANKS) - 2)
)

# One row per (sample, tool, metric): 4 tools per panel x 4 metrics.
METRICS_PER_SAMPLE = len(_TOOL_PANELS[0]) * len(_METRICS)

DEFAULT_N_SAMPLES = 500

# Bumped whenever the generated *content* changes for the same (size, samples).
# The idempotency marker compares it, so a generator change regenerates instead
# of silently reusing CSVs written by an older definition of the schema.
SCHEMA_VERSION = 2


@dataclass
class LinkedManifest:
    """What :func:`generate_linked_dataset` produced for one cell."""

    dataset_dir: str
    n_samples: int
    features_per_sample: int
    n_runs: int
    rows_by_dc: dict[str, int] = field(default_factory=dict)
    bytes_per_feature_row: float = 0.0

    @property
    def rows_total(self) -> int:
        return sum(self.rows_by_dc.values())


def _sample_ids(start: int, count: int) -> list[str]:
    return [f"SAMPLE_{i:05d}" for i in range(start, start + count)]


def _sample_index(sample_id: str) -> int:
    """The global index encoded in a sample id.

    Per-sample structure is keyed on this rather than on the position within a
    shard, so a sample's tool panel and feature palette are the same whichever
    run it lands in — the sharding is a file-layout detail and must not change
    the data.
    """
    return int(sample_id.rsplit("_", 1)[1])


def _metadata_batch(sample_ids: list[str], seed: int):
    import numpy as np
    import polars as pl

    rng = np.random.default_rng(seed)
    n = len(sample_ids)
    return pl.DataFrame(
        {
            "sample_id": sample_ids,
            "condition": rng.choice(_CONDITIONS, n),
            "batch": rng.choice(_BATCHES, n),
            "timepoint": rng.choice(_TIMEPOINTS, n),
            "tissue": rng.choice(_TISSUES, n),
            "sex": rng.choice(_SEX, n),
            "age": rng.integers(18, 85, n),
        }
    )


def _metrics_batch(sample_ids: list[str], seed: int):
    """One row per (sample, tool, metric) — the QC grain.

    The tools are the sample's *panel*, not the whole pool, so a filter on a
    panel-specific tool resolves back to the samples that ran it.
    """
    import numpy as np
    import polars as pl

    rng = np.random.default_rng(seed)
    panels = [_TOOL_PANELS[_sample_index(s) % len(_TOOL_PANELS)] for s in sample_ids]
    repeated = [s for s in sample_ids for _ in range(METRICS_PER_SAMPLE)]
    tools = [t for panel in panels for t in panel for _ in _METRICS]
    metrics = [m for panel in panels for _ in panel for m in _METRICS]
    n = len(repeated)
    return pl.DataFrame(
        {
            "sample_id": repeated,
            "tool": tools,
            "metric": metrics,
            "value": rng.uniform(0.0, 1000.0, n).round(3),
            "duplication_pct": rng.uniform(1.0, 40.0, n).round(2),
            "gc_pct": rng.uniform(35.0, 65.0, n).round(2),
            "mapped_pct": rng.uniform(60.0, 99.9, n).round(2),
        }
    )


def _features_batch(sample_ids: list[str], features_per_sample: int, seed: int):
    """One row per (sample, feature) — the heavy grain.

    ``feature_class`` and ``rank`` are drawn from the sample's palette rather
    than from the full set, so filtering either one selects a strict subset of
    samples and the reverse links have something to translate.
    """
    import numpy as np
    import polars as pl

    rng = np.random.default_rng(seed)
    repeated = [s for s in sample_ids for _ in range(features_per_sample)]
    feature_ids = [f"FEAT_{i:06d}" for _ in sample_ids for i in range(features_per_sample)]
    n = len(repeated)
    classes: list[str] = []
    ranks: list[str] = []
    for s in sample_ids:
        idx = _sample_index(s)
        palette = _FEATURE_CLASS_PALETTES[idx % len(_FEATURE_CLASS_PALETTES)]
        rank_palette = _RANK_PALETTES[idx % len(_RANK_PALETTES)]
        classes.extend(rng.choice(palette, features_per_sample))
        ranks.extend(rng.choice(rank_palette, features_per_sample))
    return pl.DataFrame(
        {
            "sample_id": repeated,
            "feature_id": feature_ids,
            "expression": rng.uniform(0.0, 500.0, n).round(3),
            "effect_size": rng.normal(0.0, 2.5, n).round(3),
            "neg_log10_p": rng.exponential(1.5, n).round(3),
            "mean_expression": rng.uniform(0.0, 14.0, n).round(3),
            "feature_class": classes,
            # Synthetic genomic + taxonomy roles (see the constants above).
            # ``chr`` stays uniform: every sample is sequenced against the same
            # reference, so a chromosome filter narrows the feature rows but not
            # the sample set — a link that legitimately resolves to everything.
            "chr": rng.choice(_CHROMOSOMES, n),
            "position": rng.integers(1, 250_000_000, n),
            "frac_expressing": rng.uniform(0.0, 1.0, n).round(3),
            "rank": ranks,
        }
    )


def _calibrate_feature_bytes_per_row() -> float:
    """Measure real CSV bytes/row for the ``features`` schema.

    Same approach as :func:`benchmark.datagen._calibrate_bytes_per_row`, but the
    schemas differ, so the calibration cannot be shared: sizing the tier off the
    penguin schema would miss the target by the ratio between them.
    """
    df = _features_batch(_sample_ids(0, 4), features_per_sample=250, seed=0)
    buf = io.BytesIO()
    df.write_csv(buf)
    header = len(",".join(df.columns)) + 1
    return max(1.0, (buf.tell() - header) / df.height)


def generate_linked_dataset(
    size_bytes: int,
    dataset_dir: str | Path,
    *,
    n_samples: int = DEFAULT_N_SAMPLES,
    shard_target_bytes: int = SHARD_TARGET_BYTES,
    force: bool = False,
) -> LinkedManifest:
    """Generate ``metadata`` / ``metrics`` / ``features`` under ``run_*`` shards.

    ``size_bytes`` targets the ``features`` collection (the other two are orders
    of magnitude smaller and are sized by the grain, not the tier).
    ``features_per_sample`` is derived so that ``n_samples`` — the join-key
    cardinality — stays where it is while the row count follows the tier.

    Idempotent via a ``.manifest`` marker, like the symmetric generator — but
    the marker also records :data:`SCHEMA_VERSION`, so changing what the
    generator *writes* (not just how much of it) invalidates data on disk. Size
    and sample count alone would not: a checkout that already had the old CSVs
    would keep serving them under the new code, and the mismatch is invisible.
    """
    import polars as pl  # noqa: F401  (clear error if polars is absent)

    dataset_dir = Path(dataset_dir)
    marker = dataset_dir / ".manifest"
    bytes_per_row = _calibrate_feature_bytes_per_row()
    features_per_sample = max(1, rows_for_bytes(size_bytes, bytes_per_row) // max(1, n_samples))

    if marker.exists() and not force:
        existing = dict(
            line.split("=", 1) for line in marker.read_text().splitlines() if "=" in line
        )
        if (
            existing.get("size_bytes") == str(size_bytes)
            and existing.get("n_samples") == str(n_samples)
            and existing.get("schema_version") == str(SCHEMA_VERSION)
        ):
            return _manifest_from_marker(dataset_dir, existing)

    dataset_dir.mkdir(parents=True, exist_ok=True)

    # Shard on samples so every run holds a coherent slice of all three
    # collections — the join key of a run's features is exactly the sample set of
    # its metadata.
    samples_per_run = max(
        1, rows_for_bytes(shard_target_bytes, bytes_per_row) // max(1, features_per_sample)
    )
    samples_per_run = min(samples_per_run, n_samples)
    n_runs = math.ceil(n_samples / samples_per_run)

    written = 0
    for run in range(n_runs):
        count = min(samples_per_run, n_samples - written)
        if count <= 0:
            break
        ids = _sample_ids(written, count)
        run_dir = dataset_dir / f"run_{run:05d}"
        run_dir.mkdir(exist_ok=True)
        _metadata_batch(ids, seed=run).write_csv(run_dir / f"{METADATA_TAG}.csv")
        _metrics_batch(ids, seed=run + 10_000).write_csv(run_dir / f"{METRICS_TAG}.csv")
        _features_batch(ids, features_per_sample, seed=run + 20_000).write_csv(
            run_dir / f"{FEATURES_TAG}.csv"
        )
        written += count

    rows_by_dc = {
        METADATA_TAG: n_samples,
        METRICS_TAG: n_samples * METRICS_PER_SAMPLE,
        FEATURES_TAG: n_samples * features_per_sample,
    }
    marker.write_text(
        "\n".join(
            [
                f"size_bytes={size_bytes}",
                f"n_samples={n_samples}",
                f"schema_version={SCHEMA_VERSION}",
                f"features_per_sample={features_per_sample}",
                f"n_runs={n_runs}",
                f"bytes_per_feature_row={bytes_per_row:.4f}",
            ]
        )
    )
    return LinkedManifest(
        dataset_dir=str(dataset_dir),
        n_samples=n_samples,
        features_per_sample=features_per_sample,
        n_runs=n_runs,
        rows_by_dc=rows_by_dc,
        bytes_per_feature_row=bytes_per_row,
    )


def _manifest_from_marker(dataset_dir: Path, existing: dict[str, str]) -> LinkedManifest:
    n_samples = int(existing.get("n_samples", 0))
    features_per_sample = int(existing.get("features_per_sample", 0))
    return LinkedManifest(
        dataset_dir=str(dataset_dir),
        n_samples=n_samples,
        features_per_sample=features_per_sample,
        n_runs=int(existing.get("n_runs", 0)),
        rows_by_dc={
            METADATA_TAG: n_samples,
            METRICS_TAG: n_samples * METRICS_PER_SAMPLE,
            FEATURES_TAG: n_samples * features_per_sample,
        },
        bytes_per_feature_row=float(existing.get("bytes_per_feature_row", 0.0)),
    )
