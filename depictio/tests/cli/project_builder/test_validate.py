"""The rules an ad-hoc template keeps before a server resolves it."""

from __future__ import annotations

import copy

import pytest

from depictio.project_builder import validate
from depictio.project_builder.assemble import (
    DcDraft,
    GeoJSONProps,
    ImageProps,
    IndexedFileProps,
    MultiQCProps,
    PhylogenyProps,
    ProjectDraft,
    WorkflowDraft,
    build_template,
)
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.validate import INVALID, validate_inline_template

from ._fixtures import project, scan_dc, table_dc


def _good() -> dict:
    """A valid template: a single table and a recursive one."""
    return build_template(project(table_dc("sheet"), scan_dc("quant", max_depth=3)))


def _dc(template: dict, index: int = 0, workflow: int = 0) -> dict:
    return template["workflows"][workflow]["data_collections"][index]


def _refusal(template, *, remote: bool = False) -> BuilderRefused:
    with pytest.raises(BuilderRefused) as exc:
        validate_inline_template(template, remote=remote)
    assert (exc.value.status, exc.value.code) == (422, INVALID)
    assert INVALID == "inline_template_invalid"
    return exc.value


def _built(*dcs: DcDraft, **workflow) -> dict:
    return build_template(project(*dcs, **workflow))


def _geojson(tag: str = "areas", path: str = "regions/areas.geojson") -> DcDraft:
    return DcDraft(tag=tag, type="geojson", mode="single", path=path, props=GeoJSONProps())


def _phylogeny(tag: str = "tree", **props) -> DcDraft:
    return DcDraft(
        tag=tag, type="phylogeny", mode="single", path="t.nwk", props=PhylogenyProps(**props)
    )


def _image(tag: str = "imgs", **props) -> DcDraft:
    return DcDraft(
        tag=tag,
        type="image",
        mode="single",
        path="images.csv",
        props=ImageProps(image_column="img", **props),
    )


# ── what is accepted ─────────────────────────────────────────────────────────


class TestAccepted:
    def test_what_the_builder_produces_has_no_warning(self):
        assert validate_inline_template(_good(), remote=False) == []
        assert validate_inline_template(_good(), remote=True) == ["'quant': " + _bounds_note()]

    def test_the_template_is_not_changed_by_validating_it(self):
        template = _good()
        before = copy.deepcopy(template)
        validate_inline_template(template, remote=False)
        assert template == before

    def test_the_type_is_read_in_any_case(self):
        template = _good()
        _dc(template)["config"]["type"] = "table"
        _dc(template, 1)["config"]["type"] = "TABLE"
        assert validate_inline_template(template, remote=False) == []

    def test_a_scan_mode_is_read_in_any_case(self):
        template = _good()
        _dc(template)["config"]["scan"]["mode"] = "SINGLE"
        assert validate_inline_template(template, remote=False) == []

    def test_the_root_itself_is_a_location_for_a_folder_of_images(self):
        template = _built(_image(local_images_path="images"))
        _dc(template)["config"]["dc_specific_properties"]["local_images_path"] = "{DATA_ROOT}"
        assert len(validate_inline_template(template, remote=False)) == 1  # the s3_base_folder note

    def test_a_variable_list_may_be_left_out(self):
        template = _good()
        del template["template"]["variables"]
        assert validate_inline_template(template, remote=False) == []

    def test_a_workflow_may_share_its_name_with_a_tag(self):
        template = build_template(
            ProjectDraft(
                name="p",
                workflows=[
                    WorkflowDraft(name="sheet", data_collections=[table_dc("sheet")]),
                ],
            )
        )
        assert validate_inline_template(template, remote=False) == []

    def test_a_phylogeny_may_link_a_table_of_another_workflow(self):
        template = build_template(
            ProjectDraft(
                name="p",
                workflows=[
                    WorkflowDraft(name="a", data_collections=[table_dc("meta")]),
                    WorkflowDraft(name="b", data_collections=[_phylogeny(metadata_dc_tag="meta")]),
                ],
            )
        )
        assert validate_inline_template(template, remote=False) == []


def _bounds_note() -> str:
    return "max_depth and ignore apply to local folders only; an S3 prefix is listed whole."


