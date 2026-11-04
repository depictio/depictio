"""Fragment-length distribution of every ATAC library, in long form.

``ataqv`` records the whole fragment-length histogram in its per-library JSON as
``metrics.fragment_length_counts``, a list of rows described by
``metrics.fragment_length_counts_fields`` (``fragment_length``, ``read_count``,
``fraction_of_all_reads``). This recipe stacks those histograms into one long
table so the nucleosome ladder of every library can be drawn on one axis.

``fragment_class`` uses the two windows ataqv itself counts: fragments of 50 to
100 bp (``hqaa_short_count``, reported as ``hqaa_tf_count``) and of 150 to 200 bp
(``hqaa_mononucleosomal_count``), which are what those two columns of the metrics
table are built from. Every other length is ``outside ataqv windows``: ataqv
defines no further class, so none is invented here.
Source: ataqv src/cpp/Metrics.cpp, lines 907 (``50 <= fragment_length &&
fragment_length <= 100``) and 911 (``150 <= fragment_length && fragment_length
<= 200``), https://github.com/ParkerLab/ataqv/blob/master/src/cpp/Metrics.cpp

Reading the JSON through the recipe loader
------------------------------------------
The loader reads CSV / TSV / Parquet only, so the report is read as a one-column
CSV with a separator that cannot occur in JSON text (``\\x1f``) and no quote
character: every line of every matched file arrives verbatim, in file order.
Re-joining them yields the concatenation of the reports, which a streaming JSON
decoder walks document by document.

Output schema:
    sample : Utf8                  library ataqv reported on
    fragment_length : Int64        fragment length in bp
    read_count : Int64             reads with that fragment length
    fraction_of_all_reads : Float64  read_count over all reads of the library
    fragment_class : Utf8          short (50-100 bp) / mononucleosomal
                                   (150-200 bp) / outside ataqv windows
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

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="reports",
        glob_pattern="**/*.ataqv.json",
        format="CSV",
        input_schema={
            "raw": pl.Utf8,
        },
        read_kwargs=_LINE_READ_KWARGS,
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "fragment_length": pl.Int64,
    "read_count": pl.Int64,
    "fraction_of_all_reads": pl.Float64,
    "fragment_class": pl.Utf8,
}

# ataqv's own counting windows (src/cpp/Metrics.cpp l.907 and l.911), both ends
# inclusive: 50-100 bp is hqaa_short_count (hqaa_tf_count in the report), 150-200 bp
# is hqaa_mononucleosomal_count. ataqv has no other fragment class.
_SHORT_MIN = 50
_SHORT_MAX = 100
_MONONUCLEOSOMAL_MIN = 150
_MONONUCLEOSOMAL_MAX = 200

SHORT_CLASS = "short (50-100 bp)"
MONONUCLEOSOMAL_CLASS = "mononucleosomal (150-200 bp)"
OTHER_CLASS = "outside ataqv windows"

_FIELDS_KEY = "fragment_length_counts_fields"
_COUNTS_KEY = "fragment_length_counts"


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


def _classify(length: pl.Expr) -> pl.Expr:
    return (
        pl.when(length.is_between(_SHORT_MIN, _SHORT_MAX))
        .then(pl.lit(SHORT_CLASS))
        .when(length.is_between(_MONONUCLEOSOMAL_MIN, _MONONUCLEOSOMAL_MAX))
        .then(pl.lit(MONONUCLEOSOMAL_CLASS))
        .otherwise(pl.lit(OTHER_CLASS))
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Stack every library's fragment-length histogram into one long table."""
    rows: list[dict] = []
    for record in read_reports(sources["reports"]):
        metrics = record["metrics"]
        sample = metrics.get("name") or (metrics.get("library") or {}).get("sample")
        fields = metrics.get(_FIELDS_KEY) or ["fragment_length", "read_count"]
        for entry in metrics.get(_COUNTS_KEY) or []:
            row = dict(zip(fields, entry))
            row["sample"] = sample
            rows.append(row)

    if not rows:
        raise ValueError("ataqv_fragment_length: no report carried a fragment-length histogram")

    df = pl.DataFrame(rows, infer_schema_length=None)
    for column in ("fragment_length", "read_count", "fraction_of_all_reads"):
        if column not in df.columns:
            df = df.with_columns(pl.lit(None).alias(column))
    df = df.with_columns(
        pl.col("sample").cast(pl.Utf8),
        pl.col("fragment_length").cast(pl.Int64, strict=False),
        pl.col("read_count").cast(pl.Int64, strict=False),
        pl.col("fraction_of_all_reads").cast(pl.Float64, strict=False),
    ).with_columns(_classify(pl.col("fragment_length")).alias("fragment_class"))
    return df.select(list(OUTPUT_SCHEMA)).sort(["sample", "fragment_length"])
