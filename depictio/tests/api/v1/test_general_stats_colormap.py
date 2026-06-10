"""Regression tests for the MultiQC general-stats colormap helpers.

Guards against the matplotlib dependency regression: after the Dash → React
migration the module imported matplotlib, which is no longer a dependency, so
importing it raised ``No module named 'matplotlib'`` and the whole general-stats
table failed to render. These tests exercise the plotly-based replacement.
"""

from __future__ import annotations

import re

import pandas as pd
import pytest

from depictio.api.v1.services.multiqc.general_stats_payload import (
    _get_colormap,
    _multiqc_data_bars_colormap,
    _sample_colormap,
)

_HEX_RE = re.compile(r"^#[0-9a-f]{6}$")


class TestColormapHelpers:
    @pytest.mark.parametrize("name", ["RdYlGn", "RdYlBu", "Blues"])
    def test_known_colormaps_resolve(self, name):
        cmap = _get_colormap(name)
        assert isinstance(cmap, list) and cmap

    def test_unknown_colormap_falls_back(self):
        # Unknown names must not raise; they fall back to the default scale.
        assert _get_colormap("not-a-real-cmap") == _get_colormap("RdYlGn")

    @pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
    def test_sample_returns_unit_rgb(self, value):
        r, g, b = _sample_colormap(_get_colormap("RdYlGn"), value)
        assert all(0.0 <= c <= 1.0 for c in (r, g, b))

    @pytest.mark.parametrize("value", [-0.5, 1.5])
    def test_sample_clamps_out_of_range(self, value):
        # Matplotlib clamped out-of-range values; the replacement must too.
        r, g, b = _sample_colormap(_get_colormap("RdYlGn"), value)
        assert all(0.0 <= c <= 1.0 for c in (r, g, b))


class TestDataBarsColormap:
    def test_produces_valid_hex_styles(self):
        df = pd.DataFrame({"metric": [0, 25, 50, 75, 100]})
        styles = _multiqc_data_bars_colormap(df, "metric", cmap_name="RdYlGn")

        assert styles, "expected per-bin styles for a non-empty numeric column"
        for style in styles:
            bg = style["backgroundImage"]
            hexes = re.findall(r"#[0-9a-fA-F]{6}", bg)
            assert hexes, f"expected hex colour in {bg!r}"
            for hex_color in hexes:
                assert _HEX_RE.match(hex_color.lower())

    def test_all_nan_column_returns_empty(self):
        df = pd.DataFrame({"metric": [None, None, None]})
        assert _multiqc_data_bars_colormap(df, "metric") == []
