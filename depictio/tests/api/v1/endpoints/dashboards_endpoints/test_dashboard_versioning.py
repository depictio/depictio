"""Invariants of dashboard version capture, coalescing and pruning.

The editor autosaves on every layout mutation behind a 500 ms debounce, so a
single editing session produces dozens of ``POST /dashboards/save``. A naive
one-version-per-save ledger would be unreadable and would grow without bound,
while over-aggressive folding would collapse hours of work into one entry you
cannot step back through. These tests pin the middle ground.

The clock is injected everywhere (``now=``) rather than slept on — the same
discipline as ``test_dashboard_save_screenshot_guard.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import mongomock
import pytest

from depictio.models.models.base import PyObjectId

BASE = datetime(2026, 3, 1, 12, 0, 0)


@pytest.fixture()
def store(monkeypatch: pytest.MonkeyPatch):
    """Point the version store and capture seam at an in-memory Mongo."""
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store, versioning

    client = mongomock.MongoClient()
    db = client["depictioTest"]
    versions = db["dashboard_versions"]
    counters = db["dashboard_version_counters"]
    dashboards = db["dashboards"]
    deltatables = db["deltatables"]

    monkeypatch.setattr(version_store, "dashboard_versions_collection", versions)
    monkeypatch.setattr(version_store, "dashboard_version_counters_collection", counters)
    monkeypatch.setattr(versioning, "dashboards_collection", dashboards)
    monkeypatch.setattr(versioning, "deltatables_collection", deltatables)

    return {
        "versions": versions,
        "counters": counters,
        "dashboards": dashboards,
        "deltatables": deltatables,
    }


class _User:
    def __init__(self, uid: str, email: str) -> None:
        self.id = uid
        self.email = email


ALICE = _User("alice-id", "alice@example.com")
BOB = _User("bob-id", "bob@example.com")


def _make_dashboard(
    store: dict[str, Any],
    *,
    dashboard_id: PyObjectId | None = None,
    title: str = "Main",
    components: list[dict] | None = None,
    is_main_tab: bool = True,
    parent: PyObjectId | None = None,
    tab_order: int = 0,
) -> PyObjectId:
    did = dashboard_id or PyObjectId()
    store["dashboards"].insert_one(
        {
            "_id": did,
            "dashboard_id": did,
            "project_id": PyObjectId(),
            "title": title,
            "is_main_tab": is_main_tab,
            "parent_dashboard_id": parent,
            "tab_order": tab_order,
            "stored_metadata": components if components is not None else [],
            "left_panel_layout_data": [],
            "right_panel_layout_data": [],
            "permissions": {"owners": [{"email": "alice@example.com"}]},
            "is_public": False,
        }
    )
    return did


def _set_components(store: dict[str, Any], did: PyObjectId, components: list[dict]) -> None:
    store["dashboards"].update_one({"_id": did}, {"$set": {"stored_metadata": components}})


def _capture(did, **kwargs):
    from depictio.api.v1.endpoints.dashboards_endpoints.versioning import (
        capture_dashboard_version,
    )

    return capture_dashboard_version(did, **kwargs)


# ── Coalescing ──────────────────────────────────────────────────────────────


def test_burst_of_edits_collapses_to_one_version(store) -> None:
    """A drag session is one timeline entry, not forty."""
    did = _make_dashboard(store)

    for i in range(10):
        _set_components(store, did, [{"index": f"box-{i}", "dc_id": None}])
        _capture(did, author=ALICE, now=BASE + timedelta(seconds=i * 3))

    assert store["versions"].count_documents({}) == 1, "in-window autosaves must fold into one"
    doc = store["versions"].find_one({})
    assert doc["save_count"] == 10, "the fold should still record how many saves it absorbed"


def test_window_is_anchored_not_sliding(store) -> None:
    """No version may span longer than the coalescing window.

    This is the whole point of anchoring ``coalesce_until`` at creation. Under
    a *sliding* window, uninterrupted editing keeps pushing the deadline out,
    so an eight-hour session collapses into one entry spanning the whole day —
    a history you cannot step back through. Anchoring caps each entry at one
    window, so a long session becomes a reviewable series.
    """
    from depictio.api.v1.configs.config import settings

    window = settings.dashboard_versions.coalesce_window_seconds
    did = _make_dashboard(store)

    # Save every 60s for half an hour — continuous activity, never idle long
    # enough for a sliding window to lapse.
    for i in range(30):
        _set_components(store, did, [{"index": f"box-{i}"}])
        _capture(did, author=ALICE, now=BASE + timedelta(seconds=i * 60))

    versions = list(store["versions"].find({}))
    assert len(versions) > 1, "a sliding window would have produced exactly one entry"

    for version in versions:
        span = (version["updated_at"] - version["created_at"]).total_seconds()
        assert span <= window, (
            f"version {version['seq']} spans {span}s, longer than the {window}s window — "
            "the deadline is being extended on each save (sliding), not anchored"
        )


def test_different_authors_never_coalesce(store) -> None:
    """Two people editing must not have their work merged into one entry."""
    did = _make_dashboard(store)

    _set_components(store, did, [{"index": "a"}])
    _capture(did, author=ALICE, now=BASE)
    _set_components(store, did, [{"index": "b"}])
    _capture(did, author=BOB, now=BASE + timedelta(seconds=5))

    assert store["versions"].count_documents({}) == 2
    emails = {d["author_email"] for d in store["versions"].find({})}
    assert emails == {"alice@example.com", "bob@example.com"}


def test_explicit_save_never_coalesces(store) -> None:
    """An explicit Save is a deliberate marker and must stand alone."""
    did = _make_dashboard(store)

    _set_components(store, did, [{"index": "a"}])
    _capture(did, author=ALICE, now=BASE)
    _set_components(store, did, [{"index": "b"}])
    _capture(did, kind="explicit", author=ALICE, now=BASE + timedelta(seconds=5))

    kinds = sorted(d["kind"] for d in store["versions"].find({}))
    assert kinds == ["auto", "explicit"]


def test_autosave_after_explicit_opens_new_version(store) -> None:
    """An autosave must never fold *into* an explicit version and rewrite it."""
    did = _make_dashboard(store)

    _set_components(store, did, [{"index": "a"}])
    _capture(did, kind="explicit", author=ALICE, now=BASE)
    _set_components(store, did, [{"index": "b"}])
    _capture(did, author=ALICE, now=BASE + timedelta(seconds=5))

    assert store["versions"].count_documents({}) == 2
    explicit = store["versions"].find_one({"kind": "explicit"})
    assert explicit["tabs"][0]["stored_metadata"] == [{"index": "a"}], (
        "the explicit version's content must not be mutated by a later autosave"
    )


def test_pinning_seals_the_version(store) -> None:
    """A pinned version is what the user chose to keep — never overwrite it."""
    did = _make_dashboard(store)
    _set_components(store, did, [{"index": "a"}])
    _capture(did, author=ALICE, now=BASE)

    store["versions"].update_one({}, {"$set": {"pinned": True, "label": "Before rerun"}})

    _set_components(store, did, [{"index": "b"}])
    _capture(did, author=ALICE, now=BASE + timedelta(seconds=5))

    assert store["versions"].count_documents({}) == 2
    pinned = store["versions"].find_one({"pinned": True})
    assert pinned["tabs"][0]["stored_metadata"] == [{"index": "a"}]


# ── The no-op short circuit ─────────────────────────────────────────────────


def test_unchanged_save_writes_no_version(store) -> None:
    """The screenshot task rewrites last_saved_ts; that must leave no trace."""
    did = _make_dashboard(store, components=[{"index": "a"}])
    _capture(did, author=ALICE, now=BASE)

    # Same content, well outside the coalescing window.
    result = _capture(did, author=ALICE, now=BASE + timedelta(hours=5))

    assert result is None, "an identical save must not create a version"
    assert store["versions"].count_documents({}) == 1


def test_unchanged_save_still_counts(store) -> None:
    """A no-op save is invisible in the timeline but not silently dropped."""
    did = _make_dashboard(store, components=[{"index": "a"}])
    _capture(did, author=ALICE, now=BASE)
    _capture(did, author=ALICE, now=BASE + timedelta(hours=5))

    assert store["versions"].find_one({})["save_count"] == 2


def test_metadata_only_change_is_not_content(store) -> None:
    """last_saved_ts / permissions churn must not register as an edit."""
    did = _make_dashboard(store, components=[{"index": "a"}])
    _capture(did, author=ALICE, now=BASE)

    store["dashboards"].update_one(
        {"_id": did},
        {"$set": {"last_saved_ts": "2026-03-01 18:00:00", "is_public": True}},
    )
    result = _capture(did, author=ALICE, now=BASE + timedelta(hours=5))

    assert result is None, "fields outside the snapshot must not create versions"


# ── Family scope ────────────────────────────────────────────────────────────


def test_version_covers_the_whole_family(store) -> None:
    """One version spans main tab plus every child."""
    main = _make_dashboard(store, title="Main", components=[{"index": "m"}])
    _make_dashboard(store, title="Tab 2", parent=main, is_main_tab=False, tab_order=1)
    _make_dashboard(store, title="Tab 3", parent=main, is_main_tab=False, tab_order=2)

    _capture(main, author=ALICE, now=BASE)

    doc = store["versions"].find_one({})
    assert len(doc["tabs"]) == 3
    assert [t["title"] for t in doc["tabs"]] == ["Main", "Tab 2", "Tab 3"]


def test_saving_a_child_tab_versions_the_family(store) -> None:
    """A child-tab save belongs on the parent's timeline, not its own."""
    main = _make_dashboard(store, title="Main")
    child = _make_dashboard(store, title="Tab 2", parent=main, is_main_tab=False, tab_order=1)

    _capture(child, author=ALICE, now=BASE)

    doc = store["versions"].find_one({})
    assert doc["family_id"] == str(main), "the version's subject is the main tab"
    assert len(doc["tabs"]) == 2


