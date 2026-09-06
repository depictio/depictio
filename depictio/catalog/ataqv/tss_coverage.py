"""Coverage profile around transcription start sites, in long form.

``ataqv`` records the aggregate read coverage in a window centred on every TSS of
the annotation it was given as ``metrics.tss_coverage``: a list of
``[position, coverage]`` rows whose first field is a 1-based offset into the
window. The window is symmetric, so this recipe recentres it on the TSS: an
odd-length profile of ``2n + 1`` points becomes ``-n .. +n``.

The peak of that curve over its flanking background is the TSS enrichment score
the metrics table carries; the curve itself is what says whether the enrichment
is a sharp signal or a broad shoulder.

Reading the JSON through the recipe loader
------------------------------------------
The loader reads CSV / TSV / Parquet only, so the report is read as a one-column
CSV with a separator that cannot occur in JSON text (``\\x1f``) and no quote
character: every line of every matched file arrives verbatim, in file order.
Re-joining them yields the concatenation of the reports, which a streaming JSON
decoder walks document by document.

Output schema:
    sample : Utf8       library ataqv reported on
    position : Int64    signed distance from the TSS in bp (0 is the TSS)
    coverage : Float64  aggregate normalised coverage at that offset
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
    "position": pl.Int64,
    "coverage": pl.Float64,
}

_COVERAGE_KEY = "tss_coverage"


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
    """Recentre every library's TSS window on the start site and stack them."""
    rows: list[dict] = []
    for record in read_reports(sources["reports"]):
        metrics = record["metrics"]
        sample = metrics.get("name") or (metrics.get("library") or {}).get("sample")
        profile = metrics.get(_COVERAGE_KEY) or []
        if not profile:
            continue
        # ataqv writes 1-based offsets across a window symmetric about the TSS.
        centre = (len(profile) + 1) // 2
        for entry in profile:
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            rows.append({"sample": sample, "position": entry[0] - centre, "coverage": entry[1]})

    if not rows:
        raise ValueError("ataqv_tss_coverage: no report carried a TSS coverage profile")

    df = pl.DataFrame(rows, infer_schema_length=None).with_columns(
        pl.col("sample").cast(pl.Utf8),
        pl.col("position").cast(pl.Int64, strict=False),
        pl.col("coverage").cast(pl.Float64, strict=False),
    )
    return df.select(list(EXPECTED_SCHEMA)).sort(["sample", "position"])
