"""Resolving a render request's "as of" intent into per-collection read pins.

The failure this guards against is not an exception, it is a *plausible wrong
answer*: a request pinned to an old dashboard version quietly served current
data, looking entirely normal while every number is from the wrong day. So the
tests below care as much about what is reported as unresolved as about what
resolves.
"""

from __future__ import annotations

import pytest

from depictio.api.v1.endpoints.dashboards_endpoints.data_versions import (
    NOT_IN_VERSION,
    DataVersionPins,
    collection_statuses,
    pins_from_stamps,
    resolve_data_versions,
    stale_version_detail,
)

DC_A = "646b0f3c1e4a2d7f8e5b9003"
DC_B = "646b0f3c1e4a2d7f8e5b9004"


def _delta_stamp(dc_id: str, delta_version: int) -> dict:
    return {"dc_id": dc_id, "version_kind": "delta", "delta_version": delta_version}


def _none_stamp(dc_id: str, reason: str) -> dict:
    return {"dc_id": dc_id, "version_kind": "none", "reason": reason}


# ── Stamps to pins ──────────────────────────────────────────────────────────


def test_delta_stamps_become_pins():
    pins = pins_from_stamps([_delta_stamp(DC_A, 0), _delta_stamp(DC_B, 5)])

    assert pins.for_dc(DC_A) == 0
    assert pins.for_dc(DC_B) == 5
    assert pins.unresolved == {}


def test_version_zero_is_a_real_pin():
    """v0 is falsy. Treating it as "no pin" would serve current data for the
    very first commit — the one a user is most likely to travel back to."""
    pins = pins_from_stamps([_delta_stamp(DC_A, 0)])

    assert pins.for_dc(DC_A) == 0
    assert pins.active


def test_unversioned_collections_are_reported_not_hidden():
    """The core honesty requirement: an unpinnable collection is named."""
    pins = pins_from_stamps([_delta_stamp(DC_A, 1), _none_stamp(DC_B, "no_delta_version_recorded")])

    assert pins.for_dc(DC_A) == 1
    assert pins.for_dc(DC_B) is None, "reads current data"
    assert pins.unresolved == {DC_B: "no_delta_version_recorded"}


def test_mixed_dashboards_pin_what_they_can():
    """A Delta table beside a MultiQC parquet: pin one, report the other."""
    pins = pins_from_stamps(
        [_delta_stamp(DC_A, 2), _none_stamp(DC_B, "asset_versioning_not_enabled")]
    )

    assert pins.pins == {DC_A: 2}
    assert list(pins.unresolved) == [DC_B]


def test_no_stamps_is_inert():
    pins = pins_from_stamps([])

    assert not pins.active


# ── Request resolution ──────────────────────────────────────────────────────


def test_empty_request_reads_current_data():
    """Every existing caller sends no time-travel keys and must be unaffected."""
    assert not resolve_data_versions({}).active
    assert not resolve_data_versions(None).active


def test_per_component_override(monkeypatch):
    """The component-level grain: pin one collection, leave the rest live."""
    pins = resolve_data_versions({"data_versions": {DC_A: 1}})

    assert pins.for_dc(DC_A) == 1
    assert pins.for_dc(DC_B) is None


def test_override_beats_the_dashboard_pin(monkeypatch):
    """Both grains at once: 'as of v3, except this component at v1'."""
    _stub_version(monkeypatch, [_delta_stamp(DC_A, 3), _delta_stamp(DC_B, 3)])

    pins = resolve_data_versions({"as_of_version": "abc", "data_versions": {DC_A: 1}})

    assert pins.for_dc(DC_A) == 1, "override wins"
    assert pins.for_dc(DC_B) == 3, "dashboard pin still applies"


def test_null_override_opts_a_collection_back_into_live_data(monkeypatch):
    """Explicit null means 'this one stays current', which is how a component
    escapes a dashboard-level pin — the inverse of the override above."""
    _stub_version(monkeypatch, [_delta_stamp(DC_A, 3), _delta_stamp(DC_B, 3)])

    pins = resolve_data_versions({"as_of_version": "abc", "data_versions": {DC_A: None}})

    assert pins.for_dc(DC_A) is None
    assert pins.for_dc(DC_B) == 3


