"""The comments service directly (agent authorship, question threads), plus the
REST routes under a scoped token.

Same set-up as ``test_comments_routes.py``: mongomock collections, and the
dashboards router's permission helpers running for real against a seeded
``projects`` collection.
"""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException, Response
from pydantic import ValidationError

from depictio.api.v1 import db
from depictio.api.v1.agents import quotas
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.comments_endpoints import routes as cr
from depictio.api.v1.endpoints.comments_endpoints import service as svc
from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
from depictio.api.v1.endpoints.user_endpoints.token_scopes import (
    current_token_id,
    current_token_scopes,
)
from depictio.models.models.comments import (
    AgentInfo,
    CommentCreate,
    ThreadCreate,
    ThreadReview,
    ThreadUpdate,
)

DC = ObjectId()
RANGE = {"kind": "range", "geometry": {"kind": "x_range", "x0": 1, "x1": 2}, "label": "band"}


def _user():
    return SimpleNamespace(
        id=ObjectId(),
        email=f"{ObjectId()}@example.com",
        is_admin=False,
        is_anonymous=False,
    )


@pytest.fixture
def world():
    database = mongomock.MongoClient()["depictio_test"]
    with (
        patch.object(svc, "comment_threads_collection", database["comment_threads"]),
        patch.object(svc, "dashboards_collection", database["dashboards"]),
        patch.object(dash_routes, "dashboards_collection", database["dashboards"]),
        patch.object(dash_routes, "projects_collection", database["projects"]),
        patch.object(svc, "_get_aggregation_hash", return_value="h1"),
        patch.object(settings.auth, "single_user_mode", False),
    ):
        editor, other = _user(), _user()
        project_id, main = ObjectId(), ObjectId()
        database["projects"].insert_one(
            {
                "_id": project_id,
                "is_public": False,
                "permissions": {
                    "owners": [],
                    "editors": [{"_id": editor.id}, {"_id": other.id}],
                    "viewers": [],
                },
            }
        )
        database["dashboards"].insert_one(
            {
                "dashboard_id": main,
                "project_id": project_id,
                "is_main_tab": True,
                "stored_metadata": [{"index": "c1", "dc_id": DC, "title": "Scatter"}],
            }
        )
        yield SimpleNamespace(db=database, main=str(main), editor=editor, other=other)


def run(coro):
    return asyncio.run(coro)


def payload(w, **body):
    body.setdefault("anchor", {"dashboard_id": w.main, "component_index": "c1"})
    if "body" not in body and "annotation" not in body:
        body["body"] = "hello"
    return ThreadCreate(**body)


def agent(run_id="r1", name="analyst@1"):
    return AgentInfo(name=name, run_id=run_id)


@contextmanager
def scoped_token(*scopes):
    token = current_token_scopes.set(list(scopes))
    try:
        yield
    finally:
        current_token_scopes.reset(token)


