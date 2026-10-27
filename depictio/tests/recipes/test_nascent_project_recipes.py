"""The nf-core/nascent pipeline recipes: the sample hub and the time-course panels.

The catalog recipes they read (featureCounts matrix, strand bedGraphs) are tested in
``test_nascent_recipes.py``; here they only feed the hub and the time course, built from
a tiny synthetic run: four time points, one induced gene, one repressed gene, one gene
that spikes at a single time point (noise, not a response) and stable genes.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe, load_recipe
from depictio.recipes.lib import strand_coverage as sc

V = "2.3.0"
LIBRARIES = ["L_0h", "L_30min", "L_2h", "L_24h"]
#: Counts per library, in LIBRARIES order.
GENES = {
    "UP": [100, 300, 800, 800],
    "DOWN": [800, 400, 100, 100],
    "SPIKE": [200, 1600, 200, 200],
    **{f"FLAT{i}": [400 + i, 400 + i, 400 + i, 400 + i] for i in range(12)},
}


def _featurecounts() -> str:
    header = "Geneid\tChr\tStart\tEnd\tStrand\tLength\t" + "\t".join(
        f"{s}.sorted.bam" for s in LIBRARIES
    )
    rows = [
        f"{g}\tchr{i % 3 + 1}\t{1000 * i}\t{1000 * i + 500}\t+\t501\t" + "\t".join(map(str, c))
        for i, (g, c) in enumerate(GENES.items())
    ]
    return "# Program:featureCounts v2.0.1\n" + "\n".join([header, *rows]) + "\n"


def run(
    recipe: str, root: Path, params: dict | None = None, **sources: pl.DataFrame
) -> pl.DataFrame:
    return execute_recipe(recipe, root, extra_sources=sources, pipeline_version=V, params=params)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    (tmp_path / "quantification" / "gene").mkdir(parents=True)
    (tmp_path / "quantification" / "gene" / "R.featureCounts.txt").write_text(_featurecounts())
    return tmp_path


@pytest.fixture()
def design() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "sample": LIBRARIES,
            "stage": ["Baseline", "Early", "Early", "Late"],
            "time_point": ["0h", "30min", "2h", "1d"],
            "time_h": [0.0, 0.5, 2.0, 24.0],
        }
    )


@pytest.fixture()
def frames(root: Path, design: pl.DataFrame) -> dict[str, pl.DataFrame]:
    out: dict[str, pl.DataFrame] = {"metadata": design}
    out["counts"] = execute_recipe("subread/gene_counts.py", root)
    out["library"] = execute_recipe(
        "subread/library_summary.py", root, extra_sources={"counts": out["counts"]}
    )
    out["samples"] = run(
        "nf-core/nascent/samples.py",
        root,
        {"time_col": "time_h"},
        library=out["library"],
        metadata=design,
    )
    out["dynamics"] = run(
        "nf-core/nascent/gene_dynamics.py", root, counts=out["counts"], samples=out["samples"]
    )
    out["trajectories"] = run(
        "nf-core/nascent/gene_trajectories.py",
        root,
        counts=out["counts"],
        samples=out["samples"],
        dynamics=out["dynamics"],
    )
    return out


def test_hub_carries_time_design_and_qc(frames):
    hub = frames["samples"]
    assert hub["sample"].to_list() == LIBRARIES  # time order
    assert hub.columns[:2] == ["sample", "stage"]
    assert hub["time_point"].to_list() == ["0h", "30min", "2h", "1d"]
    assert hub["phase"].to_list() == ["Baseline", "Early", "Mid", "Late"]
    assert hub["assigned_reads"].null_count() == 0
    # No strand coverage on this run: its columns are present and empty.
    assert hub["plus_share_pct"].null_count() == len(LIBRARIES)


def test_hub_without_a_design_reads_the_time_off_the_library_ids(root, frames):
    hub = run("nf-core/nascent/samples.py", root, {"time_col": "time_h"}, library=frames["library"])
    assert "stage" not in hub.columns
    # GROUP_COL falls back to __no_group__, which carries the phase.
    assert hub.columns[1] == "__no_group__"
    assert hub["__no_group__"].to_list() == hub["phase"].to_list()
    assert hub.filter(pl.col("sample") == "L_30min")["time_h"][0] == pytest.approx(0.5)
    assert hub.filter(pl.col("sample") == "L_24h")["time_point"][0] == "24h"


def test_gene_calls_need_two_time_points(frames):
    calls = dict(zip(frames["dynamics"]["gene_id"], frames["dynamics"]["response"], strict=True))
    assert calls["UP"].startswith("Induced")
    assert calls["DOWN"].startswith("Repressed")
    assert calls["SPIKE"] == "Stable"
    assert calls["FLAT0"] == "Stable"
    up = frames["dynamics"].filter(pl.col("gene_id") == "UP").row(0, named=True)
    assert up["peak_log2fc"] > 2 and up["n_changed"] >= 2


def test_trajectories_and_top_genes(root, frames):
    traj = frames["trajectories"]
    assert traj.filter(pl.col("time_order") == 1)["log2fc"].abs().max() == pytest.approx(0.0)
    # Every class reaches every time point, so a profile can draw its median.
    assert set(traj["response"]) == set(frames["dynamics"]["response"])
    assert traj.group_by("gene_id").len()["len"].unique().to_list() == [4]
    top = run(
        "nf-core/nascent/top_gene_trajectories.py",
        root,
        trajectories=traj,
        dynamics=frames["dynamics"],
    )
    assert set(top["gene_id"]) == {"UP", "DOWN"}
    heatmap = run(
        "nf-core/nascent/top_gene_heatmap.py", root, trajectories=traj, dynamics=frames["dynamics"]
    )
    assert heatmap.columns == ["gene_id", "response", "0h", "30min", "2h", "1d"]


def test_similarity_and_drift(root, frames):
    sim = run(
        "nf-core/nascent/sample_similarity.py",
        root,
        counts=frames["counts"],
        samples=frames["samples"],
    )
    assert "stage" in sim.columns
    base = sim.filter(pl.col("time_order") == 1).row(0, named=True)
    assert base["corr_to_baseline"] == pytest.approx(1.0) and base["corr_to_previous"] is None
    drift = run("nf-core/nascent/sample_drift.py", root, similarity=sim)
    assert drift.group_by("comparison").len().sort("comparison")["len"].to_list() == [4, 3]


@pytest.fixture()
def bins(frames) -> pl.DataFrame:
    """A synthetic window table in the shape of ``bedtools/strand_bins.py``."""
    rows = []
    for w in range(40):
        for i, sample in enumerate(LIBRARIES):
            signal = 100.0 + w
            if w == 5:
                signal *= 2 ** (0, 1, 3, 3)[i]  # a rising window
            if w == 6:
                signal /= 2 ** (0, 1, 3, 3)[i]  # a falling one
            rows.append(
                {
                    "sample": sample,
                    "chromosome": "chr1" if w < 30 else "chr2",
                    "start": w * sc.WINDOW_SIZE,
                    "end": (w + 1) * sc.WINDOW_SIZE,
                    "position": w * sc.WINDOW_SIZE + sc.WINDOW_SIZE // 2,
                    "plus_rpm": signal / 2,
                    "minus_rpm": signal / 2,
                    "signal_rpm": signal,
                }
            )
    return pl.DataFrame(rows).with_columns(
        (pl.col("signal_rpm") + 1).log(2).alias("log2_signal"),
        pl.lit(50.0).alias("plus_share_pct"),
    )


def test_window_dynamics_series_and_heatmap(root, frames, bins):
    dyn = run(
        "nf-core/nascent/signal_window_dynamics.py", root, bins=bins, samples=frames["samples"]
    )
    trend = dict(zip(dyn["window_id"], dyn["trend"], strict=True))
    w5 = f"chr1:{5 * sc.WINDOW_SIZE}-{6 * sc.WINDOW_SIZE}"
    w6 = f"chr1:{6 * sc.WINDOW_SIZE}-{7 * sc.WINDOW_SIZE}"
    # The comparable windows are the transcribed half: the falling window's mean
    # sinks below the median and drops out, the rising one stays.
    assert trend[w5] == "Rising"
    assert w6 not in trend or trend[w6] == "Falling"
    assert set(trend.values()) <= {"Rising", "Falling", "Stable"}
    series = run(
        "nf-core/nascent/signal_window_series.py",
        root,
        bins=bins,
        samples=frames["samples"],
        dynamics=dyn,
    )
    # One row per compared window and time point, with the window's call.
    assert series.group_by("window_id").len()["len"].unique().to_list() == [4]
    assert set(series["window_id"]) == set(dyn["window_id"])
    assert series.filter(pl.col("time_order") == 1)["log2fc"].abs().max() == pytest.approx(0.0)
    assert dict(zip(series["window_id"], series["trend"], strict=True)) == trend
    heat = run(
        "nf-core/nascent/signal_window_heatmap.py",
        root,
        bins=bins,
        samples=frames["samples"],
        dynamics=dyn,
    )
    assert heat.columns == ["window_id", "trend", "0h", "30min", "2h", "1d"]
    chroms = run("nf-core/nascent/chromosome_signal.py", root, bins=bins, samples=frames["samples"])
    shares = chroms.group_by("time_point").agg(pl.col("share_pct").sum())["share_pct"].to_list()
    assert shares == pytest.approx([100.0] * 4)
    assert chroms.filter(pl.col("chromosome") == "chr1")["contig_order"].unique().to_list() == [1]


def test_hub_reads_every_collection_it_names():
    refs = {s.dc_ref for s in load_recipe("nf-core/nascent/samples.py", V).SOURCES}
    assert refs == {"subread_library_summary", "bedtools_strand_summary", "metadata"}
