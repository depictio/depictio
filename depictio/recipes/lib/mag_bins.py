"""Identify a metagenome-assembled genome from the name its tools give it.

Every per-bin table nf-core/mag publishes names the bin, the run it came from,
or both, and never carries the sample, assembler and binner as columns. The
three facts a dashboard filters on therefore have to be recovered from strings:

    METAMDBG-MetaBAT2-unclassified-unrefined-CAPES_S21   run label (file name)
    METAMDBG-MetaBAT2-CAPES_S21.1                        bin id (table column)
    FLYE-SemiBin2-CAPES_S11_10                           bin id, SemiBin2 spelling

Both shapes start with the assembler and the binner. A run label ends with the
sample, with any number of refinement qualifiers (`unclassified`, `unrefined`,
`refined`, a DAS Tool tag) in between. A bin id ends with the sample followed by
the binner's own index, separated by `.` for MaxBin2 / MetaBAT2 / MetaBinner /
COMEBin and by `_` for SemiBin2.

Splitting on the separator would be ambiguous for a bin id, because the sample
itself contains `_` (`CAPES_S11`). The index is matched as *digits only* at the
end of the string instead, which never eats a token such as `_S11`. A bin id
that carries no index (a binner that writes one bin per run) keeps its whole
tail as the sample.

Shared here rather than copied because the checkm2, quast, gtdbtk, prokka and
mag catalog tools all need exactly this and recipes may not import each other.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

import polars as pl

#: `<sample>.<index>` (MaxBin2, MetaBAT2, MetaBinner, COMEBin) or
#: `<sample>_<index>` (SemiBin2). Greedy on the sample so `CAPES_S11_10`
#: splits after `CAPES_S11` and not after `CAPES`.
_BIN_INDEX_RE = re.compile(r"^(?P<sample>.+)[._](?P<index>\d+)$")

#: Columns `label_lookup` and `bin_id_lookup` return, in order.
RUN_FIELDS = ("assembler", "binner", "sample")
BIN_FIELDS = ("assembler", "binner", "sample", "bin_index")


def parse_run_label(label: str) -> tuple[str | None, str | None, str | None]:
    """Assembler, binner and sample of a `<ASM>-<BINNER>[-<qualifier>]-<SAMPLE>` label."""
    parts = [p for p in str(label).split("-") if p]
    if len(parts) < 3:
        return (None, None, None)
    return (parts[0], parts[1], parts[-1])


def parse_bin_id(bin_id: str) -> tuple[str | None, str | None, str | None, str | None]:
    """Assembler, binner, sample and binner index of a bin identifier."""
    parts = [p for p in str(bin_id).split("-") if p]
    if len(parts) < 3:
        return (None, None, None, None)
    assembler, binner, tail = parts[0], parts[1], parts[-1]
    match = _BIN_INDEX_RE.match(tail)
    if match is None:
        return (assembler, binner, tail, None)
    return (assembler, binner, match.group("sample"), match.group("index"))


def label_lookup(labels: Iterable[str], key: str = "run_label") -> pl.DataFrame:
    """A unique `key` -> assembler / binner / sample frame, ready to join."""
    unique = sorted({str(label) for label in labels if label is not None})
    rows = [(label, *parse_run_label(label)) for label in unique]
    return pl.DataFrame(
        rows,
        schema=[(key, pl.Utf8), *((field, pl.Utf8) for field in RUN_FIELDS)],
        orient="row",
    )


def bin_id_lookup(bin_ids: Iterable[str], key: str = "bin_id") -> pl.DataFrame:
    """A unique `key` -> assembler / binner / sample / bin_index frame, ready to join."""
    unique = sorted({str(bin_id) for bin_id in bin_ids if bin_id is not None})
    rows = [(bin_id, *parse_bin_id(bin_id)) for bin_id in unique]
    return pl.DataFrame(
        rows,
        schema=[(key, pl.Utf8), *((field, pl.Utf8) for field in BIN_FIELDS)],
        orient="row",
    )


def file_stem(path: str, *strip: str) -> str:
    """The file name of `path` with the directories and `strip` suffixes removed."""
    stem = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    for suffix in strip:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem


def file_stem_expr(path: pl.Expr, *strip: str) -> pl.Expr:
    """`file_stem` as an expression, for a whole column of paths at once."""
    stem = path.cast(pl.Utf8).str.replace_all("\\", "/", literal=True).str.split("/").list.last()
    if not strip:
        return stem
    # Leftmost-first alternation, so the suffix that starts earliest in the name
    # is the one stripped: `_checkm2_report.tsv` before `.tsv`.
    alternation = "|".join(re.escape(suffix) for suffix in strip)
    return stem.str.replace(f"(?:{alternation})$", "")


def quality_tier(completeness: pl.Expr, contamination: pl.Expr) -> pl.Expr:
    """CheckM2-only quality band of a bin, in the MIMAG completeness bands.

    This is not the full MIMAG tier: a high-quality MIMAG draft also needs the
    5S / 16S / 23S rRNA genes and at least 18 tRNAs, which CheckM2 does not
    report. `mag/bin_summary` adds those from Prokka and calls its own column
    `mimag_tier`; this one says only what CheckM2 can support.
    """
    return (
        pl.when(completeness.is_null() | contamination.is_null())
        .then(pl.lit("Unknown"))
        .when(contamination > 10)
        .then(pl.lit("Contaminated"))
        .when((completeness >= 90) & (contamination <= 5))
        .then(pl.lit("High quality"))
        .when(completeness >= 50)
        .then(pl.lit("Medium quality"))
        .otherwise(pl.lit("Low quality"))
        .cast(pl.Utf8)
    )
