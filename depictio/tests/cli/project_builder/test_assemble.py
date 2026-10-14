"""The draft the SPA keeps, and the ``{DATA_ROOT}`` template it becomes."""

from __future__ import annotations

import re

import pytest
import yaml
from pydantic import ValidationError

from depictio.project_builder import assemble
from depictio.project_builder.assemble import (
    CatalogRef,
    DcDraft,
    GeoJSONProps,
    ImageProps,
    IndexedFileProps,
    MultiQCProps,
    PhylogenyProps,
    ProjectDraft,
    TableProps,
    WorkflowDraft,
    build_template,
    dc_config,
    exact_path_regex,
    scan_block,
    template_id_for,
    template_yaml,
    under_root,
    workflow_block,
)
from depictio.project_builder.validate import validate_inline_template

from ._fixtures import project, scan_dc, table_dc

# ── the draft ────────────────────────────────────────────────────────────────


class TestDraftModels:
    def test_a_draft_comes_off_the_wire_with_props_chosen_by_kind(self):
        draft = ProjectDraft.model_validate(
            {
                "name": "Lab QC",
                "workflows": [
                    {
                        "name": "main",
                        "data_collections": [
                            {
                                "tag": "sheet",
                                "type": "table",
                                "mode": "single",
                                "path": "samplesheet.csv",
                                "props": {"kind": "table", "format": "csv", "separator": ","},
                            },
                            {
                                "tag": "tree",
                                "type": "phylogeny",
                                "mode": "single",
                                "path": "tree.nwk",
                                "props": {"kind": "phylogeny", "metadata_dc_tag": "sheet"},
                            },
                        ],
                    }
                ],
            }
        )
        sheet, tree = draft.workflows[0].data_collections
        assert isinstance(sheet.props, TableProps)
        assert isinstance(tree.props, PhylogenyProps)
        assert tree.props.format == "newick" and tree.props.ladderize is True

    def test_props_without_a_kind_are_refused(self):
        with pytest.raises(ValidationError):
            DcDraft.model_validate(
                {"tag": "x", "type": "table", "mode": "single", "props": {"format": "csv"}}
            )

    def test_an_unknown_kind_is_refused(self):
        with pytest.raises(ValidationError):
            DcDraft.model_validate(
                {"tag": "x", "type": "table", "mode": "single", "props": {"kind": "nope"}}
            )

    def test_a_property_of_another_kind_is_refused(self):
        with pytest.raises(ValidationError):
            DcDraft.model_validate(
                {
                    "tag": "x",
                    "type": "table",
                    "mode": "single",
                    "props": {"kind": "table", "ladderize": True},
                }
            )

    @pytest.mark.parametrize(
        "fields",
        [
            {"tag": ""},
            {"tag": "x" * 129},
            {"type": "spreadsheet"},
            {"mode": "glob"},
            {"max_depth": -1},
            {"unexpected": 1},
        ],
    )
    def test_a_data_collection_the_builder_cannot_author_is_refused(self, fields):
        base = {"tag": "x", "type": "table", "mode": "single", "props": TableProps()}
        with pytest.raises(ValidationError):
            DcDraft(**{**base, **fields})

    @pytest.mark.parametrize(
        "make",
        [
            lambda: ProjectDraft(name=""),
            lambda: ProjectDraft(name="x" * 201),
            lambda: ProjectDraft(name="ok", extra_field=1),
            lambda: WorkflowDraft(name=""),
            lambda: WorkflowDraft(name="w", structure="nested"),
            lambda: WorkflowDraft(name="w", catalog={"name": "bioconda", "url": "https://x"}),
            lambda: ImageProps(),  # image_column is required
            lambda: PhylogenyProps(format="phyloxml"),
            lambda: PhylogenyProps(tip_label_strategy="whole_label"),
        ],
    )
    def test_the_rest_of_the_draft_is_as_strict(self, make):
        with pytest.raises(ValidationError):
            make()

    def test_defaults(self):
        draft = ProjectDraft(name="p")
        assert (draft.is_public, draft.realtime, draft.workflows) == (False, False, [])
        workflow = WorkflowDraft(name="w")
        assert (workflow.engine, workflow.structure) == ("python", "flat")
        dc = table_dc()
        assert (dc.optional, dc.ignore, dc.max_depth) == (False, [], None)
        assert GeoJSONProps().feature_id_key == "id"
        assert IndexedFileProps().format == "vcf"

    def test_a_catalog_reference_is_one_of_the_three_catalogs(self):
        for name in ("nf-core", "workflowhub", "smk-wf-catalog"):
            assert CatalogRef(name=name, url="https://example.org").name == name


