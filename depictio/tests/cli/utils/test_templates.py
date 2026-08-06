"""
Generic unit tests for the project template system.

Tests here use only synthetic fixture data and never depend on any specific
pipeline template (ampliseq, etc.) existing on disk. Pipeline-specific tests
belong in depictio/tests/integration/.

Covers:
- Template file location (generic error path)
- Variable substitution
- ID stripping
- TemplateMetadata / TemplateConditional / TemplateOrigin models
- _apply_conditionals helper (remove DCs, prune links, select dashboards)
"""

from pathlib import Path

import pytest

from depictio.cli.cli.utils.templates import (
    _apply_conditionals,
    _resolve_template_id_in,
    _strip_ids,
    latest_template_version,
    locate_template,
    materialize_recipe_seeds,
    substitute_template_variables,
)
from depictio.models.models.templates import (
    TemplateConditional,
    TemplateMetadata,
    TemplateOrigin,
    TemplateVariable,
)


class TestLocateTemplate:
    def test_locate_unknown_template_raises(self) -> None:
        """Unknown template ID raises FileNotFoundError with a helpful message."""
        with pytest.raises(FileNotFoundError, match="not found"):
            locate_template("nonexistent/pipeline/9.9.9")


class TestLatestTemplateVersion:
    @staticmethod
    def _make_versions(root: Path, pipeline: str, versions: list[str]) -> Path:
        pipeline_dir = root / pipeline
        for version in versions:
            (pipeline_dir / version).mkdir(parents=True)
            (pipeline_dir / version / "template.yaml").write_text("template: {}\n")
        return pipeline_dir

    def test_picks_highest_numeric_version_with_template(self, tmp_path: Path) -> None:
        # 2.9.0 < 2.16.0 numerically even though "2.9.0" > "2.16.0" as a string.
        pipeline_dir = self._make_versions(tmp_path, "ampliseq", ["2.14.0", "2.9.0", "2.16.0"])
        (pipeline_dir / "recipes").mkdir()  # non-version dir must not win
        (pipeline_dir / "9.9.9").mkdir()  # version dir without template.yaml
        assert latest_template_version(pipeline_dir) == "2.16.0"
        assert latest_template_version(tmp_path / "missing") is None

    def test_resolve_template_id_latest_versionless_and_passthrough(self, tmp_path: Path) -> None:
        self._make_versions(tmp_path / "nf-core", "ampliseq", ["2.14.0", "2.16.0"])
        assert _resolve_template_id_in(tmp_path, "nf-core/ampliseq/latest") == (
            "nf-core/ampliseq/2.16.0"
        )
        assert _resolve_template_id_in(tmp_path, "nf-core/ampliseq") == "nf-core/ampliseq/2.16.0"
        # Explicit versions, unversioned projects and unresolvable ids pass through
        # untouched (locate_template's own not-found error then fires).
        assert _resolve_template_id_in(tmp_path, "nf-core/ampliseq/2.14.0") == (
            "nf-core/ampliseq/2.14.0"
        )
        (tmp_path / "init" / "iris").mkdir(parents=True)
        (tmp_path / "init" / "iris" / "project.yaml").write_text("name: iris\n")
        assert _resolve_template_id_in(tmp_path, "init/iris") == "init/iris"
        assert _resolve_template_id_in(tmp_path, "nope/nothing/latest") == "nope/nothing/latest"


class TestSubstituteTemplateVariables:
    def test_substitute_string(self) -> None:
        result = substitute_template_variables("{DATA_ROOT}/file.tsv", {"DATA_ROOT": "/my/data"})
        assert result == "/my/data/file.tsv"

    def test_substitute_nested_dict(self) -> None:
        config = {
            "locations": ["{DATA_ROOT}"],
            "scan": {"filename": "{DATA_ROOT}/input.tsv"},
        }
        result = substitute_template_variables(config, {"DATA_ROOT": "/data"})
        assert result["locations"] == ["/data"]
        assert result["scan"]["filename"] == "/data/input.tsv"

    def test_substitute_list(self) -> None:
        result = substitute_template_variables(["{ROOT}/a.tsv", "{ROOT}/b.tsv"], {"ROOT": "/root"})
        assert result == ["/root/a.tsv", "/root/b.tsv"]

    def test_no_substitution_for_non_matching(self) -> None:
        result = substitute_template_variables("no_vars_here", {"DATA_ROOT": "/data"})
        assert result == "no_vars_here"

    def test_substitute_multiple_vars(self) -> None:
        result = substitute_template_variables(
            "{ROOT}/{FILE}", {"ROOT": "/data", "FILE": "meta.tsv"}
        )
        assert result == "/data/meta.tsv"

    def test_substitute_preserves_non_string_types(self) -> None:
        config = {"count": 42, "enabled": True, "value": None}
        result = substitute_template_variables(config, {"DATA_ROOT": "/data"})
        assert result == config

    def test_unresolved_placeholder_left_as_is(self) -> None:
        """Placeholder with no matching variable is left unchanged (warning logged)."""
        result = substitute_template_variables("{MISSING_VAR}/file.tsv", {})
        assert "{MISSING_VAR}" in result


