"""LINX's annotated somatic structural variants, one row per SV, as locus pairs.

LINX (hmftools) clusters the PURPLE-filtered structural variants into events and
writes ``<tumor>.linx.svs.tsv`` (one row per SV: both breakend coordinates as
``chrom:position:orientation``, the SV type, cluster id, junction copy-number
range, the genes each breakend falls in, fold-back and LINE flags) and
``<tumor>.linx.clusters.tsv`` (one row per cluster: the resolved event type,
e.g. ``RECIP_TRANS``, ``COMPLEX``, ``LINE``, and how many SVs it holds).

The two are joined on the cluster id so every SV carries the event it belongs
to, and the breakends are split into bindable columns (``chrom_a``, ``pos_a``,
``chrom_b``, ``pos_b``), the row shape a chord diagram binds. A single breakend
(``SGL``, ``INF``) has no partner: its ``chrom_b`` / ``pos_b`` are null, so the
chord skips it while tables and counts keep it. ``junction_copy_number`` is the
middle of LINX's range. The tumor id is the file name before ``.linx.``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_TSV = {"infer_schema_length": 0}

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="svs",
        glob_pattern="**/*.linx.svs.tsv",
        format="tsv",
        read_kwargs=_TSV,
        source_path="source_path",
    ),
    RecipeSource(
        ref="clusters",
        glob_pattern="**/*.linx.clusters.tsv",
        format="tsv",
        read_kwargs=_TSV,
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sv_key": pl.Utf8,
    "sample": pl.Utf8,
    "sv_id": pl.Int64,
    "label": pl.Utf8,
    "type": pl.Utf8,
    "cluster_id": pl.Int64,
    "resolved_type": pl.Utf8,
    "cluster_category": pl.Utf8,
    "cluster_sv_count": pl.Int64,
    "chrom_a": pl.Utf8,
    "pos_a": pl.Int64,
    "orient_a": pl.Int64,
    "chrom_b": pl.Utf8,
    "pos_b": pl.Int64,
    "orient_b": pl.Int64,
    "length": pl.Int64,
    "junction_copy_number": pl.Float64,
    "junction_copy_number_min": pl.Float64,
    "junction_copy_number_max": pl.Float64,
    "genes_a": pl.Utf8,
    "genes_b": pl.Utf8,
    "is_foldback": pl.Boolean,
    "fragile_site": pl.Boolean,
    "line_element": pl.Boolean,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_SAMPLE_RE = r"([^/]+)\.linx\.(?:svs|clusters)\.tsv$"


def _coord(col: str, i: int, dtype: type[pl.DataType]) -> pl.Expr:
    part = pl.col(col).str.split(":").list.get(i, null_on_oob=True)
    part = pl.when(part.is_in(["", "0", "-1"]) & (i == 0)).then(None).otherwise(part)
    return part.cast(dtype, strict=False)


def _bool(col: str) -> pl.Expr:
    return pl.col(col).str.to_lowercase() == "true"


def _empty_to_null(col: str) -> pl.Expr:
    return pl.when(pl.col(col).str.strip_chars() == "").then(None).otherwise(pl.col(col))


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    svs = sources["svs"].with_columns(
        pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
        pl.col("clusterId").cast(pl.Int64, strict=False).alias("cluster_id"),
    )
    for opt in (
        "coordsEnd", "fragileSiteStart", "fragileSiteEnd", "isFoldback", "lineTypeStart",
        "lineTypeEnd", "junctionCopyNumberMin", "junctionCopyNumberMax", "geneStart", "geneEnd",
    ):  # fmt: skip
        if opt not in svs.columns:
            svs = svs.with_columns(pl.lit(None, pl.Utf8).alias(opt))
    clusters = sources["clusters"].select(
        pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
        pl.col("clusterId").cast(pl.Int64, strict=False).alias("cluster_id"),
        pl.col("resolvedType").alias("resolved_type"),
        pl.col("category").alias("cluster_category"),
        pl.col("clusterCount").cast(pl.Int64, strict=False).alias("cluster_sv_count"),
    )
    jmin = pl.col("junctionCopyNumberMin").cast(pl.Float64, strict=False)
    jmax = pl.col("junctionCopyNumberMax").cast(pl.Float64, strict=False)
    out = (
        svs.with_columns(
            pl.col("svId").cast(pl.Int64, strict=False).alias("sv_id"),
            _coord("coordsStart", 0, pl.Utf8).alias("chrom_a"),
            _coord("coordsStart", 1, pl.Int64).alias("pos_a"),
            _coord("coordsStart", 2, pl.Int64).alias("orient_a"),
            _coord("coordsEnd", 0, pl.Utf8).alias("chrom_b"),
            _coord("coordsEnd", 1, pl.Int64).alias("pos_b"),
            _coord("coordsEnd", 2, pl.Int64).alias("orient_b"),
            jmin.alias("junction_copy_number_min"),
            jmax.alias("junction_copy_number_max"),
            ((jmin + jmax) / 2.0).alias("junction_copy_number"),
            _empty_to_null("geneStart").alias("genes_a"),
            _empty_to_null("geneEnd").alias("genes_b"),
            _bool("isFoldback").alias("is_foldback"),
            (_bool("fragileSiteStart") | _bool("fragileSiteEnd")).alias("fragile_site"),
            (
                (pl.col("lineTypeStart").fill_null("NONE") != "NONE")
                | (pl.col("lineTypeEnd").fill_null("NONE") != "NONE")
            ).alias("line_element"),
        )
        .with_columns(
            pl.when(pl.col("chrom_a") == pl.col("chrom_b"))
            .then((pl.col("pos_b") - pl.col("pos_a")).abs())
            .otherwise(None)
            .alias("length"),
            pl.concat_str([pl.col("sample"), pl.col("sv_id").cast(pl.Utf8)], separator="|").alias(
                "sv_key"
            ),
            pl.concat_str([pl.col("type"), pl.lit(" #"), pl.col("sv_id").cast(pl.Utf8)]).alias(
                "label"
            ),
        )
        .join(clusters, on=["sample", "cluster_id"], how="left")
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(["sample", "sv_id"])