def test_adding_a_tab_is_a_new_version(store) -> None:
    """The change a per-document ledger could not express."""
    main = _make_dashboard(store, title="Main")
    _capture(main, author=ALICE, now=BASE)

    _make_dashboard(store, title="Tab 2", parent=main, is_main_tab=False, tab_order=1)
    _capture(main, author=ALICE, now=BASE + timedelta(hours=2))

    versions = list(store["versions"].find({}).sort("seq", 1))
    assert [len(v["tabs"]) for v in versions] == [1, 2]


# ── The security invariant ──────────────────────────────────────────────────


def test_snapshot_excludes_permission_fields(store) -> None:
    """A snapshot must never be able to restore a revoked access grant."""
    from depictio.api.v1.endpoints.dashboards_endpoints.versioning import (
        SNAPSHOT_FORBIDDEN_FIELDS,
    )

    did = _make_dashboard(store, components=[{"index": "a"}])
    _capture(did, author=ALICE, now=BASE)

    tab = store["versions"].find_one({})["tabs"][0]
    for field in SNAPSHOT_FORBIDDEN_FIELDS:
        assert field not in tab, f"{field} must never be carried in a snapshot"


def test_snapshot_excludes_dead_dash_fields(store) -> None:
    """Dead fields would make every version diff look noisy."""
    from depictio.api.v1.endpoints.dashboards_endpoints.versioning import SNAPSHOT_DEAD_FIELDS

    did = _make_dashboard(store)
    store["dashboards"].update_one(
        {"_id": did},
        {"$set": {"buttons_data": {"x": 1}, "stored_children_data": [1, 2, 3]}},
    )
    _capture(did, author=ALICE, now=BASE)

    tab = store["versions"].find_one({})["tabs"][0]
    for field in SNAPSHOT_DEAD_FIELDS:
        assert field not in tab


