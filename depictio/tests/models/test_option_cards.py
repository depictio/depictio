"""``option_cards``: a SegmentedControl drawn as one card per option.

The choice of a reference database changes what a whole tab shows, so a bare row
of labels does not say what the reader gets. A card carries a title, an icon and a
line of description, keyed by the option's value, and the control may sit in the
top panel. The model only has to carry them through import, the full document and
export.
"""

import pytest
from pydantic import ValidationError

from depictio.models.models.dashboards import DashboardDataLite

CARDS = {
    "silva": {"label": "SILVA 138.2", "icon": "mdi:bacteria", "description": "Bacteria named"},
    "pr2": {"label": "PR2 5.0.0", "description": "Eukaryotes named"},
}


def _control(**kwargs) -> dict:
    return {
        "tag": "taxonomy",
        "component_type": "interactive",
        "workflow_tag": "ampliseq",
        "data_collection_tag": "ancombc_results",
        "interactive_component_type": "SegmentedControl",
        "column_name": "taxonomy",
        "column_type": "object",
        **kwargs,
    }


def _dashboard(component: dict) -> DashboardDataLite:
    return DashboardDataLite(title="Switch", components=[component])


def test_unset_by_default():
    meta = _dashboard(_control()).to_full()["stored_metadata"][0]
    assert "option_cards" not in meta


def test_reaches_the_full_document():
    meta = _dashboard(_control(option_cards=CARDS)).to_full()["stored_metadata"][0]
    assert meta["option_cards"] == CARDS


def test_survives_a_round_trip_and_the_yaml_export():
    back = DashboardDataLite.from_full(_dashboard(_control(option_cards=CARDS)).to_full())
    assert back.components[0].option_cards["silva"].label == "SILVA 138.2"  # type: ignore[union-attr,index]
    assert "option_cards" in back.to_yaml()


def test_unset_card_fields_are_not_stored():
    meta = _dashboard(_control(option_cards=CARDS)).to_full()["stored_metadata"][0]
    assert "icon" not in meta["option_cards"]["pr2"]


def test_only_a_segmented_control_takes_cards():
    with pytest.raises(ValidationError, match="option_cards"):
        _dashboard(_control(interactive_component_type="MultiSelect", option_cards=CARDS))


def test_rejects_an_unknown_card_field():
    with pytest.raises(ValidationError):
        _dashboard(_control(option_cards={"silva": {"colour": "red"}}))


def test_a_segmented_control_may_sit_in_the_top_panel():
    meta = _dashboard(_control(placement="top")).to_full()["stored_metadata"][0]
    assert meta["placement"] == "top"


def test_a_select_may_not():
    with pytest.raises(ValidationError, match="placement"):
        _dashboard(_control(interactive_component_type="Select", placement="top"))
