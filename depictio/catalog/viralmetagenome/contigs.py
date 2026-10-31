"""One row per de novo contig: its length, its reads, its taxonomic call and its cluster.

viralmetagenome maps each sample's reads back to its own assembly and publishes
``samtools idxstats`` per assembler:
``assembly/assemblers/<assembler>/idxstats/[<prefix>-]<sample>_<assembler>.idxstats``
(contig, length, mapped reads, unmapped reads; no header). The sample is the
file name without the run prefix and the assembler suffix.

Two optional collections complete the row when the run wrote them:

* ``vmg_contig_classes`` (``viralmetagenome/contig_classes``), the merged
  Kraken2 and Kaiju call of each contig; a run with ``--skip_precluster`` has
  none and every contig reads ``Not classified``;
* ``vmg_clusters`` (``viralmetagenome/clusters``), the cluster each contig was
  put in, as a member or as its centroid; a contig in no cluster was dropped
  before clustering (``--min_contig_size``, ``--max_n_perc``).

Output schema:
    sample : Utf8           sample id
    assembler : Utf8        assembler that built the contig
    contig : Utf8           contig id as the assembler named it
    length_bp : Int64       contig length, bp
    length_class : Utf8     length band (under 500 bp, 500 bp to 1 kb, 1 to 5 kb, 5 to 10 kb, over 10 kb)
    mapped_reads : Int64    reads of the sample that map to the contig
    read_share_pct : Float64  mapped reads over all reads mapped to the sample's contigs, percent
    reads_per_kb : Float64  mapped reads per kb of contig, a depth proxy
    classification : Utf8   Classified, Unclassified, or Not classified when the step did not run
    taxid : Utf8            taxon id of the merged call
    cluster : Utf8          cluster the contig belongs to, null when it was left out
    cluster_role : Utf8     Centroid, Member or Not clustered
"""

from __future__ import annotations

from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.viralmetagenome import strip_global_prefix

