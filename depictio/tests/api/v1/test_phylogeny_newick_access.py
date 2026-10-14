"""`GET /advanced_viz/phylogeny/{dc_id}/newick` reads only what this server may read (#1170).

The fixed ingest key (``phylogeny/<dc_id>/tree.nwk`` in the instance bucket) is
the endpoint's own and stays read with the instance credentials. Every other
candidate is a string from a CLI scan or from the project's YAML, so:

* an ``s3://`` one goes through the remote-data resolution: the instance
  bucket is refused, another bucket needs an allowlist entry or project keys;
* a local one is opened only below the bundled reference projects (or the
  local-data policy's folders under ``depictio local``);
* no response names a candidate path.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1 import db
from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.settings_models import BUNDLED_PROJECTS_DIR
from depictio.api.v1.endpoints.advanced_viz_endpoints import routes
from depictio.models.s3_access import S3Target

DC_ID = ObjectId("646b0f3c1e4a2d7f8e5b8ca9")
SEED_TREE = BUNDLED_PROJECTS_DIR / "init" / "advanced_viz_showcase" / "data" / "bacterial_tree.nwk"


@pytest.fixture
def instance_client() -> MagicMock:
    """The instance-credentials client: the fixed ingest key is missing."""
    client = MagicMock()
    client.get_object.side_effect = Exception("NoSuchKey")
    return client


@pytest.fixture
def newick(monkeypatch: pytest.MonkeyPatch, instance_client: MagicMock):
    """Call the endpoint for a DC whose project names ``filename`` as its tree."""
    for name in ("DEPICTIO_LOCAL_DATA_ROOTS", "DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS"):
        monkeypatch.delenv(name, raising=False)
    mongo = mongomock.MongoClient().db
    monkeypatch.setattr(db, "files_collection", mongo.files)
    monkeypatch.setattr(db, "projects_collection", mongo.projects)
    monkeypatch.setattr(routes, "_assert_dc_access", lambda dc_oid, user: None)
    monkeypatch.setattr(routes, "_phylogeny_s3_client", lambda: instance_client)
    monkeypatch.setattr(
        "depictio.api.v1.endpoints.projects_endpoints.storage_config.project_storage_for",
        lambda project_id: None,
    )

    def call(filename: str | None) -> str:
        if filename is not None:
            mongo.projects.insert_one(
                {
                    "_id": ObjectId(),
                    "workflows": [
                        {
                            "data_collections": [
                                {
                                    "_id": DC_ID,
                                    "config": {"scan": {"scan_parameters": {"filename": filename}}},
                                }
                            ]
                        }
                    ],
                }
            )
        return routes.get_phylogeny_newick(data_collection_id=DC_ID, current_user=None)

    return call


def _error(call, filename: str | None) -> HTTPException:
    with pytest.raises(HTTPException) as exc_info:
        call(filename)
    return exc_info.value


class TestS3Locations:
    def test_the_instance_bucket_is_refused(self, newick, instance_client):
        url = f"s3://{settings.s3.bucket}/{ObjectId()}/secret.parquet"

        error = _error(newick, url)

        assert error.status_code == 403
        assert url not in str(error.detail)
        # Only the fixed ingest key was ever asked of the instance credentials.
        instance_client.get_object.assert_called_once()
        assert instance_client.get_object.call_args.kwargs["Key"] == f"phylogeny/{DC_ID}/tree.nwk"

    def test_a_bucket_nothing_allows_is_refused(self, newick):
        error = _error(newick, "s3://someone-elses-bucket/tree.nwk")

        assert error.status_code == 403

    def test_an_allowlisted_public_bucket_is_read_unsigned(self, newick, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "public-trees")
        monkeypatch.setattr("depictio.models.s3_access.ensure_region", lambda target: target)
        reads: list[S3Target] = []

        def fake_client(target: S3Target) -> MagicMock:
            reads.append(target)
            client = MagicMock()
            client.get_object.return_value = {"Body": io.BytesIO(b"(a,b);")}
            return client

        monkeypatch.setattr(S3Target, "client", fake_client)

        assert newick("s3://public-trees/run/tree.nwk") == "(a,b);"
        assert [(t.kind, t.bucket, t.key) for t in reads] == [
            ("public", "public-trees", "run/tree.nwk")
        ]


class TestLocalPaths:
    def test_a_bundled_reference_tree_is_served(self, newick):
        assert newick(str(SEED_TREE)) == SEED_TREE.read_text()

    def test_a_path_outside_the_readable_folders_is_refused(self, newick, tmp_path: Path):
        secret = tmp_path / "jwt.pem"
        secret.write_text("-----BEGIN PRIVATE KEY-----")

        error = _error(newick, str(secret))

        assert error.status_code == 403
        assert str(secret) not in str(error.detail)

    def test_a_traversal_out_of_the_bundled_projects_is_refused(self, newick):
        escaped = f"{BUNDLED_PROJECTS_DIR}/../api/v1/configs/config.py"

        assert _error(newick, escaped).status_code == 403

    def test_a_missing_file_is_a_404_that_names_no_path(self, newick):
        missing = str(BUNDLED_PROJECTS_DIR / "init" / "no_such_tree.nwk")

        error = _error(newick, missing)

        assert error.status_code == 404
        assert "no_such_tree" not in str(error.detail)
