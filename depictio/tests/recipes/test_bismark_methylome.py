"""The methylseq recipes that turn 750 MB of per-CpG bedGraph into a methylome.

Three things are worth pinning here, and they are the three that would fail
silently rather than loudly:

* **the binning contract.** `genomic_bins.bin_delimited_file` is shared, so its
  window edges and its `n` are a promise to every track that will be built on
  it later, not an implementation detail of one recipe;
* **the completeness filter.** `binned_methylation` keeps only the windows every
  library covers. Drop that and a PCA, a correlation matrix and a per-window
  t-test each silently impute their own holes, in three different ways;
* **the statistics.** `window_group_compare` evaluates the t distribution's tail
  itself, because the slim CLI environment ships numpy and polars and no SciPy.
  A hand-written regularised incomplete beta that is subtly wrong would produce
  p-values that look entirely plausible.

The aligner-agnostic sample id is checked too: the megatest publishes
`_bismark_bt2_`, the hisat2 route publishes `_bismark_hisat2_`, and a pattern
pinned to the first would hand every hisat2 library a sample id with the aligner
still glued to it.
"""

from __future__ import annotations

import gzip
import math
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from depictio.catalog.bismark.binned_methylation import (
    CPG_DENSITY_CLASSES,
    MIN_CPGS_PER_WINDOW,
    MIN_WINDOWS_PER_CONTIG,
)
from depictio.catalog.bismark.window_group_compare import (
    MIN_DELTA_PCT,
    _preferred_group_col,
    benjamini_hochberg,
    compare_windows,
    two_sided_t_p_value,
)
from depictio.recipes import execute_recipe
from depictio.recipes.lib.genomic_bins import DEFAULT_BIN_SIZE, bin_delimited_file

BINNED = "bismark/binned_methylation.py"
COMPARE = "bismark/window_group_compare.py"
SUMMARY = "bismark/summary_report.py"

#: Enough windows on a contig to clear `MIN_WINDOWS_PER_CONTIG`, plus a margin.
CONTIG_WINDOWS = MIN_WINDOWS_PER_CONTIG + 10
#: Enough CpGs in a window to clear `MIN_CPGS_PER_WINDOW`, plus a margin.
CPGS_PER_WINDOW = MIN_CPGS_PER_WINDOW + 5


def _write_bedgraph(path: Path, rows: list[tuple[str, int, float]]) -> None:
    """A Bismark bedGraph: one `track` line, then chrom / start / end / percent."""
    body = "track type=bedGraph\n" + "".join(
        f"{chrom}\t{start}\t{start + 2}\t{pct}\n" for chrom, start, pct in rows
    )
    with gzip.open(path, "wt") as handle:
        handle.write(body)


def _library_rows(
    level: float,
    *,
    contigs: dict[str, int],
    cpgs_per_window: int = CPGS_PER_WINDOW,
    skip: set[tuple[str, int]] | None = None,
) -> list[tuple[str, int, float]]:
    """A whole library's CpGs, every window sitting at `level` percent."""
    skipped = skip or set()
    rows: list[tuple[str, int, float]] = []
    for chrom, n_windows in contigs.items():
        for window in range(n_windows):
            start = window * DEFAULT_BIN_SIZE
            if (chrom, start) in skipped:
                continue
            for cpg in range(cpgs_per_window):
                rows.append((chrom, start + cpg * 3, level))
    return rows


def _index(paths: list[Path]) -> pl.DataFrame:
    """The frame the `bismark_bedgraph_index` scan DC builds: one row per file."""
    return pl.DataFrame(
        {"source_path": [str(p) for p in paths]},
        schema={"source_path": pl.Utf8},
    )


def _bedgraph_name(sample: str, aligner: str = "bt2") -> str:
    return f"{sample}_1_val_1_bismark_{aligner}_pe.deduplicated.bedGraph.gz"


# --------------------------------------------------------------- genomic_bins


def test_bin_delimited_file_averages_over_fixed_windows(tmp_path: Path) -> None:
    """The shared helper's window edges and its `n` are a contract."""
    path = tmp_path / "tiny.bedGraph.gz"
    _write_bedgraph(
        path,
        [("chr1", 0, 10.0), ("chr1", 500, 30.0), ("chr1", DEFAULT_BIN_SIZE + 7, 80.0)],
    )
    out = bin_delimited_file(
        path, column_names=["chrom", "start", "end", "value"], skip_rows=1
    ).sort("start")

    assert out.height == 2
    first, second = out.row(0, named=True), out.row(1, named=True)
    assert (first["chrom"], first["start"], first["end"]) == ("chr1", 0, DEFAULT_BIN_SIZE)
    assert first["mean"] == pytest.approx(20.0)
    assert first["n"] == 2
    assert second["start"] == DEFAULT_BIN_SIZE
    assert second["mean"] == pytest.approx(80.0)
    assert second["n"] == 1


