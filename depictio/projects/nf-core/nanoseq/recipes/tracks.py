"""Genome-browser track manifest: one row per track file the run published.

nf-core/nanoseq names every per-sample output after the validated samplesheet's
``sample`` (the ``<group>_R<replicate>`` name the pipeline builds), so the
manifest is spelled out from that sheet rather than globbed: for each sample the
coverage bigWig and the coordinate-sorted long-read BAM, under the aligner's
folder (``minimap2/``, or ``graphmap2/`` when the run used GraphMap2).

    <aligner>/bigwig/<sample>.bigWig     coverage (unstranded; --skip_bigwig drops it)
    <aligner>/<sample>.sorted.bam        alignments, with its .bai next to it

The per-read BED12 / bigBed files (``<aligner>/bigbed/``, directRNA and cDNA
runs only) are left out on purpose: they repeat what the BAM shows read by read
and weigh 30 to 130 MB per sample.

Row order is what the browser opens on (``initial_tracks`` shows the first
rows): the coverage of replicate 1 of every condition before replicate 2, the
BAMs last (0.7 to 2.8 GB each in the megatest).

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every
  expected row is kept and read in place under that results folder, on the
  first aligner folder;
- otherwise the rows whose file is present under DATA_ROOT are kept and the CLI
  uploads them at ingestion (all rows are kept when none is present, so a
  tables-only run still lists what the pipeline publishes).

Output schema:
    track_id : Utf8     `<sample>.<kind>`, unique per file
    sample : Utf8       the sample the file belongs to (links to `samples`)
    condition : Utf8    read off the `<group>_R<n>` sample name
    kind : Utf8         coverage / alignments
    format : Utf8       bigwig / bam
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    color : Utf8        per-condition colour
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
        ref="samplesheet",
        path="pipeline_info/samplesheet.valid.csv",
        format="CSV",
        input_schema={"sample": pl.Utf8},
        read_kwargs={"infer_schema_length": 0},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample": pl.Utf8,
    "condition": pl.Utf8,
    "kind": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "color": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}

# Aligner folders, in order of preference.
_ALIGNERS = ("minimap2", "graphmap2")
# (kind, format, path template, category, name)
_COVERAGE = ("coverage", "bigwig", "{a}/bigwig/{s}.bigWig", "Coverage", "{s} coverage")
_BAM = ("alignments", "bam", "{a}/{s}.sorted.bam", "Alignments", "{s} reads")

# One colour per condition, assigned in sorted order.
_PALETTE = [
    "rgb(31,119,180)",
    "rgb(214,39,40)",
    "rgb(44,160,44)",
    "rgb(148,103,189)",
    "rgb(255,127,14)",
    "rgb(23,190,207)",
]

# `<group>_R<replicate>`, the sample name the pipeline builds from the sheet.
_PIPELINE_ID = re.compile(r"^(?P<condition>.+)_R(?P<replicate>\d+)$")


def _split(name: str) -> tuple[str, int]:
    match = _PIPELINE_ID.match(name)
    if not match:
        return name, 1
    return match.group("condition"), int(match.group("replicate"))


def transform(sources: dict[str, pl.DataFrame], context=None) -> pl.DataFrame:
    """Spell out the expected track files of every sample of the sheet."""
    sheet = sources["samplesheet"]
    if "sample" not in sheet.columns:
        raise ValueError(f"nanoseq tracks: samplesheet has no sample column ({sheet.columns})")

    samples = sorted(
        {str(s).strip() for s in sheet["sample"].to_list() if s},
        key=lambda s: (_split(s)[1], s),
    )
    conditions = sorted({_split(s)[0] for s in samples})
    colors = {c: _PALETTE[i % len(_PALETTE)] for i, c in enumerate(conditions)}

    def uri_for(sample: str, template: str) -> str:
        """The first aligner folder the run holds; the first one when none (or in place)."""
        paths = [template.format(a=a, s=sample) for a in _ALIGNERS]
        if context is None or context.reads_in_place:
            return paths[0]
        return next((p for p in paths if context.exists(p)), paths[0])

    def row_for(sample: str, spec: tuple[str, str, str, str, str]) -> dict[str, str]:
        kind, fmt, template, category, name = spec
        condition = _split(sample)[0]
        return {
            "track_id": f"{sample}.{kind}",
            "sample": sample,
            "condition": condition,
            "kind": kind,
            "format": fmt,
            "uri": uri_for(sample, template),
            "name": name.format(s=sample),
            "color": colors[condition],
            "category": category,
        }

    rows = [row_for(s, _COVERAGE) for s in samples]
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
