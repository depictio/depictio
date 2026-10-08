"""Guards for the pymongo async driver that the mongomock-motor suite cannot see.

The unit suite runs Beanie on mongomock-motor, which answers differently from the
real driver (see #971). These tests build real, never-connected pymongo objects.
"""

from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId
from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

from depictio.api.v1.services.events.mongodb_watcher import MongoDBChangeWatcher


def test_append_metadata_is_a_method() -> None:
    """beanie >= 2.1 calls ``client.append_metadata`` when it is callable."""
    client: AsyncMongoClient = AsyncMongoClient("mongodb://localhost:1", connect=False)
    assert callable(client.append_metadata)


class _Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = iter(docs)

    def __aiter__(self) -> "_Cursor":
        return self

    async def __anext__(self) -> dict:
        try:
            return next(self._docs)
        except StopIteration:
            raise StopAsyncIteration from None


@pytest.mark.asyncio
async def test_find_dashboards_using_dc_with_real_async_database() -> None:
    """``AsyncDatabase.__bool__`` raises, so the watcher must compare with None."""
    watcher = MongoDBChangeWatcher(AsyncMock())
    watcher._db = AsyncMongoClient("mongodb://localhost:1", connect=False)["x"]
    dashboard_id = ObjectId()
    with patch.object(
        AsyncCollection, "aggregate", AsyncMock(return_value=_Cursor([{"_id": dashboard_id}]))
    ):
        assert await watcher._find_dashboards_using_dc(str(ObjectId())) == [str(dashboard_id)]


@pytest.mark.asyncio
async def test_find_dashboards_using_dc_without_database() -> None:
    watcher = MongoDBChangeWatcher(AsyncMock())
    assert await watcher._find_dashboards_using_dc(str(ObjectId())) == []
