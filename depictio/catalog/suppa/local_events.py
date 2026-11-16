"""SUPPA2 differential splicing of local events, one row per contrast and event.

SUPPA2 computes a PSI per local splicing event from transcript TPMs (no
alignment needed), then ``suppa.py diffSplice`` compares two conditions. Its
``<contrast>_local_diffsplice.dpsi`` table holds one row per event, keyed by
the SUPPA event id (``<gene>;<type>:<chrom>:<coordinates>:<strand>``), with the
delta PSI and an empirical p-value. The header names the two conditions but
has one field less than the rows (the event id column is unnamed), so the file
is read header-less.

Event types: skipped exon (SE), alternative 5' / 3' splice site (A5 / A3),
mutually exclusive exons (MX), retained intron (RI), alternative first / last
exon (AF / AL).

Orientation: SUPPA reports the second condition of its header minus the first.
nf-core/rnasplice 1.x listed the treatment first (control minus treatment);
2.0 lists the control first (treatment minus control) and names the table
``local_<treatment>-<control>.dpsi``. The header is read, not assumed: the
sign is set so that ``dpsi`` is treatment minus control whichever order the
run wrote, like the rMATS and DEXSeq recipes. A header naming neither order of
the contrast falls back on the release's convention (its file name).

Events SUPPA could not quantify in one condition come with a NaN delta PSI and
are dropped.

Sources:
    events   every ``*_local_diffsplice.dpsi`` (rnasplice 1.x) under the run
             root; the template points 2.0 runs at ``local_*.dpsi``.

Params:
    pvalue     p-value cut-off (default 0.05).
    min_dpsi   minimal absolute delta PSI for a call (default 0.1).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="events",
        input_schema={
            "event": pl.Utf8,
            "dpsi_raw": pl.Utf8,
            "pvalue_raw": pl.Utf8,
            "source_path": pl.Utf8,
        },
        glob_pattern="**/*_local_diffsplice.dpsi",
        format="tsv",
        # The header row is kept as data: it names the two conditions, which
        # orient the sign (it has one field less, so its p-value is null).
        # A schema, not new_columns: the shorter header row is padded with a null.
        read_kwargs={
            "has_header": False,
            "schema": {"event": pl.Utf8, "dpsi_raw": pl.Utf8, "pvalue_raw": pl.Utf8},
        },
        source_path="source_path",
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "contrast": pl.Utf8,
    "event_id": pl.Utf8,
    "event_type": pl.Utf8,
    "gene_id": pl.Utf8,
    "chrom": pl.Utf8,
    "strand": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "dpsi": pl.Float64,
    "abs_dpsi": pl.Float64,
    "pvalue": pl.Float64,
    "neg_log10_pvalue": pl.Float64,
    "significant": pl.Boolean,
    "direction": pl.Utf8,
}

DEFAULTS = {"pvalue": 0.05, "min_dpsi": 0.1}
P_ZERO_NEG_LOG10 = 300.0
EVENT_LABELS = {
    "SE": "Skipped exon",
    "RI": "Retained intron",
    "MX": "Mutually exclusive exons",
    "A3": "Alternative 3' splice site",
    "A5": "Alternative 5' splice site",
    "AF": "Alternative first exon",
    "AL": "Alternative last exon",
}
# 1.x: <contrast>_local_diffsplice.dpsi; 2.0: local_<treatment>-<control>.dpsi.
_CONTRAST = r"(?:([^/]+)_local_diffsplice|(?:^|/)local_([^/]+))\.dpsi$"
_HEADER = r"^(?:local_)?(.+?)-(?:local_)?(.+)_dPSI$"


def orientation(df: pl.DataFrame) -> pl.DataFrame:
    """``source_path`` → ``_sign``: +1 when SUPPA's second condition is the
    contrast's treatment, -1 when it is its control."""
    parts = pl.col("source_path").str.extract_groups(_CONTRAST)
    files = (
        df.select("source_path")
        .unique()
        .with_columns(
            pl.coalesce(parts.struct.field("1"), parts.struct.field("2")).alias("contrast"),
            parts.struct.field("2").is_not_null().alias("_v2"),
        )
    )
    header = (
        df.filter(pl.col("pvalue_raw").is_null() & pl.col("event").str.ends_with("_dPSI"))
        .select("source_path", pl.col("event").str.extract_groups(_HEADER).alias("_h"))
        .select(
            "source_path",
            pl.col("_h").struct.field("1").alias("_first"),
            pl.col("_h").struct.field("2").alias("_second"),
        )
    )
    files = files.join(header, on="source_path", how="left")
    sign = (
        pl.when(pl.col("contrast") == pl.concat_str(["_second", pl.lit("-"), "_first"]))
        .then(pl.lit(1.0))
        .when(pl.col("contrast") == pl.concat_str(["_first", pl.lit("-"), "_second"]))
        .then(pl.lit(-1.0))
        .when(pl.col("_v2"))
        .then(pl.lit(1.0))
        .otherwise(pl.lit(-1.0))
    )
    return files.select("source_path", "contrast", sign.alias("_sign"))


_EVENT = r"^([^;]+);([A-Z0-9]+):([^:]+):(.+):([+-])$"


def param(params: dict[str, str] | None, name: str) -> float:
    raw = str((params or {}).get(name) or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULTS[name]
    return value if value >= 0 else DEFAULTS[name]


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """Parsed event ids, oriented delta PSI and the significance call."""
    cutoff, min_dpsi = param(params, "pvalue"), param(params, "min_dpsi")
    df = sources["events"]
    df = df.join(orientation(df), on="source_path", how="left").filter(
        pl.col("pvalue_raw").is_not_null()
    )
    parts = pl.col("event").str.extract_groups(_EVENT)
    coords = pl.col("_coords").str.extract_all(r"\d+").list.eval(pl.element().cast(pl.Int64))
    out = (
        df.with_columns(
            parts.struct.field("1").alias("gene_id"),
            parts.struct.field("2").alias("_type"),
            parts.struct.field("3").alias("chrom"),
            parts.struct.field("4").alias("_coords"),
            parts.struct.field("5").alias("strand"),
            (pl.col("_sign") * pl.col("dpsi_raw").cast(pl.Float64, strict=False)).alias("dpsi"),
            pl.col("pvalue_raw").cast(pl.Float64, strict=False).alias("pvalue"),
        )
        .filter(pl.col("dpsi").is_not_null() & pl.col("dpsi").is_not_nan())
        .with_columns(coords.list.min().alias("start"), coords.list.max().alias("end"))
    )
    significant = (pl.col("pvalue") < cutoff) & (pl.col("dpsi").abs() >= min_dpsi)
    out = out.with_columns(
        pl.col("event").alias("event_id"),
        pl.col("_type").replace_strict(EVENT_LABELS, default=pl.col("_type")).alias("event_type"),
        pl.col("dpsi").abs().alias("abs_dpsi"),
        pl.when(pl.col("pvalue") > 0)
        .then(-pl.col("pvalue").log10())
        .when(pl.col("pvalue") == 0)
        .then(pl.lit(P_ZERO_NEG_LOG10))
        .otherwise(None)
        .alias("neg_log10_pvalue"),
        significant.fill_null(False).alias("significant"),
    ).with_columns(
        pl.when(~pl.col("significant"))
        .then(pl.lit("not significant"))
        .when(pl.col("dpsi") > 0)
        .then(pl.lit("up"))
        .otherwise(pl.lit("down"))
        .alias("direction")
    )
    return out.select(list(OUTPUT_SCHEMA)).sort(["contrast", "pvalue"], nulls_last=True)
