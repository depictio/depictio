"""Genome-browser track manifest: one row per track file the run published.

nf-core/rnaseq names every per-sample output after the samplesheet ``sample``,
so the manifest is spelled out from the samplesheet rather than globbed: the
strand-specific bigWig coverage (``.forward`` / ``.reverse``, named after the
genomic strand: the pipeline swaps the two for a reverse-stranded library) and
the duplicate-marked BAM of the default STAR + Salmon route, all relative to
DATA_ROOT (the ``aligner_star_salmon/`` directory of a multi-route run).

Row order is what the browser opens on (``initial_tracks`` shows the first
rows): replicate 1 of every condition before replicate 2, and for each sample its
forward and reverse coverage followed by its BAM (10 to 16 GB each in the
megatest, read by range). The opening tracks thus hold one representative library
per condition, in the design's order, with the reads whose splice arcs
(``show_junctions``) the browser draws over the coverage.

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every
  expected row is kept and read in place under that results folder;
- otherwise the rows whose file is present under DATA_ROOT are kept and the CLI
  uploads them at ingestion (all rows are kept when none is present, so a
  tables-only run still lists what the pipeline publishes).

Output schema:
    track_id : Utf8     `<sample>.<kind>`, unique per file
    sample : Utf8       the sample the file belongs to (links to `samplesheet`)
    condition : Utf8    read off the `<condition>_REP<n>` sample name; the tile colours by it
                        (``color_by``), in the colours the dashboard declares for it
    strand : Utf8       forward / reverse for the coverage, empty for the BAM
    kind : Utf8         coverage_forward / coverage_reverse / alignments
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
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
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
    "category": pl.Utf8,
    "order": pl.Int64,
}

_ROOT = "star_salmon"
# (kind, strand, format, path template, category)
_COVERAGE = [
    ("coverage_forward", "forward", "bigwig", f"{_ROOT}/bigwig/{{s}}.forward.bigWig", "Coverage"),
    ("coverage_reverse", "reverse", "bigwig", f"{_ROOT}/bigwig/{{s}}.reverse.bigWig", "Coverage"),
]
_BAM = ("alignments", "", "bam", f"{_ROOT}/{{s}}.markdup.sorted.bam", "Alignments")

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
            "category": category,
        }

    # Per sample: both strands, then the reads. Stranded libraries put a gene's
    # signal on one strand only, so the pair opens together.
    rows = [row_for(s, spec) for s in samples for spec in (*_COVERAGE, _BAM)]

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
