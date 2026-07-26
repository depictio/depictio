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
) -> str:
    version_id = f"v{seq}"
    versions.insert_one(
        {
            "version_id": version_id,
            "family_id": family,
            "project_id": "proj",
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

    for seq in range(1, 6):
        _add(versions, seq=seq, created=BASE - timedelta(days=9999))

    called = False

    def spy(*args, **kwargs):
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(version_store, "prune_family", spy)
    version_store.maybe_prune_family("fam", now=BASE)

    assert not called, "a small family must not trigger a scan-and-sort on every save"


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