# ── Sequence allocation ─────────────────────────────────────────────────────


def test_seq_is_monotonic_per_family(store) -> None:
    did = _make_dashboard(store)
    for i in range(4):
        _set_components(store, did, [{"index": f"box-{i}"}])
        _capture(did, kind="explicit", author=ALICE, now=BASE + timedelta(hours=i))

    seqs = sorted(d["seq"] for d in store["versions"].find({}))
    assert seqs == [1, 2, 3, 4]


def test_families_have_independent_sequences(store) -> None:
    a = _make_dashboard(store, title="A")
    b = _make_dashboard(store, title="B")

    _capture(a, kind="explicit", author=ALICE, now=BASE)
    _capture(b, kind="explicit", author=ALICE, now=BASE)

    seqs = {d["family_id"]: d["seq"] for d in store["versions"].find({})}
    assert set(seqs.values()) == {1}, "each family starts its own numbering at 1"


# ── Robustness ──────────────────────────────────────────────────────────────


def test_capture_of_missing_dashboard_is_a_no_op(store) -> None:
    assert _capture(PyObjectId(), author=ALICE, now=BASE) is None
    assert store["versions"].count_documents({}) == 0


def test_capture_quietly_swallows_failures(store, monkeypatch) -> None:
    """A version is a nice-to-have; a saved dashboard is not."""
    from depictio.api.v1.endpoints.dashboards_endpoints import versioning

    did = _make_dashboard(store)

    def boom(*_a, **_k):
        raise RuntimeError("mongo is on fire")

    monkeypatch.setattr(versioning, "load_family_docs", boom)

    assert versioning.capture_quietly(did, author=ALICE, now=BASE) is None


