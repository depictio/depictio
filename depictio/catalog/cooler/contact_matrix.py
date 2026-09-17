"""Binned intra-chromosomal contact matrix, from a cooler dump joined to its bins.

``cooler dump --matrix balanced`` writes a headerless, 0-based sparse triplet
per resolution, ``<sample>.<resolution>_balanced.txt``: ``bin1_id``,
``bin2_id``, ``count`` (the ICE-balanced contact value). The bin IDs index rows
of ``cooler makebins``' own output, ``cooler_bins_<resolution>.bed``
(``chrom``, ``start``, ``end``), which resets to 0 for every resolution and
carries no sample of its own (bins depend only on the reference and the
resolution).

Neither file carries the sample or the resolution as a column, so both are
read through **scan** data collections whose `include_file_paths` carries the
file path into the frame, and the recipe reads both by `dc_ref`::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*_balanced\\.txt$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          has_header: false
          new_columns: [bin1_id, bin2_id, count]
          include_file_paths: source_path
          infer_schema_length: 0

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: 'cooler_bins_\\d+\\.bed$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          has_header: false
          new_columns: [chrom, start, end]
          include_file_paths: source_path

A run typically dumps more than one resolution (the megatest ships 500 kb and
1 Mb); mixing resolutions in one matrix would draw bins of two different sizes
on the same axis, so this recipe keeps only the FINEST resolution present
(``resolution.min()``) and drops the rest. It also keeps only intra-chromosomal
pairs (``chrom1 == chrom2``): a whole-genome matrix is dominated by trans
contacts that swamp the per-chromosome structure the `contact_map` kind's
chromosome selector is for, and at fine resolution the full upper triangle is
tens of millions of rows.

Output schema:
    sample : Utf8       sample the matrix was dumped for
    resolution : Int64   bin size in bp (the finest resolution present)
    chrom1 : Utf8        chromosome of the row bin
    start1 : Int64        row bin start
    end1 : Int64           row bin end
    chrom2 : Utf8        chromosome of the column bin (== chrom1)
    start2 : Int64        column bin start
    end2 : Int64           column bin end
    count : Float64      ICE-balanced contact value
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tags the recipe reads. A template reusing this recipe must
#: scan the raw dump and the bins into DCs with these tags (see module docstring).
CONTACTS_DC_TAG = "cooler_contacts_raw"
BINS_DC_TAG = "cooler_bins_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="contacts", dc_ref=CONTACTS_DC_TAG),
    RecipeSource(ref="bins", dc_ref=BINS_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "resolution": pl.Int64,
    "chrom1": pl.Utf8,
    "start1": pl.Int64,
    "end1": pl.Int64,
    "chrom2": pl.Utf8,
    "start2": pl.Int64,
    "end2": pl.Int64,
    "count": pl.Float64,
}

_CONTACTS_RE = r"([^/\\]+)\.(\d+)_balanced\.txt$"
_BINS_RE = r"cooler_bins_(\d+)\.bed$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Join the balanced contact dump to its bins and keep the finest intra-chromosomal matrix."""
    contacts = sources["contacts"]
    bins = sources["bins"]

    contacts = contacts.with_columns(
        pl.col("source_path").str.extract(_CONTACTS_RE, 1).alias("sample"),
        pl.col("source_path").str.extract(_CONTACTS_RE, 2).cast(pl.Int64).alias("resolution"),
        pl.col("bin1_id").cast(pl.Int64),
        pl.col("bin2_id").cast(pl.Int64),
        pl.col("count").cast(pl.Float64),
    )
    if contacts.is_empty():
        return contacts.select(
            [
                pl.lit(None, dtype=t).alias(c).filter(pl.lit(False))
                for c, t in EXPECTED_SCHEMA.items()
            ]
        )

    finest = contacts["resolution"].min()
    contacts = contacts.filter(pl.col("resolution") == finest)

    bins = bins.with_columns(
        pl.col("source_path").str.extract(_BINS_RE, 1).cast(pl.Int64).alias("resolution"),
        pl.col("start").cast(pl.Int64),
        pl.col("end").cast(pl.Int64),
    ).filter(pl.col("resolution") == finest)
    bins = bins.with_columns(pl.int_range(pl.len()).over("source_path").alias("bin_id"))
    bins = bins.select(["resolution", "bin_id", "chrom", "start", "end"])

    df = (
        contacts.join(
            bins.rename({"chrom": "chrom1", "start": "start1", "end": "end1"}),
            left_on=["resolution", "bin1_id"],
            right_on=["resolution", "bin_id"],
            how="inner",
        )
        .join(
            bins.rename({"chrom": "chrom2", "start": "start2", "end": "end2"}),
            left_on=["resolution", "bin2_id"],
            right_on=["resolution", "bin_id"],
            how="inner",
        )
        .filter(pl.col("chrom1") == pl.col("chrom2"))
        .select(list(EXPECTED_SCHEMA))
        .sort(["chrom1", "start1", "start2"])
    )
    return df