# ---------------------------------------------------------- binned_methylation


def test_the_window_matrix_is_complete_in_every_library(tmp_path: Path) -> None:
    """A window one library never covered is dropped from all of them.

    Keeping it would hand a PCA, a correlation and a t-test a hole each, and
    each of the three would fill it differently.
    """
    contigs = {"chr1": CONTIG_WINDOWS}
    missing = ("chr1", 3 * DEFAULT_BIN_SIZE)
    for index, (sample, level) in enumerate([("S1", 80.0), ("S2", 78.0)]):
        _write_bedgraph(
            tmp_path / _bedgraph_name(sample),
            _library_rows(level, contigs=contigs, skip={missing} if index else None),
        )
    out = execute_recipe(
        BINNED,
        tmp_path,
        extra_sources={"index": _index(sorted(tmp_path.glob("*.bedGraph.gz")))},
    )

    assert out.get_column("sample").unique().sort().to_list() == ["S1", "S2"]
    covered = out.filter(pl.col("chromosome") == missing[0]).get_column("start").unique()
    assert missing[1] not in covered.to_list()
    # And every surviving window is present once per library.
    per_window = out.group_by(["chromosome", "start"]).len().get_column("len").unique()
    assert per_window.to_list() == [2]


def test_a_window_with_too_few_cpgs_is_not_a_measurement(tmp_path: Path) -> None:
    """A mean over three CpGs is not this window's methylation."""
    contigs = {"chr1": CONTIG_WINDOWS}
    thin = ("chr1", 5 * DEFAULT_BIN_SIZE)
    for sample in ("S1", "S2"):
        rows = _library_rows(80.0, contigs=contigs, skip={thin})
        rows += [(thin[0], thin[1] + i * 3, 80.0) for i in range(MIN_CPGS_PER_WINDOW - 1)]
        _write_bedgraph(tmp_path / _bedgraph_name(sample), rows)
    out = execute_recipe(
        BINNED,
        tmp_path,
        extra_sources={"index": _index(sorted(tmp_path.glob("*.bedGraph.gz")))},
    )
    assert thin[1] not in out.get_column("start").unique().to_list()
    assert out.get_column("n_cpg").min() >= MIN_CPGS_PER_WINDOW


def test_assembly_debris_is_dropped_without_naming_a_genome(tmp_path: Path) -> None:
    """Unplaced scaffolds go by window count, not by a hardcoded contig list."""
    contigs = {"chr1": CONTIG_WINDOWS, "chrUn_scaffold": MIN_WINDOWS_PER_CONTIG - 5}
    for sample, level in [("S1", 80.0), ("S2", 78.0)]:
        _write_bedgraph(tmp_path / _bedgraph_name(sample), _library_rows(level, contigs=contigs))
    out = execute_recipe(
        BINNED,
        tmp_path,
        extra_sources={"index": _index(sorted(tmp_path.glob("*.bedGraph.gz")))},
    )
    assert out.get_column("chromosome").unique().to_list() == ["chr1"]


def test_sample_ids_parse_on_both_bismark_routes(tmp_path: Path) -> None:
    """`_bismark_bt2_` and `_bismark_hisat2_` must both strip to the sample."""
    contigs = {"chr1": CONTIG_WINDOWS}
    _write_bedgraph(tmp_path / _bedgraph_name("S1", "bt2"), _library_rows(80.0, contigs=contigs))
    _write_bedgraph(tmp_path / _bedgraph_name("S2", "hisat2"), _library_rows(78.0, contigs=contigs))
    out = execute_recipe(
        BINNED,
        tmp_path,
        extra_sources={"index": _index(sorted(tmp_path.glob("*.bedGraph.gz")))},
    )
    assert out.get_column("sample").unique().sort().to_list() == ["S1", "S2"]


