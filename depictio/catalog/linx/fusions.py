"""LINX's predicted gene fusions, one row per fusion, with both partners resolved.

``<tumor>.linx.fusion.tsv`` has one row per candidate fusion LINX found by
chaining structural variants: the partner pair name (``GENE5_GENE3``), whether
it is reportable and why, the phasing (``INFRAME``, ``SKIPPED_EXONS``,
``OUT_OF_FRAME``), the fused exons, the protein domains kept and lost, and the
two breakend ids. ``<tumor>.linx.breakend.tsv`` resolves those ids to the gene,
transcript, region type and exon count of each partner, which the fusion table
itself only carries as a name.

``fusion_id`` (tumor, 5' breakend, 3' breakend) is unique per candidate, the
record key. ``exons_up_total`` / ``exons_down_total`` give the transcript exon
counts the fusion-structure view scales each partner by.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_TSV = {"infer_schema_length": 0}

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="fusions",
        glob_pattern="**/*.linx.fusion.tsv",
        format="tsv",
        read_kwargs=_TSV,
        source_path="source_path",
    ),
    RecipeSource(
        ref="breakends",
        glob_pattern="**/*.linx.breakend.tsv",
        format="tsv",
        read_kwargs=_TSV,
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "fusion_id": pl.Utf8,
    "sample": pl.Utf8,
    "fusion": pl.Utf8,
    "gene_up": pl.Utf8,
    "gene_down": pl.Utf8,
    "reported": pl.Boolean,
    "reported_type": pl.Utf8,
    "reportable_reasons": pl.Utf8,
    "phased": pl.Utf8,
    "likelihood": pl.Utf8,
    "transcript_up": pl.Utf8,
    "transcript_down": pl.Utf8,
    "region_up": pl.Utf8,
    "region_down": pl.Utf8,
    "coords_up": pl.Utf8,
    "coords_down": pl.Utf8,
    "fused_exon_up": pl.Int64,
    "fused_exon_down": pl.Int64,
    "exons_up_total": pl.Int64,
    "exons_down_total": pl.Int64,
    "skipped_exons_up": pl.Int64,
    "skipped_exons_down": pl.Int64,
    "chain_length": pl.Int64,
    "chain_links": pl.Int64,
    "chain_terminated": pl.Boolean,
    "domains_kept": pl.Utf8,
    "domains_lost": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_SAMPLE_RE = r"([^/]+)\.linx\.(?:fusion|breakend)\.tsv$"


def _int(col: str) -> pl.Expr:
    return pl.col(col).cast(pl.Int64, strict=False)


def _text(col: str) -> pl.Expr:
    return pl.when(pl.col(col).str.strip_chars() == "").then(None).otherwise(pl.col(col))


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    fusions = sources["fusions"].with_columns(
        pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample")
    )
    for opt in (
        "reportedType", "reportableReasons", "likelihood", "chainLength", "chainLinks",
        "chainTerminated", "domainsKept", "domainsLost", "skippedExonsUp", "skippedExonsDown",
        "fusedExonUp", "fusedExonDown", "fivePrimeCoords", "threePrimeCoords",
    ):  # fmt: skip
        if opt not in fusions.columns:
            fusions = fusions.with_columns(pl.lit(None, pl.Utf8).alias(opt))
    breakends = sources["breakends"].select(
        pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
        pl.col("id").alias("breakend_id"),
        pl.col("gene"),
        pl.col("transcriptId").alias("transcript"),
        pl.col("regionType").alias("region"),
        _int("totalExonCount").alias("exons_total"),
    )
    up = breakends.rename({c: f"{c}_up" for c in ("gene", "transcript", "region", "exons_total")})
    down = breakends.rename(
        {c: f"{c}_down" for c in ("gene", "transcript", "region", "exons_total")}
    )
    joined = fusions.join(
        up,
        left_on=["sample", "fivePrimeBreakendId"],
        right_on=["sample", "breakend_id"],
        how="left",
    ).join(
        down,
        left_on=["sample", "threePrimeBreakendId"],
        right_on=["sample", "breakend_id"],
        how="left",
    )
    name_parts = pl.col("name").str.split("_")
    out = joined.select(
        pl.concat_str(
            [pl.col("sample"), pl.col("fivePrimeBreakendId"), pl.col("threePrimeBreakendId")],
            separator="|",
        ).alias("fusion_id"),
        "sample",
        pl.col("name").alias("fusion"),
        pl.coalesce(pl.col("gene_up"), name_parts.list.first()).alias("gene_up"),
        pl.coalesce(pl.col("gene_down"), name_parts.list.last()).alias("gene_down"),
        (pl.col("reported").str.to_lowercase() == "true").alias("reported"),
        pl.col("reportedType").alias("reported_type"),
        _text("reportableReasons").alias("reportable_reasons"),
        pl.col("phased"),
        pl.col("likelihood"),
        "transcript_up",
        "transcript_down",
        "region_up",
        "region_down",
        pl.col("fivePrimeCoords").alias("coords_up"),
        pl.col("threePrimeCoords").alias("coords_down"),
        _int("fusedExonUp").alias("fused_exon_up"),
        _int("fusedExonDown").alias("fused_exon_down"),
        "exons_total_up",
        "exons_total_down",
        _int("skippedExonsUp").alias("skipped_exons_up"),
        _int("skippedExonsDown").alias("skipped_exons_down"),
        _int("chainLength").alias("chain_length"),
        _int("chainLinks").alias("chain_links"),
        (pl.col("chainTerminated").str.to_lowercase() == "true").alias("chain_terminated"),
        _text("domainsKept").alias("domains_kept"),
        _text("domainsLost").alias("domains_lost"),
    ).rename({"exons_total_up": "exons_up_total", "exons_total_down": "exons_down_total"})
    phase_rank = pl.col("phased").replace_strict(
        {"INFRAME": 0, "SKIPPED_EXONS": 1, "OUT_OF_FRAME": 2}, default=3, return_dtype=pl.Int64
    )
    # Reported first, then in-frame, then the shorter chain: the order the
    # fusion-structure view draws its facets in.
    return (
        out.with_columns(phase_rank.alias("_phase"))
        .sort(
            ["sample", "reported", "_phase", "chain_length"], descending=[False, True, False, False]
        )
        .drop("_phase")
        .select(list(EXPECTED_SCHEMA))
    )
