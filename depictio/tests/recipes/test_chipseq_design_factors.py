"""`nf-core/chipseq/design_factors.py`: the condition comes from the design table.

Nothing but the pipeline-made `<group>_R<replicate>` suffix is read out of a
library id; the factor under test is the `GROUP_COL` column of the optional
`METADATA_FILE` table, else the design sheet group.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe

RECIPE = "nf-core/chipseq/design_factors.py"

_DESIGN = """sample_id,control_id,antibody,replicatesExist,multipleGroups
ABX_IP_WT_R1,INPUT_WT_R1,ABX,1,1
ABX_IP_WT_R2,INPUT_WT_R2,ABX,1,1
ABX_IP_KO_R1,INPUT_KO_R1,ABX,1,1
ABY_IP_KO_R1,INPUT_KO_R1,ABY,1,1
"""


def _run(tmp_path: Path, metadata: pl.DataFrame | None, params: dict[str, str]) -> pl.DataFrame:
    (tmp_path / "pipeline_info").mkdir(exist_ok=True)
    (tmp_path / "pipeline_info" / "design_controls.csv").write_text(_DESIGN)
    return execute_recipe(RECIPE, tmp_path, extra_sources={"metadata": metadata}, params=params)


def test_without_a_design_table_condition_is_the_design_group(tmp_path: Path) -> None:
    out = _run(tmp_path, None, {"group_col": "__no_group__"})
    rows = {r["sample_id"]: r for r in out.iter_rows(named=True)}
    assert out.height == 7  # 4 ChIPs + 3 distinct inputs
    assert rows["ABX_IP_WT_R2"]["condition"] == "ABX_IP_WT"
    assert rows["ABX_IP_WT_R2"]["replicate"] == "R2"
    # An input takes its ChIPs' group, and the antibodies of every ChIP it serves.
    assert rows["INPUT_WT_R1"]["condition"] == "ABX_IP_WT"
    assert rows["INPUT_WT_R1"]["antibody"] == "ABX"
    assert rows["INPUT_KO_R1"]["antibody"] == "ABX,ABY"
    assert rows["INPUT_KO_R1"]["is_control"] is True
    assert rows["INPUT_KO_R1"]["role"] == "input control"
    assert out.columns[:7] == [
        "sample_id",
        "role",
        "is_control",
        "antibody",
        "condition",
        "replicate",
        "control_id",
    ]


def test_group_col_of_the_design_table_is_the_condition(tmp_path: Path) -> None:
    metadata = pl.DataFrame(
        {
            "library": ["ABX_IP_WT_R1", "ABX_IP_WT_R2", "ABX_IP_KO_R1", "ABY_IP_KO_R1"],
            "batch": ["b1", "b2", "b1", "b2"],
            "genotype": ["wildtype", "wildtype", "knockout", "knockout"],
        }
    )
    out = _run(tmp_path, metadata, {"group_col": "genotype", "id_col": "library"})
    rows = {r["sample_id"]: r for r in out.iter_rows(named=True)}
    assert rows["ABX_IP_WT_R1"]["condition"] == "wildtype"
    assert rows["ABY_IP_KO_R1"]["condition"] == "knockout"
    # Other factors ride along; inputs missing from the table inherit their ChIPs' level.
    assert rows["ABX_IP_WT_R2"]["batch"] == "b2"
    assert rows["INPUT_WT_R2"]["condition"] == "wildtype"
    assert rows["INPUT_KO_R1"]["condition"] == "knockout"


def test_design_table_keyed_on_the_group_and_unset_group_col(tmp_path: Path) -> None:
    """One row per design group matches every replicate; no GROUP_COL takes the first factor."""
    metadata = pl.DataFrame(
        {"sample": ["ABX_IP_WT", "ABX_IP_KO", "ABY_IP_KO"], "treatment": ["ctrl", "ko", "ko"]}
    )
    out = _run(tmp_path, metadata, {"group_col": "{GROUP_COL}"})
    rows = {r["sample_id"]: r for r in out.iter_rows(named=True)}
    assert rows["ABX_IP_WT_R1"]["condition"] == "ctrl"
    assert rows["ABX_IP_WT_R2"]["condition"] == "ctrl"
    assert rows["INPUT_WT_R2"]["condition"] == "ctrl"
