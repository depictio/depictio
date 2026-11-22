"""Who may preview, create, delete and list UI joins, and what each refusal says.

The real router over a mongomock project and real Delta tables (see conftest).
"""

from __future__ import annotations

import polars as pl
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.joins_endpoints.service import (
    JoinRequest,
    name_problem,
)
from depictio.tests.api.v1.endpoints.joins_endpoints.conftest import physical_features


def _code(response) -> str:
    return response.json()["detail"]["code"]


class TestPermissions:
    @pytest.mark.parametrize("action", ["preview", "create", "delete"])
    def test_a_viewer_is_refused(self, env, action):
        if action == "delete":
            env.create_ok()
            response = env.request(env.viewer, "DELETE", "/demo_phys")
            assert [j["name"] for j in env.joins()] == ["demo_phys"]
        else:
            response = getattr(env, action)(env.viewer, name="by_viewer")
            assert env.joins() == []
        assert response.status_code == 403

    @pytest.mark.parametrize("action", ["list", "preview", "create", "delete"])
    def test_a_stranger_does_not_learn_the_project_exists(self, env, action):
        # 404 on every route, as for a project that does not exist.
        if action == "delete":
            response = env.request(env.stranger, "DELETE", "/demo_phys")
        elif action == "list":
            response = env.request(env.stranger, "GET", "")
        else:
            response = getattr(env, action)(env.stranger)
        assert response.status_code == 404
        assert env.joins() == []

    @pytest.mark.parametrize("action", ["preview", "create", "delete"])
    def test_an_unknown_project_is_404(self, env, action):
        env.current = env.owner
        base = f"/joins/{ObjectId()}"
        if action == "delete":
            response = env.client.delete(f"{base}/demo_phys")
        else:
            suffix = "/preview" if action == "preview" else ""
            response = env.client.post(f"{base}{suffix}", json=env.body())
        assert response.status_code == 404

    def test_a_malformed_project_id_is_400(self, env):
        response = env.client.post("/joins/not-an-id/preview", json=env.body())
        assert response.status_code == 400

    @pytest.mark.parametrize("action", ["preview", "create", "delete"])
    def test_a_published_project_is_409(self, env, action):
        if action == "delete":
            env.create_ok()
        env.lock()
        response = (
            env.request(env.owner, "DELETE", "/demo_phys")
            if action == "delete"
            else getattr(env, action)(env.owner, name="late")
        )
        assert response.status_code == 409
        assert [j["name"] for j in env.joins()] == (["demo_phys"] if action == "delete" else [])

    @pytest.mark.parametrize("who", ["owner", "editor"])
    def test_owners_and_editors_may_preview_create_and_delete(self, env, who):
        user = getattr(env, who)
        assert env.preview(user).status_code == 200
        created = env.create(user)
        assert created.status_code == 200, created.text
        assert [j["name"] for j in env.joins()] == ["demo_phys"]
        deleted = env.request(user, "DELETE", "/demo_phys")
        assert deleted.status_code == 200
        assert env.joins() == []

    def test_an_editor_is_not_refused_by_the_owner_only_routes(self, env):
        """The join is written in-process: no HTTP round trip into owner-only routes."""
        created = env.create(env.editor)
        assert created.status_code == 200, created.text
        assert env.aggregations(created.json()["data_collection_id"])


class TestList:
    def test_a_viewer_lists_the_joins_without_edit_rights(self, env):
        made = env.create_ok()
        response = env.request(env.viewer, "GET", "")
        assert response.status_code == 200
        body = response.json()
        assert body["can_edit"] is False
        (entry,) = body["joins"]
        assert entry["name"] == "demo_phys"
        assert entry["left_dc_id"] == env.demo and entry["right_dc_id"] == env.phys
        assert entry["left_tag"] == "demographic_data"
        assert entry["right_tag"] == "physical_features"
        assert entry["result_dc_id"] == made["data_collection_id"]
        assert entry["result_tag"] == "joined_demo_phys"

    def test_owner_and_editor_can_edit(self, env):
        assert env.request(env.owner, "GET", "").json() == {"joins": [], "can_edit": True}
        assert env.request(env.editor, "GET", "").json()["can_edit"] is True

    def test_nobody_can_edit_a_published_project(self, env):
        env.lock()
        assert env.request(env.owner, "GET", "").json()["can_edit"] is False

    def test_a_user_who_cannot_see_the_project_gets_404(self, env):
        assert env.request(env.stranger, "GET", "").status_code == 404

    def test_a_public_project_is_listed_for_a_stranger(self, env):
        env.db["projects"].update_one({"_id": env.project_oid}, {"$set": {"is_public": True}})
        response = env.request(env.stranger, "GET", "")
        assert response.status_code == 200
        assert response.json()["can_edit"] is False

    def test_a_join_whose_result_was_removed_lists_no_result(self, env):
        made = env.create_ok()
        # Drop the joined collection from its workflow by hand.
        project = env.project()
        for workflow in project["workflows"]:
            workflow["data_collections"] = [
                dc
                for dc in workflow["data_collections"]
                if str(dc["_id"]) != made["data_collection_id"]
            ]
        env.db["projects"].replace_one({"_id": env.project_oid}, project)
        (entry,) = env.request(env.owner, "GET", "").json()["joins"]
        assert entry["result_dc_id"] is None


