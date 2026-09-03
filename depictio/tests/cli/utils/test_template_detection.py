"""Tests for auto-detecting a template from a Nextflow run directory."""

from __future__ import annotations

import json
from pathlib import Path

from depictio.cli.cli.utils.templates import (
    _list_pipeline_versions,
    _version_key,
    detect_template_from_run_dir,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def _write_versions(run_dir: Path, pipeline: str, version: str) -> None:
    pinfo = run_dir / "pipeline_info"
    pinfo.mkdir(parents=True, exist_ok=True)
    (pinfo / f"nf_core_{pipeline.split('/')[-1]}_software_mqc_versions.yml").write_text(
        f"FASTQC:\n  fastqc: 0.12.1\nWorkflow:\n  {pipeline}: {version}\n  Nextflow: 24.04.4\n"
    )
    (pinfo / "params_x.json").write_text(json.dumps({"input": "samplesheet.csv"}))


def test_version_key_orders_numerically():
    assert _version_key("2.16.0") > _version_key("2.14.0")
    assert _version_key("2.9.0") < _version_key("2.16.0")


def test_lists_ampliseq_versions():
    versions = _list_pipeline_versions("nf-core/ampliseq")
    # The repo ships at least 2.14.0 and 2.16.0 template/project folders.
    assert "2.16.0" in versions


def test_exact_match_detected(tmp_path):
    _write_versions(tmp_path, "nf-core/ampliseq", "2.16.0")
    template_id, info = detect_template_from_run_dir(tmp_path)
    assert template_id == "nf-core/ampliseq/2.16.0"
    assert info is not None
    assert info.params["input"] == "samplesheet.csv"


def test_closest_version_fallback(tmp_path):
    # A version with no exact template falls back to the closest available one.
    _write_versions(tmp_path, "nf-core/ampliseq", "2.15.0")
    template_id, info = detect_template_from_run_dir(tmp_path)
    assert template_id is not None
    assert template_id.startswith("nf-core/ampliseq/")
    assert info is not None


def test_unknown_pipeline_returns_none(tmp_path):
    _write_versions(tmp_path, "nf-core/doesnotexist", "1.0.0")
    template_id, info = detect_template_from_run_dir(tmp_path)
    assert template_id is None
    assert info is not None  # provenance still read


def test_no_pipeline_info_returns_none(tmp_path):
    template_id, info = detect_template_from_run_dir(tmp_path)
    assert template_id is None
    assert info is None
