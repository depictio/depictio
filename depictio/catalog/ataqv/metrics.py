"""Per-library ATAC quality metrics from the ataqv JSON reports.

``ataqv`` writes one ``<library>.ataqv.json`` per library: a JSON array holding a
single record whose ``metrics`` object carries every number the tool computed.
This recipe keeps the ones an ATAC library is actually judged by and derives the
fractions that are usually quoted (mitochondrial, duplicate, HQAA), so the whole
run is one row per library.

Reading the JSON through the recipe loader
------------------------------------------
The loader reads CSV / TSV / Parquet only, so the report is read as a one-column
CSV with a separator that cannot occur in JSON text (``\\x1f``) and no quote
character: every line of every matched file arrives verbatim, in file order.
Re-joining them yields the concatenation of the reports, which a streaming JSON
decoder walks document by document. The alternative — one ``path`` source per
library — would hard-code the library names into the recipe.

Output schema:
    sample : Utf8                     library ataqv reported on
    tss_enrichment : Float64          coverage at the TSS over background
    total_reads : Int64               reads in the alignment
    hqaa : Int64                      high-quality autosomal alignments
    hqaa_fraction : Float64           hqaa / total_reads
    hqaa_in_peaks : Int64             HQAA falling inside a called peak
    hqaa_overlapping_peaks_percent : Float64   percent of HQAA inside peaks
    total_autosomal_reads : Int64     reads on autosomes
    total_mitochondrial_reads : Int64 reads on the mitochondrial contig
    mitochondrial_fraction : Float64  mitochondrial / total_reads
    duplicate_fraction : Float64      duplicate / total_reads
    duplicate_fraction_in_peaks : Float64      duplicate rate inside peaks
    duplicate_fraction_not_in_peaks : Float64  duplicate rate outside peaks
    peak_duplicate_ratio : Float64    in-peak over out-of-peak duplicate rate
    total_peaks : Int64               peaks ataqv was given
    total_peak_territory : Int64      bases covered by those peaks
    hqaa_tf_count : Int64             HQAA in sub-nucleosomal fragments
    hqaa_mononucleosomal_count : Int64  HQAA in mononucleosomal fragments
    short_mononucleosomal_ratio : Float64  sub-nucleosomal over mononucleosomal
    max_fraction_reads_from_single_autosome : Float64  worst autosome imbalance
    median_mapq : Float64             median mapping quality
    properly_paired_fraction : Float64  properly paired and mapped / total_reads
    maximum_proper_pair_fragment_size : Int64  longest proper pair observed
    ataqv_version : Utf8              version that wrote the report
"""

import json

import polars as pl

from depictio.models.models.transforms import RecipeSource

# A separator that cannot occur in JSON text, so every line arrives as one field.
_LINE_READ_KWARGS = {
    "has_header": False,
    "separator": "\x1f",
    "quote_char": None,
    "new_columns": ["raw"],
    "infer_schema_length": 0,
}

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="reports",
        glob_pattern="**/*.ataqv.json",
        format="CSV",
        read_kwargs=_LINE_READ_KWARGS,
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "tss_enrichment": pl.Float64,
    "total_reads": pl.Int64,
    "hqaa": pl.Int64,
    "hqaa_fraction": pl.Float64,
    "hqaa_in_peaks": pl.Int64,
    "hqaa_overlapping_peaks_percent": pl.Float64,
    "total_autosomal_reads": pl.Int64,
    "total_mitochondrial_reads": pl.Int64,
    "mitochondrial_fraction": pl.Float64,
    "duplicate_fraction": pl.Float64,
    "duplicate_fraction_in_peaks": pl.Float64,
    "duplicate_fraction_not_in_peaks": pl.Float64,
    "peak_duplicate_ratio": pl.Float64,
    "total_peaks": pl.Int64,
    "total_peak_territory": pl.Int64,
    "hqaa_tf_count": pl.Int64,
    "hqaa_mononucleosomal_count": pl.Int64,
    "short_mononucleosomal_ratio": pl.Float64,
    "max_fraction_reads_from_single_autosome": pl.Float64,
    "median_mapq": pl.Float64,
    "properly_paired_fraction": pl.Float64,
    "maximum_proper_pair_fragment_size": pl.Int64,
    "ataqv_version": pl.Utf8,
}

