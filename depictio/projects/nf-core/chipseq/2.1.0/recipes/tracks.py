"""Genome-browser track manifest: one row per track file the run published.

The 2.1.0 override of the shared `nf-core/chipseq/tracks.py`: same output schema,
a different layout and a different design input. nf-core/chipseq 2.x publishes
everything below `<aligner>/merged_library/` and names each file after the merged
library id `<sample>_REP<n>`, the id the `design` hub holds and MACS3 stamps into
every peak name. So the manifest is spelled out from that hub rather than globbed:
for each ChIP the bigWig signal, the MACS3 peak calls and the filtered BAM, and for
each input control its bigWig signal as a row of its own, keyed on the control id.

The aligner (bwa, bowtie2, chromap or star) and the peak type (`macs3/narrow_peak/`
or `macs3/broad_peak/`, the second the pipeline default) are read off the peak
calls, bigWigs and BAMs DATA_ROOT holds, then off the run's `pipeline_info/params_*.json`;
the first existing path of each file wins, so a tables-only tree whose peak calls are
there but whose bigWigs are not still resolves the layout.

Row order is what the browser opens on (`initial_tracks` shows the first rows): one
block per antibody, each holding the ChIP bigWigs, then the peak calls, then the
input bigWigs, replicate 1 of every condition before replicate 2; the BAMs close the
manifest. The antibodies in `_LEAD_ANTIBODIES` come first: the megatest design's
bigWigs of that antibody are the small ones.

Two ways the files are read:
- `TRACKS_URI` is set (the template turns it into `remote_base_uri`): every
  expected row is kept and read in place under that results folder;
- otherwise the rows whose file is present under DATA_ROOT are kept and the CLI
  uploads them at ingestion (all rows are kept when none is present, so a
  tables-only run still lists what the pipeline publishes).

Colour: one per antibody, grey for the inputs. A run with a single antibody has
nothing to tell apart that way, so its ChIP tracks take one colour per condition.

Sources:
    design     the `design` hub: the ChIPs and their input controls

Output schema:
    track_id : Utf8     `<sample_id>.<kind>`, unique per file
    sample_id : Utf8    the ChIP merged library (links to `design`), or the input
                        control's own id on an input row
    antibody : Utf8     the antibody of the ChIP (of the ChIPs it serves, on an input row)
    kind : Utf8         signal / input / peaks / alignments
    format : Utf8       bigwig / narrowpeak / broadpeak / bam
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    color : Utf8        per-antibody (or per-condition) colour, grey for the inputs
    category : Utf8     track-selector folder
    order : Int64       row order the browser opens with (`order_column`)
"""

from __future__ import annotations

import json
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="design",
        dc_ref="design",
        input_schema={
            "sample_id": pl.Utf8,
            "is_control": pl.Boolean,
            "antibody": pl.Utf8,
            "condition": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample_id": pl.Utf8,
    "antibody": pl.Utf8,
    "kind": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "color": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}

#: Peak type -> (MACS3 folder, file suffix, track format).
_PEAK_TYPES = {
    "narrow_peak": ("narrow_peak", "_peaks.narrowPeak", "narrowpeak"),
    "broad_peak": ("broad_peak", "_peaks.broadPeak", "broadpeak"),
}
_DEFAULT_ALIGNER = "bwa"

# kind -> (category, label)
_SIGNAL = ("signal", "Signal", "signal")
_PEAKS = ("peaks", "Peaks (MACS3)", "peaks")
_INPUT = ("input", "Input", "input")
_BAM = ("alignments", "Alignments", "reads")

# Antibodies whose tracks open the manifest (small bigWigs in the megatest design).
_LEAD_ANTIBODIES = ("FOXA1",)

_INPUT_COLOR = "rgb(140,140,140)"
# Colour-blind-safe palette (Okabe-Ito).
_PALETTE = [
    "rgb(0,114,178)",
    "rgb(213,94,0)",
    "rgb(0,158,115)",
    "rgb(204,121,167)",
    "rgb(230,159,0)",
    "rgb(86,180,233)",
]

_REPLICATE = re.compile(r"_REP(\d+)$")
_PEAK_FILE = re.compile(
    r"^(?P<aligner>[^/]+)/merged_library/macs3/(?P<peak>[^/]+)/[^/]+_peaks\.\w+Peak$"
)


def _order(sample_id: str) -> tuple[int, str]:
    """Replicate 1 of every condition before replicate 2, then by name."""
    match = _REPLICATE.search(sample_id)
    return (int(match.group(1)) if match else 0, sample_id)


def _unique(items) -> list[str]:
    return list(dict.fromkeys(items))


