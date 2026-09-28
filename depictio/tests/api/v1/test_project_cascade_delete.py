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


def test_phylogeny_trees_are_collected_for_deletion():
    """The CLI uploads a tree under a key derived from the DC id, with no document
    recording it, so only the embedded DC config can say it exists."""
    from depictio.api.v1.endpoints.migrate_endpoints.routes import (
        _collect_s3_locations_for_project,
    )
    from depictio.models.models.data_collections_types.phylogeny import phylogeny_s3_key

    tree_dc, table_dc, other_project_tree = ObjectId(), ObjectId(), ObjectId()
    projects = MagicMock()
    projects.find.return_value = [
        {
            "workflows": [
                {
                    "data_collections": [
                        {"_id": tree_dc, "config": {"type": "phylogeny"}},
                        {"_id": table_dc, "config": {"type": "table"}},
                        {"_id": other_project_tree, "config": {"type": "phylogeny"}},
                    ]
                }
            ]
        }
    ]
    empty = MagicMock()
    empty.find.return_value = []
    migrate = "depictio.api.v1.endpoints.migrate_endpoints.routes"

    with (
        patch(f"{migrate}.projects_collection", projects),
        patch(f"{migrate}.deltatables_collection", empty),
        patch(f"{migrate}.data_collections_collection", empty),
        patch(f"{migrate}.multiqc_collection", empty),
        patch(f"{migrate}.jbrowse_collection", empty),
    ):
        locations = _collect_s3_locations_for_project([tree_dc, table_dc], "bucket")

    assert locations == [phylogeny_s3_key(str(tree_dc))]


def test_bioimage_stores_are_collected_for_deletion():
    """Every zarr key of every store sits under one DC prefix; consumers list
    each location as a prefix, so the prefix alone covers the whole upload."""
    from depictio.api.v1.endpoints.migrate_endpoints.routes import (
        _collect_s3_locations_for_project,
    )
    from depictio.models.models.data_collections_types.bioimage import bioimage_s3_prefix
    from depictio.models.models.data_collections_types.phylogeny import phylogeny_s3_key

    zarr_dc, tree_dc, other_project_zarr = ObjectId(), ObjectId(), ObjectId()
    projects = MagicMock()
    projects.find.return_value = [
        {
            "workflows": [
                {
                    "data_collections": [
                        {"_id": zarr_dc, "config": {"type": "bioimage"}},
                        {"_id": tree_dc, "config": {"type": "phylogeny"}},
                        {"_id": other_project_zarr, "config": {"type": "bioimage"}},
                    ]
                }
            ]
        }
    ]
    empty = MagicMock()
    empty.find.return_value = []
    migrate = "depictio.api.v1.endpoints.migrate_endpoints.routes"

    with (
        patch(f"{migrate}.projects_collection", projects),
        patch(f"{migrate}.deltatables_collection", empty),
        patch(f"{migrate}.data_collections_collection", empty),
        patch(f"{migrate}.multiqc_collection", empty),
        patch(f"{migrate}.jbrowse_collection", empty),
    ):
        locations = _collect_s3_locations_for_project([zarr_dc, tree_dc], "bucket")

    assert locations == [bioimage_s3_prefix(str(zarr_dc)), phylogeny_s3_key(str(tree_dc))]


def test_cascade_deletes_every_object_under_the_bioimage_prefix():
    """The cascade lists by prefix, so all chunks of all stores are removed."""
    from depictio.api.v1.endpoints.projects_endpoints.routes import _cascade_delete_project
    from depictio.models.models.data_collections_types.bioimage import bioimage_s3_prefix

    prefix = bioimage_s3_prefix(str(DC_ID))
    projects = MagicMock()
    projects.aggregate.return_value = [{"dc_id": DC_ID, "wf_id": WF_ID}]
    s3 = MagicMock()
    s3.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": f"{prefix}a.zarr/.zattrs"}, {"Key": f"{prefix}a.zarr/0/0.0"}]}
    ]

    with (
        patch(f"{MODULE}.projects_collection", projects),
        patch(f"{MODULE}.runs_collection", MagicMock()),
        patch(f"{MODULE}.files_collection", MagicMock()),
        patch(f"{MODULE}.deltatables_collection", MagicMock()),
        patch(f"{MODULE}.multiqc_collection", MagicMock()),
        patch(f"{MODULE}.jbrowse_collection", MagicMock()),
        patch(f"{MODULE}.data_collections_collection", MagicMock()),
        patch(f"{MODULE}.dashboards_collection", MagicMock()),
        patch(f"{MODULE}._collect_s3_locations_for_project", return_value=[prefix]),
        patch(f"{MODULE}.boto3.client", return_value=s3),
    ):
        _cascade_delete_project(PROJECT_ID, "demo")

    listed = s3.get_paginator.return_value.paginate.call_args.kwargs["Prefix"]
    assert listed == prefix.strip("/")
    deleted = s3.delete_objects.call_args.kwargs["Delete"]["Objects"]
    assert {o["Key"] for o in deleted} == {f"{prefix}a.zarr/.zattrs", f"{prefix}a.zarr/0/0.0"}
