"""Genome-browser track manifest: one row per track file the run published.

nf-core/atacseq 1.2.x names every per-library output after the merged, filtered
library ``<group>_R<replicate>.mLb.clN`` it builds from the design sheet
(``pipeline_info/design_reads.csv``, the file the ``sample_design`` hub reads),
so the manifest is spelled out from that sheet rather than globbed: for each
sample the bigWig signal, the MACS2 peak calls and the filtered BAM of its
merged library, each as a row of its own. The run aligns with BWA only, hence
the ``bwa/mergedLibrary/`` prefix. The ``bwa/mergedReplicate/`` level (one file
per group) is not listed: the other collections of the template bind the
merged-library level only, and the browser stays on the same one.

Peak calls come in the form the run was called with: ``--narrow_peak false``
(the template's route) writes ``macs/broadPeak/*_peaks.broadPeak``, a narrow
run ``macs/narrowPeak/*_peaks.narrowPeak``. The first one the run holds is used.

Row order is what the browser opens on (``initial_tracks`` shows the first
rows): the bigWig signals first, replicate 1 of every group before replicate 2
(groups by name), then the peak calls in the same order, and the BAMs last (they
are the heaviest files and the slowest to open).

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every
  expected row is kept and read in place under that results folder, on the
  broad-peak layout;
- otherwise the rows whose file is present under DATA_ROOT are kept and the CLI
  uploads them at ingestion (all rows are kept when none is present, so a
  tables-only run still lists what the pipeline publishes).

Output schema:
    track_id : Utf8     `<merged_library>.<kind>`, unique per file
    sample_id : Utf8    the merged library (`<sample>.mLb.clN`), the spelling the
                        peak calls use, so a picked peak opens its own tracks
    sample : Utf8       the canonical sample (`<group>_R<replicate>`)
    group : Utf8        design group
    kind : Utf8         signal / peaks / alignments
    format : Utf8       bigwig / broadpeak / narrowpeak / bam
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    color : Utf8        per-group colour
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
        ref="design",
        glob_pattern="**/design_reads.csv",
        format="CSV",
        input_schema={"sample_id": pl.Utf8},
        read_kwargs={"infer_schema_length": 0},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample_id": pl.Utf8,
    "sample": pl.Utf8,
    "group": pl.Utf8,
    "kind": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "color": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}

#: Suffix atacseq 1.2.x gives the merged, filtered library (also in every peak name).
MERGE_SUFFIX = ".mLb.clN"

_ROOT = "bwa/mergedLibrary"
# kind -> (candidate (format, path) pairs in order of preference, category, label)
_SIGNAL = ("signal", (("bigwig", f"{_ROOT}/bigwig/{{m}}.bigWig"),), "Signal", "signal")
_PEAKS = (
    "peaks",
    (
        ("broadpeak", f"{_ROOT}/macs/broadPeak/{{m}}_peaks.broadPeak"),
        ("narrowpeak", f"{_ROOT}/macs/narrowPeak/{{m}}_peaks.narrowPeak"),
    ),
    "Peaks (MACS2)",
    "peaks",
)
_BAM = ("alignments", (("bam", f"{_ROOT}/{{m}}.sorted.bam"),), "Alignments", "reads")

# Colour-blind-safe palette (Okabe-Ito), one colour per group in name order.
_PALETTE = [
    "rgb(0,114,178)",
    "rgb(213,94,0)",
    "rgb(0,158,115)",
    "rgb(204,121,167)",
    "rgb(230,159,0)",
    "rgb(86,180,233)",
]

_TECHNICAL = re.compile(r"_T\d+$")
_SAMPLE = re.compile(r"^(?P<group>.+)_R(?P<replicate>\d+)$")


def _samples(design: pl.DataFrame) -> list[tuple[str, str, int]]:
    """(sample, group, replicate) of every sample of the sheet, in sheet order.

    A sample that does not follow ``<group>_R<n>`` is its own group, replicate 0.
    """
    if "sample_id" not in design.columns:
        raise ValueError(f"atacseq tracks: design sheet lacks 'sample_id' (has {design.columns})")
    out: dict[str, tuple[str, str, int]] = {}
    for value in design["sample_id"].to_list():
        library = str(value or "").strip()
        if not library:
            continue
        sample = _TECHNICAL.sub("", library)
        match = _SAMPLE.match(sample)
        group = match.group("group") if match else sample
        replicate = int(match.group("replicate")) if match else 0
        out.setdefault(sample, (sample, group, replicate))
    return list(out.values())


def transform(sources: dict[str, pl.DataFrame], context=None) -> pl.DataFrame:
    """Spell out the expected track files of every merged library of the design."""
    samples = _samples(sources["design"])

    groups = sorted({g for _, g, _ in samples})
    colors = {g: _PALETTE[i % len(_PALETTE)] for i, g in enumerate(groups)}
    # Replicate 1 of every group before replicate 2, groups by name.
    samples.sort(key=lambda s: (s[2], s[1], s[0]))

    def uri_for(candidates: tuple[tuple[str, str], ...], merged: str) -> tuple[str, str]:
        """The first (format, path) the run holds; the first one when none (or in place)."""
        paths = [(fmt, path.format(m=merged)) for fmt, path in candidates]
        if context is None or context.reads_in_place:
            return paths[0]
        return next((p for p in paths if context.exists(p[1])), paths[0])

    rows: list[dict] = []
    for kind, candidates, category, label in (_SIGNAL, _PEAKS, _BAM):
        for sample, group, _ in samples:
            merged = f"{sample}{MERGE_SUFFIX}"
            fmt, uri = uri_for(candidates, merged)
            rows.append(
                {
                    "track_id": f"{merged}.{kind}",
                    "sample_id": merged,
                    "sample": sample,
                    "group": group,
                    "kind": kind,
                    "format": fmt,
                    "uri": uri,
                    "name": f"{sample} {label}",
                    "color": colors[group],
                    "category": category,
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
