"""The nf-core/pairgenomealign genome hub: one row per query genome, every per-genome number.

pairgenomealign aligns each genome of its samplesheet (the queries) to one
target genome. Every tab filters through this table, so it has to exist on
every run: it is built from the one-to-one alignment summary the pipeline always
writes, and enriched with what it may write, each missing source leaving its
columns null rather than failing the collection:

* the substitution matrix of the alignment (block count, K80 distance and the
  transition / transversion ratio);
* the assembly-scan statistics of the query (contigs, length, N50, GC), absent
  with ``--skip_assembly_qc``;
* the poly-N gaps of the query from ``seqtk cutN``; a genome whose BED is empty
  has no row there and gets 0 gaps here.

Design columns come from the optional design table (``METADATA_FILE``): the
genome id is its ``sample`` column, or its first column when none is named so,
and every other column is joined under its own name, so the dashboard's
``{GROUP_COL}`` resolves against it. Nothing is parsed out of genome names.

Sources:
    identity   ``last_split_identity`` (catalog ``last/split_identity.py``)
    matrix     ``last_split_matrix`` (catalog ``last/split_matrix.py``), optional
    assembly   ``assemblyscan_stats`` (catalog ``assemblyscan/stats.py``), optional
    gaps       ``seqtk_cutn_gaps`` (catalog ``seqtk/cutn_gaps.py``), optional
    metadata   ``metadata`` (the design table), optional

Output schema (in this order, the design columns right after ``genome``):
    genome : Utf8
    <design columns>
    aligned_bp : Int64, percent_identity, target_aligned_pct, query_aligned_pct : Float64
    blocks : Int64, k80_distance, ts_tv_ratio : Float64
    contigs, total_length, n50 : Int64, gc_pct : Float64
    gaps, gap_bp : Int64
    target, pair : Utf8
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="identity", dc_ref="last_split_identity"),
    RecipeSource(ref="matrix", dc_ref="last_split_matrix", optional=True),
    RecipeSource(ref="assembly", dc_ref="assemblyscan_stats", optional=True),
    RecipeSource(ref="gaps", dc_ref="seqtk_cutn_gaps", optional=True),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

# Column order is the display order of the sample sheet: the genome, its
# measures, and the run-constant target and the pair key last (the design
# columns are inserted right after the genome).
EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "aligned_bp": pl.Int64,
    "percent_identity": pl.Float64,
    "target_aligned_pct": pl.Float64,
    "query_aligned_pct": pl.Float64,
    "blocks": pl.Int64,
    "k80_distance": pl.Float64,
    "ts_tv_ratio": pl.Float64,
    "contigs": pl.Int64,
    "total_length": pl.Int64,
    "n50": pl.Int64,
    "gc_pct": pl.Float64,
    "gaps": pl.Int64,
    "gap_bp": pl.Int64,
    "target": pl.Utf8,
    "pair": pl.Utf8,
}
# Design columns are run-dependent and pass through unvalidated.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def _present(df: pl.DataFrame | None) -> bool:
    return df is not None and not df.is_empty()


def _design(metadata: pl.DataFrame) -> pl.DataFrame:
    """The design table keyed by ``genome``, every other column kept as is."""
    id_col = "sample" if "sample" in metadata.columns else metadata.columns[0]
    design = metadata.rename({id_col: "genome"}).with_columns(
        pl.col("genome").cast(pl.Utf8).str.strip_chars()
    )
    clashing = [c for c in design.columns if c != "genome" and c in EXPECTED_SCHEMA]
    return design.drop(clashing).unique(subset="genome", keep="first")


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    identity = sources["identity"]
    hub = identity.select(
        pl.col("query").alias("genome"),
        "target",
        "pair",
        "aligned_bp",
        "percent_identity",
        "target_aligned_pct",
        "query_aligned_pct",
    ).unique(subset="genome", keep="first")

    matrix = sources.get("matrix")
    if _present(matrix):
        hub = hub.join(
            matrix.select(
                pl.col("query").alias("genome"), "blocks", "k80_distance", "ts_tv_ratio"
            ).unique(subset="genome", keep="first"),
            on="genome",
            how="left",
        )

    assembly = sources.get("assembly")
    if _present(assembly):
        hub = hub.join(
            assembly.select("genome", "contigs", "total_length", "n50", "gc_pct"),
            on="genome",
            how="left",
        )

    gaps = sources.get("gaps")
    if gaps is not None:
        hub = hub.join(gaps.select("genome", "gaps", "gap_bp"), on="genome", how="left")
        # The cutN collection lists every genome with at least one gap: a genome
        # it does not list has none.
        hub = hub.with_columns(pl.col("gaps").fill_null(0), pl.col("gap_bp").fill_null(0))

    hub = hub.with_columns(
        [pl.lit(None, dtype=t).alias(c) for c, t in EXPECTED_SCHEMA.items() if c not in hub.columns]
    ).with_columns([pl.col(c).cast(t) for c, t in EXPECTED_SCHEMA.items()])
    out = hub.select(list(EXPECTED_SCHEMA))

    metadata = sources.get("metadata")
    if _present(metadata):
        design = _design(metadata)
        out = out.join(design, on="genome", how="left").select(
            "genome", *[c for c in design.columns if c != "genome"], *list(EXPECTED_SCHEMA)[1:]
        )
    return out.sort("genome")
