"""Genome-browser track manifest: one row per track file the run published.

nf-core/cutandrun names every per-sample output `<group>_R<replicate>` (the
`sample_id` the `samples` recipe builds), so the manifest is spelled out from
the validated samplesheet rather than globbed: the bigWig signal, the SEACR
stringent and MACS2 narrowPeak calls (targets only; peak calling never runs on
an IgG control) and the deduplicated BAM.

Two ways the files are read, decided by what the run folder holds:
- the track files are present under DATA_ROOT: only those rows are kept, and
  the CLI uploads them next to the manifest at ingestion;
- none is present (the tables-only megatest subset): every expected row is kept
  and the collection reads them in place under ``TRACKS_URI`` (the template sets
  ``remote_base_uri`` from it).

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
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="pipeline_info/samplesheet.valid.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample_id": pl.Utf8,
    "target": pl.Utf8,
    "kind": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "color": pl.Utf8,
    "category": pl.Utf8,
}

# kind -> (format, path template, category, targets only)
_FILES: list[tuple[str, str, str, str, bool]] = [
    ("signal", "bigwig", "03_peak_calling/03_bed_to_bigwig/{s}.bigWig", "Signal", False),
    (
        "peaks_seacr",
        "bed",
        "03_peak_calling/04_called_peaks/seacr/{s}.seacr.peaks.stringent.bed",
        "Peaks (SEACR)",
        True,
    ),
    (
        "peaks_macs2",
        "narrowpeak",
        "03_peak_calling/04_called_peaks/macs2/{s}.macs2_peaks.narrowPeak",
        "Peaks (MACS2)",
        True,
    ),
    (
        "alignments",
        "bam",
        "02_alignment/bowtie2/target/markdup/{s}.target.markdup.sorted.bam",
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
    for kind, fmt, template, category, targets_only in _FILES:
        for sample_id, (group, is_control) in sorted(samples.items()):
            if targets_only and is_control:
                continue
            rows.append(
                {
                    "track_id": f"{sample_id}.{kind}",
                    "sample_id": sample_id,
                    "target": group,
                    "kind": kind,
                    "format": fmt,
                    "uri": template.format(s=sample_id),
                    "name": f"{sample_id} {category.lower()}",
                    "color": _CONTROL_COLOR if is_control else colors.get(group, _PALETTE[0]),
                    "category": category,
                }
            )

    if context is not None and any(context.exists(r["uri"]) for r in rows):
        rows = [r for r in rows if context.exists(r["uri"])]
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA)
