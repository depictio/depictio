"""nf-core/rnaseq MultiQC general statistics as one row per library.

MultiQC writes ``multiqc_general_stats.txt`` next to its parquet: one column per
headline metric each module contributed, named ``<module>-<metric>``. The table
is what a reader scans first to find the odd library out, and it is the input
of the parallel-coordinates profile, which needs numeric columns with plain
names and exactly one row per library.

Two things stand between the file and that shape:

* FastQC and Cutadapt report per read file, so a paired-end run carries a
  ``<sample> Read 1`` and ``<sample> Read 2`` row beside the sample row. MultiQC
  1.33 already copies their mean onto the sample row; older reports do not. The
  sample row wins, and the per-read mean fills whatever it left empty.
* The module-prefixed names are replaced by the eleven metrics below, each
  from the module nf-core/rnaseq runs for it. A metric the run did not produce
  (``--skip_qualimap``, ``--skip_dupradar``, the pseudo-aligner route without
  STAR) stays a null column rather than failing the recipe.

* ``pct_trimmed`` is Cutadapt's share of bases trimmed, ``100 * (1 - bp
  written / bp processed)``. MultiQC's own ``trim_galore`` module (the reports
  of rnaseq 3.28) replaced the Cutadapt columns with ``trim_galore-tg_*`` ones,
  none of which is that share (``tg_pct_quality_trimmed`` leaves the adapter
  bases out). Its data file still holds both base counts, per read file: the
  share is computed from them, read files averaged as MultiQC does.

Sources:
    stats  every ``multiqc_general_stats.txt`` under ``multiqc/``. MultiQC
           names its data dir ``multiqc_data`` or ``<report>_data``, and the
           pipeline nests it under the aligner, so the glob spans all of them.
           A run that wrote several reports (two aligner routes under one
           DATA_ROOT) keeps the first row per library.
    trim_galore  ``multiqc_trim_galore.txt`` (optional): reports made by
           MultiQC's trim_galore module, where ``pct_trimmed`` comes from.

Output: ``sample``, ``condition`` (read off the ``<condition>_REP<n>`` sample
name nf-core RNA-seq uses, the sample name itself otherwise), then the metrics,
all Float64. Read counts are in millions, as MultiQC stores them.
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    # No input_schema: MultiQC writes a run-dependent column set, each metric is read when present and the sample name is the first column.
    RecipeSource(
        ref="stats",
        glob_pattern="multiqc/**/multiqc_general_stats.txt",
        format="tsv",
        # Every column as text: a module that wrote nothing for a library leaves
        # an empty cell, and `salmon-library_types` is a string among numbers.
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(
        ref="trim_galore",
        glob_pattern="multiqc/**/multiqc_trim_galore.txt",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        optional=True,
    ),
]

#: Output metric -> the MultiQC general-stats columns it is read from, in order
#: of preference. The first one present and non-null wins.
METRICS: dict[str, tuple[str, ...]] = {
    "total_reads_m": ("star-total_reads", "fastqc_trimmed-total_sequences"),
    "pct_trimmed": ("cutadapt-percent_trimmed",),
    "pct_gc": ("fastqc_trimmed-percent_gc", "fastqc_raw-percent_gc"),
    "pct_uniquely_mapped": ("star-uniquely_mapped_percent",),
    "pct_salmon_mapped": ("salmon-percent_mapped",),
    "pct_duplication": ("picard_mark_duplicates-PERCENT_DUPLICATION",),
    "dupradar_intercept": ("custom_content_dupradar-dupRadar_intercept",),
    "pct_exonic": (),  # derived from the three Qualimap region counts below
    "bias_5_3": ("qualimap_rnaseq-5_3_bias",),
    "error_rate": ("samtools_stats-error_rate",),
    "insert_size": ("samtools_stats-insert_size_average",),
}

_QUALIMAP_REGIONS = (
    "qualimap_rnaseq-reads_aligned_exonic",
    "qualimap_rnaseq-reads_aligned_intronic",
    "qualimap_rnaseq-reads_aligned_intergenic",
)

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "condition": pl.Utf8,
    **{name: pl.Float64 for name in METRICS},
}

# `GM12878_REP1 Read 2` (MultiQC's own naming), `ctrl_R1`, `ctrl_2`: the
# per-read-file rows.
_MULTIQC_READ = re.compile(r"\s+Read\s+[12]$")
_READ_SUFFIX = re.compile(r"(?:\s+Read\s+[12]|_R?[12])$")
# `GM12878_REP1`, `treated_rep2`: condition, then the replicate index (the same
# rule as the samplesheet recipe; recipes may not import each other).
_REPLICATE = re.compile(r"^(?P<condition>.+?)[._-](?:rep|r)?\d+$", re.IGNORECASE)


def _condition(sample: str) -> str:
    match = _REPLICATE.match(sample)
    return match.group("condition") if match else sample


def _numeric(df: pl.DataFrame, column: str) -> pl.Expr:
    if column not in df.columns:
        return pl.lit(None, dtype=pl.Float64)
    return pl.col(column).cast(pl.Float64, strict=False)


def _trim_galore_pct_trimmed(tg: pl.DataFrame | None, samples: set[str]) -> pl.DataFrame | None:
    """``sample`` → share of bases trimmed, from MultiQC's trim_galore data file:
    per read file ``100 * (1 - total_bp_written / total_bp_processed)``, read
    files of one library averaged (MultiQC's own rule for its sample row)."""
    needed = {"total_bp_processed", "total_bp_written"}
    if tg is None or tg.is_empty() or not needed <= set(tg.columns):
        return None
    name_col = "Sample" if "Sample" in tg.columns else tg.columns[0]

    def library(name: str) -> str | None:
        name = name.strip()
        if name in samples:
            return name
        bare = _READ_SUFFIX.sub("", name)
        return bare if bare != name and bare in samples else None

    per_file = tg.select(
        pl.col(name_col).cast(pl.Utf8).map_elements(library, return_dtype=pl.Utf8).alias("sample"),
        (
            100.0
            * (
                1.0
                - pl.col("total_bp_written").cast(pl.Float64, strict=False)
                / pl.col("total_bp_processed").cast(pl.Float64, strict=False)
            )
        ).alias("_tg_pct_trimmed"),
    )
    return (
        per_file.drop_nulls("sample")
        .filter(pl.col("_tg_pct_trimmed").is_finite())
        .group_by("sample", maintain_order=True)
        .agg(pl.col("_tg_pct_trimmed").mean())
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per library, sample row first, per-read rows as the fallback."""
    raw = sources["stats"]
    name_col = "Sample" if "Sample" in raw.columns else raw.columns[0]
    raw = raw.with_columns(pl.col(name_col).cast(pl.Utf8).str.strip_chars().alias("_name"))

    names = raw["_name"].to_list()
    present = set(names)

    # A per-read row is `<sample> Read N`, or `<sample>_1` / `_R1` when
    # `<sample>` is itself a row: a library named `ctrl_1` with no `ctrl` row
    # is a library, not the first read of one.
    def is_read_row(name: str) -> bool:
        if _MULTIQC_READ.search(name):
            return True
        return bool(_READ_SUFFIX.search(name)) and _READ_SUFFIX.sub("", name) in present

    base_names = {n for n in names if not is_read_row(n)}
    parents = [n if n in base_names else _READ_SUFFIX.sub("", n) for n in names]
    raw = raw.with_columns(
        pl.Series("sample", parents, dtype=pl.Utf8),
        pl.col("_name").is_in(list(base_names)).alias("_is_sample_row"),
    )

    source_cols = sorted({c for cols in METRICS.values() for c in cols} | set(_QUALIMAP_REGIONS))
    numeric = raw.select(
        "sample",
        "_is_sample_row",
        *[_numeric(raw, c).alias(c) for c in source_cols],
    )
    sample_rows = (
        numeric.filter(pl.col("_is_sample_row"))
        .drop("_is_sample_row")
        .unique(subset="sample", keep="first", maintain_order=True)
    )
    read_means = (
        numeric.filter(~pl.col("_is_sample_row"))
        .drop("_is_sample_row")
        .group_by("sample", maintain_order=True)
        .agg(pl.all().mean())
    )
    merged = (
        pl.concat([sample_rows, read_means], how="diagonal_relaxed")
        .group_by("sample", maintain_order=True)
        # first non-null: the sample row comes first in the concat
        .agg([pl.col(c).drop_nulls().first() for c in source_cols])
    )

    exprs: list[pl.Expr] = []
    for name, cols in METRICS.items():
        if name == "pct_exonic":
            exonic, intronic, intergenic = (pl.col(c) for c in _QUALIMAP_REGIONS)
            exprs.append(
                (100.0 * exonic / (exonic + intronic + intergenic)).cast(pl.Float64).alias(name)
            )
            continue
        exprs.append(
            pl.coalesce([pl.col(c) for c in cols]).cast(pl.Float64).alias(name)
            if cols
            else pl.lit(None, dtype=pl.Float64).alias(name)
        )

    out = merged.select(pl.col("sample"), *exprs)
    trimmed = _trim_galore_pct_trimmed(sources.get("trim_galore"), set(out["sample"].to_list()))
    if trimmed is not None:
        out = (
            out.join(trimmed, on="sample", how="left")
            .with_columns(pl.coalesce("pct_trimmed", "_tg_pct_trimmed").alias("pct_trimmed"))
            .drop("_tg_pct_trimmed")
        )
    out = out.with_columns(
        pl.Series("condition", [_condition(s) for s in out["sample"].to_list()], dtype=pl.Utf8)
    )
    return out.select(list(OUTPUT_SCHEMA)).sort("sample")
