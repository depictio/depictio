"""Which ORFs each caller found: one row per ORF, pooled over the libraries.

Ribo-TISH and RiboCode detect translated ORFs from different signals
(initiation peaks and frame test for Ribo-TISH, P-site periodicity for
RiboCode), so an ORF both report is better supported than one only a single
caller sees. The two catalog recipes key every ORF by its genomic stop codon
(``orf_id``), which makes the calls comparable even when the callers chose
different starts or transcripts.

Membership columns (0/1, the UpSet sets):
    ribotish       reported by Ribo-TISH in at least one library
    ribocode       reported by RiboCode in at least one library
    annotated_cds  either caller classed it as the annotated CDS, so the
                   intersections separate known coding sequences from new ORFs

Sources: the ``ribotish_orfs`` and ``ribocode_orfs`` data collections; either
may be absent.

Output: see ``OUTPUT_SCHEMA``. ``orf_class`` is RiboCode's class when
RiboCode called the ORF, else Ribo-TISH's.

Where the ORF sits (``chrom``, ``orf_start``, ``orf_end``): the key carries the
contig and the stop-codon coordinate, and the protein length says how far the
ORF reaches back from it (3 bases per amino acid, upstream of the stop on its
strand). The span is approximate (an ORF split over exons covers more of the
genome than that), which is what the genome browser needs to frame it.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="ribotish",
        input_schema={
            "sample": pl.Utf8,
            "orf_id": pl.Utf8,
            "gene_id": pl.Utf8,
            "gene_name": pl.Utf8,
            "gene_type": pl.Utf8,
            "orf_class": pl.Utf8,
            "aa_length": pl.Int64,
        },
        dc_ref="ribotish_orfs",
        optional=True,
    ),
    RecipeSource(
        ref="ribocode",
        input_schema={
            "sample": pl.Utf8,
            "orf_id": pl.Utf8,
            "gene_id": pl.Utf8,
            "gene_name": pl.Utf8,
            "gene_type": pl.Utf8,
            "orf_class": pl.Utf8,
            "aa_length": pl.Int64,
        },
        dc_ref="ribocode_orfs",
        optional=True,
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "orf_id": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "gene_type": pl.Utf8,
    "orf_class": pl.Utf8,
    "aa_length": pl.Int64,
    "chrom": pl.Utf8,
    "orf_start": pl.Int64,
    "orf_end": pl.Int64,
    "ribotish": pl.Int64,
    "ribocode": pl.Int64,
    "annotated_cds": pl.Int64,
    "ribotish_libraries": pl.Int64,
    "ribocode_libraries": pl.Int64,
}

# `<chrom>:<strand>:<stop>`, the key the two callers' recipes build. The contig
# may itself hold a colon (an HLA allele), so it is everything before the last two.
_ORF_KEY = r"^(?P<chrom>.+):(?P<strand>[+-]):(?P<stop>\d+)$"

_KEEP = ["orf_id", "gene_id", "gene_name", "gene_type", "orf_class", "aa_length"]


def _pool(df: pl.DataFrame | None, name: str) -> pl.DataFrame:
    if df is None or df.is_empty():
        return pl.DataFrame(
            schema={
                **{c: pl.Utf8 for c in _KEEP if c != "aa_length"},
                "aa_length": pl.Int64,
                f"{name}_libraries": pl.Int64,
            }
        ).select(*_KEEP, f"{name}_libraries")
    return df.group_by("orf_id").agg(
        pl.col("gene_id").first().cast(pl.Utf8),
        pl.col("gene_name").first().cast(pl.Utf8),
        pl.col("gene_type").first().cast(pl.Utf8),
        # The class seen in most libraries, ties broken alphabetically.
        pl.col("orf_class").mode().sort().first().cast(pl.Utf8),
        pl.col("aa_length").max().cast(pl.Int64),
        pl.col("sample").n_unique().cast(pl.Int64).alias(f"{name}_libraries"),
    )


def _locus(orf_id: pl.Expr, aa_length: pl.Expr) -> list[pl.Expr]:
    """Contig and approximate genomic span of an ORF, from its key and protein length."""
    key = orf_id.str.extract_groups(_ORF_KEY)
    strand = key.struct.field("strand")
    stop = key.struct.field("stop").cast(pl.Int64)
    reach = aa_length.fill_null(0).cast(pl.Int64) * 3
    return [
        key.struct.field("chrom").alias("chrom"),
        pl.when(strand == "+")
        .then((stop - reach).clip(lower_bound=1))
        .otherwise(stop)
        .cast(pl.Int64)
        .alias("orf_start"),
        pl.when(strand == "+").then(stop).otherwise(stop + reach).cast(pl.Int64).alias("orf_end"),
    ]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Outer join of the two callers' ORF sets on the stop-codon key."""
    tish = _pool(sources.get("ribotish"), "ribotish")
    code = _pool(sources.get("ribocode"), "ribocode")
    joined = code.join(tish, on="orf_id", how="full", coalesce=True, suffix="_tish")
    out = joined.select(
        pl.col("orf_id"),
        pl.coalesce("gene_id", "gene_id_tish").alias("gene_id"),
        pl.coalesce("gene_name", "gene_name_tish").alias("gene_name"),
        pl.coalesce("gene_type", "gene_type_tish").alias("gene_type"),
        pl.coalesce("orf_class", "orf_class_tish").alias("orf_class"),
        pl.max_horizontal("aa_length", "aa_length_tish").cast(pl.Int64).alias("aa_length"),
        (pl.col("ribotish_libraries").fill_null(0) > 0).cast(pl.Int64).alias("ribotish"),
        (pl.col("ribocode_libraries").fill_null(0) > 0).cast(pl.Int64).alias("ribocode"),
        ((pl.col("orf_class") == "Annotated CDS") | (pl.col("orf_class_tish") == "Annotated CDS"))
        .fill_null(False)
        .cast(pl.Int64)
        .alias("annotated_cds"),
        pl.col("ribotish_libraries").fill_null(0).cast(pl.Int64),
        pl.col("ribocode_libraries").fill_null(0).cast(pl.Int64),
    )
    out = out.with_columns(_locus(pl.col("orf_id"), pl.col("aa_length")))
    return out.sort("orf_id").select(list(OUTPUT_SCHEMA))
