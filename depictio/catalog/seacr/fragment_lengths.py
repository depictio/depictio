"""Fragment-length distribution per sample, the signature CUT&RUN QC figure.

SEACR thresholds the fragment coverage of an experiment, so the length of those
fragments is what says whether the experiment worked at all: MNase cuts around
nucleosomes, which puts a sharp sub-nucleosomal peak below ~120 bp (the
transcription-factor / free-DNA fraction) next to a mononucleosomal shoulder
around 180 bp. A flat, featureless distribution is a failed digestion.

The CUT&RUN-family pipelines write one headerless two-column histogram per
sample next to the fragment BEDs, ``<sample>.frags.len.txt``: fragment length
and how many fragments had it. Neither column names the sample, so this recipe
reads the files through a **scan** data collection (only a scan carries the
file path into the frame) and takes the sample off the path. A template reusing
it declares::

    config:
      type: Table
      scan:
        mode: recursive
        scan_parameters:
          regex_config: {pattern: '.*\\.frags\\.len\\.txt$'}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          has_header: false
          new_columns: [fragment_length, count]
          include_file_paths: source_path
          infer_schema_length: 0

Output schema:
    sample : Utf8                 sample the fragments came from
    target : Utf8                 group the sample belongs to (replicate suffix removed)
    fragment_length : Int64       fragment length in bp
    count : Int64                 fragments of that length
    fraction : Float64            count / all fragments of the sample
    cumulative_fraction : Float64  fraction of the sample's fragments at most this long
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the recipe reads (see module docstring).
RAW_DC_TAG = "seacr_fragment_lengths_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="lengths", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "target": pl.Utf8,
    "fragment_length": pl.Int64,
    "count": pl.Int64,
    "fraction": pl.Float64,
    "cumulative_fraction": pl.Float64,
}

# `<sample>.frags.len.txt`; `<group>_R<replicate>` is the sample naming.
_NAME_RE = r"(?P<sample>.+?)\.frags\.len\.txt$"
_REPLICATE_SUFFIX = r"_(?:R|rep|REP|Rep)?\d+$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Name the sample from the file path and normalise the histogram."""
    df = sources["lengths"]
    missing = [c for c in ("fragment_length", "count") if c not in df.columns]
    if missing:
        raise ValueError(f"seacr_fragment_lengths: input lacks columns {missing}")
    if "source_path" not in df.columns:
        raise ValueError(
            "seacr_fragment_lengths: input has no 'source_path' column — the raw "
            "data collection must be scanned with polars_kwargs.include_file_paths"
        )

    basename = pl.col("source_path").str.replace_all(r"^.*/", "")
    df = df.with_columns(
        basename.str.extract(_NAME_RE, 1).alias("sample"),
        pl.col("fragment_length").cast(pl.Int64, strict=False),
        pl.col("count").cast(pl.Int64, strict=False),
    )
    unnamed = df.filter(pl.col("sample").is_null()).height
    if unnamed:
        raise ValueError(
            f"seacr_fragment_lengths: {unnamed} row(s) came from a file whose name "
            "does not look like '<sample>.frags.len.txt'"
        )

    df = df.drop_nulls("fragment_length").sort(["sample", "fragment_length"])
    df = df.with_columns(
        pl.col("sample").str.replace(_REPLICATE_SUFFIX, "").alias("target"),
        (pl.col("count") / pl.col("count").sum().over("sample")).alias("fraction"),
    )
    df = df.with_columns(pl.col("fraction").cum_sum().over("sample").alias("cumulative_fraction"))
    return df.select(list(EXPECTED_SCHEMA))
