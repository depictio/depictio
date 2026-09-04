"""A CLI save must not delete the workflows the browser added.

`PUT /projects/update` takes a whole project document, so the CLI, which
round-trips a local `project.yaml`, sends a payload that has never heard of
anything created from the browser. `registration_time` and `is_public` were
already carved out of the `$set` for that reason; workflows are the case that
loses user data.
"""

import asyncio
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.projects_endpoints import routes as proj_routes
from depictio.models.models.data_collections import (
    DataCollection,
    DataCollectionConfig,
    Scan,
    ScanSingle,
)
from depictio.models.models.data_collections_types.table import DCTableConfig
from depictio.models.models.projects import Project
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import (
    Workflow,
    WorkflowDataLocation,
    WorkflowEngine,
)


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["depictio_test"]
    with patch.object(proj_routes, "projects_collection", database["projects"]):
        yield database


@pytest.fixture
def user():
    return UserBase(id=ObjectId(), email="owner@example.com", is_admin=True)


def _dc(tag: str) -> DataCollection:
    return DataCollection(
        id=ObjectId(),
        data_collection_tag=tag,
        config=DataCollectionConfig(
            type="table",
            metatype="metadata",
            scan=Scan(mode="single", scan_parameters=ScanSingle(filename="/app/depictio/x.csv")),
            dc_specific_properties=DCTableConfig(format="csv"),
        ),
    )


def _workflow(name: str, wf_id: ObjectId) -> Workflow:
    return Workflow(
        id=wf_id,
        name=name,
        workflow_tag=f"python/{name}",
        engine=WorkflowEngine(name="python", version="3.12"),
        data_location=WorkflowDataLocation(structure="flat", locations=["/app/depictio"]),
        data_collections=[_dc(f"{name}-dc")],
    )


def _seed(db, project_id, user, workflows):
    db["projects"].insert_one(
        {
            "_id": project_id,
            "name": "My project",
            "project_type": "advanced",
            "registration_time": "2024-01-01 10:00:00",
            "workflows": [wf.mongo() for wf in workflows],
            "data_collections": [],
            "permissions": {
                "owners": [{"_id": user.id, "email": user.email}],
                "editors": [],
                "viewers": [],
            },
        }
    )


def _update(project, user):
    return asyncio.run(proj_routes.update_project(project=project, current_user=user))


def _stored_workflows(db, project_id) -> list[dict]:
    return db["projects"].find_one({"_id": project_id})["workflows"]


def _stored_workflow_ids(db, project_id) -> list[str]:
    return [str(wf["_id"]) for wf in _stored_workflows(db, project_id)]


class TestUpdateProjectPreservesWorkflows:
    def test_a_browser_added_workflow_survives_a_cli_update(self, db, user):
        """The regression this file exists for."""
        project_id, cli_id, browser_id = ObjectId(), ObjectId(), ObjectId()
        cli_wf = _workflow("pipeline", cli_id)
        _seed(db, project_id, user, [cli_wf, _workflow("uploaded_csv", browser_id)])

        # The CLI re-sends only what its project.yaml describes.
        _update(
            Project(
                id=project_id,
                name="My project",
                project_type="advanced",
                workflows=[cli_wf],
                permissions=Permission(owners=[user]),
            ),
            user,
        )

        assert _stored_workflow_ids(db, project_id) == [str(cli_id), str(browser_id)]

    def test_the_payload_still_updates_the_workflow_it_owns(self, db, user):
        project_id, cli_id = ObjectId(), ObjectId()
        _seed(db, project_id, user, [_workflow("old_name", cli_id)])

        _update(
            Project(
                id=project_id,
                name="My project",
                project_type="advanced",
                workflows=[_workflow("new_name", cli_id)],
                permissions=Permission(owners=[user]),
            ),
            user,
        )

        stored = db["projects"].find_one({"_id": project_id})
        assert stored["workflows"][0]["name"] == "new_name"
        assert len(stored["workflows"]) == 1, "an update must not duplicate the workflow"

    def test_a_new_cli_workflow_is_still_added(self, db, user):
        project_id, first, second = ObjectId(), ObjectId(), ObjectId()
        wf_one = _workflow("one", first)
        _seed(db, project_id, user, [wf_one])

        _update(
            Project(
                id=project_id,
                name="My project",
                project_type="advanced",
                workflows=[wf_one, _workflow("two", second)],
                permissions=Permission(owners=[user]),
            ),
            user,
        )

        assert _stored_workflow_ids(db, project_id) == [str(first), str(second)]

    def test_repeated_updates_do_not_accumulate_copies(self, db, user):
        """A preserved workflow must be matched, not re-appended every save."""
        project_id, cli_id, browser_id = ObjectId(), ObjectId(), ObjectId()
        cli_wf = _workflow("pipeline", cli_id)
        _seed(db, project_id, user, [cli_wf, _workflow("uploaded_csv", browser_id)])

        for _ in range(3):
            _update(
                Project(
                    id=project_id,
                    name="My project",
                    project_type="advanced",
                    workflows=[cli_wf],
                    permissions=Permission(owners=[user]),
                ),
                user,
            )

        assert _stored_workflow_ids(db, project_id) == [str(cli_id), str(browser_id)]

    def test_a_preserved_workflow_keeps_objectid_typed_ids(self, db, user):
        """The merge must not read from `_async_get_project_from_id`.

        That helper returns the project through `convert_objectid_to_str`, so
        preserving a sub-document from it writes its ids back as strings.
        Nothing then complains: Pydantic re-coerces on read, so the API keeps
        showing the data collection while the persisted BSON is the wrong type
        and every ObjectId-typed query silently stops matching it. Deleting the
        DC 404s (`$pull` on an ObjectId) and its delta location disappears from
        the dashboard (an `$expr` join against `deltatables.data_collection_id`).
        """
        project_id, cli_id, browser_id = ObjectId(), ObjectId(), ObjectId()
        cli_wf = _workflow("pipeline", cli_id)
        _seed(db, project_id, user, [cli_wf, _workflow("uploaded_csv", browser_id)])

        _update(
            Project(
                id=project_id,
                name="My project",
                project_type="advanced",
                workflows=[cli_wf],
                permissions=Permission(owners=[user]),
            ),
            user,
        )

        preserved = next(
            wf for wf in _stored_workflows(db, project_id) if str(wf["_id"]) == str(browser_id)
        )
        assert isinstance(preserved["_id"], ObjectId), "preserved workflow id was stringified"
        assert isinstance(preserved["data_collections"][0]["_id"], ObjectId), (
            "preserved data collection id was stringified"
        )