# ── the shape of the whole template ──────────────────────────────────────────


class TestWholeTemplate:
    @pytest.mark.parametrize("value", [None, [], "template", 3, ("a",)])
    def test_it_must_be_a_mapping(self, value):
        assert "must be a mapping" in _refusal(value).detail

    def test_a_template_over_the_size_cap_is_refused(self):
        template = _good()
        template["description"] = "x" * (validate.MAX_TEMPLATE_BYTES + 1)
        assert f"larger than {validate.MAX_TEMPLATE_BYTES // 1024} KB" in _refusal(template).detail
        assert validate.MAX_TEMPLATE_BYTES == 256 * 1024

    def test_unknown_top_level_keys_are_named_in_order(self):
        template = _good()
        template["dashboards"] = ["x.yaml"]
        template["source"] = {"url": "https://example.org"}
        assert _refusal(template).detail == "Unexpected top-level keys: dashboards, source."

    @pytest.mark.parametrize("key", sorted(validate.TOP_LEVEL_KEYS - {"template", "workflows"}))
    def test_every_allowed_top_level_key_is_accepted(self, key):
        template = _good()
        template[key] = {"realtime": {"enabled": True}}.get(key, "x")
        if key == "is_public":
            template[key] = True
        validate_inline_template(template, remote=False)

    @pytest.mark.parametrize("section", [None, "custom/x", [], 3])
    def test_the_template_section_is_required(self, section):
        template = _good()
        template["template"] = section
        assert _refusal(template).detail == "The template section is missing."
        del template["template"]
        assert _refusal(template).detail == "The template section is missing."

    @pytest.mark.parametrize(
        "key", ["dashboards", "conditional", "provenance", "include", "recipes", "manifest"]
    )
    def test_the_template_section_declares_no_dashboards_or_conditionals(self, key):
        template = _good()
        template["template"][key] = [{"anything": 1}]
        detail = _refusal(template).detail
        assert "declares no dashboards, conditionals or provenance" in detail
        assert key in detail

    @pytest.mark.parametrize(
        "template_id",
        [
            None,
            "",
            "custom",
            "custom/",
            "nf-core/ampliseq/2.16.0",
            "other/my-run",
            "custom/My-Run",
            "custom/-leading",
            "custom/has space",
            "custom/under_score",
            "custom/a/b",
            "custom/../x",
            "../custom/x",
            "/custom/x",
            "custom/" + "a" * 65,
        ],
    )
    def test_the_template_id_must_be_custom_slash_a_slug(self, template_id):
        template = _good()
        template["template"]["template_id"] = template_id
        assert "template_id must look like 'custom/<name>'" in _refusal(template).detail

    @pytest.mark.parametrize("template_id", ["custom/a", "custom/my-run-2", "custom/" + "a" * 64])
    def test_a_well_formed_template_id_is_accepted(self, template_id):
        template = _good()
        template["template"]["template_id"] = template_id
        assert validate_inline_template(template, remote=False) == []

    @pytest.mark.parametrize(
        "variables",
        [
            [{"name": "SAMPLESHEET_FILE"}],
            [{"name": "DATA_ROOT"}, {"name": "GENOME"}],
            ["DATA_ROOT"],
        ],
    )
    def test_data_root_is_the_only_variable(self, variables):
        template = _good()
        template["template"]["variables"] = variables
        assert (
            _refusal(template).detail
            == "An inline template declares DATA_ROOT as its only variable."
        )

    def test_a_placeholder_other_than_data_root_is_refused(self):
        template = _good()
        _dc(template)["config"]["scan"]["scan_parameters"]["filename"] = "{DATA_ROOT}/{SAMPLE}.csv"
        assert _refusal(template).detail == "Unknown placeholders: {SAMPLE}."

    def test_placeholders_are_found_anywhere_outside_the_template_section(self):
        template = _good()
        template["name"] = "Run {RUN_ID} and {OTHER}"
        assert _refusal(template).detail == "Unknown placeholders: {OTHER}, {RUN_ID}."

    def test_a_regex_repetition_count_is_not_a_placeholder(self):
        template = _built(scan_dc(regex=r"^star/S\d{3}/quant\.tsv$"))
        assert validate_inline_template(template, remote=False) == []

    def test_nor_is_one_in_a_runs_regex(self):
        template = _built(scan_dc(), structure="sequencing-runs", runs_regex=r"^run_\d{4}$")
        assert validate_inline_template(template, remote=False) == []

    def test_a_repetition_range_is_never_mistaken_for_a_placeholder(self):
        template = _built(scan_dc(regex=r"^S\d{2,3}/quant\.tsv$"))
        assert validate_inline_template(template, remote=False) == []


