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
    report, n_problems = nfm.build_drift_report(
        "ampliseq", "2.16.0", "2.17.0", "ampliseq/results-abc/", source_paths, keys
    )
    assert n_problems == 1
    assert "qiime2/ancombc/gone.csv" in report
    assert "1 resolved, 1 missing, 1 optional-absent" in report
    # optional-absent stays visible (coverage) but is never counted as drift
    assert "qiime2/whatever/optional.csv — optional route, not exercised by megatest" in report
    assert "2.16.0 → 2.17.0" in report
    assert "action needed" in report  # overall status reflects the missing path


def test_build_drift_report_includes_recipe_and_catalog_layers(nfm: ModuleType) -> None:
    keys = ["qiime2/barplot/level-2.csv"]
    source_paths = [("taxonomy", "barplot", "qiime2/barplot/level-2.csv", False)]
    recipe_results = [
        nfm.RecipeCheck("taxonomy", "qiime2/x.py", "PASS", "10 rows × 3 cols"),
        nfm.RecipeCheck("ancombc", "qiime2/y.py", "FAIL", "missing output column 'lfc'"),
        nfm.RecipeCheck("sunburst", "qiime2/z.py", "SKIPPED", "consumes upstream DCs (dc_ref)"),
    ]
    report, n_problems = nfm.build_drift_report(
        "ampliseq",
        "2.16.0",
        "2.17.0",
        "ampliseq/results-abc/",
        source_paths,
        keys,
        recipe_results,
        ("PASS", "OK: 12 catalog tool(s) valid"),
    )
    # one recipe FAIL drives the problem count even though all paths resolve
    assert n_problems == 1
    assert "Recipe execution — 1 pass, 1 fail, 1 skipped" in report
    assert "missing output column 'lfc'" in report
    assert "Catalog validate — ✅ PASS" in report