def test_the_cpg_density_class_does_not_change_between_libraries(tmp_path: Path) -> None:
    """The tertile cuts are taken on the whole matrix, once.

    Cut per library and the same genomic window would be CpG-dense in a deep
    library and CpG-poor in a shallow one, which makes the class a depth
    readout rather than a genome property.
    """
    for sample, level in [("S1", 80.0), ("S2", 60.0)]:
        rows: list[tuple[str, int, float]] = []
        for window in range(CONTIG_WINDOWS):
            start = window * DEFAULT_BIN_SIZE
            # A CpG count that varies window to window, so tertiles exist.
            for cpg in range(CPGS_PER_WINDOW + window):
                rows.append(("chr1", start + cpg * 3, level))
        _write_bedgraph(tmp_path / _bedgraph_name(sample), rows)
    out = execute_recipe(
        BINNED,
        tmp_path,
        extra_sources={"index": _index(sorted(tmp_path.glob("*.bedGraph.gz")))},
    )

    assert set(out.get_column("cpg_density_class").unique()) <= set(CPG_DENSITY_CLASSES)
    per_window = out.group_by(["chromosome", "start"]).agg(
        pl.col("cpg_density_class").n_unique().alias("classes")
    )
    assert per_window.get_column("classes").unique().to_list() == [1]


# ------------------------------------------------------------- the statistics


@pytest.mark.parametrize(
    ("t", "df", "expected"),
    [
        # Reference values from the Student t distribution's two-sided tail.
        (0.0, 5, 1.0),
        (2.570582, 5, 0.05),
        (4.604095, 4, 0.01),
        (1.959964, 1_000_000, 0.05),
    ],
)
def test_the_t_tail_is_evaluated_correctly_without_scipy(
    t: float, df: int, expected: float
) -> None:
    assert two_sided_t_p_value(np.array([t]), df)[0] == pytest.approx(expected, rel=1e-5)


def test_the_t_tail_is_symmetric_and_bounded() -> None:
    values = np.linspace(-12.0, 12.0, 97)
    p = two_sided_t_p_value(values, 5)
    assert np.all((p >= 0.0) & (p <= 1.0))
    assert p == pytest.approx(two_sided_t_p_value(-values, 5))
    # Monotone decreasing in |t|.
    ordered = p[np.argsort(np.abs(values))]
    assert np.all(np.diff(ordered) <= 1e-12)


def test_benjamini_hochberg_is_monotone_and_never_shrinks_a_p_value() -> None:
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.74, 0.9])
    padj = benjamini_hochberg(p)
    assert np.all(padj >= p - 1e-12)
    assert np.all(padj <= 1.0)
    # Adjusted values keep the order of the raw ones.
    assert np.all(np.diff(padj[np.argsort(p)]) >= -1e-12)
    # The smallest of n p-values is multiplied by n, capped at the step-up.
    assert padj[0] == pytest.approx(min(0.001 * len(p), padj[1]))


# ------------------------------------------------------- window_group_compare


def _window_frame(levels: dict[str, list[float]], n_windows: int = 40) -> pl.DataFrame:
    """A binned-methylation frame: `levels[sample][window]` is its percentage."""
    rows = []
    for sample, per_window in levels.items():
        for window, pct in enumerate(per_window[:n_windows]):
            start = window * DEFAULT_BIN_SIZE
            rows.append(
                {
                    "sample": sample,
                    "chromosome": "chr1",
                    "start": start,
                    "end": start + DEFAULT_BIN_SIZE,
                    "position": start + DEFAULT_BIN_SIZE // 2,
                    "methylation_pct": pct,
                    "n_cpg": 40,
                    "cpg_density_class": "Intermediate",
                }
            )
    return pl.DataFrame(rows)


def _samples_frame(assignment: dict[str, str], factor: str = "condition") -> pl.DataFrame:
    """A sample hub with the samplesheet columns and one design factor."""
    return pl.DataFrame(
        {
            "sample_id": list(assignment),
            "fastq_1": [f"{s}_1.fastq.gz" for s in assignment],
            "fastq_2": [f"{s}_2.fastq.gz" for s in assignment],
            factor: list(assignment.values()),
        }
    )


