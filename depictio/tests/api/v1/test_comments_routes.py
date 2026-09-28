"""Comment threads and annotations: the real route functions, against mongomock.

Routes are called directly (like ``test_dashboard_save_timestamps.py``); the
permission helpers from the dashboards router run for real against a seeded
``projects`` collection, so the editor/viewer/anonymous gates are exercised
rather than mocked away. One HTTP test checks the 201-vs-200 dedupe status.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.comments_endpoints import cascade
from depictio.api.v1.endpoints.comments_endpoints import routes as cr
from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.models.comments import (
    CommentCreate,
    CommentUpdate,
    ThreadCreate,
    ThreadReview,
    ThreadUpdate,
)

DC = ObjectId()
BOT = {"name": "bot", "run_id": "r1"}
RANGE = {"kind": "range", "geometry": {"kind": "x_range", "x0": 1, "x1": 2}, "label": "band"}


def _user(*, admin=False, anonymous=False):
    return SimpleNamespace(
        id=ObjectId(),
        email=f"{ObjectId()}@example.com",
        is_admin=admin,
        is_anonymous=anonymous,
    )


@pytest.fixture
def world():
    database = mongomock.MongoClient()["depictio_test"]
    hashes = {str(DC): "h1"}
    with (
        patch.object(cr, "comment_threads_collection", database["comment_threads"]),
        patch.object(cr, "dashboards_collection", database["dashboards"]),
        patch.object(cascade, "comment_threads_collection", database["comment_threads"]),
        patch.object(dash_routes, "dashboards_collection", database["dashboards"]),
        patch.object(dash_routes, "projects_collection", database["projects"]),
        patch.object(cr, "_get_aggregation_hash", side_effect=lambda dc: hashes.get(dc)),
        patch.object(settings.auth, "single_user_mode", False),
    ):
        editor, editor2, owner, viewer = _user(), _user(), _user(), _user()
        project_id, main, child = ObjectId(), ObjectId(), ObjectId()
        database["projects"].insert_one(
            {
                "_id": project_id,
                "is_public": False,
                "permissions": {
                    "owners": [{"_id": owner.id}],
                    "editors": [{"_id": editor.id}, {"_id": editor2.id}],
                    "viewers": [{"_id": viewer.id}],
                },
            }
        )
        database["dashboards"].insert_many(
            [
                {
                    "dashboard_id": main,
                    "project_id": project_id,
                    "is_main_tab": True,
                    "stored_metadata": [
                        {"index": "c1", "dc_id": DC, "title": "Scatter"},
                        {"index": "c3", "title": "Other"},
                    ],
                },
                {
                    "dashboard_id": child,
                    "project_id": project_id,
                    "is_main_tab": False,
                    "parent_dashboard_id": main,
                    "stored_metadata": [{"index": "c2", "title": "Table"}],
                },
            ]
        )
        yield SimpleNamespace(
            db=database,
            hashes=hashes,
            project_id=project_id,
            main=str(main),
            child=str(child),
            editor=editor,
            editor2=editor2,
            owner=owner,
            viewer=viewer,
            anonymous=_user(anonymous=True),
        )


def run(coro):
    return asyncio.run(coro)


def create(w, user=None, *, response=None, **body):
    body.setdefault("anchor", {"dashboard_id": w.main, "component_index": "c1"})
    if "body" not in body and "annotation" not in body:
        body["body"] = "hello"
    return run(
        cr.create_thread(
            body=ThreadCreate(**body),
            response=response or Response(status_code=201),
            current_user=user or w.editor,
        )
    )


def listing(w, user=None, dashboard_id=None, **kw):
    kw.setdefault("scope", "tab")
    kw.setdefault("component_index", None)
    kw.setdefault("status", None)
    return run(cr.list_threads(dashboard_id or w.main, current_user=user or w.editor, **kw))


def status_of(exc_info):
    return exc_info.value.status_code


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------
class TestAccess:
    def test_can_comment_for_editor_and_owner(self, world):
        for u in (world.editor, world.owner):
            assert run(cr.get_comment_access(world.main, current_user=u)).can_comment

    @pytest.mark.parametrize("who", ["viewer", "anonymous", "none"])
    def test_cannot_comment_otherwise(self, world, who):
        user = None if who == "none" else getattr(world, who)
        assert not run(cr.get_comment_access(world.main, current_user=user)).can_comment

    def test_missing_or_malformed_dashboard_is_false(self, world):
        for dash in (str(ObjectId()), "garbage"):
            assert not run(cr.get_comment_access(dash, current_user=world.editor)).can_comment

    @pytest.mark.parametrize("who", ["viewer", "anonymous"])
    def test_list_and_create_are_forbidden(self, world, who):
        user = getattr(world, who)
        with pytest.raises(HTTPException) as e:
            listing(world, user)
        assert status_of(e) == 403
        with pytest.raises(HTTPException) as e:
            create(world, user)
        assert status_of(e) == 403
        with pytest.raises(HTTPException) as e:
            run(cr.count_threads(world.main, current_user=user))
        assert status_of(e) == 403


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------
class TestThreads:
    def test_create_fills_fingerprints_and_ignores_client_values(self, world):
        t = create(
            world,
            anchor={
                "dashboard_id": world.main,
                "component_index": "c1",
                "component_hash": "forged",
                "data_hashes": {"x": "y"},
            },
        )
        assert t.status == "open"
        assert t.created_by.kind == "human" and t.created_by.user_id == str(world.editor.id)
        assert t.anchor.component_hash not in (None, "forged")
        assert t.anchor.data_hashes == {str(DC): "h1"}
        assert t.anchor.component_title == "Scatter"
        assert t.project_id == str(world.project_id) and t.parent_dashboard_id == world.main
        assert [c.body for c in t.comments] == ["hello"]
        stored = world.db["comment_threads"].find_one({"_id": ObjectId(t.id)})
        assert stored["anchor"]["dashboard_id"] == world.main
        assert "dedupe_key" not in stored and "run_id" not in stored

    def test_unknown_component_is_rejected(self, world):
        with pytest.raises(HTTPException) as e:
            create(world, anchor={"dashboard_id": world.main, "component_index": "nope"})
        assert status_of(e) == 400

    def test_missing_dashboard_is_404(self, world):
        with pytest.raises(HTTPException) as e:
            create(world, anchor={"dashboard_id": str(ObjectId())})
        assert status_of(e) == 404

    def test_annotations_are_numbered_per_tab(self, world):
        a = create(world, annotation=RANGE)
        b = create(world, anchor={"dashboard_id": world.main}, annotation=RANGE)
        plain = create(world)
        other_tab = create(
            world, anchor={"dashboard_id": world.child, "component_index": "c2"}, annotation=RANGE
        )
        assert (a.number, b.number, plain.number, other_tab.number) == (1, 2, None, 1)

    def test_list_sorts_hides_rejected_and_filters(self, world):
        first = create(world)
        tab = create(world, anchor={"dashboard_id": world.main})
        rejected = create(world, agent=BOT)
        run(
            cr.review_thread(
                rejected.id, ThreadReview(decision="rejected"), current_user=world.editor
            )
        )
        assert [t.id for t in listing(world)] == [first.id, tab.id]
        assert [t.id for t in listing(world, status="rejected")] == [rejected.id]
        assert [t.id for t in listing(world, component_index="__tab__")] == [tab.id]
        assert [t.id for t in listing(world, component_index="c1")] == [first.id]

    def test_family_scope_spans_tabs(self, world):
        create(world)
        create(world, anchor={"dashboard_id": world.child, "component_index": "c2"})
        assert len(listing(world, dashboard_id=world.child)) == 1
        assert len(listing(world, dashboard_id=world.child, scope="family")) == 2

    def test_resolve_and_reopen(self, world):
        t = create(world)
        r = run(cr.update_thread(t.id, ThreadUpdate(status="resolved"), current_user=world.editor2))
        assert r.status == "resolved" and r.resolved_by == str(world.editor2.id) and r.resolved_at
        r = run(cr.update_thread(t.id, ThreadUpdate(status="open"), current_user=world.editor))
        assert r.status == "open" and r.resolved_by is None and r.resolved_at is None

    def test_empty_update_is_400(self, world):
        t = create(world)
        with pytest.raises(HTTPException) as e:
            run(cr.update_thread(t.id, ThreadUpdate(), current_user=world.editor))
        assert status_of(e) == 400

    def test_annotation_patch(self, world):
        plain = create(world)
        with pytest.raises(HTTPException) as e:
            run(
                cr.update_thread(
                    plain.id, ThreadUpdate(annotation={"label": "x"}), current_user=world.editor
                )
            )
        assert status_of(e) == 404

        a = create(world, annotation=RANGE)
        bad = {"geometry": {"kind": "ref_line", "axis": "x", "value": 1}}
        with pytest.raises(HTTPException) as e:
            run(cr.update_thread(a.id, ThreadUpdate(annotation=bad), current_user=world.editor))
        assert status_of(e) == 422

        r = run(
            cr.update_thread(
                a.id,
                ThreadUpdate(annotation={"label": "new", "published": True}),
                current_user=world.editor,
            )
        )
        assert r.annotation.label == "new" and r.annotation.published
        assert r.annotation.geometry.kind == "x_range"

    def test_annotation_patch_style_and_geometry(self, world):
        points = {
            "kind": "points",
            "geometry": {
                "kind": "points",
                "coords": [{"x": 1, "y": 2}],
                "region": {"shape": "box", "x0": 0, "x1": 2, "y0": 0, "y1": 3},
            },
            "label": "cluster",
            "style": {"width": 3, "fill_opacity": 0.2},
        }
        a = create(world, annotation=points)
        assert a.annotation.geometry.region.shape == "box"

        # Style replaces wholesale; explicit nulls leave fields untouched.
        r = run(
            cr.update_thread(
                a.id,
                ThreadUpdate(
                    annotation={"style": {"fill_opacity": 0.4}, "label": None, "color": None}
                ),
                current_user=world.editor,
            )
        )
        assert r.annotation.style.fill_opacity == 0.4
        assert r.annotation.style.width is None
        assert r.annotation.label == "cluster"

        # Dropping the region goes through a full geometry.
        r = run(
            cr.update_thread(
                a.id,
                ThreadUpdate(
                    annotation={"geometry": {"kind": "points", "coords": [{"x": 1, "y": 2}]}}
                ),
                current_user=world.editor,
            )
        )
        assert r.annotation.geometry.region is None
        assert r.annotation.style.fill_opacity == 0.4

    def test_delete_thread_permissions(self, world):
        t = create(world)
        with pytest.raises(HTTPException) as e:
            run(cr.delete_thread(t.id, current_user=world.editor2))
        assert status_of(e) == 403
        run(cr.delete_thread(t.id, current_user=world.owner))
        assert world.db["comment_threads"].count_documents({}) == 0

        mine = create(world)
        run(cr.delete_thread(mine.id, current_user=world.editor))
        agent = create(world, agent=BOT)
        run(cr.delete_thread(agent.id, current_user=world.editor))  # on_behalf_of
        assert world.db["comment_threads"].count_documents({}) == 0

    def test_unknown_thread_is_404(self, world):
        for tid in (str(ObjectId()), "garbage"):
            with pytest.raises(HTTPException) as e:
                run(cr.delete_thread(tid, current_user=world.editor))
            assert status_of(e) == 404


# ---------------------------------------------------------------------------
# Replies
# ---------------------------------------------------------------------------
class TestComments:
    def test_reply_edit_and_delete(self, world):
        t = create(world)
        r = run(cr.add_comment(t.id, CommentCreate(body="reply"), current_user=world.editor2))
        cid = r.comments[-1].id
        assert r.comments[-1].author.user_id == str(world.editor2.id)

        with pytest.raises(HTTPException) as e:
            run(cr.edit_comment(t.id, cid, CommentUpdate(body="x"), current_user=world.editor))
        assert status_of(e) == 403
        with pytest.raises(HTTPException) as e:
            run(cr.delete_comment(t.id, cid, current_user=world.editor))
        assert status_of(e) == 403

        r = run(
            cr.edit_comment(t.id, cid, CommentUpdate(body="edited"), current_user=world.editor2)
        )
        assert r.comments[-1].body == "edited" and r.comments[-1].edited_at
        assert r.comments[0].body == "hello"  # the other comment is untouched

        r = run(cr.delete_comment(t.id, cid, current_user=world.editor2))
        assert r.comments[-1].deleted and r.comments[-1].body == ""
        with pytest.raises(HTTPException) as e:
            run(cr.edit_comment(t.id, cid, CommentUpdate(body="y"), current_user=world.editor2))
        assert status_of(e) == 409

    def test_project_owner_can_delete_any_comment(self, world):
        t = create(world)
        r = run(cr.delete_comment(t.id, t.comments[0].id, current_user=world.owner))
        assert r.comments[0].deleted

    def test_unknown_comment_is_404(self, world):
        t = create(world)
        with pytest.raises(HTTPException) as e:
            run(cr.delete_comment(t.id, "nope", current_user=world.editor))
        assert status_of(e) == 404

    def test_comment_cap(self, world):
        t = create(world)
        with patch.object(cr, "MAX_COMMENTS_PER_THREAD", 2):
            run(cr.add_comment(t.id, CommentCreate(body="2"), current_user=world.editor))
            with pytest.raises(HTTPException) as e:
                run(cr.add_comment(t.id, CommentCreate(body="3"), current_user=world.editor))
        assert status_of(e) == 409


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
class TestAgents:
    def agent_thread(self, w, **kw):
        return create(w, annotation=RANGE, agent={"name": "bot", "run_id": "r1"}, **kw)

    def test_agent_thread_is_proposed_on_behalf_of_caller(self, world):
        t = self.agent_thread(world)
        assert t.status == "proposed" and t.run_id == "r1"
        assert t.created_by.kind == "agent"
        assert t.created_by.agent.on_behalf_of == str(world.editor.id)

    def test_publish_and_resolve_refused_while_proposed(self, world):
        t = self.agent_thread(world)
        with pytest.raises(HTTPException) as e:
            run(
                cr.update_thread(
                    t.id, ThreadUpdate(annotation={"published": True}), current_user=world.editor
                )
            )
        assert status_of(e) == 409
        with pytest.raises(HTTPException) as e:
            run(cr.update_thread(t.id, ThreadUpdate(status="resolved"), current_user=world.editor))
        assert status_of(e) == 409

    def test_accept_then_publish(self, world):
        t = self.agent_thread(world)
        r = run(
            cr.review_thread(
                t.id, ThreadReview(decision="accepted", reason="ok"), current_user=world.editor2
            )
        )
        assert r.status == "open" and r.review.by == str(world.editor2.id)
        assert r.review.reason == "ok"
        r = run(
            cr.update_thread(
                t.id, ThreadUpdate(annotation={"published": True}), current_user=world.editor
            )
        )
        assert r.annotation.published
        with pytest.raises(HTTPException) as e:
            run(
                cr.review_thread(t.id, ThreadReview(decision="rejected"), current_user=world.editor)
            )
        assert status_of(e) == 409

    def test_reject_forces_unpublished(self, world):
        t = self.agent_thread(world)
        # Simulate a stored published flag (the API would never let it be set).
        world.db["comment_threads"].update_one(
            {"_id": ObjectId(t.id)}, {"$set": {"annotation.published": True}}
        )
        r = run(
            cr.review_thread(t.id, ThreadReview(decision="rejected"), current_user=world.editor)
        )
        assert r.status == "rejected" and r.annotation.published is False

    def test_human_thread_cannot_be_reviewed(self, world):
        t = create(world)
        with pytest.raises(HTTPException) as e:
            run(
                cr.review_thread(t.id, ThreadReview(decision="accepted"), current_user=world.editor)
            )
        assert status_of(e) == 409

    def test_dedupe_updates_instead_of_duplicating(self, world):
        resp1, resp2, resp3 = (
            Response(status_code=201),
            Response(status_code=201),
            Response(status_code=201),
        )
        first = self.agent_thread(world, body="claim", dedupe_key="k", response=resp1)
        again = self.agent_thread(world, body="claim v2", dedupe_key="k", response=resp2)
        same = self.agent_thread(world, body="claim v2", dedupe_key="k", response=resp3)
        assert (resp1.status_code, resp2.status_code, resp3.status_code) == (201, 200, 200)
        assert first.id == again.id == same.id
        assert [c.body for c in same.comments] == ["claim", "claim v2"]
        assert same.number == first.number
        assert world.db["comment_threads"].count_documents({}) == 1

    def test_dedupe_status_codes_over_http(self, world):
        app = FastAPI()
        app.include_router(cr.comments_endpoint_router, prefix="/comments")
        app.dependency_overrides[get_user_or_anonymous] = lambda: world.editor
        client = TestClient(app)
        body = {
            "anchor": {"dashboard_id": world.main, "component_index": "c1"},
            "body": "x",
            "dedupe_key": "k",
            "agent": {"name": "bot", "run_id": "r1"},
        }
        assert client.post("/comments/threads", json=body).status_code == 201
        assert client.post("/comments/threads", json=body).status_code == 200

    def test_run_cap(self, world):
        with patch.object(cr, "MAX_THREADS_PER_RUN", 3):
            for _ in range(3):
                create(world, agent={"name": "bot", "run_id": "r9"})
            with pytest.raises(HTTPException) as e:
                create(world, agent={"name": "bot", "run_id": "r9"})
            create(world, agent={"name": "bot", "run_id": "other"})
        assert status_of(e) == 429

    def test_run_cap_is_per_user(self, world):
        with patch.object(cr, "MAX_THREADS_PER_RUN", 2):
            for _ in range(2):
                create(world, agent={"name": "bot", "run_id": "r9"})
            # Same run id, launched by someone else: a separate budget.
            create(world, world.editor2, agent={"name": "bot", "run_id": "r9"})

    def test_agent_requires_run_id(self, world):
        app = FastAPI()
        app.include_router(cr.comments_endpoint_router, prefix="/comments")
        app.dependency_overrides[get_user_or_anonymous] = lambda: world.editor
        body = {
            "anchor": {"dashboard_id": world.main, "component_index": "c1"},
            "body": "x",
            "agent": {"name": "bot"},
        }
        assert TestClient(app).post("/comments/threads", json=body).status_code == 422

    def dedupe(self, w, user=None, **kw):
        resp = Response(status_code=201)
        t = create(
            w, user, response=resp, annotation=RANGE, agent=BOT, dedupe_key="k", body="claim", **kw
        )
        return t, resp.status_code

    def test_dedupe_ignores_other_users_proposals(self, world):
        first, _ = self.dedupe(world)
        other, code = self.dedupe(world, world.editor2)
        assert code == 201 and other.id != first.id

    def test_dedupe_ignores_human_threads(self, world):
        human = create(world, dedupe_key="k", body="claim")
        agent, code = self.dedupe(world)
        assert code == 201 and agent.id != human.id
        # ...and a human request never updates an agent proposal.
        again = create(world, dedupe_key="k", body="claim")
        assert again.id not in (human.id, agent.id)
        assert world.db["comment_threads"].count_documents({}) == 3

    def test_dedupe_after_acceptance_makes_a_fresh_proposal(self, world):
        first, _ = self.dedupe(world)
        run(
            cr.review_thread(first.id, ThreadReview(decision="accepted"), current_user=world.editor)
        )
        fresh, code = self.dedupe(world)
        assert code == 201 and fresh.id != first.id and fresh.status == "proposed"

    def test_dedupe_reproposes_a_rejected_thread(self, world):
        first, _ = self.dedupe(world)
        run(
            cr.review_thread(first.id, ThreadReview(decision="rejected"), current_user=world.editor)
        )
        again, code = self.dedupe(world)
        assert code == 200 and again.id == first.id
        assert again.status == "proposed" and again.review is None

    def test_dedupe_never_publishes(self, world):
        first, _ = self.dedupe(world)
        # A stored published flag (never reachable through the API) is cleared.
        world.db["comment_threads"].update_one(
            {"_id": ObjectId(first.id)}, {"$set": {"annotation.published": True}}
        )
        again, code = self.dedupe(world)
        assert code == 200 and again.annotation.published is False

    def test_human_edit_of_agent_annotation_is_recorded(self, world):
        t = self.agent_thread(world)
        assert t.human_edited is False
        r = run(
            cr.update_thread(
                t.id, ThreadUpdate(annotation={"label": "fixed"}), current_user=world.editor
            )
        )
        assert r.human_edited is True

    def test_publishing_alone_is_not_an_edit(self, world):
        t = self.agent_thread(world)
        run(cr.review_thread(t.id, ThreadReview(decision="accepted"), current_user=world.editor))
        r = run(
            cr.update_thread(
                t.id, ThreadUpdate(annotation={"published": True}), current_user=world.editor
            )
        )
        assert r.human_edited is False

    def test_human_thread_edit_is_not_flagged(self, world):
        t = create(world, annotation=RANGE)
        r = run(
            cr.update_thread(
                t.id, ThreadUpdate(annotation={"label": "x"}), current_user=world.editor
            )
        )
        assert r.human_edited is False

    def test_no_replies_on_rejected_thread(self, world):
        t = self.agent_thread(world)
        run(cr.review_thread(t.id, ThreadReview(decision="rejected"), current_user=world.editor))
        with pytest.raises(HTTPException) as e:
            run(cr.add_comment(t.id, CommentCreate(body="hi"), current_user=world.editor))
        assert status_of(e) == 409


# ---------------------------------------------------------------------------
# Staleness and re-attachment
# ---------------------------------------------------------------------------
class TestStaleness:
    def one(self, w, tid, **kw):
        return next(t for t in listing(w, **kw) if t.id == tid)

    def test_fresh_thread_is_not_stale(self, world):
        t = create(world)
        s = self.one(world, t.id).staleness
        assert not (s.component_missing or s.component_changed or s.data_changed)

    def test_component_and_data_changes(self, world):
        t = create(world)
        world.db["dashboards"].update_one(
            {"dashboard_id": ObjectId(world.main)},
            {"$set": {"stored_metadata.0.title": "Renamed"}},
        )
        s = self.one(world, t.id).staleness
        assert s.component_changed and not s.data_changed

        world.hashes[str(DC)] = "h2"
        assert self.one(world, t.id).staleness.data_changed

    def test_layout_changes_do_not_count(self, world):
        t = create(world)
        world.db["dashboards"].update_one(
            {"dashboard_id": ObjectId(world.main)}, {"$set": {"stored_metadata.0.layout": {"x": 3}}}
        )
        assert not self.one(world, t.id).staleness.component_changed

    def test_unknown_current_hash_is_ignored(self, world):
        t = create(world)
        world.hashes.pop(str(DC))
        assert not self.one(world, t.id).staleness.data_changed

    def test_missing_component(self, world):
        t = create(world)
        world.db["dashboards"].update_one(
            {"dashboard_id": ObjectId(world.main)},
            {"$set": {"stored_metadata": [{"index": "c3", "title": "Other"}]}},
        )
        assert self.one(world, t.id).staleness.component_missing

    def test_unique_title_reattaches_everywhere(self, world):
        t = create(world, annotation=RANGE, body="x")
        run(
            cr.update_thread(
                t.id, ThreadUpdate(annotation={"published": True}), current_user=world.editor
            )
        )
        # A re-import regenerated the index; the title is unchanged.
        world.db["dashboards"].update_one(
            {"dashboard_id": ObjectId(world.main)},
            {"$set": {"stored_metadata.0.index": "c1-new"}},
        )
        pub = run(cr.list_published_annotations(world.main, current_user=world.viewer))
        assert pub[0].component_index == "c1-new"
        stored = world.db["comment_threads"].find_one({"_id": ObjectId(t.id)})
        assert stored["anchor"]["component_index"] == "c1"  # viewer reads never write
        counts = run(cr.count_threads(world.main, current_user=world.editor))
        assert counts["open"] == {"c1-new": 1}
        got = listing(world, component_index="c1-new")
        assert [x.id for x in got] == [t.id]
        assert not got[0].staleness.component_missing
        stored = world.db["comment_threads"].find_one({"_id": ObjectId(t.id)})
        assert stored["anchor"]["component_index"] == "c1-new"

    def test_ambiguous_title_stays_missing(self, world):
        t = create(world)
        world.db["dashboards"].update_one(
            {"dashboard_id": ObjectId(world.main)},
            {
                "$set": {
                    "stored_metadata": [
                        {"index": "a", "title": "Scatter"},
                        {"index": "b", "title": "Scatter"},
                    ]
                }
            },
        )
        got = self.one(world, t.id)
        assert got.anchor.component_index == "c1" and got.staleness.component_missing
        stored = world.db["comment_threads"].find_one({"_id": ObjectId(t.id)})
        assert stored["anchor"]["component_index"] == "c1"


# ---------------------------------------------------------------------------
# Published annotations and counts
# ---------------------------------------------------------------------------
class TestPublishedAndCounts:
    def publish(self, w, tid):
        run(
            cr.update_thread(
                tid, ThreadUpdate(annotation={"published": True}), current_user=w.editor
            )
        )

    def test_only_published_accepted_threads_are_exposed(self, world):
        shown = create(world, annotation=RANGE, body="secret discussion")
        self.publish(world, shown.id)
        resolved = create(world, annotation=RANGE)
        self.publish(world, resolved.id)
        run(
            cr.update_thread(
                resolved.id, ThreadUpdate(status="resolved"), current_user=world.editor
            )
        )
        create(world, annotation=RANGE)  # unpublished
        create(world, annotation=RANGE, agent=BOT)  # proposed
        rejected = create(world, annotation=RANGE, agent=BOT)
        run(
            cr.review_thread(
                rejected.id, ThreadReview(decision="rejected"), current_user=world.editor
            )
        )
        # Even a stored published flag on a rejected thread stays hidden.
        world.db["comment_threads"].update_one(
            {"_id": ObjectId(rejected.id)}, {"$set": {"annotation.published": True}}
        )

        pub = run(cr.list_published_annotations(world.main, current_user=world.viewer))
        assert [p.thread_id for p in pub] == [shown.id, resolved.id]
        dumped = pub[0].model_dump()
        assert "comments" not in dumped and dumped["label"] == "band"

    def test_published_requires_viewer_access(self, world):
        with pytest.raises(HTTPException) as e:
            run(cr.list_published_annotations(world.main, current_user=world.anonymous))
        assert status_of(e) == 403
        world.db["projects"].update_one({"_id": world.project_id}, {"$set": {"is_public": True}})
        assert run(cr.list_published_annotations(world.main, current_user=world.anonymous)) == []
        with pytest.raises(HTTPException) as e:
            run(cr.list_published_annotations(str(ObjectId()), current_user=world.viewer))
        assert status_of(e) == 404

    def test_counts(self, world):
        create(world)
        create(world)
        create(world, anchor={"dashboard_id": world.main})
        create(world, agent=BOT)
        resolved = create(world, anchor={"dashboard_id": world.main, "component_index": "c3"})
        run(
            cr.update_thread(
                resolved.id, ThreadUpdate(status="resolved"), current_user=world.editor
            )
        )
        create(world, anchor={"dashboard_id": world.child, "component_index": "c2"})
        counts = run(cr.count_threads(world.main, current_user=world.editor))
        assert counts == {"open": {"c1": 2, "__tab__": 1}, "proposed": {"c1": 1}}


# ---------------------------------------------------------------------------
# Cascade helpers and their call sites
# ---------------------------------------------------------------------------
class TestCascade:
    def test_helpers(self, world):
        create(world)
        create(world, anchor={"dashboard_id": world.child, "component_index": "c2"})
        assert cascade.delete_threads_for_dashboards([ObjectId(world.child)]) == 1
        assert cascade.delete_threads_for_dashboards([]) == 0
        assert cascade.delete_threads_for_project(world.project_id) == 1
        assert world.db["comment_threads"].count_documents({}) == 0

    def test_helpers_swallow_failures(self):
        class Boom:
            def delete_many(self, *_a, **_k):
                raise RuntimeError("down")

        with patch.object(cascade, "comment_threads_collection", Boom()):
            assert cascade.delete_threads_for_dashboards(["x"]) == 0
            assert cascade.delete_threads_for_project("p") == 0

    def test_delete_dashboard_drops_threads_of_all_tabs(self, world):
        create(world)
        create(world, anchor={"dashboard_id": world.child, "component_index": "c2"})
        with (
            patch.object(dash_routes, "check_dashboard_mutation_permission", return_value=True),
            patch.object(dash_routes, "delete_logo_asset"),
        ):
            run(dash_routes.delete_dashboard(ObjectId(world.main), current_user=world.owner))
        assert world.db["comment_threads"].count_documents({}) == 0

    def test_delete_tab_drops_its_threads_only(self, world):
        create(world)
        create(world, anchor={"dashboard_id": world.child, "component_index": "c2"})
        with patch.object(dash_routes, "check_dashboard_mutation_permission", return_value=True):
            run(dash_routes.delete_tab(ObjectId(world.child), current_user=world.editor))
        remaining = list(world.db["comment_threads"].find())
        assert [d["anchor"]["dashboard_id"] for d in remaining] == [world.main]


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------
def test_backup_leaves_out_threads_of_temporary_users_dashboards():
    from contextlib import ExitStack

    from depictio.api.v1.endpoints.backup_endpoints import routes as backup_routes

    database = mongomock.MongoClient()["depictio_backup_test"]
    temp_user, real_user = ObjectId(), ObjectId()
    temp_dash, real_dash = ObjectId(), ObjectId()
    database["users"].insert_many(
        [{"_id": temp_user, "is_temporary": True}, {"_id": real_user, "is_temporary": False}]
    )
    database["dashboards"].insert_many(
        [
            {"dashboard_id": temp_dash, "permissions": {"owners": [{"_id": temp_user}]}},
            {"dashboard_id": real_dash, "permissions": {"owners": [{"_id": real_user}]}},
        ]
    )
    database["comment_threads"].insert_many(
        [
            {"_id": ObjectId(), "anchor": {"dashboard_id": str(temp_dash)}},
            {"_id": ObjectId(), "anchor": {"dashboard_id": str(real_dash)}},
        ]
    )
    names = [
        "users",
        "projects",
        "dashboards",
        "data_collections",
        "workflows",
        "files",
        "deltatables",
        "runs",
        "groups",
        "instance_settings",
        "branding_assets",
        "comment_threads",
    ]
    with ExitStack() as stack:
        for name in names:
            stack.enter_context(patch.object(backup_routes, f"{name}_collection", database[name]))
        backup = asyncio.run(backup_routes._create_mongodb_backup("admin@example.com"))

    threads = backup["data"]["comment_threads"]
    assert [t["anchor"]["dashboard_id"] for t in threads] == [str(real_dash)]
    assert [str(d["dashboard_id"]) for d in backup["data"]["dashboards"]] == [str(real_dash)]
