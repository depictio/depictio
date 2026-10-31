"""One row per contig cluster, from the viralmetagenome clustering step.

viralmetagenome groups the de novo contigs of a sample (and the reference-pool
sequences they resemble) into clusters, one per genome or segment it expects to
rebuild (``--cluster_method``, ``--identity_threshold``), and writes them to
``assembly/polishing/intermediate/cluster/<sample>/[<prefix>-]<sample>.clusters.tsv``:
the cluster id, its taxon, its centroid (the sequence the consensus is
scaffolded on), its members and the share of the sample's contig read depth each
assembler's members carry.

``cluster_type`` says whether the centroid is a reference-pool sequence
(``Reference-anchored``) or one of the sample's own contigs (``Contig-only``):
a contig-only cluster has nothing in the pool close enough to anchor it, the
first place to look for a virus the pool does not hold.

The pipeline writes ``[<prefix>-]<sample>_<cluster>_cluster.json`` next to the
table for every cluster it keeps and refines; a cluster without one was
filtered out (too small a share of the reads, ``--perc_reads_contig``, or a
singleton), which ``status`` records.

Output schema:
    sample : Utf8              sample id
    cluster : Utf8             cluster id (cl0, cl1...)
    taxid : Utf8               taxon id the cluster was built under
    centroid : Utf8            centroid sequence id
    cluster_type : Utf8        Reference-anchored or Contig-only
    members : Int64            contigs in the cluster besides the centroid
    member_bp : Int64          summed length of the member contigs, bp
    read_depth_pct : Float64   share of the sample's contig read depth the cluster holds, percent
    member_ids : Utf8          the member contig ids, comma-separated
    status : Utf8              Refined (a consensus was built from it) or Filtered out
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.viralmetagenome import contig_assembler, contig_size, num, text

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="clusters",
        glob_pattern="assembly/polishing/intermediate/cluster/*/*.clusters.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        input_schema={"sample": pl.Utf8, "cluster": pl.Utf8, "centroid": pl.Utf8},
    ),
    # Read for the file names only: one JSON per kept cluster. A separator the
    # files never hold keeps each line in one column, whatever its content.
    RecipeSource(
        ref="kept",
        glob_pattern="assembly/polishing/intermediate/cluster/*/*_cluster.json",
        format="csv",
        read_kwargs={
            "has_header": False,
            "separator": "\x1f",
            "quote_char": None,
            "infer_schema_length": 0,
        },
        source_path="source_path",
        input_schema={"source_path": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "cluster": pl.Utf8,
    "taxid": pl.Utf8,
    "centroid": pl.Utf8,
    "cluster_type": pl.Utf8,
    "members": pl.Int64,
    "member_bp": pl.Int64,
    "read_depth_pct": pl.Float64,
    "member_ids": pl.Utf8,
    "status": pl.Utf8,
}

_KEPT = re.compile(r"_(?P<cluster>[^_/]+)_cluster\.json$")


def _member_bp(members: str | None) -> int | None:
    if not members:
        return None
    sizes = [contig_size(m.strip()) for m in members.split(",") if m.strip()]
    known = [s for s in sizes if s is not None]
    return sum(known) if known else None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["clusters"]
    depth_cols = [c for c in df.columns if c.startswith("cumulative read depth")]
    depth = (
        pl.sum_horizontal([num(df, c).fill_null(0.0) for c in depth_cols]).round(2)
        if depth_cols
        else pl.lit(None, dtype=pl.Float64)
    )
    out = df.select(
        text(df, "sample").alias("sample"),
        text(df, "cluster").alias("cluster"),
        text(df, "taxon-id").str.replace(r"\.0$", "").alias("taxid"),
        text(df, "centroid").alias("centroid"),
        num(df, "number of members", pl.Int64).alias("members"),
        text(df, "members").alias("member_ids"),
        depth.alias("read_depth_pct"),
    )
    out = out.with_columns(
        pl.col("member_ids").map_elements(_member_bp, return_dtype=pl.Int64).alias("member_bp"),
        pl.when(
            pl.col("centroid").map_elements(
                lambda c: contig_assembler(c) is not None, return_dtype=pl.Boolean
            )
        )
        .then(pl.lit("Contig-only"))
        .otherwise(pl.lit("Reference-anchored"))
        .alias("cluster_type"),
    )
    kept: set[tuple[str, str]] = set()
    for path in sources["kept"]["source_path"].unique().to_list():
        p = PurePosixPath(path)
        m = _KEPT.search(p.name)
        if m:
            kept.add((p.parent.name, m.group("cluster")))
    out = out.with_columns(
        pl.struct("sample", "cluster")
        .map_elements(
            lambda r: "Refined" if (r["sample"], r["cluster"]) in kept else "Filtered out",
            return_dtype=pl.Utf8,
        )
        .alias("status")
    )
    return (
        out.filter(pl.col("sample").is_not_null() & pl.col("cluster").is_not_null())
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .unique(subset=["sample", "cluster"], keep="first")
        .sort(["sample", "cluster"])
    )
