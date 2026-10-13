"""``render_map`` styles its figure with the theme's template.

Only the "no data" and error figures used to get one, so a rendered map kept
Plotly's default template, whose dark-navy text (legend, hover) disappeared on
a dark page.
"""

from __future__ import annotations

import pandas as pd
import plotly.io as pio
import pytest

from depictio.api.v1.services.map.render import render_map


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_map_uses_the_theme_template(theme: str) -> None:
    df = pd.DataFrame({"lat": [41.4, 40.8], "lon": [2.2, 14.3], "city": ["B", "N"]})
    trigger = {
        "map_type": "scatter_map",
        "lat_column": "lat",
        "lon_column": "lon",
        "color_column": "city",
    }
    fig, _info = render_map(df, trigger, theme=theme)
    expected = pio.templates[f"mantine_{theme}"].layout.font.color
    assert fig.layout.template.layout.font.color == expected
    # Still transparent: the tile, not the template, owns the background.
    assert fig.layout.paper_bgcolor == "rgba(0,0,0,0)"