# metric key -> output column, for the numbers ataqv reports as they are.
_PASS_THROUGH = {
    "tss_enrichment": "tss_enrichment",
    "total_reads": "total_reads",
    "hqaa": "hqaa",
    "hqaa_in_peaks": "hqaa_in_peaks",
    "hqaa_overlapping_peaks_percent": "hqaa_overlapping_peaks_percent",
    "total_autosomal_reads": "total_autosomal_reads",
    "total_mitochondrial_reads": "total_mitochondrial_reads",
    "duplicate_fraction_in_peaks": "duplicate_fraction_in_peaks",
    "duplicate_fraction_not_in_peaks": "duplicate_fraction_not_in_peaks",
    "peak_duplicate_ratio": "peak_duplicate_ratio",
    "total_peaks": "total_peaks",
    "total_peak_territory": "total_peak_territory",
    "hqaa_tf_count": "hqaa_tf_count",
    "hqaa_mononucleosomal_count": "hqaa_mononucleosomal_count",
    "short_mononucleosomal_ratio": "short_mononucleosomal_ratio",
    "max_fraction_reads_from_single_autosome": "max_fraction_reads_from_single_autosome",
    "median_mapq": "median_mapq",
    "maximum_proper_pair_fragment_size": "maximum_proper_pair_fragment_size",
}


def read_reports(frame: pl.DataFrame) -> list[dict]:
    """Decode the concatenated ataqv JSON documents back into records."""
    if "raw" not in frame.columns:
        raise ValueError("ataqv: the report source did not load as one 'raw' text column")
    text = "\n".join(frame["raw"].to_list())
    decoder = json.JSONDecoder()
    records: list[dict] = []
    index, end = 0, len(text)
    while index < end:
        while index < end and text[index].isspace():
            index += 1
        if index >= end:
            break
        document, index = decoder.raw_decode(text, index)
        for record in document if isinstance(document, list) else [document]:
            if isinstance(record, dict) and isinstance(record.get("metrics"), dict):
                records.append(record)
    if not records:
        raise ValueError("ataqv: no report record carried a 'metrics' object")
    return records


def _ratio(numerator, denominator) -> float | None:
    """Guarded division: ataqv leaves a metric null when it could not compute it."""
    if numerator is None or not denominator:
        return None
    return float(numerator) / float(denominator)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per library, with the derived fractions ATAC QC is quoted in."""
    rows: list[dict] = []
    for record in read_reports(sources["reports"]):
        metrics = record["metrics"]
        total = metrics.get("total_reads")
        row: dict = {
            "sample": metrics.get("name") or (metrics.get("library") or {}).get("sample"),
            "ataqv_version": record.get("ataqv_version"),
            "hqaa_fraction": _ratio(metrics.get("hqaa"), total),
            "mitochondrial_fraction": _ratio(metrics.get("total_mitochondrial_reads"), total),
            "duplicate_fraction": _ratio(metrics.get("duplicate_reads"), total),
            "properly_paired_fraction": _ratio(
                metrics.get("properly_paired_and_mapped_reads"), total
            ),
        }
        row.update({column: metrics.get(key) for key, column in _PASS_THROUGH.items()})
        rows.append(row)

    df = pl.DataFrame(rows, infer_schema_length=None)
    for column, dtype in EXPECTED_SCHEMA.items():
        if column not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=dtype).alias(column))
    return df.select(
        [pl.col(column).cast(dtype, strict=False) for column, dtype in EXPECTED_SCHEMA.items()]
    ).sort("sample")
