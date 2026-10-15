"""Record cards linked to residue-emitting tiles (protein kinds + lollipop)."""

from __future__ import annotations

from typing import Any

import pytest

from depictio.models.components.advanced_viz.configs import LollipopConfig
from depictio.models.components.advanced_viz.record_link import (
    RESIDUE_EMITTING_KINDS,
    SELECTION_ON_BY_DEFAULT,
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
        {"viz_kind": "hmm_logo"},
        {"viz_kind": "secondary_structure"},
        {"viz_kind": "domain_architecture"},
        {"viz_kind": "pae_matrix", "pae_dc_tag": "pae"},
        {"viz_kind": "ramachandran"},
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


PROTEIN_WAVE_2 = (
    "hmm_logo",
    "secondary_structure",
    "domain_architecture",
    "pae_matrix",
    "ramachandran",
)


@pytest.mark.parametrize("kind", PROTEIN_WAVE_2)
def test_the_second_protein_wave_is_residue_emitting_and_on_by_default(kind: str):
    assert kind in RESIDUE_EMITTING_KINDS
    assert kind in SELECTION_ON_BY_DEFAULT


@pytest.mark.parametrize("kind", PROTEIN_WAVE_2)
def test_an_opted_out_second_wave_tile_is_still_reported(kind: str):
    config = {"viz_kind": kind, "selection_enabled": False}
    if kind == "pae_matrix":
        config["pae_dc_tag"] = "pae"
    problems = linked_component_problems([_viz("protein", config), _card("protein")])
    assert len(problems) == 1 and "emits no selection" in problems[0]


def test_a_domain_pick_links_a_card_on_the_label_column():
    domains = _viz("domains", {"viz_kind": "domain_architecture"}, dc="domains")
    assert emitted_selection_column(domains) == "label"
    card = _card("domains", id_col="label")
    card["data_collection_tag"] = "domains"
    assert linked_component_problems([domains, card]) == []
    # The card has to key on the effective selection column, not any column.
    card["config"]["id_col"] = "domain_id"
    problems = linked_component_problems([domains, card])
    assert len(problems) == 1 and "selects on 'label'" in problems[0]


def test_a_domain_pick_links_a_card_on_the_selection_column_when_named():
    config = {"viz_kind": "domain_architecture", "selection_column": "domain_id"}
    domains = _viz("domains", config, dc="domains")
    assert emitted_selection_column(domains) == "domain_id"
    card = _card("domains", id_col="domain_id")
    card["data_collection_tag"] = "domains"
    assert linked_component_problems([domains, card]) == []
    # The label no longer identifies the pick, so a card keyed on it is reported.
    card["config"]["id_col"] = "label"
    problems = linked_component_problems([domains, card])
    assert len(problems) == 1 and "selects on 'domain_id'" in problems[0]


def test_a_domain_pick_with_label_selection_off_leaves_the_card_id_col_free():
    config = {"viz_kind": "domain_architecture", "label_selection": False}
    domains = _viz("domains", config, dc="domains")
    card = _card("domains", id_col="domain_id")
    card["data_collection_tag"] = "domains"
    assert linked_component_problems([domains, card]) == []
