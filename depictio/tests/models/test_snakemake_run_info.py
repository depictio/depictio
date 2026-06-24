"""Tests for the Snakemake run-info connector."""

from __future__ import annotations

from pathlib import Path

from depictio.models.models.snakemake import read_snakemake_run_info


def _write_snakemake(run_dir: Path, *, with_config: bool = True) -> None:
    (run_dir / "Snakefile").write_text("rule all:\n    input: 'results/out.tsv'\n")
    (run_dir / ".snakemake").mkdir()
    conda = run_dir / ".snakemake" / "conda"
    conda.mkdir()
    (conda / "abc123.yaml").write_text(
        "channels:\n  - bioconda\ndependencies:\n  - mosdepth=0.3.3\n  - samtools=1.17\n"
    )
    if with_config:
        (run_dir / "config.yaml").write_text(
            "pipeline: my-snake-wf\nversion: 1.2.0\nsamples: s.tsv\n"
        )


def test_reads_snakemake_run(tmp_path):
    _write_snakemake(tmp_path)
    info = read_snakemake_run_info(tmp_path)
    assert info is not None
    assert info.engine == "snakemake"
    assert info.pipeline_name == "my-snake-wf"
    assert info.pipeline_version == "1.2.0"
    assert info.params["samples"] == "s.tsv"
    assert {"mosdepth", "samtools"} <= info.tools_executed


def test_pipeline_name_falls_back_to_dir(tmp_path):
    run = tmp_path / "my_run"
    run.mkdir()
    _write_snakemake(run, with_config=False)
    info = read_snakemake_run_info(run)
    assert info is not None
    assert info.pipeline_name == "my_run"
    assert info.pipeline_version is None


def test_recognised_by_snakefile_only(tmp_path):
    (tmp_path / "workflow").mkdir()
    (tmp_path / "workflow" / "Snakefile").write_text("rule all:\n    input: []\n")
    info = read_snakemake_run_info(tmp_path)
    assert info is not None
    assert info.engine == "snakemake"


def test_non_snakemake_dir_returns_none(tmp_path):
    (tmp_path / "random.txt").write_text("hello")
    assert read_snakemake_run_info(tmp_path) is None


def test_nonexistent_dir_returns_none():
    assert read_snakemake_run_info("/no/such/path/xyz") is None
