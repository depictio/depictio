"""Read STAR's ``Log.final.out`` and ``SJ.out.tab`` with Polars alone.

Every STAR-based nf-core pipeline (rnaseq, rnavar, rnafusion, rnasplice,
circrna, ...) publishes the aligner's own two per-sample summaries next to the
BAM: ``<sample>.Log.final.out`` (the read fate, the splice and the error
rates) and ``<sample>.SJ.out.tab`` (one row per collapsed splice junction).
MultiQC parses the first into a few percentages and never reads the second, so
the catalog reads both itself. Shared here because three catalog recipes
(``star/log_final``, ``star/read_fate``, ``star/junctions``) need the same
parsing, and recipes may not import each other.

``Log.final.out`` is a two-column key/value list, ``<key> |<TAB><value>``, with
section titles (``UNIQUE READS:``) that carry no value. A source therefore reads
one LINE per row (a separator the file cannot contain), and the key is
everything before the last ``|``.

The sample is the file name with STAR's suffix removed: ``GM12878_REP1.Log.final.out``
and ``GM12878_REP1.SJ.out.tab`` both name ``GM12878_REP1``. nf-core writes the
prefix as the samplesheet id, so nothing else needs stripping.
"""

from __future__ import annotations

import re

import polars as pl

#: Column holding one full report line (sources read with a separator the
#: report cannot contain).
RAW_LINE_COL = "raw_line"
#: Column carrying the report's path (``source_path`` on the recipe source).
SOURCE_PATH_COL = "source_path"

_STAR_SUFFIX_RE = r"\.(?:Log\.final\.out|SJ\.out\.tab)(?:\.gz)?$"

#: ``Log.final.out`` key (stripped) -> output column. Percent keys keep their
#: number and lose the ``%`` sign; counts are integers.
LOG_KEYS: dict[str, str] = {
    "Number of input reads": "input_reads",
    "Average input read length": "avg_input_read_length",
    "Uniquely mapped reads number": "uniquely_mapped",
    "Uniquely mapped reads %": "uniquely_mapped_pct",
    "Average mapped length": "avg_mapped_length",
    "Number of splices: Total": "splices_total",
    "Number of splices: Annotated (sjdb)": "splices_annotated",
    "Number of splices: GT/AG": "splices_gt_ag",
    "Number of splices: GC/AG": "splices_gc_ag",
    "Number of splices: AT/AC": "splices_at_ac",
    "Number of splices: Non-canonical": "splices_noncanonical",
    "Mismatch rate per base, %": "mismatch_rate_pct",
    "Deletion rate per base": "deletion_rate_pct",
    "Insertion rate per base": "insertion_rate_pct",
    "Number of reads mapped to multiple loci": "multimapped",
    "% of reads mapped to multiple loci": "multimapped_pct",
    "Number of reads mapped to too many loci": "too_many_loci",
    "% of reads mapped to too many loci": "too_many_loci_pct",
    "Number of reads unmapped: too many mismatches": "unmapped_mismatches",
    "% of reads unmapped: too many mismatches": "unmapped_mismatches_pct",
    "Number of reads unmapped: too short": "unmapped_too_short",
    "% of reads unmapped: too short": "unmapped_too_short_pct",
    "Number of reads unmapped: other": "unmapped_other",
    "% of reads unmapped: other": "unmapped_other_pct",
    "Number of chimeric reads": "chimeric",
    "% of chimeric reads": "chimeric_pct",
}

#: Columns read as integers; every other ``LOG_KEYS`` column is a float.
INT_COLUMNS = frozenset(
    {
        "input_reads",
        "uniquely_mapped",
        "splices_total",
        "splices_annotated",
        "splices_gt_ag",
        "splices_gc_ag",
        "splices_at_ac",
        "splices_noncanonical",
        "multimapped",
        "too_many_loci",
        "unmapped_mismatches",
        "unmapped_too_short",
        "unmapped_other",
        "chimeric",
    }
)

#: SJ.out.tab column 5, the intron motif STAR assigns from the genome.
#: Odd codes are the + strand reading, even ones the - strand reading of the
#: same motif, so they fold onto four classes.
MOTIF_CLASSES: dict[int, str] = {
    0: "non-canonical",
    1: "GT/AG",
    2: "GT/AG",
    3: "GC/AG",
    4: "GC/AG",
    5: "AT/AC",
    6: "AT/AC",
}
#: SJ.out.tab has no header; these are STAR's documented column meanings.
SJ_COLUMNS = [
    "chrom",
    "intron_start",
    "intron_end",
    "strand",
    "motif",
    "annotated",
    "unique_reads",
    "multimapping_reads",
    "max_overhang",
]


def sample_from_path(path: str) -> str:
    """``reports/star/GM12878_REP1/GM12878_REP1.Log.final.out`` -> ``GM12878_REP1``."""
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(_STAR_SUFFIX_RE, "", name)


def _number(text: str) -> float | None:
    cleaned = text.strip().rstrip("%").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_log_final(raw: pl.DataFrame) -> pl.DataFrame:
    """One row per ``Log.final.out``: ``sample`` plus every ``LOG_KEYS`` column.

    A key a STAR version does not write comes back null rather than failing the
    collection; two reports of one sample keep the first.
    """
    rows: list[dict[str, object]] = []
    for (path,), block in raw.group_by(SOURCE_PATH_COL, maintain_order=True):
        row: dict[str, object] = {"sample": sample_from_path(str(path))}
        for line in block[RAW_LINE_COL].to_list():
            text = str(line or "")
            if "|" not in text:
                continue
            key, _, value = text.rpartition("|")
            column = LOG_KEYS.get(key.strip())
            if column is None:
                continue
            number = _number(value)
            row[column] = int(number) if number is not None and column in INT_COLUMNS else number
        rows.append(row)
    schema: dict[str, type[pl.DataType]] = {"sample": pl.Utf8}
    schema.update({c: pl.Int64 if c in INT_COLUMNS else pl.Float64 for c in LOG_KEYS.values()})
    if not rows:
        return pl.DataFrame(schema=schema)
    frame = pl.DataFrame(rows, infer_schema_length=None)
    for column, dtype in schema.items():
        if column not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=dtype).alias(column))
    return (
        frame.select([pl.col(c).cast(t) for c, t in schema.items()])
        .unique(subset="sample", keep="first", maintain_order=True)
        .sort("sample")
    )
