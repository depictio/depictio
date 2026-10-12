"""A shipped template read back as a builder draft (the inverse of ``assemble``)."""

from __future__ import annotations

import copy

import pytest

from depictio.project_builder import assemble, validate
from depictio.project_builder.assemble import (
    DcDraft,
    GeoJSONProps,
    LinkDraft,
    MultiQCProps,
    PhylogenyProps,
    ProjectDraft,
    ReaderOptions,
    TableProps,
    WildcardDraft,
    WorkflowDraft,
)
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.from_template import (
    draft_for_template,
    load_shipped_template,
    template_to_draft,
)


def _dc(tag: str, drops: list[dict]) -> dict | None:
    return next((d for d in drops if d["kind"] == "collection" and d["tag"] == tag), None)


def _draft() -> ProjectDraft:
    sheet = DcDraft(
        tag="sheet",
        description="One row per sample",
        type="table",
        mode="single",
        path="meta/samplesheet.csv",
        props=TableProps(
            format="csv",
            separator=";",
            columns_description={"sample": "Sample id"},
            reader=ReaderOptions(skip_rows=2, null_values=["NA"]),
        ),
    )
    quant = DcDraft(
        tag="quant",
        type="table",
        mode="recursive",
        regex=r"^star/{sample}/quant\.tsv$",
        wildcards=[WildcardDraft(name="sample", regex="[^/]+")],
        max_depth=3,
        ignore=["work"],
        optional=True,
        metatype="Metadata",
        props=TableProps(format="tsv", separator="\t"),
    )
    report = DcDraft(
        tag="qc",
        type="multiqc",
        mode="single",
        path="multiqc/multiqc_data/multiqc.parquet",
        props=MultiQCProps(),
    )
    areas = DcDraft(
        tag="areas",
        type="geojson",
        mode="single",
        path="regions/areas.geojson",
        props=GeoJSONProps(feature_id_key="name"),
    )
    tree = DcDraft(
        tag="tree",
        type="phylogeny",
        mode="single",
        path="trees/tree.nwk",
        props=PhylogenyProps(metadata_dc_tag="sheet", metadata_taxon_column="sample"),
    )
    return ProjectDraft(
        name="Lab Run",
        description="A lab run",
        is_public=True,
        realtime=True,
        data_management_platform_project_url="https://example.org/project/1",
        workflows=[
            WorkflowDraft(
                name="main",
                engine="nextflow",
                engine_version="24.10.4",
                version="3.0.0",
                repository_url="https://github.com/nf-core/rnaseq",
                catalog=assemble.CatalogRef(name="nf-core", url="https://nf-co.re"),
                structure="sequencing-runs",
                runs_regex="run_.*",
                data_collections=[sheet, quant, report, areas, tree],
            )
        ],
        links=[
            LinkDraft(source_tag="sheet", source_column="sample", target_tag="qc"),
            LinkDraft(
                source_tag="sheet",
                source_column="sample",
                target_tag="quant",
                target_field="sample",
                description="Samples of the sheet",
            ),
        ],
    )


def test_a_built_template_reads_back_as_the_same_draft():
    original = _draft()
    template = assemble.build_template(original)
    result = template_to_draft(template, template_id="custom/lab-run")
    assert ProjectDraft(**result["draft"]) == original
    assert result["dropped"] == []
    assert result["carried"] == {"workflows": 1, "collections": 5, "links": 2}
    assert result["editable"] is True and result["reason"] is None
    assert result["template_id"] == "custom/lab-run" and result["title"] == "Lab Run"
    # and the draft builds the very template it came from
    assert assemble.build_template(ProjectDraft(**result["draft"])) == template


def test_the_draft_is_json_compatible_and_leaves_the_template_untouched():
    template = assemble.build_template(_draft())
    before = copy.deepcopy(template)
    result = template_to_draft(template, template_id="custom/lab-run")
    assert template == before
    import json

    assert json.loads(json.dumps(result)) == result


def test_a_shipped_template_converts_and_says_what_it_lost():
    result = draft_for_template("nf-core/viralrecon/3.0.0")
    assert result["template_id"] == "nf-core/viralrecon/3.0.0"
    assert result["editable"] is True
    assert result["carried"]["collections"] >= 1
    kinds = {d["kind"] for d in result["dropped"]}
    assert {"dashboards", "conditional", "provenance", "variables", "collection"} <= kinds
    # each template-level loss is listed once
    for kind in ("dashboards", "conditional", "provenance", "variables"):
        assert sum(d["kind"] == kind for d in result["dropped"]) == 1
    assert "IS_NANOPORE" in next(d for d in result["dropped"] if d["kind"] == "variables")["reason"]
    draft = ProjectDraft(**result["draft"])
    template = assemble.build_template(draft)
    validate.validate_inline_template(template, remote=False)
    carried = {dc.tag for w in draft.workflows for dc in w.data_collections}
    dropped = {d["tag"] for d in result["dropped"] if d["kind"] == "collection"}
    assert carried and not carried & dropped
    # a link survives only with both its ends
    assert all({link.source_tag, link.target_tag} <= carried for link in draft.links)
    for entry in result["dropped"]:
        assert entry["reason"] and entry["kind"]


