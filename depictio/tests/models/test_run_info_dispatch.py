"""Tests for the pluggable run-info registry/dispatch."""

from __future__ import annotations

from pathlib import Path

from depictio.models.models.run_info import (
    WorkflowRunInfo,
    read_run_info,
    register_run_info_reader,
    registered_readers,
)


def test_nextflow_and_snakemake_connectors_registered():
    names = {r.name for r in registered_readers()}
    assert {"nextflow", "snakemake"} <= names


def test_dispatch_detects_nextflow(tmp_path):
    pinfo = tmp_path / "pipeline_info"
    pinfo.mkdir()
    (pinfo / "nf_core_ampliseq_software_mqc_versions.yml").write_text(
        "Workflow:\n  nf-core/ampliseq: 2.16.0\n  Nextflow: 24.04.4\n"
    )
    info = read_run_info(tmp_path)
    assert info is not None
    assert info.engine == "nextflow"
    assert info.pipeline_name == "nf-core/ampliseq"


def test_dispatch_detects_snakemake(tmp_path):
    (tmp_path / "Snakefile").write_text("rule all:\n    input: []\n")
    (tmp_path / "config.yaml").write_text("pipeline: smk-wf\nversion: 0.1.0\n")
    info = read_run_info(tmp_path)
    assert info is not None
    assert info.engine == "snakemake"
    assert info.pipeline_name == "smk-wf"


def test_nextflow_wins_over_snakemake_when_both_present(tmp_path):
    # A dir carrying both footprints resolves to nf-core (higher priority).
    pinfo = tmp_path / "pipeline_info"
    pinfo.mkdir()
    (pinfo / "nf_core_x_software_mqc_versions.yml").write_text(
        "Workflow:\n  nf-core/x: 1.0.0\n  Nextflow: 24.0.0\n"
    )
    (tmp_path / "Snakefile").write_text("rule all:\n    input: []\n")
    info = read_run_info(tmp_path)
    assert info is not None
    assert info.engine == "nextflow"


def test_dispatch_returns_none_for_unknown(tmp_path):
    (tmp_path / "data.txt").write_text("nothing recognisable")
    assert read_run_info(tmp_path) is None


def test_priority_ordering_and_idempotent_registration():
    before = len(registered_readers())

    class _Dummy:
        name = "nextflow"  # same name → replaces, not duplicates
        priority = 1

        def read(self, run_dir: Path) -> WorkflowRunInfo | None:
            return None

    register_run_info_reader(_Dummy())
    assert len(registered_readers()) == before
    # restore the real nextflow connector for other tests in the session
    import importlib

    import depictio.models.models.nextflow as nf

    importlib.reload(nf)
