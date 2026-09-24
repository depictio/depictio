"""One row per assessed assembly: every QC tool of nf-core/genomeassembler, joined.

nf-core/genomeassembler assesses every intermediate it writes (the raw assembly,
each polishing step, each scaffolder) and publishes each QC tool's output under
one name per assessed assembly, `<sample>_<stage>`, with `<stage>` one of
`assembly`, `medaka`, `dorado`, `pilon`, `links`, `longstitch`, `ragtag` (and
the Hi-C scaffolders). This recipe gathers what the tools say about each of
those names into one row, which is the table the Overview reads:

* contiguity (sequence count, total length, N50/L50, N90/L90, auN) computed from
  the sequence lengths `samtools idxstats` lists for the reads mapped back to the
  assembly, exact and available for every assembly the pipeline aligned to;
* Merqury's QV and k-mer completeness (`merqury_assembly_qv`);
* BUSCO's class percentages (`busco_batch_summary`), the most specific lineage
  when an assembly was scored against several;
* QUAST's reference-based columns when the run had a reference
  (`quast_reference_report`).

Each source is optional: a run that skipped a tool, or an assembly a tool was
not run on, leaves that block null, and `qc_tools` lists what was found. The
design comes from the samplesheet, keyed on its `sample` column: every
samplesheet column is passed through as text, and `assembler_used` and
`scaffolders` restate the per-row assembler and scaffolding columns in one word
each, falling back to the ONT / HiFi specific assembler columns when the
generic one is blank.

The stage is the part after the last `_` of the published name when it is one
of the pipeline's stage words; names that do not end in one (the reads aligned
to the reference, the short reads aligned for polishing) are not assemblies and
are dropped.

Output schema (plus every samplesheet column, as text):
    assembly_id : Utf8            `<sample>_<stage>`, the published name
    sample : Utf8                 samplesheet sample
    stage : Utf8                  assembly, a polisher or a scaffolder
    stage_class : Utf8            assembly, polish or scaffold
    stage_rank : Int64            0 assembly, 1 long-read polish, 2 short-read polish, 3 scaffold
    assembler_used : Utf8         assembler(s) of the sample, from the samplesheet
    scaffolders : Utf8            scaffolders switched on for the sample, comma-separated
    n_sequences : Int64           contigs or scaffolds
    total_length : Int64          assembled bases
    largest_sequence : Int64      longest sequence
    n50 : Int64                   half the assembly sits in sequences at least this long
    l50 : Int64                   how many sequences hold that half
    n90 : Int64                   the same at 90 percent
    l90 : Int64                   the same at 90 percent
    aun : Float64                 area under the Nx curve, the length-weighted mean sequence length
    qv : Float64                  Merqury consensus QV
    error_rate : Float64          Merqury per-base error rate
    kmer_completeness : Float64   Merqury k-mer completeness, percent
    busco_lineage : Utf8          BUSCO lineage dataset
    busco_complete : Float64      BUSCO complete, percent
    busco_single : Float64        BUSCO complete single-copy, percent
    busco_duplicated : Float64    BUSCO complete duplicated, percent
    busco_fragmented : Float64    BUSCO fragmented, percent
    busco_missing : Float64       BUSCO missing, percent
    genome_fraction : Float64     QUAST percent of the reference covered
    misassemblies : Int64         QUAST misassemblies against the reference
    mismatches_per_100kbp : Float64  QUAST substitution rate against the reference
    nga50 : Int64                 QUAST NGA50
    qc_tools : Utf8               the QC tools that reported on this assembly
    n_qc_tools : Int64            how many
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="samplesheet", dc_ref="samplesheet", optional=True),
    RecipeSource(ref="idxstats", dc_ref="samtools_idxstats_raw", optional=True),
    RecipeSource(ref="merqury", dc_ref="merqury_assembly_qv", optional=True),
    RecipeSource(ref="busco", dc_ref="busco_batch_summary", optional=True),
    RecipeSource(ref="quast_ref", dc_ref="quast_reference_report", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "assembly_id": pl.Utf8,
    "sample": pl.Utf8,
    "stage": pl.Utf8,
    "stage_class": pl.Utf8,
    "stage_rank": pl.Int64,
    "assembler_used": pl.Utf8,
    "scaffolders": pl.Utf8,
    "n_sequences": pl.Int64,
    "total_length": pl.Int64,
    "largest_sequence": pl.Int64,
    "n50": pl.Int64,
    "l50": pl.Int64,
    "n90": pl.Int64,
    "l90": pl.Int64,
    "aun": pl.Float64,
    "qv": pl.Float64,
    "error_rate": pl.Float64,
    "kmer_completeness": pl.Float64,
    "busco_lineage": pl.Utf8,
    "busco_complete": pl.Float64,
    "busco_single": pl.Float64,
    "busco_duplicated": pl.Float64,
    "busco_fragmented": pl.Float64,
    "busco_missing": pl.Float64,
    "genome_fraction": pl.Float64,
    "misassemblies": pl.Int64,
    "mismatches_per_100kbp": pl.Float64,
    "nga50": pl.Int64,
    "qc_tools": pl.Utf8,
    "n_qc_tools": pl.Int64,
}

SOURCE_PATH_COL = "source_path"
SAMPLE_COL = "sample"

#: Stage word -> (class, rank). Rank orders the pipeline's steps: assembly, long-read
#: polishing, short-read polishing, scaffolding (the scaffolders are alternatives).
STAGES: dict[str, tuple[str, int]] = {
    "assembly": ("assembly", 0),
    "medaka": ("polish", 1),
    "dorado": ("polish", 1),
    "pilon": ("polish", 2),
    "links": ("scaffold", 3),
    "longstitch": ("scaffold", 3),
    "ragtag": ("scaffold", 3),
    "yahs": ("scaffold", 3),
    "hic": ("scaffold", 3),
}

_LABEL = re.compile(rf"^(?P<sample>.+)_(?P<stage>{'|'.join(STAGES)})$")


def split_label(label: str) -> tuple[str, str] | None:
    """`<sample>_<stage>` -> (sample, stage), or None when it is not an assembly name."""
    match = _LABEL.match(label)
    return (match.group("sample"), match.group("stage")) if match else None


TRUTHY = ["true", "yes", "1", "t", "y"]


def _truthy(column: str) -> pl.Expr:
    return pl.col(column).str.strip_chars().str.to_lowercase().is_in(TRUTHY).fill_null(False)


def design_columns(sheet: pl.DataFrame) -> pl.DataFrame:
    """The samplesheet as text, plus `assembler_used` and `scaffolders`."""
    sheet = sheet.select([pl.col(c).cast(pl.Utf8) for c in sheet.columns])
    if SAMPLE_COL not in sheet.columns:
        sheet = sheet.rename({sheet.columns[0]: SAMPLE_COL})

    def _blank(column: str) -> pl.Expr:
        if column not in sheet.columns:
            return pl.lit(None, dtype=pl.Utf8)
        value = pl.col(column).str.strip_chars()
        return pl.when(value.str.len_chars() > 0).then(value).otherwise(None)

    ont, hifi = _blank("assembler_ont"), _blank("assembler_hifi")
    per_platform = pl.concat_str(
        [
            pl.when(ont.is_not_null()).then(ont + pl.lit(" (ONT)")),
            pl.when(hifi.is_not_null()).then(hifi + pl.lit(" (HiFi)")),
        ],
        separator=" + ",
        ignore_nulls=True,
    )
    assembler_used = pl.coalesce(
        _blank("assembler"),
        pl.when(per_platform.str.len_chars() > 0).then(per_platform),
    )

    scaffold_cols = [c for c in sheet.columns if c.startswith("scaffold_")]
    if scaffold_cols:
        scaffolders = pl.concat_str(
            [pl.when(_truthy(c)).then(pl.lit(c.removeprefix("scaffold_"))) for c in scaffold_cols],
            separator=", ",
            ignore_nulls=True,
        )
        scaffolders = pl.when(scaffolders.str.len_chars() > 0).then(scaffolders)
    else:
        scaffolders = pl.lit(None, dtype=pl.Utf8)

    return sheet.with_columns(
        assembler_used.alias("assembler_used"), scaffolders.alias("scaffolders")
    ).unique(subset=[SAMPLE_COL], keep="first", maintain_order=True)


def contiguity(lengths: list[int]) -> dict:
    """N50/L50, N90/L90, auN and totals of one assembly's sequence lengths."""
    ordered = sorted((v for v in lengths if v > 0), reverse=True)
    total = sum(ordered)
    out = {
        "n_sequences": len(ordered),
        "total_length": total,
        "largest_sequence": ordered[0] if ordered else None,
        "n50": None,
        "l50": None,
        "n90": None,
        "l90": None,
        "aun": (sum(v * v for v in ordered) / total) if total else None,
    }
    running = 0
    for index, value in enumerate(ordered, start=1):
        running += value
        if out["n50"] is None and running * 2 >= total:
            out["n50"], out["l50"] = value, index
        if running * 10 >= total * 9:
            out["n90"], out["l90"] = value, index
            break
    return out


