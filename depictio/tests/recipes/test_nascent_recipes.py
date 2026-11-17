"""Catalog recipes and libs behind nf-core/nascent: featureCounts matrix, strand bedGraphs, time course.

Pinned here because each would fail silently rather than loudly: a library column
that strips to the wrong sample merges two libraries, a window that averages depth
instead of summing read bases weighs a 1 bp interval like a 5 kb one, a window
missing instead of 0 hands a correlation a hole, and a one-time-point spike called a
response is noise on an unreplicated time course.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe
from depictio.recipes.lib import strand_coverage as sc
from depictio.recipes.lib import time_course as tc
from depictio.recipes.lib.count_matrix import expressed_matrix, pca, spearman

COUNTS = "subread/gene_counts.py"
LIBRARY = "subread/library_summary.py"
CORRELATION = "subread/correlation.py"
BINS = "bedtools/strand_bins.py"
SUMMARY = "bedtools/strand_summary.py"

FEATURECOUNTS = (
    '# Program:featureCounts v2.0.1; Command:"featureCounts" "-o" "G.featureCounts.txt"\n'
    "Geneid\tChr\tStart\tEnd\tStrand\tLength\tA_0h.sorted.bam\tA_1h.sorted.bam\tA_2h.sorted.bam\n"
    "G1\tchr1;chr1\t100;500\t200;900\t+;+\t502\t100\t400\t800\n"
    "G2\tchr2\t50\t150\t-\t101\t300\t300\t300\n"
    "G3\tchr3\t10\t20\t+\t11\t0\t0\t0\n"
    "G4\tchr3\t30\t90\t-\t61\t600\t300\t100\n"
)


@pytest.fixture()
def counts_root(tmp_path: Path) -> Path:
    (tmp_path / "quantification" / "gene").mkdir(parents=True)
    (tmp_path / "quantification" / "gene" / "G.featureCounts.txt").write_text(FEATURECOUNTS)
    return tmp_path


@pytest.fixture()
def gene_counts(counts_root: Path) -> pl.DataFrame:
    return execute_recipe(COUNTS, counts_root)


# ---------------------------------------------------------------------------
# featureCounts
# ---------------------------------------------------------------------------


def test_gene_counts_melts_libraries_and_collapses_meta_features(gene_counts: pl.DataFrame):
    assert sorted(gene_counts["sample"].unique()) == ["A_0h", "A_1h", "A_2h"]
    g1 = gene_counts.filter(pl.col("gene_id") == "G1").row(0, named=True)
    assert (g1["chromosome"], g1["start"], g1["end"], g1["strand"]) == ("chr1", 100, 900, "+")
    # A gene with no read anywhere says nothing.
    assert "G3" not in gene_counts["gene_id"].to_list()
    totals = gene_counts.group_by("sample").agg(pl.col("cpm").sum())
    assert totals["cpm"].to_list() == pytest.approx([1e6] * 3)


def test_library_summary_counts_reads_and_detected_genes(gene_counts: pl.DataFrame, counts_root):
    out = execute_recipe(LIBRARY, counts_root, extra_sources={"counts": gene_counts})
    row = out.filter(pl.col("sample") == "A_0h").row(0, named=True)
    assert row["assigned_reads"] == 1000
    assert row["genes_detected"] == 3
    # Fewer than 100 genes: the top 100 hold everything.
    assert row["top100_share_pct"] == pytest.approx(100.0)


def test_correlation_is_square_with_a_unit_diagonal(gene_counts: pl.DataFrame, counts_root):
    out = execute_recipe(CORRELATION, counts_root, extra_sources={"counts": gene_counts})
    assert out.columns == ["sample", "A_0h", "A_1h", "A_2h"]
    for row in out.iter_rows(named=True):
        assert row[row["sample"]] == pytest.approx(1.0)


def test_pca_and_spearman_share_the_expressed_selection(gene_counts: pl.DataFrame):
    matrix = expressed_matrix(gene_counts)
    assert set(matrix["gene_id"]) == {"G1", "G2", "G4"}
    coords = pca(matrix)
    assert coords.columns[:4] == ["sample", "pc1", "pc2", "pc3"]
    assert coords["pc1_variance"][0] + coords["pc2_variance"][0] == pytest.approx(100.0)
    assert spearman(matrix).height == 3


# ---------------------------------------------------------------------------
# Strand bedGraphs
# ---------------------------------------------------------------------------

WINDOW = sc.WINDOW_SIZE
N_WINDOWS = sc.MIN_WINDOWS_PER_CONTIG + 2


def _bedgraph(path: Path, depth: float, *, skip_window: int | None = None) -> None:
    lines = []
    for w in range(N_WINDOWS):
        if w == skip_window:
            continue
        start = w * WINDOW + 1000
        lines.append(f"chr1\t{start}\t{start + 100}\t{depth}")
        lines.append(f"chr1\t{start + 200}\t{start + 201}\t{depth * 10}")
    lines.append(f"chrM\t100\t200\t{depth}")
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture()
def bedgraph_root(tmp_path: Path) -> tuple[Path, pl.DataFrame]:
    cov = tmp_path / "coverage_graphs"
    cov.mkdir()
    _bedgraph(cov / "S_0h.plus.bedGraph", 2.0)
    _bedgraph(cov / "S_0h.minus.bedGraph", 2.0)
    _bedgraph(cov / "S_1h.plus.bedGraph", 3.0, skip_window=4)
    _bedgraph(cov / "S_1h.minus.bedGraph", 1.0)
    # The dREG input beside them is a signed 3' end count, never coverage.
    (cov / "S_0h.dreg.bedGraph").write_text("chr1\t1\t2\t-5\n")
    paths = sorted(str(p) for p in cov.glob("*.bedGraph"))
    index = pl.DataFrame({"source_path": paths})
    return tmp_path, index


def test_strand_files_ignore_the_dreg_bedgraph():
    files = sc.strand_bedgraph_files(
        ["a/S.plus.bedGraph", "a/S.minus.bedGraph", "a/S.dreg.bedGraph"]
    )
    assert [(s, strand) for _p, s, strand in files] == [("S", "minus"), ("S", "plus")]


def test_bins_sum_read_bases_not_depth(bedgraph_root):
    root, index = bedgraph_root
    path = str(root / "coverage_graphs" / "S_0h.plus.bedGraph")
    binned = sc.bin_bedgraph(path)
    first = binned.filter((pl.col("chrom") == "chr1") & (pl.col("start") == 0)).row(0, named=True)
    # 100 bp at depth 2 plus 1 bp at depth 20.
    assert first["read_bases"] == pytest.approx(2 * 100 + 20 * 1)


def test_strand_bins_complete_normalised_and_on_the_chromosomes(bedgraph_root):
    root, index = bedgraph_root
    out = execute_recipe(BINS, root, extra_sources={"index": index})
    assert set(out["chromosome"]) == {"chr1"}  # chrM holds one window: no row
    assert out.group_by("sample").len()["len"].to_list() == [N_WINDOWS, N_WINDOWS]
    gap = out.filter((pl.col("sample") == "S_1h") & (pl.col("start") == 4 * WINDOW)).row(
        0, named=True
    )
    assert gap["plus_rpm"] == 0.0 and gap["minus_rpm"] > 0
    # The library total includes chrM (100 bp at depth 2 per strand), so the
    # chromosome windows hold less than a million: 220 read bases per window and
    # strand against 200 on chrM.
    total = out.filter(pl.col("sample") == "S_0h")["signal_rpm"].sum()
    on_chr1 = 2 * N_WINDOWS * 220
    assert total == pytest.approx(1e6 * on_chr1 / (on_chr1 + 2 * 200))
    balanced = out.filter((pl.col("sample") == "S_0h") & (pl.col("start") == 0))["plus_share_pct"][
        0
    ]
    assert balanced == pytest.approx(50.0)


def test_strand_summary_reads_balance_mito_and_hotspots(bedgraph_root):
    root, index = bedgraph_root
    out = execute_recipe(SUMMARY, root, extra_sources={"index": index})
    s1 = out.filter(pl.col("sample") == "S_1h").row(0, named=True)
    assert s1["plus_share_pct"] == pytest.approx(
        100 * s1["plus_read_bases"] / (s1["plus_read_bases"] + s1["minus_read_bases"])
    )
    assert s1["plus_share_pct"] > 50
    assert 0 < s1["mito_pct"] < 5
    assert s1["off_main_pct"] == pytest.approx(s1["mito_pct"])
    # Equal windows: the top 1% (one window of 22) holds about 1/22 of the signal.
    s0 = out.filter(pl.col("sample") == "S_0h").row(0, named=True)
    assert s0["hotspot_share_pct"] == pytest.approx(100 / N_WINDOWS, rel=1e-6)


def test_strand_bins_refuse_an_index_without_paths():
    with pytest.raises(ValueError, match="include_file_paths"):
        sc.files_from_index(pl.DataFrame({"chrom": ["chr1"]}), "x")


# ---------------------------------------------------------------------------
# Time course
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "hours"),
    [
        ("GM_0h", 0.0),
        ("GM_30min", 0.5),
        ("x_1.5hr", 1.5),
        ("A_2d", 48.0),
        ("72h", 72.0),
        ("REP12", None),
        ("sample", None),
    ],
)
def test_parse_hours_reads_only_a_trailing_duration(label, hours):
    assert tc.parse_hours(label) == hours


def test_sample_times_prefers_the_design_and_ranks_phases():
    design = pl.DataFrame(
        {
            "sample": ["a", "b", "c", "d"],
            "time_h": [0, 1, 4, 24],
            "time_point": ["0h", "1h", "4h", "1d"],
        }
    )
    out = tc.sample_times(["a", "b", "c", "d"], design, "time_h").sort("time_order")
    assert out["time_point"].to_list() == ["0h", "1h", "4h", "1d"]
    assert out["phase"].to_list() == ["Baseline", "Early", "Mid", "Late"]
    parsed = tc.sample_times(["X_0h", "X_30min", "X_odd"])
    assert parsed.filter(pl.col("sample") == "X_odd")["time_order"][0] is None
    assert parsed.filter(pl.col("sample") == "X_30min")["time_point"][0] == "30min"


def _points(values: dict[str, list[float]]) -> pl.DataFrame:
    samples = [f"S_{h}h" for h in range(len(next(iter(values.values()))))]
    long = pl.DataFrame(
        [
            {"gene_id": g, "sample": s, "v": v}
            for g, vs in values.items()
            for s, v in zip(samples, vs, strict=True)
        ]
    )
    return tc.time_point_values(long, tc.sample_times(samples), key="gene_id", value_col="v")


def test_a_response_needs_two_changed_time_points():
    calls = tc.classify_changes(
        _points(
            {
                "up": [0, 1.5, 2, 2],
                "spike": [0, 3, 0, 0],
                "down": [3, 1, 1, 3],
                "flat": [1, 1, 1, 1],
            }
        ),
        key="gene_id",
    )
    direction = dict(zip(calls["gene_id"], calls["direction"], strict=True))
    assert direction == {"up": "Up", "spike": "Stable", "down": "Down", "flat": "Stable"}
    up = calls.filter(pl.col("gene_id") == "up").row(0, named=True)
    assert up["peak_log2fc"] == pytest.approx(2.0) and up["n_changed"] == 3


def test_a_two_point_course_calls_on_its_only_later_point():
    calls = tc.classify_changes(_points({"up": [0, 2], "flat": [1, 1.2]}), key="gene_id")
    assert dict(zip(calls["gene_id"], calls["direction"], strict=True)) == {
        "up": "Up",
        "flat": "Stable",
    }
