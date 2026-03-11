"""Dash component package wrapping react-phylogeny-tree (Phylocanvas 3)."""

import os

from ._imports_ import *  # noqa: F401, F403
from ._imports_ import __all__

_this_module = __name__

_current_path = os.path.dirname(os.path.abspath(__file__))

_js_dist = [
    {
        "relative_package_path": "dash_phylotree.min.js",
        "namespace": "dash_phylotree",
    }
]

_css_dist = []

for _component in __all__:
    setattr(locals()[_component], "_js_dist", _js_dist)
    setattr(locals()[_component], "_css_dist", _css_dist)
