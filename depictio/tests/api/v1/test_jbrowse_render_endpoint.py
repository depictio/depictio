"""``render_jbrowse`` under a pinned data version.

A version preview (or a dataset pin) sends ``as_of_version`` / ``data_versions``
with the render. The browser's manifest, the filter applied to it and the
``locus_from`` collection must all be read at their pinned commits, or a past
view shows today's tracks under a past label. Storage and Mongo are faked; this
pins which commit each read asks for.
"""

from __future__ import annotations

from types import SimpleNamespace

import polars as pl
import pytest

from depictio.api.v1 import deltatables_utils
from depictio.api.v1.endpoints.dashboards_endpoints import routes
from depictio.api.v1.endpoints.dashboards_endpoints.data_versions import DataVersionPins
from depictio.api.v1.services.jbrowse import render, tracks

DASHBOARD_ID = "646b0f3c1e4a2d7f8e5b8d01"
TRACKS_DC = "646b0f3c1e4a2d7f8e5b8d02"
PEAKS_DC = "646b0f3c1e4a2d7f8e5b8d03"

COMPONENT = {
    "index": "jb",
    "component_type": "jbrowse",
    "dc_id": TRACKS_DC,
    "locus_from": {
        "data_collection_tag": "peaks",
        "chrom_column": "chrom",
        "start_column": "start",
        "end_column": "end",
        "padding": 10,
    },
}
FILTERS = [{"index": "f1", "column_name": "sample", "value": ["S1"]}]


@pytest.fixture
def calls(monkeypatch):
    seen: dict[str, object] = {}

    dashboard = {
        "dashboard_id": DASHBOARD_ID,
        "project_id": "646b0f3c1e4a2d7f8e5b8d00",
        "stored_metadata": [COMPONENT],
    }
    monkeypatch.setattr(
        routes, "dashboards_collection", SimpleNamespace(find_one=lambda *a, **k: dashboard)
    )
    monkeypatch.setattr(routes, "check_project_permission", lambda *a, **k: True)
    monkeypatch.setattr(routes, "_resolve_link_filters_cached", lambda **kw: kw["filters"])
    monkeypatch.setattr(routes, "_find_project_dc", lambda pid, tag: ("646b0f3c1e4a2d7f8e5b8d04", PEAKS_DC))
    monkeypatch.setattr(
        routes,
        "_data_pins",
        lambda request, dash: DataVersionPins(
            pins={TRACKS_DC: 3, PEAKS_DC: 7} if request.get("as_of_version") else {}
        ),
    )
    monkeypatch.setattr(tracks, "find_tracks_dc", lambda dc_id: SimpleNamespace(dc_id=dc_id))

    def filtered(tdc, metadata, delta_version=None):
        seen["filtered"] = delta_version
        return []

    def payload(component, tdc, rows, uid, locus=None, delta_version=None):
        seen["payload"] = delta_version
        seen["locus"] = locus
        return {}

    def load(**kw):
        seen["locus_dc"] = kw.get("delta_version")
        return pl.DataFrame({"chrom": ["chr1"], "start": [100], "end": [200]})

    monkeypatch.setattr(render, "filtered_track_rows", filtered)
    monkeypatch.setattr(render, "build_jbrowse_payload", payload)
    monkeypatch.setattr(deltatables_utils, "load_deltatable_lite", load)
    return seen


def _render(body: dict) -> None:
    routes.render_jbrowse_endpoint(
        DASHBOARD_ID, "jb", body, current_user=SimpleNamespace(id="u1"), access_token=None
    )


def test_every_read_follows_the_pin(calls):
    _render({"filters": FILTERS, "as_of_version": "v1"})
    assert calls["filtered"] == 3
    assert calls["payload"] == 3
    assert calls["locus_dc"] == 7
    assert calls["locus"] == "chr1:90-210"


def test_a_live_render_reads_current_data(calls):
    _render({"filters": FILTERS})
    assert calls["filtered"] is None
    assert calls["payload"] is None
    assert calls["locus_dc"] is None