def test_check_updates_flags_newer_release(
    nfm: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without the nf-co.re index (offline) the GitHub releases API is the source.
    monkeypatch.setattr(nfm, "load_index_or_none", lambda: None)

    def fake_latest(pipeline: str, token: str | None = None) -> str | None:
        return {"ampliseq": "9.9.9", "viralrecon": None}.get(pipeline, "0.0.1")

    monkeypatch.setattr(nfm, "fetch_latest_release", fake_latest)
    by_pipeline = {r["pipeline"]: r for r in nfm.check_updates()}
    assert by_pipeline["ampliseq"]["update_available"] is True
    # A failed (None) lookup must never report an update.
    assert by_pipeline["viralrecon"]["update_available"] is False


def test_check_updates_prefers_index_over_github(
    nfm: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = {
        "remote_workflows": [
            {
                "name": "ampliseq",
                "releases": [
                    {
                        "tag_name": "9.9.9",
                        "tag_sha": "a" * 40,
                        "published_at": "2030-01-01T00:00:00Z",
                    },
                    {
                        "tag_name": "2.18.0",
                        "tag_sha": "b" * 40,
                        "published_at": "2026-06-17T00:00:00Z",
                    },
                    {
                        "tag_name": "dev",
                        "tag_sha": "c" * 40,
                        "published_at": "2030-02-01T00:00:00Z",
                    },
                ],
            }
        ]
    }
    asked_github: list[str] = []

    def fake_latest(pipeline: str, token: str | None = None) -> str | None:
        asked_github.append(pipeline)
        return "0.0.1"

    monkeypatch.setattr(nfm, "fetch_latest_release", fake_latest)
    by_pipeline = {r["pipeline"]: r for r in nfm.check_updates(index=index)}
    # The index answers for ampliseq (9.9.9, never the dev pseudo-release) ...
    assert by_pipeline["ampliseq"]["remote"] == "9.9.9"
    assert by_pipeline["ampliseq"]["update_available"] is True
    assert "ampliseq" not in asked_github
    # ... and GitHub is only asked for pipelines the index does not know.
    assert "viralrecon" in asked_github
    assert by_pipeline["viralrecon"]["remote"] == "0.0.1"
    assert nfm.latest_release_tag("ampliseq", index) == "9.9.9"


def test_resolve_results_prefix_delegates_to_resolve_run(
    nfm: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    calls: list[dict] = []

    def fake_resolve_run(pipeline, version=None, run_root="", index=None, region=None, **kw):
        calls.append(
            {"pipeline": pipeline, "version": version, "run_root": run_root, "index": index}
        )
        return SimpleNamespace(root_prefix=f"{pipeline}/results-{'a' * 40}/{run_root}")

    monkeypatch.setattr(nfm, "resolve_run", fake_resolve_run)
    index = {"remote_workflows": []}
    prefix = nfm.resolve_results_prefix(
        "rnaseq", version="3.26.0", index=index, run_root="aligner_star_salmon"
    )
    assert prefix == f"rnaseq/results-{'a' * 40}/aligner_star_salmon/"
    assert calls == [
        {
            "pipeline": "rnaseq",
            "version": "3.26.0",
            "run_root": "aligner_star_salmon/",
            "index": index,
        }
    ]
    # An explicit hash short-circuits the lookup (no resolve_run call) and keeps the run_root.
    assert (
        nfm.resolve_results_prefix("rnaseq", "deadbeef", run_root="aligner_star_salmon/")
        == "rnaseq/results-deadbeef/aligner_star_salmon/"
    )
    assert len(calls) == 1


def test_build_drift_report_shows_run_root_and_fallback_note(nfm: ModuleType) -> None:
    keys = ["multiqc/star_salmon/multiqc_report_data/multiqc.parquet"]
    source_paths = [("multiqc", "parquet", keys[0], False)]
    report, n_problems = nfm.build_drift_report(
        "rnaseq",
        "3.26.0",
        "3.27.0",
        "rnaseq/results-abc/",
        source_paths,
        keys,
        run_root="aligner_star_salmon/",
        note="nf-core/rnaseq 3.27.0: megatest run is empty. Falling back to `rnaseq/results-abc/`.",
    )
    assert n_problems == 0
    header = report.splitlines()[2]
    assert "Megatest: `s3://nf-core-awsmegatests/rnaseq/results-abc/`" in header
    assert "run_root: `aligner_star_salmon/`" in header
    assert "> ⚠️ nf-core/rnaseq 3.27.0: megatest run is empty" in report
    # Without a run_root or note the header stays as before.
    plain, _ = nfm.build_drift_report(
        "rnaseq", "3.26.0", "3.27.0", "rnaseq/results-abc/", source_paths, keys
    )
    assert "run_root" not in plain and "⚠️" not in plain


def test_validate_one_recipe_skips_dc_ref_recipes(nfm: ModuleType, tmp_path: Path) -> None:
    # A recipe consuming an upstream DC (dc_ref) reads no megatest file, so it is
    # skipped before any download/execution — no network needed.
    pytest.importorskip("depictio.recipes")  # needs the editable install (present in CI)
    from types import SimpleNamespace

    module = SimpleNamespace(SOURCES=[SimpleNamespace(dc_ref="variants_long", path=None)])
    result = nfm._validate_one_recipe(
        "upset",
        "nf-core/viralrecon/upset.py",
        module,
        {},
        {},
        "viralrecon/results-x/",
        {},
        tmp_path,
        "3.0.0",
        50.0,
    )
    assert result.status == "SKIPPED"
    assert "dc_ref" in result.detail


def test_validate_one_recipe_skips_optional_dc_with_absent_source(
    nfm: ModuleType, tmp_path: Path
) -> None:
    # An `optional: true` DC (route-gated, e.g. ampliseq multiregion/SIDLE) whose
    # source file the default-profile megatest never produces must be SKIPPED,
    # not FAILed — absence is pruning, not drift.
    pytest.importorskip("depictio.recipes")
    from types import SimpleNamespace

    module = SimpleNamespace(
        SOURCES=[
            SimpleNamespace(
                dc_ref=None,
                glob_pattern=None,
                ref="reconstructed",
                path="sidle/reconstructed/reconstructed_merged.tsv",
                optional=False,
            )
        ]
    )
    result = nfm._validate_one_recipe(
        "sidle_reconstructed",
        "nf-core/ampliseq/sidle_reconstructed.py",
        module,
        {},
        {},
        "ampliseq/results-x/",
        {},  # megatest has no sidle/ files at all
        tmp_path,
        "2.16.0",
        50.0,
        dc_optional=True,
    )
    assert result.status == "SKIPPED"
    assert "optional route not exercised" in result.detail
    # Without the DC-level flag the same absence is a genuine failure.
    result = nfm._validate_one_recipe(
        "sidle_reconstructed",
        "nf-core/ampliseq/sidle_reconstructed.py",
        module,
        {},
        {},
        "ampliseq/results-x/",
        {},
        tmp_path,
        "2.16.0",
        50.0,
        dc_optional=False,
    )
    assert result.status == "FAIL"
    assert "source file absent" in result.detail


def test_resolve_results_prefix_with_explicit_hash(nfm: ModuleType) -> None:
    # No network: an explicit hash short-circuits S3 discovery.
    assert nfm.resolve_results_prefix("ampliseq", "deadbeef") == "ampliseq/results-deadbeef/"
    assert (
        nfm.resolve_results_prefix("ampliseq", "results-deadbeef") == "ampliseq/results-deadbeef/"
    )