def test_the_latest_version_resolves_and_the_resolved_id_is_reported():
    result = draft_for_template("nf-core/ampliseq/latest")
    assert result["template_id"].startswith("nf-core/ampliseq/")
    assert result["template_id"] != "nf-core/ampliseq/latest"
    validate.validate_inline_template(
        assemble.build_template(ProjectDraft(**result["draft"])), remote=False
    )


def _raw(*collections: dict, links: list[dict] | None = None) -> dict:
    template = assemble.build_template(
        ProjectDraft(
            name="Mixed",
            workflows=[
                WorkflowDraft(
                    name="main",
                    data_collections=[
                        DcDraft(
                            tag="seed",
                            type="table",
                            mode="single",
                            path="seed.csv",
                            props=TableProps(format="csv", separator=","),
                        )
                    ],
                )
            ],
        )
    )
    template["workflows"][0]["data_collections"].extend(collections)
    if links:
        template["links"] = links
    return template


def _table(tag: str, **config) -> dict:
    return {
        "data_collection_tag": tag,
        "description": tag,
        "config": {
            "type": "Table",
            "scan": {"mode": "single", "scan_parameters": {"filename": "{DATA_ROOT}/x.csv"}},
            "dc_specific_properties": {"format": "csv"},
            **config,
        },
    }


@pytest.mark.parametrize(
    "extra, expected",
    [
        ({"source": "transformed", "transform": {"recipe": "join.py"}}, "other collections"),
        ({"sources": [{"dc": "seed"}]}, "other collections"),
        ({"join": {"on": "sample"}}, "other collections"),
        ({"type": "Spreadsheet"}, "not one the builder offers"),
        (
            {"scan": {"mode": "manifest", "scan_parameters": {"manifest_url": "https://x"}}},
            "scan mode",
        ),
        (
            {
                "scan": {
                    "mode": "single",
                    "scan_parameters": {"filename": "{SAMPLESHEET_FILE}"},
                }
            },
            "template variable {SAMPLESHEET_FILE}",
        ),
        (
            {"dc_specific_properties": {"format": "csv", "polars_kwargs": {"new_columns": ["a"]}}},
            "new_columns",
        ),
        ({"dc_specific_properties": {"format": "csv", "mystery": 1}}, "mystery"),
        ({"scan": None}, "no file scan"),
    ],
)
def test_a_collection_the_builder_cannot_express_is_dropped_with_its_tag(extra, expected):
    raw = _raw(_table("odd", **extra))
    result = template_to_draft(raw, template_id="x/y/1")
    entry = _dc("odd", result["dropped"])
    assert entry is not None and expected in entry["reason"]
    kept = ProjectDraft(**result["draft"]).workflows[0].data_collections
    assert [dc.tag for dc in kept] == ["seed"]
    assert result["carried"]["collections"] == 1 and result["editable"] is True


def test_a_collection_that_fails_the_builders_validation_is_dropped_not_raised():
    bad_regex = _table("bad_regex")
    bad_regex["config"]["scan"] = {
        "mode": "recursive",
        "scan_parameters": {"regex_config": {"pattern": "(unclosed"}},
    }
    undeclared = _table("undeclared")
    undeclared["config"]["scan"] = {
        "mode": "recursive",
        "scan_parameters": {"regex_config": {"pattern": r"^{run}/x\.tsv$"}},
    }
    not_a_mapping = "just a string"
    raw = _raw(bad_regex, undeclared)
    raw["workflows"][0]["data_collections"].append(not_a_mapping)
    result = template_to_draft(raw, template_id="x/y/1")
    assert _dc("bad_regex", result["dropped"]) is not None
    assert _dc("undeclared", result["dropped"]) is not None
    assert result["carried"]["collections"] == 1


def test_duplicate_tags_keep_the_first_and_drop_the_rest():
    result = template_to_draft(_raw(_table("seed")), template_id="x/y/1")
    entry = _dc("seed", result["dropped"])
    assert entry is not None and "already" in entry["reason"]
    assert result["carried"]["collections"] == 1


