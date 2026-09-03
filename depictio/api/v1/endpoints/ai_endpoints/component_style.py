"""The icons and colours a generated card or filter may wear.

A tile without an icon reads as a placeholder, so the prompts ask for one on
every card and every filter. They cannot ask for *any* icon: the viewer ships a
scanned subset of Iconify and its CSP blocks the network fallback, so an id
nobody wrote down renders as a blank box. The lists below are therefore the
builders' own pickers, mirrored from
``depictio/viewer/src/builder/card/CardBuilder.tsx`` and
``builder/interactive/InteractiveBuilder.tsx``: what the model may choose is
exactly what a person could have chosen by hand, which also keeps the tile
editable afterwards (a value outside the picker blanks the field on the first
save).

Colours are hex because that is what the builders' swatches write. The model
often answers with a Mantine palette name instead, so a name is translated
rather than dropped.
"""

from typing import Any

# Card icons: `ICON_OPTIONS` in CardBuilder.tsx.
CARD_ICONS: tuple[str, ...] = (
    "mdi:chart-line",
    "mdi:chart-bar",
    "mdi:chart-pie",
    "mdi:counter",
    "mdi:sigma",
    "mdi:calculator",
    "mdi:database",
    "mdi:table",
    "mdi:account-multiple",
    "mdi:dna",
    "mdi:flask",
    "mdi:microscope",
    "mdi:test-tube",
    "mdi:percent",
    "mdi:check-circle",
    "mdi:alpha",
    "mdi:bacteria",
    "mdi:molecule",
    "mdi:virus",
    "mdi:family-tree",
    "mdi:forest",
    "mdi:scale-balance",
    "mdi:shape",
    "mdi:map-marker",
    "mdi:image-multiple",
    "mdi:chart-line-variant",
    "mdi:chart-bell-curve-cumulative",
)

# Filter icons: `ICON_OPTIONS` in InteractiveBuilder.tsx.
INTERACTIVE_ICONS: tuple[str, ...] = (
    "bx:slider-alt",
    "mdi:chart-line",
    "mdi:counter",
    "mdi:thermometer",
    "mdi:water",
    "mdi:flask",
    "mdi:air-filter",
    "mdi:flash",
    "mdi:gauge",
    "mdi:water-percent",
    "mdi:ruler",
    "mdi:blur",
    "mdi:leaf",
    "mdi:check-circle",
    "mdi:target",
    "mdi:bullseye-arrow",
    "mdi:flask-empty",
    "mdi:shield-check",
    "mdi:chart-bell-curve",
    "mdi:scatter-plot",
    "mdi:alert-circle",
    "mdi:sine-wave",
    "mdi:beaker",
    "mdi:speedometer",
    "mdi:flash-outline",
    "mdi:trending-up",
    "mdi:dna",
    "mdi:map-marker-path",
    "mdi:content-copy",
    "mdi:form-select",
    "mdi:radiobox-marked",
    "mdi:checkbox-marked",
    "mdi:toggle-switch",
    "mdi:calendar-range",
    "mdi:bacteria",
    "mdi:virus",
    "mdi:family-tree",
    "mdi:city",
    "mdi:waves",
    "mdi:image-filter",
)

ICONS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "card": CARD_ICONS,
    "interactive": INTERACTIVE_ICONS,
}

# The palette both builders' swatches are drawn from, one hex per hue. Named
# so a Mantine palette name answered by the model resolves to the same value
# a person would have picked from the swatch row.
COLOR_BY_NAME: dict[str, str] = {
    "red": "#fa5252",
    "pink": "#e64980",
    "grape": "#be4bdb",
    "violet": "#7950f2",
    "indigo": "#4c6ef5",
    "blue": "#228be6",
    "cyan": "#15aabf",
    "teal": "#12b886",
    "green": "#40c057",
    "lime": "#82c91e",
    "yellow": "#fab005",
    "orange": "#fd7e14",
}
COMPONENT_COLORS: tuple[str, ...] = tuple(COLOR_BY_NAME.values())

# Which styling keys each type carries, and what fills them.
_COLOR_KEYS: dict[str, tuple[str, ...]] = {
    "card": ("icon_color", "title_color"),
    "interactive": ("custom_color",),
}


def icon_choices(component_type: str) -> str:
    """The icon allowlist as one comma-separated prompt line."""
    return ", ".join(ICONS_BY_TYPE.get(component_type, ()))


def color_choices() -> str:
    """The palette as `name (#hex)` pairs, so either answer is understood."""
    return ", ".join(f"{name} ({hex_})" for name, hex_ in COLOR_BY_NAME.items())


def sanitize_style(component: dict[str, Any]) -> None:
    """Keep the styling a generated card or filter can actually render.

    A colour given by name becomes its hex. An icon or a colour outside the
    picker is dropped rather than kept: the field is decorative, and a value
    the bundle does not carry renders as a blank box and blanks itself on the
    first save anyway. Mutates in place; anything else is left untouched.
    """
    component_type = component.get("component_type")
    icons = ICONS_BY_TYPE.get(str(component_type), ())
    icon = component.get("icon_name")
    if icon is not None and icon not in icons:
        component.pop("icon_name", None)
    for key in _COLOR_KEYS.get(str(component_type), ()):
        value = component.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value.strip().casefold() in COLOR_BY_NAME:
            component[key] = COLOR_BY_NAME[value.strip().casefold()]
        elif value not in COMPONENT_COLORS:
            component.pop(key, None)
