"""Concurrent link-filter resolution collapses to one call.

The lock is the point: without it, N components firing on the same filter
change all miss the cache at once and each does the full resolution — the
cache would only ever help a fan-out that never comes.
"""

import threading
import time

import pytest

pytestmark = pytest.mark.no_db


@pytest.fixture(autouse=True)
def _stub_aggregation_hash(monkeypatch):
    """Keep the cache-key data salt out of Mongo by default.

    The key is salted with each DC's ``aggregation_hash``, which is a real
    database lookup. Tests that don't care about invalidation would otherwise
    reach for Mongo with fake ids and rely on the lookup failing quietly — a
    dependency that would turn into flakiness the moment a Mongo happened to be
    reachable. Tests that DO care override this.
    """
    monkeypatch.setattr(
        "depictio.api.v1.deltatables_utils._get_aggregation_hash",
        lambda dc_id: "stub",
    )


def test_concurrent_resolutions_collapse_to_one(monkeypatch):
    from depictio.api.v1.endpoints.dashboards_endpoints import routes

    calls = []
    lock = threading.Lock()

    def slow_resolve(*, filters, target_dc_id, project_id, access_token, component_type):
        with lock:
            calls.append(target_dc_id)
        time.sleep(0.05)  # long enough that peers pile up behind it
        return list(filters) + [{"index": "synthetic", "value": ["x"]}]

    monkeypatch.setattr(routes, "_resolve_link_filters", slow_resolve)
    routes._link_filter_cache.clear()
    routes._link_filter_locks.clear()

    filters = [{"index": "i1", "value": ["Adelie"], "metadata": {"dc_id": "dcA"}}]
    results = []

    def worker():
        results.append(
            routes._resolve_link_filters_cached(
                filters=filters,
                target_dc_id="dcTarget",
                project_id="p1",
                access_token="tok",
                component_type="figure",
            )
        )

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(calls) == 1, f"resolved {len(calls)} times for one fan-out"
    assert len(results) == 12
    assert all(r == results[0] for r in results), "callers disagreed on the resolution"
    # Callers must not be able to mutate each other's list through the cache.
    results[0].append({"index": "mutated"})
    assert len(results[1]) == 2


def test_different_filter_values_do_not_share_a_cache_entry(monkeypatch):
    from depictio.api.v1.endpoints.dashboards_endpoints import routes

    seen = []

    def resolve(*, filters, target_dc_id, project_id, access_token, component_type):
        seen.append(filters[0]["value"])
        return list(filters)

    monkeypatch.setattr(routes, "_resolve_link_filters", resolve)
    routes._link_filter_cache.clear()
    routes._link_filter_locks.clear()

    for value in (["Adelie"], ["Gentoo"], ["Adelie"]):
        routes._resolve_link_filters_cached(
            filters=[{"index": "i1", "value": value, "metadata": {"dc_id": "dcA"}}],
            target_dc_id="dcTarget",
            project_id="p1",
            access_token="tok",
            component_type="figure",
        )

    # Adelie resolved once and reused; Gentoo is a distinct key.
    assert seen == [["Adelie"], ["Gentoo"]]


def test_empty_filters_never_resolve(monkeypatch):
    """Unfiltered renders must not pay for link resolution at all."""
    from depictio.api.v1.endpoints.dashboards_endpoints import routes

    def boom(**kwargs):
        raise AssertionError("resolution attempted with no filters")

    monkeypatch.setattr(routes, "_resolve_link_filters", boom)
    assert (
        routes._resolve_link_filters_cached(
            filters=[],
            target_dc_id="dcTarget",
            project_id="p1",
            access_token="tok",
            component_type="figure",
        )
        == []
    )


def test_dc_update_invalidates_the_memo(monkeypatch):
    """Any update to a DC must change the answer, not be masked by the cache.

    A link resolves *which target rows correspond to the filtered source rows*,
    so the correct resolution moves whenever either DC is rewritten — an
    appended run, a re-ingest of the same data, a compaction. Keyed on the
    filter alone, the cache would keep serving the pre-update answer and the
    affected rows would be silently absent from every linked component.

    The salt is ``aggregation_hash`` rather than ``aggregation_version``: the
    version counts writes, the hash is derived from the Delta log and so tracks
    the state those writes produced.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints import routes

    agg = {"hash": "h1"}
    resolutions = []

    def resolve(*, filters, target_dc_id, project_id, access_token, component_type):
        resolutions.append(agg["hash"])
        n = int(agg["hash"][1:])
        return [{"index": "synthetic", "value": [f"sample{i}" for i in range(n)]}]

    monkeypatch.setattr(routes, "_resolve_link_filters", resolve)
    monkeypatch.setattr(
        "depictio.api.v1.deltatables_utils._get_aggregation_hash",
        lambda dc_id: agg["hash"],
    )
    routes._link_filter_cache.clear()
    routes._link_filter_locks.clear()

    filters = [{"index": "i1", "value": ["Adelie"], "metadata": {"dc_id": "dcA"}}]

    def resolve_once():
        return routes._resolve_link_filters_cached(
            filters=filters,
            target_dc_id="dcTarget",
            project_id="p1",
            access_token="tok",
            component_type="figure",
        )

    first = resolve_once()
    assert resolve_once() == first, "an unchanged DC should reuse the memo"
    assert resolutions == ["h1"]

    # The DC is rewritten: its aggregation_hash changes.
    agg["hash"] = "h2"
    after = resolve_once()

    assert resolutions == ["h1", "h2"], "the memo survived a DC update"
    assert after != first
    assert len(after[0]["value"]) == 2, "the new sample is missing from the resolution"


def test_link_resolution_cache_key_is_salted_by_hash(monkeypatch):
    """The 300s-TTL cache in filter_links must key on the data hash too."""
    from depictio.api.v1 import filter_links

    agg = {"hash": "h1"}
    monkeypatch.setattr(
        "depictio.api.v1.deltatables_utils._get_aggregation_hash",
        lambda dc_id: agg["hash"],
    )

    posted = []

    class _Resp:
        status_code = 200

        def json(self):
            return {"resolved_values": [f"s{agg['hash']}"]}

    def fake_post(url, **kwargs):
        posted.append(agg["hash"])
        return _Resp()

    monkeypatch.setattr(filter_links.httpx, "post", fake_post)
    filter_links.clear_link_resolution_cache()

    def call():
        return filter_links.resolve_link_values(
            project_id="p1",
            source_dc_id="dcA",
            source_column="species",
            filter_values=["Adelie"],
            target_dc_id="dcB",
            token="tok",
        )

    call()
    call()
    assert posted == ["h1"], "identical inputs on an unchanged DC should hit the cache"

    agg["hash"] = "h2"
    call()
    assert posted == ["h1", "h2"], "a DC update must not be served from the cache"
