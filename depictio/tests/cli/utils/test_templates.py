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

The exception to "never depend on a specific pipeline template" is at the
bottom: resolving against a remote data root has to be proved on a real shipped
template, because the value of the feature is that a template written for a
directory works unchanged against an ``s3://`` prefix. The data is still
synthetic - a stubbed key listing, no network.
"""

import json
from pathlib import Path

import pytest

from depictio.cli.cli.utils.data_root import data_root_for
from depictio.cli.cli.utils.templates import (
    OPTIONAL_SOURCE_MISSING_REASON,
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
from depictio.tests.cli.s3_stubs import (
    MEGATEST_TREE,
    S3_BUCKET,
    S3_ROOT,
    install_megatest_listing,
    s3_cli_config,
    s3_data_root,
    write_tree,
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


class TestLocateTemplateByPath:
    """A received bundle must be runnable where it lands.

    `depictio template export` produces a directory; without path support the
    recipient would have to copy it into their own site-packages before
    `--template` could see it, which is exactly what blocks sharing.
    """

    @pytest.fixture(autouse=True)
    def _cli_context(self, monkeypatch):
        # The path form is a CLI affordance; the suite's default context is "server".
        monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")

    def test_directory_containing_template_yaml(self, tmp_path):
        bundle = tmp_path / "recu"
        bundle.mkdir()
        (bundle / "template.yaml").write_text("name: x\n")
        assert locate_template(str(bundle)) == (bundle / "template.yaml").resolve()

    def test_direct_yaml_file(self, tmp_path):
        target = tmp_path / "template.yaml"
        target.write_text("name: x\n")
        assert locate_template(str(target)) == target.resolve()

    def test_project_yaml_fallback(self, tmp_path):
        bundle = tmp_path / "legacy"
        bundle.mkdir()
        (bundle / "project.yaml").write_text("name: x\n")
        assert locate_template(str(bundle)) == (bundle / "project.yaml").resolve()

    def test_directory_without_a_template_explains_what_is_missing(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(FileNotFoundError, match="no template.yaml or project.yaml"):
            locate_template(str(empty))

    def test_installed_ids_still_resolve(self):
        """Path support must not shadow the shipped catalogue."""
        assert locate_template("generic/manifest-tables/1").is_file()


class TestLocateTemplateConfinement:
    """Ids are confined to the templates directory; the path form is CLI-only.

    The API resolves ids for remote callers (``POST /projects/from_manifest``),
    so a path form there, or an id that walks out of the directory, would let
    any request read an arbitrary YAML on the server.
    """

    def test_path_form_refused_outside_the_cli(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
        bundle = tmp_path / "recu"
        bundle.mkdir()
        (bundle / "template.yaml").write_text("name: x\n")
        with pytest.raises(FileNotFoundError, match="not found"):
            locate_template(str(bundle))
        with pytest.raises(FileNotFoundError, match="not found"):
            locate_template(str(bundle / "template.yaml"))

    @pytest.mark.parametrize("context", ["server", "CLI"])
    @pytest.mark.parametrize(
        "escaping",
        ["../../../nope-does-not-exist/x", "generic/../../nope/x", "./generic/manifest-tables/1"],
    )
    def test_id_leaving_the_templates_dir_is_refused(self, context, escaping, monkeypatch):
        # On the CLI the path form is tried first, so none of these may exist
        # relative to the working directory either.
        monkeypatch.setenv("DEPICTIO_CONTEXT", context)
        with pytest.raises(FileNotFoundError, match="not found"):
            locate_template(escaping)

    def test_installed_ids_resolve_in_server_context(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
        assert locate_template("generic/manifest-tables/1").is_file()
        with pytest.raises(FileNotFoundError) as exc:
            locate_template("generic/does-not-exist/1")
        # The catalogue is carried separately so the API can omit the path.
        assert "generic/manifest-tables/1" in exc.value.available_templates


# ---------------------------------------------------------------------------
# Remote data roots
# ---------------------------------------------------------------------------
#
# A data root that is an ``s3://`` prefix answers the same questions a directory
# does, so template resolution should not be able to tell them apart. The
# listing and the megatest fixture tree come from ``depictio.tests.cli.s3_stubs``:
# no network, and the key list is the whole fixture.


def _scans_by_tag(config: dict) -> dict[str, dict]:
    return {
        dc["data_collection_tag"]: (dc.get("config") or {}).get("scan")
        for workflow in config["workflows"]
        for dc in workflow["data_collections"]
    }


class TestRemoteTemplateResolution:
    """A real shipped template resolved against an ``s3://`` prefix."""

    def _resolve(self, monkeypatch, tree=None, **kwargs):
        install_megatest_listing(monkeypatch, tree)
        from depictio.cli.cli.utils.templates import resolve_template

        return resolve_template(
            "nf-core/ampliseq/2.16.0", S3_ROOT, CLI_config=s3_cli_config(), **kwargs
        )

    def test_data_root_is_the_prefix_verbatim(self, monkeypatch):
        """`Path("s3://b/k").absolute()` yields `<cwd>/s3:/b/k` — every path
        derived from DATA_ROOT would be silently corrupted by it."""
        config, _meta, origin, _dashboards, variables = self._resolve(monkeypatch)
        assert variables["DATA_ROOT"] == S3_ROOT
        assert origin.data_root == S3_ROOT
        assert config["workflows"][0]["data_location"]["locations"] == [S3_ROOT]
        # `Path.absolute()` collapses the double slash; nothing in the config
        # may carry that spelling, nor the working directory it prepends.
        dumped = json.dumps(config)
        assert f"s3:/{S3_BUCKET}" not in dumped
        assert str(Path.cwd()) not in dumped

    def test_variables_are_derived_from_the_listing(self, monkeypatch):
        """Samplesheet, metadata and the params-derived flags, all off one listing."""
        _config, _meta, _origin, _dashboards, variables = self._resolve(monkeypatch)
        assert variables["SAMPLESHEET_FILE"] == f"{S3_ROOT}/input/samplesheet.csv"
        assert variables["METADATA_FILE"] == f"{S3_ROOT}/input/Metadata_full.tsv"
        # Read out of the object, not off a disk.
        assert variables["METADATA_ID_COL"] == "sample"
        assert variables["GROUP_COL"] == "habitat"
        assert variables["ANNOTATION_COLS"] == "habitat,treatment"
        # params.json has no `ancombc: true`, so the ANCOM-BC DCs are gated out.
        assert variables["SKIP_ANCOM"] == "true"

    def test_a_local_metadata_override_is_still_read_under_a_remote_root(
        self, monkeypatch, tmp_path
    ):
        """In the CLI, a METADATA_FILE outside the root falls back to the filesystem.

        `--data-root s3://... --var METADATA_FILE=/local/meta.tsv` is a
        supported combination. Bailing out as soon as the root was remote left
        GROUP_COL at the `__no_group__` sentinel with nothing logged, so every
        group-aware dashboard rendered ungrouped and the run still reported
        success.
        """
        monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")
        local_meta = tmp_path / "outside_the_root.tsv"
        local_meta.write_text("ID\tbiome\tdepth\nS1\tsoil\t10\n")
        _config, _meta, _origin, _dashboards, variables = self._resolve(
            monkeypatch, extra_vars={"METADATA_FILE": str(local_meta)}
        )
        assert variables["METADATA_ID_COL"] == "ID"
        assert variables["GROUP_COL"] == "biome"
        assert variables["ANNOTATION_COLS"] == "biome,depth"

    def test_a_server_never_probes_its_own_disk_under_a_remote_root(self, monkeypatch, tmp_path):
        """Outside the CLI the local fallback is an oracle, so it does not exist.

        `POST /projects/from_run` hands user-supplied variables to this
        resolver. With the fallback live, `METADATA_FILE=/etc/hostname` read
        the file's first line, and the optional metadata collection came back
        pruned or kept depending on whether the path existed in the container:
        any authenticated caller could probe the server's filesystem one path
        at a time. Present or absent, a local path must now resolve identically
        and nothing may be read from it.
        """
        monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
        present = tmp_path / "present.tsv"
        present.write_text("ID\tbiome\tdepth\nS1\tsoil\t10\n")
        absent = tmp_path / "absent.tsv"

        outcomes = []
        for path in (present, absent):
            config, _meta, _origin, _dashboards, variables = self._resolve(
                monkeypatch, extra_vars={"METADATA_FILE": str(path)}
            )
            tags = sorted(
                dc["data_collection_tag"] for dc in config["workflows"][0]["data_collections"]
            )
            outcomes.append((tags, variables.get("METADATA_ID_COL"), variables.get("GROUP_COL")))

        assert outcomes[0] == outcomes[1]
        tags, id_col, group_col = outcomes[0]
        assert "metadata" not in tags
        assert id_col != "ID"
        assert group_col != "biome"

    def test_scan_modes_become_their_remote_counterparts(self, monkeypatch):
        config, _meta, _origin, _dashboards, _variables = self._resolve(monkeypatch)
        scans = _scans_by_tag(config)
        assert scans["samplesheet"] == {
            "mode": "url",
            "scan_parameters": {"url": f"{S3_ROOT}/input/samplesheet.csv"},
        }
        assert scans["multiqc_data"] == {
            "mode": "s3_prefix",
            "scan_parameters": {
                "prefix": f"{S3_ROOT}/",
                # The template's own regex, verbatim.
                "pattern": "multiqc/multiqc_data/multiqc.parquet",
                "pattern_syntax": "regex",
            },
        }
        # Nothing may survive in a mode that stats the local filesystem.
        assert all(scan["mode"] != "single" for scan in scans.values() if scan)

    def test_optional_dc_is_pruned_through_its_url_mode(self, monkeypatch):
        """The prune must see `url`, not a `single` filename it cannot stat."""
        without_tree = {
            rel: body
            for rel, body in MEGATEST_TREE.items()
            if rel != "qiime2/phylogenetic_tree/tree.nwk"
        }
        config, _meta, origin, _dashboards, _variables = self._resolve(
            monkeypatch, tree=without_tree
        )
        assert "phylogenetic_tree_canonical" not in _scans_by_tag(config)
        pruned = {
            entry.data_collection_tag: entry.removal_reason
            for entry in origin.expected_data_collections
            if not entry.included
        }
        assert pruned["phylogenetic_tree_canonical"] == OPTIONAL_SOURCE_MISSING_REASON
        # And it survives when the object is there.
        kept, _m, _o, _d, _v = self._resolve(monkeypatch)
        assert _scans_by_tag(kept)["phylogenetic_tree_canonical"]["mode"] == "url"

    def test_provenance_is_read_out_of_the_prefix(self, monkeypatch):
        _config, _meta, origin, _dashboards, _variables = self._resolve(monkeypatch)
        assert origin.run_provenance_files == ["pipeline_info/params_2026-01-16_12-00-00.json"]
        assert any(entry.key == "FW_primer" for entry in origin.run_provenance)


