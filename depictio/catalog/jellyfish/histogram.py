"""The read k-mer spectrum of each read set, from `jellyfish histo` output.

`jellyfish histo` prints two space-separated numbers per line, a multiplicity
and the number of distinct k-mers seen that many times, and nothing else: the
read set lives only in the file name. The full histogram runs to the highest
multiplicity observed (tens of thousands of rows, almost all of them repeats
seen once each), which no plot needs. The recipe finds the main peak past the
error trough and keeps the curve up to four times that multiplicity, which
holds the error peak, the heterozygous and homozygous peaks and the start of
the repeat tail, then thins it to at most ``MAX_POINTS`` rows per read set.

Input: the ``jellyfish_histo_raw`` data collection, a recursive Table scan::

    dc_specific_properties:
      format: TSV
      polars_kwargs: {separator: " ", has_header: false, new_columns: [multiplicity, kmers],
                      include_file_paths: source_path, infer_schema_length: 0}

Output schema:
    read_set : Utf8               the file name without `_hist.tsv` / `.histo` / `.tsv`
    multiplicity : Int64          how often a k-mer occurs in the reads
    kmers : Int64                 distinct k-mers with that multiplicity
    kmer_mass : Int64             multiplicity times kmers, the reads' k-mer volume at that depth
    peak_multiplicity : Int64     the main peak of this read set (the k-mer depth)
"""

from __future__ import annotations

from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "jellyfish_histo_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="histograms", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "read_set": pl.Utf8,
    "multiplicity": pl.Int64,
    "kmers": pl.Int64,
    "kmer_mass": pl.Int64,
    "peak_multiplicity": pl.Int64,
}

SOURCE_PATH_COL = "source_path"

#: Upper bound on the rows kept per read set, the profile kind's comfort zone.
MAX_POINTS = 200

#: Keep the curve up to this many times the main peak.
PEAK_SPAN = 4


def read_set_name(source_path: str) -> str:
    """`<dir>/<name>_hist.tsv` (or `.histo`, `.tsv`) -> `<name>`."""
    name = PurePosixPath(source_path.replace("\\", "/")).name
    for suffix in ("_hist.tsv", ".histo", ".tsv", ".txt"):
        if name.endswith(suffix):
            return name.removesuffix(suffix)
    return name


def main_peak(multiplicity: list[int], kmers: list[int]) -> int:
    """The highest point after the error trough (the first rise of the curve)."""
    pairs = sorted(zip(multiplicity, kmers, strict=True))
    start = 0
    for i in range(len(pairs) - 1):
        if pairs[i + 1][1] > pairs[i][1]:
            start = i + 1
            break
    tail = pairs[start:] or pairs
    return max(tail, key=lambda p: p[1])[0]


def _one_read_set(name: str, frame: pl.DataFrame) -> pl.DataFrame:
    frame = frame.sort("multiplicity")
    peak = main_peak(frame["multiplicity"].to_list(), frame["kmers"].to_list())
    kept = frame.filter(pl.col("multiplicity") <= max(PEAK_SPAN * peak, 10))
    if kept.height > MAX_POINTS:
        step = -(-kept.height // MAX_POINTS)
        kept = kept.gather_every(step)
    return kept.select(
        pl.lit(name).alias("read_set"),
        pl.col("multiplicity"),
        pl.col("kmers"),
        (pl.col("multiplicity") * pl.col("kmers")).alias("kmer_mass"),
        pl.lit(peak, dtype=pl.Int64).alias("peak_multiplicity"),
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Cut and thin every scanned histogram."""
    raw = sources["histograms"]
    if raw.is_empty():
        raise ValueError("jellyfish_histogram: the scanned histograms are empty")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError("jellyfish_histogram: the scan must include_file_paths: source_path")
    value_cols = [c for c in raw.columns if c != SOURCE_PATH_COL]
    if len(value_cols) < 2:
        raise ValueError(f"jellyfish_histogram: expected two columns, got {value_cols}")
    tidy = raw.select(
        pl.col(SOURCE_PATH_COL).map_elements(read_set_name, return_dtype=pl.Utf8).alias("read_set"),
        pl.col(value_cols[0]).cast(pl.Float64, strict=False).cast(pl.Int64).alias("multiplicity"),
        pl.col(value_cols[1]).cast(pl.Float64, strict=False).cast(pl.Int64).alias("kmers"),
    ).drop_nulls()
    parts = [
        _one_read_set(str(name), group)
        for (name,), group in tidy.group_by(["read_set"], maintain_order=True)
    ]
    if not parts:
        raise ValueError("jellyfish_histogram: no histogram carried a data row")
    return (
        pl.concat(parts, how="vertical")
        .select(list(EXPECTED_SCHEMA))
        .sort(["read_set", "multiplicity"])
    )
