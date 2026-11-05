"""Every data collection type travels in a bundle: S3 discovery, export, import."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.migrate_endpoints import routes
from depictio.models.models.data_collections_types.genomic_tracks import genomic_tracks_s3_prefix
from depictio.models.models.data_collections_types.phylogeny import phylogeny_s3_key

from .conftest import FakeS3, make_db, seed_source_project
from .test_bundle_roundtrip import _admin, _export_zip, _import_zip

SRC = "src-bucket"
TGT = "tgt-bucket"
HTTPS_URI = "https://example.org/tracks/sample.bam"


def _dc(dc_id, tag, dc_type, props=None):
    return {
        "_id": dc_id,
        "data_collection_tag": tag,
        "config": {
            "type": dc_type,
            "source": "joined",
            "dc_specific_properties": props or {},
        },
    }


@pytest.fixture
def world():
    db = make_db()
    ids = seed_source_project(db)
    geo, img, jb, phy, gt = (ObjectId() for _ in range(5))
    uri_geo = f"s3://{SRC}/{geo}/map.geojson"
    uri_img = f"s3://{SRC}/{img}/images/"
    uri_jb = f"s3://{SRC}/{jb}/tracks/sample.bam"
    props_geo = {"s3_location": uri_geo}
    props_img = {"s3_base_folder": uri_img}
    new_dcs = [
        _dc(geo, "geo", "geojson", props_geo),
        _dc(img, "img", "image", props_img),
        _dc(jb, "jb", "jbrowse2"),
        _dc(phy, "phy", "phylogeny"),
        _dc(gt, "gt", "genomic_tracks"),
    ]
    db.projects_collection.update_one(
        {"_id": ids["project_id"]}, {"$push": {"workflows.0.data_collections": {"$each": new_dcs}}}
    )
    # GeoJSON / image properties are read from the standalone data collection docs.
    db.data_collections_collection.insert_many(
        [
            {"_id": geo, "config": {"dc_specific_properties": props_geo}},
            {"_id": img, "config": {"dc_specific_properties": props_img}},
        ]
    )
    db.jbrowse_collection.insert_one(
        {
            "_id": ObjectId(),
            "data_collection_id": str(jb),
            "tracks": [{"uri": uri_jb}, {"uri": HTTPS_URI}],
        }
    )
    s3 = FakeS3()
    objects = {
        f"{ids['table_dc']}/part-0.parquet": b"rows",
        f"{ids['table_dc']}/_delta_log/00000.json": b"{}",
        f"{ids['mqc_dc']}/abc/multiqc.parquet": b"mqc",
        f"{geo}/map.geojson": b"{}",
        f"{img}/images/a.png": b"png-a",
        f"{img}/images/sub/b.png": b"png-b",
        f"{jb}/tracks/sample.bam": b"bam",
        phylogeny_s3_key(str(phy)): b"(A,B);",
        f"{genomic_tracks_s3_prefix(str(gt))}x.bw": b"bw",
        f"{genomic_tracks_s3_prefix(str(gt))}sub/y.bw": b"bw2",
    }
    for k, v in objects.items():
        s3.put(SRC, k, v)
    s3.put(SRC, "unrelated/file", b"nope")
    return db, {**ids, "geo": geo, "img": img, "jb": jb, "phy": phy, "gt": gt}, s3, objects


def _all_dc_ids(ids):
    return [ids[k] for k in ("table_dc", "mqc_dc", "geo", "img", "jb", "phy", "gt")]


def test_collect_s3_locations_covers_every_type(world, monkeypatch):
    db, ids, _, _ = world
    for attr in (
        "deltatables_collection",
        "data_collections_collection",
        "multiqc_collection",
        "jbrowse_collection",
        "projects_collection",
    ):
        monkeypatch.setattr(routes, attr, getattr(db, attr))
    locs = routes._collect_s3_locations_for_project(_all_dc_ids(ids), SRC)
    assert str(ids["table_dc"]) in locs
    assert f"{ids['mqc_dc']}/abc/multiqc.parquet" in locs
    assert f"{ids['geo']}/map.geojson" in locs
    assert f"{ids['img']}/images/" in locs
    assert f"{ids['jb']}/tracks/sample.bam" in locs
    assert phylogeny_s3_key(str(ids["phy"])) in locs
    assert genomic_tracks_s3_prefix(str(ids["gt"])) in locs
    assert not any("example.org" in loc for loc in locs)
    assert len(locs) == len(set(locs)) == 7


def test_export_carries_every_object_and_import_rewrites_every_reference(
    world, target_db, captures, monkeypatch
):
    db, ids, s3, objects = world
    payload = _export_zip((db, ids, s3), monkeypatch)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        members = {
            n[len("s3_data/") :]: zf.read(n) for n in zf.namelist() if n.startswith("s3_data/")
        }
        bundle_text = zf.read("bundle.json").decode()
    assert members == objects, "every typed object travels, nothing else"
    assert f"s3://{SRC}/" in bundle_text

    monkeypatch.setattr(routes.settings.s3, "bucket", TGT)
    target_s3 = FakeS3()
    result = _import_zip(payload, _admin(), s3=target_s3)
    assert result.success, result.message

    assert target_s3.buckets[TGT] == objects
    # Not one stored reference still names the source bucket.
    dumped = json.dumps(
        {
            name: list(getattr(target_db, f"{name}_collection").find({}))
            for name in ("projects", "deltatables", "multiqc", "jbrowse")
        },
        default=str,
    )
    assert f"s3://{SRC}" not in dumped
    assert f"s3://{TGT}/" in dumped

    project = target_db.projects_collection.find_one({"_id": ids["project_id"]})
    by_tag = {d["data_collection_tag"]: d for d in project["workflows"][0]["data_collections"]}
    assert by_tag["geo"]["config"]["dc_specific_properties"]["s3_location"] == (
        f"s3://{TGT}/{ids['geo']}/map.geojson"
    )
    assert by_tag["img"]["config"]["dc_specific_properties"]["s3_base_folder"] == (
        f"s3://{TGT}/{ids['img']}/images/"
    )
    jb = target_db.jbrowse_collection.find_one({})
    assert [t["uri"] for t in jb["tracks"]] == [
        f"s3://{TGT}/{ids['jb']}/tracks/sample.bam",
        HTTPS_URI,
    ]
    mqc = target_db.multiqc_collection.find_one({})
    assert mqc["s3_location"] == f"s3://{TGT}/{ids['mqc_dc']}/abc/multiqc.parquet"
