"""Read QC of nf-core/hlatyping: one row per sample and read file.

hlatyping runs FastQC on every read file it types (a BAM input is first turned
back into FASTQ by ``samtools collate``), and MultiQC writes FastQC's numbers to
``multiqc_data/multiqc_fastqc.txt``: one row per read file, named
``<sample>_1`` / ``<sample>_2`` (paired-end) or ``<sample>`` (single-end). The
yara mapping to the HLA reference publishes BAMs only, no statistics, so the
read count the typing rests on is OptiType's own: the reads its genotype
explains (``Reads`` of the result table, through the ``optitype_summary``
collection).

Per read file: the reads, GC content, duplicate share and mean length, how many
FastQC modules fail or warn and the worst status, and, per sample, the reads
OptiType explains with their share of the sequenced read pairs (the reads of
the largest read file, so a paired-end sample is not counted twice). Every
column of the sample hub is joined on the sample, so ``{GROUP_COL}`` colours the
read files like the samples.

Sources:
    fastqc   multiqc/multiqc_data/multiqc_fastqc.txt (MultiQC's FastQC table)
    samples  the sample hub (dc_ref), to attach each read file to its sample
    typing   the OptiType summary (dc_ref, optional): the reads it explains

Output (hub columns follow):
    read_key, sample, read : Utf8
    total_sequences : Int64     reads in the file
    pct_gc, pct_duplicates, mean_length : Float64
    fastqc_fail, fastqc_warn : Int64
    fastqc_status : Utf8        Fail, Warn or Pass: the worst FastQC module
    typing_reads : Int64        reads OptiType's genotype explains (the sample's)
    typing_share : Float64      typing_reads over the sample's read pairs, 0 to 1
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="fastqc",
        input_schema={"Sample": pl.Utf8, "Total Sequences": pl.Utf8},
        path="multiqc/multiqc_data/multiqc_fastqc.txt",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(ref="samples", dc_ref="samples", input_schema={"sample": pl.Utf8}),
    RecipeSource(ref="typing", dc_ref="optitype_summary", optional=True),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "read_key": pl.Utf8,
    "sample": pl.Utf8,
    "read": pl.Utf8,
    "total_sequences": pl.Int64,
    "pct_gc": pl.Float64,
    "pct_duplicates": pl.Float64,
    "mean_length": pl.Float64,
    "fastqc_fail": pl.Int64,
    "fastqc_warn": pl.Int64,
    "fastqc_status": pl.Utf8,
    "typing_reads": pl.Int64,
    "typing_share": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

#: FastQC's module columns in MultiQC's table, each pass / warn / fail.
_MODULES = (
    "basic_statistics",
    "per_base_sequence_quality",
    "per_tile_sequence_quality",
    "per_sequence_quality_scores",
    "per_base_sequence_content",
    "per_sequence_gc_content",
    "per_base_n_content",
    "sequence_length_distribution",
    "sequence_duplication_levels",
    "overrepresented_sequences",
    "adapter_content",
)
_READ_LABELS = {"1": "Read 1", "2": "Read 2"}


def attach(name: str, hubs: set[str]) -> tuple[str, str]:
    """``(sample, read)`` of a FastQC sample name, against the hub's samples.

    ``<sample>_1`` / ``_2`` is a read of ``<sample>`` when ``<sample>`` is a hub
    id; a hub id itself is a single-end file. Otherwise the longest hub id the
    name starts with (at ``_``, ``.`` or ``-``) owns it, and a name no hub id
    claims is kept as its own sample.
    """
    base, _, suffix = name.rpartition("_")
    if suffix in _READ_LABELS and base in hubs:
        return base, _READ_LABELS[suffix]
    if name in hubs:
        return name, "Single-end"
    owners = [h for h in hubs if name.startswith(h) and name[len(h) : len(h) + 1] in "_.-"]
    if owners:
        owner = max(owners, key=len)
        return owner, name[len(owner) + 1 :] or "Single-end"
    if suffix in _READ_LABELS and base:
        return base, _READ_LABELS[suffix]
    return name, "Single-end"


def _float(column: str, df: pl.DataFrame) -> pl.Expr:
    if column not in df.columns:
        return pl.lit(None, dtype=pl.Float64)
    return pl.col(column).cast(pl.Float64, strict=False)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    fastqc = sources["fastqc"]
    hub = sources["samples"]
    hubs = set(hub["sample"].drop_nulls().to_list())

    names = [str(n).strip() for n in fastqc["Sample"].to_list()]
    owners = [attach(n, hubs) for n in names]
    modules = [c for c in _MODULES if c in fastqc.columns]
    status = [pl.col(c).str.strip_chars().str.to_lowercase() for c in modules]

    def tally(word: str) -> pl.Expr:
        if not status:
            return pl.lit(None, dtype=pl.Int64)
        return pl.sum_horizontal([(s == word).cast(pl.Int64) for s in status])

    reads = fastqc.select(
        pl.Series("read_key", names, dtype=pl.Utf8),
        pl.Series("sample", [o[0] for o in owners], dtype=pl.Utf8),
        pl.Series("read", [o[1] for o in owners], dtype=pl.Utf8),
        _float("Total Sequences", fastqc).round(0).cast(pl.Int64).alias("total_sequences"),
        _float("%GC", fastqc).alias("pct_gc"),
        (100.0 - _float("total_deduplicated_percentage", fastqc)).round(2).alias("pct_duplicates"),
        _float("avg_sequence_length", fastqc).alias("mean_length"),
        tally("fail").alias("fastqc_fail"),
        tally("warn").alias("fastqc_warn"),
    ).with_columns(
        pl.when(pl.col("fastqc_fail") > 0)
        .then(pl.lit("Fail"))
        .when(pl.col("fastqc_warn") > 0)
        .then(pl.lit("Warn"))
        .when(pl.col("fastqc_fail").is_not_null())
        .then(pl.lit("Pass"))
        .otherwise(None)
        .alias("fastqc_status")
    )

    typing = sources.get("typing")
    if typing is not None and {"sample_id", "reads"} <= set(typing.columns):
        typed = typing.select(
            pl.col("sample_id").alias("sample"),
            pl.col("reads").cast(pl.Int64).alias("typing_reads"),
        )
    else:
        typed = pl.DataFrame(schema={"sample": pl.Utf8, "typing_reads": pl.Int64})
    pairs = reads.group_by("sample").agg(pl.col("total_sequences").max().alias("_pairs"))
    reads = (
        reads.join(typed, on="sample", how="left")
        .join(pairs, on="sample", how="left")
        .with_columns(
            pl.when(pl.col("_pairs") > 0)
            .then((pl.col("typing_reads") / pl.col("_pairs")).round(4))
            .otherwise(None)
            .alias("typing_share")
        )
        .drop("_pairs")
    )
    # The sample's design columns; its input file names stay on the hub.
    hub_cols = [
        c for c in hub.columns if c not in ("sample", "input_files") and c not in reads.columns
    ]
    out = reads.join(hub.select(["sample", *hub_cols]), on="sample", how="left")
    lead = list(OUTPUT_SCHEMA)
    return out.select(lead + [c for c in out.columns if c not in lead]).sort("read_key")
