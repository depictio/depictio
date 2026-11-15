"""Every advanced-viz kind has one explicit serverless tier.

The bundle used to decide by elimination (``pruning.serves_advanced_viz_live``
was a deny-list), so a new kind — or a renderer that fetches files on its own —
was "live" until someone noticed it could not draw. The table now lives beside
the component export's matrix (``SERVERLESS_KINDS`` in
``api/v1/services/export/capabilities.py``); a kind added to ``AdvancedVizKind``
without a tier fails here and in that module's import-time self-check.
"""

from __future__ import annotations

from typing import get_args

import pytest

from depictio.api.v1.services.export.capabilities import (
    HTML_UNAVAILABLE_KINDS,
    SERVERLESS_KINDS,
    serverless_capability,
)
from depictio.models.components.advanced_viz.sampling import KIND_SAMPLING_POLICY
from depictio.models.components.types import AdvancedVizKind

KINDS = sorted(get_args(AdvancedVizKind))


@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_has_a_tier_and_a_reason_when_not_live(kind: str) -> None:
    cap = SERVERLESS_KINDS[kind]
    assert cap.tier in ("live", "frozen", "omitted")
    if cap.tier != "live":
        assert cap.reason, f"{kind} is {cap.tier} without saying why"
    else:
        assert cap.path in ("data", "compute_live")
        # A live kind is reduced in the browser by the sampling table.
        assert kind in KIND_SAMPLING_POLICY


def test_no_extra_kinds() -> None:
    assert set(SERVERLESS_KINDS) == set(KINDS)


def test_the_offline_embed_and_the_bundle_agree_on_what_fetches_files() -> None:
    """The renderer-fetching kinds main's embed refuses are not live here either."""
    for kind in ("molecule_3d", "pae_matrix", "ramachandran", "contact_map", "group_compare"):
        assert kind in HTML_UNAVAILABLE_KINDS
        assert SERVERLESS_KINDS[kind].tier != "live"


def test_sub_modes_and_unknown_kinds() -> None:
    table_driven = {"component_type": "advanced_viz", "viz_kind": "embedding", "config": {}}
    assert serverless_capability(table_driven).tier == "live"
    computed = {**table_driven, "config": {"compute_method": "tsne"}}
    assert (serverless_capability(computed).tier, serverless_capability(computed).path) == (
        "frozen",
        "celery",
    )
    assert serverless_capability({"viz_kind": "upset"}).path == "celery"
    assert serverless_capability({"viz_kind": "bioimage_viewer"}).tier == "omitted"