# ---------------------------------------------------------------------------
# Agent authorship
# ---------------------------------------------------------------------------
class TestAgentThreads:
    def test_forces_agent_author_and_proposed(self, world):
        published = {**RANGE, "published": True}
        thread, created = run(
            svc.create_agent_thread(
                world.editor, payload(world, annotation=published, body="look"), agent()
            )
        )
        assert created
        assert thread.status == "proposed"
        assert thread.created_by.kind == "agent"
        assert thread.created_by.agent.name == "analyst@1"
        assert thread.created_by.agent.on_behalf_of == str(world.editor.id)
        assert thread.comments[0].author.kind == "agent"
        assert thread.run_id == "r1"
        assert thread.annotation.published is False

    def test_agent_overrides_payload_agent_and_needs_run_id(self, world):
        body = payload(world, agent={"name": "spoof", "run_id": "x"})
        thread, _ = run(svc.create_agent_thread(world.editor, body, agent()))
        assert thread.created_by.agent.name == "analyst@1" and thread.run_id == "r1"

        with pytest.raises(HTTPException) as e:
            run(svc.create_agent_thread(world.editor, payload(world), AgentInfo(name="a")))
        assert e.value.status_code == 422

    def test_run_cap(self, world):
        with patch.object(svc, "MAX_THREADS_PER_RUN", 2):
            for _ in range(2):
                run(svc.create_agent_thread(world.editor, payload(world), agent()))
            with pytest.raises(HTTPException) as e:
                run(svc.create_agent_thread(world.editor, payload(world), agent()))
            assert e.value.status_code == 429
            # Another run, or the same run id for another user, has its own budget.
            run(svc.create_agent_thread(world.editor, payload(world), agent("r2")))
            run(svc.create_agent_thread(world.other, payload(world), agent()))

    def test_dedupe_key_updates_own_proposal(self, world):
        first, created = run(
            svc.create_agent_thread(
                world.editor, payload(world, body="v1"), agent("r1"), dedupe_key="k"
            )
        )
        assert created
        again, created = run(
            svc.create_agent_thread(
                world.editor, payload(world, body="v2"), agent("r2"), dedupe_key="k"
            )
        )
        assert not created and again.id == first.id
        assert again.run_id == "r2"
        # Same agent, no human reply: the opening comment is rewritten, not appended to.
        assert [c.body for c in again.comments] == ["v2"]
        assert again.comments[0].id == first.comments[0].id
        assert again.comments[0].edited_at is not None
        assert again.comments[0].author.agent.run_id == "r2"
        assert again.updated_at > first.updated_at
        assert world.db["comment_threads"].count_documents({}) == 1

        # Another user's run never touches this proposal.
        _, created = run(
            svc.create_agent_thread(world.other, payload(world), agent("r1"), dedupe_key="k")
        )
        assert created

    def test_dedupe_resend_replaces_annotation_and_evidence(self, world):
        evidence = [{"claim": "mean 4", "values": {"mean": 4}}]
        first, _ = run(
            svc.create_agent_thread(
                world.editor,
                payload(world, body="v1", annotation=RANGE, evidence=evidence),
                agent(),
                dedupe_key="k",
            )
        )
        moved = {**RANGE, "geometry": {"kind": "x_range", "x0": 5, "x1": 6}}
        again, created = run(
            svc.create_agent_thread(
                world.editor,
                payload(world, body="v2", annotation=moved, evidence=[{"claim": "mean 5"}]),
                agent(),
                dedupe_key="k",
            )
        )
        assert not created and again.id == first.id and again.number == first.number
        assert again.annotation.geometry.x0 == 5 and again.annotation.published is False
        assert [e.claim for e in again.evidence] == ["mean 5"]
        assert [c.body for c in again.comments] == ["v2"]

    def test_dedupe_resend_appends_after_a_human_reply(self, world):
        first, _ = run(
            svc.create_agent_thread(
                world.editor, payload(world, body="v1"), agent(), dedupe_key="k"
            )
        )
        assert not svc.has_human_reply(first)
        run(svc.add_comment(world.other, first.id, CommentCreate(body="why?")))
        again, created = run(
            svc.create_agent_thread(
                world.editor, payload(world, body="v2"), agent("r2"), dedupe_key="k"
            )
        )
        assert not created and svc.has_human_reply(again)
        assert [c.body for c in again.comments] == ["v1", "why?", "v2"]
        assert again.comments[0].edited_at is None

    def test_dedupe_resend_by_another_agent_appends(self, world):
        run(
            svc.create_agent_thread(
                world.editor, payload(world, body="v1"), agent(), dedupe_key="k"
            )
        )
        again, _ = run(
            svc.create_agent_thread(
                world.editor, payload(world, body="v2"), agent(name="other@2"), dedupe_key="k"
            )
        )
        assert [c.body for c in again.comments] == ["v1", "v2"]

    def test_rejected_proposal_goes_back_to_review(self, world):
        first, _ = run(
            svc.create_agent_thread(world.editor, payload(world), agent(), dedupe_key="k")
        )
        run(svc.review_thread(world.editor, first.id, ThreadReview(decision="rejected")))
        again, created = run(
            svc.create_agent_thread(world.editor, payload(world), agent(), dedupe_key="k")
        )
        assert not created and again.status == "proposed" and again.review is None

    def test_agent_reply(self, world):
        thread, _ = run(svc.create_thread(world.editor, payload(world)))
        out = run(svc.agent_reply(world.editor, thread.id, "an answer", agent()))
        reply = out.comments[-1]
        assert reply.author.kind == "agent" and reply.body == "an answer"
        assert reply.author.agent.on_behalf_of == str(world.editor.id)
        with pytest.raises(HTTPException) as e:
            run(svc.agent_reply(world.editor, thread.id, "   ", agent()))
        assert e.value.status_code == 422

    def test_agent_cannot_review_or_publish(self, world):
        thread, _ = run(
            svc.create_agent_thread(world.editor, payload(world, annotation=RANGE), agent())
        )
        with pytest.raises(HTTPException) as e:
            run(
                svc.review_thread(
                    world.editor, thread.id, ThreadReview(decision="accepted"), agent=agent()
                )
            )
        assert e.value.status_code == 403

        accepted = run(
            svc.review_thread(world.editor, thread.id, ThreadReview(decision="accepted"))
        )
        assert accepted.status == "open"
        with pytest.raises(HTTPException) as e:
            run(
                svc.update_thread(
                    world.editor,
                    thread.id,
                    ThreadUpdate(annotation={"published": True}),
                    agent=agent(),
                )
            )
        assert e.value.status_code == 403
        # An agent reshaping its own annotation is not a human edit.
        out = run(
            svc.update_thread(
                world.editor, thread.id, ThreadUpdate(annotation={"label": "x"}), agent=agent()
            )
        )
        assert out.annotation.label == "x" and not out.human_edited

    def test_agent_edits_and_deletes_only_agent_content(self, world):
        human, _ = run(svc.create_thread(world.editor, payload(world)))
        human_comment = human.comments[0].id
        for call in (
            svc.edit_comment(
                world.editor, human.id, human_comment, CommentCreate(body="x"), agent=agent()
            ),
            svc.delete_comment(world.editor, human.id, human_comment, agent=agent()),
            svc.delete_thread(world.editor, human.id, agent=agent()),
        ):
            with pytest.raises(HTTPException) as e:
                run(call)
            assert e.value.status_code == 403

        mine, _ = run(svc.create_agent_thread(world.editor, payload(world), agent()))
        out = run(
            svc.edit_comment(
                world.editor, mine.id, mine.comments[0].id, CommentCreate(body="y"), agent=agent()
            )
        )
        assert out.comments[0].body == "y"
        run(svc.delete_thread(world.editor, mine.id, agent=agent()))
        assert world.db["comment_threads"].count_documents({}) == 1