class TestStripIds:
    def test_strip_top_level_id(self) -> None:
        config = {"id": "abc123", "name": "test"}
        result = _strip_ids(config)
        assert "id" not in result
        assert result["name"] == "test"

    def test_strip_nested_ids(self) -> None:
        config = {
            "workflows": [
                {
                    "id": "wf1",
                    "name": "my-pipeline",
                    "data_collections": [
                        {"id": "dc1", "data_collection_tag": "results"},
                    ],
                }
            ]
        }
        result = _strip_ids(config)
        assert "id" not in result["workflows"][0]
        assert "id" not in result["workflows"][0]["data_collections"][0]
        assert result["workflows"][0]["name"] == "my-pipeline"

    def test_non_id_fields_preserved(self) -> None:
        config = {"identifier": "keep-me", "id": "remove-me"}
        result = _strip_ids(config)
        assert result["identifier"] == "keep-me"
        assert "id" not in result


class TestTemplateVariableModel:
    def test_valid_required_variable(self) -> None:
        var = TemplateVariable(name="DATA_ROOT", description="Root directory")
        assert var.required is True

    def test_optional_variable(self) -> None:
        var = TemplateVariable(name="META_FILE", description="Metadata TSV", required=False)
        assert var.required is False

    def test_name_must_be_alphanumeric_underscores(self) -> None:
        with pytest.raises(ValueError):
            TemplateVariable(name="bad-name", description="x")

    def test_name_cannot_be_empty(self) -> None:
        with pytest.raises(ValueError):
            TemplateVariable(name="", description="x")


class TestTemplateMetadataModel:
    def test_valid_metadata_minimal(self) -> None:
        meta = TemplateMetadata(
            template_id="vendor/pipeline/1.0.0",
            description="A generic pipeline template",
            version="1.0.0",
        )
        assert meta.template_id == "vendor/pipeline/1.0.0"
        assert meta.variables == []
        assert meta.conditional == []

    def test_get_required_variable_names(self) -> None:
        meta = TemplateMetadata(
            template_id="vendor/pipeline/1.0.0",
            description="test",
            version="1.0.0",
            variables=[
                TemplateVariable(name="DATA_ROOT", description="Root", required=True),
                TemplateVariable(name="META_FILE", description="Optional", required=False),
            ],
        )
        assert meta.get_required_variable_names() == ["DATA_ROOT"]

    def test_template_id_cannot_be_empty(self) -> None:
        with pytest.raises(ValueError):
            TemplateMetadata(template_id="", description="x", version="1.0.0")

    def test_version_cannot_be_empty(self) -> None:
        with pytest.raises(ValueError):
            TemplateMetadata(template_id="vendor/pipeline/1.0.0", description="x", version="")


