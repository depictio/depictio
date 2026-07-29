"""MultiQC time travel: pin the object set, not the collection.

MultiQC keeps no commit log, so Delta's mechanism does not apply. What it does
have is content addressing — every ingest writes
``s3://{bucket}/{dc_id}/{sha256}/multiqc.parquet`` at a fresh key and leaves the
previous object in place — which means recording *which keys* made up the
collection is enough to reproduce it exactly.

That property is load-bearing and was, until this change, violated by two write
paths: the CLI's ``--overwrite`` branch reused the old content key for new
bytes, and the API's "replace all" deleted the superseded objects outright.
Either one turns a pinned manifest into a pointer at something else.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import mongomock
import pytest
from bson import ObjectId

BASE = datetime(2026, 3, 1, 12, 0, 0)
DC_ID = str(ObjectId())


@pytest.fixture()
def store(monkeypatch: pytest.MonkeyPatch):
    """In-memory `multiqc` + `multiqc_manifests` collections."""
    import depictio.api.v1.db as api_db
    from depictio.api.v1.services.multiqc import manifests

    client = mongomock.MongoClient()
    db = client["depictioTest"]
    monkeypatch.setattr(api_db, "multiqc_collection", db["multiqc"])
    monkeypatch.setattr(api_db, "multiqc_manifests_collection", db["multiqc_manifests"])
    return {"reports": db["multiqc"], "manifests": db["multiqc_manifests"], "mod": manifests}


def _add_report(store, name: str, samples: list[str], *, dc_id: str = DC_ID) -> str:
    location = f"s3://bucket/{dc_id}/{name}/multiqc.parquet"
    store["reports"].insert_one(
        {
            "data_collection_id": dc_id,
            "s3_location": location,
            "original_file_path": f"/data/{name}/multiqc.parquet",
            "metadata": {"canonical_samples": samples, "samples": samples},
        }
    )
    return location


class TestDigest:
    def test_it_is_order_independent(self, store):
        digest = store["mod"].compute_manifest_digest
        assert digest(["b", "a"]) == digest(["a", "b"])

    def test_it_ignores_duplicates(self, store):
        digest = store["mod"].compute_manifest_digest
        assert digest(["a", "a", "b"]) == digest(["a", "b"])

    def test_an_empty_set_has_no_digest(self, store):
        assert store["mod"].compute_manifest_digest([]) == ""

    def test_it_matches_the_prerender_cache_construction(self, store):
        """`_compute_s3_locations_hash` has computed exactly this since before
        versioning existed. If the two drift, the prerender cache can serve one
        generation's figures under another generation's identity."""
        import hashlib

        locations = ["s3://b/x/multiqc.parquet", "s3://b/y/multiqc.parquet"]
        expected = hashlib.sha256("|".join(sorted(locations)).encode()).hexdigest()

        assert store["mod"].compute_manifest_digest(locations) == expected


class TestRecordingGenerations:
    def test_the_first_ingest_records_generation_one(self, store):
        _add_report(store, "aaa", ["s1", "s2"])

        manifest = store["mod"].record_generation(DC_ID, trigger="ingest")

        assert manifest is not None
        assert manifest["generation"] == 1
        assert manifest["report_count"] == 1
        assert manifest["sample_count"] == 2

    def test_an_append_records_a_new_generation(self, store):
        _add_report(store, "aaa", ["s1"])
        first = store["mod"].record_generation(DC_ID)
        _add_report(store, "bbb", ["s2"])
        second = store["mod"].record_generation(DC_ID, trigger="append")

        assert second["generation"] == 2
        assert second["digest"] != first["digest"]
        assert len(second["s3_locations"]) == 2
        assert second["sample_count"] == 2

    def test_re_recording_an_unchanged_set_is_a_no_op(self, store):
        """A CLI retry after a dropped response must not inflate the ledger."""
        _add_report(store, "aaa", ["s1"])
        first = store["mod"].record_generation(DC_ID)
        again = store["mod"].record_generation(DC_ID)

        assert again["generation"] == first["generation"] == 1
        assert store["manifests"].count_documents({}) == 1

    def test_a_collection_with_no_reports_records_nothing(self, store):
        assert store["mod"].record_generation(DC_ID) is None
        assert store["manifests"].count_documents({}) == 0

    def test_generations_do_not_leak_across_collections(self, store):
        other = str(ObjectId())
        _add_report(store, "aaa", ["s1"])
        _add_report(store, "bbb", ["s2"], dc_id=other)

        mine = store["mod"].record_generation(DC_ID)
        theirs = store["mod"].record_generation(other)

        assert mine["generation"] == theirs["generation"] == 1
        assert mine["s3_locations"] != theirs["s3_locations"]

    def test_a_write_failure_never_raises_into_an_ingest(self, store, monkeypatch):
        """A missing manifest costs one version's replayability; a raised
        exception costs someone's data."""
        _add_report(store, "aaa", ["s1"])

        def boom(*a, **k):
            raise RuntimeError("mongo is down")

        monkeypatch.setattr(store["manifests"], "insert_one", boom)

        assert store["mod"].record_generation(DC_ID) is None


