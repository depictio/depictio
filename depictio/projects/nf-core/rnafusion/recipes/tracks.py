"""Genome-browser track manifest: one row per track file the run published.

nf-core/rnafusion names every per-sample output after the samplesheet
``sample``, so the manifest is spelled out from the sheet rather than globbed:
the run's one genome-aligned track per sample is the STAR alignment,

    star/<sample>.Aligned.sortedByCoord.out.bam   with its .bai next to it
    star/<sample>.Aligned.sortedByCoord.out.cram  instead, with its .crai,
                                                  when the run used --cram

rnafusion publishes no bigWig, and the FusionInspector alignments are made
against a fusion-contig reference, not the genome, so they are not tracks. The
fusion breakpoints themselves are not a track either: the browser frames them
(the `locus_from` of the Breakpoints tab).

Row order is what the browser opens on (``initial_tracks`` shows the first
rows): the samples in sheet order.

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every
  expected row is kept and read in place under that results folder, on the BAM
  layout;
- otherwise the rows whose file is present under DATA_ROOT are kept and the CLI
  uploads them at ingestion (all rows are kept when none is present, so a
  tables-only run still lists what the pipeline publishes).

Output schema:
    track_id : Utf8     `<sample>.alignments`, unique per file
    sample : Utf8       the sample the file belongs to (links to `samplesheet`)
    kind : Utf8         alignments
    format : Utf8       bam / cram
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    color : Utf8        per-sample colour
    category : Utf8     track-selector folder
    order : Int64       row order the browser opens with (``order_column``)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        input_schema={"sample": pl.Utf8},
        read_kwargs={"infer_schema_length": 0},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample": pl.Utf8,
    "kind": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "color": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}

# (format, path template), in order of preference.
_ALIGNMENTS = (
    ("bam", "star/{s}.Aligned.sortedByCoord.out.bam"),
    ("cram", "star/{s}.Aligned.sortedByCoord.out.cram"),
)

# One colour per sample, in sheet order.
_PALETTE = [
    "rgb(31,119,180)",
    "rgb(214,39,40)",
    "rgb(44,160,44)",
    "rgb(148,103,189)",
    "rgb(255,127,14)",
    "rgb(23,190,207)",
]


def transform(sources: dict[str, pl.DataFrame], context=None) -> pl.DataFrame:
    """Spell out the expected alignment file of every sample of the sheet."""
    sheet = sources["samplesheet"]
    if "sample" not in sheet.columns:
        raise ValueError(f"rnafusion tracks: samplesheet has no sample column ({sheet.columns})")
    samples = list(dict.fromkeys(str(s).strip() for s in sheet["sample"].to_list() if s))

    def pick(sample: str) -> tuple[str, str]:
        """The first alignment file the run holds; the BAM when none (or in place)."""
        candidates = [(fmt, template.format(s=sample)) for fmt, template in _ALIGNMENTS]
        if context is None or context.reads_in_place:
            return candidates[0]
        return next(((f, p) for f, p in candidates if context.exists(p)), candidates[0])

    rows = []
    for i, sample in enumerate(samples):
        fmt, uri = pick(sample)
        rows.append(
            {
                "track_id": f"{sample}.alignments",
                "sample": sample,
                "kind": "alignments",
                "format": fmt,
                "uri": uri,
                "name": f"{sample} reads",
                "color": _PALETTE[i % len(_PALETTE)],
                "category": "Alignments",
            }
        )

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
