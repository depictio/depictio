"""Recover a library name from a Bismark output file name.

Every Bismark output a methylseq run publishes is named after the read-1 FASTQ
it came from, with the trimming stage, the aligner and the step that wrote the
file glued on::

    SRR389222_1_val_1_bismark_bt2_PE_report.txt           bismark align
    SRR389222_1_val_1_bismark_bt2_pe.deduplication_report.txt
    SRR389222_1_val_1_bismark_hisat2_pe.deduplicated.M-bias.txt
    SRR389222_1_val_1_bismark_bt2_pe.deduplicated.bedGraph.gz

The tail differs per step, so each recipe owns the regex for the file it reads;
what is shared is the stripping itself, which every bismark recipe needs and
which recipes may not import from one another.

The per-CpG bedGraph gets a little more: its suffix, its column names and the
window eligibility rules (``eligible_methylation_windows``), because the
binned-methylation recipe and the group comparison must agree on which windows
exist, and recipes may not import from one another.

Shared here rather than copied because seven recipes in one tool need exactly
this, and two of them used to run the regex through a one-element polars Series
(the Rust regex crate) while the other five used Python ``re``, which is two
implementations of one idea.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from depictio.recipes.lib.genomic_bins import complete_window_frame


def sample_id_from_filename(path: str, suffix: re.Pattern[str]) -> str:
    """The library name left once ``suffix`` is stripped from the file's name.

    Never returns an empty string: a name that is entirely suffix is handed back
    as it came, because dropping a sample id silently merges samples.
    """
    name = Path(str(path)).name
    return suffix.sub("", name) or name


#: The tail every per-CpG bedGraph a methylseq run writes carries after the
#: library name: ``_1_val_1_bismark_bt2_pe.deduplicated.bedGraph.gz`` and its
#: single-end, hisat2, ``--skip_trimming`` and ``--skip_deduplication`` spellings.
BEDGRAPH_SUFFIX_RE = re.compile(
    r"(_\d+)?(_val_\d+)?_bismark_[a-z0-9]+_(pe|se)(\.deduplicated)?\.bedGraph\.gz$", re.IGNORECASE
)
#: Column names of a Bismark bedGraph, which ships no header line.
BEDGRAPH_COLUMNS = ["chrom", "start", "end", "pct"]


def bedgraph_files(paths: list[str]) -> list[tuple[str, str]]:
    """``(path, library)`` for every distinct bedGraph path, sorted by path."""
    return [
        (path, sample_id_from_filename(path, BEDGRAPH_SUFFIX_RE))
        for path in sorted({str(p) for p in paths if p})
    ]


#: Window width of every binned-methylation panel. See
#: ``genomic_bins.DEFAULT_BIN_SIZE`` for why 10 kb.
WINDOW_SIZE = 10_000
#: A window mean is a measurement only once enough CpGs stand behind it.
MIN_CPGS_PER_WINDOW = 20
#: Contigs with fewer surviving windows than this are assembly debris.
MIN_WINDOWS_PER_CONTIG = 50
#: Column of the bedGraph index scan that carries each file's path.
SOURCE_PATH_COL = "source_path"


def eligible_methylation_windows(index: pl.DataFrame, label: str) -> pl.DataFrame:
    """Every 10 kb window measured in every library, before any decimation.

    Read from the ``bismark_bedgraph_index`` scan (one row per per-CpG bedGraph,
    carrying its path). Shared by the binned-methylation recipe, which then
    strides it for drawing, and by the group comparison, which tests all of it,
    so both apply the same eligibility rules. Columns: ``sample, chromosome,
    start, end, methylation_pct, n_cpg``.
    """
    if index is None or index.is_empty():
        raise ValueError(f"{label}: the bedGraph index is empty")
    if SOURCE_PATH_COL not in index.columns:
        raise ValueError(
            f"{label}: the bedGraph index must be scanned with include_file_paths={SOURCE_PATH_COL}"
        )
    return complete_window_frame(
        bedgraph_files(index.get_column(SOURCE_PATH_COL).to_list()),
        column_names=BEDGRAPH_COLUMNS,
        chrom_col="chrom",
        pos_col="start",
        value_col="pct",
        bin_size=WINDOW_SIZE,
        skip_rows=1,
        min_obs=MIN_CPGS_PER_WINDOW,
        min_windows_per_contig=MIN_WINDOWS_PER_CONTIG,
        label=label,
    ).rename({"mean": "methylation_pct", "n": "n_cpg"})


#: Sample-hub columns that are never a design factor.
HUB_NON_FACTOR_COLUMNS = frozenset({"sample_id", "sample", "fastq_1", "fastq_2", "genome"})


def hub_factor_columns(samples: pl.DataFrame | None) -> list[str]:
    """The design factors a methylseq ``samples`` hub carries, in its own order.

    The hub passes the run's ``METADATA_FILE`` columns through under their own
    names, so the factors are whatever is left once the id and samplesheet
    columns are set aside; empty without a hub or a design table.
    """
    if samples is None or samples.is_empty():
        return []
    return [c for c in samples.columns if c not in HUB_NON_FACTOR_COLUMNS]
