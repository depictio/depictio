"""Record cards linked to residue-emitting tiles (lot 3 protein kinds + lollipop)."""

from __future__ import annotations

from typing import Any

import pytest

from depictio.models.components.advanced_viz.configs import LollipopConfig
from depictio.models.components.advanced_viz.record_link import (
    emitted_selection_column,
    linked_component_problems,
)

pytestmark = pytest.mark.no_db


def _viz(tag: str, config: dict[str, Any], dc: str = "variants") -> dict[str, Any]:
    return {
        "tag": tag,
        "component_type": "advanced_viz",
        "workflow_tag": "demo",
        "data_collection_tag": dc,
        "viz_kind": config["viz_kind"],
        "config": config,
    }


def _card(linked: str, id_col: str = "label") -> dict[str, Any]:
    return _viz(
        "variant-card", {"viz_kind": "record_card", "id_col": id_col, "linked_component": linked}
    )


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({"viz_kind": "lollipop"}, None),
        ({"viz_kind": "lollipop", "selection_enabled": True}, "position"),
        ({"viz_kind": "lollipop", "selection_enabled": True, "position_col": "aa_pos"}, "aa_pos"),
        ({"viz_kind": "lollipop", "selection_enabled": True, "label_col": "hgvs_p"}, "hgvs_p"),
        (
            {
                "viz_kind": "lollipop",
                "selection_enabled": True,
                "label_col": "hgvs_p",
                "selection_column": "variant_id",
            },
            "variant_id",
        ),
    ],
)
def test_lollipop_emits_only_when_opted_in(config: dict[str, Any], expected: str | None):
    assert emitted_selection_column(_viz("lolli", config)) == expected


def test_lollipop_config_accepts_the_selection_fields():
    cfg = LollipopConfig(selection_enabled=True, selection_column="variant_id")
    assert cfg.selection_enabled is True
    assert LollipopConfig().selection_enabled is False


@pytest.mark.parametrize(
    "source",
    [
        {"viz_kind": "molecule_3d"},
        {"viz_kind": "sequence_track"},
        {"viz_kind": "lollipop", "selection_enabled": True},
    ],
)
def test_a_residue_pick_drives_a_card_on_the_same_collection_whatever_its_id_col(
    source: dict[str, Any],
):
    comps = [_viz("protein", source), _card("protein", id_col="label")]
    assert linked_component_problems(comps) == []


def test_an_opted_out_lollipop_is_still_reported():
    comps = [_viz("protein", {"viz_kind": "lollipop"}), _card("protein")]
    problems = linked_component_problems(comps)
    assert len(problems) == 1 and "emits no selection" in problems[0]


def test_an_msa_row_pick_still_has_to_match_the_card_id_col():
    comps = [_viz("aln", {"viz_kind": "msa"}, dc="msa"), _card("aln", id_col="seq")]
    comps[1]["data_collection_tag"] = "msa"
    problems = linked_component_problems(comps)
    assert len(problems) == 1 and "selects on 'seq_id'" in problems[0]
