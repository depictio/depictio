"""Server-rendered figures fall back to the shared depictio palette.

Precedence is component > dashboard pins > brand colorway > default palette; the
brand cases are in ``test_brand_theme.py`` and ``test_category_colors.py``. These
tests cover the last step: with no brand, the mantine templates (read by plotly
express for the trace colours) carry the default palette, per mode.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.io as pio
import pytest

from depictio.api.v1.services.figure.mantine_templates import ensure_mantine_templates
from depictio.models import palettes


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_mantine_template_carries_the_default_palette(mode: str) -> None:
    ensure_mantine_templates()
    template = pio.templates[f"mantine_{mode}"]
    chrome = palettes.chrome(mode)
    assert list(template.layout.colorway) == palettes.categorical(None, mode)
    assert template.layout.font.color == chrome["text"]
    assert template.layout.xaxis.gridcolor == chrome["grid"]
    assert [stop[1] for stop in template.layout.colorscale.sequential] == palettes.sequential(
        None, mode
    )


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_px_traces_take_the_default_palette_in_each_mode(mode: str) -> None:
    ensure_mantine_templates()
    frame = pd.DataFrame({"x": [1, 2, 3], "y": [1, 2, 3], "g": ["a", "b", "c"]})
    fig = px.scatter(frame, x="x", y="y", color="g", template=f"mantine_{mode}")
    assert [t.marker.color for t in fig.data] == palettes.categorical(None, mode)[:3]
