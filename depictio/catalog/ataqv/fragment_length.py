"""Fragment-length distribution of every ATAC library, in long form.

``ataqv`` records the whole fragment-length histogram in its per-library JSON as
``metrics.fragment_length_counts``, a list of rows described by
``metrics.fragment_length_counts_fields`` (``fragment_length``, ``read_count``,
``fraction_of_all_reads``). This recipe stacks those histograms into one long
table so the nucleosome ladder of every library can be drawn on one axis.

``fragment_class`` uses ataqv's own cut-offs: it counts fragments up to 100 bp as
the transcription-factor (sub-nucleosomal) window and 150 to 324 bp as the
mononucleosomal one, which is what ``hqaa_tf_count`` and
``hqaa_mononucleosomal_count`` in the metrics table are built from.

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
    fragment_class : Utf8          sub-nucleosomal / transitional /
                                   mononucleosomal / multi-nucleosomal
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
    "fragment_length": pl.Int64,
    "read_count": pl.Int64,
    "fraction_of_all_reads": pl.Float64,
    "fragment_class": pl.Utf8,
}

# ataqv's own windows: <= 100 bp is the TF (sub-nucleosomal) count, 150-324 bp
# the mononucleosomal one. The gap between them is the transition.
_SUB_NUCLEOSOMAL_MAX = 100
_MONONUCLEOSOMAL_MIN = 150
_MONONUCLEOSOMAL_MAX = 324

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
        pl.when(length <= _SUB_NUCLEOSOMAL_MAX)
        .then(pl.lit("sub-nucleosomal"))
        .when(length < _MONONUCLEOSOMAL_MIN)
        .then(pl.lit("transitional"))
        .when(length <= _MONONUCLEOSOMAL_MAX)
        .then(pl.lit("mononucleosomal"))
        .otherwise(pl.lit("multi-nucleosomal"))
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
    return df.select(list(EXPECTED_SCHEMA)).sort(["sample", "fragment_length"])
