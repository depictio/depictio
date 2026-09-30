"""The run's driver catalog, somatic and germline, one row per gene and driver.

PURPLE writes ``<tumor>.purple.driver.catalog.somatic.tsv`` and, with a normal,
``<tumor>.purple.driver.catalog.germline.tsv``: one row per gene and driver type
(point mutation, amplification, deletion, LOH, germline variant) with PURPLE's
driver likelihood, the variant counts behind a mutation driver, biallelic
status and the gene's copy-number range. LINX then republishes the reported
somatic drivers in ``<tumor>.linx.driver.catalog.tsv`` and adds its own
structural drivers (``DISRUPTION``, ``HOM_DUP_DISRUPTION``,
``HOM_DEL_DISRUPTION``); LINX germline writes ``*.linx.germline.driver.catalog.tsv``
the same way.

Every ``*driver.catalog*.tsv`` of the run is read. PURPLE's rows are kept as
they are; a LINX row is kept only when PURPLE has no row for the same tumor,
gene and driver type, so the LINX disruptions are added without doubling the
reported PURPLE drivers. ``origin`` says somatic or germline (from the file
name), ``source_tool`` which tool wrote the row, and ``driver_id`` (tumor, gene,
driver type) is the record key. ``report_status`` keeps PURPLE's ``REPORTED`` /
``NOT_REPORTED`` as text so a filter can default to the reported drivers.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="catalogs",
        glob_pattern="**/*.driver.catalog*.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "driver_id": pl.Utf8,
    "sample": pl.Utf8,
    "gene": pl.Utf8,
    "driver": pl.Utf8,
    "origin": pl.Utf8,
    "source_tool": pl.Utf8,
    "category": pl.Utf8,
    "reported": pl.Boolean,
    "report_status": pl.Utf8,
    "driver_likelihood": pl.Float64,
    "likelihood_method": pl.Utf8,
    "biallelic": pl.Boolean,
    "missense": pl.Int64,
    "nonsense": pl.Int64,
    "splice": pl.Int64,
    "inframe": pl.Int64,
    "frameshift": pl.Int64,
    "min_copy_number": pl.Float64,
    "max_copy_number": pl.Float64,
    "chrom": pl.Utf8,
    "chromosome_band": pl.Utf8,
    "transcript": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_FILE_RE = r"([^/]+)\.(purple|linx)\.(?:germline\.)?driver\.catalog(?:\.(somatic|germline))?\.tsv$"
_TOOL_RANK = {"PURPLE": 0, "LINX": 1}


def _int(name: str) -> pl.Expr:
    return pl.col(name).cast(pl.Float64, strict=False).round(0).cast(pl.Int64)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["catalogs"]
    path = pl.col("source_path")
    df = df.with_columns(
        path.str.extract(_FILE_RE, 1).alias("sample"),
        path.str.extract(_FILE_RE, 2).str.to_uppercase().alias("source_tool"),
        pl.when(path.str.contains(r"germline"))
        .then(pl.lit("germline"))
        .otherwise(pl.lit("somatic"))
        .alias("origin"),
    ).filter(pl.col("sample").is_not_null() & pl.col("gene").is_not_null())
    for opt in (
        "category", "reportedStatus", "driverLikelihood", "likelihoodMethod", "biallelic",
        "missense", "nonsense", "splice", "inframe", "frameshift", "minCopyNumber",
        "maxCopyNumber", "chromosome", "chromosomeBand", "transcript",
    ):  # fmt: skip
        if opt not in df.columns:
            df = df.with_columns(pl.lit(None, pl.Utf8).alias(opt))

    out = df.select(
        pl.concat_str([pl.col("sample"), pl.col("gene"), pl.col("driver")], separator="|").alias(
            "driver_id"
        ),
        "sample",
        "gene",
        "driver",
        "origin",
        "source_tool",
        "category",
        (pl.col("reportedStatus") == "REPORTED").alias("reported"),
        pl.col("reportedStatus").fill_null("NOT_REPORTED").alias("report_status"),
        pl.col("driverLikelihood").cast(pl.Float64, strict=False).alias("driver_likelihood"),
        pl.col("likelihoodMethod").alias("likelihood_method"),
        (pl.col("biallelic").str.to_lowercase() == "true").alias("biallelic"),
        _int("missense").alias("missense"),
        _int("nonsense").alias("nonsense"),
        _int("splice").alias("splice"),
        _int("inframe").alias("inframe"),
        _int("frameshift").alias("frameshift"),
        pl.col("minCopyNumber").cast(pl.Float64, strict=False).alias("min_copy_number"),
        pl.col("maxCopyNumber").cast(pl.Float64, strict=False).alias("max_copy_number"),
        pl.col("chromosome").alias("chrom"),
        pl.col("chromosomeBand").alias("chromosome_band"),
        "transcript",
    )
    # PURPLE first: a LINX row survives only when PURPLE has no row for it.
    return (
        out.with_columns(pl.col("source_tool").replace_strict(_TOOL_RANK, default=9).alias("_rank"))
        .sort(["_rank"])
        .unique(subset=["driver_id"], keep="first", maintain_order=True)
        .drop("_rank")
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "reported", "driver_likelihood"], descending=[False, True, True])
    )
