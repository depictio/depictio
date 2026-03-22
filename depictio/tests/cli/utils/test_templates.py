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
    _strip_ids,
    locate_template,
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
        result = substitute_template_variables(
            ["{ROOT}/a.tsv", "{ROOT}/b.tsv"], {"ROOT": "/root"}
        )
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
            TemplateOrigin(
                template_id="", template_version="1.0.0", data_root="/data"
            )

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
        result, dashboards = _apply_conditionals(
            config, self._conditionals(), {"REQUIRED_VAR"}, Path("/tmp")
        )
        dc_tags = [dc["data_collection_tag"] for dc in result["workflows"][0]["data_collections"]]
        assert "dc_optional_a" not in dc_tags
        assert "dc_optional_b" not in dc_tags
        assert "dc_always" in dc_tags
        assert "dc_core" in dc_tags
        # Only the dc_always→dc_core link survives
        links = [(l["source_dc_tag"], l["target_dc_tag"]) for l in result["links"]]
        assert ("dc_always", "dc_core") in links
        assert ("dc_optional_a", "dc_results") not in links
        assert ("dc_optional_a", "dc_optional_b") not in links
        assert dashboards == ["dashboards/base.yaml"]

    def test_present_var_keeps_all_dcs(self) -> None:
        """When OPT_VAR present: all DCs kept; extended dashboard added."""
        config = self._base_config()
        result, dashboards = _apply_conditionals(
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
        result, dashboards = _apply_conditionals(config, [], {"REQUIRED_VAR"}, Path("/tmp"))
        dc_tags = [dc["data_collection_tag"] for dc in result["workflows"][0]["data_collections"]]
        assert len(dc_tags) == 5
        assert dashboards == []

    def test_no_links_key_is_safe(self) -> None:
        """Config without a 'links' key doesn't crash when pruning."""
        config = self._base_config()
        del config["links"]
        result, _ = _apply_conditionals(
            config, self._conditionals(), {"REQUIRED_VAR"}, Path("/tmp")
        )
        assert "links" in result
        assert result["links"] == []

    def test_multiple_workflows_all_pruned(self) -> None:
        """DCs are removed from ALL workflows, not just the first."""
        config = {
            "workflows": [
                {"name": "wf1", "data_collections": [
                    {"data_collection_tag": "dc_always"},
                    {"data_collection_tag": "dc_optional_a"},
                ]},
                {"name": "wf2", "data_collections": [
                    {"data_collection_tag": "dc_optional_a"},
                    {"data_collection_tag": "dc_core"},
                ]},
            ],
            "links": [],
        }
        conditionals = [TemplateConditional(if_var_absent="OPT_VAR", remove_dc_tags=["dc_optional_a"])]
        result, _ = _apply_conditionals(config, conditionals, set(), Path("/tmp"))
        for wf in result["workflows"]:
            tags = [dc["data_collection_tag"] for dc in wf["data_collections"]]
            assert "dc_optional_a" not in tags
