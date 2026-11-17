"""Genome-browser track manifest: one row per track file the run published.

nf-core/cutandrun names every per-sample output `<group>_R<replicate>` (the
`sample_id` the `samples` recipe builds), so the manifest is spelled out from
the validated samplesheet rather than globbed: the bigWig signal, the SEACR
stringent and MACS2 narrowPeak calls (targets only; peak calling never runs on
an IgG control) and the marked-duplicate BAM.

3.2.2 keeps the 3.1 layout and adds `linear_dedup/` twins of the BAMs (written
when linear duplicate removal is on) and `04_reporting/igv/` copies of the
signal and the SEACR calls. Each kind lists the places its file can be, and the
first one the run holds wins, so a run published with another layout lists the
same rows.

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every
  expected row is kept and read in place under that results folder, at the
  first candidate path (nothing can be listed there);
- otherwise the rows whose file is present under DATA_ROOT are kept and the CLI
  uploads them at ingestion (all rows are kept when none is present, so a
  tables-only run still lists what the pipeline publishes). An empty file, such
  as the peak file of a sample a caller found nothing for, counts as absent.

Output schema:
    track_id : Utf8     `<sample_id>.<kind>`, unique per file
    sample_id : Utf8    the sample the file belongs to (links to `samples`)
    target : Utf8       the samplesheet group (mark or IgG control)
    kind : Utf8         signal / peaks_seacr / peaks_macs2 / alignments
    format : Utf8       bigwig / bed / narrowpeak / bam
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    color : Utf8        per-target colour (the run's own IGV session colours)
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
        path="pipeline_info/samplesheet.valid.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample_id": pl.Utf8,
    "target": pl.Utf8,
    "kind": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "color": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}

_ALIGN = "02_alignment/bowtie2/target"
_CALLS = "03_peak_calling/04_called_peaks"

# kind -> (format, candidate path templates, category, targets only)
_FILES: list[tuple[str, str, tuple[str, ...], str, bool]] = [
    (
        "signal",
        "bigwig",
        (
            "03_peak_calling/03_bed_to_bigwig/{s}.bigWig",
            "04_reporting/igv/{s}.bigWig",
        ),
        "Signal",
        False,
    ),
    (
        "peaks_seacr",
        "bed",
        (
            f"{_CALLS}/seacr/{{s}}.seacr.peaks.stringent.bed",
            "04_reporting/igv/{s}.seacr.peaks.stringent.bed",
        ),
        "Peaks (SEACR)",
        True,
    ),
    (
        "peaks_macs2",
        "narrowpeak",
        (f"{_CALLS}/macs2/{{s}}.macs2_peaks.narrowPeak",),
        "Peaks (MACS2)",
        True,
    ),
    (
        "alignments",
        "bam",
        (
            f"{_ALIGN}/markdup/{{s}}.target.markdup.sorted.bam",
            f"{_ALIGN}/linear_dedup/{{s}}.target.linear_dedup.sorted.bam",
            f"{_ALIGN}/dedup/{{s}}.target.dedup.sorted.bam",
        ),
        "Alignments",
        False,
    ),
]

# The colours the run's own IGV session (04_reporting/igv) gives each group;
# anything else cycles through the same family.
_KNOWN_COLORS = {"h3k27me3": "rgb(38,70,83)", "h3k4me3": "rgb(231,111,81)"}
_CONTROL_COLOR = "rgb(42,157,143)"
_PALETTE = ["rgb(233,196,106)", "rgb(244,162,97)", "rgb(138,177,125)", "rgb(94,80,63)"]


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _held(context, rel: str) -> bool:
    """Whether the run holds a usable ``rel``: present and not empty.

    A caller that finds nothing for a sample still publishes its peak file, at
    0 bytes, and a browser cannot range-read a file with no bytes.
    """
    return context.exists(rel) and context.root.size(rel) != 0


def _pick(candidates: list[str], context) -> str:
    """The first candidate the run holds; the first one when none is (or in place)."""
    if context is None or context.reads_in_place:
        return candidates[0]
    return next((c for c in candidates if _held(context, c)), candidates[0])


def transform(sources: dict[str, pl.DataFrame], context=None) -> pl.DataFrame:
    """Spell out the expected track files of every sample."""
    sheet = sources["samplesheet"]
    missing = [c for c in ("group", "replicate") if c not in sheet.columns]
    if missing:
        raise ValueError(f"cutandrun tracks: samplesheet lacks columns {missing}")

    samples: dict[str, tuple[str, bool]] = {}
    for row in sheet.iter_rows(named=True):
        sample_id = f"{row['group']}_R{int(float(row['replicate']))}"
        samples[sample_id] = (str(row["group"]), _truthy(row.get("is_control", "")))

    groups = sorted({g for g, _ in samples.values()})
    palette = iter(_PALETTE * (len(groups) // len(_PALETTE) + 1))
    colors = {
        g: _KNOWN_COLORS.get(g.lower()) or next(palette)
        for g in groups
        if not any(c and gg == g for gg, c in samples.values())
    }

    rows: list[dict[str, str]] = []
    # Signal first: the browser opens on the first rows of the manifest.
    for kind, fmt, templates, category, targets_only in _FILES:
        for sample_id, (group, is_control) in sorted(samples.items()):
            if targets_only and is_control:
                continue
            uri = _pick([t.format(s=sample_id) for t in templates], context)
            rows.append(
                {
                    "track_id": f"{sample_id}.{kind}",
                    "sample_id": sample_id,
                    "target": group,
                    "kind": kind,
                    "format": fmt,
                    "uri": uri,
                    "name": f"{sample_id} {category.lower()}",
                    "color": _CONTROL_COLOR if is_control else colors.get(group, _PALETTE[0]),
                    "category": category,
                }
            )

    if (
        context is not None
        and not context.reads_in_place
        and any(_held(context, r["uri"]) for r in rows)
    ):
        rows = [r for r in rows if _held(context, r["uri"])]
    # Ingestion reorders rows (clustering on link columns): keep the intended
    # order explicit, the browser opens on the first `initial_tracks`.
    for i, row in enumerate(rows, start=1):
        row["order"] = i
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA)