class TestResolvingAPin:
    def test_a_digest_resolves_the_generation_it_names(self, store):
        first_loc = _add_report(store, "aaa", ["s1"])
        first = store["mod"].record_generation(DC_ID)
        _add_report(store, "bbb", ["s2"])
        store["mod"].record_generation(DC_ID)

        resolved = store["mod"].get_manifest(DC_ID, digest=first["digest"])

        assert resolved["s3_locations"] == [first_loc]

    def test_an_instant_resolves_the_newest_generation_at_or_before_it(self, store):
        _add_report(store, "aaa", ["s1"])
        store["mod"].record_generation(DC_ID)
        store["manifests"].update_one(
            {"generation": 1}, {"$set": {"created_at": BASE - timedelta(days=2)}}
        )
        _add_report(store, "bbb", ["s2"])
        store["mod"].record_generation(DC_ID)
        store["manifests"].update_one({"generation": 2}, {"$set": {"created_at": BASE}})

        resolved = store["mod"].get_manifest(DC_ID, as_of=BASE - timedelta(days=1))

        assert resolved["generation"] == 1

    def test_an_unknown_digest_resolves_to_nothing(self, store):
        _add_report(store, "aaa", ["s1"])
        store["mod"].record_generation(DC_ID)

        assert store["mod"].get_manifest(DC_ID, digest="not-a-digest") is None

    def test_a_digest_from_another_collection_does_not_resolve(self, store):
        other = str(ObjectId())
        _add_report(store, "aaa", ["s1"], dc_id=other)
        theirs = store["mod"].record_generation(other)

        assert store["mod"].get_manifest(DC_ID, digest=theirs["digest"]) is None


class TestTheReadPath:
    """`fetch_s3_locations_from_dc` is where the pin actually takes effect —
    everything downstream derives from its return value."""

    def test_no_pin_returns_the_current_set(self, store):
        _add_report(store, "aaa", ["s1"])
        store["mod"].record_generation(DC_ID)
        second = _add_report(store, "bbb", ["s2"])
        store["mod"].record_generation(DC_ID)

        from depictio.api.v1.services.multiqc.dc_lookup import fetch_s3_locations_from_dc

        assert second in fetch_s3_locations_from_dc(DC_ID)

    def test_a_pin_returns_the_set_that_generation_had(self, store):
        first_loc = _add_report(store, "aaa", ["s1"])
        first = store["mod"].record_generation(DC_ID)
        second_loc = _add_report(store, "bbb", ["s2"])
        store["mod"].record_generation(DC_ID)

        from depictio.api.v1.services.multiqc.dc_lookup import fetch_s3_locations_from_dc

        pinned = fetch_s3_locations_from_dc(DC_ID, manifest=first["digest"])

        assert pinned == [first_loc]
        assert second_loc not in pinned

    def test_an_unresolvable_pin_falls_back_to_live(self, store):
        """A version whose objects were swept should render current data with a
        warning, not an empty dashboard."""
        current = _add_report(store, "aaa", ["s1"])

        from depictio.api.v1.services.multiqc.dc_lookup import fetch_s3_locations_from_dc

        assert fetch_s3_locations_from_dc(DC_ID, manifest="gone") == [current]


class TestTheStamp:
    def test_a_multiqc_collection_stamps_the_manifest_arm(self, store, monkeypatch):
        from depictio.api.v1.endpoints.dashboards_endpoints import versioning
        from depictio.models.models.dashboard_versions import TabSnapshot

        monkeypatch.setattr(versioning, "deltatables_collection", mongomock.MongoClient()["d"]["x"])

        _add_report(store, "aaa", ["s1", "s2"])
        manifest = store["mod"].record_generation(DC_ID)

        tabs = [
            TabSnapshot(
                dashboard_id="t1",
                stored_metadata=[{"dc_id": DC_ID, "dc_config": {"type": "multiqc"}}],
            )
        ]
        stamps = versioning.build_dc_stamps(tabs, now=BASE)

        assert len(stamps) == 1
        stamp = stamps[0]
        assert stamp.version_kind == "manifest"
        assert stamp.manifest_digest == manifest["digest"]
        assert stamp.sample_count == 2
        assert stamp.reason is None

    def test_a_collection_with_no_manifest_says_so(self, store, monkeypatch):
        """Ingested before manifests existed. `as_of` still anchors a backfill."""
        from depictio.api.v1.endpoints.dashboards_endpoints import versioning
        from depictio.models.models.dashboard_versions import TabSnapshot

        monkeypatch.setattr(versioning, "deltatables_collection", mongomock.MongoClient()["d"]["x"])

        tabs = [
            TabSnapshot(
                dashboard_id="t1",
                stored_metadata=[{"dc_id": DC_ID, "dc_config": {"type": "multiqc"}}],
            )
        ]
        stamps = versioning.build_dc_stamps(tabs, now=BASE)

        assert stamps[0].version_kind == "none"
        assert stamps[0].reason == "no_manifest_recorded"
        assert stamps[0].as_of == BASE