def test_the_planted_window_is_the_one_that_comes_out() -> None:
    n_windows = 40
    flat = [70.0, 70.4, 69.6, 70.2]
    levels = {
        "A1": [flat[0]] * n_windows,
        "A2": [flat[1]] * n_windows,
        "B1": [flat[2]] * n_windows,
        "B2": [flat[3]] * n_windows,
    }
    # One window moved far past MIN_DELTA_PCT in the B arm only.
    planted = 7
    for sample in ("B1", "B2"):
        levels[sample][planted] -= MIN_DELTA_PCT * 3

    out = compare_windows(
        _window_frame(levels, n_windows),
        _samples_frame({"A1": "low", "A2": "low", "B1": "high", "B2": "high"}),
    )

    assert out.height == n_windows
    called = out.filter(pl.col("direction") != "Not significant")
    assert called.height == 1
    hit = called.row(0, named=True)
    assert (
        hit["window_id"] == f"chr1:{planted * DEFAULT_BIN_SIZE}-{(planted + 1) * DEFAULT_BIN_SIZE}"
    )
    # The two arms are ordered by their level's name, so `group_a` is "high"
    # (B1/B2, the arm the drop was planted in) and the delta is signed against it.
    assert (hit["group_a"], hit["group_b"]) == ("high", "low")
    assert hit["direction"] == "Hypomethylated"
    assert hit["delta_methylation"] == pytest.approx(-MIN_DELTA_PCT * 3, abs=1.0)
    assert hit["neg_log10_padj"] == pytest.approx(-math.log10(hit["padj"]), rel=1e-9)


def test_a_clean_but_tiny_shift_is_not_called() -> None:
    """A statistically clean two-point shift is not a methylation difference."""
    n_windows = 20
    levels = {
        "A1": [70.00] * n_windows,
        "A2": [70.01] * n_windows,
        "B1": [68.00] * n_windows,
        "B2": [68.01] * n_windows,
    }
    out = compare_windows(
        _window_frame(levels, n_windows),
        _samples_frame({"A1": "low", "A2": "low", "B1": "high", "B2": "high"}),
    )
    assert out.get_column("padj").min() < 0.05  # the test itself is convinced
    assert out.get_column("direction").unique().to_list() == ["Not significant"]


def test_a_design_with_fewer_than_two_libraries_a_side_is_refused() -> None:
    levels = {"A1": [70.0] * 10, "B1": [50.0] * 10, "B2": [51.0] * 10}
    with pytest.raises(ValueError, match="at least two on each side"):
        compare_windows(
            _window_frame(levels, 10),
            _samples_frame({"A1": "low", "B1": "high", "B2": "high"}),
        )


def test_the_first_two_level_design_factor_is_tested() -> None:
    """The hub's factors are read in order; a one-level factor is skipped."""
    levels = {"A1": [70.0] * 10, "A2": [71.0] * 10, "B1": [50.0] * 10, "B2": [51.0] * 10}
    samples = _samples_frame({"A1": "x", "A2": "x", "B1": "x", "B2": "x"}, factor="batch")
    samples = samples.with_columns(
        pl.Series("condition", ["treated", "treated", "control", "control"])
    )
    out = compare_windows(_window_frame(levels, 10), samples)
    assert (out.row(0, named=True)["group_a"], out.row(0, named=True)["group_b"]) == (
        "control",
        "treated",
    )


def _two_factor_samples() -> pl.DataFrame:
    """A hub with two two-level factors: `batch` first, `condition` second."""
    samples = _samples_frame({"A1": "b1", "A2": "b2", "B1": "b1", "B2": "b2"}, factor="batch")
    return samples.with_columns(
        pl.Series("condition", ["treated", "treated", "control", "control"])
    )


def test_group_col_param_wins_over_the_first_two_level_factor() -> None:
    """GROUP_COL, passed as the `group_col` param, is tested when it has two levels."""
    levels = {"A1": [70.0] * 10, "A2": [71.0] * 10, "B1": [50.0] * 10, "B2": [51.0] * 10}
    samples = _two_factor_samples()
    first = compare_windows(_window_frame(levels, 10), samples)
    assert first.row(0, named=True)["group_a"] == "b1"  # fallback: first factor
    chosen = compare_windows(_window_frame(levels, 10), samples, group_col="condition")
    assert (chosen.row(0, named=True)["group_a"], chosen.row(0, named=True)["group_b"]) == (
        "control",
        "treated",
    )