def test_as_of_version_pins_every_stamped_collection(monkeypatch):
    _stub_version(monkeypatch, [_delta_stamp(DC_A, 0), _delta_stamp(DC_B, 4)])

    pins = resolve_data_versions({"as_of_version": "abc"})

    assert pins.pins == {DC_A: 0, DC_B: 4}
    assert pins.as_of_version_id == "abc"


def test_missing_version_is_an_error_not_a_fallback(monkeypatch):
    """A deleted version must not silently degrade to current data."""
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    monkeypatch.setattr(version_store, "get_version", lambda vid: None)

    with pytest.raises(ValueError, match="no longer exists"):
        resolve_data_versions({"as_of_version": "gone"})


FAMILY = "507f1f77bcf86cd799439011"
OTHER_FAMILY = "507f1f77bcf86cd799439099"


def test_a_version_from_another_dashboard_is_an_error(monkeypatch):
    """A real version id, paired with a dashboard it was never taken of.

    Accepted, it pins this dashboard's collections to commits stamped for a
    different one, and labels the render "as of" a version of nothing on screen.
    Refused the same way a deleted version is, so the endpoint answers 400.
    """
    _stub_version(monkeypatch, [_delta_stamp(DC_A, 0)], family_id=OTHER_FAMILY)

    with pytest.raises(ValueError, match="does not belong to this dashboard"):
        resolve_data_versions(
            {"as_of_version": "abc"}, dashboard={"dashboard_id": FAMILY, "is_main_tab": True}
        )


def test_the_main_tab_reads_its_own_versions(monkeypatch):
    _stub_version(monkeypatch, [_delta_stamp(DC_A, 0)], family_id=FAMILY)

    pins = resolve_data_versions(
        {"as_of_version": "abc"}, dashboard={"dashboard_id": FAMILY, "is_main_tab": True}
    )

    assert pins.for_dc(DC_A) == 0


def test_a_child_tab_reads_its_familys_versions(monkeypatch):
    """A version covers the whole family, and is filed under the main tab's id.

    A child tab rendering "as of" its family's version is the ordinary case, so
    the check has to resolve the child to its parent rather than compare ids.
    """
    _stub_version(monkeypatch, [_delta_stamp(DC_A, 2)], family_id=FAMILY)

    pins = resolve_data_versions(
        {"as_of_version": "abc"},
        dashboard={
            "dashboard_id": "507f1f77bcf86cd799439012",
            "is_main_tab": False,
            "parent_dashboard_id": FAMILY,
        },
    )

    assert pins.for_dc(DC_A) == 2


@pytest.mark.parametrize("value", [True, False, 3.7, "3", -1, "not-a-number", [1], {"v": 1}])
def test_a_data_version_that_is_not_a_commit_number_is_an_error(value):
    """A commit is an int of 0 or more. ``int()`` took ``True`` as commit 1,
    ``3.7`` and ``"3"`` as commit 3, and a negative one failed later, inside
    deltalake, as a 500 for a table and a silent null for a card."""
    with pytest.raises(ValueError, match="must be a Delta commit number"):
        resolve_data_versions({"data_versions": {DC_A: value}})


def test_data_versions_must_be_a_mapping():
    with pytest.raises(ValueError, match="data_versions must map"):
        resolve_data_versions({"data_versions": [DC_A, 1]})


def test_a_stale_version_has_the_detail_the_editor_matches(monkeypatch):
    """The editor drops a selection whose version is gone by this sentence."""
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    monkeypatch.setattr(version_store, "get_version", lambda vid: None)

    with pytest.raises(ValueError) as exc:
        resolve_data_versions({"as_of_version": "v-gone"})

    assert str(exc.value) == stale_version_detail("v-gone") == "Version v-gone no longer exists."


# ── A collection the version never stamped ─────────────────────────────────


def test_a_collection_added_since_is_reported_not_dropped():
    """It reads current data, and says so, instead of vanishing from the list."""
    pins = pins_from_stamps([_delta_stamp(DC_A, 1)], referenced=[DC_A, DC_B])

    assert pins.pins == {DC_A: 1}
    assert pins.unresolved == {DC_B: NOT_IN_VERSION}