class TestLocalResolutionIsUnchanged:
    """The regression guard: a local root is still resolved exactly as before."""

    def _resolve(self, data_root):
        from depictio.cli.cli.utils.templates import resolve_template

        return resolve_template("nf-core/ampliseq/2.16.0", data_root)

    def test_local_paths_stay_local_paths(self, tmp_path):
        base = write_tree(tmp_path / "results", MEGATEST_TREE)
        config, _meta, origin, dashboards, variables = self._resolve(str(base))

        assert variables["DATA_ROOT"] == str(base.absolute())
        assert origin.data_root == str(base.absolute())
        assert variables["SAMPLESHEET_FILE"] == str(base / "input" / "samplesheet.csv")
        assert variables["METADATA_FILE"] == str(base / "input" / "Metadata_full.tsv")
        assert variables["METADATA_ID_COL"] == "sample"
        assert variables["GROUP_COL"] == "habitat"
        assert variables["SKIP_ANCOM"] == "true"
        assert origin.run_provenance_files == ["pipeline_info/params_2026-01-16_12-00-00.json"]
        assert [p.name for p in dashboards] == ["base.yaml"]

        scans = _scans_by_tag(config)
        assert scans["samplesheet"] == {
            "mode": "single",
            "scan_parameters": {"filename": str(base / "input" / "samplesheet.csv")},
        }
        # A local root leaves the walk alone: no prefix, no mode rewriting.
        assert scans["multiqc_data"] == {
            "mode": "recursive",
            "scan_parameters": {
                "regex_config": {"pattern": "multiqc/multiqc_data/multiqc.parquet"}
            },
        }
        assert config["workflows"][0]["data_location"]["locations"] == [str(base.absolute())]

    def test_a_path_and_a_prebuilt_root_resolve_identically(self, tmp_path):
        """`str`, `Path` and `DataRoot` are three spellings of one data root."""
        base = write_tree(tmp_path / "results", MEGATEST_TREE)
        from_str = self._resolve(str(base))[0]
        from_path = self._resolve(base)[0]
        from_root = self._resolve(data_root_for(str(base)))[0]
        for other in (from_path, from_root):
            assert _scans_by_tag(other) == _scans_by_tag(from_str)
            assert other["name"] == from_str["name"]

    def test_local_and_remote_keep_the_same_data_collections(self, tmp_path, monkeypatch):
        """The remote path must not lose or invent a DC: only locations change."""
        base = write_tree(tmp_path / "results-3d5c7e5b", MEGATEST_TREE)
        local = self._resolve(str(base))[0]
        install_megatest_listing(monkeypatch)
        from depictio.cli.cli.utils.templates import resolve_template

        remote = resolve_template("nf-core/ampliseq/2.16.0", S3_ROOT, CLI_config=s3_cli_config())[0]
        assert sorted(_scans_by_tag(remote)) == sorted(_scans_by_tag(local))


