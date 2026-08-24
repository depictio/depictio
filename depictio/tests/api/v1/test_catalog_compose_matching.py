"""Unit tests for how the catalog compose endpoint recognises a data collection.

Covers the three matching signals (`find.filename`, `find.path_glob`, recipe),
how a stored DC config is normalised into them, and the MultiQC section filter.
All pure functions, no DB.
"""

from __future__ import annotations

from typing import Any

import pytest

from depictio.api.v1.endpoints.catalog_endpoints.routes import (
    _add_matches,
    _dc_match_inputs,
    _keep_present_multiqc_sections,
    _match_dc_to_catalog,
)
from depictio.models.components.advanced_viz.catalog import load_catalog_entries

# A seeded reference project materialises every recipe DC as `{dc_tag}.tsv` next
# to the run, so the raw pipeline layout the `find` patterns describe is gone.
SEEDED_TSV = "/app/depictio/projects/nf-core/ampliseq/2.16.0/rarefaction_canonical.tsv"
RAW_MULTIQC = "/app/depictio/projects/nf-core/ampliseq/2.16.0/multiqc/multiqc_data/multiqc.parquet"


@pytest.fixture(scope="module")
def entries():
    return load_catalog_entries()


def _ids(matches: list[dict[str, Any]]) -> set[str]:
    return {m["output_id"] for m in matches}


class TestMatchSignals:
    def test_recipe_identifies_a_materialised_collection(self, entries):
        """The canonical TSV matches no `find` pattern; the recipe still names the tool."""
        assert (
            _match_dc_to_catalog(
                entries, basename="rarefaction_canonical.tsv", full_path=SEEDED_TSV
            )
            == []
        )

        matched = _match_dc_to_catalog(
            entries,
            basename="rarefaction_canonical.tsv",
            full_path=SEEDED_TSV,
            recipe="qiime2/rarefaction_canonical.py",
        )
        assert _ids(matched) == {"qiime2_rarefaction_canonical"}

    def test_recipe_works_without_any_path(self, entries):
        """A CLI-computed recipe DC has no scan block at all, so no path to offer."""
        assert _ids(_match_dc_to_catalog(entries, recipe="qiime2/ancombc.py")) == {"qiime2_ancombc"}

    def test_unknown_recipe_matches_nothing(self, entries):
        assert _match_dc_to_catalog(entries, recipe="does/not/exist.py") == []

    def test_no_path_and_no_recipe_matches_nothing(self, entries):
        """Guards the recipe-only call path against wildcard `find` patterns."""
        assert _match_dc_to_catalog(entries) == []

    def test_path_glob_still_matches(self, entries):
        matched = _match_dc_to_catalog(entries, basename="multiqc.parquet", full_path=RAW_MULTIQC)
        assert "multiqc_cutadapt" in _ids(matched)

    def test_filename_glob_still_matches(self, entries):
        matched = _match_dc_to_catalog(
            entries, basename="sample.pangolin.csv", full_path="/run/sample.pangolin.csv"
        )
        assert "pangolin_report" in _ids(matched)

    def test_one_recipe_may_back_several_outputs(self, entries):
        """Two catalog outputs render the same frame differently; both are offered."""
        matched = _match_dc_to_catalog(entries, recipe="qiime2/stacked_taxonomy_canonical.py")
        assert _ids(matched) == {"qiime2_stacked_taxonomy_canonical", "qiime2_taxa_barplot"}


class TestMatchInputs:
    """A stored DC carries every config key, `null` where the template had none."""

    def test_null_scan_still_yields_the_recipe(self):
        """A recipe DC computed straight into a delta table has `scan: null`."""
        config = {
            "type": "table",
            "source": "transformed",
            "transform": {"recipe": "qiime2/ancombc.py"},
            "scan": None,
        }
        assert _dc_match_inputs(config) == ("qiime2/ancombc.py", "", "")

    def test_materialised_dc_yields_both_recipe_and_scan(self):
        config = {
            "transform": {"recipe": "qiime2/ancombc.py", "materialized": True},
            "scan": {"mode": "single", "scan_parameters": {"filename": "/d/ancombc_results.tsv"}},
        }
        assert _dc_match_inputs(config) == ("qiime2/ancombc.py", "single", "/d/ancombc_results.tsv")

    def test_plain_scan_dc_has_no_recipe(self):
        config = {
            "transform": None,
            "scan": {"mode": "recursive", "scan_parameters": {"regex_config": {}}},
        }
        assert _dc_match_inputs(config) == (None, "recursive", "")


class TestDedupe:
    MATCH = {
        "tool_id": "qiime2",
        "tool_name": "QIIME 2",
        "output_id": "qiime2_ancombc",
        "description": "",
        "renders_as": [],
    }

    def test_same_output_is_offered_once_per_collection(self):
        """A DC can match through both its path and its recipe."""
        modules: dict[str, dict[str, Any]] = {}
        seen: set[tuple[str, str, str]] = set()
        _add_matches(modules, [self.MATCH], "dc1", "wf1", "ancombc_results", seen)
        _add_matches(modules, [self.MATCH], "dc1", "wf1", "ancombc_results", seen)

        assert len(modules["qiime2"]["matches"]) == 1

    def test_the_same_output_on_two_collections_is_kept(self):
        modules: dict[str, dict[str, Any]] = {}
        seen: set[tuple[str, str, str]] = set()
        _add_matches(modules, [self.MATCH], "dc1", "wf1", "tag1", seen)
        _add_matches(modules, [self.MATCH], "dc2", "wf1", "tag2", seen)

        assert len(modules["qiime2"]["matches"]) == 2


class TestMultiqcSectionFilter:
    def test_only_sections_present_in_the_report_survive(self, entries):
        matches = _match_dc_to_catalog(entries, basename="multiqc.parquet", full_path=RAW_MULTIQC)
        assert len(matches) > 2  # the raw path offers every section

        kept = _keep_present_multiqc_sections(matches, {"cutadapt", "fastqc"})
        assert _ids(kept) == {"multiqc_cutadapt", "multiqc_fastqc"}

    def test_unknown_module_list_leaves_matches_untouched(self, entries):
        matches = _match_dc_to_catalog(entries, basename="multiqc.parquet", full_path=RAW_MULTIQC)
        assert _keep_present_multiqc_sections(matches, None) == matches

    def test_renders_without_a_section_are_never_dropped(self):
        match = {
            "tool_id": "multiqc",
            "tool_name": "MultiQC",
            "output_id": "multiqc_summary_metrics",
            "description": "",
            "renders_as": [{"component": "table"}],
        }
        assert _keep_present_multiqc_sections([match], set()) == [match]
