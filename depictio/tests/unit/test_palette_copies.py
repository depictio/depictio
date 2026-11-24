"""The standalone plot packages carry copies of the shared palette; keep them equal.

``plotly-complexheatmap`` and ``plotly-upset`` install without depictio, so they
cannot import ``depictio.models.palettes``. Their defaults are copies of the
marque values; this test fails CI when either copy drifts from the source.
"""

from __future__ import annotations

import pytest

from depictio.models import palettes
from depictio.models.palette_tracks import track_palette


def test_complexheatmap_defaults_follow_the_shared_palette() -> None:
    utils = pytest.importorskip("plotly_complexheatmap.utils")
    assert [list(s) for s in utils.COMPLEXHEATMAP_COLORSCALE] == palettes.colorscale(
        palettes.diverging("marque", "light")
    )
    assert utils.COLUMN_PALETTE == track_palette("diverging", "light")
    assert utils.ROW_PALETTE == track_palette("diverging", "light")
    assert utils.DEFAULT_PALETTE == track_palette("diverging", "light")


def test_upset_default_palette_is_the_shared_categorical() -> None:
    utils = pytest.importorskip("plotly_upset.utils")
    assert utils.UPSET_PALETTE == palettes.categorical("marque", "light")
