"""One row per annotated feature, with the coordinates it sits at inside its bin.

Prokka's GFF is the only file in a metagenome run that says where a gene is.
Three things about it shape this recipe:

* every contig is renamed to Prokka's own `gnl|<centre>|<hash>_N`, so the
  coordinates are meaningful inside the bin and join to nothing outside it.
  This is a within-bin locus map, never a genome browser track over the
  assembly;
* the bin's whole FASTA follows the features after a `##FASTA` line. Read as a
  tab-separated table those sequence lines come back as rows with one non-null
  field, and they outnumber the features fifteen to one, so they are dropped on
  the `attributes` column being null;
* Prokka emits a `gene` feature and a `CDS` feature at the same coordinates for
  every protein. Keeping both would draw every arrow twice, so `gene` is
  dropped and CDS, tRNA, rRNA, tmRNA and repeat regions are kept.

Input: the ``prokka_gff_raw`` data collection, a recursive Table scan of the
GFF files read without a header, scoped to a `Prokka/` directory the way the
summary scan is::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '(?:.*/)?[Pp]rokka/.*\\.gff$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          has_header: false
          comment_prefix: "#"
          quote_char: null
          truncate_ragged_lines: true
          new_columns: [seqid, source, ftype, start, end, score, strand, phase, attributes]
          include_file_paths: source_path
          infer_schema_length: 0

Output schema:
    bin_id : Utf8      bin the feature belongs to, from the file name
    sample : Utf8      sample the assembly was built from
    assembler : Utf8   assembler part of the bin name
    binner : Utf8      binner part of the bin name
    contig : Utf8      Prokka's contig label, bin-local
    feature_id : Utf8  locus tag
    ftype : Utf8       CDS, tRNA, rRNA, tmRNA, repeat_region
    start : Int64      first base, 1-based as GFF writes it
    end : Int64        last base
    strand : Utf8      '+' or '-'
    length_bp : Int64  end - start + 1
    gene : Utf8        gene symbol when Prokka assigned one
    product : Utf8     product description, 'hypothetical protein' when unknown
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mag_bins import bin_id_lookup, file_stem

RAW_DC_TAG = "prokka_gff_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="features", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "bin_id": pl.Utf8,
    "sample": pl.Utf8,
    "assembler": pl.Utf8,
    "binner": pl.Utf8,
    "contig": pl.Utf8,
    "feature_id": pl.Utf8,
    "ftype": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "strand": pl.Utf8,
    "length_bp": pl.Int64,
    "gene": pl.Utf8,
    "product": pl.Utf8,
}

SOURCE_PATH_COL = "source_path"

#: Feature types kept. `gene` is dropped: Prokka writes it at the same
#: coordinates as the CDS it belongs to.
KEPT_FTYPES: tuple[str, ...] = ("CDS", "tRNA", "rRNA", "tmRNA", "repeat_region")

#: GFF columns the scan is asked to name.
_GFF_COLUMNS = (
    "seqid",
    "source",
    "ftype",
    "start",
    "end",
    "score",
    "strand",
    "phase",
    "attributes",
)


def _attribute(name: str) -> pl.Expr:
    """One `key=value;` field out of the GFF attributes column, URL-decoded."""
    return (
        pl.col("attributes")
        .str.extract(rf"(?:^|;){name}=([^;]*)", 1)
        .str.replace_all("%2C", ",", literal=True)
        .str.replace_all("%3B", ";", literal=True)
        .str.replace_all("%20", " ", literal=True)
        .str.replace_all("%28", "(", literal=True)
        .str.replace_all("%29", ")", literal=True)
        .str.replace_all("%2F", "/", literal=True)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Drop the embedded FASTA and the duplicate gene rows, then name the bin."""
    raw = sources["features"]
    if raw.is_empty():
        raise ValueError("prokka_gene_track: the scanned GFF files are empty")
    missing = [column for column in (*_GFF_COLUMNS, SOURCE_PATH_COL) if column not in raw.columns]
    if missing:
        raise ValueError(
            f"prokka_gene_track: the scan must produce {missing}; got {raw.columns}. "
            "Declare the GFF scan with has_header false and the nine GFF column names."
        )

    features = raw.filter(
        pl.col("attributes").is_not_null() & pl.col("ftype").is_in(list(KEPT_FTYPES))
    )
    if features.is_empty():
        raise ValueError(
            "prokka_gene_track: no row carried a GFF attributes field; "
            f"expected feature types {list(KEPT_FTYPES)}"
        )

    frame = features.select(
        pl.col(SOURCE_PATH_COL)
        .map_elements(lambda path: file_stem(path, ".gff"), return_dtype=pl.Utf8)
        .alias("bin_id"),
        pl.col("seqid").cast(pl.Utf8).alias("contig"),
        _attribute("locus_tag").alias("locus_tag"),
        _attribute("ID").alias("feature_ref"),
        pl.col("ftype").cast(pl.Utf8).alias("ftype"),
        pl.col("start").cast(pl.Float64, strict=False).cast(pl.Int64, strict=False).alias("start"),
        pl.col("end").cast(pl.Float64, strict=False).cast(pl.Int64, strict=False).alias("end"),
        pl.col("strand").cast(pl.Utf8).alias("strand"),
        _attribute("gene").alias("gene"),
        _attribute("product").alias("product"),
    ).with_columns(
        pl.coalesce([pl.col("locus_tag"), pl.col("feature_ref")]).alias("feature_id"),
        (pl.col("end") - pl.col("start") + 1).alias("length_bp"),
    )

    lookup = bin_id_lookup(frame["bin_id"].unique().to_list()).drop("bin_index")
    frame = frame.join(lookup, on="bin_id", how="left")

    return (
        frame.drop_nulls(["bin_id", "contig", "start", "end"])
        .select(list(EXPECTED_SCHEMA))
        .sort(["bin_id", "contig", "start"])
    )
