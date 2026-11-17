# ruff: noqa: F811 - the fixtures imported from test_from_run are parameters here
"""``POST /projects/from_run`` with a shipped template edited in the Project Builder.

``template_id`` plus ``edits`` (``project_builder.overlay``): the shipped
template is re-read, the reader's edits are applied to it, and the rest is a
shipped template's creation, dashboards and recipes included. What was not
edited reports exactly as the same run without edits.
"""

from __future__ import annotations

import pytest
from bson import ObjectId
from pydantic import ValidationError

from depictio.api.v1.endpoints.projects_endpoints import from_run
from depictio.api.v1.endpoints.projects_endpoints.local_dirs import CodedHTTPException
from depictio.project_builder import overlay
from depictio.project_builder.assemble import (
    DcDraft,
    LinkDraft,
    ProjectDraft,
    TableProps,
    WorkflowDraft,
    build_template,
)
from depictio.project_builder.overlay import ScanEdit, TemplateEdits, WorkflowEdit
from depictio.tests.cli.s3_stubs import S3_ROOT

from .test_from_run import (  # noqa: F401 - fixtures
    TEMPLATE_ID,
    _call,
    _dispatched_payloads,
    _rows,
    _run_from_folder,
    allowlisted_bucket,
    megatest_s3,
    mock_db,
    no_bucket_lists,
    server_context,
)


def _additions(workflow: str = "added", link_to: str | None = None) -> dict:
    """One extra table, read from the run's metadata file, as the builder sends it."""
    draft = ProjectDraft(
        name="Edited",
        workflows=[
            WorkflowDraft(
                name=workflow,
                data_collections=[
                    DcDraft(
                        tag="lab_metadata",
                        type="table",
                        mode="single",
                        path="input/Metadata_full.tsv",
                        props=TableProps(format="tsv", separator="\t"),
                    )
                ],
            )
        ],
        links=[LinkDraft(source_tag="lab_metadata", source_column="sample", target_tag=link_to)]
        if link_to
        else [],
    )
    return build_template(draft, remote=True, link_targets=overlay.link_targets(TEMPLATE_ID))


def test_edits_need_the_template_they_edit():
    with pytest.raises(ValidationError, match="give its template_id"):
        from_run.FromRunRequest(data_root=S3_ROOT, edits=TemplateEdits(remove=["metadata"]))


def test_no_edit_reports_as_the_shipped_template(mock_db, megatest_s3):
    megatest_s3()
    shipped = _call(dry_run=True)
    edited = _call(dry_run=True, edits=TemplateEdits())
    assert edited.model_dump() == shipped.model_dump()


def test_a_removal_reports_every_other_collection_as_without_it(mock_db, megatest_s3):
    megatest_s3()
    edits = TemplateEdits(remove=["taxonomy_composition"])
    _raw, _path, removed, _ = overlay.compose(TEMPLATE_ID, edits, remote=True)
    shipped = _rows(_call(dry_run=True))
    edited = _rows(_call(dry_run=True, edits=edits))

    assert "taxonomy_composition" in removed
    assert set(shipped) - set(edited) == set(removed) & set(shipped)
    for tag, row in edited.items():
        assert row.model_dump() == shipped[tag].model_dump(), tag


def test_an_added_collection_is_read_next_to_the_template(mock_db, megatest_s3):
    megatest_s3()
    shipped = _rows(_call(dry_run=True))
    report = _call(dry_run=True, edits=TemplateEdits(additions=_additions()))
    rows = _rows(report)

    assert set(rows) == set(shipped) | {"lab_metadata"}
    assert (rows["lab_metadata"].status, rows["lab_metadata"].matched) == ("ok", 1)
    assert report.template_id == TEMPLATE_ID


def test_a_real_run_imports_the_dashboards_and_ingests_the_edited_project(mock_db, megatest_s3):
    megatest_s3()
    edits = TemplateEdits(
        remove=["taxonomy_composition"],
        additions=_additions(workflow="ampliseq", link_to="multiqc_data"),
    )
    report, _user, importer, task = _run_from_folder(mock_db, edits=edits)

    assert report.project_id is not None
    # The template's dashboards, as for the shipped template: the import
    # prunes the tiles of what was removed.
    assert importer.call_count == 1
    stored = mock_db["projects"].find_one({"_id": ObjectId(report.project_id)})
    (workflow,) = stored["workflows"]
    tags = [dc["data_collection_tag"] for dc in workflow["data_collections"]]
    assert "lab_metadata" in tags
    assert "taxonomy_composition" not in tags and "ma_canonical" not in tags
    assert any(
        link["source_dc_tag"] == "lab_metadata" and link["target_dc_tag"] == "multiqc_data"
        for link in stored.get("links") or []
    )
    assert stored["template_origin"]["template_id"] == TEMPLATE_ID
    dispatched = {payload["dc_tag"] for payload in _dispatched_payloads(task)}
    assert "lab_metadata" in dispatched
    assert "taxonomy_composition" not in dispatched


def test_a_repointed_file_is_read_where_the_reader_put_it(mock_db, megatest_s3):
    megatest_s3()
    edits = TemplateEdits(
        scans={"phylogenetic_tree_canonical": ScanEdit(path="qiime2/barplot/level-2.csv")}
    )
    row = _rows(_call(dry_run=True, edits=edits))["phylogenetic_tree_canonical"]
    assert row.location == f"{S3_ROOT}/qiime2/barplot/level-2.csv"


def test_an_edit_that_does_not_fit_is_a_422_with_its_code(mock_db, megatest_s3):
    megatest_s3()
    with pytest.raises(CodedHTTPException) as refused:
        _call(dry_run=True, edits=TemplateEdits(remove=["not_a_collection"]))
    assert refused.value.status_code == 422
    assert refused.value.code == "template_edits_invalid"


def test_a_renamed_workflow_is_what_the_dashboards_name(mock_db, megatest_s3):
    megatest_s3()
    edits = TemplateEdits(workflows={"ampliseq": WorkflowEdit(name="ampliseq-lab")})
    report, _user, importer, _task = _run_from_folder(mock_db, edits=edits)

    stored = mock_db["projects"].find_one({"_id": ObjectId(report.project_id)})
    assert [w["name"] for w in stored["workflows"]] == ["ampliseq-lab"]
    imported = importer.call_args.kwargs["yaml_content"]
    assert "workflow_tag: ampliseq-lab" in imported
    assert "workflow_tag: ampliseq\n" not in imported