def _idxstats_contiguity(raw: pl.DataFrame | None) -> pl.DataFrame:
    schema = {"assembly_id": pl.Utf8} | {
        k: EXPECTED_SCHEMA[k]
        for k in [
            "n_sequences",
            "total_length",
            "largest_sequence",
            "n50",
            "l50",
            "n90",
            "l90",
            "aun",
        ]
    }
    if raw is None or raw.is_empty() or SOURCE_PATH_COL not in raw.columns:
        return pl.DataFrame(schema=schema)
    cols = [c for c in raw.columns if c != SOURCE_PATH_COL]
    name_col, length_col = cols[0], cols[1]
    tidy = raw.select(
        pl.col(SOURCE_PATH_COL)
        .map_elements(
            lambda p: PurePosixPath(p.replace("\\", "/")).name.removesuffix(".idxstats"),
            return_dtype=pl.Utf8,
        )
        .alias("assembly_id"),
        pl.col(name_col).cast(pl.Utf8).alias("name"),
        pl.col(length_col).cast(pl.Float64, strict=False).cast(pl.Int64).alias("length"),
    ).filter((pl.col("name") != "*") & pl.col("length").is_not_null())
    rows = []
    for (label,), group in tidy.group_by(["assembly_id"], maintain_order=True):
        if split_label(str(label)) is None:
            continue
        rows.append({"assembly_id": label, **contiguity(group["length"].to_list())})
    return pl.DataFrame(rows, schema=schema)


