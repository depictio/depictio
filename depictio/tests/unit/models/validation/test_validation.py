"""
Basic unit tests for component validation modules.

Tests cover core functionality without exhaustive edge cases.
"""


class TestPlotlyExpressValidation:
    """Tests for Plotly Express dict_kwargs validation."""

    def test_valid_scatter_params(self):
        """Valid scatter parameters should pass."""
        from depictio.models.validation.plotly_express import validate_dict_kwargs

        is_valid, errors = validate_dict_kwargs(
            "scatter", {"x": "col1", "y": "col2", "color": "col3"}
        )
        assert is_valid is True
        assert errors == []

    def test_invalid_param_name(self):
        """Invalid parameter name should fail with suggestion."""
        from depictio.models.validation.plotly_express import validate_dict_kwargs

        is_valid, errors = validate_dict_kwargs("scatter", {"x": "col1", "colour": "col2"})
        assert is_valid is False
        assert len(errors) == 1
        assert "colour" in errors[0]["msg"]
        assert "color" in errors[0]["msg"]  # Suggestion

    def test_invalid_chart_type(self):
        """Invalid chart type should fail."""
        from depictio.models.validation.plotly_express import validate_dict_kwargs

        is_valid, errors = validate_dict_kwargs("invalid_chart", {"x": "col1"})
        assert is_valid is False
        assert "invalid_chart" in errors[0]["msg"]

    def test_visu_type_specific_params(self):
        """Parameters should be validated per visu_type."""
        from depictio.models.validation.plotly_express import validate_dict_kwargs

        # trendline valid for scatter
        is_valid, _ = validate_dict_kwargs("scatter", {"x": "a", "y": "b", "trendline": "ols"})
        assert is_valid is True

        # trendline invalid for pie
        is_valid, errors = validate_dict_kwargs(
            "pie", {"names": "a", "values": "b", "trendline": "ols"}
        )
        assert is_valid is False

    def test_empty_dict_kwargs(self):
        """Empty dict_kwargs should be valid."""
        from depictio.models.validation.plotly_express import validate_dict_kwargs

        is_valid, errors = validate_dict_kwargs("scatter", {})
        assert is_valid is True

        is_valid, errors = validate_dict_kwargs("scatter", None)
        assert is_valid is True


class TestAGGridValidation:
    """Tests for AG Grid cols_json validation."""

    def test_valid_cols_json(self):
        """Valid cols_json should pass."""
        from depictio.models.validation.ag_grid import validate_cols_json

        cols = {
            "name": {"type": "object", "filter": "agTextColumnFilter"},
            "count": {"type": "int64", "filter": "agNumberColumnFilter"},
        }
        is_valid, errors, validated = validate_cols_json(cols)
        assert is_valid is True
        assert errors == []
        assert validated is not None

    def test_auto_filter_assignment(self):
        """Filter should be auto-assigned based on type."""
        from depictio.models.validation.ag_grid import validate_cols_json

        cols = {"count": {"type": "int64"}}  # No filter specified
        is_valid, errors, validated = validate_cols_json(cols)
        assert is_valid is True
        assert validated["count"].filter == "agNumberColumnFilter"

    def test_type_normalization(self):
        """Type aliases should be normalized."""
        from depictio.models.validation.ag_grid import validate_cols_json

        cols = {"name": {"type": "str"}}  # 'str' -> 'object'
        is_valid, errors, validated = validate_cols_json(cols)
        assert is_valid is True
        assert validated["name"].type == "object"

    def test_cols_json_to_column_defs(self):
        """Should convert cols_json to AG Grid columnDefs."""
        from depictio.models.validation.ag_grid import cols_json_to_column_defs

        cols = {"sample": {"type": "object"}}
        column_defs = cols_json_to_column_defs(cols)

        assert len(column_defs) == 2  # ID column + sample
        assert column_defs[0]["field"] == "ID"
        assert column_defs[1]["field"] == "sample"

    def test_none_cols_json(self):
        """None cols_json should be valid."""
        from depictio.models.validation.ag_grid import validate_cols_json

        is_valid, errors, validated = validate_cols_json(None)
        assert is_valid is True
        assert validated is None


class TestDashMantineValidation:
    """Tests for Dash Mantine interactive component validation."""

    def test_valid_select(self):
        """Select with object column should be valid."""
        from depictio.models.validation.dash_mantine import validate_interactive_component

        is_valid, errors, warnings = validate_interactive_component("Select", "object")
        assert is_valid is True
        assert errors == []

    def test_slider_requires_numeric(self):
        """Slider should require numeric column type."""
        from depictio.models.validation.dash_mantine import validate_interactive_component

        # Invalid: string column
        is_valid, errors, _ = validate_interactive_component("Slider", "object")
        assert is_valid is False
        assert "numeric" in errors[0]["msg"]

        # Valid: float column
        is_valid, errors, _ = validate_interactive_component("Slider", "float64")
        assert is_valid is True

    def test_date_picker_requires_datetime(self):
        """DateRangePicker should require datetime column."""
        from depictio.models.validation.dash_mantine import validate_interactive_component

        is_valid, errors, _ = validate_interactive_component("DateRangePicker", "object")
        assert is_valid is False

        is_valid, errors, _ = validate_interactive_component("DateRangePicker", "datetime")
        assert is_valid is True

    def test_invalid_component_type(self):
        """Invalid component type should fail."""
        from depictio.models.validation.dash_mantine import validate_interactive_component

        is_valid, errors, _ = validate_interactive_component("InvalidComponent", "object")
        assert is_valid is False
        assert "InvalidComponent" in errors[0]["msg"]

    def test_component_recommendations(self):
        """Should recommend appropriate components."""
        from depictio.models.validation.dash_mantine import get_recommended_component

        assert get_recommended_component("datetime") == "DateRangePicker"
        assert get_recommended_component("float64") == "RangeSlider"
        assert get_recommended_component("bool") == "Switch"


class TestComponentModelIntegration:
    """Tests for validation integration in component models."""

    def test_figure_component_validates(self):
        """FigureComponent should validate dict_kwargs."""
        from depictio.models.components.figure import FigureComponent

        # Should create without error (warns but doesn't fail)
        fig = FigureComponent(
            title="Test",
            visu_type="scatter",
            dict_kwargs={"x": "col1", "colour": "col2"},  # typo
        )
        assert fig.title == "Test"

        # Explicit validation should show error
        is_valid, errors = fig.get_validated_dict_kwargs()
        assert is_valid is False

    def test_interactive_component_validates(self):
        """InteractiveComponent should validate type compatibility."""
        from depictio.models.components.interactive import InteractiveComponent

        # Should create without error (warns but doesn't fail)
        comp = InteractiveComponent(
            interactive_component_type="Slider",
            column_name="name",
            column_type="object",  # Invalid for slider
        )
        assert comp.interactive_component_type == "Slider"

        # Explicit validation should show error
        is_valid, errors, _ = comp.get_validation_result()
        assert is_valid is False

    def test_table_component_validates(self):
        """TableComponent should validate cols_json."""
        from depictio.models.components.table import TableComponent

        # Valid cols_json
        table = TableComponent(
            cols_json={"sample": {"type": "object"}},
        )
        assert table.cols_json is not None

        # Can convert to column defs
        defs = table.to_column_defs()
        assert len(defs) >= 1
