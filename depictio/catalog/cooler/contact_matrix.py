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

Multi-resolution: one table, one partition per resolution
---------------------------------------------------------
A run typically dumps more than one resolution (the megatest ships 500 kb and
1 Mb). Earlier this recipe kept only the finest one, because mixing two bin
sizes on one axis draws nonsense. The `resolution` column is now the partition
key instead: every dumped resolution is kept, and whoever reads the table picks
exactly one partition before drawing. That is what lets a contact map re-bin
itself as the reader zooms, without a tile-side matrix service.

When a run dumps a single resolution the column would carry one value and the
zoom would have nothing to switch to, so the recipe derives the coarser levels
itself: each derived level merges 2, 4 and 8 adjacent bins and SUMS the values
of the merged cells, which is what ``cooler coarsen`` does. Deriving is only a
fallback: a level the run really dumped is never replaced by a derived one, and
no level coarser than `_MAX_DERIVED_RESOLUTION` is produced (a whole mammalian
chromosome in ten bins carries no structure to look at).

Only intra-chromosomal pairs are kept (``chrom1 == chrom2``): a whole-genome
matrix is dominated by trans contacts that swamp the per-chromosome structure
the `contact_map` kind's chromosome selector is for, and at fine resolution the
full upper triangle is tens of millions of rows.

Output schema:
    sample : Utf8       sample the matrix was dumped for
    resolution : Int64   bin size in bp; the partition key, one matrix per value
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

#: Bin-merge factors used to derive coarser levels when a run dumped exactly
#: one resolution. Powers of two so every derived bin boundary falls on a
#: dumped bin boundary, which keeps the derived matrices nested.
DERIVED_FACTORS: tuple[int, ...] = (2, 4, 8)

#: Ceiling on a derived level. Past this a mammalian chromosome is a handful of
#: bins and the matrix has no structure left to read.
MAX_DERIVED_RESOLUTION = 20_000_000

_SORT_KEYS = ["resolution", "chrom1", "start1", "start2"]


def _empty() -> pl.DataFrame:
    """The output schema with no rows, for a run that dumped nothing."""
    return pl.DataFrame(schema=EXPECTED_SCHEMA)


def coarsen(df: pl.DataFrame, base_resolution: int, factor: int) -> pl.DataFrame:
    """Merge `factor` adjacent bins per axis, summing the merged cells.

    The bin a coordinate lands in is ``start // new_resolution``, so bin
    boundaries of the coarse level are a subset of the fine level's as long as
    `factor` divides evenly, which is why `DERIVED_FACTORS` are powers of two.
    Ends are carried as the max of the merged cells rather than recomputed from
    the start, so the last bin of a chromosome keeps the truncated end cooler
    gave it instead of running past the contig.
    """
    new_resolution = base_resolution * factor
    return (
        df.with_columns(
            pl.lit(new_resolution, dtype=pl.Int64).alias("resolution"),
            ((pl.col("start1") // new_resolution) * new_resolution).alias("start1"),
            ((pl.col("start2") // new_resolution) * new_resolution).alias("start2"),
        )
        .group_by(["sample", "resolution", "chrom1", "start1", "chrom2", "start2"])
        .agg(
            pl.col("end1").max(),
            pl.col("end2").max(),
            pl.col("count").sum(),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(_SORT_KEYS)
    )


def derive_levels(df: pl.DataFrame, base_resolution: int) -> list[pl.DataFrame]:
    """Coarser partitions for a run that dumped a single resolution."""
    out: list[pl.DataFrame] = []
    for factor in DERIVED_FACTORS:
        if base_resolution * factor > MAX_DERIVED_RESOLUTION:
            break
        out.append(coarsen(df, base_resolution, factor))
    return out


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Join the balanced contact dump to its bins, one partition per resolution."""
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
        return _empty()

    bins = bins.with_columns(
        pl.col("source_path").str.extract(_BINS_RE, 1).cast(pl.Int64).alias("resolution"),
        pl.col("start").cast(pl.Int64),
        pl.col("end").cast(pl.Int64),
    )
    # `cooler makebins` restarts the bin ids at 0 in every file, so the row
    # number has to be taken per file, then keyed by resolution on the join.
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
        .sort(_SORT_KEYS)
    )
    if df.is_empty():
        return _empty()

    dumped = sorted(set(df["resolution"].to_list()))
    if len(dumped) == 1:
        derived = derive_levels(df, int(dumped[0]))
        if derived:
            df = pl.concat([df, *derived], how="vertical").sort(_SORT_KEYS)
    return df
