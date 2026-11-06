"""An image collection's files live under ``s3_base_folder``, outside its id prefix.

``ingest`` uploads them to the folder the project names (``s3://bucket/images/``),
and the data collection is stored embedded in the project, not in the separate
``data_collections`` collection. The bundle used to look in that legacy
collection only, so a project sent to another instance arrived with its image
table and none of its images.
"""

from __future__ import annotations

import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.migrate_endpoints import routes
from depictio.api.v1.services import project_bundle

from .conftest import make_db, seed_source_project

SRC = "src-bucket"


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("s3://src-bucket/image_demo/", "image_demo/"),
        ("s3://src-bucket/image_demo", "image_demo/"),
        ("s3://src-bucket/a/b/c/", "a/b/c/"),
        # Not this instance's bucket: read in place, nothing to copy.
        ("s3://elsewhere/image_demo/", None),
        # The whole bucket would sweep in every other project's data.
        ("s3://src-bucket/", None),
        ("s3://src-bucket", None),
        # Not an S3 location, or an escape attempt.
        ("/local/images", None),
        ("s3://src-bucket/a/../b/", None),
        (None, None),
        ("", None),
    ],
)
def test_image_base_prefix(location, expected):
    assert project_bundle.image_base_prefix(location, SRC) == expected


def test_image_base_prefix_without_a_bucket_accepts_any_host():
    """A bundle names the *source* bucket; the import side doesn't know it."""
    assert project_bundle.image_base_prefix("s3://whatever/image_demo/") == "image_demo/"


@pytest.fixture
def world():
    db = make_db()
    ids = seed_source_project(db)
    img = ObjectId()
    dc = {
        "_id": img,
        "data_collection_tag": "img",
        "config": {
            "type": "image",
            "source": "joined",
            "dc_specific_properties": {
                "image_column": "image_path",
                "s3_base_folder": f"s3://{SRC}/image_demo/",
            },
        },
    }
    # Embedded in the project only: the legacy ``data_collections`` stays empty,
    # as it does for every project created through the CLI.
    db.projects_collection.update_one(
        {"_id": ids["project_id"]}, {"$push": {"workflows.0.data_collections": dc}}
    )
    return db, {**ids, "img": img}


def test_collect_includes_the_image_folder_of_an_embedded_collection(world, monkeypatch):
    db, ids = world
    for attr in (
        "deltatables_collection",
        "data_collections_collection",
        "multiqc_collection",
        "jbrowse_collection",
        "projects_collection",
    ):
        monkeypatch.setattr(routes, attr, getattr(db, attr))
    locs = routes._collect_s3_locations_for_project([ids["table_dc"], ids["img"]], SRC)
    assert "image_demo/" in locs


def test_scope_owns_the_image_folder_and_nothing_next_to_it(world):
    db, ids = world
    project = db.projects_collection.find_one({"_id": ids["project_id"]})
    scope = project_bundle.resolve_project_scope(project)
    assert scope.owns_key("image_demo/sample_001.png")
    assert scope.owns_key("image_demo/sub/x.png")
    assert not scope.owns_key("image_demo_other/x.png")
    assert not scope.owns_key("other/x.png")