CLASSES_DC_TAG = "vmg_contig_classes"
CLUSTERS_DC_TAG = "vmg_clusters"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="idxstats",
        glob_pattern="assembly/assemblers/*/idxstats/*.idxstats",
        format="tsv",
        read_kwargs={"has_header": False, "infer_schema_length": 0, "quote_char": None},
        source_path="source_path",
        input_schema={
            "column_1": pl.Utf8,
            "column_2": pl.Utf8,
            "column_3": pl.Utf8,
            "source_path": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="classes",
        dc_ref=CLASSES_DC_TAG,
        optional=True,
        input_schema={"sample": pl.Utf8, "contig": pl.Utf8, "classification": pl.Utf8},
    ),
    RecipeSource(
        ref="clusters",
        dc_ref=CLUSTERS_DC_TAG,
        optional=True,
        input_schema={"sample": pl.Utf8, "cluster": pl.Utf8, "centroid": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "assembler": pl.Utf8,
    "contig": pl.Utf8,
    "length_bp": pl.Int64,
    "length_class": pl.Utf8,
    "mapped_reads": pl.Int64,
    "read_share_pct": pl.Float64,
    "reads_per_kb": pl.Float64,
    "classification": pl.Utf8,
    "taxid": pl.Utf8,
    "cluster": pl.Utf8,
    "cluster_role": pl.Utf8,
}

LENGTH_CLASSES = ["under 500 bp", "500 bp to 1 kb", "1 to 5 kb", "5 to 10 kb", "over 10 kb"]


def _sample_and_assembler(path: str) -> tuple[str, str]:
    p = PurePosixPath(path)
    assembler = p.parent.parent.name if p.parent.name == "idxstats" else ""
    stem = strip_global_prefix(p.name.removesuffix(".idxstats"))
    if assembler and stem.endswith(f"_{assembler}"):
        stem = stem[: -len(assembler) - 1]
    return stem, assembler or "assembly"


def _length_class(length: pl.Expr) -> pl.Expr:
    return (
        pl.when(length < 500)
        .then(pl.lit(LENGTH_CLASSES[0]))
        .when(length < 1000)
        .then(pl.lit(LENGTH_CLASSES[1]))
        .when(length < 5000)
        .then(pl.lit(LENGTH_CLASSES[2]))
        .when(length < 10000)
        .then(pl.lit(LENGTH_CLASSES[3]))
        .otherwise(pl.lit(LENGTH_CLASSES[4]))
    )


def _membership(clusters: pl.DataFrame) -> pl.DataFrame:
    """``(sample, contig, cluster, cluster_role)`` for every clustered contig."""
    rows: list[dict[str, str]] = []
    members_col = "member_ids" if "member_ids" in clusters.columns else None
    for rec in clusters.iter_rows(named=True):
        rows.append(
            {
                "sample": rec["sample"],
                "contig": rec["centroid"],
                "cluster": rec["cluster"],
                "cluster_role": "Centroid",
            }
        )
        for member in (rec.get(members_col) or "").split(",") if members_col else []:
            if member.strip():
                rows.append(
                    {
                        "sample": rec["sample"],
                        "contig": member.strip(),
                        "cluster": rec["cluster"],
                        "cluster_role": "Member",
                    }
                )
    if not rows:
        return pl.DataFrame(
            schema={
                "sample": pl.Utf8,
                "contig": pl.Utf8,
                "cluster": pl.Utf8,
                "cluster_role": pl.Utf8,
            }
        )
    # A centroid listed among the members too keeps its centroid role.
    return (
        pl.DataFrame(rows)
        .with_columns((pl.col("cluster_role") == "Centroid").alias("_c"))
        .sort("_c", descending=True)
        .unique(subset=["sample", "contig"], keep="first")
        .drop("_c")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    idx = sources["idxstats"]
    ids = idx["source_path"].map_elements(
        lambda p: list(_sample_and_assembler(p)), return_dtype=pl.List(pl.Utf8)
    )
    out = idx.select(
        ids.list.get(0).alias("sample"),
        ids.list.get(1).alias("assembler"),
        pl.col("column_1").str.strip_chars().alias("contig"),
        pl.col("column_2").cast(pl.Int64, strict=False).alias("length_bp"),
        pl.col("column_3").cast(pl.Int64, strict=False).alias("mapped_reads"),
    ).filter(pl.col("contig").is_not_null() & (pl.col("contig") != "*"))
    out = out.with_columns(
        _length_class(pl.col("length_bp")).alias("length_class"),
        pl.when(pl.col("mapped_reads").sum().over("sample") > 0)
        .then(
            (pl.col("mapped_reads") * 100.0 / pl.col("mapped_reads").sum().over("sample")).round(2)
        )
        .otherwise(None)
        .alias("read_share_pct"),
        pl.when(pl.col("length_bp") > 0)
        .then((pl.col("mapped_reads") * 1000.0 / pl.col("length_bp")).round(2))
        .otherwise(None)
        .alias("reads_per_kb"),
    )

    classes = sources.get("classes")
    if classes is not None and not classes.is_empty():
        out = out.join(
            classes.select(
                "sample",
                "contig",
                "classification",
                *(["taxid"] if "taxid" in classes.columns else []),
            ),
            on=["sample", "contig"],
            how="left",
        )
    if "classification" not in out.columns:
        out = out.with_columns(pl.lit(None, dtype=pl.Utf8).alias("classification"))
    if "taxid" not in out.columns:
        out = out.with_columns(pl.lit(None, dtype=pl.Utf8).alias("taxid"))
    out = out.with_columns(pl.col("classification").fill_null("Not classified"))

    clusters = sources.get("clusters")
    membership = None
    if clusters is not None and not clusters.is_empty():
        membership = _membership(clusters)
    if membership is not None and not membership.is_empty():
        out = out.join(membership, on=["sample", "contig"], how="left")
    else:
        out = out.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias("cluster"),
            pl.lit(None, dtype=pl.Utf8).alias("cluster_role"),
        )
    out = out.with_columns(pl.col("cluster_role").fill_null("Not clustered"))
    return (
        out.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .unique(subset=["sample", "assembler", "contig"], keep="first")
        .sort(["sample", "assembler", "length_bp"], descending=[False, False, True])
    )
