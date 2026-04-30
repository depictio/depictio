"""Depictio shared React components — Python wrappers.

These classes are Dash `Component` subclasses that let the Dash editor place
the React components in a Dash layout tree. They register with Dash's
component-suite loader so the compiled JS bundle (`depictio_components.min.js`)
is served alongside the app.

The React implementations live in `../src/lib/components/` and are consumed by
BOTH the Dash editor (via these wrappers) and the React viewer (direct TS
import). One source of truth, two renderers.
"""

from __future__ import annotations

from .DepictioCard import DepictioCard
from .DepictioMultiSelect import DepictioMultiSelect

# Dash looks this up via register_library / component-suites. The path is the
# directory containing the built JS bundle.
__version__ = "0.1.0"

# File served by Dash's /_dash-component-suites/ endpoint. Must match
# webpack.config.js output.filename.
_js_dist = [
    {
        "relative_package_path": "depictio_components.min.js",
        "namespace": "depictio_components",
    },
]

_css_dist: list[dict] = []

# Expose for Dash component-suite discovery.
for _component in (DepictioCard, DepictioMultiSelect):
    _component._js_dist = _js_dist  # type: ignore[attr-defined]
    _component._css_dist = _css_dist  # type: ignore[attr-defined]

__all__ = ["DepictioCard", "DepictioMultiSelect"]
