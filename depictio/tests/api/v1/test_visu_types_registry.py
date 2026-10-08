"""The YAML validator's chart list must match the one the builder offers.

Two lists name the visualisations a figure may be: ``ALLOWED_VISUALIZATIONS``
in the API's figure registry, which the builder dropdown is populated from at
runtime, and ``VISU_TYPES`` in the model layer, which validates a YAML or CLI
dashboard. They cannot be one constant — the model layer is shared with the CLI
and must not import the API package — so they are a copy, and a copy drifts.

It already did. ``VISU_TYPES`` stayed on the six types a since-deleted Dash
module offered while the registry grew to twelve, which meant a violin built in
the UI could not be written down in YAML: the dashboard was rejected for
declaring a chart the product renders. Nothing failed at the time, because
nothing compared the two.
"""

from depictio.api.v1.services.figure.definitions import (
    ALLOWED_VISUALIZATIONS,
    VIZ_LABELS_DESCRIPTIONS,
)
from depictio.models.components.constants import VISU_TYPES

#: In ``VISU_TYPES`` but deliberately not in the API registry. ``heatmap`` is not
#: a Plotly Express constructor — it renders through the complex-heatmap path —
#: so the registry excludes it while YAML still has to accept it.
NON_PX_TYPES = frozenset({"heatmap"})


def test_visu_types_match_registry():
    """Every builder visualisation is writable in YAML, and vice versa."""
    model_types = set(VISU_TYPES)
    registry_types = set(ALLOWED_VISUALIZATIONS)

    missing_from_yaml = registry_types - model_types
    assert not missing_from_yaml, (
        "the builder offers visualisations a YAML dashboard cannot declare: "
        f"{sorted(missing_from_yaml)} — add them to models/components/constants.py"
    )

    unknown_to_registry = model_types - registry_types - NON_PX_TYPES
    assert not unknown_to_registry, (
        "YAML accepts visualisations the builder does not offer: "
        f"{sorted(unknown_to_registry)} — either add them to ALLOWED_VISUALIZATIONS "
        "or drop them from VISU_TYPES"
    )


def test_non_px_types_are_absent_from_the_registry():
    """The documented exception stays an exception.

    If ``heatmap`` ever joins the registry the exemption above is stale, and
    keeping it would hide the next real difference.
    """
    assert NON_PX_TYPES.isdisjoint(ALLOWED_VISUALIZATIONS), (
        f"{sorted(NON_PX_TYPES & set(ALLOWED_VISUALIZATIONS))} is in the registry now — "
        "drop it from NON_PX_TYPES so the lists compare directly"
    )


def test_every_allowed_visualisation_has_builder_copy():
    """A type in the registry with no label reaches the dropdown unlabelled."""
    missing = set(ALLOWED_VISUALIZATIONS) - set(VIZ_LABELS_DESCRIPTIONS)
    assert not missing, (
        f"no label/description for {sorted(missing)} — add a row to VIZ_LABELS_DESCRIPTIONS"
    )