# ── small pure helpers ───────────────────────────────────────────────────────


class TestHelpers:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("My Run", "custom/my-run"),
            ("Lab  QC!!", "custom/lab-qc"),
            ("snake_case_name", "custom/snake-case-name"),
            ("RNA-seq 2026", "custom/rna-seq-2026"),
            ("Café", "custom/caf"),
            ("!!!", "custom/x"),
        ],
    )
    def test_template_id_for(self, name, expected):
        assert template_id_for(name) == expected

    def test_a_long_name_stays_within_what_validation_accepts(self):
        template_id = template_id_for("a" * 200)
        assert len(template_id.split("/", 1)[1]) <= 64
        draft = project(table_dc(), name="a" * 200)
        assert validate_inline_template(build_template(draft), remote=False) == []

    @pytest.mark.parametrize(
        ("rel", "expected"),
        [
            (None, "{DATA_ROOT}"),
            ("", "{DATA_ROOT}"),
            ("/", "{DATA_ROOT}"),
            ("a/b.csv", "{DATA_ROOT}/a/b.csv"),
            ("/a/b/", "{DATA_ROOT}/a/b"),
        ],
    )
    def test_under_root(self, rel, expected):
        assert under_root(rel) == expected

    def test_exact_path_regex_matches_that_path_alone(self):
        regex = re.compile(exact_path_regex("/out (1)/a.b+c.tsv"))
        assert regex.pattern == "^" + re.escape("out (1)/a.b+c.tsv") + "$"
        assert regex.match("out (1)/a.b+c.tsv")
        for other in ("out (1)/aXb+c.tsv", "x/out (1)/a.b+c.tsv", "out (1)/a.b+c.tsv.bak"):
            assert not regex.match(other)


# ── the scan block ───────────────────────────────────────────────────────────


class TestScanBlock:
    def test_a_single_file_is_scanned_by_name_under_the_root(self):
        assert scan_block(table_dc(path="input/samplesheet.csv")) == {
            "mode": "single",
            "scan_parameters": {"filename": "{DATA_ROOT}/input/samplesheet.csv"},
        }

    def test_a_recursive_scan_carries_its_regex_and_bounds(self):
        dc = scan_dc(regex=r"^quant\.tsv$", max_depth=3, ignore=["work", "*.tmp"])
        assert scan_block(dc) == {
            "mode": "recursive",
            "scan_parameters": {
                "regex_config": {"pattern": r"^quant\.tsv$"},
                "max_depth": 3,
                "ignore": ["work", "*.tmp"],
            },
        }

    def test_bounds_not_set_are_left_out_but_a_depth_of_zero_is_a_bound(self):
        assert scan_block(scan_dc())["scan_parameters"] == {
            "regex_config": {"pattern": r"^quant\.tsv$"}
        }
        assert scan_block(scan_dc(max_depth=0))["scan_parameters"]["max_depth"] == 0

    def test_a_recursive_scan_with_a_path_and_no_regex_matches_exactly_that_path(self):
        dc = DcDraft(
            tag="t", type="table", mode="recursive", path="star/S1/quant.tsv", props=TableProps()
        )
        assert scan_block(dc)["scan_parameters"]["regex_config"]["pattern"] == exact_path_regex(
            "star/S1/quant.tsv"
        )

    def test_the_regex_wins_over_the_path(self):
        dc = scan_dc(regex=r"^a$", path="b.tsv")
        assert scan_block(dc)["scan_parameters"]["regex_config"]["pattern"] == "^a$"

    def test_multiqc_is_always_walked_so_a_picked_parquet_becomes_an_exact_regex(self):
        rel = "multiqc/multiqc_data/multiqc.parquet"
        dc = DcDraft(tag="mqc", type="multiqc", mode="single", path=rel, props=MultiQCProps())
        assert scan_block(dc) == {
            "mode": "recursive",
            "scan_parameters": {"regex_config": {"pattern": exact_path_regex(rel)}},
        }

    def test_the_ignore_list_is_a_copy(self):
        dc = scan_dc(ignore=["work"])
        scan_block(dc)["scan_parameters"]["ignore"].append("more")
        assert dc.ignore == ["work"]


# ── one data collection per type ─────────────────────────────────────────────