def test_unusable_group_col_falls_back() -> None:
    """A GROUP_COL that is absent, the no-group sentinel, or not two-level falls back."""
    assert _preferred_group_col({"group_col": "__no_group__"}) is None
    assert _preferred_group_col({}) is None
    assert _preferred_group_col(None) is None
    assert _preferred_group_col({"group_col": "condition"}) == "condition"
    levels = {"A1": [70.0] * 10, "A2": [71.0] * 10, "B1": [50.0] * 10, "B2": [51.0] * 10}
    samples = _two_factor_samples().with_columns(pl.lit("x").alias("site"))
    for group_col in ("missing", "site"):
        out = compare_windows(_window_frame(levels, 10), samples, group_col=group_col)
        assert out.row(0, named=True)["group_a"] == "b1"


def test_no_design_means_no_comparison() -> None:
    """Without a two-level factor the recipe refuses, and the DC is skipped."""
    levels = {"A1": [70.0] * 10, "A2": [71.0] * 10, "B1": [50.0] * 10, "B2": [51.0] * 10}
    with pytest.raises(ValueError, match="no two-group comparison"):
        compare_windows(_window_frame(levels, 10), None)
    samplesheet_only = _samples_frame({"A1": "x", "A2": "x", "B1": "x", "B2": "x"}).drop(
        "condition"
    )
    with pytest.raises(ValueError, match="no two-group comparison"):
        compare_windows(_window_frame(levels, 10), samplesheet_only)


def test_every_eligible_window_is_tested_from_the_bedgraphs(tmp_path: Path) -> None:
    """The comparison re-bins the bedGraphs and tests every eligible window.

    It must not inherit the drawing stride of `bismark_binned_methylation`, so
    its row count is the full eligible set: every window of every contig that
    clears the CpG and contig cut-offs.
    """
    contigs = {"chr1": CONTIG_WINDOWS, "chr2": CONTIG_WINDOWS}
    design = {"A1": "low", "A2": "low", "B1": "high", "B2": "high"}
    for sample, level in zip(design, (70.0, 71.0, 50.0, 51.0), strict=True):
        _write_bedgraph(tmp_path / _bedgraph_name(sample), _library_rows(level, contigs=contigs))
    out = execute_recipe(
        COMPARE,
        tmp_path,
        extra_sources={
            "index": _index(sorted(tmp_path.glob("*.bedGraph.gz"))),
            "samples": _samples_frame(design),
        },
    )
    assert out.height == 2 * CONTIG_WINDOWS
    assert out.get_column("window_id").n_unique() == out.height


# ------------------------------------------------------------- summary_report

# The header bismark2summary writes, verbatim, including its own lower-cased
# "chgs" spelling; the recipe matches case-insensitively because of it.
_SUMMARY_HEADER = (
    "File\tTotal Reads\tAligned Reads\tUnaligned Reads\tAmbiguously Aligned Reads\t"
    "No Genomic Sequence\tDuplicate Reads (removed)\tUnique Reads (remaining)\tTotal Cs\t"
    "Methylated CpGs\tUnmethylated CpGs\tMethylated chgs\tUnmethylated chgs\t"
    "Methylated CHHs\tUnmethylated CHHs\n"
)


def _summary_row(sample: str, *, aligner: str = "bt2", chh_pct: float = 1.0) -> str:
    unmethylated_chh = 1_000_000
    methylated_chh = int(round(unmethylated_chh * chh_pct / (100.0 - chh_pct)))
    return (
        f"{sample}_1_val_1_bismark_{aligner}_pe.bam\t1000\t800\t150\t50\t0\t100\t700\t"
        f"500000\t80000\t20000\t2000\t98000\t{methylated_chh}\t{unmethylated_chh}\n"
    )


def test_conversion_efficiency_is_read_off_the_chh_calls(tmp_path: Path) -> None:
    """Mammalian CHH methylation is near zero, so a CHH call is a failed conversion."""
    report = tmp_path / "bismark_summary_report.txt"
    report.write_text(
        _SUMMARY_HEADER
        + _summary_row("S1", chh_pct=1.0)
        + _summary_row("S2", aligner="hisat2", chh_pct=4.0)
    )

    out = execute_recipe(SUMMARY, tmp_path).sort("sample")

    assert out.get_column("sample").to_list() == ["S1", "S2"]
    assert out.get_column("pct_chh_methylation").to_list() == pytest.approx([1.0, 4.0], abs=1e-3)
    assert out.get_column("conversion_efficiency_pct").to_list() == pytest.approx(
        [99.0, 96.0], abs=1e-3
    )
    # `cpgs_called` is the CpG calls the extractor produced, both states.
    assert out.get_column("cpgs_called").to_list() == [100_000, 100_000]