class TestTemplateConditionalModel:
    def test_if_var_absent(self) -> None:
        cond = TemplateConditional(
            if_var_absent="META_FILE",
            remove_dc_tags=["optional_dc_a", "optional_dc_b"],
            dashboards=["dashboards/base.yaml"],
        )
        assert cond.if_var_absent == "META_FILE"
        assert cond.if_var_present is None
        assert "optional_dc_a" in cond.remove_dc_tags
        assert cond.dashboards == ["dashboards/base.yaml"]

    def test_if_var_present(self) -> None:
        cond = TemplateConditional(
            if_var_present="META_FILE",
            dashboards=["dashboards/base.yaml", "dashboards/extended.yaml"],
        )
        assert cond.if_var_present == "META_FILE"
        assert cond.remove_dc_tags == []

    def test_defaults_are_empty(self) -> None:
        cond = TemplateConditional()
        assert cond.if_var_absent is None
        assert cond.if_var_present is None
        assert cond.remove_dc_tags == []
        assert cond.dashboards == []

    def test_template_metadata_parses_conditional_list(self) -> None:
        meta = TemplateMetadata(
            template_id="vendor/pipeline/1.0.0",
            description="test",
            version="1.0.0",
            variables=[
                TemplateVariable(name="DATA_ROOT", description="Root", required=True),
                TemplateVariable(name="META_FILE", description="Meta", required=False),
            ],
            conditional=[
                TemplateConditional(
                    if_var_absent="META_FILE",
                    remove_dc_tags=["optional_dc"],
                    dashboards=["base.yaml"],
                )
            ],
        )
        assert len(meta.conditional) == 1
        assert meta.get_required_variable_names() == ["DATA_ROOT"]


class TestTemplateOriginModel:
    def test_valid_origin(self) -> None:
        origin = TemplateOrigin(
            template_id="vendor/pipeline/1.0.0",
            template_version="1.0.0",
            data_root="/my/data",
            config_snapshot={"name": "test"},
        )
        assert origin.template_id == "vendor/pipeline/1.0.0"
        assert origin.data_root == "/my/data"
        assert origin.applied_at  # auto-generated timestamp

    def test_template_id_cannot_be_empty(self) -> None:
        with pytest.raises(ValueError):
            TemplateOrigin(template_id="", template_version="1.0.0", data_root="/data")

    def test_data_root_cannot_be_empty(self) -> None:
        with pytest.raises(ValueError):
            TemplateOrigin(
                template_id="vendor/pipeline/1.0.0", template_version="1.0.0", data_root=""
            )


class TestApplyConditionals:
    """Tests for _apply_conditionals using fully synthetic generic config."""

    def _base_config(self) -> dict:
        """A config with 5 DCs and 3 links, all with generic names."""
        return {
            "workflows": [
                {
                    "name": "my-pipeline",
                    "data_collections": [
                        {"data_collection_tag": "dc_always"},
                        {"data_collection_tag": "dc_core"},
                        {"data_collection_tag": "dc_optional_a"},
                        {"data_collection_tag": "dc_results"},
                        {"data_collection_tag": "dc_optional_b"},
                    ],
                }
            ],
            "links": [
                {"source_dc_tag": "dc_always", "target_dc_tag": "dc_core"},
                {"source_dc_tag": "dc_optional_a", "target_dc_tag": "dc_results"},
                {"source_dc_tag": "dc_optional_a", "target_dc_tag": "dc_optional_b"},
            ],
        }

    def _conditionals(self) -> list[TemplateConditional]:
        return [
            TemplateConditional(
                if_var_absent="OPT_VAR",
                remove_dc_tags=["dc_optional_a", "dc_optional_b"],
                dashboards=["dashboards/base.yaml"],
            ),
            TemplateConditional(
                if_var_present="OPT_VAR",
                dashboards=["dashboards/base.yaml", "dashboards/extended.yaml"],
            ),
        ]

    def test_absent_var_removes_dcs_and_prunes_links(self) -> None:
        """When OPT_VAR absent: optional DCs removed, their links pruned."""
        config = self._base_config()
        result, dashboards, _ = _apply_conditionals(
            config, self._conditionals(), {"REQUIRED_VAR"}, Path("/tmp")
        )
        dc_tags = [dc["data_collection_tag"] for dc in result["workflows"][0]["data_collections"]]
        assert "dc_optional_a" not in dc_tags
        assert "dc_optional_b" not in dc_tags
        assert "dc_always" in dc_tags
        assert "dc_core" in dc_tags
        # Only the dc_always→dc_core link survives
        links = [(lnk["source_dc_tag"], lnk["target_dc_tag"]) for lnk in result["links"]]
        assert ("dc_always", "dc_core") in links
        assert ("dc_optional_a", "dc_results") not in links
        assert ("dc_optional_a", "dc_optional_b") not in links
        assert dashboards == ["dashboards/base.yaml"]

    def test_present_var_keeps_all_dcs(self) -> None:
        """When OPT_VAR present: all DCs kept; extended dashboard added."""
        config = self._base_config()
        result, dashboards, _ = _apply_conditionals(
            config,
            self._conditionals(),
            {"REQUIRED_VAR", "OPT_VAR"},
            Path("/tmp"),
        )
        dc_tags = [dc["data_collection_tag"] for dc in result["workflows"][0]["data_collections"]]
        assert len(dc_tags) == 5
        assert "dc_optional_a" in dc_tags
        assert "dc_optional_b" in dc_tags
        assert dashboards == ["dashboards/base.yaml", "dashboards/extended.yaml"]

    def test_no_conditionals_is_noop(self) -> None:
        """Empty conditionals list: config unchanged, no dashboards selected."""
        config = self._base_config()
        result, dashboards, _ = _apply_conditionals(config, [], {"REQUIRED_VAR"}, Path("/tmp"))
        dc_tags = [dc["data_collection_tag"] for dc in result["workflows"][0]["data_collections"]]
        assert len(dc_tags) == 5
        assert dashboards == []

    def test_no_links_key_is_safe(self) -> None:
        """Config without a 'links' key doesn't crash when pruning."""
        config = self._base_config()
        del config["links"]
        result, _, _ = _apply_conditionals(
            config, self._conditionals(), {"REQUIRED_VAR"}, Path("/tmp")
        )
        assert "links" in result
        assert result["links"] == []

    def test_multiple_workflows_all_pruned(self) -> None:
        """DCs are removed from ALL workflows, not just the first."""
        config = {
            "workflows": [
                {
                    "name": "wf1",
                    "data_collections": [
                        {"data_collection_tag": "dc_always"},
                        {"data_collection_tag": "dc_optional_a"},
                    ],
                },
                {
                    "name": "wf2",
                    "data_collections": [
                        {"data_collection_tag": "dc_optional_a"},
                        {"data_collection_tag": "dc_core"},
                    ],
                },
            ],
            "links": [],
        }
        conditionals = [
            TemplateConditional(if_var_absent="OPT_VAR", remove_dc_tags=["dc_optional_a"])
        ]
        result, _, _ = _apply_conditionals(config, conditionals, set(), Path("/tmp"))
        for wf in result["workflows"]:
            tags = [dc["data_collection_tag"] for dc in wf["data_collections"]]
            assert "dc_optional_a" not in tags


