"""The auto-fit ``render_map`` computes, and the bounding box it forwards.

Two things are pinned here. First, the centre is the middle of the *projected*
latitude span: Mercator stretches towards the poles, so the arithmetic mean of
two latitudes is not the latitude that lands halfway down the viewport, and a
map framed on it sits visibly low. Second, the fit is only as good as the
viewport it was computed against — the server has to guess one — so the box it
fitted travels to the client in ``data_info["fit"]`` for a host that knows its
real size to redo the fit.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from depictio.api.v1.services.map import render as map_render
from depictio.api.v1.services.map.render import (
    _FIT_SINGLE_POINT_ZOOM,
    _FIT_VIEWPORT_PX,
    _compute_auto_zoom,
    render_map,
)


def _trigger(**overrides) -> dict:
    trigger = {"map_type": "scatter_map", "lat_column": "lat", "lon_column": "lon"}
    trigger.update(overrides)
    return trigger


def _frame(lats: list[float], lons: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"lat": lats, "lon": lons})


# ---------------------------------------------------------------------------
# Centre
# ---------------------------------------------------------------------------


def test_center_is_the_projected_midpoint_not_the_degree_mean() -> None:
    """0..60N: the pixel halfway down the viewport is 35.26N, not 30N."""
    center, _zoom, _bounds = _compute_auto_zoom([0.0, 60.0], [-5.0, 5.0])
    assert center["lat"] == pytest.approx(35.2644, abs=1e-3)
    assert center["lon"] == pytest.approx(0.0)


def test_center_is_symmetric_about_the_equator() -> None:
    """The projection is odd around 0, so a symmetric span keeps its mean."""
    center, _zoom, _bounds = _compute_auto_zoom([-40.0, 40.0], [10.0, 20.0])
    assert center["lat"] == pytest.approx(0.0, abs=1e-9)
    assert center["lon"] == pytest.approx(15.0)


def test_center_mirrors_in_the_southern_hemisphere() -> None:
    center, _zoom, _bounds = _compute_auto_zoom([-60.0, 0.0], [0.0, 0.0])
    assert center["lat"] == pytest.approx(-35.2644, abs=1e-3)


def test_center_of_a_narrow_span_is_still_the_degree_mean() -> None:
    """Over a degree or two the projection is linear enough to notice nothing.

    A couple of thousandths of a degree here, against ten degrees over a
    continent-wide span, is why the defect only ever showed on wide data.
    """
    center, _zoom, _bounds = _compute_auto_zoom([48.0, 49.0], [2.0, 3.0])
    assert center["lat"] == pytest.approx(48.5, abs=5e-3)


# ---------------------------------------------------------------------------
# Zoom
# ---------------------------------------------------------------------------


def _pixel_span(bounds: dict[str, float], zoom: float) -> tuple[float, float]:
    """Width and height in pixels the bounding box occupies at ``zoom``."""
    world = 512.0
    lat_fraction = (
        map_render._lat_rad(bounds["max_lat"]) - map_render._lat_rad(bounds["min_lat"])
    ) / math.pi
    lon_fraction = (bounds["max_lon"] - bounds["min_lon"]) / 360.0
    scale = world * 2.0**zoom
    return lon_fraction * scale, lat_fraction * scale


@pytest.mark.parametrize(
    ("lats", "lons"),
    [
        ([35.0, 60.0], [-10.0, 30.0]),  # Europe, wide
        ([-34.0, 37.0], [-18.0, 51.0]),  # Africa, tall
        ([47.0, 48.0], [7.0, 9.0]),  # a single region
    ],
    ids=["europe", "africa", "region"],
)
def test_every_point_fits_the_reference_viewport(lats, lons) -> None:
    _center, zoom, bounds = _compute_auto_zoom(lats, lons)
    assert bounds is not None
    width_px, height_px = _pixel_span(bounds, zoom)
    assert width_px <= _FIT_VIEWPORT_PX[0]
    assert height_px <= _FIT_VIEWPORT_PX[1]


def test_a_shorter_narrower_viewport_needs_a_lower_zoom(monkeypatch) -> None:
    """The docked panel in one assertion.

    The side panel's plot box is roughly 378x190 against the 600x400 the server
    has to assume, and the same points need a whole level less zoom to fit it.
    The server cannot know which it is drawing for, which is what the forwarded
    bounding box is for.
    """
    lats, lons = [35.0, 60.0], [-10.0, 30.0]
    _center, wide_zoom, _bounds = _compute_auto_zoom(lats, lons)
    monkeypatch.setattr(map_render, "_FIT_VIEWPORT_PX", (378, 190))
    _center, docked_zoom, _bounds = _compute_auto_zoom(lats, lons)
    assert docked_zoom < wide_zoom


# ---------------------------------------------------------------------------
# Bounds and the degenerate cases
# ---------------------------------------------------------------------------


def test_bounds_are_the_data_extent() -> None:
    _center, _zoom, bounds = _compute_auto_zoom([12.0, 3.0, 9.0], [-4.0, 8.0, 1.0])
    assert bounds == {"min_lat": 3.0, "max_lat": 12.0, "min_lon": -4.0, "max_lon": 8.0}


def test_a_single_point_keeps_its_position_and_a_readable_zoom() -> None:
    center, zoom, bounds = _compute_auto_zoom([48.85, 48.85], [2.35, 2.35])
    assert center["lat"] == pytest.approx(48.85)
    assert center["lon"] == pytest.approx(2.35)
    assert zoom == _FIT_SINGLE_POINT_ZOOM
    assert bounds == {"min_lat": 48.85, "max_lat": 48.85, "min_lon": 2.35, "max_lon": 2.35}


def test_no_points_falls_back_to_a_world_view_with_nothing_to_fit() -> None:
    center, zoom, bounds = _compute_auto_zoom([], [])
    assert center == {"lat": 0.0, "lon": 0.0}
    assert zoom == 2
    assert bounds is None


# ---------------------------------------------------------------------------
# What reaches the client
# ---------------------------------------------------------------------------


def test_data_info_carries_the_box_and_the_constants_it_was_fitted_with() -> None:
    _fig, data_info = render_map(
        df=_frame([48.85, 52.52, 41.9], [2.35, 13.4, 12.5]),
        trigger_data=_trigger(),
    )
    fit = data_info["fit"]
    assert fit["min_lat"] == pytest.approx(41.9)
    assert fit["max_lat"] == pytest.approx(52.52)
    assert fit["min_lon"] == pytest.approx(2.35)
    assert fit["max_lon"] == pytest.approx(13.4)
    # Without these the client would have to hardcode them and could drift.
    assert fit["padding"] == pytest.approx(map_render._FIT_ZOOM_PADDING)
    assert fit["max_zoom"] == pytest.approx(map_render._FIT_MAX_ZOOM)
    assert fit["single_point_zoom"] == pytest.approx(_FIT_SINGLE_POINT_ZOOM)


def test_an_authored_viewport_is_never_re_fitted() -> None:
    """A component that pins its own centre and zoom means it, so no box goes
    out: a client that re-fitted one would undo the author's choice."""
    _fig, data_info = render_map(
        df=_frame([48.85, 52.52], [2.35, 13.4]),
        trigger_data=_trigger(default_center={"lat": 0.0, "lon": 0.0}, default_zoom=4),
    )
    assert data_info["fit"] is None
    assert data_info["zoom"] == 4


@pytest.mark.parametrize("authored", ["center", "zoom"], ids=["center-only", "zoom-only"])
def test_a_half_authored_viewport_is_not_re_fitted_either(authored) -> None:
    """One authored half is still an authored viewport: re-fitting would move
    the other half out from under it."""
    overrides = (
        {"default_center": {"lat": 10.0, "lon": 10.0}}
        if authored == "center"
        else {"default_zoom": 6}
    )
    _fig, data_info = render_map(
        df=_frame([48.85, 52.52], [2.35, 13.4]),
        trigger_data=_trigger(**overrides),
    )
    assert data_info["fit"] is None


def test_no_usable_rows_reports_no_fit() -> None:
    _fig, data_info = render_map(df=_frame([], []), trigger_data=_trigger())
    assert data_info["displayed_count"] == 0
    assert data_info.get("fit") is None
