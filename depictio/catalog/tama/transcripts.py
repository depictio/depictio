"""The TAMA merge transcriptome: one row per isoform, its read support and its class.

TAMA merge writes, per sample, the final transcript models (``<sample>.bed``,
BED12, name ``<gene>;<transcript>``) and ``<sample>_merge.txt``, which lists for
every merged transcript the TAMA collapse models it was built from
(``<transcript>;<collapse bed>_<collapse transcript>``). TAMA collapse, in
turn, reports in ``<prefix>_trans_report.txt`` how many reads each of its models
collapsed (``num_clusters``). Chaining the two gives the number of FLNC reads
behind every final isoform, the long-read equivalent of a count.

Structural category. When a reference annotation is available (the GTF the run
indexed, ``ULTRA_INDEX/genome.gtf`` on the uLTRA route, or any GTF the template
points the ``reference`` source at) every isoform is classified by its splice
junctions, following the SQANTI3 categories:

* ``FSM`` full splice match: the intron chain equals a reference transcript's;
* ``ISM`` incomplete splice match: a contiguous part of a reference chain;
* ``NIC`` novel in catalog: every donor and acceptor is annotated, the
  combination is new;
* ``NNC`` novel not in catalog: at least one donor or acceptor is new, at
  least one is annotated;
* ``genic``: no annotated splice site shared (mono-exonic isoforms included),
  but the isoform overlaps a gene on its strand;
* ``antisense``: overlaps a gene on the other strand only;
* ``intergenic``: overlaps no annotated gene.

Without a reference every isoform is ``unclassified`` and keeps its TAMA gene.
Junction coordinates are compared exactly (TAMA already snapped them to the
reads' consensus within its splice-junction wobble).

Sources:
    bed         ``tama_merge_bed_raw``: the merged BED12 files, scanned by the
                template with ``include_file_paths: source_path`` (a scan regex
                can tell ``<sample>.bed`` from the per-chunk collapse BEDs, a
                glob cannot)
    merge       every ``*_merge.txt`` (merged transcript to collapse models)
    collapse    every per-chunk ``*chunk*_trans_report.txt`` of TAMA collapse
    reference   optional reference GTF (default ``ULTRA_INDEX/genome.gtf``)

The pooled ``all_samples`` annotation (``--tama_merge_all``) is left out: its
isoforms are the per-sample ones merged again, and counting both would double
every number.

Output schema (one row per sample and merged isoform; the isoform, its class and
support first, its position and ids last, so a table reads left to right):
    transcript_id : Utf8         TAMA isoform id, e.g. G12.3 (unique within a sample)
    gene_name : Utf8             reference gene name, else tama_gene_id
    sample : Utf8                sample (the TAMA merge file prefix)
    structural_category : Utf8   FSM, ISM, NIC, NNC, genic, antisense, intergenic, unclassified
    exon_structure : Utf8        mono-exon or multi-exon
    read_support : Int64         FLNC reads collapsed into the isoform
    transcript_length : Int64    summed exon length, bp
    exons : Int64                exon count
    junctions : Int64            splice junctions (exons - 1)
    known_junctions : Int64      junctions annotated in the reference (0 without one)
    chrom : Utf8                 sequence
    start : Int64                first base, 1-based
    end : Int64                  last base, inclusive
    strand : Utf8                + or -
    ref_transcript_id : Utf8     reference transcript matched (FSM / ISM only)
    source_models : Int64        TAMA collapse models merged into it
    gene_id : Utf8               reference gene, else ``<sample>:<tama_gene_id>``
    tama_gene_id : Utf8          TAMA gene id, e.g. G12
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "tama_merge_bed_raw"

#: Columns the raw BED scan declares, in order (``new_columns`` of the template).
BED_COLUMNS = [
    "chrom",
    "chrom_start",
    "chrom_end",
    "name",
    "score",
    "strand",
    "thick_start",
    "thick_end",
    "item_rgb",
    "block_count",
    "block_sizes",
    "block_starts",
]

_GTF_READ = {
    "has_header": False,
    "comment_prefix": "#",
    "quote_char": None,
    "columns": [0, 2, 3, 4, 6, 8],
    "new_columns": ["seqname", "feature", "start", "end", "strand", "attributes"],
    "infer_schema_length": 0,
    "truncate_ragged_lines": True,
}

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="bed", dc_ref=RAW_DC_TAG),
    RecipeSource(
        ref="merge",
        glob_pattern="**/*_merge.txt",
        format="tsv",
        read_kwargs={
            "has_header": False,
            "quote_char": None,
            "new_columns": BED_COLUMNS,
            "infer_schema_length": 0,
        },
        source_path="source_path",
    ),
    RecipeSource(
        ref="collapse",
        glob_pattern="**/*chunk*_trans_report.txt",
        format="tsv",
        read_kwargs={"columns": ["transcript_id", "num_clusters"], "infer_schema_length": 0},
        source_path="source_path",
    ),
    RecipeSource(
        ref="reference",
        path="ULTRA_INDEX/genome.gtf",
        format="tsv",
        read_kwargs=_GTF_READ,
        optional=True,
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "transcript_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "sample": pl.Utf8,
    "structural_category": pl.Utf8,
    "exon_structure": pl.Utf8,
    "read_support": pl.Int64,
    "transcript_length": pl.Int64,
    "exons": pl.Int64,
    "junctions": pl.Int64,
    "known_junctions": pl.Int64,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "strand": pl.Utf8,
    "ref_transcript_id": pl.Utf8,
    "source_models": pl.Int64,
    "gene_id": pl.Utf8,
    "tama_gene_id": pl.Utf8,
}

POOLED = "all_samples"
_BIN = 100_000
_KEY = ["sample", "transcript_id"]
_LOC = ["chrom", "strand"]


def _basename(col: str) -> pl.Expr:
    return pl.col(col).str.split("/").list.last()


# ---------------------------------------------------------------------------
# Query isoforms (TAMA merge BED12)
# ---------------------------------------------------------------------------


def merged_models(bed: pl.DataFrame) -> pl.DataFrame:
    """One row per merged isoform, with its exon starts / ends as lists (1-based)."""
    missing = [c for c in [*BED_COLUMNS, "source_path"] if c not in bed.columns]
    if missing:
        raise ValueError(f"TAMA merge BED scan: missing column(s) {missing}")
    name = _basename("source_path")
    frame = (
        bed.filter(~name.str.contains(r"_(collapsed|trans_read)\.bed$"))
        .with_columns(name.str.replace(r"\.bed$", "").alias("sample"))
        .filter(pl.col("sample") != POOLED)
        .filter(pl.col("name").is_not_null() & pl.col("chrom_start").is_not_null())
    )
    parts = pl.col("name").str.split(";")
    return frame.select(
        "sample",
        parts.list.get(0, null_on_oob=True).alias("tama_gene_id"),
        parts.list.get(-1, null_on_oob=True).alias("transcript_id"),
        pl.col("chrom").cast(pl.Utf8),
        pl.col("strand").cast(pl.Utf8),
        pl.col("chrom_start").cast(pl.Int64).alias("_cs"),
        pl.col("block_sizes").str.strip_chars(",").str.split(",").alias("_sizes"),
        pl.col("block_starts").str.strip_chars(",").str.split(",").alias("_starts"),
    ).unique(subset=_KEY, keep="first")


def query_exons(models: pl.DataFrame) -> pl.DataFrame:
    """One row per exon of every isoform, 1-based inclusive."""
    return (
        models.explode(["_sizes", "_starts"])
        .with_columns(
            (pl.col("_cs") + pl.col("_starts").cast(pl.Int64) + 1).alias("exon_start"),
            (
                pl.col("_cs") + pl.col("_starts").cast(pl.Int64) + pl.col("_sizes").cast(pl.Int64)
            ).alias("exon_end"),
        )
        .select(*_KEY, "tama_gene_id", *_LOC, "exon_start", "exon_end")
        .sort(*_KEY, "exon_start")
    )


def introns(exons: pl.DataFrame, key: list[str]) -> pl.DataFrame:
    """Introns between consecutive exons of each transcript (``key``), 1-based inclusive."""
    return (
        exons.sort(*key, "exon_start")
        .with_columns(
            (pl.col("exon_end") + 1).alias("i_start"),
            (pl.col("exon_start").shift(-1).over(key) - 1).alias("i_end"),
        )
        .drop_nulls("i_end")
        .filter(pl.col("i_end") >= pl.col("i_start"))
        .select(*key, *_LOC, "i_start", "i_end")
    )


def chains(intr: pl.DataFrame, key: list[str]) -> pl.DataFrame:
    """The intron chain of each transcript as one comparable string."""
    return (
        intr.sort(*key, "i_start")
        .group_by(*key, *_LOC, maintain_order=True)
        .agg(pl.concat_str(["i_start", "i_end"], separator="-").str.join(",").alias("chain"))
        .with_columns(("," + pl.col("chain") + ",").alias("chain"))
    )


# ---------------------------------------------------------------------------
# Reference annotation (GTF)
# ---------------------------------------------------------------------------


def _attr(key: str) -> pl.Expr:
    return pl.col("attributes").str.extract(rf'{key} "([^"]*)"', 1)


def reference_exons(gtf: pl.DataFrame) -> pl.DataFrame:
    """Reference exons with their transcript, gene and gene name."""
    exons = gtf.filter(pl.col("feature") == "exon").select(
        _attr("transcript_id").alias("rid"),
        _attr("gene_id").alias("ref_gene_id"),
        pl.coalesce(_attr("gene_name"), _attr("gene_id")).alias("ref_gene_name"),
        pl.col("seqname").cast(pl.Utf8).alias("chrom"),
        pl.col("strand").cast(pl.Utf8),
        pl.col("start").cast(pl.Int64, strict=False).alias("exon_start"),
        pl.col("end").cast(pl.Int64, strict=False).alias("exon_end"),
    )
    return exons.drop_nulls(["rid", "ref_gene_id", "exon_start", "exon_end"])


def _overlap_genes(spans: pl.DataFrame, genes: pl.DataFrame) -> pl.DataFrame:
    """(query key, gene, same_strand, overlap bp) for every overlapping gene, via 100 kb bins."""

    def binned(frame: pl.DataFrame) -> pl.DataFrame:
        return frame.with_columns(
            pl.int_ranges(pl.col("start") // _BIN, pl.col("end") // _BIN + 1).alias("_bin")
        ).explode("_bin")

    q = binned(spans)
    g = binned(genes).rename({"start": "g_start", "end": "g_end", "strand": "g_strand"})
    pairs = (
        q.join(g, on=["chrom", "_bin"])
        .filter((pl.col("start") <= pl.col("g_end")) & (pl.col("end") >= pl.col("g_start")))
        .unique(subset=[*_KEY, "ref_gene_id"])
    )
    return pairs.select(
        *_KEY,
        "ref_gene_id",
        (pl.col("strand") == pl.col("g_strand")).alias("same_strand"),
        (pl.min_horizontal("end", "g_end") - pl.max_horizontal("start", "g_start") + 1).alias(
            "overlap"
        ),
    )


def classify(exons: pl.DataFrame, spans: pl.DataFrame, ref: pl.DataFrame) -> pl.DataFrame:
    """(sample, transcript_id) -> category, reference gene / transcript, known junctions."""
    q_intr = introns(exons, _KEY)
    r_intr = introns(ref, ["rid"])
    q_chain = chains(q_intr, _KEY)
    r_chain = chains(r_intr, ["rid"]).rename({"chain": "r_chain"})
    rid_gene = ref.select("rid", "ref_gene_id").unique(subset="rid")

    # FSM: the whole chain is a reference chain.
    fsm = (
        q_chain.join(r_chain, left_on=[*_LOC, "chain"], right_on=[*_LOC, "r_chain"])
        .sort("rid")
        .unique(subset=_KEY, keep="first")
        .select(*_KEY, "rid", pl.lit("FSM").alias("category"))
    )
    # ISM: a contiguous run of a reference chain sharing the query's first intron.
    first = q_intr.sort(*_KEY, "i_start").unique(subset=_KEY, keep="first")
    candidates = first.join(r_intr, on=[*_LOC, "i_start", "i_end"]).select(*_KEY, "rid").unique()
    ism = (
        candidates.join(q_chain.select(*_KEY, "chain"), on=_KEY)
        .join(r_chain.select("rid", "r_chain"), on="rid")
        .filter(pl.col("r_chain").str.contains(pl.col("chain"), literal=True))
        .join(fsm.select(_KEY), on=_KEY, how="anti")
        .sort("rid")
        .unique(subset=_KEY, keep="first")
        .select(*_KEY, "rid", pl.lit("ISM").alias("category"))
    )
    matched = pl.concat([fsm, ism]).join(rid_gene, on="rid", how="left")

    # Splice sites and junctions known to the reference.
    r_sites = (
        pl.concat(
            [
                r_intr.select(
                    *_LOC, pl.col("i_start").alias("pos"), pl.lit("d").alias("kind"), "rid"
                ),
                r_intr.select(
                    *_LOC, pl.col("i_end").alias("pos"), pl.lit("a").alias("kind"), "rid"
                ),
            ]
        )
        .join(rid_gene, on="rid")
        .select(*_LOC, "pos", "kind", "ref_gene_id")
        .unique()
    )
    q_sites = pl.concat(
        [
            q_intr.select(*_KEY, *_LOC, pl.col("i_start").alias("pos"), pl.lit("d").alias("kind")),
            q_intr.select(*_KEY, *_LOC, pl.col("i_end").alias("pos"), pl.lit("a").alias("kind")),
        ]
    )
    site_hits = q_sites.join(r_sites, on=[*_LOC, "pos", "kind"], how="left")
    known_sites = (
        site_hits.group_by(*_KEY, *_LOC, "pos", "kind")
        .agg(pl.col("ref_gene_id").is_not_null().any().alias("_known"))
        .group_by(_KEY)
        .agg(pl.len().alias("_sites"), pl.col("_known").sum().alias("_known_sites"))
    )
    site_gene = (
        site_hits.drop_nulls("ref_gene_id")
        .group_by(*_KEY, "ref_gene_id")
        .agg(pl.len().alias("_n"))
        .sort(*_KEY, "_n", "ref_gene_id", descending=[False, False, True, False])
        .unique(subset=_KEY, keep="first")
        .select(*_KEY, pl.col("ref_gene_id").alias("_site_gene"))
    )
    known_junctions = (
        q_intr.join(
            r_intr.select(*_LOC, "i_start", "i_end").unique(), on=[*_LOC, "i_start", "i_end"]
        )
        .group_by(_KEY)
        .agg(pl.len().cast(pl.Int64).alias("known_junctions"))
    )

    # Gene overlap, for isoforms that share no splice site with the reference.
    genes = ref.group_by("ref_gene_id").agg(
        pl.col("chrom").first(),
        pl.col("strand").first(),
        pl.col("exon_start").min().alias("start"),
        pl.col("exon_end").max().alias("end"),
    )
    overlaps = _overlap_genes(spans.select(*_KEY, *_LOC, "start", "end"), genes)
    best = lambda same: (  # noqa: E731
        overlaps.filter(pl.col("same_strand") == same)
        .sort(*_KEY, "overlap", "ref_gene_id", descending=[False, False, True, False])
        .unique(subset=_KEY, keep="first")
    )
    sense = best(True).select(*_KEY, pl.col("ref_gene_id").alias("_sense_gene"))
    anti = best(False).select(*_KEY, pl.col("ref_gene_id").alias("_anti_gene"))

    out = (
        spans.select(_KEY)
        .join(
            matched.select(*_KEY, "rid", "category", pl.col("ref_gene_id").alias("_match_gene")),
            on=_KEY,
            how="left",
        )
        .join(known_sites, on=_KEY, how="left")
        .join(site_gene, on=_KEY, how="left")
        .join(known_junctions, on=_KEY, how="left")
        .join(sense, on=_KEY, how="left")
        .join(anti, on=_KEY, how="left")
    )
    has_sites = pl.col("_sites").fill_null(0) > 0
    known = pl.col("_known_sites").fill_null(0)
    category = (
        pl.when(pl.col("category").is_not_null())
        .then(pl.col("category"))
        .when(has_sites & (known == pl.col("_sites")))
        .then(pl.lit("NIC"))
        .when(has_sites & (known > 0))
        .then(pl.lit("NNC"))
        .when(pl.col("_sense_gene").is_not_null())
        .then(pl.lit("genic"))
        .when(pl.col("_anti_gene").is_not_null())
        .then(pl.lit("antisense"))
        .otherwise(pl.lit("intergenic"))
    )
    gene = (
        pl.when(pl.col("category").is_not_null())
        .then(pl.col("_match_gene"))
        .when(has_sites & (known > 0))
        .then(pl.col("_site_gene"))
        .when(pl.col("_sense_gene").is_not_null())
        .then(pl.col("_sense_gene"))
        .otherwise(pl.col("_anti_gene"))
    )
    return out.select(
        *_KEY,
        category.alias("structural_category"),
        gene.alias("ref_gene_id"),
        pl.col("rid").alias("ref_transcript_id"),
        pl.col("known_junctions").fill_null(0).cast(pl.Int64),
    )


# ---------------------------------------------------------------------------
# Read support
# ---------------------------------------------------------------------------


def read_support(merge: pl.DataFrame, collapse: pl.DataFrame) -> pl.DataFrame:
    """(sample, transcript_id) -> FLNC reads and collapse models merged into it."""
    parts = pl.col("name").str.splitn(";", 2)
    members = merge.select(
        _basename("source_path").str.replace(r"_merge\.txt$", "").alias("sample"),
        parts.struct.field("field_0").alias("transcript_id"),
        parts.struct.field("field_1").alias("_member"),
    ).drop_nulls("_member")
    prefix = _basename("source_path").str.replace(r"_trans_report\.txt$", "")
    counts = collapse.select(
        (prefix + "_collapsed.bed_" + pl.col("transcript_id")).alias("_member"),
        pl.col("num_clusters").cast(pl.Int64, strict=False).alias("_reads"),
    ).unique(subset="_member", keep="first")
    return (
        members.join(counts, on="_member", how="left")
        .group_by(_KEY)
        .agg(
            pl.col("_reads").sum().cast(pl.Int64).alias("read_support"),
            pl.len().cast(pl.Int64).alias("source_models"),
        )
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    models = merged_models(sources["bed"])
    if models.is_empty():
        raise ValueError("TAMA merge: no merged isoform in the scanned BED files")
    exons = query_exons(models)
    spans = exons.group_by(*_KEY, "tama_gene_id", *_LOC).agg(
        pl.col("exon_start").min().alias("start"),
        pl.col("exon_end").max().alias("end"),
        pl.len().cast(pl.Int64).alias("exons"),
        (pl.col("exon_end") - pl.col("exon_start") + 1)
        .sum()
        .cast(pl.Int64)
        .alias("transcript_length"),
    )
    reference = sources.get("reference")
    if reference is not None and not reference.is_empty():
        ref = reference_exons(reference)
        classes = classify(exons, spans, ref)
        names = ref.select("ref_gene_id", "ref_gene_name").unique(subset="ref_gene_id")
        classes = classes.join(names, on="ref_gene_id", how="left")
    else:
        classes = spans.select(
            *_KEY,
            pl.lit("unclassified").alias("structural_category"),
            pl.lit(None, dtype=pl.Utf8).alias("ref_gene_id"),
            pl.lit(None, dtype=pl.Utf8).alias("ref_transcript_id"),
            pl.lit(0, dtype=pl.Int64).alias("known_junctions"),
            pl.lit(None, dtype=pl.Utf8).alias("ref_gene_name"),
        )
    support = read_support(sources["merge"], sources["collapse"])
    out = (
        spans.join(classes, on=_KEY, how="left")
        .join(support, on=_KEY, how="left")
        .with_columns(
            pl.coalesce("ref_gene_id", pl.col("sample") + ":" + pl.col("tama_gene_id")).alias(
                "gene_id"
            ),
            pl.coalesce("ref_gene_name", "tama_gene_id").alias("gene_name"),
            pl.when(pl.col("exons") > 1)
            .then(pl.lit("multi-exon"))
            .otherwise(pl.lit("mono-exon"))
            .alias("exon_structure"),
            (pl.col("exons") - 1).cast(pl.Int64).alias("junctions"),
            pl.col("read_support").fill_null(0).cast(pl.Int64),
            pl.col("source_models").fill_null(0).cast(pl.Int64),
            pl.col("structural_category").fill_null("unclassified"),
        )
    )
    return out.sort("sample", "chrom", "start", "transcript_id").select(list(EXPECTED_SCHEMA))
