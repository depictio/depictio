"""Where a library's reads land on the annotation, from RSeQC read_distribution.

``<sample>.read_distribution.txt`` is a fixed-width report, not a table: three
header totals, a rule, a block of one row per annotation feature, another rule.
It is read here as raw lines and parsed, because a delimiter-based read would
split on the padding.

Two things the raw file does not say straight out, and this recipe fixes:

* **The upstream and downstream bands nest.** ``TSS_up_5kb`` counts the tags in
  ``TSS_up_1kb`` again, and ``TSS_up_10kb`` counts both. Stacking the rows as
  published triple counts the promoter signal. The bands are therefore
  differenced into disjoint rings (1kb, 1 to 5kb, 5 to 10kb), which is what
  MultiQC's own RSeQC panel does.
* **Assigned is not total.** Tags that fall in none of the features are only
  visible as ``Total Tags`` minus ``Total Assigned Tags``; they are published
  here as an explicit ``Other_intergenic`` row so the composition sums to one.

The report is fixed-width, so the scan reads it as one text column per line with
``quote_char: null`` (``5'UTR_Exons`` would otherwise open a quoted field that
never closes) and ``include_file_paths: source_path``, which is where the sample
name comes from.

The frame is long and carries two resolutions, the way
``enchantr/v_gene_usage`` does: ``rank`` is ``Region class`` (exonic, intronic,
promoter, downstream, other) or ``Feature`` (the individual RSeQC rows), so one
composition tile switches between the coarse and the fine view.

Output:
    sample_id : Utf8       recovered from the file name
    rank : Utf8            "Region class" or "Feature"
    taxon : Utf8           the class or feature name
    region_class : Utf8    the class, filled in on feature rows too
    tag_count : Int64      tags in this class or feature
    abundance : Float64    share of the sample's total tags
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# The sample name lives only in the file name, and `pl.read_csv` (what a recipe
# glob source goes through) has no `include_file_paths`. So this is the raw-scan
# two-step: a recursive scan DC reads every report as raw lines with the path
# attached, and this recipe consumes it by tag.
RAW_DC_TAG = "rseqc_read_distribution_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="report", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "rank": pl.Utf8,
    "taxon": pl.Utf8,
    "region_class": pl.Utf8,
    "tag_count": pl.Int64,
    "abundance": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_TOTAL = re.compile(r"^Total\s+(Reads|Tags|Assigned Tags)\s+(\d+)\s*$")
_ROW = re.compile(r"^(\S+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s*$")
_SUFFIX = ".read_distribution.txt"

# Feature -> the class it is rolled up into. The nested upstream and downstream
# bands are differenced first (see `_disjoint`), so every key here is disjoint.
_CLASS: dict[str, str] = {
    "CDS_Exons": "Exonic",
    "5'UTR_Exons": "Exonic",
    "3'UTR_Exons": "Exonic",
    "Introns": "Intronic",
    "TSS_up_1kb": "Promoter",
    "TSS_up_1kb_5kb": "Promoter",
    "TSS_up_5kb_10kb": "Promoter",
    "TES_down_1kb": "Downstream",
    "TES_down_1kb_5kb": "Downstream",
    "TES_down_5kb_10kb": "Downstream",
    "Other_intergenic": "Other intergenic",
}
_NESTED = [
    ("TSS_up_1kb_5kb", "TSS_up_5kb", "TSS_up_1kb"),
    ("TSS_up_5kb_10kb", "TSS_up_10kb", "TSS_up_5kb"),
    ("TES_down_1kb_5kb", "TES_down_5kb", "TES_down_1kb"),
    ("TES_down_5kb_10kb", "TES_down_10kb", "TES_down_5kb"),
]


def _sample_id(source_path: str) -> str:
    name = source_path.rsplit("/", 1)[-1]
    return name[: -len(_SUFFIX)] if name.endswith(_SUFFIX) else name.split(".")[0]


def _disjoint(counts: dict[str, int], total_tags: int, assigned: int) -> dict[str, int]:
    """Turn RSeQC's nested upstream and downstream bands into disjoint rings."""
    out = {
        key: counts.get(key, 0)
        for key in (
            "CDS_Exons",
            "5'UTR_Exons",
            "3'UTR_Exons",
            "Introns",
            "TSS_up_1kb",
            "TES_down_1kb",
        )
    }
    for name, outer, inner in _NESTED:
        out[name] = max(counts.get(outer, 0) - counts.get(inner, 0), 0)
    out["Other_intergenic"] = max(total_tags - assigned, 0)
    return out


def _parse_one(lines: list[str], source_path: str) -> list[dict]:
    totals: dict[str, int] = {}
    counts: dict[str, int] = {}
    for raw in lines:
        line = (raw or "").rstrip()
        match = _TOTAL.match(line)
        if match:
            totals[match.group(1)] = int(match.group(2))
            continue
        match = _ROW.match(line)
        if match and match.group(1) != "Group":
            counts[match.group(1)] = int(match.group(3))
    if not counts:
        return []

    total_tags = totals.get("Tags") or sum(counts.values())
    assigned = totals.get("Assigned Tags") or sum(counts.values())
    features = _disjoint(counts, total_tags, assigned)
    denominator = total_tags or 1
    sample_id = _sample_id(source_path)

    rows = [
        {
            "sample_id": sample_id,
            "rank": "Feature",
            "taxon": feature,
            "region_class": _CLASS[feature],
            "tag_count": count,
            "abundance": count / denominator,
        }
        for feature, count in features.items()
    ]
    by_class: dict[str, int] = {}
    for feature, count in features.items():
        by_class[_CLASS[feature]] = by_class.get(_CLASS[feature], 0) + count
    rows += [
        {
            "sample_id": sample_id,
            "rank": "Region class",
            "taxon": region,
            "region_class": region,
            "tag_count": count,
            "abundance": count / denominator,
        }
        for region, count in by_class.items()
    ]
    return rows


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Parse one report per sample into a two-resolution composition frame."""
    df = sources["report"]
    rows: list[dict] = []
    for source_path, group in df.group_by("source_path"):
        path = source_path[0] if isinstance(source_path, tuple) else source_path
        rows += _parse_one(group.get_column("line").to_list(), str(path))
    if not rows:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA).sort(["sample_id", "rank", "taxon"])
