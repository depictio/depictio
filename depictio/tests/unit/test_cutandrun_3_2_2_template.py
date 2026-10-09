"""nf-core/cutandrun 3.2.2: which files the directory-aware scans bind.

The template has to pick ONE MultiQC report per run (the pipeline's own one by
default, the re-generated one with MULTIQC_REPROCESSED) and has to skip the
byte-identical copies of the SEACR beds the pipeline writes into igv/. Both
rules live in scan patterns, so they are checked here with the CLI's own file
matcher on a run tree that holds every competing file.
"""

from pathlib import Path

import pytest

from depictio.cli.cli.utils.scan_utils import file_matches_data_collection
from depictio.cli.cli.utils.templates import resolve_template

TEMPLATE_ID = "nf-core/cutandrun/3.2.2"

PIPELINE_REPORT = "04_reporting/multiqc/multiqc_data/multiqc.parquet"
REPROCESSED_REPORT = "multiqc/multiqc_data/multiqc.parquet"
SEACR_BEDS = [
    "03_peak_calling/04_called_peaks/seacr/target_R1.seacr.peaks.stringent.bed",
    "03_peak_calling/04_called_peaks/seacr/target_R2.seacr.peaks.stringent.bed",
]
IGV_COPIES = [
    "04_reporting/igv/target_R1.seacr.peaks.stringent.bed",
    "04_reporting/igv/target_R2.seacr.peaks.stringent.bed",
]
MARKDUP_FLAGSTAT = "02_alignment/bowtie2/target/markdup/target_R1.flagstat"
LINEAR_DEDUP_FLAGSTAT = "02_alignment/bowtie2/target/linear_dedup/target_R1.flagstat"


@pytest.fixture
def run_tree(tmp_path: Path) -> Path:
    for rel in [
        PIPELINE_REPORT,
        REPROCESSED_REPORT,
        *SEACR_BEDS,
        *IGV_COPIES,
        MARKDUP_FLAGSTAT,
        LINEAR_DEDUP_FLAGSTAT,
    ]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n")
    return tmp_path


def _bound(run_tree: Path, tag: str, extra_vars: dict[str, str] | None = None) -> list[str]:
    config, *_ = resolve_template(TEMPLATE_ID, str(run_tree), extra_vars=extra_vars)
    dcs = {
        dc["data_collection_tag"]: dc for wf in config["workflows"] for dc in wf["data_collections"]
    }
    pattern = dcs[tag]["config"]["scan"]["scan_parameters"]["regex_config"]["pattern"]
    return sorted(
        str(path.relative_to(run_tree))
        for path in run_tree.rglob("*")
        if path.is_file() and file_matches_data_collection(str(path), str(run_tree), pattern)
    )


def test_default_binding_reads_the_pipeline_report_only(run_tree: Path) -> None:
    assert _bound(run_tree, "multiqc_data") == [PIPELINE_REPORT]


def test_reprocessed_binding_reads_the_regenerated_report_only(run_tree: Path) -> None:
    bound = _bound(run_tree, "multiqc_data", {"MULTIQC_REPROCESSED": "true"})
    assert bound == [REPROCESSED_REPORT]


@pytest.mark.parametrize("extra_vars", [None, {"MULTIQC_REPROCESSED": "true"}])
def test_seacr_scan_skips_the_igv_copies(run_tree: Path, extra_vars: dict[str, str] | None) -> None:
    assert _bound(run_tree, "seacr_peaks_raw", extra_vars) == SEACR_BEDS


def test_flagstat_scan_skips_the_linear_dedup_twin(run_tree: Path) -> None:
    assert _bound(run_tree, "samtools_flagstat_raw") == [MARKDUP_FLAGSTAT]
