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
    assert _capture(did, author=ALICE, now=BASE + timedelta(hours=5)) is None

    _capture(did, kind="explicit", author=ALICE, now=BASE + timedelta(hours=6))
    latest = store["versions"].find_one({}, sort=[("seq", -1)])
    assert latest["tabs"][0]["source_key"] == "nf-core/x:base.yaml"


# ── only_if_changed ─────────────────────────────────────────────────────────


def test_only_if_changed_writes_nothing_for_an_unchanged_family(store) -> None:
    """Even an explicit capture: a copy of the newest version is noise."""
    did = _make_dashboard(store, components=[{"index": "a"}])
    _capture(did, kind="explicit", author=ALICE, now=BASE)

    result = _capture(
        did, kind="explicit", author=ALICE, now=BASE + timedelta(hours=5), only_if_changed=True
    )

    assert result is None
    doc = store["versions"].find_one({})
    assert store["versions"].count_documents({}) == 1
    assert doc["save_count"] == 1, "not even a touch: nothing was saved"


def test_only_if_changed_records_a_state_the_ledger_lacks(store) -> None:
    did = _make_dashboard(store, components=[{"index": "a"}])
    _capture(did, kind="explicit", author=ALICE, now=BASE)
    _set_components(store, did, [{"index": "b"}])

    result = _capture(
        did, kind="explicit", author=ALICE, now=BASE + timedelta(hours=5), only_if_changed=True
    )

    assert result is not None
    assert store["versions"].count_documents({}) == 2


def test_only_if_changed_records_the_first_state_of_a_family(store) -> None:
    """An empty ledger lacks every state, including the present one."""
    did = _make_dashboard(store, components=[{"index": "a"}])

    assert _capture(did, kind="explicit", author=ALICE, now=BASE, only_if_changed=True)
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