class TestPreviewDataRoot:
    """What `--data-root` would yield, before anything is created."""

    def _preview(self, monkeypatch, tree=None, **kwargs):
        install_megatest_listing(monkeypatch, tree)
        from depictio.cli.cli.utils.template_preview import preview_data_root

        return preview_data_root(
            "nf-core/ampliseq/2.16.0", S3_ROOT, CLI_config=s3_cli_config(), **kwargs
        )

    @staticmethod
    def _row(preview, tag):
        return next(row for row in preview.data_collections if row.tag == tag)

    def test_header_reports_what_the_run_would_be(self, monkeypatch):
        preview = self._preview(monkeypatch)
        assert preview.template_id == "nf-core/ampliseq/2.16.0"
        assert preview.data_root == S3_ROOT
        assert preview.project_name
        assert preview.dashboards == ["base.yaml"]
        assert preview.detected_runs == []  # ampliseq is a `flat` structure
        assert preview.truncated is False

    def test_resolved_variables_carry_the_derived_decisions(self, monkeypatch):
        """The gating flags matter most: they decide which DCs exist at all."""
        preview = self._preview(monkeypatch)
        assert preview.resolved_variables["SKIP_ANCOM"] == "true"
        assert preview.resolved_variables["GROUP_COL"] == "habitat"
        assert preview.resolved_variables["METADATA_ID_COL"] == "sample"
        assert preview.resolved_variables["SAMPLESHEET_FILE"].startswith(S3_ROOT)
        # The root itself is a field of its own, not a "resolved variable".
        assert "DATA_ROOT" not in preview.resolved_variables

    def test_a_scan_dc_that_matches(self, monkeypatch):
        row = self._row(self._preview(monkeypatch), "multiqc_data")
        assert (row.kind, row.mode, row.status, row.matched) == ("scan", "s3_prefix", "ok", 1)

    def test_a_scan_dc_that_matches_nothing(self, monkeypatch):
        without_multiqc = {
            rel: body
            for rel, body in MEGATEST_TREE.items()
            if rel != "multiqc/multiqc_data/multiqc.parquet"
        }
        row = self._row(self._preview(monkeypatch, tree=without_multiqc), "multiqc_data")
        assert (row.status, row.matched) == ("empty", 0)

    def test_a_recipe_dc_with_a_missing_required_source(self, monkeypatch):
        row = self._row(self._preview(monkeypatch), "alpha_rarefaction")
        assert (row.kind, row.mode, row.status) == ("recipe", None, "missing")
        assert row.missing_sources == ["qiime2/alpha-rarefaction/faith_pd.csv"]

    def test_a_recipe_dc_whose_source_is_present(self, monkeypatch):
        row = self._row(self._preview(monkeypatch), "taxonomy_composition")
        assert (row.kind, row.status, row.matched, row.missing_sources) == ("recipe", "ok", 1, [])

    def test_a_pruned_optional_dc_gets_its_own_row(self, monkeypatch):
        without_tree = {
            rel: body
            for rel, body in MEGATEST_TREE.items()
            if rel != "qiime2/phylogenetic_tree/tree.nwk"
        }
        preview = self._preview(monkeypatch, tree=without_tree)
        assert preview.pruned_optional_dcs == ["phylogenetic_tree_canonical"]
        row = self._row(preview, "phylogenetic_tree_canonical")
        assert (row.status, row.optional, row.matched) == ("pruned", True, 0)

    def test_a_local_data_root_previews_the_same_way(self, tmp_path):
        from depictio.cli.cli.utils.template_preview import preview_data_root

        base = write_tree(tmp_path / "results", MEGATEST_TREE)
        preview = preview_data_root("nf-core/ampliseq/2.16.0", str(base))
        assert preview.data_root == str(base.absolute())
        by_tag = {row.tag: row for row in preview.data_collections}
        assert (by_tag["multiqc_data"].mode, by_tag["multiqc_data"].status) == ("recursive", "ok")
        assert by_tag["samplesheet"].status == "ok"
        assert by_tag["alpha_rarefaction"].missing_sources == [
            "qiime2/alpha-rarefaction/faith_pd.csv"
        ]