class TestDcConfig:
    def test_a_single_table_is_metadata(self):
        assert dc_config(table_dc(path="samplesheet.csv")) == {
            "type": "Table",
            "metatype": "Metadata",
            "scan": {
                "mode": "single",
                "scan_parameters": {"filename": "{DATA_ROOT}/samplesheet.csv"},
            },
            "dc_specific_properties": {"format": "csv", "polars_kwargs": {"separator": ","}},
        }

    def test_a_recursive_table_is_an_aggregate(self):
        config = dc_config(scan_dc())
        assert (config["type"], config["metatype"]) == ("Table", "Aggregate")
        assert config["scan"]["mode"] == "recursive"
        assert config["dc_specific_properties"] == {
            "format": "tsv",
            "polars_kwargs": {"separator": "\t"},
        }

    def test_the_separator_matters_for_text_tables_only(self):
        parquet = DcDraft(
            tag="p",
            type="table",
            mode="single",
            path="a.parquet",
            props=TableProps(format="parquet", separator=","),
        )
        assert dc_config(parquet)["dc_specific_properties"] == {"format": "parquet"}
        no_separator = DcDraft(
            tag="t", type="table", mode="single", path="a.csv", props=TableProps(format="csv")
        )
        assert dc_config(no_separator)["dc_specific_properties"] == {"format": "csv"}

    def test_column_descriptions_ride_along_as_a_copy(self):
        props = TableProps(format="csv", columns_description={"sample": "Sample id"})
        dc = DcDraft(tag="t", type="table", mode="single", path="a.csv", props=props)
        properties = dc_config(dc)["dc_specific_properties"]
        assert properties["columns_description"] == {"sample": "Sample id"}
        properties["columns_description"]["sample"] = "changed"
        assert props.columns_description == {"sample": "Sample id"}

    def test_multiqc_has_no_properties_and_no_metatype(self):
        dc = DcDraft(
            tag="mqc",
            type="multiqc",
            mode="recursive",
            regex=r"multiqc\.parquet$",
            props=MultiQCProps(),
        )
        config = dc_config(dc)
        assert config["type"] == "MultiQC"
        assert config["dc_specific_properties"] == {}
        assert "metatype" not in config
        assert config["scan"]["mode"] == "recursive"

    def test_an_image_collection_uploads_a_folder_under_the_root(self):
        dc = DcDraft(
            tag="imgs",
            type="image",
            mode="single",
            path="images.csv",
            props=ImageProps(image_column="img", local_images_path="images/"),
        )
        config = dc_config(dc)
        assert config["type"] == "image"
        assert config["scan"]["scan_parameters"]["filename"] == "{DATA_ROOT}/images.csv"
        assert config["dc_specific_properties"] == {
            "format": "csv",
            "image_column": "img",
            "local_images_path": "{DATA_ROOT}/images",
        }

    def test_an_image_collection_keeps_the_bucket_folder_it_was_given(self):
        props = ImageProps(
            image_column="img", format="tsv", separator="\t", s3_base_folder="s3://bucket/imgs"
        )
        dc = DcDraft(tag="imgs", type="image", mode="single", path="images.tsv", props=props)
        assert dc_config(dc)["dc_specific_properties"] == {
            "format": "tsv",
            "polars_kwargs": {"separator": "\t"},
            "image_column": "img",
            "s3_base_folder": "s3://bucket/imgs",
        }

    def test_an_indexed_file_collection_keeps_what_was_set(self):
        scan = dict(tag="v", type="indexed_file", mode="recursive", regex=r"\.vcf\.gz$")
        bare = DcDraft(props=IndexedFileProps(), **scan)
        config = dc_config(bare)
        assert (config["type"], config["metatype"]) == ("indexed_file", "Metadata")
        assert config["dc_specific_properties"] == {"format": "vcf"}

        full = DcDraft(
            props=IndexedFileProps(
                format="vcf",
                index_suffix=".csi",
                sample_regex=r"^(S\d+)",
                sample_col="sample",
                assembly="hg38",
                max_file_size_mb=500,
            ),
            **scan,
        )
        assert dc_config(full)["dc_specific_properties"] == {
            "format": "vcf",
            "index_suffix": ".csi",
            "sample_regex": r"^(S\d+)",
            "sample_col": "sample",
            "assembly": "hg38",
            "max_file_size_mb": 500,
        }

    def test_an_empty_index_suffix_is_kept(self):
        """'' means "no index file", which is not the same as not saying."""
        dc = DcDraft(
            tag="v",
            type="indexed_file",
            mode="recursive",
            regex=r"\.bw$",
            props=IndexedFileProps(format="bigwig", index_suffix=""),
        )
        assert dc_config(dc)["dc_specific_properties"]["index_suffix"] == ""

    def test_a_geojson_collection_names_its_feature_id(self):
        dc = DcDraft(
            tag="areas",
            type="geojson",
            mode="single",
            path="regions/areas.geojson",
            props=GeoJSONProps(feature_id_key="code"),
        )
        assert dc_config(dc) == {
            "type": "geojson",
            "metatype": "GeoJSON",
            "scan": {
                "mode": "single",
                "scan_parameters": {"filename": "{DATA_ROOT}/regions/areas.geojson"},
            },
            "dc_specific_properties": {"feature_id_key": "code"},
        }

    def test_a_phylogeny_collection_links_its_metadata_table(self):
        props = PhylogenyProps(
            format="nexus",
            ladderize=False,
            metadata_dc_tag="sheet",
            metadata_taxon_column="sample",
            tip_label_strategy="first_token",
        )
        dc = DcDraft(tag="tree", type="phylogeny", mode="single", path="t.nex", props=props)
        config = dc_config(dc)
        assert (config["type"], config["metatype"]) == ("phylogeny", "Aggregate")
        assert config["dc_specific_properties"] == {
            "format": "nexus",
            "ladderize": False,
            "metadata_dc_tag": "sheet",
            "metadata_taxon_column": "sample",
            "tip_label_strategy": "first_token",
        }

    def test_a_phylogeny_collection_without_links_keeps_only_what_is_set(self):
        dc = DcDraft(
            tag="tree", type="phylogeny", mode="single", path="t.nwk", props=PhylogenyProps()
        )
        assert dc_config(dc)["dc_specific_properties"] == {"format": "newick", "ladderize": True}

    def test_the_entry_has_a_tag_and_only_the_flags_that_are_set(self):
        entry = assemble.data_collection(table_dc("sheet"))
        assert list(entry) == ["data_collection_tag", "config"]
        flagged = assemble.data_collection(
            table_dc("sheet", description="The samples", optional=True)
        )
        assert list(flagged) == ["data_collection_tag", "description", "optional", "config"]
        assert (flagged["description"], flagged["optional"]) == ("The samples", True)


