"""Genome-browser track manifest: one row per track file the run published.

nf-core/rnaseq names every per-sample output after the samplesheet ``sample``,
so the manifest is spelled out from the samplesheet rather than globbed: the
strand-specific bigWig coverage (``.forward`` / ``.reverse``, named after the
genomic strand: the pipeline swaps the two for a reverse-stranded library) and
the duplicate-marked BAM of the default STAR + Salmon route, all relative to
DATA_ROOT (the ``aligner_star_salmon/`` directory of a multi-route run).

Row order is what the browser opens on (``initial_tracks`` shows the first
rows): the bigWig pairs first, replicate 1 of every condition before
replicate 2, the BAMs last (10 to 16 GB each in the megatest).

Two ways the files are read, decided by what the run folder holds:
- the track files are present under DATA_ROOT: only those rows are kept, and
  the CLI uploads them next to the manifest at ingestion;
- none is present (the tables-only megatest subset): every expected row is kept
  and the collection reads them in place under ``TRACKS_URI`` (the template sets
  ``remote_base_uri`` from it).

Output schema:
    track_id : Utf8     `<sample>.<kind>`, unique per file
    sample : Utf8       the sample the file belongs to (links to `samplesheet`)
    condition : Utf8    read off the `<condition>_REP<n>` sample name
    strand : Utf8       forward / reverse for the coverage, empty for the BAM
    kind : Utf8         coverage_forward / coverage_reverse / alignments
    format : Utf8       bigwig / bam
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    color : Utf8        per-condition colour, the reverse strand a lighter shade
    category : Utf8     track-selector folder
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
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
}

_ROOT = "star_salmon"
# (kind, strand, format, path template, category)
_COVERAGE = [
    ("coverage_forward", "forward", "bigwig", f"{_ROOT}/bigwig/{{s}}.forward.bigWig", "Coverage"),
    ("coverage_reverse", "reverse", "bigwig", f"{_ROOT}/bigwig/{{s}}.reverse.bigWig", "Coverage"),
]
_BAM = ("alignments", "", "bam", f"{_ROOT}/{{s}}.markdup.sorted.bam", "Alignments")

# (forward / BAM, reverse) shade per condition, assigned in sorted order.
_PALETTE = [
    ("rgb(31,119,180)", "rgb(140,186,222)"),
    ("rgb(214,39,40)", "rgb(237,146,146)"),
    ("rgb(44,160,44)", "rgb(150,212,150)"),
    ("rgb(148,103,189)", "rgb(199,175,222)"),
    ("rgb(255,127,14)", "rgb(255,187,125)"),
    ("rgb(23,190,207)", "rgb(155,222,230)"),
]

# `GM12878_REP1`, `treated_rep2`, `ctrl_R3`: the same split the samplesheet
# recipe makes, so `condition` agrees with the hub.
_REPLICATE = re.compile(r"^(?P<condition>.+?)[._-](?:rep|r)?(?P<replicate>\d+)$", re.IGNORECASE)


def _split(name: str) -> tuple[str, int]:
    match = _REPLICATE.match(name)
    if not match:
        return name, 1
    return match.group("condition"), int(match.group("replicate"))


def transform(sources: dict[str, pl.DataFrame], context=None) -> pl.DataFrame:
    """Spell out the expected track files of every sample."""
    sheet = sources["samplesheet"]
    sample_col = next(
        (c for c in sheet.columns if c.lower() in ("sample", "sample_id", "sampleid")),
        None,
    )
    if sample_col is None:
        raise ValueError(f"rnaseq tracks: samplesheet has no sample column ({sheet.columns})")

    # A sample sequenced over several runs has several sheet rows, one output.
    samples = sorted(
        {str(s).strip() for s in sheet[sample_col].to_list() if s},
        key=lambda s: (_split(s)[1], s),
    )
    conditions = sorted({_split(s)[0] for s in samples})
    colors = {c: _PALETTE[i % len(_PALETTE)] for i, c in enumerate(conditions)}

    def row_for(sample: str, spec: tuple[str, str, str, str, str]) -> dict[str, str]:
        kind, strand, fmt, template, category = spec
        condition = _split(sample)[0]
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

    if context is not None and any(context.exists(r["uri"]) for r in rows):
        rows = [r for r in rows if context.exists(r["uri"])]
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA)
