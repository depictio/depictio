"""Consensus genome hub for nf-core/viralmetagenome: one row per final consensus.

viralmetagenome reaches a consensus genome by two routes, and a run takes one
or both:

* de novo: contigs are clustered and each kept cluster is refined by
  iterative mapping into a consensus (``vmg_contigs_overview``, catalog
  ``viralmetagenome/contigs_overview``; absent with ``--skip_assembly``);
* constraint: the reads are mapped to the references of the mapping
  constraint sheet (``vmg_mapping_overview``, catalog
  ``viralmetagenome/mapping_overview``; absent without ``--mapping_constraints``).

Both tables carry the same per-genome measures (closest reference and its
identity, ambiguous bases, CheckV, mapping, depth and breadth, variant counts),
so the hub stacks them under one schema, keyed ``<sample>_<reference>``
(``genome_id``). CheckV's completeness is not in either table; it is read from
``checkv_quality`` (catalog ``checkv/quality_summary``) for the consensus the
genome ended with: the variant-calling consensus of a constraint mapping, the
consensus of the last refinement step of a de novo one. The design columns of
the sample hub (``samples``) follow ``sample``, so ``{GROUP_COL}`` resolves here
too.

Sources:
    denovo      ``vmg_contigs_overview``, optional
    constraint  ``vmg_mapping_overview``, optional
    checkv      ``checkv_quality``, optional
    samples     ``samples``, the sample hub, optional

Output schema: ``GENOME_SCHEMA`` of ``depictio.recipes.lib.viralmetagenome``, then
``checkv_completeness`` and ``completeness_method``, with the design columns
after ``sample``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.viralmetagenome import (
    GENOME_SCHEMA,
    NO_GROUP_COL,
    NO_GROUP_VALUE,
    split_mapping_name,
)

_GENOME_INPUT = {"genome_id": pl.Utf8, "sample": pl.Utf8, "reference": pl.Utf8, "route": pl.Utf8}

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="denovo", dc_ref="vmg_contigs_overview", optional=True, input_schema=_GENOME_INPUT
    ),
    RecipeSource(
        ref="constraint", dc_ref="vmg_mapping_overview", optional=True, input_schema=_GENOME_INPUT
    ),
    RecipeSource(
        ref="checkv",
        dc_ref="checkv_quality",
        optional=True,
        input_schema={"sample": pl.Utf8, "contig_id": pl.Utf8, "completeness": pl.Float64},
    ),
    RecipeSource(ref="samples", dc_ref="samples", optional=True, input_schema={"sample": pl.Utf8}),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    **GENOME_SCHEMA,
    "checkv_completeness": pl.Float64,
    "completeness_method": pl.Utf8,
}

#: Measures of the sample hub, which are not design columns.
_SAMPLE_MEASURES = {
    "raw_read_pairs",
    "raw_gc_pct",
    "raw_dup_pct",
    "trimmed_reads",
    "q30_pct",
    "fastp_dup_pct",
    "adapter_pct",
    "trimmed_read_pairs",
    "host_pct",
    "host_filtered_read_pairs",
    "retained_pct",
    "assembly_length",
    "assembly_n50",
    "clusters",
    "removed_clusters",
    "mean_cluster_size",
    "singletons",
    "denovo_consensus",
}
_FINAL_CONSTRAINT_STEP = "itvariant-calling"


def _present(frame: pl.DataFrame | None) -> bool:
    return frame is not None and not frame.is_empty()


def _completeness(checkv: pl.DataFrame, genomes: pl.DataFrame) -> pl.DataFrame:
    """``(genome_id, checkv_completeness, completeness_method)`` of each genome's final consensus."""
    rows = []
    for rec in checkv.iter_rows(named=True):
        reference, _route, step = split_mapping_name(rec["contig_id"] or "", rec["sample"] or "")
        if reference is None:
            continue
        rows.append(
            {
                "genome_id": f"{rec['sample']}_{reference}",
                "checkv_step": step,
                "checkv_completeness": rec.get("completeness"),
                "completeness_method": rec.get("completeness_method"),
            }
        )
    if not rows:
        return pl.DataFrame(
            schema={
                "genome_id": pl.Utf8,
                "checkv_completeness": pl.Float64,
                "completeness_method": pl.Utf8,
            }
        )
    calls = pl.DataFrame(
        rows,
        schema={
            "genome_id": pl.Utf8,
            "checkv_step": pl.Utf8,
            "checkv_completeness": pl.Float64,
            "completeness_method": pl.Utf8,
        },
    )
    wanted = genomes.select(
        "genome_id",
        pl.when(pl.col("route") == "constraint")
        .then(pl.lit(_FINAL_CONSTRAINT_STEP))
        .otherwise(pl.col("step"))
        .alias("_want"),
    )
    ranked = calls.join(wanted, on="genome_id", how="inner").with_columns(
        pl.when(pl.col("checkv_step") == pl.col("_want"))
        .then(0)
        .when(pl.col("checkv_step") == _FINAL_CONSTRAINT_STEP)
        .then(1)
        .otherwise(2)
        .alias("_rank")
    )
    return (
        ranked.sort("genome_id", "_rank")
        .unique(subset="genome_id", keep="first")
        .select("genome_id", "checkv_completeness", "completeness_method")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    parts = [
        sources[ref].select([pl.col(c).cast(t) for c, t in GENOME_SCHEMA.items()])
        for ref in ("denovo", "constraint")
        if _present(sources.get(ref))
    ]
    if not parts:
        raise ValueError(
            "viralmetagenome genomes: neither the contigs nor the mapping overview was found"
        )
    genomes = pl.concat(parts).unique(subset="genome_id", keep="first")

    checkv = sources.get("checkv")
    if _present(checkv):
        genomes = genomes.join(_completeness(checkv, genomes), on="genome_id", how="left")
    for col in ("checkv_completeness", "completeness_method"):
        if col not in genomes.columns:
            genomes = genomes.with_columns(pl.lit(None, dtype=OUTPUT_SCHEMA[col]).alias(col))
    genomes = genomes.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])

    samples = sources.get("samples")
    design: list[str] = []
    if _present(samples):
        design = [
            c
            for c in samples.columns
            if c != "sample" and c not in _SAMPLE_MEASURES and c not in OUTPUT_SCHEMA
        ]
        if design:
            genomes = genomes.join(
                samples.select("sample", *design).unique(subset="sample"), on="sample", how="left"
            )
    if not design:
        genomes = genomes.with_columns(pl.lit(NO_GROUP_VALUE).alias(NO_GROUP_COL))
        design = [NO_GROUP_COL, *design]
    cols = list(OUTPUT_SCHEMA)
    return genomes.select(cols[0], "sample", *design, *cols[2:]).sort(
        ["sample", "route", "reference"]
    )