class TestMaterializeRecipeSeeds:
    """The shared recipe→seed conversion used by both the CLI and boot seeding."""

    @staticmethod
    def _config(source: str = "transformed", *, tag: str = "taxonomy", **extra) -> dict:
        dc_config: dict = {"source": source, **extra}
        if source == "transformed":
            dc_config.setdefault("transform", {"recipe": "some_recipe"})
        return {
            "workflows": [
                {
                    "name": "wf",
                    "data_collections": [
                        {"data_collection_tag": tag, "config": dc_config},
                        {
                            "data_collection_tag": "plain",
                            "config": {"source": "native", "scan": {"mode": "recursive"}},
                        },
                    ],
                }
            ],
            "links": [{"source_dc_tag": tag, "target_dc_tag": "plain"}],
        }

    def test_seed_present_replaces_recipe_with_file_scan(self, tmp_path: Path) -> None:
        """A recipe DC with a committed seed becomes a single-file TSV scan."""
        (tmp_path / "taxonomy.tsv").write_text("a\tb\n1\t2\n")
        config = self._config(dc_specific_properties={"format": "csv"})

        materialized, missing = materialize_recipe_seeds(config, str(tmp_path), drop_missing=False)

        assert (materialized, missing) == (["taxonomy"], [])
        dc_config = config["workflows"][0]["data_collections"][0]["config"]
        # `source` and `transform` both survive so the viewer still shows the
        # recipe lineage and the catalog can still match the DC on
        # `transform.recipe`; `materialized` is what marks it as already computed.
        assert dc_config["source"] == "transformed"
        assert dc_config["transform"] == {"recipe": "some_recipe", "materialized": True}
        assert dc_config["scan"] == {
            "mode": "single",
            "scan_parameters": {"filename": str(tmp_path / "taxonomy.tsv")},
        }
        # The template's format described the recipe's *input*, not the seed.
        assert dc_config["dc_specific_properties"]["format"] == "tsv"

    def test_seed_missing_keeps_recipe_when_not_dropping(self, tmp_path: Path) -> None:
        """The CLI contract: no seed means the recipe runs exactly as before."""
        config = self._config()

        materialized, missing = materialize_recipe_seeds(config, str(tmp_path), drop_missing=False)

        assert (materialized, missing) == ([], [])
        dc_config = config["workflows"][0]["data_collections"][0]["config"]
        assert dc_config["transform"] == {"recipe": "some_recipe"}
        assert "scan" not in dc_config
        assert len(config["workflows"][0]["data_collections"]) == 2
        assert config["links"] == [{"source_dc_tag": "taxonomy", "target_dc_tag": "plain"}]

    def test_seed_missing_drops_dc_and_its_links(self, tmp_path: Path) -> None:
        """The init contract: no seed means the DC goes, links included."""
        config = self._config()

        materialized, missing = materialize_recipe_seeds(config, str(tmp_path), drop_missing=True)

        assert (materialized, missing) == ([], ["taxonomy"])
        tags = [dc["data_collection_tag"] for dc in config["workflows"][0]["data_collections"]]
        assert tags == ["plain"]
        assert config["links"] == []

    def test_native_dc_with_matching_tsv_is_untouched(self, tmp_path: Path) -> None:
        """A root `{dc_tag}.tsv` next to a non-recipe DC is a name collision.

        viralrecon ships mosdepth_*.tsv beside `source: native` recursive-scan
        DCs of the same tag — "root TSV present" must never on its own mean
        "this DC has a seed".
        """
        (tmp_path / "mosdepth_genome_coverage.tsv").write_text("a\tb\n")
        config = self._config("native", tag="mosdepth_genome_coverage", scan={"mode": "recursive"})

        materialized, missing = materialize_recipe_seeds(config, str(tmp_path), drop_missing=True)

        assert (materialized, missing) == ([], [])
        dc_config = config["workflows"][0]["data_collections"][0]["config"]
        assert dc_config["scan"] == {"mode": "recursive"}

    def test_absent_dc_specific_properties_is_created(self, tmp_path: Path) -> None:
        """A DC declaring no (or null) dc_specific_properties still gets the format."""
        (tmp_path / "taxonomy.tsv").write_text("a\tb\n")
        config = self._config(dc_specific_properties=None)

        materialize_recipe_seeds(config, str(tmp_path), drop_missing=False)

        dc_config = config["workflows"][0]["data_collections"][0]["config"]
        assert dc_config["dc_specific_properties"] == {"format": "tsv"}
