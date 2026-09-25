"""The distribution blocks of `bcftools stats`, melted into one long frame.

`bcftools stats` packs several distributions into one flat report, each
tagged by its own record type and each with its own column layout: indel
length (`IDD`), substitution type (`ST`), read depth (`DP`), non-reference
allele frequency (`AF`) and singleton stats (`SiS`). Read as five tables they
would be five data collections, five sets of filters and five tiles that
cannot be compared; read as one long `section / bin / label / count` frame
they are one collection, and a single `section` filter drives every tile on
the tab.

The quality block (`QUAL`) is left out on purpose. It has one row per
distinct quality value, which on a real callset is most of the melted frame,
so a bar chart of the unfiltered collection read as a quality histogram and
nothing else; and the quality question it answers (where a caller's score
stops separating calls from noise) is the VCFtools Ts/Tv-by-quality sweep's
job (`vcftools/tstv_qual.py`).

The price of melting is that the key column differs per section. A numeric
distribution (indel length, depth, allele frequency) carries its
x value in `bin` and leaves `label` null; a categorical one (substitution
type, singleton stats) carries its x value in `label` and leaves `bin`
null. `DP` is the one section that fills both, because bcftools writes its
open-ended top bucket as a non-numeric bin name.

`count` is the closest thing to "how many" each section publishes, which is
not the same field in all five: number of sites for indel length and depth,
number of SNPs for allele frequency, and the substitution or singleton count
for the two categorical ones. It is always a count of
variant records, so summing it across a filtered section is meaningful;
summing it across sections is not.

The report never names its sample or its caller, so both are read off its
`ID` line by `depictio.recipes.lib.bcftools_stats` and joined back on
`source_path`, exactly as in `bcftools/stats_summary.py`. The raw DC scans
with a separator that never occurs in the file, so one full line lands in a
single `raw_line` column and this recipe splits it on tabs itself -- the
record types have between 4 and 10 fields, and a fixed column count would
truncate the wide ones.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bcftools_stats import sample_and_caller

RAW_DC_TAG = "bcftools_stats_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "section": pl.Utf8,
    "bin": pl.Float64,  # null for the categorical sections
    "label": pl.Utf8,  # null for the numeric sections
    "count": pl.Int64,
}

#: Section name -> (record type, 0-based field holding the numeric bin,
#: 0-based field holding the count). Field 0 is the record type itself and
#: field 1 is bcftools' file id, so the payload starts at field 2. Offsets
#: verified against the `# <TYPE>\t[2]...` legend bcftools writes above each
#: block. `_SUBSTITUTION` below has the same shape, with the categorical label
#: in place of the bin.
_NUMERIC_SECTIONS: dict[str, tuple[str, int, int]] = {
    # IDD  [3]length (deletions negative)  [4]number of sites
    "indel_length": ("IDD", 2, 3),
    # AF   [3]allele frequency  [4]number of SNPs
    "allele_frequency": ("AF", 2, 3),
}

#: ST  [3]type (e.g. "A to C")  [4]count
_SUBSTITUTION = ("ST", 2, 3)

#: DP  [3]bin  [6]number of sites. bcftools only fills [4] "number of
#: genotypes" when it was run with -s/-S, which nf-core does not, so that
#: column is identically zero in these reports and the number of sites is
#: the only count the section actually carries.
_DEPTH = ("DP", 2, 5)

#: SiS [3]allele count (always 1: these are singletons) [4]number of SNPs
#: [7]number of indels. The transition/transversion split is already in the
#: TSTV output and the three repeat-consistency columns are documented
#: upstream as deprecated and useless, so only the two counts are kept.
_SINGLETON_FIELDS: dict[int, str] = {3: "singleton SNPs", 6: "singleton indels"}


def _fields(df: pl.DataFrame, record: str) -> pl.DataFrame:
    """Rows of one record type, tab-split into a `fields` list column."""
    return df.filter(pl.col("raw_line").str.starts_with(f"{record}\t")).with_columns(
        pl.col("raw_line").str.split("\t").alias("fields")
    )


def _melted(
    df: pl.DataFrame, record: str, section: str, bin_field: int, count_field: int
) -> pl.DataFrame:
    """A numeric section: `bin` from one field, `count` from another."""
    return _fields(df, record).select(
        pl.col("source_path"),
        pl.lit(section).alias("section"),
        # `.` (bcftools' "not applicable") and any other non-number become
        # null rather than raising: the count is still worth keeping.
        pl.col("fields").list.get(bin_field).cast(pl.Float64, strict=False).alias("bin"),
        pl.lit(None, dtype=pl.Utf8).alias("label"),
        pl.col("fields").list.get(count_field).cast(pl.Int64, strict=False).alias("count"),
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per sample, caller, section and bin or label."""
    df = sources["raw"].filter(pl.col("raw_line").is_not_null())

    blocks: list[pl.DataFrame] = [
        _melted(df, record, section, bin_field, count_field)
        for section, (record, bin_field, count_field) in _NUMERIC_SECTIONS.items()
    ]

    record, label_field, count_field = _SUBSTITUTION
    blocks.append(
        _fields(df, record).select(
            pl.col("source_path"),
            pl.lit("substitution").alias("section"),
            pl.lit(None, dtype=pl.Float64).alias("bin"),
            pl.col("fields").list.get(label_field).alias("label"),
            pl.col("fields").list.get(count_field).cast(pl.Int64, strict=False).alias("count"),
        )
    )

    # Depth is the one section with both: the bin name is numeric except for
    # bcftools' open-ended top bucket, which is kept verbatim in `label` so
    # the tail is not silently dropped.
    record, bin_field, count_field = _DEPTH
    blocks.append(
        _fields(df, record).select(
            pl.col("source_path"),
            pl.lit("depth").alias("section"),
            pl.col("fields").list.get(bin_field).cast(pl.Float64, strict=False).alias("bin"),
            pl.col("fields").list.get(bin_field).alias("label"),
            pl.col("fields").list.get(count_field).cast(pl.Int64, strict=False).alias("count"),
        )
    )

    singletons = _fields(df, "SiS")
    for field, label in _SINGLETON_FIELDS.items():
        blocks.append(
            singletons.select(
                pl.col("source_path"),
                pl.lit("singleton_stats").alias("section"),
                pl.lit(None, dtype=pl.Float64).alias("bin"),
                pl.lit(label).alias("label"),
                pl.col("fields").list.get(field).cast(pl.Int64, strict=False).alias("count"),
            )
        )

    long = pl.concat(blocks, how="vertical")

    return (
        long.join(sample_and_caller(sources["raw"]), on="source_path", how="left")
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "caller", "section", "bin", "label"], nulls_last=True)
    )
