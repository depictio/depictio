"""
Robust component builder for figure parameter UI.

This module provides a clean, maintainable way to build UI components
for figure parameters, replacing the fragile nested dictionary approach.
"""

from typing import Any, Dict, List, Optional, Union

import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html
from dash_iconify import DashIconify

from .models import FigureComponentState, ParameterDefinition, ParameterType


class ComponentBuilder:
    """Builder for creating parameter input components."""

    def __init__(self, component_index: str, columns: List[str]):
        """Initialize component builder.

        Args:
            component_index: Unique index for this component instance
            columns: Available column names for column-type parameters
        """
        self.component_index = component_index
        self.columns = columns

    def build_parameter_input(
        self, param: ParameterDefinition, value: Any = None, disabled: bool = False
    ) -> Union[dmc.Select, dmc.MultiSelect, dbc.Input, dmc.Switch, html.Div]:
        """Build input component for a parameter.

        Args:
            param: Parameter definition
            value: Current parameter value
            disabled: Whether component should be disabled

        Returns:
            Appropriate Dash component for the parameter
        """
        component_id = {"type": f"param-{param.name}", "index": self.component_index}

        # Use provided value or parameter default
        current_value = value if value is not None else param.default

        if param.type == ParameterType.COLUMN:
            return self._build_column_dropdown(param, component_id, current_value, disabled)
        elif param.type == ParameterType.SELECT:
            return self._build_select_dropdown(param, component_id, current_value, disabled)
        elif param.type == ParameterType.MULTI_SELECT:
            return self._build_multi_select(param, component_id, current_value, disabled)
        elif param.type == ParameterType.STRING:
            return self._build_text_input(param, component_id, current_value, disabled)
        elif param.type in [ParameterType.INTEGER, ParameterType.FLOAT]:
            return self._build_numeric_input(param, component_id, current_value, disabled)
        elif param.type == ParameterType.BOOLEAN:
            return self._build_boolean_switch(param, component_id, current_value, disabled)
        elif param.type == ParameterType.RANGE:
            return self._build_range_input(param, component_id, current_value, disabled)
        elif param.type == ParameterType.COLOR:
            return self._build_color_picker(param, component_id, current_value, disabled)
        else:
            return html.Div(f"Unsupported parameter type: {param.type}")

    def _build_column_dropdown(
        self, param: ParameterDefinition, component_id: Dict, value: Any, disabled: bool
    ) -> dmc.Select:
        """Build dropdown for column selection."""
        return dmc.Select(
            id=component_id,
            data=[{"label": col, "value": col} for col in self.columns],
            value=value,
            placeholder=f"Select {param.label.lower()}...",
            disabled=disabled,
            clearable=not param.required,
            searchable=True,
            comboboxProps={"withinPortal": False},  # Prevents dropdown from going behind modals
            style={"width": "100%"},
        )

    def _build_select_dropdown(
        self, param: ParameterDefinition, component_id: Dict, value: Any, disabled: bool
    ) -> dmc.Select:
        """Build dropdown for option selection."""
        options = [{"label": str(opt), "value": opt} for opt in (param.options or [])]
        return dmc.Select(
            id=component_id,
            data=options,
            value=value,
            placeholder=f"Select {param.label.lower()}...",
            disabled=disabled,
            clearable=not param.required,
            searchable=True,
            comboboxProps={"withinPortal": False},  # Prevents dropdown from going behind modals
            style={"width": "100%"},
        )

    def _build_multi_select(
        self, param: ParameterDefinition, component_id: Dict, value: Any, disabled: bool
    ) -> dmc.MultiSelect:
        """Build multi-select dropdown."""
        if param.name in ["hover_data", "custom_data"]:
            # Special case for data parameters - use columns
            options = [{"label": col, "value": col} for col in self.columns]
        else:
            options = [{"label": str(opt), "value": opt} for opt in (param.options or [])]

        return dmc.MultiSelect(
            id=component_id,
            data=options,
            value=value or [],
            placeholder=f"Select {param.label.lower()}...",
            disabled=disabled,
            searchable=True,
            comboboxProps={"withinPortal": False},  # Prevents dropdown from going behind modals
            style={"width": "100%"},
        )

    def _build_text_input(
        self, param: ParameterDefinition, component_id: Dict, value: Any, disabled: bool
    ) -> dbc.Input:
        """Build text input."""
        return dbc.Input(
            id=component_id,
            type="text",
            value=value or "",
            placeholder=param.label,
            disabled=disabled,
            style={"width": "100%"},
        )

    def _build_numeric_input(
        self, param: ParameterDefinition, component_id: Dict, value: Any, disabled: bool
    ) -> dbc.Input:
        """Build numeric input."""
        input_type = "number"
        step = 1 if param.type == ParameterType.INTEGER else 0.1

        return dbc.Input(
            id=component_id,
            type=input_type,
            value=value,
            placeholder=param.label,
            disabled=disabled,
            min=param.min_value,
            max=param.max_value,
            step=step,
            style={"width": "100%"},
        )

    def _build_boolean_switch(
        self, param: ParameterDefinition, component_id: Dict, value: Any, disabled: bool
    ) -> dmc.Switch:
        """Build boolean switch."""
        return dmc.Switch(
            id=component_id,
            checked=bool(value) if value is not None else False,
            disabled=disabled,
            label=param.label,
            size="sm",
        )

    def _build_range_input(
        self, param: ParameterDefinition, component_id: Dict, value: Any, disabled: bool
    ) -> html.Div:
        """Build range input (min/max)."""
        min_id = {**component_id, "type": f"{component_id['type']}-min"}
        max_id = {**component_id, "type": f"{component_id['type']}-max"}

        min_val, max_val = None, None
        if value and isinstance(value, (list, tuple)) and len(value) == 2:
            min_val, max_val = value

        return html.Div(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                dbc.Label("Min", size="sm"),
                                dbc.Input(
                                    id=min_id,
                                    type="number",
                                    value=min_val,
                                    placeholder="Min",
                                    disabled=disabled,
                                    size="sm",
                                ),
                            ],
                            width=6,
                        ),
                        dbc.Col(
                            [
                                dbc.Label("Max", size="sm"),
                                dbc.Input(
                                    id=max_id,
                                    type="number",
                                    value=max_val,
                                    placeholder="Max",
                                    disabled=disabled,
                                    size="sm",
                                ),
                            ],
                            width=6,
                        ),
                    ]
                )
            ]
        )

    def _build_color_picker(
        self, param: ParameterDefinition, component_id: Dict, value: Any, disabled: bool
    ) -> dbc.Input:
        """Build color picker input."""
        return dbc.Input(
            id=component_id,
            type="color",
            value=value or "#1f77b4",
            disabled=disabled,
            style={"width": "100%", "height": "38px"},
        )


