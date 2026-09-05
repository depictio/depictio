"""Consensus peak x replicate presence matrix from CUT&RUN consensus BEDs.

The nf-core CUT&RUN-family pipelines merge the per-replicate peak calls of one
target into ``<target>.consensus.peak_counts.bed``: a headerless BED whose first
three columns are the merged interval and whose next six carry the member peaks
as parallel comma-separated lists (their starts, ends, total signals, max
signals, max-signal sub-intervals and the peak files they came from), followed
by how many member peaks were merged.

The member file names are the only place the replicate identity survives, so
they are what the 0/1 set columns are built from — which is the shape
``upset_plot`` reads (binary integer columns are the sets). Because the same
column also names the caller, one consensus table stays readable whichever
caller the run used (``*.seacr.peaks.stringent.bed``,
``*.macs2_peaks.narrowPeak``).

Several consensus tables can be concatenated (one per target); a row's target is
the replicate suffix stripped off its member samples, following the
``<group>_R<replicate>`` sample naming these pipelines build.

Output schema:
    peak_id : Utf8         "<target>:<chr>:<start>-<end>", unique across targets
    target : Utf8          the group the replicates belong to
    caller : Utf8          peak caller the member calls came from
    chr : Utf8             chromosome of the merged interval
    start : Int64          merged interval start
    end : Int64            merged interval end
    width : Int64          end - start
    num_peaks : Int64      member peaks merged into the interval
    num_samples : Int64    distinct replicates calling a peak on the interval
    support : Utf8         num_samples as a category, for donut / composition strips
    total_signal : Float64 summed total signal of the member peaks
    max_signal : Float64   highest max signal among the member peaks
    <sample> : Int8        1 when the replicate called a peak (run-specific names)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_BED_COLUMNS = [
    "chr",
    "start",
    "end",
    "member_starts",
    "member_ends",
    "member_total_signals",
    "member_max_signals",
    "member_max_regions",
    "member_files",
    "num_peaks",
]

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="consensus",
        glob_pattern="**/*.consensus.peak_counts.bed",
        format="TSV",
        read_kwargs={
            "has_header": False,
            "new_columns": _BED_COLUMNS,
            "infer_schema_length": 0,
        },
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "peak_id": pl.Utf8,
    "target": pl.Utf8,
    "caller": pl.Utf8,
    "chr": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "width": pl.Int64,
    "num_peaks": pl.Int64,
    "num_samples": pl.Int64,
    "support": pl.Utf8,
    "total_signal": pl.Float64,
    "max_signal": pl.Float64,
}
# One Int8 0/1 column per replicate follows; the names are run-specific.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

# `<sample>.seacr.peaks.stringent.bed`, `<sample>.macs2_peaks.narrowPeak`, ...
_CALLERS = ("seacr", "macs2", "macs3", "epic2")
_CALLER_RE = r"\.(" + "|".join(_CALLERS) + r")[._]"
_SAMPLE_RE = _CALLER_RE + r".*$"
# `<group>_R<replicate>` is how these pipelines build a sample name.
_REPLICATE_SUFFIX = r"_(?:R|rep|REP|Rep)?\d+$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Type the interval, split the member lists and pivot replicates to 0/1."""
    df = sources["consensus"]
    missing = [c for c in _BED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"seacr_consensus_peaks: input lacks columns {missing}")

    members = pl.col("member_files").cast(pl.Utf8).str.split(",")
    df = df.with_columns(
        pl.col("chr").cast(pl.Utf8),
        pl.col("start").cast(pl.Int64, strict=False),
        pl.col("end").cast(pl.Int64, strict=False),
        pl.col("num_peaks").cast(pl.Int64, strict=False),
        members.list.eval(pl.element().str.replace_all(r"^.*/", "").str.replace(_SAMPLE_RE, ""))
        .list.unique()
        .list.sort()
        .alias("_samples"),
        pl.col("member_files").cast(pl.Utf8).str.extract(_CALLER_RE, 1).alias("caller"),
        pl.col("member_total_signals")
        .cast(pl.Utf8)
        .str.split(",")
        .list.eval(pl.element().cast(pl.Float64, strict=False))
        .list.sum()
        .alias("total_signal"),
        pl.col("member_max_signals")
        .cast(pl.Utf8)
        .str.split(",")
        .list.eval(pl.element().cast(pl.Float64, strict=False))
        .list.max()
        .alias("max_signal"),
    )

    samples = sorted(df.get_column("_samples").explode().drop_nulls().unique().to_list())
    samples = [s for s in samples if s]
    if not samples:
        raise ValueError("seacr_consensus_peaks: no member peak file named a sample")

    df = df.with_columns(
        pl.col("_samples").list.len().cast(pl.Int64).alias("num_samples"),
        (pl.col("end") - pl.col("start")).alias("width"),
        pl.col("_samples").list.first().str.replace(_REPLICATE_SUFFIX, "").alias("target"),
        pl.col("caller").fill_null("unknown"),
        *[pl.col("_samples").list.contains(pl.lit(s)).cast(pl.Int8).alias(s) for s in samples],
    )
    df = df.with_columns(
        pl.col("num_samples").cast(pl.Utf8).alias("support"),
        pl.concat_str(
            [
                pl.col("target"),
                pl.lit(":"),
                pl.col("chr"),
                pl.lit(":"),
                pl.col("start").cast(pl.Utf8),
                pl.lit("-"),
                pl.col("end").cast(pl.Utf8),
            ]
        ).alias("peak_id"),
    )
    return df.select(list(EXPECTED_SCHEMA) + samples).sort(["target", "chr", "start"])
