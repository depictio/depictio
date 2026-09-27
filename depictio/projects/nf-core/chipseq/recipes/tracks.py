"""Genome-browser track manifest: one row per track file the run published.

nf-core/chipseq 1.2.0 names every per-sample output after the ChIP or input id
of the design sheet the pipeline derived (``pipeline_info/design_controls.csv``,
the file the ``design`` hub reads), so the manifest is spelled out from that
sheet rather than globbed: for each ChIP sample the bigWig signal, the MACS2
narrowPeak calls and the filtered BAM of the merged library, and for each input
control its bigWig signal, as a row of its own keyed on the control id. 1.2.0
aligns with BWA only, hence the ``bwa/mergedLibrary/`` prefix.

Row order is what the browser opens on (``initial_tracks`` shows the first
rows): one block per antibody, each holding the ChIP bigWigs, then the ChIP
peak calls, then the input bigWigs, replicate 1 of every condition before
replicate 2; the BAMs close the manifest. The antibodies in ``_LEAD_ANTIBODIES``
come first: the megatest's FOXA1 bigWigs are about 50 MB each, against more
than 1 GB for the EZH2 ones and their inputs.

Two ways the files are read, decided by what the run folder holds:
- the track files are present under DATA_ROOT: only those rows are kept, and
  the CLI uploads them next to the manifest at ingestion;
- none is present (the tables-only megatest subset): every expected row is kept
  and the collection reads them in place under ``TRACKS_URI`` (the template sets
  ``remote_base_uri`` from it).

Output schema:
    track_id : Utf8     `<sample_id>.<kind>`, unique per file
    sample_id : Utf8    the ChIP sample (links to `design`), or the input
                        control's own id on an input row
    antibody : Utf8     the antibody of the ChIP (of the ChIP it controls, on
                        an input row)
    kind : Utf8         signal / input / peaks / alignments
    format : Utf8       bigwig / narrowpeak / bam
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    color : Utf8        per-antibody colour, grey for the inputs
    category : Utf8     track-selector folder
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="design",
        path="pipeline_info/design_controls.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample_id": pl.Utf8,
    "antibody": pl.Utf8,
    "kind": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "color": pl.Utf8,
    "category": pl.Utf8,
}

_ROOT = "bwa/mergedLibrary"
# kind -> (format, path template, category)
_SIGNAL = ("signal", "bigwig", f"{_ROOT}/bigwig/{{s}}.bigWig", "Signal")
_PEAKS = ("peaks", "narrowpeak", f"{_ROOT}/macs/narrowPeak/{{s}}_peaks.narrowPeak", "Peaks (MACS2)")
_INPUT = ("input", "bigwig", f"{_ROOT}/bigwig/{{s}}.bigWig", "Input")
_BAM = ("alignments", "bam", f"{_ROOT}/{{s}}.mLb.clN.sorted.bam", "Alignments")

# Antibodies whose tracks open the manifest (small bigWigs in the megatest).
_LEAD_ANTIBODIES = ("FOXA1",)

_KNOWN_COLORS = {"foxa1": "rgb(0,114,178)", "ezh2": "rgb(213,94,0)"}
_INPUT_COLOR = "rgb(140,140,140)"
_PALETTE = ["rgb(0,158,115)", "rgb(204,121,167)", "rgb(230,159,0)", "rgb(86,180,233)"]

_REPLICATE = re.compile(r"_R(\d+)$")


def _order(sample_id: str) -> tuple[int, str]:
    """Replicate 1 of every condition before replicate 2, then by name."""
    match = _REPLICATE.search(sample_id)
    return (int(match.group(1)) if match else 0, sample_id)


def transform(sources: dict[str, pl.DataFrame], context=None) -> pl.DataFrame:
    """Spell out the expected track files of every ChIP sample and input."""
    design = sources["design"]
    missing = [c for c in ("sample_id", "control_id", "antibody") if c not in design.columns]
    if missing:
        raise ValueError(f"chipseq tracks: design_controls.csv lacks columns {missing}")

    chips: dict[str, str] = {}  # ChIP sample -> antibody
    inputs: dict[str, str] = {}  # input control -> antibody of the first ChIP it controls
    for row in design.iter_rows(named=True):
        sample_id = str(row["sample_id"]).strip()
        antibody = str(row["antibody"]).strip()
        chips[sample_id] = antibody
        control = str(row["control_id"] or "").strip()
        if control:
            inputs.setdefault(control, antibody)

    lead = {a.lower(): i for i, a in enumerate(_LEAD_ANTIBODIES)}
    antibodies = sorted(set(chips.values()), key=lambda a: (lead.get(a.lower(), len(lead)), a))
    palette = iter(_PALETTE * (len(antibodies) // len(_PALETTE) + 1))
    colors = {a: _KNOWN_COLORS.get(a.lower()) or next(palette) for a in antibodies}

    def row_for(sample_id: str, antibody: str, spec: tuple[str, str, str, str]) -> dict:
        kind, fmt, template, category = spec
        return {
            "track_id": f"{sample_id}.{kind}",
            "sample_id": sample_id,
            "antibody": antibody,
            "kind": kind,
            "format": fmt,
            "uri": template.format(s=sample_id),
            "name": f"{sample_id} {category.lower()}",
            "color": _INPUT_COLOR if kind == "input" else colors[antibody],
            "category": category,
        }

    rows: list[dict[str, str]] = []
    for antibody in antibodies:
        ab_chips = sorted((s for s, a in chips.items() if a == antibody), key=_order)
        ab_inputs = sorted((s for s, a in inputs.items() if a == antibody), key=_order)
        rows += [row_for(s, antibody, _SIGNAL) for s in ab_chips]
        rows += [row_for(s, antibody, _PEAKS) for s in ab_chips]
        rows += [row_for(s, antibody, _INPUT) for s in ab_inputs if s not in chips]
    for antibody in antibodies:
        ab_chips = sorted((s for s, a in chips.items() if a == antibody), key=_order)
        rows += [row_for(s, antibody, _BAM) for s in ab_chips]

    if context is not None and any(context.exists(r["uri"]) for r in rows):
        rows = [r for r in rows if context.exists(r["uri"])]
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA)
