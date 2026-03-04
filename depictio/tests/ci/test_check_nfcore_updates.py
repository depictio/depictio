"""Tests for the nf-core pipeline update checker."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from depictio.ci.check_nfcore_updates import (
    _parse_version,
    check_dashboard_multiqc_refs,
    diff_tools,
    discover_tracked_pipelines,
    extract_multiqc_modules_from_project,
    extract_tools_from_modules_json,
    generate_report,
)

# -- Fixtures ----------------------------------------------------------------


@pytest.fixture()
def sample_project_config() -> dict:
    """Minimal ampliseq-like project config."""
    return {
        "workflows": [
            {
                "name": "ampliseq",
                "version": "2.14.0",
                "data_collections": [
                    {
                        "data_collection_tag": "multiqc_data",
                        "config": {
                            "type": "MultiQC",
                            "dc_specific_properties": {
                                "modules": ["cutadapt", "fastqc"],
                            },
                        },
                    },
                ],
            }
        ],
    }


@pytest.fixture()
def sample_modules_json() -> dict:
    """Minimal nf-core modules.json."""
    return {
        "name": "nf-core/ampliseq",
        "repos": {
            "https://github.com/nf-core/modules.git": {
                "modules": {
                    "nf-core": {
                        "cutadapt": {"branch": "master"},
                        "fastqc": {"branch": "master"},
                        "kraken2/kraken2": {"branch": "master"},
                    },
                },
            },
        },
    }


@pytest.fixture()
def dashboard_yaml(tmp_path: Path) -> Path:
    """Create a dashboard YAML with MultiQC components."""
    dashboard = {
        "main_dashboard": {
            "components": [
                {
                    "component_type": "multiqc",
                    "selected_module": "cutadapt",
                    "tag": "mqc-cutadapt",
                },
                {
                    "component_type": "multiqc",
                    "selected_module": "fastqc",
                    "tag": "mqc-fastqc",
                },
                {
                    "component_type": "card",
                    "column_name": "sample",
                    "tag": "card-sample",
                },
            ],
        },
        "tabs": [],
    }
    path = tmp_path / "dashboard.yaml"
    path.write_text(yaml.dump(dashboard))
    return path


# -- Tests: version parsing --------------------------------------------------


class TestParseVersion:
    def test_standard(self) -> None:
        assert _parse_version("2.14.0") == (2, 14, 0)

    def test_comparison(self) -> None:
        assert _parse_version("2.15.0") > _parse_version("2.14.0")
        assert _parse_version("3.0.0") > _parse_version("2.99.99")


# -- Tests: discovery ---------------------------------------------------------


class TestDiscoverTrackedPipelines:
    def test_discovers_pipeline(self, tmp_path: Path) -> None:
        d = tmp_path / "ampliseq" / "2.14.0"
        d.mkdir(parents=True)
        (d / "project.yaml").write_text(yaml.dump({"workflows": []}))

        result = discover_tracked_pipelines(tmp_path)
        assert len(result) == 1
        assert result[0]["name"] == "ampliseq"
        assert result[0]["version"] == "2.14.0"

    def test_picks_latest_version(self, tmp_path: Path) -> None:
        for v in ["2.13.0", "2.14.0", "2.15.0"]:
            d = tmp_path / "ampliseq" / v
            d.mkdir(parents=True)
            (d / "project.yaml").write_text(yaml.dump({"workflows": []}))

        result = discover_tracked_pipelines(tmp_path)
        assert result[0]["version"] == "2.15.0"

    def test_missing_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            discover_tracked_pipelines(tmp_path / "nonexistent")


# -- Tests: modules.json parsing ----------------------------------------------


class TestExtractToolsFromModulesJson:
    def test_extracts_tools(self, sample_modules_json: dict) -> None:
        tools = extract_tools_from_modules_json(sample_modules_json)
        assert "cutadapt" in tools
        assert "fastqc" in tools
        assert "kraken2" in tools  # normalised from "kraken2/kraken2"

    def test_empty_modules(self) -> None:
        assert extract_tools_from_modules_json({"repos": {}}) == set()


# -- Tests: diffing -----------------------------------------------------------


class TestDiffTools:
    def test_no_changes(self) -> None:
        result = diff_tools({"a", "b"}, {"a", "b"})
        assert result["added"] == []
        assert result["removed"] == []
        assert sorted(result["unchanged"]) == ["a", "b"]

    def test_added_and_removed(self) -> None:
        result = diff_tools({"a", "b"}, {"b", "c"})
        assert result["added"] == ["c"]
        assert result["removed"] == ["a"]
        assert result["unchanged"] == ["b"]


# -- Tests: MultiQC extraction -----------------------------------------------


class TestExtractMultiqcModules:
    def test_extracts(self, sample_project_config: dict) -> None:
        modules = extract_multiqc_modules_from_project(sample_project_config)
        assert modules == {"cutadapt", "fastqc"}

    def test_empty_config(self) -> None:
        assert extract_multiqc_modules_from_project({"workflows": []}) == set()


# -- Tests: dashboard validation ----------------------------------------------


class TestCheckDashboardMultiqcRefs:
    def test_valid_refs(self, dashboard_yaml: Path) -> None:
        warnings = check_dashboard_multiqc_refs(dashboard_yaml, {"cutadapt", "fastqc"})
        assert warnings == []

    def test_missing_module(self, dashboard_yaml: Path) -> None:
        # Only fastqc available – cutadapt should trigger a warning
        warnings = check_dashboard_multiqc_refs(dashboard_yaml, {"fastqc"})
        assert len(warnings) == 1
        assert "cutadapt" in warnings[0]

    def test_missing_file(self, tmp_path: Path) -> None:
        warnings = check_dashboard_multiqc_refs(tmp_path / "nope.yaml", {"fastqc"})
        assert len(warnings) == 1
        assert "not found" in warnings[0]


# -- Tests: report generation -------------------------------------------------


class TestGenerateReport:
    def test_contains_versions(self) -> None:
        report = generate_report(
            "ampliseq", "2.14.0", "2.15.0", diff_tools(set(), set()), [], "https://x"
        )
        assert "2.14.0" in report
        assert "2.15.0" in report

    def test_breaking_status(self) -> None:
        tdiff = {"added": [], "removed": ["cutadapt"], "unchanged": []}
        report = generate_report("ampliseq", "2.14.0", "3.0.0", tdiff, [], "https://x")
        assert "BREAKING" in report
        assert "cutadapt" in report

    def test_includes_warnings(self) -> None:
        tdiff = {"added": [], "removed": [], "unchanged": []}
        report = generate_report(
            "ampliseq", "2.14.0", "2.15.0", tdiff, ["bad module ref"], "https://x"
        )
        assert "bad module ref" in report