def test_links_need_both_ends_and_the_builders_link_fields():
    sheet_to_qc = {
        "source_dc_tag": "seed",
        "source_column": "sample",
        "target_dc_tag": "gone",
        "target_type": "table",
        "link_config": {"resolver": "direct", "target_field": "sample"},
    }
    region = {
        "source_dc_tag": "seed",
        "source_column": "sample",
        "target_dc_tag": "other",
        "target_type": "table",
        "link_config": {"resolver": "region", "columns": ["chrom"]},
    }
    kept = {
        "source_dc_tag": "seed",
        "source_column": "sample",
        "target_dc_tag": "other",
        "target_type": "table",
        "link_config": {"resolver": "direct", "target_field": "sample"},
        "description": "keep",
        "enabled": True,
    }
    raw = _raw(_table("other"), links=[sheet_to_qc, region, kept])
    result = template_to_draft(raw, template_id="x/y/1")
    assert result["carried"]["links"] == 1
    assert ProjectDraft(**result["draft"]).links[0].description == "keep"
    reasons = {d["tag"]: d["reason"] for d in result["dropped"] if d["kind"] == "link"}
    assert "gone" in reasons["seed -> gone"]
    assert "columns" in reasons["seed -> other"]


def test_nothing_to_carry_is_not_editable():
    raw = _raw()
    raw["workflows"][0]["data_collections"] = [
        _table("derived", source="transformed", transform={"recipe": "x.py"})
    ]
    result = template_to_draft(raw, template_id="x/y/1")
    assert result["editable"] is False and result["reason"]
    assert result["carried"] == {"workflows": 0, "collections": 0, "links": 0}
    assert {d["kind"] for d in result["dropped"]} == {"collection", "workflow"}
    assert result["draft"]["workflows"] == []


def test_a_template_with_nothing_in_it_does_not_raise():
    result = template_to_draft({}, template_id="x/y/1")
    assert result["editable"] is False and result["draft"]["name"] == "x/y/1"


@pytest.mark.parametrize("bad", ["../etc/passwd", "nf-core/../../x", "/etc/passwd", "~/x", ""])
def test_ids_that_leave_the_templates_are_refused(bad):
    with pytest.raises(BuilderRefused) as refused:
        load_shipped_template(bad)
    assert (refused.value.status, refused.value.code) == (400, "template_invalid")


def test_an_unknown_id_is_not_found():
    with pytest.raises(BuilderRefused) as refused:
        load_shipped_template("nf-core/no-such-pipeline/9.9.9")
    assert (refused.value.status, refused.value.code) == (404, "template_not_found")


def test_a_path_is_not_read_even_where_the_cli_accepts_one(tmp_path, monkeypatch):
    folder = tmp_path / "mine"
    folder.mkdir()
    (folder / "template.yaml").write_text("name: mine\nworkflows: []\n")
    monkeypatch.setenv("DEPICTIO_CONTEXT", "cli")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(BuilderRefused) as refused:
        load_shipped_template("mine")
    assert refused.value.status == 404
    with pytest.raises(BuilderRefused) as refused:
        load_shipped_template(str(folder / "template.yaml"))
    assert refused.value.status == 400


# The route, on the injected-opener router both servers use.

URL = "/depictio/api/v1/projects/builder/from_template"


@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from depictio.project_builder.routes import BUILDER_PREFIX, build_builder_router

    def opener(spec, *, count_files):  # never asked: /from_template reads no data root
        raise AssertionError("the route opened a data root")

    app = FastAPI()
    app.include_router(build_builder_router(lambda: opener), prefix=BUILDER_PREFIX)
    return TestClient(app)


def test_the_route_answers_with_the_converted_draft(client):
    response = client.post(URL, json={"template_id": "nf-core/viralrecon/3.0.0"})
    assert response.status_code == 200, response.text
    assert response.json() == draft_for_template("nf-core/viralrecon/3.0.0")
    assert response.json()["carried"]["collections"] >= 1


def test_the_route_answers_latest(client):
    response = client.post(URL, json={"template_id": "nf-core/ampliseq/latest"})
    assert response.status_code == 200
    assert response.json()["template_id"].startswith("nf-core/ampliseq/")


def test_the_route_refuses_unknown_and_escaping_ids(client):
    missing = client.post(URL, json={"template_id": "nf-core/nope/1.0.0"})
    assert (missing.status_code, missing.json()["code"]) == (404, "template_not_found")
    escaping = client.post(URL, json={"template_id": "nf-core/../../etc"})
    assert (escaping.status_code, escaping.json()["code"]) == (400, "template_invalid")
    absolute = client.post(URL, json={"template_id": "/etc/passwd"})
    assert (absolute.status_code, absolute.json()["code"]) == (400, "template_invalid")