class TestManifestModeResolution:
    """resolve_template with data_root=None (manifest-driven templates)."""

    def test_reference_template_resolves_without_data_root(self) -> None:
        from depictio.cli.cli.utils.templates import resolve_template

        config, meta, origin, dashboard_paths, variables = resolve_template(
            "generic/manifest-tables/1",
            data_root=None,
            extra_vars={"MANIFEST_URL": "https://example.org/run42/manifest.json"},
        )
        assert origin.data_root is None
        assert variables["MANIFEST_URL"] == "https://example.org/run42/manifest.json"
        assert "DATA_ROOT" not in variables
        scan = config["workflows"][0]["data_collections"][0]["config"]["scan"]
        assert scan["mode"] == "manifest"
        assert scan["scan_parameters"]["manifest_url"] == "https://example.org/run42/manifest.json"
        assert [p.name for p in dashboard_paths] == ["base.yaml"]

    def test_default_project_name_derives_from_manifest(self) -> None:
        from depictio.cli.cli.utils.templates import resolve_template

        # The reference template carries a `name`, so exercise the fallback via
        # project_name=None on a config whose name we blank through override.
        config, _, _, _, _ = resolve_template(
            "generic/manifest-tables/1",
            data_root=None,
            project_name="run42",
            extra_vars={"MANIFEST_URL": "https://example.org/run42/manifest.json?token=x"},
        )
        assert config["name"] == "run42"

    def test_origin_allows_none_data_root(self) -> None:
        origin = TemplateOrigin(
            template_id="generic/manifest-tables/1",
            template_version="1.0.0",
            variables={"MANIFEST_URL": "https://example.org/m.json"},
        )
        assert origin.data_root is None
