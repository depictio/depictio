"""Genome-browser track manifest: one row per track file the run published.

nf-core/rnasplice names every per-sample output after the sample of the
validated sheet (``pipeline_info/samplesheet.valid.csv``, the sheet the hub
reads: a sample sequenced over several runs has one row per run, suffixed
``_T1``, ``_T2``..., which the pipeline merges), so the manifest is spelled out
from that sheet rather than globbed. For each sample, under the aligner's
folder (``star_salmon/``):

    star_salmon/bigwig/<sample>.forward.bigWig, .reverse.bigWig
                                       strand-specific coverage (--skip_bigwig
                                       drops it)
    star_salmon/<sample>_sorted.bam    coordinate-sorted genome alignments, with
                                       its .bai (published with
                                       --save_align_intermeds only)

The STAR junction tables (``star_salmon/log/<sample>.SJ.out.tab``) are not a
format a genome browser reads, so there is no junction track; the sashimi of the
Splicing Events tab draws them.

Row order is what the browser opens on (``initial_tracks`` shows the first
rows): the coverage pairs first, the first sample of every condition before the
second, the BAMs last (15 GB each in a full run).

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every
  expected row is kept and read in place under that results folder;
- otherwise the rows whose file is present under DATA_ROOT are kept and the CLI
  uploads them at ingestion (all rows are kept when none is present, so a
  tables-only run still lists what the pipeline publishes).

Output schema:
    track_id : Utf8     `<sample>.<kind>`, unique per file
    sample : Utf8       the sample the file belongs to (links to `samples`)
    condition : Utf8    the sheet's condition
    strand : Utf8       forward / reverse for the coverage, empty for the BAM
    kind : Utf8         coverage_forward / coverage_reverse / alignments
    format : Utf8       bigwig / bam
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    color : Utf8        per-condition colour, the reverse strand a lighter shade
    category : Utf8     track-selector folder
    order : Int64       row order the browser opens with (``order_column``)
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="sheet",
        path="pipeline_info/samplesheet.valid.csv",
        format="csv",
        input_schema={"sample": pl.Utf8, "condition": pl.Utf8},
        read_kwargs={"infer_schema_length": 0},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample": pl.Utf8,
    "condition": pl.Utf8,
    "strand": pl.Utf8,
    "kind": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "color": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}

_ROOT = "star_salmon"
# (kind, strand, format, path template, category)
_COVERAGE = [
    ("coverage_forward", "forward", "bigwig", f"{_ROOT}/bigwig/{{s}}.forward.bigWig", "Coverage"),
    ("coverage_reverse", "reverse", "bigwig", f"{_ROOT}/bigwig/{{s}}.reverse.bigWig", "Coverage"),
]
_BAM = ("alignments", "", "bam", f"{_ROOT}/{{s}}_sorted.bam", "Alignments")

# (forward / BAM, reverse) shade per condition, assigned in sorted order.
_PALETTE = [
    ("rgb(31,119,180)", "rgb(140,186,222)"),
    ("rgb(214,39,40)", "rgb(237,146,146)"),
    ("rgb(44,160,44)", "rgb(150,212,150)"),
    ("rgb(148,103,189)", "rgb(199,175,222)"),
    ("rgb(255,127,14)", "rgb(255,187,125)"),
    ("rgb(23,190,207)", "rgb(155,222,230)"),
]

# The suffix the sheet check adds to the runs of one sample.
_RUN_SUFFIX = re.compile(r"_T\d+$")


def transform(sources: dict[str, pl.DataFrame], context=None) -> pl.DataFrame:
    """Spell out the expected track files of every sample of the sheet."""
    sheet = sources["sheet"]
    # One entry per sample, in sheet order: the runs of a sample collapse to it.
    conditions_of: dict[str, str] = {}
    for record in sheet.to_dicts():
        sample = _RUN_SUFFIX.sub("", str(record.get("sample") or "").strip())
        if sample and sample not in conditions_of:
            conditions_of[sample] = str(record.get("condition") or "").strip() or sample

    # The first sample of every condition before the second.
    seen: dict[str, int] = {}
    rank: dict[str, int] = {}
    for sample, condition in conditions_of.items():
        seen[condition] = seen.get(condition, 0) + 1
        rank[sample] = seen[condition]
    # sorted() is stable: ties keep the sheet's order.
    samples = sorted(conditions_of, key=lambda s: rank[s])
    conditions = sorted(set(conditions_of.values()))
    colors = {c: _PALETTE[i % len(_PALETTE)] for i, c in enumerate(conditions)}

    def row_for(sample: str, spec: tuple[str, str, str, str, str]) -> dict[str, str]:
        kind, strand, fmt, template, category = spec
        condition = conditions_of[sample]
        return {
            "track_id": f"{sample}.{kind}",
            "sample": sample,
            "condition": condition,
            "strand": strand,
            "kind": kind,
            "format": fmt,
            "uri": template.format(s=sample),
            "name": f"{sample} {strand}" if strand else f"{sample} alignments",
            "color": colors[condition][1 if strand == "reverse" else 0],
            "category": category,
        }

    rows = [row_for(s, spec) for s in samples for spec in _COVERAGE]
    rows += [row_for(s, _BAM) for s in samples]

    if (
        context is not None
        and not context.reads_in_place
        and any(context.exists(r["uri"]) for r in rows)
    ):
        rows = [r for r in rows if context.exists(r["uri"])]
    # Ingestion reorders rows (clustering on link columns): keep the intended
    # order explicit, the browser opens on the first `initial_tracks`.
    for i, row in enumerate(rows, start=1):
        row["order"] = i
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA)