def test_the_dashboards_collections_are_checked_against_the_stamps(monkeypatch):
    _stub_version(monkeypatch, [_delta_stamp(DC_A, 0)], family_id=FAMILY)
    dashboard = {
        "dashboard_id": FAMILY,
        "is_main_tab": True,
        "stored_metadata": [{"index": "a", "dc_id": DC_A}, {"index": "b", "dc_id": DC_B}],
    }

    pins = resolve_data_versions({"as_of_version": "abc"}, dashboard=dashboard)

    assert pins.unresolved == {DC_B: NOT_IN_VERSION}


# ── What each collection shows ─────────────────────────────────────────────


DC_C = "646b0f3c1e4a2d7f8e5b9005"
DC_D = "646b0f3c1e4a2d7f8e5b9006"

IDENTITIES = {
    DC_A: {"workflow_tag": "wf", "data_collection_tag": "a", "dc_type": "table"},
    DC_B: {"workflow_tag": "wf", "data_collection_tag": "b", "dc_type": "table"},
    DC_C: {"workflow_tag": "wf", "data_collection_tag": "c", "dc_type": "multiqc"},
}


def _by_dc(entries):
    return {entry["dc_id"]: entry for entry in entries}


def test_statuses_name_every_collection_and_why(monkeypatch):
    _stub_version(
        monkeypatch,
        [
            _delta_stamp(DC_A, 2),
            {**_none_stamp(DC_C, "manifest_versioning_not_enabled"), "dc_type": "multiqc"},
            # Read by the version, by no component now, and gone from the project.
            {
                **_delta_stamp(DC_D, 7),
                "workflow_tag": "old",
                "data_collection_tag": "d",
                "dc_type": "table",
            },
        ],
        family_id=FAMILY,
    )
    pins = resolve_data_versions(
        {"as_of_version": "abc"},
        dashboard={"dashboard_id": FAMILY, "is_main_tab": True},
        referenced=[DC_A, DC_B, DC_C],
    )

    entries = collection_statuses(pins, [DC_A, DC_B, DC_C], IDENTITIES)

    assert [e["dc_id"] for e in entries] == [DC_A, DC_B, DC_C, DC_D]
    got = _by_dc(entries)
    assert got[DC_A] == {
        "dc_id": DC_A,
        "workflow_tag": "wf",
        "data_collection_tag": "a",
        "dc_type": "table",
        "status": "pinned",
        "delta_version": 2,
        "reason": None,
    }
    assert (got[DC_B]["status"], got[DC_B]["reason"]) == ("live", NOT_IN_VERSION)
    assert (got[DC_C]["status"], got[DC_C]["reason"]) == (
        "not_versioned",
        "manifest_versioning_not_enabled",
    )
    assert (got[DC_D]["status"], got[DC_D]["delta_version"]) == ("pinned", 7)
    assert got[DC_D]["data_collection_tag"] == "d", "falls back to the stamp's identity"


def test_a_collection_kept_live_says_so(monkeypatch):
    _stub_version(monkeypatch, [_delta_stamp(DC_A, 2)], family_id=FAMILY)
    pins = resolve_data_versions(
        {"as_of_version": "abc", "data_versions": {DC_A: None}},
        dashboard={"dashboard_id": FAMILY, "is_main_tab": True},
        referenced=[DC_A],
    )

    (entry,) = collection_statuses(pins, [DC_A], IDENTITIES)

    assert (entry["status"], entry["delta_version"], entry["reason"]) == (
        "live",
        None,
        "kept_live",
    )


def test_without_time_travel_everything_is_live_without_a_reason():
    entries = collection_statuses(DataVersionPins(), [DC_A, DC_C], IDENTITIES)

    assert [(e["status"], e["reason"]) for e in entries] == [
        ("live", None),
        ("not_versioned", "manifest_versioning_not_enabled"),
    ]


def test_an_image_collection_pins_its_manifest_not_its_pixels():
    entries = collection_statuses(
        DataVersionPins(pins={DC_A: 1}), [DC_A], {DC_A: {"dc_type": "image"}}
    )

    assert (entries[0]["status"], entries[0]["reason"]) == (
        "pinned",
        "image_pixels_not_versioned",
    )


def test_pins_are_inert_by_default():
    assert not DataVersionPins().active


def _stub_version(monkeypatch, stamps, family_id=None):
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    monkeypatch.setattr(
        version_store,
        "get_version",
        lambda vid: {"version_id": vid, "family_id": family_id, "data_collections": stamps},
    )
