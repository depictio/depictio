"""Offline unit tests for scripts/nfcore_monitor.py (no network)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from packaging.version import Version

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "nfcore_monitor.py"


@pytest.fixture(scope="module")
def nfm() -> ModuleType:
    spec = importlib.util.spec_from_file_location("nfcore_monitor", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_discover_pipelines_finds_templated_pipelines(nfm: ModuleType) -> None:
    pipelines = nfm.discover_pipelines()
    # The repo ships at least these two; non-version dirs (recipes/) are ignored.
    assert "ampliseq" in pipelines
    assert "viralrecon" in pipelines
    assert Version("2.16.0") in pipelines["ampliseq"]


def test_local_latest_version_picks_highest(nfm: ModuleType) -> None:
    versions = [Version("2.14.0"), Version("2.16.0"), Version("2.9.0")]
    assert nfm.local_latest_version(versions) == Version("2.16.0")


def test_substitute_vars_resolves_group_col_and_drops_data_root(nfm: ModuleType) -> None:
    raw = "qiime2/ancombc/differentials/Category-{GROUP_COL}-level-2/lfc_slice.csv"
    assert (
        nfm.substitute_vars(raw, {"GROUP_COL": "habitat"})
        == "qiime2/ancombc/differentials/Category-habitat-level-2/lfc_slice.csv"
    )
    assert nfm.substitute_vars("{DATA_ROOT}/input/samplesheet.csv", {}) == "input/samplesheet.csv"


def test_substitute_vars_leaves_unknown_tokens_intact(nfm: ModuleType) -> None:
    # An unresolved token should remain so it surfaces as missing in the report.
    assert nfm.substitute_vars("a/{UNKNOWN}/b.csv", {}) == "a/{UNKNOWN}/b.csv"


def test_path_resolves_exact_glob_and_dir(nfm: ModuleType) -> None:
    keys = ["qiime2/barplot/level-2.csv", "multiqc/multiqc_data/multiqc.parquet"]
    key_set = set(keys)
    assert nfm._path_resolves("qiime2/barplot/level-2.csv", keys, key_set)  # exact
    assert nfm._path_resolves("qiime2/barplot/*.csv", keys, key_set)  # glob
    assert nfm._path_resolves("multiqc/multiqc_data", keys, key_set)  # dir prefix
    assert not nfm._path_resolves("qiime2/barplot/level-9.csv", keys, key_set)  # missing


def test_nearest_prefix_finds_longest_existing_dir(nfm: ModuleType) -> None:
    keys = ["qiime2/ancombc/Category-habitat/differentials/lfc_slice.csv"]
    missing = "qiime2/ancombc/differentials/Category-habitat-level-2/lfc_slice.csv"
    assert nfm._nearest_prefix(missing, keys) == "qiime2/ancombc/"
    assert nfm._nearest_prefix("nope/x.csv", keys) is None


def test_build_drift_report_counts_missing_and_resolved(nfm: ModuleType) -> None:
    keys = ["qiime2/barplot/level-2.csv"]
    source_paths = [
        ("taxonomy", "barplot", "qiime2/barplot/level-2.csv", False),  # resolves
        ("ancombc", "lfc", "qiime2/ancombc/gone.csv", False),  # missing
        ("opt", "x", "qiime2/whatever/optional.csv", True),  # optional -> not missing
    ]
    report, n_missing = nfm.build_drift_report(
        "ampliseq", "2.16.0", "2.17.0", "ampliseq/results-abc/", source_paths, keys
    )
    assert n_missing == 1
    assert "Missing" in report and "qiime2/ancombc/gone.csv" in report
    assert "Resolved (2)" in report  # the resolving one + the optional one
    assert "2.16.0 → 2.17.0" in report


def test_check_updates_flags_newer_release(
    nfm: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_latest(pipeline: str, token: str | None = None) -> str | None:
        return {"ampliseq": "9.9.9", "viralrecon": None}.get(pipeline, "0.0.1")

    monkeypatch.setattr(nfm, "fetch_latest_release", fake_latest)
    by_pipeline = {r["pipeline"]: r for r in nfm.check_updates()}
    assert by_pipeline["ampliseq"]["update_available"] is True
    # A failed (None) lookup must never report an update.
    assert by_pipeline["viralrecon"]["update_available"] is False


def test_resolve_results_prefix_with_explicit_hash(nfm: ModuleType) -> None:
    # No network: an explicit hash short-circuits S3 discovery.
    assert nfm.resolve_results_prefix("ampliseq", "deadbeef") == "ampliseq/results-deadbeef/"
    assert (
        nfm.resolve_results_prefix("ampliseq", "results-deadbeef") == "ampliseq/results-deadbeef/"
    )
