"""A SpatialData table DC is ingested by the CLI only: UI upload paths answer 400."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from depictio.api.v1.endpoints.datacollections_endpoints import table_manage
from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
    SPATIALDATA_CLI_ONLY_DETAIL,
    _create_dc_from_upload,
)

DC_ID = "646b0f3c1e4a2d7f8e5b8cab"
USER = SimpleNamespace(id="507f1f77bcf86cd799439011", is_admin=False)


def test_create_from_upload_rejects_spatialdata():
    with pytest.raises(HTTPException) as exc:
        _create_dc_from_upload(
            project_id="646b0f3c1e4a2d7f8e5b8cac",
            name="spots",
            description="",
            data_type="table",
            file_format="spatialdata",
            separator=",",
            custom_separator=None,
            compression="none",
            has_header=True,
            file_bytes=b"x",
            filename="spots.zarr",
            current_user=USER,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == SPATIALDATA_CLI_ONLY_DETAIL


@pytest.mark.parametrize("mode", ["append", "replace"])
def test_append_and_replace_reject_spatialdata(mode):
    dc = {"config": {"type": "table", "dc_specific_properties": {"format": "spatialdata"}}}
    with (
        patch.object(table_manage, "_load_table_dc", return_value=({}, dc)),
        patch.object(table_manage, "_write_table_upload") as write,
        pytest.raises(HTTPException) as exc,
    ):
        table_manage._process_table_uploads(
            data_collection_id=DC_ID,
            decoded_files=[(b"a,b\n1,2\n", "new.csv")],
            current_user=USER,
            mode=mode,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == SPATIALDATA_CLI_ONLY_DETAIL
    write.assert_not_called()
