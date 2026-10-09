"""`nf-core/chipseq/deseq2_qc_pca.py` at 2.1.0: the shared PCA, with the condition.

2.x publishes the same `*.pca.vals_mqc.tsv` as 1.x, one per antibody, under
`consensus/<antibody>/deseq2/`. The override delegates the parsing to the shared
recipe (same columns, components resolved per matrix) and joins each library's
condition from the design hub when it is passed in.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe, load_recipe

RECIPE = "nf-core/chipseq/deseq2_qc_pca.py"
VERSION = "2.1.0"

_HEADER = (
    "#id: 'deseq2_pca_1'\n"
    "#section_name: 'MERGED LIB: DESeq2 PCA plot'\n"
    '#description: "PCA plot of the samples in the experiment.\n'
    '#              A second comment line."\n'
    "#plot_type: 'scatter'\n"
)
_ABX = (
    _HEADER + '"sample"\t"PC1: 62% variance"\t"PC2: 22% variance"\n'
    '"ABX_WT_REP1"\t-4.5\t-8.0\n'
    '"ABX_WT_REP2"\t-11.3\t5.2\n'
    '"ABX_KO_REP1"\t8.3\t0.8\n'
    '"ABX_KO_REP2"\t7.5\t2.1\n'
)
_ABY = (
    _HEADER + '"sample"\t"PC1: 91% variance"\t"PC2: 7% variance"\n'
    '"ABY_KO_REP1"\t2.0\t0.1\n'
    '"ABY_KO_REP2"\t-2.0\t-0.1\n'
)

_DESIGN = pl.DataFrame(
    {
        "sample_id": ["ABX_WT_REP1", "ABX_WT_REP2", "ABX_KO_REP1", "ABX_KO_REP2", "ABY_KO_REP1"],
        "condition": ["wildtype", "wildtype", "knockout", "knockout", "knockout"],
    }
)


def _tree(tmp_path: Path) -> Path:
    for antibody, body in (("ABX", _ABX), ("ABY", _ABY)):
        folder = tmp_path / "bwa/merged_library/macs3/narrow_peak/consensus" / antibody / "deseq2"
        folder.mkdir(parents=True)
        (folder / f"{antibody}.consensus_peaks.pca.vals_mqc.tsv").write_text(body)
        # The plain copy beside it must not be read twice.
        (folder / f"{antibody}.consensus_peaks.pca.vals.txt").write_text(body)
    return tmp_path


def test_override_keeps_the_shared_output_schema() -> None:
    override = load_recipe(RECIPE, VERSION)
    shared = load_recipe(RECIPE)
    assert override.__file__ != shared.__file__
    assert override.OUTPUT_SCHEMA == shared.OUTPUT_SCHEMA


def test_components_per_antibody_with_the_condition_joined(tmp_path: Path) -> None:
    out = execute_recipe(
        RECIPE, _tree(tmp_path), extra_sources={"design": _DESIGN}, pipeline_version=VERSION
    )
    assert out.height == 6
    rows = {r["sample_id"]: r for r in out.iter_rows(named=True)}
    # Each matrix keeps its own axes and percentages.
    assert rows["ABX_WT_REP1"]["dim_1"] == -4.5
    assert rows["ABX_WT_REP1"]["dim_1_percent"] == 62.0
    assert rows["ABY_KO_REP1"]["dim_1"] == 2.0
    assert rows["ABY_KO_REP1"]["dim_1_percent"] == 91.0
    assert rows["ABX_WT_REP1"]["consensus_set"] != rows["ABY_KO_REP1"]["consensus_set"]
    assert rows["ABX_KO_REP2"]["condition"] == "knockout"
    # A library the hub does not list keeps its row, with no condition.
    assert rows["ABY_KO_REP2"]["condition"] is None


def test_without_the_design_hub_the_shared_columns_come_back(tmp_path: Path) -> None:
    out = execute_recipe(RECIPE, _tree(tmp_path), pipeline_version=VERSION)
    assert out.columns == [
        "sample_id",
        "consensus_set",
        "dim_1",
        "dim_2",
        "dim_1_percent",
        "dim_2_percent",
    ]
    assert out.height == 6
