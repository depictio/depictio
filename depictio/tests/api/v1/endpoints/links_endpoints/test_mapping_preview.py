"""Tests for the link mapping-preview endpoint (issue #938 debug/inspect view)."""

from unittest.mock import patch

import mongomock
import polars as pl
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.links_endpoints.routes import link_mapping_preview
from depictio.api.v1.endpoints.user_endpoints.core_functions import _hash_password
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import User

SOURCE_DC = str(ObjectId())
TARGET_DC = str(ObjectId())
PROJECT_ID = ObjectId()
LINK_ID = str(ObjectId())

MAPPINGS = {
    "HG001": ["HG001_R1", "HG001_R2"],
    "HG002": ["HG002_R1"],
    "ORPHAN": ["ORPHAN_R1"],
}


def _admin_user() -> User:
    return User(
        id=PyObjectId(),
        email="admin@example.com",
        password=_hash_password("test_password"),
        is_admin=True,
    )


@pytest.fixture
def patched_env():
    client = mongomock.MongoClient()
    db = client.test_db
    db.projects.insert_one(
        {
            "_id": PROJECT_ID,
            "permissions": {"owners": [], "editors": [], "viewers": []},
            "links": [
                {
                    "id": LINK_ID,
                    "source_dc_id": SOURCE_DC,
                    "source_column": "sample",
                    "target_dc_id": TARGET_DC,
                    "target_type": "multiqc",
                    "enabled": True,
                    "link_config": {
                        "resolver": "sample_mapping",
                        "target_field": "sample_name",
                        "case_sensitive": False,
                    },
                }
            ],
        }
    )
    db.deltatables.insert_one(
        {
            "data_collection_id": SOURCE_DC,
            "delta_table_location": "memory://source",
        }
    )
    db.multiqc.insert_one(
        {
            "data_collection_id": TARGET_DC,
            "metadata": {"sample_mappings": MAPPINGS},
        }
    )

    source_frame = pl.DataFrame({"sample": ["HG001", "HG002", "UNKNOWN"]}).lazy()

    with (
        patch("depictio.api.v1.endpoints.links_endpoints.routes.projects_collection", db.projects),
        patch(
            "depictio.api.v1.endpoints.links_endpoints.routes.deltatables_collection",
            db.deltatables,
        ),
        patch("depictio.api.v1.endpoints.links_endpoints.routes.multiqc_collection", db.multiqc),
        patch(
            "depictio.api.v1.endpoints.links_endpoints.routes.pl.scan_delta",
            return_value=source_frame,
        ),
    ):
        yield
        client.close()


@pytest.mark.asyncio
async def test_mapping_preview_reports_matches_and_orphans(patched_env):
    response = await link_mapping_preview(
        project_id=str(PROJECT_ID),
        link_id=LINK_ID,
        limit=500,
        current_user=_admin_user(),
    )

    assert response.resolver == "sample_mapping"
    assert response.mappings_source == "multiqc_live"
    assert response.source_values_total == 3
    assert response.truncated is False
    assert response.matched_count == 2
    assert response.unmapped_count == 1

    by_source = {r.source_value: r for r in response.rows}
    assert by_source["HG001"].matched and by_source["HG001"].via == "exact"
    assert set(by_source["HG001"].resolved) == {"HG001", "HG001_R1", "HG001_R2"}
    assert not by_source["UNKNOWN"].matched
    assert by_source["UNKNOWN"].via == "passthrough"

    # ORPHAN's variants are reached by no source value.
    assert response.orphan_targets == ["ORPHAN"]


@pytest.mark.asyncio
async def test_mapping_preview_respects_limit(patched_env):
    response = await link_mapping_preview(
        project_id=str(PROJECT_ID),
        link_id=LINK_ID,
        limit=2,
        current_user=_admin_user(),
    )
    assert len(response.rows) == 2
    assert response.truncated is True
    assert response.source_values_total == 3


@pytest.mark.asyncio
async def test_mapping_preview_unknown_link_404(patched_env):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await link_mapping_preview(
            project_id=str(PROJECT_ID),
            link_id=str(ObjectId()),
            limit=10,
            current_user=_admin_user(),
        )
    assert exc.value.status_code == 404
