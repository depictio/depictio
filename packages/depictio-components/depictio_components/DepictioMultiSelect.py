"""Python wrapper for the DepictioMultiSelect React component.

Mirrors the DMC MultiSelect prop surface used in
`depictio/dash/modules/interactive_component/utils.py:_build_select_component`.
"""

from __future__ import annotations

from typing import Any

from dash.development.base_component import Component

_PROP_NAMES = [
    "id",
    "title",
    "column_name",
    "options",
    "value",
    "placeholder",
    "color",
    "icon_name",
    "clearable",
    "searchable",
    "limit",
]


class DepictioMultiSelect(Component):
    """Depictio MultiSelect — filter input for categorical columns.

    Emits the selected values list via Dash's ``setProps({value: [...]})``.
    Pattern-matched IDs like ``{"type": "interactive-component-value",
    "index": <uuid>}`` continue to work — the existing
    ``interactive-values-store`` aggregation callback picks up changes
    unchanged.

    Keyword arguments:
    - id (string or dict; optional): Dash component ID.
    - title (string; optional): Heading shown above the select.
    - column_name (string; optional): Dataframe column this filters.
    - options (list; optional): Either list of strings or list of
      ``{"value": str, "label": str}`` dicts.
    - value (list; optional): Currently selected values.
    - placeholder (string; optional): Placeholder when empty.
    - color (string; optional): Mantine color or CSS color for accent.
    - icon_name (string; optional): Iconify ID for leading icon.
    - clearable (bool; default True): Show clear-all control.
    - searchable (bool; default True): Enable free-text option search.
    - limit (number; default 100): Max options rendered in dropdown.
    """

    _children_props: list[str] = []
    _base_nodes: list[str] = ["children"]
    _namespace = "depictio_components"
    _type = "DepictioMultiSelect"

    def __init__(
        self,
        id: Any = None,
        title: str | None = None,
        column_name: str | None = None,
        options: list | None = None,
        value: list | None = None,
        placeholder: str | None = None,
        color: str | None = None,
        icon_name: str | None = None,
        clearable: bool | None = None,
        searchable: bool | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> None:
        self._prop_names = _PROP_NAMES
        self._valid_wildcard_attributes: list[str] = []
        self.available_properties = _PROP_NAMES
        self.available_wildcard_properties: list[str] = []

        _locals = locals()
        args = {k: _locals[k] for k in _PROP_NAMES if k in _locals and _locals[k] is not None}
        super().__init__(**args)
