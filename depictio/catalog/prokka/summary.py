"""One row per annotated genome, from Prokka's `.txt` feature counts.

Prokka writes a short `key: value` file beside every annotation::

    organism: Genus species strain
    contigs: 28
    bases: 2137271
    CDS: 1810
    gene: 1864
    tRNA: 53
    tmRNA: 1

with a line per feature class it actually found, so `rRNA` and `tmRNA` are
present on some bins and absent on others. The recipe pivots those lines into
one row per bin and fills the classes a bin has none of with 0 rather than with
null: "this bin has no rRNA" is a finding, not a missing measurement, and it is
the finding MIMAG turns on.

`meets_mimag_rna` applies the RNA half of the MIMAG high-quality draft
definition (Table 1 of Bowers et al. 2017, Nat Biotechnol 35:725,
https://doi.org/10.1038/nbt.3893): the 5S, 16S and 23S rRNA genes each present
and at least 18 tRNAs. The `.txt` file only counts rRNA features, so it cannot
say which genes they are; the product of each rRNA feature ("5S ribosomal RNA",
"16S ribosomal RNA", "23S ribosomal RNA", a partial one included) is read from
the same bin's GFF (``prokka_gff_raw``, optional second source). Three things
follow:

* a bin with fewer than 3 rRNA features, or fewer than 18 tRNAs, cannot meet
  the criterion, GFF or not: it is False;
* otherwise the GFF decides: True when all three genes are named in it, False
  when one is missing;
* a bin with no GFF (the file is optional and a run may publish a subset)
  cannot be checked: it is null, and `mag/bin_summary` then never rates it a
  high-quality draft.

The completeness half comes from CheckM2; `mag/bin_summary` puts the two
together.

Input: the ``prokka_summary_raw`` data collection, a recursive Table scan of
the `.txt` files read as two colon-separated columns. The pattern is scoped to
a `Prokka/` directory on purpose: a bare `.*\\.txt$` also swallows the
`GenomeBinning/depths/contigs/*-depth.txt` tables next door::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '(?:.*/)?[Pp]rokka/.*\\.txt$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: ":"
          has_header: false
          new_columns: [key, value]
          truncate_ragged_lines: true
          include_file_paths: source_path
          infer_schema_length: 0

Output schema:
    bin_id : Utf8          bin the annotation belongs to, from the file name
    sample : Utf8          sample the assembly was built from
    assembler : Utf8       assembler part of the bin name
    binner : Utf8          binner part of the bin name
    n_contigs : Int64      contigs Prokka annotated
    bases : Int64          bases in the bin
    cds : Int64            coding sequences
    genes : Int64          gene features (CDS plus RNA genes)
    trna : Int64           transfer RNAs
    rrna : Int64           ribosomal RNAs
    tmrna : Int64          transfer-messenger RNAs
    repeat_regions : Int64 repeat regions
    cds_per_mbp : Float64  coding sequences per megabase, the gene density
    meets_mimag_rna : Boolean  5S, 16S and 23S rRNAs present and 18 tRNAs; null when no GFF
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mag_bins import bin_id_lookup, file_stem

RAW_DC_TAG = "prokka_summary_raw"
GFF_DC_TAG = "prokka_gff_raw"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summaries",
        input_schema={
            "source_path": pl.Utf8,
            "key": pl.Utf8,
            "value": pl.Utf8,
        },
        dc_ref=RAW_DC_TAG,
    ),
    # Names the rRNA genes; declared before this collection in the workflow.
    RecipeSource(
        ref="gff",
        dc_ref=GFF_DC_TAG,
        optional=True,
        input_schema={"ftype": pl.Utf8, "attributes": pl.Utf8, "source_path": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "bin_id": pl.Utf8,
    "sample": pl.Utf8,
    "assembler": pl.Utf8,
    "binner": pl.Utf8,
    "n_contigs": pl.Int64,
    "bases": pl.Int64,
    "cds": pl.Int64,
    "genes": pl.Int64,
    "trna": pl.Int64,
    "rrna": pl.Int64,
    "tmrna": pl.Int64,
    "repeat_regions": pl.Int64,
    "cds_per_mbp": pl.Float64,
    "meets_mimag_rna": pl.Boolean,
}

SOURCE_PATH_COL = "source_path"
KEY_COL = "key"
VALUE_COL = "value"

#: Prokka's key -> output column. Matched case-insensitively.
_COUNT_KEYS: dict[str, str] = {
    "contigs": "n_contigs",
    "bases": "bases",
    "cds": "cds",
    "gene": "genes",
    "trna": "trna",
    "rrna": "rrna",
    "tmrna": "tmrna",
    "repeat_region": "repeat_regions",
}

#: MIMAG's RNA criteria for a high-quality draft (Bowers et al. 2017, Table 1):
#: the 5S, 16S and 23S rRNA genes, and at least 18 tRNAs.
RRNA_GENES: tuple[str, ...] = ("5S", "16S", "23S")
MIN_TRNA = 18

#: Product of an rRNA feature in Prokka's GFF; the space is `%20` in a URL-encoded value.
_RRNA_PRODUCT = r"(?i)(?:^|;)product=(5S|16S|23S)(?:%20|\s)ribosomal(?:%20|\s)RNA"


def _rrna_genes(gff: pl.DataFrame | None) -> pl.DataFrame | None:
    """One row per bin in the GFF with a boolean per MIMAG rRNA gene, or None.

    A bin is listed as soon as the GFF holds any feature for it, so a bin with
    no rRNA at all is a row of Falses and not an absent one.
    """
    if gff is None or gff.is_empty():
        return None
    features = gff.filter(pl.col("attributes").is_not_null()).select(
        pl.col(SOURCE_PATH_COL)
        .map_elements(lambda path: file_stem(path, ".gff"), return_dtype=pl.Utf8)
        .alias("bin_id"),
        pl.col("ftype").cast(pl.Utf8),
        pl.col("attributes").str.extract(_RRNA_PRODUCT, 1).str.to_uppercase().alias("gene"),
    )
    if features.is_empty():
        return None
    named = features.filter(pl.col("ftype") == "rRNA")
    return (
        features.select("bin_id")
        .unique()
        .with_columns(
            *[
                pl.col("bin_id")
                .is_in(named.filter(pl.col("gene") == gene)["bin_id"].to_list())
                .alias(f"_has_{gene}")
                for gene in RRNA_GENES
            ]
        )
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot Prokka's key/value lines into one row per bin."""
    raw = sources["summaries"]
    if raw.is_empty():
        raise ValueError("prokka_summary: the scanned Prokka summaries are empty")
    for column in (SOURCE_PATH_COL, KEY_COL, VALUE_COL):
        if column not in raw.columns:
            raise ValueError(
                f"prokka_summary: the scan must produce `{column}`; got {raw.columns}. "
                "Declare it with separator ':', has_header false, "
                f"new_columns [{KEY_COL}, {VALUE_COL}] and include_file_paths {SOURCE_PATH_COL}."
            )

    tidy = raw.select(
        pl.col(SOURCE_PATH_COL)
        .map_elements(lambda path: file_stem(path, ".txt"), return_dtype=pl.Utf8)
        .alias("bin_id"),
        pl.col(KEY_COL).cast(pl.Utf8).str.strip_chars().str.to_lowercase().alias("metric"),
        pl.col(VALUE_COL).cast(pl.Utf8).str.strip_chars().alias("raw_value"),
    ).filter(pl.col("metric").is_in(list(_COUNT_KEYS)))

    if tidy.is_empty():
        raise ValueError(
            f"prokka_summary: no line matched a known Prokka key {sorted(_COUNT_KEYS)}"
        )

    wide = tidy.with_columns(
        pl.col("raw_value")
        .cast(pl.Float64, strict=False)
        .cast(pl.Int64, strict=False)
        .alias("count")
    ).pivot(on="metric", index="bin_id", values="count", aggregate_function="first")

    counts: list[pl.Expr] = []
    for key, alias in _COUNT_KEYS.items():
        if key in wide.columns:
            # A class Prokka did not list for this bin means zero of them.
            counts.append(pl.col(key).cast(pl.Int64).fill_null(0).alias(alias))
        else:
            counts.append(pl.lit(0, dtype=pl.Int64).alias(alias))

    frame = wide.select(pl.col("bin_id"), *counts)
    lookup = bin_id_lookup(frame["bin_id"].to_list()).drop("bin_index")
    frame = frame.join(lookup, on="bin_id", how="left")

    genes = _rrna_genes(sources.get("gff"))
    gene_cols = [f"_has_{gene}" for gene in RRNA_GENES]
    if genes is None:
        frame = frame.with_columns(*[pl.lit(None, dtype=pl.Boolean).alias(c) for c in gene_cols])
    else:
        frame = frame.join(genes, on="bin_id", how="left")
    # None when the GFF does not cover the bin, else whether all three genes are named.
    all_genes = pl.all_horizontal(*[pl.col(c) for c in gene_cols])

    return (
        frame.with_columns(
            pl.when(pl.col("bases") > 0)
            .then(pl.col("cds") / (pl.col("bases") / 1_000_000.0))
            .otherwise(None)
            .cast(pl.Float64)
            .alias("cds_per_mbp"),
            # Fewer than 3 rRNA features cannot name 3 genes, and fewer than 18 tRNAs
            # fails on its own: both are False without the GFF. Otherwise the GFF decides.
            pl.when((pl.col("trna") < MIN_TRNA) | (pl.col("rrna") < len(RRNA_GENES)))
            .then(pl.lit(False))
            .when(pl.col(gene_cols[0]).is_not_null())
            .then(all_genes)
            .otherwise(pl.lit(None, dtype=pl.Boolean))
            .alias("meets_mimag_rna"),
        )
        .select(list(OUTPUT_SCHEMA))
        .sort(["assembler", "binner", "sample", "bin_id"])
    )
