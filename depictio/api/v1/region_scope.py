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

A residue range picked on a protein tile (``source: "residue_selection"``, an
entity ``MultiSelect`` and a position ``RangeSlider``, see ``residueRangeFilters``
in packages/depictio-react-core/src/selection.ts) is the same kind of filter on
protein coordinates, and is scoped by the same rule.

The heatmap and the UpSet are a second case (``scope_residue_filters``): they
summarise a whole collection (one cell per sample and column, one bar per set
intersection), so a click on a domain or residue span in another tile must not
narrow them to the one protein it names. They ignore the whole residue gesture
and keep every real dashboard filter.
"""

from __future__ import annotations

from typing import Any

from depictio.api.v1.filter_links import GENOME_SELECTION_SOURCE

# The residue pick of the protein tiles: the same pair shape on protein
# coordinates. Mirrors `residueRangeFilters` in selection.ts.
RESIDUE_SELECTION_SOURCE = "residue_selection"
_LOCUS_SOURCES = frozenset({GENOME_SELECTION_SOURCE, RESIDUE_SELECTION_SOURCE})

# Component types a region never reaches unless they opt in (figures only when
# they do not encode a region column, see ``_figure_encodes``).
_SCOPED_TYPES = frozenset({"card", "figure", "interactive"})

# advanced_viz kinds that never follow a residue pick. The dispatcher names them
# ``upset`` and the export path ``upset_plot``. Every other kind (molecule_3d,
# sequence_track, msa, hmm_logo, domain_architecture, secondary_structure, ...)
# is driven by the pick and is deliberately absent.
_RESIDUE_BLIND_KINDS = frozenset({"complex_heatmap", "upset", "upset_plot"})


def is_region_filter(f: Any) -> bool:
    """True for either half of a genome region pair or of a residue range pair."""
    if not isinstance(f, dict):
        return False
    meta = f.get("metadata") or {}
    return (f.get("source") or meta.get("source")) in _LOCUS_SOURCES


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


def is_residue_gesture_filter(f: Any) -> bool:
    """True for a residue pick (either half) or a selection emitted with it.

    ``paired_with`` marks the label a ``domain_architecture`` domain click adds
    beside its span (``pairedWithResiduePick`` in selection.ts). The viewer
    drops it together with the pick, so it belongs to the same gesture.
    """
    if not isinstance(f, dict):
        return False
    meta = f.get("metadata") or {}
    if (f.get("source") or meta.get("source")) == RESIDUE_SELECTION_SOURCE:
        return True
    return (f.get("paired_with") or meta.get("paired_with")) == RESIDUE_SELECTION_SOURCE


def scope_residue_filters(filters: list[dict], viz_kind: str | None) -> list[dict]:
    """``filters`` without the residue gesture for kinds that ignore it.

    The pick travels as an entity ``MultiSelect`` plus a position ``RangeSlider``
    (both ``residue_selection``) and, for a domain click, a paired label
    selection. The entity half goes too: link resolution would carry it to the
    heatmap's collection as a one-protein row filter, and
    ``_narrow_wide_matrix_columns`` would read set names into a column subset.
    Strip before link resolution, like ``scope_region_filters``.
    """
    if viz_kind not in _RESIDUE_BLIND_KINDS:
        return list(filters)
    return [f for f in filters if not is_residue_gesture_filter(f)]
