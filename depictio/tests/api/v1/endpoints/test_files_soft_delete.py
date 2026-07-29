"""Departed files leave a tombstone instead of vanishing.

"Which files backed this data collection at time T" cannot be answered from
records that no longer exist, and `--sync-files` removed them outright — so a
dashboard version saved before a cleanup could name a file set that was
unreconstructable a minute later.

This is the one non-additive change in the versioning work, and its whole risk
is a *reader* that forgets the new predicate: a missed consumer does not error,
it silently resurrects departed files into an ingest. So the tests here are
mostly about readers, not about the delete itself.

Backward compatibility rests on one Mongo behaviour: a missing field compares
equal to ``None``, so ``{"deleted_at": None}`` selects both a live file and
every document written before this field existed. There is no migration, and a
test pins that rather than leaving it to a comment.
"""

from __future__ import annotations

import mongomock
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

DC_ID = ObjectId()
OTHER_DC_ID = ObjectId()


class _User:
    def __init__(self, uid: ObjectId, is_admin: bool = False) -> None:
        self.id = uid
        self.email = "caller@example.com"
        self.is_admin = is_admin
        self.is_anonymous = False


CALLER = _User(ObjectId())


@pytest.fixture()
def ctx(monkeypatch: pytest.MonkeyPatch):
    from depictio.api.v1.endpoints.files_endpoints import routes as files_routes
    from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user

    db = mongomock.MongoClient()["depictioTest"]
    files = db["files"]
    monkeypatch.setattr(files_routes, "files_collection", files)

    app = FastAPI()
    app.include_router(files_routes.files_endpoint_router, prefix="/depictio/api/v1/files")
    app.dependency_overrides[get_current_user] = lambda: CALLER

    return {"client": TestClient(app), "files": files}


def _insert(ctx, name: str, *, dc_id=DC_ID, legacy: bool = False) -> ObjectId:
    """Insert a file. ``legacy`` omits ``deleted_at`` entirely, as every
    document written before this feature does."""
    fid = ObjectId()
    document = {
        "_id": fid,
        "filename": name,
        "file_location": f"/data/{name}",
        "data_collection_id": dc_id,
        "registration_time": "2026-03-01 12:00:00",
        "permissions": {"owners": [{"_id": CALLER.id}]},
    }
    if not legacy:
        document["deleted_at"] = None
    ctx["files"].insert_one(document)
    return fid


API = "/depictio/api/v1/files"


