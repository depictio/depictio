"""Reads per reference sequence, per library, from the ataqv JSON reports.

``ataqv`` records how many reads landed on each reference sequence as
``metrics.chromosome_counts``, a list of ``[reference, read_count]`` rows. Stacked
across libraries this is the read-distribution matrix an ATAC run is checked on:
one autosome carrying a disproportionate share, or a mitochondrial contig
dominating, both show up here before any peak is called.

Reading the JSON through the recipe loader
------------------------------------------
The loader reads CSV / TSV / Parquet only, so the report is read as a one-column
CSV with a separator that cannot occur in JSON text (``\\x1f``) and no quote
character: every line of every matched file arrives verbatim, in file order.
Re-joining them yields the concatenation of the reports, which a streaming JSON
decoder walks document by document.

Output schema:
    sample : Utf8              library ataqv reported on
    chromosome : Utf8          reference sequence name
    read_count : Int64         reads aligned to it
    fraction_of_reads : Float64  read_count over the library's counted reads
    log10_read_count : Float64   log10(read_count + 1), the colour axis
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
    "chromosome": pl.Utf8,
    "read_count": pl.Int64,
    "fraction_of_reads": pl.Float64,
    "log10_read_count": pl.Float64,
}

_COUNTS_KEY = "chromosome_counts"


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


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per library and reference sequence, with its share of the reads."""
    rows: list[dict] = []
    for record in read_reports(sources["reports"]):
        metrics = record["metrics"]
        sample = metrics.get("name") or (metrics.get("library") or {}).get("sample")
        for entry in metrics.get(_COUNTS_KEY) or []:
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            rows.append({"sample": sample, "chromosome": entry[0], "read_count": entry[1]})

    if not rows:
        raise ValueError("ataqv_chromosome_counts: no report carried per-reference read counts")

    df = pl.DataFrame(rows, infer_schema_length=None).with_columns(
        pl.col("sample").cast(pl.Utf8),
        pl.col("chromosome").cast(pl.Utf8),
        pl.col("read_count").cast(pl.Int64, strict=False),
    )
    return (
        df.with_columns(
            (pl.col("read_count") / pl.col("read_count").sum().over("sample")).alias(
                "fraction_of_reads"
            ),
            (pl.col("read_count") + 1).log10().alias("log10_read_count"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "chromosome"])
    )