class TestValidation:
    """422 with a machine-readable ``detail.code``; same rules for preview and create."""

    @pytest.fixture(params=["preview", "create"])
    def act(self, env, request):
        return getattr(env, request.param)

    def test_the_same_table_on_both_sides(self, env, act):
        response = act(right_dc_id=env.demo)
        assert response.status_code == 422
        assert _code(response) == "same_collection"

    def test_no_shared_column(self, env, act):
        notes = env.add_table("notes", pl.DataFrame({"note_id": [1, 2], "text": ["a", "b"]}))
        response = act(right_dc_id=notes, on_columns=["individual_id"])
        assert response.status_code == 422
        assert _code(response) == "no_shared_column"

    def test_a_column_that_is_not_in_both(self, env, act):
        response = act(on_columns=["individual_id", "island"])
        assert response.status_code == 422
        assert _code(response) == "invalid_columns"
        assert "island" in response.json()["detail"]["message"]

    def test_bookkeeping_columns_are_not_shared_columns(self, env, act):
        """Both tables carry ``aggregation_time`` and ``depictio_run_id``: never a key."""
        response = act(on_columns=["depictio_run_id"])
        assert response.status_code == 422
        assert _code(response) == "invalid_columns"

    def test_a_collection_that_is_not_a_table(self, env, act):
        geo = env.add_table("a_map", None, kind="geojson")
        response = act(right_dc_id=geo)
        assert response.status_code == 422
        assert _code(response) == "not_a_table"
        assert "right" in response.json()["detail"]["message"]

    def test_a_left_collection_that_is_not_a_table(self, env, act):
        geo = env.add_table("a_map", None, kind="geojson")
        response = act(left_dc_id=geo)
        assert _code(response) == "not_a_table"

    def test_a_collection_of_another_project(self, env, act):
        response = act(right_dc_id=str(ObjectId()))
        assert response.status_code == 404
        assert _code(response) == "unknown_collection"

    def test_a_table_that_holds_no_data(self, env, act):
        empty = env.add_table("empty_table", None)
        response = act(right_dc_id=empty)
        assert response.status_code == 409
        assert _code(response) == "no_data"
        assert env.joins() == []


class TestNames:
    def test_a_bad_name_is_flagged_by_the_preview_and_refused_by_create(self, env):
        preview = env.preview(name="not a name!")
        assert preview.status_code == 200
        assert preview.json()["name_problem"] == (
            "A join name cannot contain spaces: use _ or - instead."
        )

        created = env.create(name="not a name!")
        assert created.status_code == 422
        assert _code(created) == "invalid_name"
        assert env.joins() == []

    def test_a_name_with_a_bad_character_says_which_characters_are_allowed(self, env):
        problem = env.preview(name="penguins!").json()["name_problem"]
        assert problem == "Use only letters, digits, _ and - in a join name."

    def test_a_long_name_is_a_readable_problem_not_a_422(self, env):
        preview = env.preview(name="x" * 101)
        assert preview.status_code == 200
        assert preview.json()["name_problem"] == "A join name has at most 100 characters."

        created = env.create(name="x" * 101)
        assert created.status_code == 422
        assert created.json()["detail"]["message"] == "A join name has at most 100 characters."
        assert env.create(name="x" * 100).status_code == 200

    def test_the_preview_works_before_a_name_is_typed(self, env):
        body = env.preview(name="").json()
        assert body["name_problem"] == "Give the join a name."
        assert body["result_tag"] is None

    def test_create_needs_a_name(self, env):
        response = env.create(name="")
        assert response.status_code == 422
        assert _code(response) == "invalid_name"

    def test_create_needs_columns(self, env):
        response = env.create(on_columns=[])
        assert response.status_code == 422
        assert _code(response) == "invalid_columns"

    def test_a_name_in_use_is_409_and_the_preview_says_so(self, env):
        env.create_ok()
        again = env.create()
        assert again.status_code == 409
        assert _code(again) == "name_taken"
        assert "already has a join" in again.json()["detail"]["message"]
        assert "already has a join" in env.preview().json()["name_problem"]
        assert len(env.joins()) == 1

    def test_a_name_whose_table_tag_is_in_use_is_409(self, env):
        env.add_table("joined_taken", physical_features())
        response = env.create(name="taken")
        assert response.status_code == 409
        assert _code(response) == "name_taken"
        assert "joined_taken" in response.json()["detail"]["message"]
        assert env.joins() == []

    def test_name_problem_is_none_for_a_free_name(self, env):
        assert name_problem(env.project(), "fresh-name_2") is None


def test_a_request_has_defaults():
    request = JoinRequest(left_dc_id="a", right_dc_id="b")
    assert request.how == "left"
    assert request.on_columns == [] and request.name == ""