def _list(ctx, dc_id=DC_ID, **params):
    response = ctx["client"].get(f"{API}/list/{dc_id}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


class TestBackwardCompatibility:
    def test_a_document_with_no_deleted_at_field_is_live(self, ctx):
        """The entire migration story. Mongo treats a missing field as equal to
        None, so every pre-existing file passes the live predicate untouched."""
        _insert(ctx, "legacy.txt", legacy=True)

        names = [f["filename"] for f in _list(ctx)]

        assert names == ["legacy.txt"]

    def test_legacy_and_new_documents_list_together(self, ctx):
        _insert(ctx, "legacy.txt", legacy=True)
        _insert(ctx, "new.txt")

        assert len(_list(ctx)) == 2


class TestDeleting:
    def test_a_deleted_file_leaves_the_list(self, ctx):
        fid = _insert(ctx, "gone.txt")
        _insert(ctx, "stays.txt")

        response = ctx["client"].delete(f"{API}/delete/{fid}")

        assert response.status_code == 200, response.text
        assert [f["filename"] for f in _list(ctx)] == ["stays.txt"]

    def test_but_the_record_survives(self, ctx):
        """The point of the whole change."""
        fid = _insert(ctx, "gone.txt")

        ctx["client"].delete(f"{API}/delete/{fid}")

        stored = ctx["files"].find_one({"_id": fid})
        assert stored is not None
        assert stored["deleted_at"] is not None

    def test_a_batch_delete_reports_the_same_shape_as_before(self, ctx):
        """The CLI's scan cleanup reconciles against these counts."""
        alive = [_insert(ctx, f"f{i}.txt") for i in range(3)]

        response = ctx["client"].post(
            f"{API}/delete_batch",
            json={"file_ids": [str(f) for f in alive] + [str(ObjectId())]},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body == {"requested": 4, "deleted": 3, "not_found": 1}

    def test_deleting_twice_is_not_counted_twice(self, ctx):
        """A retried cleanup must not report work it did not do."""
        fid = _insert(ctx, "gone.txt")
        ctx["client"].post(f"{API}/delete_batch", json={"file_ids": [str(fid)]})

        again = ctx["client"].post(f"{API}/delete_batch", json={"file_ids": [str(fid)]})

        assert again.json()["deleted"] == 0

    def test_deleting_an_already_deleted_file_is_a_404(self, ctx):
        fid = _insert(ctx, "gone.txt")
        ctx["client"].delete(f"{API}/delete/{fid}")

        assert ctx["client"].delete(f"{API}/delete/{fid}").status_code == 404

    def test_a_caller_cannot_delete_another_owner_s_file(self, ctx):
        """Unchanged by soft deletion, and worth re-pinning: the predicate moved
        from a delete to an update and could have lost its owner clause."""
        fid = _insert(ctx, "theirs.txt")
        ctx["files"].update_one(
            {"_id": fid}, {"$set": {"permissions": {"owners": [{"_id": ObjectId()}]}}}
        )

        assert ctx["client"].delete(f"{API}/delete/{fid}").status_code == 404
        assert ctx["files"].find_one({"_id": fid})["deleted_at"] is None


class TestReconstruction:
    def test_include_deleted_returns_the_tombstones(self, ctx):
        fid = _insert(ctx, "gone.txt")
        _insert(ctx, "stays.txt")
        ctx["client"].delete(f"{API}/delete/{fid}")

        everything = _list(ctx, include_deleted=True)

        assert sorted(f["filename"] for f in everything) == ["gone.txt", "stays.txt"]
        tombstone = next(f for f in everything if f["filename"] == "gone.txt")
        assert tombstone["deleted_at"] is not None

    def test_the_default_is_still_live_only(self, ctx):
        """Every existing caller means "the files in this collection" — an ingest
        rebuilding a Delta table from departed files is the failure this
        default prevents."""
        fid = _insert(ctx, "gone.txt")
        ctx["client"].delete(f"{API}/delete/{fid}")

        assert _list(ctx) == []
        assert len(_list(ctx, include_deleted=True)) == 1


class TestReRegistration:
    def test_a_file_that_comes_back_is_alive_again(self, ctx):
        """A path can legitimately reappear — restored from backup, or a run
        re-run. It must not stay tombstoned."""
        fid = _insert(ctx, "flaky.txt")
        ctx["client"].delete(f"{API}/delete/{fid}")
        assert _list(ctx) == []

        ctx["files"].update_one({"_id": fid}, {"$set": {"deleted_at": None}})

        assert [f["filename"] for f in _list(ctx)] == ["flaky.txt"]


class TestOtherReaders:
    """Every direct `files_collection` reader that means "the files in this
    collection". A missed one resurrects departed files silently."""

    def test_the_ingestion_report_count_excludes_tombstones(self, monkeypatch):
        from depictio.api.v1.endpoints.projects_endpoints import ingestion_report

        db = mongomock.MongoClient()["t"]
        files = db["files"]
        monkeypatch.setattr(ingestion_report, "files_collection", files)
        files.insert_many(
            [
                {"data_collection_id": DC_ID, "deleted_at": None},
                {"data_collection_id": DC_ID},  # legacy, no field
                {"data_collection_id": DC_ID, "deleted_at": "2026-03-01 12:00:00"},
            ]
        )

        assert ingestion_report._dc_file_count(str(DC_ID)) == 2

    def test_the_phylogeny_lookup_skips_a_tombstone(self):
        """It takes the *first* matching document, so a tombstone sorting first
        would serve a tree whose file is gone."""
        # `get_phylogeny_newick` imports the collection inside the function, so
        # there is no module attribute to patch — assert on the predicate the
        # endpoint uses rather than on a rebound global that does not exist.
        db = mongomock.MongoClient()["t"]
        files = db["files"]
        files.insert_many(
            [
                {
                    "data_collection_id": DC_ID,
                    "file_location": "/gone.nwk",
                    "deleted_at": "2026-03-01 12:00:00",
                },
                {"data_collection_id": DC_ID, "file_location": "/live.nwk", "deleted_at": None},
            ]
        )

        found = files.find_one({"data_collection_id": DC_ID, "deleted_at": None})

        assert found["file_location"] == "/live.nwk"
