"""Full-length read yield of ``isoseq refine`` per library: FL, FLNC and FLNC with poly(A).

``isoseq refine`` writes one ``<prefix>.filter_summary.report.json`` (pbcopper
report, id ``isoseq_refine``) per input, and a chunked run one per chunk. The
three counts it holds are the Iso-Seq funnel after primer removal: full-length
reads (both primers found, the input of refine), the full-length non-chimeric
reads (FLNC) it kept, and the FLNC that also carried a poly(A) tail. This
recipe sums the chunks back into one row per library and adds the two shares a
reader compares across libraries.

Sample ids follow ``pbccs/zmw_yield``: the library is the file prefix without the
chunk suffix, ``sample`` drops nf-core/isoseq's trailing ``_<row>`` counter.

Output schema (one row per library):
    sample : Utf8                sample the library belongs to
    library : Utf8               samplesheet row / SMRT cell prefix
    fl_reads : Int64             full-length reads refine read
    flnc_reads : Int64           full-length non-chimeric reads kept
    flnc_polya_reads : Int64     FLNC reads with a poly(A) tail
    chimeric_reads : Int64       fl_reads minus flnc_reads
    pct_flnc : Float64           flnc_reads over fl_reads, percent (2 decimals)
    pct_polya : Float64          flnc_polya_reads over flnc_reads, percent (2 decimals)
"""

from __future__ import annotations

import json
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="reports",
        glob_pattern="**/*.filter_summary.report.json",
        format="csv",
        read_kwargs={
            "separator": "\x1f",
            "quote_char": None,
            "has_header": False,
            "new_columns": ["raw"],
            "infer_schema_length": 0,
        },
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "library": pl.Utf8,
    "fl_reads": pl.Int64,
    "flnc_reads": pl.Int64,
    "flnc_polya_reads": pl.Int64,
    "chimeric_reads": pl.Int64,
    "pct_flnc": pl.Float64,
    "pct_polya": pl.Float64,
}

_CHUNK = re.compile(r"\.chunk\.?\d+$")
_COUNTS = {
    "num_reads_fl": "fl_reads",
    "num_reads_flnc": "flnc_reads",
    "num_reads_flnc_polya": "flnc_polya_reads",
}


def _library(path: str) -> str:
    base = path.rstrip("/").split("/")[-1].removesuffix(".filter_summary.report.json")
    return _CHUNK.sub("", base)


def _pct(num: str, den: str) -> pl.Expr:
    return (
        pl.when(pl.col(den) > 0)
        .then(pl.col(num) * 100.0 / pl.col(den))
        .otherwise(None)
        .cast(pl.Float64)
        .round(2)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    rows: list[dict] = []
    for (path,), group in sources["reports"].group_by(["source_path"], maintain_order=True):
        text = "\n".join(line or "" for line in group["raw"].to_list())
        try:
            report = json.loads(text)
        except json.JSONDecodeError:
            continue
        if report.get("id") != "isoseq_refine":
            continue
        row = {"library": _library(str(path)), **dict.fromkeys(_COUNTS.values(), 0)}
        for a in report.get("attributes") or []:
            key = _COUNTS.get(str(a.get("id", "")))
            if key is not None:
                row[key] = int(a.get("value") or 0)
        rows.append(row)
    if not rows:
        raise ValueError("isoseq refine: no filter summary report (id isoseq_refine) found")
    counts = list(_COUNTS.values())
    frame = pl.DataFrame(rows, schema={"library": pl.Utf8, **dict.fromkeys(counts, pl.Int64)})
    return (
        frame.group_by("library")
        .agg(pl.col(c).sum().cast(pl.Int64) for c in counts)
        .with_columns(
            pl.col("library").str.replace(r"_\d+$", "").alias("sample"),
            (pl.col("fl_reads") - pl.col("flnc_reads"))
            .clip(0)
            .cast(pl.Int64)
            .alias("chimeric_reads"),
            _pct("flnc_reads", "fl_reads").alias("pct_flnc"),
            _pct("flnc_polya_reads", "flnc_reads").alias("pct_polya"),
        )
        .sort("sample", "library")
        .select(list(EXPECTED_SCHEMA))
    )
