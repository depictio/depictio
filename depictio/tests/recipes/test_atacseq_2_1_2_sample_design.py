"""`nf-core/atacseq/sample_design.py` (2.1.2): one hub row per merged library.

The 2.x recipe reads `pipeline_info/samplesheet.valid.csv`, one row per sequencing
library named `<group>_REP<n>_T<n>`, and must give the dashboards the columns the
1.x recipe gives them (`replicate_label` included), plus the read type and the
control route. On that route the 2.1.2 validator writes the `control` header
twice, the first copy empty.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe, load_recipe

RECIPE = "nf-core/atacseq/sample_design.py"
VERSION = "2.1.2"

_SHEET = """sample,fastq_1,fastq_2,replicate,single_end,control
WT_REP1_T1,a_1.fq.gz,a_2.fq.gz,1,0,
WT_REP2_T1,b_1.fq.gz,b_2.fq.gz,2,0,
KO_REP1_T1,c_1.fq.gz,,1,1,
KO_REP1_T2,d_1.fq.gz,d_2.fq.gz,1,0,
"""

# The control route, header and empty first copy as the 2.1.2 validator writes them.
_SHEET_CONTROLS = """sample,fastq_1,fastq_2,replicate,single_end,control,control,control_replicate
IN_REP1_T1,i1_1.fq.gz,i1_2.fq.gz,1,0,,,
IN_REP2_T1,i2_1.fq.gz,i2_2.fq.gz,2,0,,,
TF_REP1_T1,t1_1.fq.gz,t1_2.fq.gz,1,0,,IN,1
TF_REP2_T1,t2_1.fq.gz,t2_2.fq.gz,2,0,,IN,2
"""


def _run(tmp_path: Path, sheet: str) -> dict[str, dict]:
    (tmp_path / "pipeline_info").mkdir(exist_ok=True)
    (tmp_path / "pipeline_info" / "samplesheet.valid.csv").write_text(sheet)
    out = execute_recipe(RECIPE, tmp_path, pipeline_version=VERSION)
    return {r["sample"]: r for r in out.iter_rows(named=True)}


def test_resolves_to_the_version_recipe_with_the_1x_columns_first() -> None:
    module = load_recipe(RECIPE, VERSION)
    assert Path(module.__file__).parent.parent.name == VERSION
    assert list(module.OUTPUT_SCHEMA)[:7] == [
        "sample",
        "merged_library",
        "group",
        "replicate",
        "replicate_label",
        "read_type",
        "role",
    ]


def test_libraries_collapse_into_samples(tmp_path: Path) -> None:
    rows = _run(tmp_path, _SHEET)
    assert sorted(rows) == ["KO_REP1", "WT_REP1", "WT_REP2"]

    wt = rows["WT_REP2"]
    assert wt["merged_library"] == "WT_REP2.mLb.clN"
    assert (wt["group"], wt["replicate"], wt["replicate_label"]) == ("WT", 2, "REP2")
    assert (wt["n_libraries"], wt["libraries"]) == (1, "WT_REP2_T1")
    assert wt["read_type"] == "paired-end"
    assert (wt["role"], wt["control"]) == ("sample", None)

    # Two technical replicates, one single-end and one paired-end, merge into one sample.
    ko = rows["KO_REP1"]
    assert (ko["n_libraries"], ko["libraries"]) == (2, "KO_REP1_T1,KO_REP1_T2")
    assert ko["read_type"] == "mixed"


def test_duplicated_control_header_resolves_the_control(tmp_path: Path) -> None:
    rows = _run(tmp_path, _SHEET_CONTROLS)
    assert rows["TF_REP1"]["control"] == "IN_REP1"
    assert rows["TF_REP2"]["control"] == "IN_REP2"
    assert rows["TF_REP1"]["role"] == "sample"
    # The input group is a control because another sample names it.
    assert rows["IN_REP1"]["role"] == "control"
    assert rows["IN_REP2"]["control"] is None
    assert rows["IN_REP2"]["replicate_label"] == "REP2"


def test_a_name_off_the_convention_is_its_own_group(tmp_path: Path) -> None:
    rows = _run(tmp_path, "sample,fastq_1,fastq_2,replicate,single_end\nODD_T1,x.fq.gz,,1,1\n")
    odd = rows["ODD"]
    assert odd["group"] == "ODD"
    assert odd["replicate"] is None
    assert odd["replicate_label"] is None
    assert odd["read_type"] == "single-end"


def test_output_matches_the_declared_schema(tmp_path: Path) -> None:
    (tmp_path / "pipeline_info").mkdir()
    (tmp_path / "pipeline_info" / "samplesheet.valid.csv").write_text(_SHEET_CONTROLS)
    out = execute_recipe(RECIPE, tmp_path, pipeline_version=VERSION)
    schema = load_recipe(RECIPE, VERSION).OUTPUT_SCHEMA
    assert out.columns == list(schema)
    assert out.schema["replicate"] == pl.Int64
    assert out.schema["n_libraries"] == pl.Int64