def test_disabled_setting_captures_nothing(store, monkeypatch) -> None:
    from depictio.api.v1.configs.config import settings

    did = _make_dashboard(store)
    monkeypatch.setattr(settings.dashboard_versions, "enabled", False)

    assert _capture(did, author=ALICE, now=BASE) is None
    assert store["versions"].count_documents({}) == 0


def test_oversized_snapshot_is_skipped_not_raised(store, monkeypatch) -> None:
    """Better no version than a save that fails on the BSON limit."""
    from depictio.api.v1.configs.config import settings

    did = _make_dashboard(store, components=[{"index": "a", "blob": "x" * 5000}])
    monkeypatch.setattr(settings.dashboard_versions, "max_snapshot_bytes", 100)

    assert _capture(did, author=ALICE, now=BASE) is None
    assert store["versions"].count_documents({}) == 0


# ── Baseline ────────────────────────────────────────────────────────────────
#
# Capture runs *after* a save, so without a baseline every version describes a
# state the user has already left. For a dashboard that predates the ledger —
# which is every existing dashboard — that makes its original state the one
# state no version can restore, and "restore doesn't go back to the original"
# is exactly what a user reports.


def _ensure_baseline(did, **kwargs):
    from depictio.api.v1.endpoints.dashboards_endpoints.versioning import (
        ensure_baseline_quietly,
    )

    return ensure_baseline_quietly(did, **kwargs)


def test_baseline_makes_the_pre_edit_state_restorable(store) -> None:
    """The state before the first tracked edit must be reachable."""
    original = [{"index": "a"}, {"index": "b"}, {"index": "c"}]
    did = _make_dashboard(store, components=original)

    # First tracked write: seed the baseline, then the edit is captured.
    _ensure_baseline(did, author=ALICE)
    _set_components(store, did, original[:1])
    _capture(did, author=ALICE, now=BASE)

    reachable = [
        len(v["tabs"][0]["stored_metadata"]) for v in store["versions"].find({}).sort("seq", 1)
    ]
    assert len(original) in reachable, (
        f"the pristine {len(original)}-component state must be restorable; got {reachable}"
    )


def test_baseline_is_labelled_so_it_explains_itself(store) -> None:
    did = _make_dashboard(store, components=[{"index": "a"}])

    record = _ensure_baseline(did, author=ALICE)

    assert record is not None
    assert record.label == "Before first tracked change"
    assert record.kind == "explicit", "a baseline must never be thinned as an autosave"


def test_baseline_is_seeded_only_once(store) -> None:
    """A per-save baseline would double the ledger for no added recoverability."""
    did = _make_dashboard(store, components=[{"index": "a"}])

    _ensure_baseline(did, author=ALICE)
    _set_components(store, did, [{"index": "b"}])
    _capture(did, author=ALICE, now=BASE)
    _ensure_baseline(did, author=ALICE)

    assert store["versions"].count_documents({"label": "Before first tracked change"}) == 1


def test_baseline_belongs_to_the_family_not_the_tab(store) -> None:
    """Saving a child tab must seed the family's baseline, not a second one."""
    main = _make_dashboard(store, components=[{"index": "main-a"}])
    child = _make_dashboard(
        store, title="Tab 2", components=[{"index": "child-a"}], is_main_tab=False, parent=main
    )

    _ensure_baseline(child, author=ALICE)

    assert store["versions"].count_documents({}) == 1
    doc = store["versions"].find_one({})
    assert doc["family_id"] == str(main)
    assert doc["tab_count"] == 2, "a baseline covers the whole family, as every version does"


def test_baseline_never_raises(store, monkeypatch) -> None:
    """A version is a nice-to-have; a saved dashboard is not."""
    from depictio.api.v1.endpoints.dashboards_endpoints import versioning

    did = _make_dashboard(store, components=[{"index": "a"}])
    monkeypatch.setattr(
        versioning,
        "capture_dashboard_version",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("mongo is down")),
    )

    assert _ensure_baseline(did, author=ALICE) is None