# ── workflows and the template ───────────────────────────────────────────────


class TestWorkflowBlock:
    def test_a_flat_workflow_reads_the_root(self):
        block = workflow_block(WorkflowDraft(name="main", data_collections=[table_dc()]))
        assert block["name"] == "main"
        assert block["engine"] == {"name": "python"}
        assert block["data_location"] == {"structure": "flat", "locations": ["{DATA_ROOT}"]}
        assert [dc["data_collection_tag"] for dc in block["data_collections"]] == ["sheet"]
        assert not {"version", "repository_url", "catalog"} & set(block)

    def test_sequencing_runs_carry_their_regex(self):
        block = workflow_block(
            WorkflowDraft(name="w", structure="sequencing-runs", runs_regex=r"^run_\d+$")
        )
        assert block["data_location"] == {
            "structure": "sequencing-runs",
            "locations": ["{DATA_ROOT}"],
            "runs_regex": r"^run_\d+$",
        }

    def test_sequencing_runs_without_a_regex_write_an_empty_one_for_validation_to_refuse(self):
        block = workflow_block(WorkflowDraft(name="w", structure="sequencing-runs"))
        assert block["data_location"]["runs_regex"] == ""

    def test_the_engine_is_normalised_and_provenance_is_kept(self):
        block = workflow_block(
            WorkflowDraft(
                name="w",
                engine="  Nextflow ",
                engine_version="24.04.2",
                version="3.14.0",
                repository_url="https://github.com/nf-core/rnaseq",
                catalog=CatalogRef(name="nf-core", url="https://github.com/nf-core/rnaseq"),
            )
        )
        assert block["engine"] == {"name": "nextflow", "version": "24.04.2"}
        assert block["version"] == "3.14.0"
        assert block["repository_url"] == "https://github.com/nf-core/rnaseq"
        assert block["catalog"] == {"name": "nf-core", "url": "https://github.com/nf-core/rnaseq"}