def _layout(context) -> tuple[list[str], list[str]]:
    """Candidate aligner folders and peak types, most likely first."""
    aligners: list[str] = []
    peak_types: list[str] = []
    if context is not None:
        for path in context.glob("*/merged_library/macs3/*/*_peaks.*Peak"):
            match = _PEAK_FILE.match(path)
            if match and match["peak"] in _PEAK_TYPES:
                aligners.append(match["aligner"])
                peak_types.append(match["peak"])
        for pattern in ("*/merged_library/bigwig/*.bigWig", "*/merged_library/*.sorted.bam"):
            aligners += [p.split("/", 1)[0] for p in context.glob(pattern)]
        for path in context.glob("pipeline_info/params_*.json"):
            try:
                params = json.loads(context.root.read_bytes(path))
            except (OSError, ValueError):
                continue
            if not isinstance(params, dict):
                continue
            aligners.append(str(params.get("aligner") or ""))
            narrow = params.get("narrow_peak")
            if isinstance(narrow, bool):
                peak_types.append("narrow_peak" if narrow else "broad_peak")
    return (
        _unique([a for a in aligners if a] + [_DEFAULT_ALIGNER]),
        _unique(peak_types + list(_PEAK_TYPES)),
    )


def transform(sources: dict[str, pl.DataFrame], context=None) -> pl.DataFrame:
    """Spell out the expected track files of every ChIP and input control."""
    design = sources["design"]
    missing = [
        c for c in ("sample_id", "is_control", "antibody", "condition") if c not in design.columns
    ]
    if missing:
        raise ValueError(f"chipseq tracks: the design hub lacks columns {missing}")

    chips: dict[str, tuple[str, str]] = {}  # ChIP library -> (antibody, condition)
    inputs: dict[str, str] = {}  # input control -> first antibody it serves
    for row in design.iter_rows(named=True):
        sample_id = str(row["sample_id"]).strip()
        antibody = str(row["antibody"] or "").strip()
        if row["is_control"]:
            inputs[sample_id] = antibody.split(",")[0].strip()
        else:
            chips[sample_id] = (antibody, str(row.get("condition") or "").strip())

    lead = {a.lower(): i for i, a in enumerate(_LEAD_ANTIBODIES)}
    antibodies = sorted(
        {a for a, _ in chips.values()} | set(inputs.values()),
        key=lambda a: (lead.get(a.lower(), len(lead)), a),
    )
    # Colour by antibody; a single antibody cannot tell the ChIPs apart, so by condition.
    by_condition = len(antibodies) <= 1
    keys = sorted({c for _, c in chips.values()} if by_condition else set(antibodies))
    palette = {k: _PALETTE[i % len(_PALETTE)] for i, k in enumerate(keys)}

    aligners, peak_types = _layout(context)
    in_place = context is None or context.reads_in_place

    def path_for(kind: str, sample_id: str) -> tuple[str, str]:
        """The first (format, path) the run holds; the first candidate when none (or in place)."""
        candidates: list[tuple[str, str]] = []
        for aligner in aligners:
            base = f"{aligner}/merged_library"
            if kind in ("signal", "input"):
                candidates.append(("bigwig", f"{base}/bigwig/{sample_id}.mLb.clN.bigWig"))
            elif kind == "peaks":
                for peak in peak_types:
                    folder, suffix, fmt = _PEAK_TYPES[peak]
                    candidates.append((fmt, f"{base}/macs3/{folder}/{sample_id}{suffix}"))
            else:
                candidates.append(("bam", f"{base}/{sample_id}.mLb.clN.sorted.bam"))
        if in_place:
            return candidates[0]
        return next((c for c in candidates if context.exists(c[1])), candidates[0])

    def row_for(sample_id: str, antibody: str, condition: str, spec: tuple[str, str, str]) -> dict:
        kind, category, label = spec
        fmt, uri = path_for(kind, sample_id)
        if kind == "input":
            color = _INPUT_COLOR
        else:
            color = palette[condition if by_condition else antibody]
        return {
            "track_id": f"{sample_id}.{kind}",
            "sample_id": sample_id,
            "antibody": antibody,
            "kind": kind,
            "format": fmt,
            "uri": uri,
            "name": f"{sample_id} {label}",
            "color": color,
            "category": category,
        }

    rows: list[dict] = []
    for antibody in antibodies:
        ab_chips = sorted((s for s, (a, _) in chips.items() if a == antibody), key=_order)
        ab_inputs = sorted((s for s, a in inputs.items() if a == antibody), key=_order)
        rows += [row_for(s, antibody, chips[s][1], _SIGNAL) for s in ab_chips]
        rows += [row_for(s, antibody, chips[s][1], _PEAKS) for s in ab_chips]
        rows += [row_for(s, antibody, "", _INPUT) for s in ab_inputs]
    for antibody in antibodies:
        ab_chips = sorted((s for s, (a, _) in chips.items() if a == antibody), key=_order)
        rows += [row_for(s, antibody, chips[s][1], _BAM) for s in ab_chips]

    if context is not None and not in_place and any(context.exists(r["uri"]) for r in rows):
        rows = [r for r in rows if context.exists(r["uri"])]
    # Ingestion reorders rows (clustering on link columns): keep the intended
    # order explicit, the browser opens on the first `initial_tracks`.
    for i, row in enumerate(rows, start=1):
        row["order"] = i
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA)
