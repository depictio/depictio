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

Orientation: SUPPA reports the second condition of its header minus the first,
and nf-core/rnasplice lists the treatment first, so the sign is flipped here to
give treatment minus control, like the rMATS and DEXSeq recipes.

Events SUPPA could not quantify in one condition come with a NaN delta PSI and
are dropped.

Sources:
    events   every ``*_local_diffsplice.dpsi`` under the run root.

Params:
    pvalue     p-value cut-off (default 0.05).
    min_dpsi   minimal absolute delta PSI for a call (default 0.1).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="events",
        glob_pattern="**/*_local_diffsplice.dpsi",
        format="tsv",
        read_kwargs={
            "has_header": False,
            "skip_rows": 1,
            "new_columns": ["event", "dpsi_raw", "pvalue_raw"],
            "infer_schema_length": 0,
        },
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
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
_CONTRAST = r"([^/]+)_local_diffsplice\.dpsi$"
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
    parts = pl.col("event").str.extract_groups(_EVENT)
    coords = pl.col("_coords").str.extract_all(r"\d+").list.eval(pl.element().cast(pl.Int64))
    out = (
        df.with_columns(
            pl.col("source_path").str.extract(_CONTRAST, 1).alias("contrast"),
            parts.struct.field("1").alias("gene_id"),
            parts.struct.field("2").alias("_type"),
            parts.struct.field("3").alias("chrom"),
            parts.struct.field("4").alias("_coords"),
            parts.struct.field("5").alias("strand"),
            (-pl.col("dpsi_raw").cast(pl.Float64, strict=False)).alias("dpsi"),
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
    return out.select(list(EXPECTED_SCHEMA)).sort(["contrast", "pvalue"], nulls_last=True)
