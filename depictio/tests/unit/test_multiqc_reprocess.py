"""Tests for depictio/dev_scripts/multiqc_reprocess.py.

Everything but the last test is offline and works on tmp_path fixtures. The
end-to-end test runs the pinned MultiQC over the conformance stubs and is
skipped when `multiqc` is not importable.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from depictio.dev_scripts import multiqc_reprocess as mr

# The exact banner chipseq 1.2.0 (MultiQC 1.9, Nov 2020) wrote to multiqc.log.
LOG_1_9 = (
    "[2020-11-05 15:12:33,472] multiqc  [DEBUG  ]  No MultiQC config found: /root/.multiqc_config.yaml\n"
    "[2020-11-05 15:12:33,745] multiqc  [DEBUG  ]  Latest MultiQC version is v1.9\n"
    "[2020-11-05 15:12:33,745] multiqc  [INFO   ]  This is MultiQC v1.9\n"
    "[2020-11-05 15:12:33,745] multiqc  [DEBUG  ]  Command used: multiqc -f .\n"
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# --------------------------------------------------------------------------
# detect_source_multiqc_version
# --------------------------------------------------------------------------


def test_detect_version_from_data_json(tmp_path: Path) -> None:
    _write(
        tmp_path / "multiqc" / "multiqc_data" / "multiqc_data.json",
        json.dumps({"config_version": "1.9", "config_short_version": "1.9"}),
    )
    assert mr.detect_source_multiqc_version(tmp_path) == "1.9"


def test_detect_version_from_log_banner(tmp_path: Path) -> None:
    _write(tmp_path / "multiqc" / "multiqc_data" / "multiqc.log", LOG_1_9)
    assert mr.detect_source_multiqc_version(tmp_path) == "1.9"


def test_detect_version_from_software_versions_yml(tmp_path: Path) -> None:
    _write(
        tmp_path / "pipeline_info" / "software_versions.yml",
        "FASTQC:\n  fastqc: 0.12.1\nMULTIQC:\n  multiqc: 1.21\nWorkflow:\n  Nextflow: 24.04.2\n",
    )
    assert mr.detect_source_multiqc_version(tmp_path) == "1.21"


def test_detect_version_from_dsl1_software_versions_csv(tmp_path: Path) -> None:
    _write(
        tmp_path / "pipeline_info" / "software_versions.csv",
        "nf-core/chipseq\tv1.2.0\nFastQC\tv0.11.9\nMultiQC\tv1.9\n",
    )
    assert mr.detect_source_multiqc_version(tmp_path) == "1.9"


def test_detect_version_prefers_json_over_log_and_yml(tmp_path: Path) -> None:
    _write(tmp_path / "multiqc" / "multiqc_data" / "multiqc_data.json", '{"config_version": "1.9"}')
    _write(tmp_path / "multiqc" / "multiqc_data" / "multiqc.log", LOG_1_9.replace("v1.9", "v1.8"))
    _write(tmp_path / "pipeline_info" / "software_versions.yml", "MULTIQC:\n  multiqc: 1.7\n")
    assert mr.detect_source_multiqc_version(tmp_path) == "1.9"


def test_detect_version_returns_none_without_evidence(tmp_path: Path) -> None:
    _write(tmp_path / "fastqc" / "a_fastqc.txt", "x")
    assert mr.detect_source_multiqc_version(tmp_path) is None


# --------------------------------------------------------------------------
# plan_inputs / stage_inputs
# --------------------------------------------------------------------------


@pytest.fixture()
def results_dir(tmp_path: Path) -> Path:
    src = tmp_path / "results"
    _write(src / "fastqc" / "S1_fastqc.txt", "fastqc")
    _write(src / "pipeline_info" / "software_versions.yml", "MULTIQC:\n  multiqc: 1.9\n")
    _write(src / "bwa" / "S1.sorted.bam", "not really a bam")
    _write(src / "multiqc" / "multiqc_data" / "multiqc_data.json", '{"config_version": "1.9"}')
    _write(src / "multiqc" / "multiqc_report.html", "<html/>")
    _write(src / "multiqc_broadPeak" / "multiqc_data" / "multiqc.log", LOG_1_9)
    _write(src / "work" / "ab" / "cd" / ".command.log", "work")
    _write(src / ".nextflow.log", "nextflow")
    _write(src / ".nextflow" / "history", "history")
    return src


def test_plan_inputs_skips_old_reports_work_and_nextflow(results_dir: Path) -> None:
    planned = {p.as_posix() for p in mr.plan_inputs(results_dir)}
    assert planned == {
        "fastqc/S1_fastqc.txt",
        "pipeline_info/software_versions.yml",
        "bwa/S1.sorted.bam",
    }


def test_plan_inputs_honours_user_excludes(results_dir: Path) -> None:
    planned = {p.as_posix() for p in mr.plan_inputs(results_dir, exclude=("*.bam",))}
    assert planned == {"fastqc/S1_fastqc.txt", "pipeline_info/software_versions.yml"}
    planned = {p.as_posix() for p in mr.plan_inputs(results_dir, exclude=("pipeline_info/*",))}
    assert planned == {"fastqc/S1_fastqc.txt", "bwa/S1.sorted.bam"}


def test_stage_inputs_mirrors_plan_into_work_dir(results_dir: Path, tmp_path: Path) -> None:
    work_in = tmp_path / "work_in"
    _write(work_in / "stale.txt", "must be wiped")
    staged = mr.stage_inputs(results_dir, work_in, exclude=("*.bam",))
    assert sorted(p.relative_to(work_in).as_posix() for p in staged) == [
        "fastqc/S1_fastqc.txt",
        "pipeline_info/software_versions.yml",
    ]
    assert not (work_in / "stale.txt").exists()
    assert not (work_in / "multiqc").exists()
    assert not (work_in / "multiqc_broadPeak").exists()
    assert not (work_in / "work").exists()
    for path in staged:
        assert path.is_file()
        assert path.read_text() == (results_dir / path.relative_to(work_in)).read_text()


# --------------------------------------------------------------------------
# pin_creation_date / write_provenance
# --------------------------------------------------------------------------


def test_pin_creation_date_is_idempotent(tmp_path: Path) -> None:
    parquet = tmp_path / "multiqc.parquet"
    pl.DataFrame(
        {
            "anchor": ["fastqc", "fastqc", None],
            "creation_date": [datetime(2026, 9, 5, 12, 0, 0), None, datetime(2020, 11, 5)],
        }
    ).write_parquet(parquet)
    mr.pin_creation_date(parquet)
    first = parquet.read_bytes()
    pinned = pl.read_parquet(parquet)["creation_date"].to_list()
    assert pinned == [mr.FROZEN_CREATION_DATE, None, mr.FROZEN_CREATION_DATE]
    mr.pin_creation_date(parquet)
    assert parquet.read_bytes() == first


def test_pin_creation_date_leaves_other_frames_alone(tmp_path: Path) -> None:
    parquet = tmp_path / "other.parquet"
    pl.DataFrame({"a": [1, 2]}).write_parquet(parquet)
    before = parquet.read_bytes()
    mr.pin_creation_date(parquet)
    assert parquet.read_bytes() == before


def test_write_provenance_records_the_run(tmp_path: Path) -> None:
    target = mr.write_provenance(
        tmp_path / "multiqc" / "multiqc_data",
        source_version="1.9",
        reprocessed_with="1.35",
        modules={"samtools", "fastqc"},
        n_inputs=12,
        src="/data/results",
        timestamp=mr.FROZEN_CREATION_DATE,
    )
    assert target == tmp_path / "multiqc" / "multiqc_data" / "REPROCESSED.json"
    assert json.loads(target.read_text()) == {
        "source_version": "1.9",
        "reprocessed_with": "1.35",
        "timestamp": "2026-08-25T00:00:00",
        "modules": ["fastqc", "samtools"],
        "n_inputs": 12,
        "src": "/data/results",
    }


# --------------------------------------------------------------------------
# dry run / CLI
# --------------------------------------------------------------------------


def test_dry_run_prints_plan_without_writing(results_dir: Path, tmp_path: Path, capsys) -> None:
    dest = tmp_path / "dest"
    parquet = mr.reprocess(results_dir, dest, exclude=("*.bam",), dry_run=True)
    out = capsys.readouterr().out
    assert parquet == dest / "multiqc" / "multiqc_data" / "multiqc.parquet"
    assert "files to stage:    2" in out
    assert "source MultiQC:    1.9" in out
    assert str(parquet) in out
    assert str(dest / "multiqc" / "multiqc_data" / "REPROCESSED.json") in out
    assert not dest.exists()


def test_main_dry_run_exit_codes(results_dir: Path, tmp_path: Path, capsys) -> None:
    dest = tmp_path / "dest"
    assert mr.main(["--src", str(results_dir), "--dest", str(dest), "--dry-run"]) == 0
    assert "files to stage:    3" in capsys.readouterr().out
    assert mr.main(["--src", str(tmp_path / "missing"), "--dest", str(dest), "--dry-run"]) == 2
    assert "source is not a directory" in capsys.readouterr().err
    with pytest.raises(SystemExit) as excinfo:
        mr.main(["--dest", str(dest)])
    assert excinfo.value.code == 2


# --------------------------------------------------------------------------
# End to end over the conformance stubs
# --------------------------------------------------------------------------


def test_reprocess_stub_inputs_yields_fastqc(tmp_path: Path) -> None:
    multiqc = pytest.importorskip("multiqc")
    from depictio.projects.init.catalog_conformance.scripts import multiqc_stubs

    src = tmp_path / "results"
    for relative, content in multiqc_stubs.build_inputs(["fastqc", "samtools"]).items():
        _write(src / relative, content)
    # An old report next to the raw outputs: it must be detected, not re-parsed.
    _write(src / "multiqc" / "multiqc_data" / "multiqc_data.json", '{"config_version": "1.9"}')
    _write(src / "multiqc" / "multiqc_data" / "multiqc.log", LOG_1_9)

    dest = tmp_path / "dest"
    parquet = mr.reprocess(src, dest, timestamp=mr.FROZEN_CREATION_DATE)

    assert parquet == dest / "multiqc" / "multiqc_data" / "multiqc.parquet"
    assert parquet.exists()
    anchors = mr.parquet_modules(parquet)
    assert any(anchor.lower().startswith("fastqc") for anchor in anchors), anchors
    assert any(anchor.lower().startswith("samtools") for anchor in anchors), anchors
    assert set(
        pl.read_parquet(parquet, columns=["multiqc_version"])["multiqc_version"].drop_nulls()
    ) == {multiqc.__version__}

    provenance = json.loads((parquet.parent / "REPROCESSED.json").read_text())
    assert provenance["reprocessed_with"] == multiqc.__version__
    assert provenance["source_version"] == "1.9"
    assert provenance["timestamp"] == "2026-08-25T00:00:00"
    assert provenance["src"] == str(src.resolve())
    assert provenance["n_inputs"] == len(multiqc_stubs.build_inputs(["fastqc", "samtools"]))
    assert set(provenance["modules"]) == anchors

    before = parquet.read_bytes()
    mr.pin_creation_date(parquet)
    assert parquet.read_bytes() == before
    assert not mr.WORK_ROOT.exists()
