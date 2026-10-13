"""`nf-core/nanoseq/samples.py`: the design comes from METADATA_FILE, not file names.

Only the pipeline-made `<group>_R<replicate>` sample name is decoded; the
condition is the `GROUP_COL` column of the optional design table and the
confounder columns (`protocol`, `source_replicate`, `run_id`) are that table's
columns of the same name.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe

RECIPE = "nf-core/nanoseq/samples.py"

# The FASTQ names carry prep / replicate / run tokens on purpose: none may leak.
_SHEET = """sample,barcode,input_file,fasta,gtf,is_transcripts,nanopolish_fast5
CL1_R1,,s3://x/CL1_cDNA_replicate1_run2.fastq.gz,GRCh38,,0,
CL1_R2,,s3://x/CL1_directRNA_replicate3_run1.fastq.gz,GRCh38,,0,/fast5
CL2_R1,,s3://x/CL2_cDNA_replicate1_run2.fastq.gz,GRCh38,,1,
"""


def _run(tmp_path: Path, metadata: pl.DataFrame | None, params: dict[str, str]) -> pl.DataFrame:
    (tmp_path / "pipeline_info").mkdir(exist_ok=True)
    (tmp_path / "pipeline_info" / "samplesheet.valid.csv").write_text(_SHEET)
    return execute_recipe(RECIPE, tmp_path, extra_sources={"metadata": metadata}, params=params)


def test_without_a_design_table_nothing_is_parsed_from_file_names(tmp_path: Path) -> None:
    out = _run(tmp_path, None, {"group_col": "__no_group__"})
    assert out["sample_id"].to_list() == ["CL1_R1", "CL1_R2", "CL2_R1"]
    assert out["condition"].to_list() == ["CL1", "CL1", "CL2"]
    assert out["replicate"].to_list() == [1, 2, 1]
    for column in ("protocol", "source_replicate", "run_id"):
        assert out[column].unique().to_list() == ["unknown"]
    assert out["has_fast5"].to_list() == [False, True, False]
    assert out["is_transcripts"].to_list() == [False, False, True]


def test_design_table_feeds_condition_confounders_and_extras(tmp_path: Path) -> None:
    metadata = pl.DataFrame(
        {
            "id": ["CL1_R1", "CL1_R2", "CL2_R1"],
            "batch": ["b1", "b2", "b1"],
            "cell_type": ["epithelial", "epithelial", "myeloid"],
            "protocol": ["cdna", "directrna", "cdna"],
            "run_id": ["fc1", "fc2", "fc1"],
        }
    )
    out = _run(tmp_path, metadata, {"group_col": "cell_type", "id_col": "id"})
    rows = {r["sample_id"]: r for r in out.iter_rows(named=True)}
    assert rows["CL2_R1"]["condition"] == "myeloid"
    assert rows["CL1_R2"]["protocol"] == "directrna"
    assert rows["CL1_R2"]["run_id"] == "fc2"
    assert rows["CL1_R2"]["source_replicate"] == "unknown"  # not in the table
    assert rows["CL1_R2"]["batch"] == "b2"  # extra factor rides along


def test_group_keyed_table_and_unresolved_group_col(tmp_path: Path) -> None:
    """A per-group table matches every replicate; no GROUP_COL takes the first factor."""
    metadata = pl.DataFrame({"sample": ["CL1", "CL2"], "tissue": ["lung", "blood"]})
    out = _run(tmp_path, metadata, {"group_col": "{GROUP_COL}", "id_col": "{METADATA_ID_COL}"})
    assert out["condition"].to_list() == ["lung", "lung", "blood"]
