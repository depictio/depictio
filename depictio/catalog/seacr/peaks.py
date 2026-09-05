"""Tidy every SEACR peak of every sample into one table.

SEACR writes a headerless BED6 per sample,
``<sample>.seacr.peaks.<threshold>.bed``, whose columns are chrom, start, end,
total signal (summed fragment coverage over the region), max signal (the
highest coverage inside it) and the sub-interval where that max was reached
(``chr1:778588-778597``). There is no p-value, no fold enrichment and no summit
offset: SEACR thresholds the coverage landscape against an IgG control instead
of fitting a background model, so the MACS2 schema does not apply.

The sample is not a column of the file and SEACR stamps nothing into the rows,
so this recipe reads the per-sample files through a **scan** data collection
rather than a glob: only a scan carries the file path into the frame
(``include_file_paths``), and the sample and the threshold mode are read off
that path. A template reusing this recipe declares::

    config:
      type: Table
      scan:
        mode: recursive
        scan_parameters:
          regex_config: {pattern: '.*\\.seacr\\.peaks\\.\\w+\\.bed$'}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          has_header: false
          new_columns: [chr, start, end, total_signal, max_signal, max_signal_region]
          include_file_paths: source_path
          infer_schema_length: 0

``infer_schema_length: 0`` reads every column as text: SEACR writes the signal
columns in scientific notation (``1.13476e+06``) and per-file inference
disagrees between a histone mark and a transcription factor, which breaks the
concatenation. This recipe recasts.

Output schema:
    sample : Utf8               sample the peak was called in
    peak_id : Utf8              "<sample>:<chr>:<start>-<end>", unique across samples
    threshold_mode : Utf8       SEACR mode the call came from (stringent / relaxed)
    chr : Utf8                  chromosome
    start : Int64               region start (0-based, as SEACR reports it)
    end : Int64                 region end
    width : Int64               end - start, the region width in bp
    summit : Int64              midpoint of the max-signal sub-interval
    total_signal : Float64      summed fragment coverage over the region
    max_signal : Float64        highest fragment coverage inside the region
    signal_density : Float64    total_signal / width, coverage per base
    log10_total_signal : Float64  log10(total_signal + 1), the significance axis
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the recipe reads. A template reusing this recipe must
#: scan its per-sample SEACR beds into a DC with this tag (see module docstring).
RAW_DC_TAG = "seacr_peaks_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="peaks", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "peak_id": pl.Utf8,
    "threshold_mode": pl.Utf8,
    "chr": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "width": pl.Int64,
    "summit": pl.Int64,
    "total_signal": pl.Float64,
    "max_signal": pl.Float64,
    "signal_density": pl.Float64,
    "log10_total_signal": pl.Float64,
}

_BED_COLUMNS = ["chr", "start", "end", "total_signal", "max_signal", "max_signal_region"]

# `<sample>.seacr.peaks.<mode>.bed`; the mode is `stringent` or `relaxed`.
_NAME_RE = r"(?P<sample>.+?)\.seacr\.peaks\.(?P<mode>[^.]+)\.bed$"
# `chr1:778588-778597`, the sub-interval SEACR reports the max signal for.
_REGION_RE = r"^(?P<chr>.+):(?P<start>\d+)-(?P<end>\d+)$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Type the BED columns and read sample / threshold mode off the file path."""
    df = sources["peaks"]
    missing = [c for c in _BED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"seacr_peaks: input lacks columns {missing}")
    if "source_path" not in df.columns:
        raise ValueError(
            "seacr_peaks: input has no 'source_path' column — the raw data "
            "collection must be scanned with polars_kwargs.include_file_paths"
        )

    basename = pl.col("source_path").str.replace_all(r"^.*/", "")
    df = df.with_columns(
        basename.str.extract(_NAME_RE, 1).alias("sample"),
        basename.str.extract(_NAME_RE, 2).alias("threshold_mode"),
        pl.col("chr").cast(pl.Utf8),
        pl.col("start").cast(pl.Int64, strict=False),
        pl.col("end").cast(pl.Int64, strict=False),
        pl.col("total_signal").cast(pl.Float64, strict=False),
        pl.col("max_signal").cast(pl.Float64, strict=False),
    )
    unnamed = df.filter(pl.col("sample").is_null()).height
    if unnamed:
        raise ValueError(
            f"seacr_peaks: {unnamed} row(s) came from a file whose name does not "
            "look like '<sample>.seacr.peaks.<mode>.bed'"
        )

    region = pl.col("max_signal_region").cast(pl.Utf8)
    max_start = region.str.extract(_REGION_RE, 2).cast(pl.Int64, strict=False)
    max_end = region.str.extract(_REGION_RE, 3).cast(pl.Int64, strict=False)
    width = (pl.col("end") - pl.col("start")).alias("width")

    df = df.with_columns(
        width,
        pl.concat_str(
            [
                pl.col("sample"),
                pl.lit(":"),
                pl.col("chr"),
                pl.lit(":"),
                pl.col("start").cast(pl.Utf8),
                pl.lit("-"),
                pl.col("end").cast(pl.Utf8),
            ]
        ).alias("peak_id"),
        # The max-signal sub-interval is inside the region, so its midpoint is a
        # usable point position; fall back to the region midpoint when SEACR
        # wrote no sub-interval.
        pl.coalesce(
            ((max_start + max_end) // 2),
            ((pl.col("start") + pl.col("end")) // 2),
        )
        .cast(pl.Int64)
        .alias("summit"),
    )
    df = df.with_columns(
        (pl.col("total_signal") / pl.col("width").cast(pl.Float64))
        .fill_nan(None)
        .alias("signal_density"),
        (pl.col("total_signal") + 1.0).log10().alias("log10_total_signal"),
    )
    return df.select(list(EXPECTED_SCHEMA)).sort(["sample", "chr", "start"])
