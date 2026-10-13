"""``File.registration_time`` must survive re-registration.

``registration_time`` is the only record of when a file first entered
depictio, and it is the field an "as of T" reconstruction has to range over.
It is also the easiest field in the codebase to destroy by accident:

* the CLI never sends a value for it — ``File``'s ``default_factory`` stamps
  *now* on every scan (``cli/utils/scan.py``);
* ``MongoModel.mongo()`` uses ``exclude_unset=False``, so that fresh value is
  always present in the payload;
* the watcher's default incremental mode sends ``update=True`` on every cycle
  (``cli/commands/data.py``).

So a blanket ``$set`` of the payload rewrites the original timestamp with the
current scan's, and a long-running watcher converges every file's
``registration_time`` on "recently". These tests pin the split: everything
except ``registration_time`` goes in ``$set``; ``registration_time`` goes in
``$setOnInsert`` so it is written once and never again.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

from depictio.api.v1.endpoints.files_endpoints import routes
from depictio.models.models.base import PyObjectId
from depictio.models.models.files import File
from depictio.models.models.users import Permission, UserBase


def _make_file(location: str = "/data/sample.csv") -> File:
    owner = UserBase(id=PyObjectId(), email="owner@example.com")
    return File(
        file_location=location,
        filename=location.rsplit("/", 1)[-1],
        creation_time="2026-01-01 00:00:00",
        modification_time="2026-01-01 00:00:00",
        data_collection_id=PyObjectId(),
        file_hash="a" * 64,
        filesize=123,
        permissions=Permission(owners=[owner]),
    )


class _FakeBulkResult:
    matched_count = 1
    modified_count = 1
    upserted_count = 0


def _capture_operations(update: bool) -> list[Any]:
    """Run the upsert endpoint and return the pymongo operations it built."""
    captured: list[Any] = []

    def fake_bulk_write(operations, ordered=True):  # noqa: ANN001, ARG001
        captured.extend(operations)
        return _FakeBulkResult()

    payload = routes.UpsertFilesBatchRequest(files=[_make_file()], update=update)
    user = UserBase(id=PyObjectId(), email="caller@example.com")

    with patch.object(routes.files_collection, "bulk_write", side_effect=fake_bulk_write):
        asyncio.run(routes.create_file(payload, current_user=user))

    assert captured, "endpoint built no write operations"
    return captured


def test_update_does_not_set_registration_time() -> None:
    """The regression: update=True must not overwrite registration_time."""
    op = _capture_operations(update=True)[0]
    update_doc = op._doc

    assert "registration_time" not in update_doc.get("$set", {}), (
        "registration_time in $set would rewrite the original registration on every "
        "re-scan — the watcher sends update=True each cycle"
    )


def test_update_seeds_registration_time_only_on_insert() -> None:
    """A file seen for the first time under update=True still gets a timestamp."""
    op = _capture_operations(update=True)[0]
    update_doc = op._doc

    assert "registration_time" in update_doc.get("$setOnInsert", {}), (
        "a first-time file must still record when it entered depictio"
    )


def test_update_still_writes_every_other_field() -> None:
    """Splitting registration_time out must not drop the rest of the payload."""
    op = _capture_operations(update=True)[0]
    set_doc = op._doc.get("$set", {})

    for field in ("file_location", "filename", "file_hash", "filesize", "modification_time"):
        assert field in set_doc, f"{field} must still be updated on re-registration"


def test_insert_path_unchanged() -> None:
    """update=False keeps its original all-or-nothing $setOnInsert shape."""
    op = _capture_operations(update=False)[0]
    update_doc = op._doc

    assert "$set" not in update_doc, "update=False must never modify an existing document"
    assert "registration_time" in update_doc["$setOnInsert"]
    assert "file_location" in update_doc["$setOnInsert"]


def test_registration_time_and_set_are_disjoint() -> None:
    """No field may appear in both operators — Mongo rejects such an update."""
    op = _capture_operations(update=True)[0]
    doc = op._doc
    overlap = set(doc.get("$set", {})) & set(doc.get("$setOnInsert", {}))

    assert not overlap, f"fields in both $set and $setOnInsert are a Mongo error: {overlap}"
