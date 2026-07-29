"""GeoJSON and phylogeny stamp the asset arm of a version.

These two are each one opaque blob, and until now neither could be reproduced.
GeoJSON overwrote a single fixed key in place, so prior content was gone.
Phylogeny was never uploaded at all — the CLI recorded the path on the machine
that ran the scan, which the container usually cannot read, so the tree often
failed to load at all.

Content addressing settles both: a PUT to ``{dc_id}/versions/{sha256}/{name}``
is idempotent, and the bytes behind a digest cannot change without the key
changing too.
"""

from __future__ import annotations

from datetime import datetime

import mongomock
import pytest
from bson import ObjectId

from depictio.models.models.dashboard_versions import TabSnapshot

BASE = datetime(2026, 3, 1, 12, 0, 0)
DC_ID = ObjectId()
DIGEST = "d" * 64


@pytest.fixture()
def ctx(monkeypatch: pytest.MonkeyPatch):
    import depictio.api.v1.db as api_db
    from depictio.api.v1.endpoints.dashboards_endpoints import versioning

    db = mongomock.MongoClient()["t"]
    monkeypatch.setattr(versioning, "deltatables_collection", db["deltatables"])
    monkeypatch.setattr(api_db, "projects_collection", db["projects"])
    return {"projects": db["projects"], "versioning": versioning}


def _project_with(ctx, dc_type: str, props: dict) -> None:
    ctx["projects"].insert_one(
        {
            "_id": ObjectId(),
            "workflows": [
                {
                    "data_collections": [
                        {
                            "_id": DC_ID,
                            "config": {"type": dc_type, "dc_specific_properties": props},
                        }
                    ]
                }
            ],
        }
    )


def _tabs(dc_type: str) -> list[TabSnapshot]:
    return [
        TabSnapshot(
            dashboard_id="t1",
            stored_metadata=[{"dc_id": str(DC_ID), "dc_config": {"type": dc_type}}],
        )
    ]


def _version(generation: int = 1, digest: str = DIGEST) -> dict:
    return {
        "digest": digest,
        "s3_location": f"s3://bucket/{DC_ID}/versions/{digest}/map.geojson",
        "filename": "map.geojson",
        "size_bytes": 4096,
        "generation": generation,
        "uploaded_at": BASE,
        "source_path": "/data/map.geojson",
    }


@pytest.mark.parametrize("dc_type", ["geojson", "phylogeny"])
class TestTheAssetArm:
    def test_an_uploaded_asset_is_pinned_by_digest(self, ctx, dc_type):
        _project_with(ctx, dc_type, {"versions": [_version()]})

        stamp = ctx["versioning"].build_dc_stamps(_tabs(dc_type), now=BASE)[0]

        assert stamp.version_kind == "asset"
        assert stamp.asset_digest == DIGEST
        assert stamp.asset_bytes == 4096
        assert stamp.as_of == BASE
        assert stamp.reason is None

    def test_the_newest_generation_wins(self, ctx, dc_type):
        newest = "e" * 64
        _project_with(ctx, dc_type, {"versions": [_version(1), _version(2, digest=newest)]})

        stamp = ctx["versioning"].build_dc_stamps(_tabs(dc_type), now=BASE)[0]

        assert stamp.asset_digest == newest

    def test_a_collection_uploaded_by_an_older_cli_says_so(self, ctx, dc_type):
        """Its object sits at a fixed key that a re-upload overwrites in place.
        There is genuinely nothing to pin, and claiming otherwise would be
        worse than reporting the gap."""
        _project_with(ctx, dc_type, {"s3_location": f"s3://bucket/{DC_ID}/geojson_data.geojson"})

        stamp = ctx["versioning"].build_dc_stamps(_tabs(dc_type), now=BASE)[0]

        assert stamp.version_kind == "none"
        assert stamp.reason == "no_asset_version_recorded"

    def test_a_missing_project_document_does_not_break_the_save(self, ctx, dc_type):
        """Capture must never raise into a save."""
        stamp = ctx["versioning"].build_dc_stamps(_tabs(dc_type), now=BASE)[0]

        assert stamp.version_kind == "none"


class TestImagePixelsStayUnversioned:
    """The Delta manifest of image *paths* is versioned; the blobs behind those
    paths live under a user-supplied prefix with no content addressing at all.
    Reported as a gap rather than implied to be covered."""

    def test_an_image_collection_declares_the_gap(self, ctx):
        stamp = ctx["versioning"].build_dc_stamps(
            [
                TabSnapshot(
                    dashboard_id="t1",
                    stored_metadata=[{"dc_id": str(DC_ID), "dc_config": {"type": "image"}}],
                )
            ],
            now=BASE,
        )[0]

        assert stamp.unversioned_parts == ["image_pixels"]
