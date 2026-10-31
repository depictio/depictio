"""Genome-browser track manifest: one row per track file the run published.

nf-core/riboseq names every per-library output after the samplesheet ``sample``,
so the manifest is spelled out from the sheet rather than globbed. All paths are
relative to DATA_ROOT:

    psites/plastid/tracks/<sample>_fw.bedgraph, _rc.bedgraph
                                      Plastid P-site tracks, footprint
                                      libraries only (--skip_plastid drops them)
    coverage/<sample>.forward.bigWig, .reverse.bigWig
                                      stranded coverage
    coverage/<sample>.unstranded.bigWig
                                      unstranded coverage (their sum)
    alignment/star/sorted/<sample>.genome.sorted.bam
                                      genome alignments, with its .bai

The coverage is stranded or not depending on the library: the sheet's
``strandedness`` when it says (forward, reverse, unstranded), else the usual
split of the two assays (``auto``: footprint libraries stranded, total mRNA
unstranded). When the run is read from DATA_ROOT, the layout it actually holds
wins over that guess. The transcriptome BAMs are not genome tracks and are left
out.

The P-site bedGraphs are plain text with a ``##`` header (Plastid's argument
dump) and 5 to 10 MB each, read whole by the browser, so they come after the
bigWigs, which are range-read.

Row order is what the browser opens on (``initial_tracks`` shows the first
rows): the coverage, then the P-sites, then the BAMs (0.3 to 2 GB each in the
megatest). Inside a block the libraries come in design order: one representative
per assay and design group first (one control and one treated library of each
assay, the assays in sheet order), then the second library of every assay and
group, and so on. The opening tracks therefore cover the design instead of the
first replicates of one condition.

The design group (the template's ``GROUP_COL``: a treatment, a condition) is a
column of the manifest under its own name, which the tile colours by
(``color_by``): the libraries of a group share a hue and the Tracks menu groups the
tracks by it. It is read from the design table when that has the column, else from
the sample sheet; without either, the column is the constant ``__no_group__``. A
library's label is the sheet's (or the design table's) ``sample_description`` when
it has one, else the sample id.

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every
  expected row is kept and read in place under that results folder;
- otherwise the rows whose file is present under DATA_ROOT are kept and the CLI
  uploads them at ingestion (all rows are kept when none is present, so a
  tables-only run still lists what the pipeline publishes).

Parameters:
    group_col  the design column the tracks are coloured by (the template's ``GROUP_COL``)

Sources:
    samplesheet  the run's ``--input`` sheet (assay, strandedness, design columns)
    metadata     the optional design table (first column the sample id)

Output schema (the group column is named by ``group_col``):
    track_id : Utf8     `<sample>.<kind>[.<strand>]`, unique per file
    sample : Utf8       the library the file belongs to (links to `samples`)
    assay : Utf8        RNA-seq / Ribo-seq / TI-seq, from the sheet's `type`
    <group> : Utf8      the library's design group
    strand : Utf8       forward / reverse for the stranded tracks, empty otherwise
    kind : Utf8         psites / coverage / alignments
    format : Utf8       bedgraph / bigwig / bam
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser (library label, then what the file is)
    category : Utf8     track-selector folder
    order : Int64       row order the browser opens with (``order_column``)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    # No input_schema: the id column is found by name and the design columns are run-dependent.
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
    # The design table (METADATA_FILE), absent on a run without one.
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample": pl.Utf8,
    "assay": pl.Utf8,
    "strand": pl.Utf8,
    "kind": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}
# The group column is named by the template's group_col and passes through.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

#: Column the group falls back to when the template names none.
NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All libraries"

# The sheet's `type` -> assay label.
_ASSAYS = {
    "rnaseq": "RNA-seq",
    "riboseq": "Ribo-seq",
    "tiseq": "TI-seq",
}
_DEFAULT_ASSAY = "riboseq"
_FOOTPRINT = ("riboseq", "tiseq")

_PSITES = ("psites/plastid/tracks/{s}_fw.bedgraph", "psites/plastid/tracks/{s}_rc.bedgraph")
_COVERAGE_STRANDED = ("coverage/{s}.forward.bigWig", "coverage/{s}.reverse.bigWig")
_COVERAGE_UNSTRANDED = ("coverage/{s}.unstranded.bigWig",)
_BAM = "alignment/star/sorted/{s}.genome.sorted.bam"


def _fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """A TSV sheet read as CSV arrives as one tab-joined column: split it."""
    if df.width != 1 or "\t" not in df.columns[0]:
        return df
    header = df.columns[0].split("\t")
    rows = [str(v).split("\t") for v in df[df.columns[0]].to_list()]
    return pl.DataFrame(
        {h: [r[i] if i < len(r) else None for r in rows] for i, h in enumerate(header)}
    )


def _stranded(strandedness: str, assay_key: str) -> bool:
    """Whether the library's coverage is a forward / reverse pair."""
    declared = strandedness.strip().lower()
    if declared == "unstranded":
        return False
    if declared in ("forward", "reverse"):
        return True
    return assay_key in _FOOTPRINT


def _by_sample(df: pl.DataFrame | None, id_col: str | None, column: str) -> dict[str, str]:
    """``sample -> value`` of one column of a table keyed on ``id_col``, blanks left out."""
    if df is None or id_col is None or column not in df.columns or column == id_col:
        return {}
    out: dict[str, str] = {}
    for record in df.to_dicts():
        sample = str(record.get(id_col) or "").strip()
        value = str(record.get(column) or "").strip()
        if sample and value:
            out.setdefault(sample, value)
    return out


