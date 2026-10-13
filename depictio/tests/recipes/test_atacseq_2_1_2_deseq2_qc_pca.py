"""`nf-core/atacseq/deseq2_qc_pca.py` at 2.1.2: the catalog PCA, with each sample's group."""

from __future__ import annotations

from pathlib import Path

from depictio.recipes import execute_recipe, load_recipe

RECIPE = "nf-core/atacseq/deseq2_qc_pca.py"
VERSION = "2.1.2"

_PCA = (
    '"sample"\t"PC1: 49% variance"\t"PC2: 19% variance"\n'
    '"SPT5_T0_REP1"\t-9.0\t3.2\n'
    '"SPT5_T0_REP2"\t-13.5\t8.0\n'
    '"SPT5_T15_REP1"\t-3.9\t-8.4\n'
    '"SPT5_INPUT_REP1"\t14.8\t7.5\n'
)


def _tree(tmp_path: Path) -> Path:
    for level, prefix in (("merged_library", "mLb"), ("merged_replicate", "mRp")):
        folder = tmp_path / "bwa" / level / "macs2/broad_peak/consensus/deseq2"
        folder.mkdir(parents=True)
        (folder / f"consensus_peaks.{prefix}.clN.pca.vals.txt").write_text(_PCA)
    return tmp_path


def test_keeps_the_catalog_columns() -> None:
    shared = load_recipe("deseq2/qc_pca.py")
    override = load_recipe(RECIPE, VERSION)
    assert {k: v for k, v in override.OUTPUT_SCHEMA.items() if k != "group"} == shared.OUTPUT_SCHEMA


def test_merged_library_only_with_the_group(tmp_path: Path) -> None:
    out = execute_recipe(RECIPE, _tree(tmp_path), pipeline_version=VERSION)
    assert out.height == 4
    groups = dict(zip(out["sample_id"], out["group"], strict=True))
    assert groups == {
        "SPT5_T0_REP1": "SPT5_T0",
        "SPT5_T0_REP2": "SPT5_T0",
        "SPT5_T15_REP1": "SPT5_T15",
        "SPT5_INPUT_REP1": "SPT5_INPUT",
    }
    assert out["dim_1_percent"].unique().to_list() == [49.0]