class AccordionBuilder:
    """Builder for creating modern DMC accordions."""

    def __init__(self, component_builder: ComponentBuilder):
        """Initialize accordion builder.

        Args:
            component_builder: Component builder instance
        """
        self.component_builder = component_builder

    def build_parameter_accordion(
        self,
        parameters: List[ParameterDefinition],
        title: str,
        icon: str,
        state: Optional[FigureComponentState] = None,
        default_expanded: bool = True,
    ) -> Optional[dmc.AccordionItem]:
        """Build accordion section for parameters.

        Args:
            parameters: List of parameter definitions
            title: Section title
            icon: Icon name for section
            state: Current component state
            default_expanded: Whether section is expanded by default

        Returns:
            DMC accordion item
        """
        if not parameters:
            return None

        # Build parameter inputs
        parameter_inputs = []
        for param in parameters:
            current_value = state.get_parameter_value(param.name) if state else None

            # Create parameter input with label and description
            input_component = self.component_builder.build_parameter_input(
                param, value=current_value
            )

            # Create tooltip for parameter description
            tooltip_content = (
                dmc.Tooltip(
                    label=param.description or param.label,
                    position="top",
                    multiline=True,
                    children=[
                        dmc.Text(param.label, size="sm", fw="bold", style={"marginBottom": "5px"})
                    ],
                )
                if param.description
                else dmc.Text(param.label, size="sm", fw="bold", style={"marginBottom": "5px"})
            )

            # Add required indicator
            label_content = [tooltip_content]
            if param.required:
                label_content.append(
                    dmc.Text(" *", c="red", size="sm", style={"display": "inline"})
                )

            parameter_row = dmc.Stack([html.Div(label_content), input_component], gap="xs")

            parameter_inputs.append(parameter_row)

        # Create accordion content
        content = dmc.Stack(parameter_inputs, gap="md")

        # Create accordion item
        return dmc.AccordionItem(
            children=[
                dmc.AccordionControl(title, icon=DashIconify(icon=icon, width=20)),
                dmc.AccordionPanel(content),
            ],
            value=title.lower().replace(" ", "_"),
        )

    def build_full_accordion(
        self, visualization_def, state: Optional[FigureComponentState] = None
    ) -> dmc.Accordion:
        """Build complete accordion for visualization parameters.

        Args:
            visualization_def: Visualization definition
            state: Current component state

        Returns:
            Complete DMC accordion
        """
        accordion_items = []

        # Core parameters section
        if visualization_def.core_params:
            core_item = self.build_parameter_accordion(
                visualization_def.core_params,
                "Core Parameters",
                "mdi:cog",
                state,
                default_expanded=True,
            )
            if core_item:
                accordion_items.append(core_item)

        # Common parameters section
        if visualization_def.common_params:
            common_item = self.build_parameter_accordion(
                visualization_def.common_params,
                "Styling & Layout",
                "mdi:palette",
                state,
                default_expanded=False,
            )
            if common_item:
                accordion_items.append(common_item)

        # Specific parameters section
        if visualization_def.specific_params:
            specific_item = self.build_parameter_accordion(
                visualization_def.specific_params,
                f"{visualization_def.label} Options",
                visualization_def.icon,
                state,
                default_expanded=False,
            )
            if specific_item:
                accordion_items.append(specific_item)

        # Advanced parameters section
        if visualization_def.advanced_params:
            advanced_item = self.build_parameter_accordion(
                visualization_def.advanced_params,
                "Advanced Options",
                "mdi:tune",
                state,
                default_expanded=False,
            )
            if advanced_item:
                accordion_items.append(advanced_item)

        return dmc.Accordion(
            children=accordion_items,
            multiple=True,
            variant="separated",
            radius="md",
            value=["core_parameters"] if accordion_items else [],
            id={"type": "parameter-accordion", "index": self.component_builder.component_index},
        )
