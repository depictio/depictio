"""Auto-generated shape — mirrors what dash-generate-components produces.

Follows Dash's component protocol:
  - `_type` = React component name (matches window.depictio_components.<name>)
  - `_namespace` = npm package name (matches window object key)
  - `_prop_names` = list of valid prop names (all TypeScript props from the TSX)
  - `__init__` accepts each prop as a kwarg and stores in self._props
  - `_valid_wildcard_attributes` empty (no 'data-*' passthrough for now)

When updating DepictioCard.tsx props, update `_PROP_NAMES` here to match.
Long-term replacement: `dash-generate-components` run against the TSX.
"""

from __future__ import annotations

from typing import Any

from dash.development.base_component import Component

_PROP_NAMES = [
    "id",
    "title",
    "value",
    "icon_name",
    "icon_color",
    "title_color",
    "background_color",
    "title_font_size",
    "value_font_size",
    "aggregation_description",
    "secondary_metrics",
    "comparison",
    "filter_applied",
]


class DepictioCard(Component):
    """Depictio Card component — hero metric + optional secondary rows.

    Keyword arguments:
    - id (string or dict; optional): Dash component ID. Pattern-matched dicts
      like ``{"type": "card-component", "index": <uuid>}`` work as usual.
    - title (string; optional): Card heading.
    - value (string or number; optional): Primary hero metric (already formatted).
    - icon_name (string; optional): Iconify ID, e.g. ``"mdi:flower-outline"``.
    - icon_color (string; optional): CSS color string for the icon.
    - title_color (string; optional): CSS color string for the title text.
    - background_color (string; optional): CSS color for the card background.
    - title_font_size (string; optional): Mantine size (xs/sm/md/lg/xl).
    - value_font_size (string; optional): Mantine size for the hero value.
    - aggregation_description (string; optional): Short label under the value.
    - secondary_metrics (list; optional): List of {label, value, aggregation?}.
    - comparison (dict; optional): Unfiltered baseline metadata.
    - filter_applied (bool; optional): True if interactive filter is applied.
    """

    _children_props: list[str] = []
    _base_nodes: list[str] = ["children"]
    _namespace = "depictio_components"
    _type = "DepictioCard"

    def __init__(
        self,
        id: Any = None,
        title: str | None = None,
        value: Any = None,
        icon_name: str | None = None,
        icon_color: str | None = None,
        title_color: str | None = None,
        background_color: str | None = None,
        title_font_size: str | None = None,
        value_font_size: str | None = None,
        aggregation_description: str | None = None,
        secondary_metrics: list | None = None,
        comparison: dict | None = None,
        filter_applied: bool | None = None,
        **kwargs: Any,
    ) -> None:
        self._prop_names = _PROP_NAMES
        self._valid_wildcard_attributes: list[str] = []
        self.available_properties = _PROP_NAMES
        self.available_wildcard_properties: list[str] = []

        _explicit_args = kwargs.pop("_explicit_args", None)
        _locals = locals()
        args = {k: _locals[k] for k in _PROP_NAMES if k in _locals and _locals[k] is not None}
        super().__init__(**args)
