"""Cascade delete must not leave a project's runs behind.

A run document is keyed by ``workflow_id`` and carries no ``data_collection_id``,
so deleting runs by collection never matched one. The leftovers are not inert:
a scan skips runs it has already registered, so re-creating a project on the same
(static) workflow id inherited the stale runs and registered no files for any
recursive-scan collection — the collection then looked ingested but held nothing.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from bson import ObjectId

MODULE = "depictio.api.v1.endpoints.projects_endpoints.routes"

PROJECT_ID = ObjectId()
WF_ID = ObjectId()
DC_ID = ObjectId()


def _run_cascade():
    """Run the cascade against mocked collections; return the runs mock."""
    from depictio.api.v1.endpoints.projects_endpoints.routes import _cascade_delete_project

    projects = MagicMock()
    projects.aggregate.return_value = [{"dc_id": DC_ID, "wf_id": WF_ID}]
    runs = MagicMock()

    with (
        patch(f"{MODULE}.projects_collection", projects),
        patch(f"{MODULE}.runs_collection", runs),
        patch(f"{MODULE}.files_collection", MagicMock()),
        patch(f"{MODULE}.deltatables_collection", MagicMock()),
        patch(f"{MODULE}.multiqc_collection", MagicMock()),
        patch(f"{MODULE}.jbrowse_collection", MagicMock()),
        patch(f"{MODULE}.data_collections_collection", MagicMock()),
        patch(f"{MODULE}.dashboards_collection", MagicMock()),
        patch(f"{MODULE}._collect_s3_locations_for_project", return_value=[]),
    ):
        _cascade_delete_project(PROJECT_ID, "demo")
    return runs


def test_runs_are_deleted_by_workflow():
    runs = _run_cascade()
    queried = [call.args[0] for call in runs.delete_many.call_args_list]
    by_workflow = [q for q in queried if "workflow_id" in q]
    assert by_workflow, f"cascade never deleted runs by workflow: {queried}"
    assert WF_ID in by_workflow[0]["workflow_id"]["$in"]


def test_runs_are_not_queried_by_collection():
    """`WorkflowRun` has no `data_collection_id`, so such a filter matches nothing.

    Keeping it as belt-and-braces is what let the missing workflow filter go
    unnoticed: the cascade looked like it deleted runs.
    """
    runs = _run_cascade()
    queried = [call.args[0] for call in runs.delete_many.call_args_list]
    assert not any("data_collection_id" in q for q in queried), queried


def test_the_run_model_really_has_no_collection_key():
    """Pins the premise of the test above."""
    from depictio.models.models.workflows import WorkflowRun

    assert "data_collection_id" not in WorkflowRun.model_fields
    assert "workflow_id" in WorkflowRun.model_fields
