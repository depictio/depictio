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
    projects = db["projects"]

    monkeypatch.setattr(version_store, "dashboard_versions_collection", versions)
    monkeypatch.setattr(version_store, "dashboard_version_counters_collection", counters)
    monkeypatch.setattr(versioning, "dashboards_collection", dashboards)
    monkeypatch.setattr(versioning, "deltatables_collection", deltatables)
    monkeypatch.setattr(versioning, "projects_collection", projects)

    return {
        "versions": versions,
        "counters": counters,
        "dashboards": dashboards,
        "deltatables": deltatables,
        "projects": projects,
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


def test_a_strict_capture_says_why_it_recorded_nothing(store, monkeypatch) -> None:
    """Strict, None means unchanged content and nothing else.

    Naming the current state labels the newest version when nothing changed;
    for any other reason there is no version holding the live state to label.
    """
    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.endpoints.dashboards_endpoints.versioning import CaptureSkipped

    did = _make_dashboard(store, components=[{"index": "a"}])
    _capture(did, kind="explicit", author=ALICE, now=BASE)
    assert _capture(did, kind="explicit", author=ALICE, now=BASE, strict=True) is None

    with pytest.raises(CaptureSkipped) as missing:
        _capture(PyObjectId(), author=ALICE, now=BASE, strict=True)
    assert missing.value.reason == "missing"

    _set_components(store, did, [{"index": "b", "blob": "x" * 5000}])
    monkeypatch.setattr(settings.dashboard_versions, "max_snapshot_bytes", 100)
    with pytest.raises(CaptureSkipped) as oversized:
        _capture(did, kind="explicit", author=ALICE, now=BASE, strict=True)
    assert oversized.value.reason == "oversized"
    assert oversized.value.limit == 100
    assert oversized.value.size is not None and oversized.value.size > 100

    monkeypatch.setattr(settings.dashboard_versions, "enabled", False)
    with pytest.raises(CaptureSkipped) as disabled:
        _capture(did, kind="explicit", author=ALICE, now=BASE, strict=True)
    assert disabled.value.reason == "disabled"
    assert store["versions"].count_documents({}) == 1


# ── Concurrent writers ──────────────────────────────────────────────────────
#
# Capture reads the newest version, then builds the snapshot, then writes.
# Across API workers, anything can land in between.


@pytest.mark.parametrize(
    "sealed_by",
    [{"pinned": True}, {"label": "Known good"}, {"kind": "explicit"}],
    ids=["pin", "name", "save-click"],
)
def test_a_fold_never_rewrites_a_version_sealed_after_it_was_read(
    store, monkeypatch, sealed_by
) -> None:
    """The fold re-checks the version, and records a new one if it was sealed."""
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    did = _make_dashboard(store, components=[{"index": "a"}])
    first = _capture(did, author=ALICE, now=BASE)
    assert first is not None
    stale = store["versions"].find_one({"version_id": first.version_id})
    store["versions"].update_one({"version_id": first.version_id}, {"$set": sealed_by})
    # Capture reads the newest version before the seal lands.
    monkeypatch.setattr(version_store, "latest_version", lambda _family: stale)

    _set_components(store, did, [{"index": "b"}])
    second = _capture(did, author=ALICE, now=BASE + timedelta(seconds=30))

    assert second is not None and second.version_id != first.version_id
    assert store["versions"].count_documents({}) == 2
    kept = store["versions"].find_one({"version_id": first.version_id})
    assert kept["tabs"][0]["stored_metadata"] == [{"index": "a"}], "the sealed state was rewritten"
    assert kept["save_count"] == 1


def test_a_counter_behind_its_ledger_catches_up_instead_of_losing_versions(store) -> None:
    """A counter restored from an older backup than its ledger.

    Every allocation hit the unique (family, seq) index until the counter
    caught up, and each hit was a version silently not recorded.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    version_store.ensure_dashboard_version_storage()
    did = _make_dashboard(store)
    for hour, index in enumerate("abc"):
        _set_components(store, did, [{"index": index}])
        _capture(did, kind="explicit", author=ALICE, now=BASE + timedelta(hours=hour))
    store["counters"].update_one({"family_id": str(did)}, {"$set": {"seq": 1}})

    _set_components(store, did, [{"index": "d"}])
    record = _capture(did, kind="explicit", author=ALICE, now=BASE + timedelta(hours=5))

    assert record is not None and record.seq == 4
    assert sorted(v["seq"] for v in store["versions"].find({})) == [1, 2, 3, 4]
    assert store["counters"].find_one({"family_id": str(did)})["seq"] == 4


# ── Denormalised counts ─────────────────────────────────────────────────────
#
# The timeline query projects `tabs` away, so anything derived from `tabs` is
# unavailable exactly where the counts are displayed. They must be persisted.


def test_counts_are_persisted_not_derived(store) -> None:
    main = _make_dashboard(store, title="Main", components=[{"index": "a"}, {"index": "b"}])
    _make_dashboard(store, title="Tab 2", parent=main, is_main_tab=False, tab_order=1)

    _capture(main, kind="explicit", author=ALICE, now=BASE)

    doc = store["versions"].find_one({})
    assert doc["component_count"] == 2
    assert doc["tab_count"] == 2


def test_counts_survive_the_list_projection(store) -> None:
    """The regression: the drawer read 0 components for every version."""
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    did = _make_dashboard(store, components=[{"index": "a"}, {"index": "b"}, {"index": "c"}])
    _capture(did, kind="explicit", author=ALICE, now=BASE)

    row = version_store.list_versions(str(did))[0]

    assert "tabs" not in row, "the timeline query must not ship the snapshot"
    assert row["component_count"] == 3, "counts must survive without `tabs` to derive from"
    assert row["tab_count"] == 1


def test_counts_follow_a_coalesced_edit(store) -> None:
    """Folding replaces the content, so the counts must move with it."""
    did = _make_dashboard(store, components=[{"index": "a"}])
    _capture(did, author=ALICE, now=BASE)

    _set_components(store, did, [{"index": "a"}, {"index": "b"}, {"index": "c"}])
    _capture(did, author=ALICE, now=BASE + timedelta(seconds=5))

    assert store["versions"].count_documents({}) == 1, "precondition: the saves coalesced"
    assert store["versions"].find_one({})["component_count"] == 3


# ── Field coverage ──────────────────────────────────────────────────────────
#
# A snapshot is built from an explicit list of fields, so a field added to the
# dashboard document is silently dropped by default: restore loses it, and a
# save that only changes it looks like a no-op. These pin the list against the
# model instead of against memory.


def test_every_dashboard_field_is_snapshotted_or_excluded_on_purpose() -> None:
    """A new `DashboardData` field must be versioned or deliberately excluded."""
    from depictio.api.v1.endpoints.dashboards_endpoints.versioning import (
        SNAPSHOT_EXCLUDED_FIELDS,
    )
    from depictio.models.models.dashboard_versions import TabSnapshot
    from depictio.models.models.dashboards import DashboardData

    unaccounted = (
        set(DashboardData.model_fields) - set(TabSnapshot.model_fields) - SNAPSHOT_EXCLUDED_FIELDS
    )

    assert not unaccounted, (
        f"{sorted(unaccounted)} would be dropped by every snapshot. Add them to "
        "TabSnapshot (and build_tab_snapshots), or to a commented group in "
        "SNAPSHOT_EXCLUDED_FIELDS saying why they are not content."
    )


def test_no_field_is_both_snapshotted_and_excluded() -> None:
    from depictio.api.v1.endpoints.dashboards_endpoints.versioning import (
        SNAPSHOT_EXCLUDED_FIELDS,
    )
    from depictio.models.models.dashboard_versions import TabSnapshot

    assert not set(TabSnapshot.model_fields) & SNAPSHOT_EXCLUDED_FIELDS


#: One value per schema-2 field, none of them its default.
SCHEMA_2_VALUES: dict[str, Any] = {
    "filter_sections": [{"name": "Sample", "icon": "mdi:test-tube", "collapsed": True}],
    "grid_sections": [{"name": "Key figures", "filter_bar": True}],
    "category_colors": {"species": {"Adelie": "#1a4f8f"}},
    "funnel_filtering": False,
    "filter_panel_default": "collapsed",
    "content_width_default": "compact",
    "show_tab_header": False,
    "show_guide": False,
    "guide_intro": "Start with the QC tab.",
    "advanced_viz_controls": "rail",
    "autofit": False,
    "brand_theme": {"primary": "#1a4f8f", "logo_mode": "none"},
}


def test_snapshot_records_the_settings_added_since_schema_1(store) -> None:
    did = _make_dashboard(store)
    store["dashboards"].update_one({"_id": did}, {"$set": SCHEMA_2_VALUES})

    record = _capture(did, kind="explicit", author=ALICE, now=BASE)

    tab = store["versions"].find_one({})["tabs"][0]
    for field, value in SCHEMA_2_VALUES.items():
        assert tab[field] == value, f"{field} was not carried into the snapshot"
    assert record is not None and record.record_schema_version == 2


def test_a_change_to_a_new_setting_alone_is_a_new_version(store) -> None:
    """The bug this guards: such a save was a no-op as far as the ledger knew."""
    did = _make_dashboard(store, components=[{"index": "a"}])
    _capture(did, author=ALICE, now=BASE)

    store["dashboards"].update_one(
        {"_id": did}, {"$set": {"grid_sections": [{"name": "Overview"}]}}
    )
    result = _capture(did, author=ALICE, now=BASE + timedelta(hours=5))

    assert result is not None, "only grid_sections changed, and that is an edit"
    assert store["versions"].count_documents({}) == 2


def test_a_logo_cache_buster_alone_is_not_a_change(store) -> None:
    """The boot-time logo migration rewrites `?v=`; the logo itself is the same."""
    did = _make_dashboard(store)
    logo = "/depictio/api/v1/dashboards/logo/abc"
    store["dashboards"].update_one(
        {"_id": did}, {"$set": {"brand_theme": {"logo_mode": "custom", "logo_url": f"{logo}?v=1"}}}
    )
    _capture(did, author=ALICE, now=BASE)

    store["dashboards"].update_one({"_id": did}, {"$set": {"brand_theme.logo_url": f"{logo}?v=2"}})
    result = _capture(did, author=ALICE, now=BASE + timedelta(hours=5))

    assert result is None
    assert store["versions"].count_documents({}) == 1


def test_a_family_using_no_new_setting_keeps_its_schema_1_hash(store) -> None:
    """Upgrading must not make every dashboard's next save look like an edit."""
    import hashlib
    import json

    from depictio.api.v1.endpoints.dashboards_endpoints import versioning
    from depictio.models.models.dashboard_versions import TAB_SCHEMA_1_FIELDS

    did = _make_dashboard(store, components=[{"index": "a"}])
    tabs = versioning.build_tab_snapshots(versioning.load_family_docs(did))

    schema_1 = [t.model_dump(mode="json", include=set(TAB_SCHEMA_1_FIELDS)) for t in tabs]
    expected = hashlib.sha256(
        json.dumps(schema_1, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert versioning.compute_content_hash(tabs) == expected


def test_legacy_appearance_fields_are_folded_into_the_snapshot(store) -> None:
    """A document still carrying the pre-brand-theme keys renders with them."""
    did = _make_dashboard(store)
    store["dashboards"].update_one(
        {"_id": did},
        {"$set": {"logo_url": "/static/logo.png", "plot_theme": {"template": "plotly_dark"}}},
    )

    _capture(did, kind="explicit", author=ALICE, now=BASE)

    theme = store["versions"].find_one({})["tabs"][0]["brand_theme"]
    assert theme["logo_url"] == "/static/logo.png"
    assert theme["plots"] == {"template": "plotly_dark"}


def test_a_child_tabs_own_guide_copy_is_not_recorded(store) -> None:
    """The viewer reads the Guide from the main tab; a child's copy is invisible."""
    main = _make_dashboard(store, title="Main")
    child = _make_dashboard(store, title="Tab 2", parent=main, is_main_tab=False, tab_order=1)
    store["dashboards"].update_one({"_id": child}, {"$set": {"show_guide": False}})

    _capture(main, kind="explicit", author=ALICE, now=BASE)

    tabs = {t["title"]: t for t in store["versions"].find_one({})["tabs"]}
    assert tabs["Tab 2"]["show_guide"] is True


def test_source_key_is_kept_but_never_hashed(store) -> None:
    """Identity, not content: setting it is not an edit."""
    did = _make_dashboard(store)
    _capture(did, author=ALICE, now=BASE)

    store["dashboards"].update_one({"_id": did}, {"$set": {"source_key": "nf-core/x:base.yaml"}})
    assert _capture(did, kind="explicit", author=ALICE, now=BASE + timedelta(hours=5)) is None

    # The next version written for a real edit carries it.
    _set_components(store, did, [{"index": "a"}])
    _capture(did, kind="explicit", author=ALICE, now=BASE + timedelta(hours=6))
    latest = store["versions"].find_one({}, sort=[("seq", -1)])
    assert latest["tabs"][0]["source_key"] == "nf-core/x:base.yaml"


# ── Unchanged content, whatever the kind ────────────────────────────────────
#
# A "state before" capture (ahead of a restore or an import) is explicit, and
# the state it records is usually the newest version already. Writing nothing
# for unchanged content, whatever the kind, is what keeps it from duplicating
# that version every time.


def test_an_unchanged_explicit_capture_writes_nothing(store) -> None:
    """Even an explicit capture: a copy of the newest version is noise."""
    did = _make_dashboard(store, components=[{"index": "a"}])
    _capture(did, kind="explicit", author=ALICE, now=BASE)

    result = _capture(did, kind="explicit", author=ALICE, now=BASE + timedelta(hours=5))

    assert result is None
    assert store["versions"].count_documents({}) == 1


def test_an_explicit_capture_records_a_state_the_ledger_lacks(store) -> None:
    did = _make_dashboard(store, components=[{"index": "a"}])
    _capture(did, kind="explicit", author=ALICE, now=BASE)
    _set_components(store, did, [{"index": "b"}])

    result = _capture(did, kind="explicit", author=ALICE, now=BASE + timedelta(hours=5))

    assert result is not None
    assert store["versions"].count_documents({}) == 2


def test_an_explicit_capture_records_the_first_state_of_a_family(store) -> None:
    """An empty ledger lacks every state, including the present one."""
    did = _make_dashboard(store, components=[{"index": "a"}])

    assert _capture(did, kind="explicit", author=ALICE, now=BASE)
    assert store["versions"].count_documents({}) == 1


def test_a_fold_upgrades_the_record_schema_version(store) -> None:
    """A version first written at schema 1 holds schema-2 tabs once folded into."""
    did = _make_dashboard(store, components=[{"index": "a"}])
    _capture(did, author=ALICE, now=BASE)
    store["versions"].update_one({}, {"$set": {"record_schema_version": 1}})

    _set_components(store, did, [{"index": "b"}])
    _capture(did, author=ALICE, now=BASE + timedelta(seconds=5))

    assert store["versions"].count_documents({}) == 1, "precondition: the saves coalesced"
    assert store["versions"].find_one({})["record_schema_version"] == 2


# ── Save click on an already-autosaved state ────────────────────────────────
#
# The editor autosaves 500 ms after each change, so by the time the user
# clicks Save the autosave has nearly always recorded that content. The click
# must still show: it seals that autosave rather than writing nothing.


def test_a_save_click_seals_the_autosave_that_holds_its_content(store) -> None:
    did = _make_dashboard(store, components=[{"index": "a"}])
    _capture(did, author=ALICE, now=BASE)

    result = _capture(
        did, kind="explicit", seal=True, author=ALICE, now=BASE + timedelta(seconds=30)
    )

    assert result is None, "no second copy of the same content"
    assert store["versions"].count_documents({}) == 1
    sealed = store["versions"].find_one({})
    assert sealed["kind"] == "explicit"
    assert sealed["coalesce_until"] == sealed["created_at"], "its window must be closed"


def test_an_edit_after_a_save_click_opens_a_new_version(store) -> None:
    did = _make_dashboard(store, components=[{"index": "a"}])
    _capture(did, author=ALICE, now=BASE)
    _capture(did, kind="explicit", seal=True, author=ALICE, now=BASE + timedelta(seconds=30))

    _set_components(store, did, [{"index": "b"}])
    _capture(did, author=ALICE, now=BASE + timedelta(seconds=60))

    assert store["versions"].count_documents({}) == 2, "the saved state must not be folded into"
    saved = store["versions"].find_one({"kind": "explicit"})
    assert saved["tabs"][0]["stored_metadata"] == [{"index": "a"}]


def test_a_state_before_capture_does_not_seal(store) -> None:
    """Only a Save click seals: the capture ahead of a restore is not one."""
    did = _make_dashboard(store, components=[{"index": "a"}])
    _capture(did, author=ALICE, now=BASE)

    _capture(did, kind="explicit", author=ALICE, now=BASE + timedelta(seconds=30))

    assert store["versions"].find_one({})["kind"] == "auto"


@pytest.fixture()
def far_from_utc(monkeypatch: pytest.MonkeyPatch):
    """Run with a local clock 5h30 away from UTC, as on a developer laptop."""
    import time

    monkeypatch.setenv("TZ", "Asia/Kolkata")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_versions_are_stamped_in_utc(store, far_from_utc) -> None:
    """Version times are naive UTC like every other API timestamp.

    Stamped with the server's local clock, a laptop running `depictio local
    up` showed every version hours away from when it was saved, since the
    viewer reads naive timestamps as UTC.
    """
    from datetime import timezone

    did = _make_dashboard(store, components=[{"index": "a"}])
    before = datetime.now(timezone.utc).replace(tzinfo=None)

    _capture(did, author=ALICE)

    created = store["versions"].find_one({})["created_at"]
    assert abs((created - before).total_seconds()) < 60


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


# ── Data-collection stamps ──────────────────────────────────────────────────
#
# The stamp is what makes a version reproducible: it records which Delta
# version each collection was at, so the dashboard can later be read against
# that data rather than whatever landed since. A stamp that degrades to
# ``version_kind="none"`` silently removes that ability, which is exactly what
# was happening — every stamp on a real imported dashboard said
# ``unknown_data_collection_type``.


def _dc_component(dc_id: PyObjectId, *, dc_type: str | None, index: str = "c1") -> dict:
    """A component as the editor stores it.

    Note ``dc_config.type`` is nullable: the stored config is a projection and
    real imported dashboards routinely carry ``None`` there.
    """
    return {
        "index": index,
        "component_type": "card",
        "dc_id": str(dc_id),
        "wf_id": str(PyObjectId()),
        "workflow_tag": "iris_versioned",
        "data_collection_tag": "iris_versioned_table",
        "dc_config": {"type": dc_type, "data_collection_tag": "iris_versioned_table"},
    }


def _seed_delta(store, dc_id: PyObjectId, *, versions: list[tuple[int, int, int]]) -> None:
    """versions: list of (aggregation_version, delta_version, rows_total)."""
    store["deltatables"].insert_one(
        {
            "_id": PyObjectId(),
            "data_collection_id": dc_id,
            "aggregation": [
                {
                    "aggregation_version": av,
                    "delta_version": dv,
                    "delta_commit_timestamp": BASE + timedelta(minutes=dv),
                    "rows_total": rows,
                    "aggregation_columns_specs": [
                        {"name": "sepal_length", "type": "float64"},
                        {"name": "species", "type": "object"},
                    ],
                }
                for av, dv, rows in versions
            ],
        }
    )


def _seed_project(store, dc_id: PyObjectId, *, dc_type: str = "table") -> None:
    store["projects"].insert_one(
        {
            "_id": PyObjectId(),
            "name": "Iris Versioned Demo",
            "workflows": [
                {
                    "_id": PyObjectId(),
                    "data_collections": [
                        {"_id": dc_id, "data_collection_tag": "t", "config": {"type": dc_type}}
                    ],
                }
            ],
        }
    )


def _stamps_for(store, components: list[dict]):
    from depictio.api.v1.endpoints.dashboards_endpoints.versioning import (
        build_dc_stamps,
        build_tab_snapshots,
        load_family_docs,
    )

    did = _make_dashboard(store, components=components)
    return build_dc_stamps(build_tab_snapshots(load_family_docs(did)))


def test_stamp_records_the_delta_version(store) -> None:
    """The whole point: a version knows which Delta commit it was authored on."""
    dc_id = PyObjectId()
    _seed_delta(store, dc_id, versions=[(1, 0, 100), (2, 1, 150), (3, 2, 150)])

    (stamp,) = _stamps_for(store, [_dc_component(dc_id, dc_type="table")])

    assert stamp.version_kind == "delta"
    assert stamp.delta_version == 2, "the latest commit, not the first"
    assert stamp.aggregation_version == 3
    assert stamp.row_count == 150
    assert stamp.schema_hash, "needed to detect schema drift on restore"


def test_stamp_falls_back_to_the_project_for_the_type(store) -> None:
    """Regression: `dc_config.type` is None on real dashboards.

    Components store a projected config whose ``type`` is frequently null. When
    that was the only source, every collection classified as unknown and the
    stamp carried no Delta version at all, so nothing was reproducible.
    """
    dc_id = PyObjectId()
    _seed_delta(store, dc_id, versions=[(1, 0, 100)])
    _seed_project(store, dc_id, dc_type="table")

    (stamp,) = _stamps_for(store, [_dc_component(dc_id, dc_type=None)])

    assert stamp.version_kind == "delta", "must not degrade to none"
    assert stamp.dc_type == "table"
    assert stamp.delta_version == 0
    assert stamp.reason is None


def test_stamp_without_type_anywhere_explains_itself(store) -> None:
    """No type in the component and no project row: say so, don't imply coverage."""
    dc_id = PyObjectId()
    _seed_delta(store, dc_id, versions=[(1, 0, 100)])

    (stamp,) = _stamps_for(store, [_dc_component(dc_id, dc_type=None)])

    assert stamp.version_kind == "none"
    assert stamp.reason == "unknown_data_collection_type"


def test_stamp_carries_human_readable_tags(store) -> None:
    """The picker labels collections by tag, so the stamp has to hold them."""
    dc_id = PyObjectId()
    _seed_delta(store, dc_id, versions=[(1, 0, 100)])

    (stamp,) = _stamps_for(store, [_dc_component(dc_id, dc_type="table")])

    assert stamp.workflow_tag == "iris_versioned"
    assert stamp.data_collection_tag == "iris_versioned_table"


def test_stamp_without_delta_version_is_honest(store) -> None:
    """Pre-provenance aggregations and UI uploads record no Delta version."""
    dc_id = PyObjectId()
    store["deltatables"].insert_one(
        {
            "_id": PyObjectId(),
            "data_collection_id": dc_id,
            "aggregation": [{"aggregation_version": 1, "rows_total": 10}],
        }
    )

    (stamp,) = _stamps_for(store, [_dc_component(dc_id, dc_type="table")])

    assert stamp.version_kind == "none"
    assert stamp.reason == "no_delta_version_recorded"
    assert stamp.aggregation_version == 1, "still worth recording what we do know"


def test_components_without_a_collection_are_skipped(store) -> None:
    """Text components carry no dc_id and must not produce an empty stamp."""
    dc_id = PyObjectId()
    _seed_delta(store, dc_id, versions=[(1, 0, 100)])

    stamps = _stamps_for(
        store,
        [
            {"index": "t1", "component_type": "text", "dc_id": None},
            _dc_component(dc_id, dc_type="table"),
        ],
    )

    assert [s.dc_id for s in stamps] == [str(dc_id)]