class TestBuildTemplate:
    def test_the_template_section_names_the_root_as_its_one_variable(self):
        template = build_template(project(table_dc(), name="My Run"))
        assert list(template)[0] == "template"
        assert template["template"] == {
            "template_id": "custom/my-run",
            "description": "My Run, defined with the Project Builder",
            "version": "1",
            "variables": [
                {
                    "name": "DATA_ROOT",
                    "description": "The folder or s3:// prefix the collections are read from",
                    "required": True,
                }
            ],
        }
        assert template["name"] == "My Run"
        assert template["project_type"] == "advanced"
        assert template["is_public"] is False
        assert "description" not in template
        assert "realtime" not in template

    def test_the_description_and_public_flag_are_the_users(self):
        draft = project(table_dc(), name="My Run")
        draft.description = "Weekly QC"
        draft.is_public = True
        template = build_template(draft)
        assert template["template"]["description"] == "Weekly QC"
        assert template["description"] == "Weekly QC"
        assert template["is_public"] is True

    def test_realtime_is_switched_on_with_a_debounce(self):
        draft = project(table_dc())
        draft.realtime = True
        assert build_template(draft)["realtime"] == {"enabled": True, "debounce_ms": 1000}

    def test_workflows_keep_their_order_and_collections(self):
        draft = ProjectDraft(
            name="Two",
            workflows=[
                WorkflowDraft(name="first", data_collections=[table_dc("a")]),
                WorkflowDraft(name="second", data_collections=[table_dc("b"), scan_dc("c")]),
            ],
        )
        workflows = build_template(draft)["workflows"]
        assert [w["name"] for w in workflows] == ["first", "second"]
        assert [d["data_collection_tag"] for d in workflows[1]["data_collections"]] == ["b", "c"]

    def test_a_template_owns_its_data(self):
        draft = project(scan_dc(ignore=["work"]))
        template = build_template(draft)
        template["workflows"][0]["data_collections"][0]["config"]["scan"]["scan_parameters"][
            "ignore"
        ].append("more")
        assert draft.workflows[0].data_collections[0].ignore == ["work"]

    def test_every_type_builds_a_template_validation_accepts(self):
        draft = project(
            table_dc("sheet"),
            scan_dc("quant", max_depth=3),
            DcDraft(
                tag="mqc",
                type="multiqc",
                mode="single",
                path="multiqc/multiqc_data/multiqc.parquet",
                props=MultiQCProps(),
            ),
            DcDraft(
                tag="imgs",
                type="image",
                mode="single",
                path="images.csv",
                props=ImageProps(image_column="img", local_images_path="images"),
            ),
            DcDraft(
                tag="vcf",
                type="indexed_file",
                mode="recursive",
                regex=r"\.vcf\.gz$",
                props=IndexedFileProps(),
            ),
            DcDraft(
                tag="areas",
                type="geojson",
                mode="single",
                path="regions/areas.geojson",
                props=GeoJSONProps(),
            ),
            DcDraft(
                tag="tree",
                type="phylogeny",
                mode="single",
                path="trees/tree.nwk",
                props=PhylogenyProps(metadata_dc_tag="sheet"),
            ),
        )
        warnings = validate_inline_template(build_template(draft), remote=False)
        # The only advice: the image folder in the server's bucket is for the server to pick.
        assert len(warnings) == 1 and "s3_base_folder" in warnings[0]

    def test_locations_are_all_under_the_root_placeholder(self):
        draft = project(
            table_dc("sheet", path="input/samplesheet.csv"),
            DcDraft(
                tag="imgs",
                type="image",
                mode="single",
                path="images.csv",
                props=ImageProps(image_column="img", local_images_path="images"),
            ),
        )
        text = yaml.safe_dump(build_template(draft))
        # The folder the user browsed never leaks in as an absolute path.
        assert "/home" not in text and "/tmp" not in text
        assert "{DATA_ROOT}/input/samplesheet.csv" in text
        assert "{DATA_ROOT}/images" in text


class TestTemplateYaml:
    def test_it_is_a_commented_file_that_loads_back_to_the_template(self):
        template = build_template(project(table_dc(), scan_dc(), name="Café QC"))
        text = template_yaml(template)
        assert text.startswith(assemble.YAML_HEADER)
        assert text.splitlines()[0] == "# Defined with the Depictio Project Builder."
        assert "depictio ingest <folder or s3://prefix> --template <this file>" in text
        assert yaml.safe_load(text) == template
        # Unicode stays readable, and the sections stay in the order they were built.
        assert "Café QC" in text
        assert text.index("\ntemplate:") < text.index("\nworkflows:")

    def test_the_placeholder_survives_the_round_trip(self):
        text = template_yaml(build_template(project(table_dc())))
        loaded = yaml.safe_load(text)
        scan = loaded["workflows"][0]["data_collections"][0]["config"]["scan"]
        assert scan["scan_parameters"]["filename"] == "{DATA_ROOT}/samplesheet.csv"
