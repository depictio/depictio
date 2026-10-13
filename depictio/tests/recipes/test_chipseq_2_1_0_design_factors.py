"""`nf-core/chipseq/design_factors.py` at 2.1.0: the hub from `samplesheet.valid.csv`.

The version override reads the library-level validated samplesheet instead of the
1.x `design_controls.csv` and returns the shared recipe's output schema. Nothing but
the pipeline-made `_T<n>` and `_REP<n>` suffixes is read out of an id; the factor
under test is the `GROUP_COL` column of the optional `METADATA_FILE` table, else the
sample group.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe, load_recipe

RECIPE = "nf-core/chipseq/design_factors.py"
VERSION = "2.1.0"

# Two technical runs of one ChIP library, two antibodies sharing one input, and an
# input listed by a ChIP but missing from the sheet.
_SHEET = """sample,single_end,fastq_1,fastq_2,replicate,antibody,control
INPUT_WT_REP1_T1,0,a.fq.gz,b.fq.gz,1,,
INPUT_KO_REP1_T1,0,a.fq.gz,b.fq.gz,1,,
ABX_WT_REP1_T1,0,a.fq.gz,b.fq.gz,1,ABX,INPUT_WT_REP1
ABX_WT_REP1_T2,0,a.fq.gz,b.fq.gz,1,ABX,INPUT_WT_REP1
ABX_WT_REP2_T1,0,a.fq.gz,b.fq.gz,2,ABX,INPUT_WT_REP2
ABX_KO_REP1_T1,0,a.fq.gz,b.fq.gz,1,ABX,INPUT_KO_REP1
ABY_KO_REP1_T1,0,a.fq.gz,b.fq.gz,1,ABY,INPUT_KO_REP1
"""

_COLUMNS = ["sample_id", "role", "is_control", "antibody", "condition", "replicate", "control_id"]


def _run(tmp_path: Path, metadata: pl.DataFrame | None, params: dict[str, str]) -> pl.DataFrame:
    (tmp_path / "pipeline_info").mkdir(exist_ok=True)
    (tmp_path / "pipeline_info" / "samplesheet.valid.csv").write_text(_SHEET)
    return execute_recipe(
        RECIPE,
        tmp_path,
        extra_sources={"metadata": metadata},
        pipeline_version=VERSION,
        params=params,
    )


def test_override_keeps_the_shared_output_schema() -> None:
    override = load_recipe(RECIPE, VERSION)
    shared = load_recipe(RECIPE)
    assert override.__file__ != shared.__file__
    assert override.OUTPUT_SCHEMA == shared.OUTPUT_SCHEMA


def test_without_a_design_table_condition_is_the_sample_group(tmp_path: Path) -> None:
    out = _run(tmp_path, None, {"group_col": "__no_group__"})
    rows = {r["sample_id"]: r for r in out.iter_rows(named=True)}
    # 4 ChIPs (two technical runs collapse) + 3 inputs (one recovered from control).
    assert out.height == 7
    assert out.columns[:7] == _COLUMNS
    assert rows["ABX_WT_REP1"]["condition"] == "ABX_WT"
    assert rows["ABX_WT_REP2"]["replicate"] == "REP2"
    assert rows["ABX_WT_REP1"]["control_id"] == "INPUT_WT_REP1"
    # An input takes its ChIPs' group, and the antibodies of every ChIP it serves.
    assert rows["INPUT_WT_REP1"]["condition"] == "ABX_WT"
    assert rows["INPUT_WT_REP1"]["antibody"] == "ABX"
    assert rows["INPUT_KO_REP1"]["antibody"] == "ABX,ABY"
    assert rows["INPUT_KO_REP1"]["condition"] == "INPUT_KO"  # its ChIPs disagree
    assert rows["INPUT_WT_REP2"]["role"] == "input control"
    assert rows["INPUT_WT_REP2"]["is_control"] is True
    assert rows["INPUT_WT_REP2"]["control_id"] is None
    assert out.filter(pl.col("is_control")).height == 3


def test_group_col_of_the_design_table_is_the_condition(tmp_path: Path) -> None:
    metadata = pl.DataFrame(
        {
            "library": ["ABX_WT_REP1", "ABX_WT_REP2", "ABX_KO_REP1", "ABY_KO_REP1"],
            "batch": ["b1", "b2", "b1", "b2"],
            "genotype": ["wildtype", "wildtype", "knockout", "knockout"],
        }
    )
    out = _run(tmp_path, metadata, {"group_col": "genotype", "id_col": "library"})
    rows = {r["sample_id"]: r for r in out.iter_rows(named=True)}
    assert rows["ABX_WT_REP1"]["condition"] == "wildtype"
    assert rows["ABY_KO_REP1"]["condition"] == "knockout"
    # Other factors ride along; inputs missing from the table inherit their ChIPs' level.
    assert rows["ABX_WT_REP2"]["batch"] == "b2"
    assert rows["INPUT_WT_REP2"]["condition"] == "wildtype"
    assert rows["INPUT_KO_REP1"]["condition"] == "knockout"


def test_design_table_keyed_on_the_group_and_unset_group_col(tmp_path: Path) -> None:
    """One row per sample group matches every replicate; no GROUP_COL takes the first factor."""
    metadata = pl.DataFrame(
        {"sample": ["ABX_WT", "ABX_KO", "ABY_KO"], "treatment": ["ctrl", "ko", "ko"]}
    )
    out = _run(tmp_path, metadata, {"group_col": "{GROUP_COL}"})
    rows = {r["sample_id"]: r for r in out.iter_rows(named=True)}
    assert rows["ABX_WT_REP1"]["condition"] == "ctrl"
    assert rows["ABX_WT_REP2"]["condition"] == "ctrl"
    assert rows["INPUT_WT_REP2"]["condition"] == "ctrl"


def test_a_sheet_without_any_chip_is_refused(tmp_path: Path) -> None:
    (tmp_path / "pipeline_info").mkdir()
    (tmp_path / "pipeline_info" / "samplesheet.valid.csv").write_text(
        "sample,replicate,antibody,control\nINPUT_REP1_T1,1,,\n"
    )
    with pytest.raises(ValueError, match="no ChIP row"):
        execute_recipe(RECIPE, tmp_path, pipeline_version=VERSION)
