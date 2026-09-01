"""The Sankey figure has to carry its own hover design.

The React renderer replaces both hovertemplates with a richer version, so for
a long time the compute task could leave the hover entirely undescribed and
the dashboard still looked right. An export changed that: it ships the compute
task's figure verbatim, so whatever the task leaves unsaid falls through to
Plotly's defaults on someone else's page.

Two of those defaults are actively wrong for a Sankey. `valueformat` is SI
notation, which renders a relative abundance of 0.881 as "881m". And with no
hovertemplate the trace name becomes a second label that Plotly draws outside
the tooltip box, unboxed, on top of the diagram.
"""

from __future__ import annotations

from depictio.api.v1.celery_tasks import _sankey_value_format


def test_a_fraction_reads_as_a_percentage() -> None:
    # The defect this whole module exists for: ".3s" turns 0.881 into "881m".
    assert _sankey_value_format("fraction", [0.881, 0.077]) == ".2%"


def test_counts_get_thousands_separators() -> None:
    assert _sankey_value_format("count", [12000.0, 4.0]) == ","


def test_raw_values_below_one_keep_four_decimals() -> None:
    # Abundances live here when a dashboard does not declare a format; ".2f"
    # would print 0.00 for most of the links.
    assert _sankey_value_format("raw", [0.0771, 0.0069]) == ".4f"


def test_raw_values_above_one_keep_two() -> None:
    assert _sankey_value_format("raw", [1204.5, 3.0]) == ".2f"


def test_no_values_at_all_still_yields_a_format() -> None:
    # An over-filtered Sankey has no links; max() over an empty sequence would
    # raise, and the figure still has to be serialisable.
    assert _sankey_value_format("raw", []) == ".2f"


def test_an_unknown_mode_falls_back_to_raw() -> None:
    assert _sankey_value_format("percentage-ish", [0.5]) == ".4f"
