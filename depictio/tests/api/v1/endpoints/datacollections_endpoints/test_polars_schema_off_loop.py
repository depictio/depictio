"""GET /datacollections/polars_schema/{id} reads the Delta log off the event loop.

A dashboard with a view on runs asks for one schema per collection; each read
blocks ~170 ms against S3, which on the loop stalled every other request.
"""

import threading
from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.datacollections_endpoints import utils


@pytest.mark.asyncio
async def test_the_schema_is_read_in_a_worker_thread() -> None:
    seen: dict[str, object] = {}

    def fake_read(dc_oid: ObjectId) -> dict[str, str]:
        seen["thread"] = threading.current_thread()
        seen["dc"] = dc_oid
        return {"depictio_run_id": "String"}

    dc_id = ObjectId()
    with (
        patch.object(utils, "_get_data_collection_specs", AsyncMock(return_value={})),
        patch.object(utils, "_read_polars_schema", fake_read),
    ):
        schema = await utils._get_data_collection_polars_schema(dc_id, "user")  # type: ignore[arg-type]

    assert schema == {"depictio_run_id": "String"}
    assert seen["dc"] == dc_id
    assert seen["thread"] is not threading.main_thread()
