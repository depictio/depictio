"""Finding someone to share a project with, as an owner or P.I. who is not an admin."""

from types import SimpleNamespace

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.projects_endpoints import routes
from depictio.api.v1.endpoints.projects_endpoints.share_candidates import (
    MAX_RESULTS,
    MIN_QUERY_LENGTH,
    clean_query,
    exact_email_filter,
    partial_filter,
    rank_candidates,
)

OWNER, OUTSIDER = ObjectId(), ObjectId()


def _user(email, name=None, **extra):
    return {"_id": ObjectId(), "email": email, "display_name": name, **extra}


class TestQuery:
    @pytest.mark.parametrize("raw", [None, "", "  ", "ab", " ab "])
    def test_a_short_query_is_not_searched(self, raw):
        assert clean_query(raw) is None

    def test_the_query_is_trimmed(self):
        assert clean_query("  ann  ") == "ann"
        assert len("ann") == MIN_QUERY_LENGTH

    def test_typed_text_is_escaped_never_a_pattern(self):
        assert partial_filter("a.b+")["$or"][0]["email"]["$regex"] == r"a\.b\+"
        assert exact_email_filter("a.b@x.org")["email"]["$regex"] == r"^a\.b@x\.org$"


class TestRanking:
    def test_exact_email_then_prefix_then_the_rest(self):
        exact = _user("ann@x.org", "Someone")
        prefix = _user("anna.b@x.org")
        by_name = _user("zed@x.org", "Annette Z")
        inside = _user("joann@x.org")

        ranked = rank_candidates([inside, by_name, prefix, exact], "ann@x.org")
        assert ranked[0]["email"] == "ann@x.org"

        ranked = rank_candidates([inside, by_name, prefix], "ann")
        assert [r["email"] for r in ranked] == ["anna.b@x.org", "zed@x.org", "joann@x.org"]

    def test_a_person_found_twice_is_listed_once(self):
        ann = _user("ann@x.org")
        assert len(rank_candidates([ann, ann], "ann")) == 1

    def test_the_page_is_capped_and_an_exact_match_survives_the_cap(self):
        many = [_user(f"ann{i:02d}@x.org") for i in range(MAX_RESULTS + 15)]
        exact = _user("ann@x.org")

        ranked = rank_candidates([*many, exact], "ann@x.org")

        assert len(ranked) == MAX_RESULTS
        assert ranked[0]["email"] == "ann@x.org"

    def test_only_id_email_and_name_leave_the_server(self):
        doc = _user("ann@x.org", "Ann", is_admin=True, password="hash")
        assert set(rank_candidates([doc], "ann")[0]) == {"id", "email", "display_name"}


@pytest.fixture
def users(monkeypatch):
    collection = mongomock.MongoClient().db.users
    collection.insert_many(
        [
            _user("ann.lee@x.org", "Ann Lee"),
            _user("bob@x.org", "Bob Annan"),
            _user("gone@x.org", "Ann Gone", is_active=False),
            _user("anonymous@depictio.io", "Anonymous Ann", is_anonymous=True),
            _user("cara@x.org", "Cara"),
        ]
    )
    monkeypatch.setattr(routes, "users_collection", collection)
    return collection


def _project(monkeypatch, owner=OWNER):
    project = {"_id": ObjectId(), "permissions": {"owners": [{"_id": owner}]}}
    monkeypatch.setattr(routes, "_async_get_project_from_id", lambda *a, **k: project)
    return project


async def _search(q, user_id=OWNER, is_admin=False):
    caller = SimpleNamespace(id=user_id, is_admin=is_admin)
    return await routes.find_share_candidates(str(ObjectId()), q=q, current_user=caller)


class TestRoute:
    @pytest.mark.asyncio
    async def test_a_non_admin_owner_finds_people_by_name_or_email(self, users, monkeypatch):
        _project(monkeypatch)

        found = await _search("ann")

        assert [r["email"] for r in found] == ["ann.lee@x.org", "bob@x.org"]

    @pytest.mark.asyncio
    async def test_deactivated_and_anonymous_accounts_are_not_offered(self, users, monkeypatch):
        _project(monkeypatch)

        emails = {r["email"] for r in await _search("ann")}

        assert "gone@x.org" not in emails
        assert "anonymous@depictio.io" not in emails

    @pytest.mark.asyncio
    async def test_a_pasted_address_resolves_whatever_its_case(self, users, monkeypatch):
        _project(monkeypatch)

        found = await _search("CARA@x.org")

        assert [r["email"] for r in found] == ["cara@x.org"]

    @pytest.mark.asyncio
    async def test_a_short_query_returns_nothing(self, users, monkeypatch):
        _project(monkeypatch)

        assert await _search("an") == []

    @pytest.mark.asyncio
    async def test_someone_who_does_not_manage_the_sharing_is_refused(self, users, monkeypatch):
        _project(monkeypatch)

        with pytest.raises(HTTPException) as refused:
            await _search("ann", user_id=OUTSIDER)

        assert refused.value.status_code == 403

    @pytest.mark.asyncio
    async def test_an_admin_may_search(self, users, monkeypatch):
        _project(monkeypatch)

        assert await _search("cara", user_id=OUTSIDER, is_admin=True)
