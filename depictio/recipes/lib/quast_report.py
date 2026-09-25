"""Read a QUAST transposed report, whatever QUAST called its columns.

QUAST writes the same table for a whole assembly and for a single bin, one row
per assembly in `transposed_report.tsv` (and in the `*-quast_summary.tsv`
nf-core/mag aggregates per binning run). Its column names carry units and
comparison operators (`# contigs (>= 1000 bp)`, `GC (%)`, `# N's per 100 kbp`),
which change between QUAST versions and between the `quast` and `metaquast`
front-ends, so nothing may match them literally.

Names are folded to `#` -> `n`, non-alphanumerics -> `_` before matching, which
turns `# contigs (>= 1000 bp)` into `n_contigs_1000_bp` and `GC (%)` into
`gc`. The two families that vary with QUAST's `--contig-thresholds` are matched
by pattern rather than by name, so a run configured with other thresholds still
reads.

Shared by the `quast` catalog outputs (whole assemblies, per-bin summaries and
the contig-length ladder) because they parse one file shape three ways and
recipes may not import each other.
"""

from __future__ import annotations

import re

import polars as pl

#: `# contigs (>= 1000 bp)` and `Total length (>= 1000 bp)` after folding.
_N_CONTIGS_THRESHOLD_RE = re.compile(r"^n_contigs_(?P<bp>\d+)_bp$")
_TOTAL_LENGTH_THRESHOLD_RE = re.compile(r"^total_length_(?P<bp>\d+)_bp$")

#: Output column -> the folded QUAST name it comes from. The unqualified
#: `# contigs` / `Total length` are QUAST's own headline numbers (contigs past
#: its `--min-contig` cut), not a threshold row.
SCALAR_COLUMNS: dict[str, str] = {
    "n_contigs": "n_contigs",
    "largest_contig": "largest_contig",
    "total_length": "total_length",
    "gc_percent": "gc",
    "n50": "n50",
    "n75": "n75",
    "l50": "l50",
    "l75": "l75",
    "ns_per_100_kbp": "n_ns_per_100_kbp",
    "predicted_rrna_genes": "n_predicted_rrna_genes",
}

#: Which of those are counts rather than measurements.
INTEGER_COLUMNS: frozenset[str] = frozenset(
    {"n_contigs", "largest_contig", "total_length", "n50", "n75", "l50", "l75"}
)


def fold(name: str) -> str:
    """QUAST's column name reduced to something stable across its versions."""
    folded = str(name).strip().lower().replace("#", "n").replace("'", "")
    folded = re.sub(r"[^0-9a-z]+", "_", folded)
    return folded.strip("_")


def column_map(columns: list[str]) -> dict[str, str]:
    """Folded name -> original name, first spelling wins."""
    mapping: dict[str, str] = {}
    for column in columns:
        mapping.setdefault(fold(column), column)
    return mapping


def scalar_expressions(columns: list[str]) -> list[pl.Expr]:
    """One cast expression per entry of `SCALAR_COLUMNS`, null when absent.

    `# predicted rRNA genes` is left as text on purpose: QUAST writes it as
    `23 + 20 part`, so a cast would silently drop the partial hits.
    """
    mapping = column_map(columns)
    expressions: list[pl.Expr] = []
    for alias, folded in SCALAR_COLUMNS.items():
        original = mapping.get(folded)
        if original is None:
            dtype = pl.Utf8 if alias == "predicted_rrna_genes" else pl.Float64
            if alias in INTEGER_COLUMNS:
                dtype = pl.Int64
            expressions.append(pl.lit(None, dtype=dtype).alias(alias))
        elif alias == "predicted_rrna_genes":
            expressions.append(pl.col(original).cast(pl.Utf8).alias(alias))
        elif alias in INTEGER_COLUMNS:
            expressions.append(
                pl.col(original)
                .cast(pl.Float64, strict=False)
                .cast(pl.Int64, strict=False)
                .alias(alias)
            )
        else:
            expressions.append(pl.col(original).cast(pl.Float64, strict=False).alias(alias))
    return expressions


def label_parts(label: pl.Expr) -> tuple[pl.Expr, pl.Expr]:
    """``<assembler>-<sample>`` split into (assembler, sample) expressions.

    nf-core/mag labels every assembly it hands to QUAST that way. A label with
    no dash keeps both parts null, and a part that is empty (a leading or
    trailing dash) is null rather than "", so a filter on either column never
    offers a blank value.
    """
    text = label.cast(pl.Utf8)
    has_dash = text.str.contains("-", literal=True)
    assembler = text.str.extract(r"^([^-]*)-", 1)
    sample = text.str.extract(r"^[^-]*-(.*)$", 1)
    return (
        pl.when(has_dash & (assembler.str.len_chars() > 0)).then(assembler).otherwise(None),
        pl.when(has_dash & (sample.str.len_chars() > 0)).then(sample).otherwise(None),
    )


def threshold_columns(columns: list[str]) -> list[tuple[int, str | None, str | None]]:
    """Every `--contig-thresholds` step present, as (bp, n_contigs_col, total_length_col)."""
    mapping = column_map(columns)
    counts: dict[int, str] = {}
    lengths: dict[int, str] = {}
    for folded, original in mapping.items():
        match = _N_CONTIGS_THRESHOLD_RE.match(folded)
        if match:
            counts[int(match.group("bp"))] = original
            continue
        match = _TOTAL_LENGTH_THRESHOLD_RE.match(folded)
        if match:
            lengths[int(match.group("bp"))] = original
    steps = sorted(set(counts) | set(lengths))
    return [(bp, counts.get(bp), lengths.get(bp)) for bp in steps]
