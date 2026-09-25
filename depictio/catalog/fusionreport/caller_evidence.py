"""Unpivot the per-caller evidence strings of the fusion-report consensus CSV.

``<sample>.fusions.csv`` holds one column per caller whose cell is that caller's
own evidence for the fusion, written as ``key: value`` pairs joined by commas, for
example::

    arriba          position: chr4:1806934#chr4:1727977,reading-frame: in-frame,
                    type: duplication,split_reads1: 90,split_reads2: 104,
                    discordant_mates: 300,coverage1: 245,coverage2: 425,
                    confidence: high
    fusioncatcher   position: 4:1806934:+#4:1727977:+,common_mapping_reads: 0,
                    spanning_pairs: 840,spanning_unique_reads: 75,...
    starfusion      position: chr4:1806934:+#chr4:1727977:+,junction_reads: 253,
                    spanning_reads: 543,ffmp: 66217.4528

The keys differ per caller, so the recipe reads the read counts each caller
reports and sums them into one comparable ``supporting_reads`` figure. That makes
the callers directly comparable on the same fusion, which is what a per-caller
evidence dot plot and a caller-versus-caller scatter need. The full string is kept
in ``detail`` so nothing is lost.

The CSV carries no sample column, so the source declares ``source_path`` and the
sample is read off the file name (``fusionreport/<sample>/<sample>.fusions.csv``);
the evidence fraction is a caller's share of the fusion's support in that sample.

The callers are every column that is not one of fusion-report's own, so a run
with other callers than the default three still gets a row per caller. A caller
without a known read-count vocabulary has every ``*read*`` / ``*pair*`` /
``*frag*`` / ``*mate*`` count of its string summed.

Output columns: sample, fusion, caller, position_5p, position_3p,
supporting_reads, log_support, evidence_fraction, fii, detail
"""

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# The sample exists only in the file NAME: the source hands every row the path
# of its file, and the sample is the basename minus the suffix.
_SOURCE_PATH = "_source_path"
_SAMPLE_SUFFIX = ".fusions.csv"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="fusions",
        source_path=_SOURCE_PATH,
        glob_pattern="fusionreport/*/*.fusions.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "fusion": pl.Utf8,
    "caller": pl.Utf8,
    "position_5p": pl.Utf8,
    "position_3p": pl.Utf8,
    "supporting_reads": pl.Int64,
    "log_support": pl.Float64,
    "evidence_fraction": pl.Float64,
    "fii": pl.Float64,
    "detail": pl.Utf8,
}

# Which keys of each caller's evidence string carry read counts. Keys the caller
# did not write simply contribute nothing.
READ_KEYS: dict[str, tuple[str, ...]] = {
    "arriba": ("split_reads1", "split_reads2", "discordant_mates"),
    "fusioncatcher": ("spanning_pairs", "spanning_unique_reads"),
    "starfusion": ("junction_reads", "spanning_reads"),
}


# fusion-report's own columns; every other column is one caller's evidence.
_REPORT_COLUMNS = frozenset(
    {
        "fusion",
        "databases",
        "fusion indication index (fii)",
        "fii",
        "score",
        "explained fii",
        "explained score",
        _SOURCE_PATH,
    }
)
# Any `<key>: <int>` whose key names reads, pairs, fragments or mates.
_GENERIC_COUNT = r"[A-Za-z0-9_]*(?:read|pair|frag|mate)[A-Za-z0-9_]*:\s*-?\d+"


def _caller_name(column: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", column.strip().lower()).strip("_")


def _generic_read_count(detail: pl.Expr) -> pl.Expr:
    """Sum every read-like count of an evidence string whose keys are unknown."""
    return (
        detail.str.extract_all(_GENERIC_COUNT)
        .list.eval(pl.element().str.extract(r"(-?\d+)$", 1).cast(pl.Int64, strict=False))
        .list.sum()
        .fill_null(0)
        .cast(pl.Int64)
    )


def _column(df: pl.DataFrame, name: str) -> str | None:
    lowered = {c.lower(): c for c in df.columns}
    return lowered.get(name.lower())


def _read_count(detail: pl.Expr, keys: tuple[str, ...]) -> pl.Expr:
    """Sum the read-count keys a caller wrote into its evidence string."""
    parts = [
        detail.str.extract(rf"{key}:\s*(-?\d+)", 1).cast(pl.Int64, strict=False).fill_null(0)
        for key in keys
    ]
    return pl.sum_horizontal(parts).cast(pl.Int64)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (fusion, caller that reported it), with comparable read support."""
    df = sources["fusions"]

    fusion_col = _column(df, "Fusion")
    if fusion_col is None:
        raise ValueError(f"caller_evidence: no 'Fusion' column in {df.columns}")
    fii_col = _column(df, "Fusion Indication Index (FII)") or _column(df, "FII")

    sample = (
        pl.col(_SOURCE_PATH).str.split("/").list.last().str.strip_suffix(_SAMPLE_SUFFIX)
        if _SOURCE_PATH in df.columns
        else pl.lit("", dtype=pl.Utf8)
    )
    callers = {c: _caller_name(c) for c in df.columns if c.strip().lower() not in _REPORT_COLUMNS}

    frames: list[pl.DataFrame] = []
    for col, caller in callers.items():
        keys = READ_KEYS.get(caller)
        detail = pl.col(col).cast(pl.Utf8).str.strip_chars()
        position = detail.str.extract(r"position:\s*([^,]+)", 1).fill_null("")
        frames.append(
            df.filter(pl.col(col).is_not_null() & (detail.str.len_chars() > 0)).select(
                sample.alias("sample"),
                pl.col(fusion_col).cast(pl.Utf8).alias("fusion"),
                pl.lit(caller, dtype=pl.Utf8).alias("caller"),
                position.str.split("#")
                .list.get(0, null_on_oob=True)
                .fill_null("")
                .alias("position_5p"),
                position.str.split("#")
                .list.get(1, null_on_oob=True)
                .fill_null("")
                .alias("position_3p"),
                (_read_count(detail, keys) if keys else _generic_read_count(detail)).alias(
                    "supporting_reads"
                ),
                (
                    pl.col(fii_col).cast(pl.Float64, strict=False)
                    if fii_col
                    else pl.lit(None, dtype=pl.Float64)
                ).alias("fii"),
                detail.alias("detail"),
            )
        )

    if not frames:
        raise ValueError(
            f"caller_evidence: no caller column beside fusion-report's own in {df.columns}"
        )

    out = pl.concat(frames, how="vertical")

    total = pl.col("supporting_reads").sum().over(["sample", "fusion"])
    out = out.with_columns(
        (pl.col("supporting_reads").cast(pl.Float64) + 1).log10().alias("log_support"),
        pl.when(total > 0)
        .then(pl.col("supporting_reads").cast(pl.Float64) / total.cast(pl.Float64))
        .otherwise(0.0)
        .cast(pl.Float64)
        .alias("evidence_fraction"),
    )

    return out.select(list(EXPECTED_SCHEMA)).sort(["sample", "fusion", "caller"])
