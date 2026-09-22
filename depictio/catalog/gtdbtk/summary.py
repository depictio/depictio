"""One row per classified bin, with its GTDB lineage split into ranks.

`gtdbtk classify_wf` writes `<prefix>.bac120.summary.tsv` for the bacterial
placements and `<prefix>.ar53.summary.tsv` for the archaeal ones. nf-core/mag
publishes both under `Taxonomy/GTDB-Tk/`, once at the run root and once under
`classify/`; the `classify/` copy is the populated one.

The whole lineage arrives as one semicolon-separated string with Greengenes
prefixes::

    d__Bacteria;p__Actinomycetota;c__Actinomycetes;o__Actinomycetales;...

which is unfilterable and undrawable. This recipe splits it into one column per
rank, drops the `x__` prefixes, and records the deepest rank that actually
carries a name in `rank_assigned`: a bin placed only to family is a different
result from one named to species, and the difference is invisible in the packed
string.

`bin_count` is 1 on every row on purpose: it is the weight a sunburst or a
sankey sums, so an arc is a number of bins.

Input: the ``gtdbtk_summary_raw`` data collection, a recursive Table scan::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*\\.(bac\\d+|ar\\d+)\\.summary\\.tsv$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs: {separator: "\\t", include_file_paths: source_path, infer_schema_length: 0}

Output schema:
    bin_id : Utf8            bin name, FASTA suffix removed
    sample : Utf8            sample the assembly was built from
    assembler : Utf8         assembler part of the run label
    binner : Utf8            binner part of the run label
    marker_set : Utf8        bac120 or ar53, the marker set that placed the bin
    domain, phylum, class_name, order, family, genus, species : Utf8
    rank_assigned : Utf8     deepest rank that carries a name
    classification : Utf8    the packed lineage as GTDB-Tk wrote it
    closest_reference : Utf8 accession of the closest GTDB genome
    closest_ani : Float64    average nucleotide identity to it, percent
    closest_af : Float64     alignment fraction to it
    classification_method : Utf8  ani_screen, topology, taxonomic novelty, ...
    msa_percent : Float64    percent of the marker alignment the bin covered
    bin_count : Int64        always 1, the weight a sunburst or sankey sums
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mag_bins import file_stem, label_lookup

RAW_DC_TAG = "gtdbtk_summary_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="summaries", dc_ref=RAW_DC_TAG),
]

#: GTDB rank prefix -> output column, root first. `class` is a Python keyword,
#: so the column is `class_name`.
RANKS: tuple[tuple[str, str], ...] = (
    ("d", "domain"),
    ("p", "phylum"),
    ("c", "class_name"),
    ("o", "order"),
    ("f", "family"),
    ("g", "genus"),
    ("s", "species"),
)

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "bin_id": pl.Utf8,
    "sample": pl.Utf8,
    "assembler": pl.Utf8,
    "binner": pl.Utf8,
    "marker_set": pl.Utf8,
    "domain": pl.Utf8,
    "phylum": pl.Utf8,
    "class_name": pl.Utf8,
    "order": pl.Utf8,
    "family": pl.Utf8,
    "genus": pl.Utf8,
    "species": pl.Utf8,
    "rank_assigned": pl.Utf8,
    "classification": pl.Utf8,
    "closest_reference": pl.Utf8,
    "closest_ani": pl.Float64,
    "closest_af": pl.Float64,
    "classification_method": pl.Utf8,
    "msa_percent": pl.Float64,
    "bin_count": pl.Int64,
}

SOURCE_PATH_COL = "source_path"

#: Suffixes to peel off the file name to reach the run label. The marker set is
#: read back out of the peeled part.
_SUMMARY_SUFFIX = ".summary.tsv"

#: FASTA suffixes GTDB-Tk keeps on the genome name it was handed.
_FASTA_SUFFIXES = (".fa.gz", ".fasta.gz", ".fna.gz", ".fa", ".fasta", ".fna")

#: Placeholders GTDB-Tk writes for "no value".
_NULL_TOKENS = frozenset({"", "n/a", "na", "none", "null", "-"})


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in _NULL_TOKENS else text


def _split_lineage(classification: str | None) -> dict[str, str | None]:
    """`d__Bacteria;p__...` -> one entry per rank, prefixes removed."""
    found: dict[str, str | None] = {column: None for _, column in RANKS}
    if classification is None:
        return found
    by_prefix = dict(RANKS)
    for part in str(classification).split(";"):
        token = part.strip()
        if "__" not in token:
            continue
        prefix, _, name = token.partition("__")
        column = by_prefix.get(prefix.strip())
        if column is not None:
            found[column] = _clean(name)
    return found


def _rank_assigned(lineage: dict[str, str | None]) -> str | None:
    deepest: str | None = None
    for _, column in RANKS:
        if lineage.get(column):
            deepest = column
    return deepest


def _marker_set(path: str) -> str | None:
    """`...FLYE-MaxBin2-...-CAPES_S11.bac120.summary.tsv` -> `bac120`."""
    stem = file_stem(path, _SUMMARY_SUFFIX)
    _, _, marker = stem.rpartition(".")
    return _clean(marker)


def _run_label(path: str) -> str:
    """The file name with the marker set and the summary suffix removed."""
    stem = file_stem(path, _SUMMARY_SUFFIX)
    head, sep, _ = stem.rpartition(".")
    return head if sep else stem


def _numeric(frame: pl.DataFrame, name: str) -> pl.Expr:
    if name not in frame.columns:
        return pl.lit(None, dtype=pl.Float64)
    return (
        pl.col(name)
        .cast(pl.Utf8)
        .str.strip_chars()
        .replace({token: None for token in ("N/A", "n/a", "NA", "-", "")})
        .cast(pl.Float64, strict=False)
    )


def _text(frame: pl.DataFrame, name: str) -> pl.Expr:
    if name not in frame.columns:
        return pl.lit(None, dtype=pl.Utf8)
    return pl.col(name).cast(pl.Utf8).map_elements(_clean, return_dtype=pl.Utf8)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Split every packed GTDB lineage into ranks and label the bin with its run."""
    raw = sources["summaries"]
    if raw.is_empty():
        raise ValueError("gtdbtk_summary: the scanned GTDB-Tk summaries are empty")
    if "user_genome" not in raw.columns:
        raise ValueError(f"gtdbtk_summary: no `user_genome` column in {raw.columns}")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "gtdbtk_summary: the scan must set "
            f"`include_file_paths: {SOURCE_PATH_COL}`; the binning run lives only in the file name"
        )

    labelled = raw.with_columns(
        pl.col("user_genome")
        .map_elements(lambda name: file_stem(name, *_FASTA_SUFFIXES), return_dtype=pl.Utf8)
        .alias("bin_id"),
        pl.col(SOURCE_PATH_COL).map_elements(_run_label, return_dtype=pl.Utf8).alias("run_label"),
        pl.col(SOURCE_PATH_COL).map_elements(_marker_set, return_dtype=pl.Utf8).alias("marker_set"),
    )
    labelled = labelled.join(
        label_lookup(labelled["run_label"].to_list()), on="run_label", how="left"
    )

    lineages = (
        [_split_lineage(value) for value in labelled["classification"].to_list()]
        if ("classification" in labelled.columns)
        else [{column: None for _, column in RANKS}] * labelled.height
    )
    ranks = pl.DataFrame(
        [
            tuple(lineage[column] for _, column in RANKS) + (_rank_assigned(lineage),)
            for lineage in lineages
        ],
        schema=[(column, pl.Utf8) for _, column in RANKS] + [("rank_assigned", pl.Utf8)],
        orient="row",
    )

    frame = (
        pl.concat([labelled, ranks], how="horizontal")
        .select(
            pl.col("bin_id"),
            pl.col("sample"),
            pl.col("assembler"),
            pl.col("binner"),
            pl.col("marker_set"),
            *[pl.col(column) for _, column in RANKS],
            pl.col("rank_assigned"),
            _text(labelled, "classification").alias("classification"),
            _text(labelled, "closest_genome_reference").alias("closest_reference"),
            _numeric(labelled, "closest_genome_ani").alias("closest_ani"),
            _numeric(labelled, "closest_genome_af").alias("closest_af"),
            _text(labelled, "classification_method").alias("classification_method"),
            _numeric(labelled, "msa_percent").alias("msa_percent"),
            pl.lit(1, dtype=pl.Int64).alias("bin_count"),
        )
        .drop_nulls(["bin_id"])
    )

    if frame.is_empty():
        raise ValueError("gtdbtk_summary: no row carried a genome name")

    return (
        frame.unique(subset=["bin_id", "marker_set"], keep="first", maintain_order=True)
        .select(list(EXPECTED_SCHEMA))
        .sort(["assembler", "binner", "sample", "bin_id"])
    )
