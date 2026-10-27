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
megatest); inside a block, the first library of every assay before the second,
so the first rows put one total-mRNA and one footprint library side by side.

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every
  expected row is kept and read in place under that results folder;
- otherwise the rows whose file is present under DATA_ROOT are kept and the CLI
  uploads them at ingestion (all rows are kept when none is present, so a
  tables-only run still lists what the pipeline publishes).

Output schema:
    track_id : Utf8     `<sample>.<kind>[.<strand>]`, unique per file
    sample : Utf8       the library the file belongs to (links to `samples`)
    assay : Utf8        RNA-seq / Ribo-seq / TI-seq, from the sheet's `type`
    strand : Utf8       forward / reverse for the stranded tracks, empty otherwise
    kind : Utf8         psites / coverage / alignments
    format : Utf8       bedgraph / bigwig / bam
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    color : Utf8        per-assay colour, the reverse strand a lighter shade
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
    "color": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}

# The sheet's `type` -> (label, (forward / BAM colour, reverse colour)).
_ASSAYS = {
    "rnaseq": ("RNA-seq", ("rgb(31,119,180)", "rgb(140,186,222)")),
    "riboseq": ("Ribo-seq", ("rgb(255,127,14)", "rgb(255,187,125)")),
    "tiseq": ("TI-seq", ("rgb(148,103,189)", "rgb(199,175,222)")),
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


def transform(sources: dict[str, pl.DataFrame], context=None) -> pl.DataFrame:
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

    libraries: dict[str, tuple[str, str]] = {}
    for record in sheet.to_dicts():
        sample = str(record.get(sample_col) or "").strip()
        if not sample or sample in libraries:
            continue
        assay_key = str(record.get(type_col) or "").strip().lower() if type_col else ""
        if assay_key not in _ASSAYS:
            assay_key = _DEFAULT_ASSAY
        libraries[sample] = (assay_key, str(record.get(strand_col) or "") if strand_col else "")

    # The first library of every assay before the second, within a block.
    seen: dict[str, int] = {}
    rank: dict[str, int] = {}
    for sample, (assay_key, _) in libraries.items():
        seen[assay_key] = seen.get(assay_key, 0) + 1
        rank[sample] = seen[assay_key]
    assay_order = {key: i for i, key in enumerate(_ASSAYS)}
    # sorted() is stable: ties keep the sheet's order.
    ordered = sorted(libraries, key=lambda s: (rank[s], assay_order[libraries[s][0]]))

    in_place = context is None or context.reads_in_place

    def holds(paths: tuple[str, ...]) -> bool:
        return not in_place and any(context.exists(p) for p in paths)

    def row(sample: str, kind: str, fmt: str, path: str, strand: str, category: str) -> dict:
        assay_key = libraries[sample][0]
        label, (main, light) = _ASSAYS[assay_key]
        what = {"psites": "P-sites", "coverage": "coverage", "alignments": "reads"}[kind]
        suffix = f".{strand}" if strand else ""
        return {
            "track_id": f"{sample}.{kind}{suffix}",
            "sample": sample,
            "assay": label,
            "strand": strand,
            "kind": kind,
            "format": fmt,
            "uri": path.format(s=sample),
            "name": f"{sample} {what}" + (f" {strand}" if strand else ""),
            "color": light if strand == "reverse" else main,
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
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA)
