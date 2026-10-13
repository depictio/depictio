"""Retention policy for the dashboard version ledger.

Retention is a function rather than a Mongo TTL index for two reasons, and
both are load-bearing enough to test: a TTL index is unconditional, so it
could not exempt pinned versions, and the thinning rule (keep one per day past
a threshold) is application logic no index can express.

The invariant that matters most is the first one below. A pin is the user
saying "this state must not disappear"; every other rule here is a
convenience, and any of them silently overriding a pin would be a data-loss
bug rather than a tidy-up.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import mongomock
import pytest

BASE = datetime(2026, 3, 1, 12, 0, 0)


@pytest.fixture()
def versions(monkeypatch: pytest.MonkeyPatch):
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    client = mongomock.MongoClient()
    db = client["depictioTest"]
    collection = db["dashboard_versions"]
    monkeypatch.setattr(version_store, "dashboard_versions_collection", collection)
    monkeypatch.setattr(version_store, "dashboard_version_counters_collection", db["counters"])
    return collection


def _add(
    versions,
    *,
    seq: int,
    created: datetime,
    kind: str = "auto",
    pinned: bool = False,
    label: str | None = None,
    family: str = "fam",
    project: str = "proj",
) -> str:
    version_id = f"v{seq}"
    versions.insert_one(
        {
            "version_id": version_id,
            "family_id": family,
            "project_id": project,
            "seq": seq,
            "kind": kind,
            "pinned": pinned,
            "label": label,
            "created_at": created,
            "updated_at": created,
            "content_hash": f"hash-{seq}",
            "tabs": [],
            "data_collections": [],
        }
    )
    return version_id


def _prune(family: str = "fam", now: datetime | None = None) -> int:
    from depictio.api.v1.endpoints.dashboards_endpoints.version_store import prune_family

    return prune_family(family, now=now or BASE)


def _surviving(versions) -> set[str]:
    return {d["version_id"] for d in versions.find({})}


def test_pinned_versions_survive_the_age_cap(versions) -> None:
    """The invariant a TTL index could not express."""
    _add(versions, seq=1, created=BASE - timedelta(days=5000), pinned=True, label="Paper figure")
    _add(versions, seq=2, created=BASE - timedelta(days=5000))

    _prune()

    assert "v1" in _surviving(versions), "a pinned version must never be pruned, at any age"
    assert "v2" not in _surviving(versions)


def test_pinned_versions_survive_the_count_cap(versions) -> None:
    """Volume must not evict a pin either."""
    from depictio.api.v1.configs.config import settings

    _add(versions, seq=1, created=BASE - timedelta(days=1), pinned=True, label="Known good")
    for seq in range(2, settings.dashboard_versions.max_versions_per_family + 50):
        _add(versions, seq=seq, created=BASE - timedelta(minutes=seq))

    _prune()

    assert "v1" in _surviving(versions), "the count cap must skip over pinned versions"


def test_recent_autosaves_are_kept(versions) -> None:
    for seq in range(1, 11):
        _add(versions, seq=seq, created=BASE - timedelta(minutes=seq))

    removed = _prune()

    assert removed == 0
    assert len(_surviving(versions)) == 10


def test_count_cap_evicts_oldest_autosaves(versions) -> None:
    from depictio.api.v1.configs.config import settings

    cap = settings.dashboard_versions.max_versions_per_family
    for seq in range(1, cap + 21):
        _add(versions, seq=seq, created=BASE - timedelta(minutes=seq))

    _prune()

    survivors = _surviving(versions)
    assert len(survivors) == cap
    assert "v1" not in survivors, "the oldest autosave should go first"
    assert f"v{cap + 20}" in survivors, "the newest must always be kept"


def test_explicit_and_restore_versions_are_not_thinned(versions) -> None:
    """Deliberate markers are few; keep them for the whole retention window."""
    from depictio.api.v1.configs.config import settings

    cap = settings.dashboard_versions.max_versions_per_family
    _add(versions, seq=1, created=BASE - timedelta(days=2), kind="explicit")
    _add(versions, seq=2, created=BASE - timedelta(days=2), kind="restore")
    _add(versions, seq=3, created=BASE - timedelta(days=2), kind="import")
    for seq in range(4, cap + 40):
        _add(versions, seq=seq, created=BASE - timedelta(minutes=seq))

    _prune()

    survivors = _surviving(versions)
    assert {"v1", "v2", "v3"} <= survivors, "explicit/restore/import must outlive autosave churn"


def test_old_autosaves_thin_to_one_per_day(versions) -> None:
    """Past the daily threshold the timeline keeps shape without keeping bulk."""
    from depictio.api.v1.configs.config import settings

    old = BASE - timedelta(days=settings.dashboard_versions.keep_daily_for_days + 5)
    # Six autosaves spread across two days, all inside the retention window.
    for seq, offset in enumerate(
        [
            timedelta(hours=1),
            timedelta(hours=5),
            timedelta(hours=9),
            timedelta(days=1, hours=1),
            timedelta(days=1, hours=5),
            timedelta(days=1, hours=9),
        ],
        start=1,
    ):
        _add(versions, seq=seq, created=old + offset)

    _prune()

    survivors = list(versions.find({}))
    days = {d["created_at"].strftime("%Y-%m-%d") for d in survivors}
    assert len(survivors) == len(days) == 2, (
        f"expected one survivor per day, got {len(survivors)} across {len(days)} days"
    )


def test_beyond_retention_everything_unpinned_goes(versions) -> None:
    from depictio.api.v1.configs.config import settings

    ancient = BASE - timedelta(days=settings.dashboard_versions.retention_days + 10)
    _add(versions, seq=1, created=ancient)
    _add(versions, seq=2, created=ancient, kind="explicit")
    _add(versions, seq=3, created=ancient, pinned=True, label="keep")

    _prune()

    assert _surviving(versions) == {"v3"}


def test_prune_is_scoped_to_one_family(versions) -> None:
    """One dashboard's churn must never evict another's history.

    Both records deliberately share a ``version_id`` here. Real ids are uuid4
    and would never collide, so this forces the question the collision asks:
    is the delete scoped by family, or does it reach across the collection on
    id alone? The prune must be structurally incapable of the latter.
    """
    _add(versions, seq=1, created=BASE - timedelta(days=9999), family="fam")
    _add(versions, seq=1, created=BASE - timedelta(days=9999), family="other")

    _prune("fam")

    remaining = list(versions.find({}))
    assert len(remaining) == 1
    assert remaining[0]["family_id"] == "other"


def test_maybe_prune_skips_below_threshold(versions, monkeypatch) -> None:
    """The common path after a capture must be one count, not a full scan."""
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    # Recent: an expired version is the other trigger, tested on its own below.
    for seq in range(1, 6):
        _add(versions, seq=seq, created=BASE - timedelta(minutes=seq))

    called = False

    def spy(*args, **kwargs):
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(version_store, "prune_family", spy)
    version_store.maybe_prune_family("fam", now=BASE)

    assert not called, "a small family must not trigger a scan-and-sort on every save"


def test_maybe_prune_counts_only_what_a_prune_can_remove(versions, monkeypatch) -> None:
    """Saves and pins are never pruned, so they must not hold a family over the
    threshold: it would then stay over after every prune, and every capture
    would pay for a full scan."""
    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    cap = settings.dashboard_versions.max_versions_per_family
    for seq in range(1, cap + 1):
        _add(versions, seq=seq, created=BASE - timedelta(minutes=seq))
    for seq in range(cap + 1, cap + 41):
        _add(versions, seq=seq, created=BASE - timedelta(minutes=seq), kind="explicit")
    _add(versions, seq=cap + 41, created=BASE, pinned=True, label="Known good")

    calls: list[str] = []
    monkeypatch.setattr(version_store, "prune_family", lambda family, **_k: calls.append(family))

    version_store.maybe_prune_family("fam", now=BASE)
    assert calls == [], "kept versions alone must not trigger a prune"

    threshold = int(cap * 1.2)
    for seq in range(cap + 42, cap + 42 + threshold - cap + 1):
        _add(versions, seq=seq, created=BASE)
    version_store.maybe_prune_family("fam", now=BASE)
    assert calls == ["fam"], "autosaves past the threshold must still trigger one"


def test_maybe_prune_expires_old_saves_in_a_family_with_few_autosaves(
    versions, monkeypatch
) -> None:
    """Each Save click seals an autosave, so a family that is saved often keeps
    few autosaves and never reaches the count threshold. Its explicit versions
    must still expire after `retention_days`, and pins never do."""
    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    retention = settings.dashboard_versions.retention_days
    _add(versions, seq=1, created=BASE - timedelta(days=retention + 5), pinned=True, label="Kept")
    _add(versions, seq=2, created=BASE - timedelta(days=1), kind="explicit")

    calls: list[str] = []
    monkeypatch.setattr(version_store, "prune_family", lambda family, **_k: calls.append(family))

    version_store.maybe_prune_family("fam", now=BASE)
    assert calls == [], "a pin past the cutoff is never removed, so it must not trigger"

    _add(versions, seq=3, created=BASE - timedelta(days=retention + 1), kind="explicit")
    version_store.maybe_prune_family("fam", now=BASE)
    assert calls == ["fam"], "an expired Save must trigger a prune without the count"


def test_prune_never_loads_the_snapshots(versions, monkeypatch) -> None:
    """A family past the threshold holds well over a hundred full snapshots."""
    _add(versions, seq=1, created=BASE - timedelta(days=9999))
    projections: list = []
    real_find = versions.find

    def spy(query, projection=None, *args, **kwargs):
        # The delete that follows goes through `find` too, inside mongomock.
        if query == {"family_id": "fam"}:
            projections.append(projection)
        return real_find(query, projection, *args, **kwargs)

    monkeypatch.setattr(versions, "find", spy)

    assert _prune() == 1
    assert projections, "precondition: prune reads the family through find"
    for projection in projections:
        assert projection, "an unprojected read loads every snapshot"
        assert {k for k, v in projection.items() if v} == {
            "version_id",
            "created_at",
            "kind",
            "pinned",
            "label",
        }


def test_prune_never_raises_on_bad_records(versions) -> None:
    """A hand-written or legacy record must not break the save path."""
    versions.insert_one(
        {
            "version_id": "legacy",
            "family_id": "fam",
            "seq": 1,
            "kind": "auto",
            "created_at": "2026-01-01 00:00:00",  # a string, not a datetime
        }
    )
    _add(versions, seq=2, created=BASE - timedelta(days=9999))

    _prune()

    assert "legacy" in _surviving(versions), "an unparseable record is skipped, not deleted"


# ── Project delete ──────────────────────────────────────────────────────────


def test_project_delete_drops_its_ledgers_and_counters(versions) -> None:
    """A project delete removes dashboards wholesale, past the dashboard route.

    Without this every family's history and sequence counter outlived the
    project, unreachable: nothing lists versions of a dashboard that is gone.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    counters = version_store.dashboard_version_counters_collection
    _add(versions, seq=1, created=BASE, family="fam-a")
    _add(versions, seq=2, created=BASE, family="fam-a")
    _add(versions, seq=1, created=BASE, family="fam-b")
    _add(versions, seq=1, created=BASE, family="kept", project="other")
    counters.insert_many(
        [{"family_id": f, "seq": 2} for f in ("fam-a", "fam-b", "kept")],
    )

    removed = version_store.delete_project_versions("proj")

    assert removed == 3
    assert {d["family_id"] for d in versions.find({})} == {"kept"}
    assert {d["family_id"] for d in counters.find({})} == {"kept"}, (
        "a counter left behind would hand a recreated family's first version a stale seq"
    )


def test_project_delete_has_an_index_to_use(versions) -> None:
    """The distinct and the delete both filter the largest collection on it."""
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    version_store.ensure_dashboard_version_storage()

    keys = [spec["key"] for spec in versions.index_information().values()]
    assert [("project_id", 1)] in keys


def test_project_delete_never_raises(versions, monkeypatch) -> None:
    """Cleanup is best-effort: it must not fail the project delete."""
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    class Down:
        def distinct(self, *_a, **_k):
            raise RuntimeError("mongo is down")

    monkeypatch.setattr(version_store, "dashboard_versions_collection", Down())

    assert version_store.delete_project_versions("proj") == 0
