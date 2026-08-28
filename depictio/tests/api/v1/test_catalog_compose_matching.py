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
from depictio.catalog.payload import multiqc_module
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
            entries, basename="SRR1_profile.txt", full_path="/run/metaphlan/SRR1_profile.txt"
        )
        assert "metaphlan_profile" in _ids(matched)

    def test_an_outputs_recipe_makes_its_path_lane_inert(self, entries):
        """`pangolin_report` declares a recipe, so its raw CSV is not bindable.

        The recipe owns the output columns (SCHEMA.md), so offering the render on
        the raw collection would bind columns that only the recipe produces.
        """
        raw = _match_dc_to_catalog(
            entries, basename="sample.pangolin.csv", full_path="/run/sample.pangolin.csv"
        )
        assert "pangolin_report" not in _ids(raw)

        derived = _match_dc_to_catalog(entries, recipe="pangolin/pangolin_lineages.py")
        assert _ids(derived) == {"pangolin_report"}

    def test_a_renaming_recipe_is_never_offered_on_its_raw_file(self, entries):
        """The regression: mosdepth renames chrom/start/coverage, so a coverage
        track bound to the raw TSV failed with `"chromosome" not found`."""
        raw_tsv = "/run/variants/bowtie2/mosdepth/genome/all_samples.mosdepth.coverage.tsv"
        raw = _match_dc_to_catalog(
            entries, basename="all_samples.mosdepth.coverage.tsv", full_path=raw_tsv
        )
        assert "mosdepth_genome_coverage" not in _ids(raw)

        derived = _match_dc_to_catalog(entries, recipe="mosdepth/coverage_track_canonical.py")
        assert _ids(derived) == {"mosdepth_genome_coverage"}

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
        _add_matches(modules, [self.MATCH], "dc1", "wf1", "ancombc_results", "table", seen)
        _add_matches(modules, [self.MATCH], "dc1", "wf1", "ancombc_results", "table", seen)

        assert len(modules["qiime2"]["matches"]) == 1

    def test_the_same_output_on_two_collections_is_kept(self):
        modules: dict[str, dict[str, Any]] = {}
        seen: set[tuple[str, str, str]] = set()
        _add_matches(modules, [self.MATCH], "dc1", "wf1", "tag1", "table", seen)
        _add_matches(modules, [self.MATCH], "dc2", "wf1", "tag2", "table", seen)

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


class TestMultiqcAnchorNormalisation:
    """A report anchors a module per run, a catalog output names the module."""

    @pytest.mark.parametrize(
        ("anchor", "module"),
        [
            ("fastqc", "fastqc"),
            ("samtools_bowtie2", "samtools"),
            ("samtools_markduplicates", "samtools"),
            ("ivar_variants", "ivar"),
            ("quast_variants", "quast"),
            ("summary_variants_metrics", "summary"),
            ("mosdepth-cumcov", "mosdepth"),
        ],
    )
    def test_anchor_resolves_to_its_module(self, anchor, module):
        assert multiqc_module(anchor) == module

    def test_per_run_anchors_no_longer_drop_their_section(self, entries):
        """The whole point: these four were silently missing from every report."""
        matches = _match_dc_to_catalog(entries, basename="multiqc.parquet", full_path=RAW_MULTIQC)
        present = {
            multiqc_module(a)
            for a in [
                "ivar_variants",
                "samtools_bowtie2",
                "quast_variants",
                "summary_variants_metrics",
            ]
        }
        kept = _ids(_keep_present_multiqc_sections(matches, present))
        assert {"multiqc_ivar", "multiqc_samtools", "multiqc_quast", "multiqc_summary"} <= kept


class TestMatchPayload:
    def test_multiqc_matches_carry_their_origin_tool(self, entries):
        matches = _match_dc_to_catalog(entries, basename="multiqc.parquet", full_path=RAW_MULTIQC)
        origins = {m["output_id"]: m["origin_tool"] for m in matches}
        assert origins["multiqc_cutadapt"] == "Cutadapt"
        assert origins["multiqc_fastqc"] == "FastQC"
        # pipeline-generated custom content has no upstream tool to name
        assert origins["multiqc_summary"] is None

    def test_every_match_links_to_the_yaml_that_declares_it(self, entries):
        matches = _match_dc_to_catalog(entries, recipe="qiime2/ancombc.py")
        assert matches
        for match in matches:
            assert match["source_url"].endswith("depictio/catalog/qiime2/ancombc.yaml")

    def test_recipe_only_lookup_finds_the_new_module_outputs(self, entries):
        """The outputs added for collections that previously matched nothing."""
        for recipe, output_id in [
            ("qiime2/embedding_pcoa.py", "qiime2_embedding_pcoa"),
            ("qiime2/taxonomy_composition.py", "qiime2_taxonomy_composition"),
            ("qiime2/taxonomy_heatmap.py", "qiime2_taxonomy_heatmap"),
            ("nf-core/ampliseq/complex_heatmap_canonical.py", "qiime2_clustered_heatmap"),
            ("nf-core/ampliseq/ma_canonical.py", "qiime2_ma"),
            ("nf-core/ampliseq/bray_curtis_canonical.py", "qiime2_bray_curtis"),
            ("nf-core/ampliseq/tree_metadata_canonical.py", "qiime2_tree_metadata"),
            ("nf-core/viralrecon/oncoplot_canonical.py", "ivar_oncoplot_matrix"),
        ]:
            assert output_id in _ids(_match_dc_to_catalog(entries, recipe=recipe)), recipe

    def test_compositions_stay_out_of_the_catalog(self, entries):
        """Cross-sample compositions are dashboard work, not a module's output."""
        for recipe in [
            "nf-core/ampliseq/upset_canonical.py",
            "nf-core/viralrecon/upset_canonical.py",
            "nf-core/viralrecon/variant_feature_matrix_canonical.py",
        ]:
            assert _match_dc_to_catalog(entries, recipe=recipe) == []

    def test_the_collection_type_reaches_the_client(self):
        modules: dict[str, dict[str, Any]] = {}
        match = {"tool_id": "t", "tool_name": "T", "output_id": "o", "renders_as": []}
        _add_matches(modules, [match], "dc1", "wf1", "tag1", "multiqc", set())
        assert modules["t"]["matches"][0]["dc_type"] == "multiqc"


class TestPreviewPayloadSerialisation:
    """`/preview-payload` returns the payload as JSON, not through the bundle.

    A plotly trace built on a pandas frame keeps numpy arrays and NaN, which the
    embedded-bundle path already normalises. The JSON endpoint used to hand the
    raw dict to FastAPI, which raised on the arrays — a 500 on every output whose
    preview holds one.
    """

    def test_numpy_and_non_finite_survive_the_json_endpoint(self):
        import json

        import numpy as np

        from depictio.catalog.payload import json_safe

        payload = {
            "figures": {"a": {"x": np.array([1, 2, 3]), "y": [float("nan"), 1.0]}},
            "n": np.int64(7),
            "nested": [{"z": np.array([[1.0, float("inf")]])}],
        }
        safe = json_safe(payload)
        assert json.loads(json.dumps(safe)) == {
            "figures": {"a": {"x": [1, 2, 3], "y": [None, 1.0]}},
            "n": 7,
            "nested": [{"z": [[1.0, None]]}],
        }
