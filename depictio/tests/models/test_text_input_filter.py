"""TextInput interactive filter: model validation and the YAML round trip.

A TextInput filters a string column by a regular expression. The model has to
accept it on string columns only, refuse its options on any other control, and
carry `placeholder`, `case_sensitive` and `match_mode` through the YAML import,
the stored document and the export.
"""

import pytest
from pydantic import ValidationError

from depictio.models.components.interactive import InteractiveComponent
from depictio.models.components.lite import InteractiveLiteComponent
from depictio.models.models.dashboards import DashboardDataLite
from depictio.models.validation.dash_mantine import validate_interactive_component
from depictio.models.yaml_serialization.validation_rules import VALIDATION_RULES


def _lite(**kwargs) -> dict:
    return {
        "component_type": "interactive",
        "interactive_component_type": "TextInput",
        "workflow_tag": "nf-core/crisprseq",
        "data_collection_tag": "guides",
        "column_name": "guide",
        "column_type": "object",
        **kwargs,
    }


def _dashboard(**kwargs) -> DashboardDataLite:
    return DashboardDataLite(title="Guides", components=[{"tag": "guide-text", **_lite(**kwargs)}])


class TestColumnTypeCompatibility:
    def test_accepted_on_a_string_column(self):
        comp = InteractiveLiteComponent(**_lite())
        assert comp.interactive_component_type == "TextInput"

    @pytest.mark.parametrize("column_type", ["int64", "float64", "datetime", "bool", "category"])
    def test_rejected_on_every_other_column_type(self, column_type):
        with pytest.raises(ValidationError, match="TextInput|No interactive components"):
            InteractiveLiteComponent(**_lite(column_type=column_type))

    def test_the_numeric_message_names_the_valid_types(self):
        with pytest.raises(ValidationError) as err:
            InteractiveLiteComponent(**_lite(column_type="float64"))
        assert "Valid types" in str(err.value)

    def test_full_component_type_is_known(self):
        full = InteractiveComponent(
            interactive_component_type="TextInput", column_name="guide", column_type="object"
        )
        assert full.get_validation_result()[0] is True

    @pytest.mark.parametrize("column_type", ["object", "string"])
    def test_validator_accepts_string_columns(self, column_type):
        ok, errors, _ = validate_interactive_component("TextInput", column_type)
        assert ok and not errors

    @pytest.mark.parametrize("column_type", ["int64", "float64", "datetime", "bool"])
    def test_validator_rejects_other_columns(self, column_type):
        ok, errors, _ = validate_interactive_component("TextInput", column_type)
        assert not ok
        assert "TextInput expects string" in errors[0]["msg"]

    def test_yaml_rules_allow_it_on_object_only(self):
        rules = VALIDATION_RULES.get_column_type_rules
        assert rules("object").is_valid_filter("TextInput")
        assert not rules("float64").is_valid_filter("TextInput")
        assert not rules("datetime").is_valid_filter("TextInput")


class TestOptions:
    def test_defaults(self):
        comp = InteractiveLiteComponent(**_lite())
        assert comp.placeholder is None
        assert not comp.case_sensitive
        assert comp.match_mode in (None, "regex")

    def test_options_are_kept(self):
        comp = InteractiveLiteComponent(
            **_lite(placeholder="e.g. GGG$", case_sensitive=True, match_mode="contains")
        )
        assert (comp.placeholder, comp.case_sensitive, comp.match_mode) == (
            "e.g. GGG$",
            True,
            "contains",
        )

    def test_unknown_match_mode_is_rejected(self):
        with pytest.raises(ValidationError):
            InteractiveLiteComponent(**_lite(match_mode="glob"))

    @pytest.mark.parametrize(
        "option", [{"placeholder": "x"}, {"case_sensitive": True}, {"match_mode": "contains"}]
    )
    def test_options_are_refused_on_another_control(self, option):
        with pytest.raises(ValidationError, match="only valid for a TextInput"):
            InteractiveLiteComponent(**_lite(interactive_component_type="Select", **option))

    def test_default_value_must_be_a_string(self):
        assert InteractiveLiteComponent(**_lite(default_value="^ACG")).default_value == "^ACG"
        with pytest.raises(ValidationError, match="string"):
            InteractiveLiteComponent(**_lite(default_value=5))


class TestRoundTrip:
    def test_options_reach_the_stored_component(self):
        full = _dashboard(
            placeholder="e.g. GGG$", case_sensitive=True, match_mode="contains"
        ).to_full()
        stored = full["stored_metadata"][0]
        assert stored["interactive_component_type"] == "TextInput"
        assert stored["placeholder"] == "e.g. GGG$"
        assert stored["case_sensitive"] is True
        assert stored["match_mode"] == "contains"

    def test_defaults_are_not_stored_or_exported(self):
        dash = _dashboard()
        stored = dash.to_full()["stored_metadata"][0]
        assert "case_sensitive" not in stored
        assert "match_mode" not in stored
        assert "placeholder" not in stored
        yaml_text = DashboardDataLite.from_full(dash.to_full()).to_yaml()
        assert "case_sensitive" not in yaml_text and "match_mode" not in yaml_text
        assert "placeholder" not in yaml_text

    def test_yaml_round_trip(self):
        dash = _dashboard(
            title="Guide sequence",
            placeholder="e.g. GGG$ or ^ACG",
            case_sensitive=True,
            match_mode="contains",
            default_value="^ACG",
        )
        for again in (
            DashboardDataLite.from_yaml(dash.to_yaml()),
            DashboardDataLite.from_full(dash.to_full()),
        ):
            comp = again.components[0]
            comp = comp if isinstance(comp, dict) else comp.model_dump()
            assert comp["interactive_component_type"] == "TextInput"
            assert comp["placeholder"] == "e.g. GGG$ or ^ACG"
            assert comp["case_sensitive"] is True
            assert comp["match_mode"] == "contains"
            assert comp["default_value"] == "^ACG"