class TestPreviewRunScoping:
    """A `sequencing-runs` structure is counted per run, the way the scan walks it."""

    RUNS_TREE = {
        "run_1/qiime2/barplot/level-2.csv": b"a\n",
        "run_2/qiime2/barplot/level-2.csv": b"a\n",
        "logs/nextflow.log": b"noise\n",
    }

    def test_matches_are_summed_across_the_detected_runs(self, monkeypatch):
        from depictio.cli.cli.utils.template_preview import _preview_scan_dc

        root = s3_data_root(monkeypatch, self.RUNS_TREE)
        assert root.runs("run_.*") == ["run_1", "run_2"]
        dc_config = {
            "scan": {
                "mode": "recursive",
                "scan_parameters": {"regex_config": {"pattern": "level-2\\.csv"}},
            }
        }
        row = _preview_scan_dc("barplot", dc_config, root, ["run_1", "run_2"], False)
        assert (row.matched, row.status) == (2, "ok")
        # Without run scoping the same pattern still sees both, so the scoping is
        # what keeps a per-run count honest rather than what finds the files.
        assert _preview_scan_dc("barplot", dc_config, root, [], False).matched == 2

    def test_a_prefix_outside_the_root_is_not_reported_as_empty_data(self, monkeypatch):
        """An s3_prefix on another bucket is invisible to this root's listing."""
        from depictio.cli.cli.utils.template_preview import _preview_scan_dc

        root = s3_data_root(monkeypatch, self.RUNS_TREE)
        dc_config = {
            "scan": {
                "mode": "s3_prefix",
                "scan_parameters": {"prefix": "s3://elsewhere/run42/", "pattern": "*.csv"},
            }
        }
        row = _preview_scan_dc("foreign", dc_config, root, [], False)
        assert (row.status, row.matched, row.location) == ("ok", 0, "s3://elsewhere/run42/")

    def test_a_glob_pattern_is_translated_for_the_matcher(self, monkeypatch):
        """s3_prefix patterns are globs unless they say `pattern_syntax: regex`."""
        from depictio.cli.cli.utils.template_preview import _preview_scan_dc

        root = s3_data_root(monkeypatch, self.RUNS_TREE)
        dc_config = {
            "scan": {
                "mode": "s3_prefix",
                "scan_parameters": {"prefix": f"{S3_ROOT}/", "pattern": "*.csv"},
            }
        }
        assert _preview_scan_dc("globbed", dc_config, root, [], False).matched == 2
