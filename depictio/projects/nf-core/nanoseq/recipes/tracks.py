"""Genome-browser track manifest: one row per track file the run published.

nf-core/nanoseq names every per-sample output after the validated samplesheet's
``sample`` (the ``<group>_R<replicate>`` name the pipeline builds), so the
manifest is spelled out from the template's ``samples`` hub rather than globbed:
for each sample the coverage bigWig and the coordinate-sorted long-read BAM,
under the aligner's folder (``minimap2/``, or ``graphmap2/`` when the run used
GraphMap2).

    <aligner>/bigwig/<sample>.bigWig     coverage (unstranded; --skip_bigwig drops it)
    <aligner>/<sample>.sorted.bam        alignments, with its .bai next to it

The per-read BED12 / bigBed files (``<aligner>/bigbed/``, directRNA and cDNA
runs only) are left out on purpose: they repeat what the BAM shows read by read
and weigh 30 to 130 MB per sample.

Row order is what the browser opens on (``initial_tracks`` shows the first
rows): replicate 1 of every condition before replicate 2, the conditions in the
hub's order, and within a sample the alignments before the coverage. This is the
exception to "light tracks first" of a long-read RNA run with no junction table:
the splice arcs the browser draws over the coverage (``show_junctions``) are read
from the BAM, so a BAM that opens last (0.7 to 2.8 GB each in the megatest, read
by range) leaves the arcs out. The opening rows are the reads of one library of
each condition, each with its coverage.

The condition is a column of the manifest under the name the dashboard's
``category_colors`` keys it by (``condition``, the hub's column: the design
table's ``GROUP_COL``, else the samplesheet group), which the tile colours by
(``color_by``), so a bar, a table row and a track share one hue per condition.
The manifest writes no colour of its own: a colour column would win over the
dashboard's palette.

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every
  expected row is kept and read in place under that results folder, on the
  first aligner folder;
- otherwise the rows whose file is present under DATA_ROOT are kept and the CLI
  uploads them at ingestion (all rows are kept when none is present, so a
  tables-only run still lists what the pipeline publishes).

Sources:
    hub        ``samples`` (this template's ``samples.py``): the samples, their condition
               and replicate

Output schema:
    track_id : Utf8     `<sample>.<kind>`, unique per file
    sample : Utf8       the sample the file belongs to (links to `samples`)
    condition : Utf8    the sample's condition (the hub's)
    kind : Utf8         coverage / alignments
    format : Utf8       bigwig / bam
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    category : Utf8     track-selector folder
    order : Int64       row order the browser opens with (``order_column``)
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(ref="hub", dc_ref="samples", input_schema={"sample_id": pl.Utf8}),
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
    "category": pl.Utf8,
    "order": pl.Int64,
}

# Aligner folders, in order of preference.
_ALIGNERS = ("minimap2", "graphmap2")
# (kind, format, path template, category, name)
_COVERAGE = ("coverage", "bigwig", "{a}/bigwig/{s}.bigWig", "Coverage", "{s} coverage")
_BAM = ("alignments", "bam", "{a}/{s}.sorted.bam", "Alignments", "{s} reads")

# `<group>_R<replicate>`, the sample name the pipeline builds from the sheet.
_PIPELINE_ID = re.compile(r"^(?P<condition>.+)_R(?P<replicate>\d+)$")


def _split(name: str) -> tuple[str, int]:
    match = _PIPELINE_ID.match(name)
    if not match:
        return name, 1
    return match.group("condition"), int(match.group("replicate"))


def _hub_samples(hub: pl.DataFrame) -> list[tuple[str, str, int]]:
    """``(sample, condition, replicate)`` of the hub's samples, the hub's own order."""
    if "sample_id" not in hub.columns:
        raise ValueError(f"nanoseq tracks: the samples hub has no sample_id ({hub.columns})")
    out: list[tuple[str, str, int]] = []
    for row in hub.to_dicts():
        sample = str(row["sample_id"] or "").strip()
        if not sample or any(sample == s for s, _, _ in out):
            continue
        guess_condition, guess_replicate = _split(sample)
        condition = row.get("condition") or guess_condition
        replicate = row.get("replicate")
        out.append((sample, str(condition), int(replicate) if replicate else guess_replicate))
    return out


def transform(sources: dict[str, pl.DataFrame], context=None) -> pl.DataFrame:
    """Spell out the expected track files of every sample of the hub."""
    members = _hub_samples(sources["hub"])
    # Conditions in the hub's order; replicate 1 of every condition before replicate 2.
    rank = {c: i for i, c in enumerate(dict.fromkeys(c for _, c, _ in members))}
    members.sort(key=lambda m: (m[2], rank[m[1]], m[0]))

    def uri_for(sample: str, template: str) -> str:
        """The first aligner folder the run holds; the first one when none (or in place)."""
        paths = [template.format(a=a, s=sample) for a in _ALIGNERS]
        if context is None or context.reads_in_place:
            return paths[0]
        return next((p for p in paths if context.exists(p)), paths[0])

    def row_for(
        sample: str, condition: str, spec: tuple[str, str, str, str, str]
    ) -> dict[str, str]:
        kind, fmt, template, category, name = spec
        return {
            "track_id": f"{sample}.{kind}",
            "sample": sample,
            "condition": condition,
            "kind": kind,
            "format": fmt,
            "uri": uri_for(sample, template),
            "name": name.format(s=sample),
            "category": category,
        }

    rows = [row_for(s, c, spec) for s, c, _ in members for spec in (_BAM, _COVERAGE)]

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