# ── workflows ────────────────────────────────────────────────────────────────


class TestWorkflows:
    @pytest.mark.parametrize("workflows", [None, [], "main", {"name": "main"}])
    def test_at_least_one_workflow_in_a_list(self, workflows):
        template = _good()
        template["workflows"] = workflows
        assert _refusal(template).detail == "A project needs at least one workflow."

    def test_a_workflow_must_be_a_mapping(self):
        template = _good()
        template["workflows"] = ["main"]
        assert _refusal(template).detail == "Each workflow must be a mapping."

    def test_at_most_twenty_workflows(self):
        draft = ProjectDraft(
            name="many",
            workflows=[
                WorkflowDraft(name=f"wf{i}", data_collections=[table_dc(f"t{i}")])
                for i in range(validate.MAX_WORKFLOWS + 1)
            ],
        )
        assert _refusal(build_template(draft)).detail == "At most 20 workflows."
        draft.workflows.pop()
        assert validate_inline_template(build_template(draft), remote=False) == []

    def test_unknown_workflow_keys_are_named(self):
        template = _good()
        template["workflows"][0]["steps"] = []
        template["workflows"][0]["hooks"] = []
        assert _refusal(template).detail == "Unexpected workflow keys: hooks, steps."

    @pytest.mark.parametrize("name", [None, "", "   "])
    def test_every_workflow_needs_a_name(self, name):
        template = _good()
        template["workflows"][0]["name"] = name
        assert _refusal(template).detail == "Every workflow needs a name."

    def test_workflow_names_are_unique(self):
        template = build_template(
            ProjectDraft(
                name="p",
                workflows=[
                    WorkflowDraft(name="main", data_collections=[table_dc("a")]),
                    WorkflowDraft(name="main", data_collections=[table_dc("b")]),
                ],
            )
        )
        detail = _refusal(template).detail
        assert "Two workflows are named 'main'" in detail

    def test_a_workflow_needs_at_least_one_collection(self):
        template = build_template(ProjectDraft(name="p", workflows=[WorkflowDraft(name="empty")]))
        assert _refusal(template).detail == "Workflow 'empty' needs at least one data collection."

    def test_tags_are_unique_across_workflows(self):
        template = build_template(
            ProjectDraft(
                name="p",
                workflows=[
                    WorkflowDraft(name="first", data_collections=[table_dc("sheet")]),
                    WorkflowDraft(name="second", data_collections=[table_dc("sheet")]),
                ],
            )
        )
        detail = _refusal(template).detail
        assert "'sheet'" in detail and "'first'" in detail and "'second'" in detail
        assert "unique in the project" in detail

    def test_tags_are_unique_within_a_workflow_too(self):
        detail = _refusal(_built(table_dc("sheet"), scan_dc("sheet"))).detail
        assert "The tag 'sheet'" in detail

    @pytest.mark.parametrize(
        "location",
        [
            {"locations": ["/data/run1"]},
            {"locations": ["{DATA_ROOT}", "/data/run2"]},
            {"locations": []},
            {"locations": "{DATA_ROOT}"},
            {},
            {"locations": ["{DATA_ROOT}"], "attached_locations": ["/data/other"]},
        ],
    )
    def test_a_workflow_reads_the_data_root_only(self, location):
        template = _good()
        template["workflows"][0]["data_location"] = {"structure": "flat", **location}
        assert _refusal(template).detail == "Workflow 'main' reads {DATA_ROOT} only."

    @pytest.mark.parametrize("structure", [None, "nested", "Flat"])
    def test_the_structure_is_flat_or_sequencing_runs(self, structure):
        template = _good()
        template["workflows"][0]["data_location"]["structure"] = structure
        assert "structure must be flat or sequencing-runs" in _refusal(template).detail

    def test_sequencing_runs_need_a_runs_regex(self):
        template = _built(scan_dc(), structure="sequencing-runs")
        assert _refusal(template).detail == "Workflow 'main': sequencing runs need a runs regex."

    def test_the_runs_regex_must_compile(self):
        template = _built(scan_dc(), structure="sequencing-runs", runs_regex="run_(")
        detail = _refusal(template).detail
        assert "Workflow 'main' runs regex" in detail and "invalid regex" in detail

    def test_a_good_runs_regex_is_accepted(self):
        template = _built(scan_dc(), structure="sequencing-runs", runs_regex=r"^run_\d+$")
        assert validate_inline_template(template, remote=False) == []

    def test_at_most_two_hundred_collections_in_all(self):
        cap = validate.MAX_DATA_COLLECTIONS
        draft = ProjectDraft(
            name="big",
            workflows=[
                WorkflowDraft(
                    name=f"wf{w}",
                    data_collections=[table_dc(f"t{w}_{i}") for i in range(cap // 2)],
                )
                for w in range(2)
            ],
        )
        assert validate_inline_template(build_template(draft), remote=False) == []
        draft.workflows[1].data_collections.append(table_dc("one_too_many"))
        assert _refusal(build_template(draft)).detail == "At most 200 data collections."


# ── data collections ─────────────────────────────────────────────────────────


class TestDataCollections:
    def test_a_collection_must_be_a_mapping_with_known_keys(self):
        template = _good()
        template["workflows"][0]["data_collections"] = ["sheet"]
        assert "unexpected data collection keys" in _refusal(template).detail
        template = _good()
        _dc(template)["source"] = "https://example.org/a.csv"
        assert "unexpected data collection keys" in _refusal(template).detail

    @pytest.mark.parametrize("tag", [None, "", "  "])
    def test_a_collection_needs_a_tag(self, tag):
        template = _good()
        _dc(template)["data_collection_tag"] = tag
        assert "every data collection needs a tag" in _refusal(template).detail

    @pytest.mark.parametrize("key", ["source", "join", "transform", "recipe", "url", "tags"])
    def test_the_config_has_no_source_join_or_transform(self, key):
        template = _good()
        _dc(template)["config"][key] = {"anything": 1}
        assert "unexpected config keys (no source, join or transform)" in _refusal(template).detail

    @pytest.mark.parametrize("config", [None, [], "Table"])
    def test_the_config_must_be_a_mapping(self, config):
        template = _good()
        _dc(template)["config"] = config
        assert "unexpected config keys" in _refusal(template).detail

    @pytest.mark.parametrize("dc_type", [None, "", "Delta", "recipe", "manifest", "joined"])
    def test_an_unsupported_type_is_named(self, dc_type):
        template = _good()
        _dc(template)["config"]["type"] = dc_type
        assert "unsupported type" in _refusal(template).detail

    def test_every_type_the_builder_authors_is_supported(self):
        assert set(validate.TYPES) == {
            "table",
            "multiqc",
            "image",
            "indexed_file",
            "geojson",
            "phylogeny",
        }

    def test_an_optional_collection_stays_optional(self):
        template = _built(table_dc("sheet", optional=True))
        assert _dc(template)["optional"] is True
        assert validate_inline_template(template, remote=False) == []


# ── scans ────────────────────────────────────────────────────────────────────


class TestScans:
    def test_a_scan_block_is_required(self):
        template = _good()
        del _dc(template)["config"]["scan"]
        assert "a scan block is required" in _refusal(template).detail

    @pytest.mark.parametrize("mode", [None, "", "url", "s3_prefix", "manifest", "glob"])
    def test_the_mode_is_single_or_recursive(self, mode):
        template = _good()
        _dc(template)["config"]["scan"]["mode"] = mode
        assert "scan mode must be single or recursive" in _refusal(template).detail

    @pytest.mark.parametrize(
        "filename",
        [
            "/etc/passwd",
            "samplesheet.csv",
            "s3://bucket/key.csv",
            "https://example.org/a.csv",
            "{DATA_ROOT}x/a.csv",
            "~/a.csv",
            None,
            "",
            3,
        ],
    )
    def test_a_single_file_is_under_the_data_root(self, filename):
        template = _good()
        _dc(template)["config"]["scan"]["scan_parameters"]["filename"] = filename
        assert "filename must be a path under {DATA_ROOT}" in _refusal(template).detail

    @pytest.mark.parametrize(
        "filename", ["{DATA_ROOT}/../x", "{DATA_ROOT}/a/../../x", "{DATA_ROOT}/a/.."]
    )
    def test_a_single_file_may_not_climb_out_of_the_root(self, filename):
        template = _good()
        _dc(template)["config"]["scan"]["scan_parameters"]["filename"] = filename
        assert "may not contain '..'" in _refusal(template).detail

    def test_a_dotted_name_is_not_a_climb(self):
        template = _good()
        _dc(template)["config"]["scan"]["scan_parameters"]["filename"] = "{DATA_ROOT}/a..b/c.csv"
        assert validate_inline_template(template, remote=False) == []

    def test_a_single_file_scan_cannot_name_the_root_folder_itself(self):
        template = _good()
        _dc(template)["config"]["scan"]["scan_parameters"]["filename"] = "{DATA_ROOT}"
        with pytest.raises(BuilderRefused):
            validate_inline_template(template, remote=False)

    def test_a_single_scan_takes_a_filename_only(self):
        template = _good()
        _dc(template)["config"]["scan"]["scan_parameters"]["regex_config"] = {"pattern": ".*"}
        assert "a single-file scan takes a filename only" in _refusal(template).detail

    def test_a_recursive_scan_takes_known_parameters_only(self):
        template = _good()
        parameters = _dc(template, 1)["config"]["scan"]["scan_parameters"]
        parameters["follow_symlinks"] = True
        assert "unknown recursive scan parameters" in _refusal(template).detail

    def test_the_regex_config_takes_a_pattern_only(self):
        template = _good()
        _dc(template, 1)["config"]["scan"]["scan_parameters"]["regex_config"]["wildcards"] = []
        assert "wildcards are not supported here" in _refusal(template).detail

    @pytest.mark.parametrize("pattern", [None, "", 3, ["a"]])
    def test_a_recursive_scan_needs_a_regex(self, pattern):
        template = _good()
        _dc(template, 1)["config"]["scan"]["scan_parameters"]["regex_config"]["pattern"] = pattern
        assert "a recursive scan needs a regex" in _refusal(template).detail

    def test_a_recursive_scan_with_no_regex_config_needs_one(self):
        template = _good()
        del _dc(template, 1)["config"]["scan"]["scan_parameters"]["regex_config"]
        assert "a recursive scan needs a regex" in _refusal(template).detail

    @pytest.mark.parametrize("pattern", ["(", "[a-", "*quant", "(?P<x"])
    def test_the_regex_must_compile(self, pattern):
        template = _built(scan_dc(regex=pattern))
        assert "invalid regex" in _refusal(template).detail

    def test_the_message_names_the_collection_at_fault(self):
        template = _built(table_dc("sheet"), scan_dc("quant", regex="("))
        assert _refusal(template).detail.startswith("'quant': invalid regex")

    @pytest.mark.parametrize("make", [_geojson, _phylogeny])
    def test_one_file_types_cannot_be_scanned_recursively(self, make):
        template = _built(make())
        scan = _dc(template)["config"]["scan"]
        scan["mode"] = "recursive"
        scan["scan_parameters"] = {"regex_config": {"pattern": r"\.nwk$"}}
        detail = _refusal(template).detail
        assert "reads one file (single scan)" in detail

    def test_a_geojson_or_phylogeny_can_be_a_single_file(self):
        template = _built(_geojson(), _phylogeny())
        assert validate_inline_template(template, remote=False) == []

    def test_recursive_multiqc_and_single_multiqc_are_both_fine(self):
        template = _built(
            DcDraft(
                tag="a",
                type="multiqc",
                mode="recursive",
                regex=r"multiqc\.parquet$",
                props=MultiQCProps(),
            ),
            DcDraft(
                tag="b",
                type="multiqc",
                mode="single",
                path="m/multiqc.parquet",
                props=MultiQCProps(),
            ),
        )
        assert validate_inline_template(template, remote=False) == []


# ── remote roots ─────────────────────────────────────────────────────────────


class TestRemote:
    def test_indexed_files_cannot_be_read_from_a_prefix(self):
        template = _built(
            DcDraft(
                tag="vcf",
                type="indexed_file",
                mode="recursive",
                regex=r"\.vcf\.gz$",
                props=IndexedFileProps(),
            )
        )
        assert validate_inline_template(template, remote=False) == []
        detail = _refusal(template, remote=True).detail
        assert detail.startswith("'vcf': Indexed files can't be read from an S3 prefix yet")

    def test_images_cannot_be_uploaded_from_a_prefix(self):
        template = _built(_image(local_images_path="images"))
        assert len(validate_inline_template(template, remote=False)) == 1
        detail = _refusal(template, remote=True).detail
        assert detail.startswith("'imgs': Images are uploaded from a folder on this computer")

    def test_an_image_collection_without_an_upload_is_refused_on_a_prefix_as_well(self):
        template = _built(_image())
        assert "Images are uploaded" in _refusal(template, remote=True).detail

    def test_the_refusal_comes_before_the_scan_is_read(self):
        """An image on a prefix is refused whatever else is wrong with it."""
        template = _built(_image())
        _dc(template)["config"]["scan"]["mode"] = "bogus"
        assert "Images are uploaded" in _refusal(template, remote=True).detail
        assert "scan mode" in _refusal(template, remote=False).detail

    def test_the_remote_types_are_the_two_that_need_a_local_disk(self):
        assert set(validate.REMOTE_REFUSED_TYPES) == {"indexed_file", "image"}

    @pytest.mark.parametrize(
        "bounds",
        [
            {"max_depth": 2},
            {"ignore": ["work"]},
            {"max_depth": 0},
            {"max_depth": 2, "ignore": ["w"]},
        ],
    )
    def test_bounds_on_a_prefix_are_a_warning(self, bounds):
        template = _built(scan_dc("quant", **bounds))
        assert validate_inline_template(template, remote=False) == []
        assert validate_inline_template(template, remote=True) == ["'quant': " + _bounds_note()]

    def test_no_bounds_no_warning(self):
        assert validate_inline_template(_built(scan_dc()), remote=True) == []

    def test_a_single_file_has_no_bounds_to_warn_about(self):
        assert validate_inline_template(_built(table_dc()), remote=True) == []

    def test_one_warning_per_collection_in_order(self):
        template = _built(scan_dc("a", max_depth=1), scan_dc("b", ignore=["x"]))
        warnings = validate_inline_template(template, remote=True)
        assert [w.split(":")[0] for w in warnings] == ["'a'", "'b'"]


# ── properties ───────────────────────────────────────────────────────────────


class TestProperties:
    def test_properties_must_be_a_mapping(self):
        template = _good()
        _dc(template)["config"]["dc_specific_properties"] = ["format"]
        assert "dc_specific_properties must be a mapping" in _refusal(template).detail

    def test_properties_may_be_left_out_where_the_type_needs_none(self):
        template = _built(
            DcDraft(
                tag="m",
                type="multiqc",
                mode="recursive",
                regex=r"multiqc\.parquet$",
                props=MultiQCProps(),
            )
        )
        del _dc(template)["config"]["dc_specific_properties"]
        assert validate_inline_template(template, remote=False) == []

    @pytest.mark.parametrize(
        ("properties", "field"),
        [({"format": "csv", "bogus": 1}, "bogus"), ({}, "format")],
    )
    def test_a_property_the_model_refuses_is_named_with_its_field(self, properties, field):
        template = _good()
        _dc(template)["config"]["dc_specific_properties"] = properties
        detail = _refusal(template).detail
        assert detail.startswith("'sheet': ") and field in detail

    def test_the_wrong_kind_of_property_for_the_type_is_refused(self):
        template = _built(_geojson())
        _dc(template)["config"]["dc_specific_properties"] = {"feature_id_key": 3}
        detail = _refusal(template).detail
        assert detail.startswith("'areas': feature_id_key:")

    def test_an_indexed_format_outside_the_supported_ones_is_refused(self):
        template = _built(
            DcDraft(
                tag="c",
                type="indexed_file",
                mode="recursive",
                regex=r"\.cram$",
                props=IndexedFileProps(format="vcf"),
            )
        )
        _dc(template)["config"]["dc_specific_properties"]["format"] = "cram"
        assert "format" in _refusal(template).detail

    def test_an_image_needs_its_column(self):
        template = _built(_image())
        del _dc(template)["config"]["dc_specific_properties"]["image_column"]
        assert "image_column" in _refusal(template).detail

    @pytest.mark.parametrize(
        "path", ["/home/me/images", "images", "s3://bucket/images", "{DATA_ROOT}/../images"]
    )
    def test_the_image_folder_is_under_the_data_root(self, path):
        template = _built(_image())
        _dc(template)["config"]["dc_specific_properties"]["local_images_path"] = path
        assert "local_images_path" in _refusal(template).detail

    def test_an_image_folder_under_the_root_is_accepted(self):
        template = _built(_image(local_images_path="images/pngs"))
        assert _dc(template)["config"]["dc_specific_properties"]["local_images_path"] == (
            "{DATA_ROOT}/images/pngs"
        )
        assert len(validate_inline_template(template, remote=False)) == 1  # the s3_base_folder note

    def test_a_missing_bucket_folder_is_advice_not_a_refusal(self):
        template = _built(_image(local_images_path="images"))
        (warning,) = validate_inline_template(template, remote=False)
        assert warning.startswith("'imgs': no s3_base_folder.")
        assert "depictio ingest" in warning

    def test_an_image_with_its_bucket_folder_has_no_warning(self):
        template = _built(_image(local_images_path="images", s3_base_folder="s3://bkt/imgs"))
        assert validate_inline_template(template, remote=False) == []

    def test_an_empty_bucket_folder_counts_as_missing(self):
        template = _built(_image(local_images_path="images"))
        _dc(template)["config"]["dc_specific_properties"]["s3_base_folder"] = ""
        assert len(validate_inline_template(template, remote=False)) == 1


# ── phylogeny links ──────────────────────────────────────────────────────────


class TestPhylogenyLinks:
    def test_the_metadata_collection_must_exist(self):
        template = _built(table_dc("sheet"), _phylogeny(metadata_dc_tag="nope"))
        detail = _refusal(template).detail
        assert "'tree'" in detail and "metadata_dc_tag 'nope'" in detail
        assert "not a table collection of the project" in detail

    @pytest.mark.parametrize(
        "other",
        [
            _geojson("meta"),
            DcDraft(
                tag="meta",
                type="multiqc",
                mode="recursive",
                regex=r"m\.parquet$",
                props=MultiQCProps(),
            ),
            DcDraft(
                tag="meta",
                type="indexed_file",
                mode="recursive",
                regex=r"\.vcf\.gz$",
                props=IndexedFileProps(),
            ),
        ],
        ids=["geojson", "multiqc", "indexed_file"],
    )
    def test_it_must_be_a_table(self, other):
        template = _built(other, _phylogeny(metadata_dc_tag="meta"))
        assert "not a table collection of the project" in _refusal(template).detail

    def test_it_may_be_declared_after_the_phylogeny(self):
        template = _built(_phylogeny(metadata_dc_tag="sheet"), table_dc("sheet"))
        assert validate_inline_template(template, remote=False) == []

    def test_no_link_is_fine(self):
        assert validate_inline_template(_built(_phylogeny()), remote=False) == []

    def test_a_table_of_the_same_name_in_another_type_does_not_count(self):
        template = _built(_phylogeny(metadata_dc_tag="areas"), _geojson("areas"))
        assert "not a table collection" in _refusal(template).detail


def test_every_kind_of_draft_props_passes_the_models_validation_checks_them_with():
    for dc in (
        table_dc("sheet"),
        _image(local_images_path="images"),
        _phylogeny(metadata_dc_tag="sheet"),
        _geojson(),
    ):
        template = _built(table_dc("sheet"), dc) if dc.tag != "sheet" else _built(dc)
        validate_inline_template(template, remote=False)
