"""Per-sample deepTools fingerprint metrics, one row per library.

``plotFingerprint --outQualityMetrics`` writes one
``<sample>.plotFingerprint.qcmetrics.txt`` comparing the observed cumulative
coverage curve against the curve a perfectly uniform library of the same depth
would give. An ``AUC`` close to the synthetic value means the coverage is flat —
an input, or a failed enrichment; an ``AUC`` well below it means the reads pile
into a small share of the genome, which is what an enriched ChIP, a sharp ATAC
or a CUT&RUN target looks like. Plotting the two against each other separates
the targets from the controls in one glance, which is why ``auc_ratio`` is
precomputed here rather than left to a code-mode figure.

Two flavours of the file exist and both are read:

* ``plotFingerprint`` run on a single BAM writes one row and eight columns
  (chipseq's ATAC twin, cutandrun);
* ``plotFingerprint --JSDsample <input>`` writes one row per BAM it was given —
  the IP and the input it was compared against — and five more columns holding
  the comparison (``JS Distance``, ``% genome enriched``, ``diff. enrichment``,
  ``CHANCE divergence``). Those five are optional here: a run without a control
  never produces them.

A sample can therefore be reported twice, once as the IP of its own file and
once as the control inside another's. The rows agree on everything computed
from the BAM alone, so the duplicate is dropped keeping whichever row carries
the comparison columns.

Output schema:
    sample : Utf8                    library plotFingerprint ran on
    auc : Float64                    area under the observed coverage curve
    synthetic_auc : Float64          same, for a uniform library of that depth
    auc_ratio : Float64              auc / synthetic_auc; 1.0 = no enrichment
    x_intercept : Float64            share of bins with no reads at all
    synthetic_x_intercept : Float64  same, for the uniform library
    elbow_point : Float64            where the observed curve turns
    synthetic_elbow_point : Float64  same, for the uniform library
    synthetic_js_distance : Float64  Jensen-Shannon distance to the uniform library

Optional (written only with --JSDsample):
    js_distance : Float64            Jensen-Shannon distance to the control
    percent_genome_enriched : Float64  share of the genome called enriched
    diff_enrichment : Float64        differential enrichment over the control
    chance_divergence : Float64      CHANCE divergence from the control
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sample_ids import strip_stage_suffixes

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="metrics",
        glob_pattern="**/*.plotFingerprint.qcmetrics.txt",
        format="TSV",
        read_kwargs={"infer_schema_length": 0, "null_values": ["NA", "nan", ""]},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "auc": pl.Float64,
    "synthetic_auc": pl.Float64,
    "auc_ratio": pl.Float64,
    "x_intercept": pl.Float64,
    "synthetic_x_intercept": pl.Float64,
    "elbow_point": pl.Float64,
    "synthetic_elbow_point": pl.Float64,
    "synthetic_js_distance": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "js_distance": pl.Float64,
    "percent_genome_enriched": pl.Float64,
    "diff_enrichment": pl.Float64,
    "chance_divergence": pl.Float64,
}

# Canonical column name -> the deepTools header cell after `_norm`.
_HEADERS: dict[str, str] = {
    "auc": "auc",
    "synthetic_auc": "synthetic_auc",
    "x_intercept": "x_intercept",
    "synthetic_x_intercept": "synthetic_x_intercept",
    "elbow_point": "elbow_point",
    "synthetic_elbow_point": "synthetic_elbow_point",
    "synthetic_js_distance": "synthetic_js_distance",
    "js_distance": "js_distance",
    # "% genome enriched", "diff. enrichment" and "CHANCE divergence" once the
    # punctuation is folded away.
    "percent_genome_enriched": "genome_enriched",
    "diff_enrichment": "diff_enrichment",
    "chance_divergence": "chance_divergence",
}


def _norm(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", name.strip().lower()).strip("_")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Normalise the header, strip the BAM suffixes and add the AUC ratio."""
    raw = sources["metrics"]
    if raw.is_empty():
        raise ValueError("deeptools_fingerprint_metrics: no qcmetrics file carried a row")

    present = {_norm(c): c for c in raw.columns}
    if "sample" not in present or "auc" not in present:
        raise ValueError(
            f"deeptools_fingerprint_metrics: expected a Sample and an AUC column, got {raw.columns}"
        )

    selections = [
        # deepTools names the sample after the BAM it was given, so the value
        # carries the alignment-stage suffixes of whichever pipeline ran it.
        pl.col(present["sample"])
        .cast(pl.Utf8)
        .map_elements(strip_stage_suffixes, return_dtype=pl.Utf8)
        .alias("sample")
    ]
    optional_present: list[str] = []
    for canonical, header in _HEADERS.items():
        source = present.get(header)
        if source is None:
            if canonical in OPTIONAL_SCHEMA:
                continue  # a run without --JSDsample: the column does not exist
            selections.append(pl.lit(None, dtype=pl.Float64).alias(canonical))
            continue
        if canonical in OPTIONAL_SCHEMA:
            optional_present.append(canonical)
        selections.append(pl.col(source).cast(pl.Float64, strict=False).alias(canonical))

    frame = raw.select(selections).with_columns(
        # The synthetic AUC is the same number for every library of a given
        # depth, so the ratio is what makes two runs comparable; guard the
        # division because a zero-coverage library reports 0.0 for both.
        pl.when(pl.col("synthetic_auc") > 0)
        .then(pl.col("auc") / pl.col("synthetic_auc"))
        .otherwise(None)
        .alias("auc_ratio")
    )

    # A sample reported both as an IP and as somebody's control: keep the row
    # that carries the comparison columns, which is the one from its own file.
    if "js_distance" in optional_present:
        frame = frame.sort("js_distance", descending=True, nulls_last=True)
    frame = frame.unique(subset=["sample"], keep="first")

    return frame.select([*EXPECTED_SCHEMA, *optional_present]).sort("sample")