def transform(
    sources: dict[str, pl.DataFrame | None],
    context=None,
    params: dict[str, str] | None = None,
) -> pl.DataFrame:
    """Spell out the expected track files of every library of the sheet."""
    sheet = _fix_delimiter(sources["samplesheet"])
    sheet = sheet.rename({c: c.strip() for c in sheet.columns})
    sample_col = next(
        (c for c in sheet.columns if c.lower() in ("sample", "sample_id", "sampleid")), None
    )
    if sample_col is None:
        raise ValueError(f"riboseq tracks: samplesheet has no sample column ({sheet.columns})")
    type_col = next((c for c in sheet.columns if c.lower() == "type"), None)
    strand_col = next((c for c in sheet.columns if c.lower() == "strandedness"), None)

    # The design table keys its rows on its first column.
    design = sources.get("metadata")
    if design is not None:
        design = design.rename({c: c.strip() for c in design.columns})
    design_id = design.columns[0] if design is not None and design.width else None

    def lookup(column: str) -> dict[str, str]:
        """A design column of the design table, else of the sheet."""
        return _by_sample(design, design_id, column) or _by_sample(sheet, sample_col, column)

    requested = ((params or {}).get("group_col") or "").strip()
    group = requested if requested and requested not in OUTPUT_SCHEMA else NO_GROUP_COL
    groups = lookup(group) if group != NO_GROUP_COL else {}
    labels = lookup("sample_description")

    libraries: dict[str, tuple[str, str]] = {}
    for record in sheet.to_dicts():
        sample = str(record.get(sample_col) or "").strip()
        if not sample or sample in libraries:
            continue
        assay_key = str(record.get(type_col) or "").strip().lower() if type_col else ""
        if assay_key not in _ASSAYS:
            assay_key = _DEFAULT_ASSAY
        libraries[sample] = (assay_key, str(record.get(strand_col) or "") if strand_col else "")

    def group_of(sample: str) -> str:
        return groups.get(sample, NO_GROUP_VALUE)

    # Design order: the assays as the template lists them, the groups as the sheet
    # meets them. The first library of each (assay, group) represents it; the
    # second library of every pair comes next, and so on.
    assay_order = {key: i for i, key in enumerate(_ASSAYS)}
    group_order = {g: i for i, g in enumerate(dict.fromkeys(group_of(s) for s in libraries))}
    seen: dict[tuple[str, str], int] = {}
    rank: dict[str, int] = {}
    for sample, (assay_key, _) in libraries.items():
        pair = (assay_key, group_of(sample))
        seen[pair] = seen.get(pair, 0) + 1
        rank[sample] = seen[pair]
    # sorted() is stable: ties keep the sheet's order.
    ordered = sorted(
        libraries,
        key=lambda s: (rank[s], assay_order[libraries[s][0]], group_order[group_of(s)]),
    )

    in_place = context is None or context.reads_in_place

    def holds(paths: tuple[str, ...]) -> bool:
        return not in_place and any(context.exists(p) for p in paths)

    def row(sample: str, kind: str, fmt: str, path: str, strand: str, category: str) -> dict:
        what = {"psites": "P-sites", "coverage": "coverage", "alignments": "reads"}[kind]
        suffix = f".{strand}" if strand else ""
        return {
            "track_id": f"{sample}.{kind}{suffix}",
            "sample": sample,
            "assay": _ASSAYS[libraries[sample][0]],
            group: group_of(sample),
            "strand": strand,
            "kind": kind,
            "format": fmt,
            "uri": path.format(s=sample),
            "name": f"{labels.get(sample, sample)} {what}" + (f" {strand}" if strand else ""),
            "category": category,
        }

    rows: list[dict] = []
    for sample in ordered:
        assay_key, strandedness = libraries[sample]
        stranded = _stranded(strandedness, assay_key)
        guess, other = (
            (_COVERAGE_STRANDED, _COVERAGE_UNSTRANDED)
            if stranded
            else (_COVERAGE_UNSTRANDED, _COVERAGE_STRANDED)
        )
        paths = guess
        if not holds(tuple(p.format(s=sample) for p in guess)) and holds(
            tuple(p.format(s=sample) for p in other)
        ):
            paths = other
        strands = ("forward", "reverse") if paths is _COVERAGE_STRANDED else ("",)
        for path, strand in zip(paths, strands, strict=True):
            rows.append(row(sample, "coverage", "bigwig", path, strand, "Coverage"))
    for sample in ordered:
        if libraries[sample][0] in _FOOTPRINT:
            for path, strand in zip(_PSITES, ("forward", "reverse"), strict=True):
                rows.append(row(sample, "psites", "bedgraph", path, strand, "P-sites"))
    for sample in ordered:
        rows.append(row(sample, "alignments", "bam", _BAM, "", "Alignments"))

    if not in_place and any(context.exists(r["uri"]) for r in rows):
        rows = [r for r in rows if context.exists(r["uri"])]
    # Ingestion reorders rows (clustering on link columns): keep the intended
    # order explicit, the browser opens on the first `initial_tracks`.
    for i, r in enumerate(rows, start=1):
        r["order"] = i
    schema = {**OUTPUT_SCHEMA, group: pl.Utf8}
    return pl.DataFrame(rows, schema=schema).select(
        "track_id",
        "sample",
        "assay",
        group,
        "strand",
        "kind",
        "format",
        "uri",
        "name",
        "category",
        "order",
    )
