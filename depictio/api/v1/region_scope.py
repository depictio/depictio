"""Which components a genome region filter applies to.

A locus navigator (``genome_view`` with ``region_filter_enabled``) publishes the
region it shows, its ``default_region`` included, as an ordinary filter pair
(``source: "genome_selection"``, a chromosome ``MultiSelect`` and a position
``RangeSlider``). Every component on the region's collection, and every one a
``region`` link reaches, used to apply it, so a tab opened on a small window
turned its run-wide cards into cards about that window (a mean depth of the
window instead of the run, a per-chromosome donut at one chromosome, 100 %).

A region is a place to look, not a subset to summarise. So it applies to the
components that draw coordinates (tracks, locus views, genomic advanced_viz
kinds, tables) and not to:

- cards, which summarise a collection (``bulk_compute_cards`` and the card
  builder's preview routes, ``/deltatables/breakdown`` and
  ``/deltatables/card_metric``);
- figures whose encodings never name one of the region's columns (a bar per
  contig, a histogram of depth);
- interactive filters, whose options the funnel narrows under every other
  active filter: a sidebar contig selector would otherwise offer one contig.

Any of them can opt back in with ``follow_region_filter: true`` on the component,
the flag ``genome_view`` already uses for "follow the section's region".
"""

from __future__ import annotations

from typing import Any

from depictio.api.v1.filter_links import GENOME_SELECTION_SOURCE

# Component types a region never reaches unless they opt in (figures only when
# they do not encode a region column, see ``_figure_encodes``).
_SCOPED_TYPES = frozenset({"card", "figure", "interactive"})


def is_region_filter(f: Any) -> bool:
    """True for either half of a genome region pair."""
    if not isinstance(f, dict):
        return False
    meta = f.get("metadata") or {}
    return (f.get("source") or meta.get("source")) == GENOME_SELECTION_SOURCE


def _filter_column(f: dict) -> str | None:
    meta = f.get("metadata") or {}
    column = f.get("column_name") or meta.get("column_name")
    return str(column) if column else None


def follows_region(component: dict | None) -> bool:
    """The explicit opt-in, on the component or on its ``config``."""
    if not component:
        return False
    if component.get("follow_region_filter") is True:
        return True
    config = component.get("config")
    return isinstance(config, dict) and config.get("follow_region_filter") is True


def _string_values(value: Any):
    """Every string inside a (nested) figure-kwargs value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _string_values(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _string_values(v)


def _figure_encodes(component: dict, columns: set[str]) -> bool:
    """True when the figure's encodings (``dict_kwargs``) name a region column."""
    kwargs = component.get("dict_kwargs") or {}
    return any(v in columns for v in _string_values(kwargs))


def scope_region_filters(
    filters: list[dict],
    component_type: str,
    component: dict | None = None,
) -> list[dict]:
    """``filters`` without the region pair when ``component`` should not follow it.

    Only card, figure and interactive components are scoped; every other type
    gets the list unchanged. Strip before link resolution so a ``region`` link cannot bring
    the region back under another collection's column names.
    """
    if component_type not in _SCOPED_TYPES:
        return list(filters)
    region = [f for f in filters if is_region_filter(f)]
    if not region or follows_region(component):
        return list(filters)
    if component_type == "figure" and component is not None:
        columns = {c for c in (_filter_column(f) for f in region) if c}
        if _figure_encodes(component, columns):
            return list(filters)
    return [f for f in filters if not is_region_filter(f)]
