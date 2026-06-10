"""Tests for the Nextflow run-info reader (pipeline_info/ provenance)."""

from __future__ import annotations

import json
from pathlib import Path

from depictio.models.models.nextflow import NextflowRunInfo, read_nextflow_run_info

REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_pipeline_info(run_dir: Path) -> None:
    """Create a realistic nf-core pipeline_info/ under run_dir."""
    pinfo = run_dir / "pipeline_info"
    pinfo.mkdir(parents=True)
    (pinfo / "nf_core_ampliseq_software_mqc_versions.yml").write_text(
        "FASTQC:\n"
        "  fastqc: 0.12.1\n"
        "QIIME2:\n"
        "  qiime2: 2024.5.0\n"
        "Workflow:\n"
        "  nf-core/ampliseq: 2.16.0\n"
        "  Nextflow: 24.04.4\n"
    )
    (pinfo / "params_2026-06-09_10-00-00.json").write_text(
        json.dumps({"input": "samplesheet.csv", "metadata": "meta.tsv", "outdir": "results"})
    )
    (pinfo / "execution_report_2026-06-09_10-00-00.html").write_text("<html></html>")
    (pinfo / "execution_trace_2026-06-09_10-00-00.txt").write_text("task_id\thash\n")


def test_reads_full_pipeline_info(tmp_path):
    _write_pipeline_info(tmp_path)
    info = read_nextflow_run_info(tmp_path)
    assert info is not None
    assert info.pipeline_name == "nf-core/ampliseq"
    assert info.pipeline_version == "2.16.0"
    assert info.nextflow_version == "24.04.4"
    assert info.short_name == "ampliseq"
    assert info.tools_executed == {"fastqc", "qiime2"}
    assert info.params["input"] == "samplesheet.csv"
    assert info.params["metadata"] == "meta.tsv"
    assert info.execution_report_path is not None
    assert info.execution_trace_path is not None


def test_template_ids_offers_both_version_spellings():
    info = NextflowRunInfo(pipeline_name="nf-core/rnaseq", pipeline_version="v3.16.0")
    assert info.template_ids() == ["nf-core/rnaseq/3.16.0", "nf-core/rnaseq/v3.16.0"]
    plain = NextflowRunInfo(pipeline_name="nf-core/ampliseq", pipeline_version="2.16.0")
    assert plain.template_ids() == ["nf-core/ampliseq/2.16.0"]


def test_strips_leading_v_from_version(tmp_path):
    pinfo = tmp_path / "pipeline_info"
    pinfo.mkdir()
    (pinfo / "nf_core_rnaseq_software_mqc_versions.yml").write_text(
        "Workflow:\n  nf-core/rnaseq: v3.16.0\n  Nextflow: 24.10.0\n"
    )
    info = read_nextflow_run_info(tmp_path)
    assert info is not None
    assert info.pipeline_version == "3.16.0"


def test_missing_pipeline_info_degrades_gracefully(tmp_path):
    # An empty run dir (no pipeline_info/) must not raise; returns None.
    assert read_nextflow_run_info(tmp_path) is None


def test_nonexistent_dir_returns_none():
    assert read_nextflow_run_info("/no/such/path/xyz") is None


def test_real_viralrecon_run_has_no_pipeline_info():
    # The curated reference run dirs are subsets without pipeline_info/ — the
    # reader must tolerate that (returns None or partial without exception).
    run = REPO_ROOT / "depictio" / "projects" / "nf-core" / "viralrecon" / "3.0.0" / "run_1"
    if not run.is_dir():
        import pytest

        pytest.skip("viralrecon run_1 fixture not present")
    info = read_nextflow_run_info(run)
    # No pipeline_info → no pipeline identity (None or partial without a name).
    assert info is None or info.pipeline_name is None


def test_software_versions_fallback_for_tools(tmp_path):
    # Legacy software_versions.yml (no Workflow section) still yields tools.
    (tmp_path / "software_versions.yml").write_text("FASTQC:\n  fastqc: 0.12.1\n")
    info = read_nextflow_run_info(tmp_path)
    assert info is not None
    assert info.tools_executed == {"fastqc"}
    assert info.pipeline_name is None
