"""Owner-level permissions on the legacy DELETE /datacollections/delete route.

Deletion cannot be undone, so the route must require owner level, like
``utils._delete_data_collection_by_id``: a viewer (direct, through a group,
or via a public project) gets the same 404 as for a missing workflow, while
an owner — direct or through a group — and a sysadmin still delete.

The route runs end to end against a fake Mongo that honours the access
predicate ``build_access_query`` builds, so the refusal comes from the real
``validate_workflow_and_collection``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.datacollections_endpoints.routes import delete_datacollection

ROUTES = "depictio.api.v1.endpoints.datacollections_endpoints.routes"

WF_ID = ObjectId()
DC_ID = ObjectId()
GROUP_ID = ObjectId()


def _user(*, admin: bool = False):
    return SimpleNamespace(id=ObjectId(), email="u@example.org", is_admin=admin, is_anonymous=False)


def _workflow_doc(**grants):
    """A workflow document as the workflows collection stores it."""
    entries = lambda ids: [{"_id": i} for i in ids]  # noqa: E731

    return {
        "_id": WF_ID,
        "name": "wf",
        "engine": {"name": "nextflow"},
        "is_public": grants.get("public", False),
        "permissions": {
            "owners": entries(grants.get("owners", ())),
            "editors": entries(grants.get("editors", ())),
            "viewers": entries(grants.get("viewers", ())),
            "group_owners": entries(grants.get("group_owners", ())),
            "group_editors": entries(grants.get("group_editors", ())),
            "group_viewers": entries(grants.get("group_viewers", ())),
        },
        "data_collections": [
            {
                "_id": DC_ID,
                "data_collection_tag": "samples",
                "config": {
                    "type": "table",
                    "scan": {"mode": "single", "scan_parameters": {"filename": "samples.csv"}},
                    "dc_specific_properties": {"format": "csv"},
                },
            }
        ],
        "data_location": {"structure": "flat", "locations": ["/data"]},
    }


def _values_at(node, parts):
    """Every value at a dotted Mongo path, descending through lists."""
    if not parts:
        return [node]
    head, rest = parts[0], parts[1:]
    if isinstance(node, dict):
        return _values_at(node[head], rest) if head in node else []
    if isinstance(node, list):
        out: list = []
        for element in node:
            out.extend(_values_at(element, parts))
        return out
    return []


def _clause_matches(doc: dict, clause: dict) -> bool:
    for key, expected in clause.items():
        values = _values_at(doc, key.split("."))
        if isinstance(expected, dict) and "$in" in expected:
            if not any(value in expected["$in"] for value in values):
                return False
        elif expected not in values:
            return False
    return True


def _matches(doc: dict, query: dict) -> bool:
    """Evaluate a Mongo query the way the server would."""
    for key, expected in query.items():
        if key == "$or":
            if not any(_clause_matches(doc, clause) for clause in expected):
                return False
        elif key == "_id":
            if doc.get("_id") != expected:
                return False
        elif not _clause_matches(doc, {key: expected}):
            return False
    return True


def _delete(user, workflow_doc, groups=()):
    """Run the legacy delete route against ``workflow_doc``; True if allowed."""
    collection = MagicMock()

    def find_one(query, *args, **kwargs):
        if workflow_doc is None or not _matches(workflow_doc, query):
            return None
        if "data_collections._id" in query:
            return {"data_collections": [workflow_doc["data_collections"][0]]}
        # The access predicate has already decided the match above; hand the
        # validator the projection the Workflow model can parse.
        return {
            key: value
            for key, value in workflow_doc.items()
            if key not in ("permissions", "is_public")
        }

    collection.find_one.side_effect = find_one
    with (
        patch(f"{ROUTES}.workflows_collection", collection),
        patch(f"{ROUTES}.get_user_group_ids", return_value=list(groups)),
        patch(f"{ROUTES}.assert_dc_project_unlocked"),
        patch(f"{ROUTES}.assert_workflow_project_unlocked"),
        patch(f"{ROUTES}._delete_orphan_links_for_dc", return_value=0),
    ):
        try:
            asyncio.run(delete_datacollection(str(WF_ID), str(DC_ID), user))
            return True, collection
        except HTTPException as exc:
            assert exc.status_code == 404
            return False, collection


class TestLegacyDeleteRoute:
    def test_a_direct_owner_still_deletes(self):
        owner = _user()
        allowed, collection = _delete(owner, _workflow_doc(owners=[owner.id]))
        assert allowed
        collection.update_one.assert_called_once()

    def test_a_group_owner_deletes(self):
        member = _user()
        allowed, collection = _delete(
            member, _workflow_doc(group_owners=[GROUP_ID]), groups=[GROUP_ID]
        )
        assert allowed
        collection.update_one.assert_called_once()

    def test_a_sysadmin_deletes_any_workflow(self):
        allowed, collection = _delete(_user(admin=True), _workflow_doc())
        assert allowed
        collection.update_one.assert_called_once()

    def test_a_direct_viewer_cannot_delete(self):
        viewer = _user()
        allowed, collection = _delete(viewer, _workflow_doc(viewers=[viewer.id]))
        assert not allowed
        collection.update_one.assert_not_called()

    def test_editors_group_members_and_public_visitors_cannot_delete(self):
        editor = _user()
        for user, doc, groups in (
            (editor, _workflow_doc(editors=[editor.id]), ()),
            (_user(), _workflow_doc(group_editors=[GROUP_ID]), [GROUP_ID]),
            (_user(), _workflow_doc(group_viewers=[GROUP_ID]), [GROUP_ID]),
            (_user(), _workflow_doc(public=True), ()),
        ):
            allowed, collection = _delete(user, doc, groups)
            assert not allowed
            collection.update_one.assert_not_called()

    def test_a_missing_workflow_answers_the_same_404(self):
        allowed, _ = _delete(_user(admin=True), None)
        assert not allowed