# ---------------------------------------------------------------------------
# Question threads
# ---------------------------------------------------------------------------
class TestQuestions:
    def test_question_needs_a_body(self, world):
        with pytest.raises(ValidationError):
            payload(world, kind="question", annotation=RANGE)

    def test_kind_filter(self, world):
        question, _ = run(
            svc.create_agent_thread(
                world.editor, payload(world, kind="question", body="why?"), agent()
            )
        )
        assert question.kind == "question"
        comment, _ = run(svc.create_thread(world.editor, payload(world)))
        assert comment.kind == "comment"
        # A thread stored before kinds existed reads as a comment.
        legacy = world.db["comment_threads"].find_one({"_id": ObjectId(comment.id)})
        legacy.pop("kind")
        legacy["_id"] = ObjectId()
        world.db["comment_threads"].insert_one(legacy)

        def ids(kind):
            return {t.id for t in run(svc.list_threads(world.editor, world.main, kind=kind))}

        assert ids("question") == {question.id}
        assert ids("comment") == {comment.id, str(legacy["_id"])}
        assert len(ids(None)) == 3
        assert run(svc.get_thread(world.editor, question.id)).kind == "question"

    def test_kind_via_route(self, world):
        run(svc.create_thread(world.editor, payload(world, kind="question", body="q")))
        run(svc.create_thread(world.editor, payload(world)))
        out = run(
            cr.list_threads(
                world.main,
                scope="tab",
                component_index=None,
                status=None,
                kind="question",
                current_user=world.editor,
            )
        )
        assert [t.kind for t in out] == ["question"]


