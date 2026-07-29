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
    DataVersionPins,
    pins_from_stamps,
    resolve_data_versions,
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
    assert pins.warning() is None


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
    assert DC_B in pins.unresolved
    warning = pins.warning()
    assert warning and DC_B in warning and "no_delta_version_recorded" in warning


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
    assert pins.warning() is None


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


def test_garbage_override_is_ignored_not_crashed():
    """A malformed client value must not 500 the render."""
    pins = resolve_data_versions({"data_versions": {DC_A: "not-a-number"}})

    assert pins.for_dc(DC_A) is None


def test_response_meta_carries_the_warning():
    """The viewer renders this in the banner, so it has to survive the trip."""
    pins = pins_from_stamps([_none_stamp(DC_A, "no_delta_version_recorded")])
    pins.as_of_version_id = "v-abc"

    meta = pins.as_response_meta()

    assert meta["as_of_version_id"] == "v-abc"
    assert meta["pinned"] == {}
    assert meta["unresolved"] == {DC_A: "no_delta_version_recorded"}
    assert meta["warning"]


def test_pins_are_inert_by_default():
    assert not DataVersionPins().active


def _stub_version(monkeypatch, stamps):
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    monkeypatch.setattr(
        version_store,
        "get_version",
        lambda vid: {"version_id": vid, "data_collections": stamps},
    )