def _merqury(frame: pl.DataFrame | None) -> pl.DataFrame:
    schema = {
        "assembly_id": pl.Utf8,
        "qv": pl.Float64,
        "error_rate": pl.Float64,
        "kmer_completeness": pl.Float64,
    }
    if frame is None or frame.is_empty():
        return pl.DataFrame(schema=schema)
    return frame.select(list(schema)).unique(subset=["assembly_id"], keep="first")


def _busco(frame: pl.DataFrame | None) -> pl.DataFrame:
    renames = {
        "lineage": "busco_lineage",
        "complete_pct": "busco_complete",
        "single_pct": "busco_single",
        "duplicated_pct": "busco_duplicated",
        "fragmented_pct": "busco_fragmented",
        "missing_pct": "busco_missing",
    }
    schema = {"assembly_id": pl.Utf8} | {v: EXPECTED_SCHEMA[v] for v in renames.values()}
    if frame is None or frame.is_empty():
        return pl.DataFrame(schema=schema)
    # Several lineages per assembly: keep the most specific, the one with the most markers.
    return (
        frame.sort(["assembly_id", "n_markers"], descending=[False, True], nulls_last=True)
        .unique(subset=["assembly_id"], keep="first", maintain_order=True)
        .rename(renames)
        .select(list(schema))
    )


def _quast_ref(frame: pl.DataFrame | None) -> pl.DataFrame:
    keep = ["genome_fraction", "misassemblies", "mismatches_per_100kbp", "nga50"]
    schema = {"assembly_id": pl.Utf8} | {k: EXPECTED_SCHEMA[k] for k in keep}
    if frame is None or frame.is_empty():
        return pl.DataFrame(schema=schema)
    return frame.select(pl.col("report_id").alias("assembly_id"), *keep).unique(
        subset=["assembly_id"], keep="first"
    )


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """Join every QC block on the published assembly name."""
    blocks = {
        "samtools": _idxstats_contiguity(sources.get("idxstats")),
        "merqury": _merqury(sources.get("merqury")),
        "busco": _busco(sources.get("busco")),
        "quast": _quast_ref(sources.get("quast_ref")),
    }
    labels = sorted(
        {
            label
            for block in blocks.values()
            for label in block["assembly_id"].to_list()
            if label is not None and split_label(label) is not None
        }
    )
    if not labels:
        raise ValueError(
            "genomeassembler assemblies: no QC output named `<sample>_<stage>` was found "
            "(samtools idxstats, Merqury, BUSCO or QUAST)"
        )

    parts = [split_label(label) for label in labels]
    frame = pl.DataFrame(
        {
            "assembly_id": labels,
            "sample": [p[0] for p in parts],
            "stage": [p[1] for p in parts],
            "stage_class": [STAGES[p[1]][0] for p in parts],
            "stage_rank": [STAGES[p[1]][1] for p in parts],
        },
        schema={
            "assembly_id": pl.Utf8,
            "sample": pl.Utf8,
            "stage": pl.Utf8,
            "stage_class": pl.Utf8,
            "stage_rank": pl.Int64,
        },
    )
    found = []
    for tool, block in blocks.items():
        frame = frame.join(block, on="assembly_id", how="left")
        present = set(block["assembly_id"].to_list())
        found.append(pl.when(pl.col("assembly_id").is_in(list(present))).then(pl.lit(tool)))
    frame = frame.with_columns(
        pl.concat_str(found, separator=", ", ignore_nulls=True).alias("qc_tools")
    ).with_columns(pl.col("qc_tools").str.split(", ").list.len().cast(pl.Int64).alias("n_qc_tools"))

    sheet = sources.get("samplesheet")
    if sheet is not None and not sheet.is_empty():
        design = design_columns(sheet)
        passthrough = [c for c in design.columns if c == SAMPLE_COL or c not in EXPECTED_SCHEMA]
        passthrough += ["assembler_used", "scaffolders"]
        frame = frame.join(design.select(passthrough), on=SAMPLE_COL, how="left")
    else:
        frame = frame.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias("assembler_used"),
            pl.lit(None, dtype=pl.Utf8).alias("scaffolders"),
        )

    extra = [c for c in frame.columns if c not in EXPECTED_SCHEMA]
    return frame.select([*EXPECTED_SCHEMA, *extra]).sort(["sample", "stage_rank", "stage"])