# ---------------------------------------------------------------------------
# REST under a scoped token
# ---------------------------------------------------------------------------
class TestScopedToken:
    def test_create_and_reply_forced_to_agent(self, world):
        with scoped_token("annotate"):
            thread = run(
                cr.create_thread(
                    body=payload(world),
                    response=Response(status_code=201),
                    current_user=world.editor,
                )
            )
            assert thread.status == "proposed"
            assert thread.created_by.kind == "agent"
            assert thread.created_by.agent.name == svc.DEFAULT_TOKEN_AGENT_NAME
            assert thread.created_by.agent.on_behalf_of == str(world.editor.id)
            assert thread.run_id

            out = run(
                cr.add_comment(thread.id, CommentCreate(body="more"), current_user=world.editor)
            )
            assert out.comments[-1].author.kind == "agent"

    def test_review_and_publish_refused(self, world):
        thread, _ = run(
            svc.create_agent_thread(world.editor, payload(world, annotation=RANGE), agent())
        )
        with scoped_token("annotate"), pytest.raises(HTTPException) as e:
            run(
                cr.review_thread(
                    thread.id, ThreadReview(decision="accepted"), current_user=world.editor
                )
            )
        assert e.value.status_code == 403

        run(
            cr.review_thread(
                thread.id, ThreadReview(decision="accepted"), current_user=world.editor
            )
        )
        with scoped_token("annotate"), pytest.raises(HTTPException) as e:
            run(
                cr.update_thread(
                    thread.id,
                    ThreadUpdate(annotation={"published": True}),
                    current_user=world.editor,
                )
            )
        assert e.value.status_code == 403

    def test_client_run_id_is_ignored(self, world):
        body = payload(world, agent={"name": "bot@2", "run_id": "client-run"})
        with scoped_token("annotate"):
            first = run(
                cr.create_thread(
                    body=body, response=Response(status_code=201), current_user=world.editor
                )
            )
            second = run(
                cr.create_thread(
                    body=payload(world, agent={"name": "bot@2", "run_id": "other-run"}),
                    response=Response(status_code=201),
                    current_user=world.editor,
                )
            )
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        assert first.created_by.agent.name == "bot@2"
        assert first.run_id == second.run_id == f"token-{world.editor.id}-{day}"

    def test_daily_token_cap(self, world):
        tok = current_token_id.set("tok1")
        try:
            with (
                scoped_token("annotate"),
                patch.object(db, "agent_quotas_collection", world.db["agent_quotas"]),
                patch.object(quotas, "MAX_THREADS_PER_TOKEN_PER_DAY", 1),
            ):
                run(svc.create_thread(world.editor, payload(world)))
                with pytest.raises(HTTPException) as e:
                    run(svc.create_thread(world.editor, payload(world)))
        finally:
            current_token_id.reset(tok)
        assert e.value.status_code == 429 and "per day" in e.value.detail

    def test_unscoped_request_stays_human(self, world):
        thread = run(
            cr.create_thread(
                body=payload(world), response=Response(status_code=201), current_user=world.editor
            )
        )
        assert thread.created_by.kind == "human" and thread.status == "open"
