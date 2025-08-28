"""
Robust component builder for figure parameter UI.

This module provides a clean, maintainable way to build UI components
for figure parameters, replacing the fragile nested dictionary approach.
"""

from typing import Any, Dict, List, Optional, Union

import dash_mantine_components as dmc
from dash import html
from dash_iconify import DashIconify

from .models import FigureComponentState, ParameterDefinition, ParameterType


class ComponentBuilder:
    """Builder for creating parameter input components."""

    def __init__(
        self, component_index: str, columns: List[str], columns_info: Optional[Dict] = None
    ):
        """Initialize component builder.

        Args:
            component_index: Unique index for this component instance
            columns: Available column names for column-type parameters
            columns_info: Dictionary with column type information {col_name: {"type": "int64", ...}}
        """
        self.component_index = component_index
        self.columns = columns
        self.columns_info = columns_info or {}

    def _get_numeric_columns(self) -> List[str]:
        """Get list of numeric columns based on column type information."""
        if not self.columns_info:
            # Fallback: return all columns if no type info available
            return self.columns

        numeric_types = {"int64", "float64", "int32", "float32", "number"}
        numeric_columns = []

        for col_name, col_info in self.columns_info.items():
            col_type = col_info.get("type", "").lower()
            if col_type in numeric_types or "int" in col_type or "float" in col_type:
                numeric_columns.append(col_name)

        return numeric_columns

    def build_parameter_input(
        self, param: ParameterDefinition, value: Any = None, disabled: bool = False
    ) -> Union[dmc.Select, dmc.MultiSelect, dmc.TextInput, dmc.Switch, html.Div]:
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
        # For hierarchical charts, add empty option for parents parameter
        options = [{"label": col, "value": col} for col in self.columns]

        # Add empty option for optional parameters in hierarchical charts
        if not param.required and param.name in ["parents"]:
            options.insert(0, {"label": "(None - Root level)", "value": ""})

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

    def _build_select_dropdown(
        self, param: ParameterDefinition, component_id: Dict, value: Any, disabled: bool
    ) -> dmc.Select:
        """Build dropdown for option selection."""
        options = [{"label": str(opt), "value": str(opt)} for opt in (param.options or [])]
        return dmc.Select(
            id=component_id,
            data=options,
            value=value,
            placeholder=f"Select {param.label.lower()}...",
            disabled=disabled,
            clearable=not param.required,
            searchable=True,
            size="md",  # Make dropdown larger
            comboboxProps={"withinPortal": False},  # Prevents dropdown from going behind modals
            style={"width": "100%", "minHeight": "40px"},  # Increase height
        )

    def _build_multi_select(
        self, param: ParameterDefinition, component_id: Dict, value: Any, disabled: bool
    ) -> Union[dmc.MultiSelect, html.Div]:
        """Build multi-select dropdown."""
        if param.name in ["hover_data", "custom_data"]:
            # Special case for data parameters - use columns
            options = [{"label": col, "value": col} for col in self.columns]
        elif param.name == "features":
            # Special case for UMAP features - use only numeric columns with Select All button
            return self._build_features_multi_select(param, component_id, value, disabled)
        else:
            options = [{"label": str(opt), "value": str(opt)} for opt in (param.options or [])]

        return dmc.MultiSelect(
            id=component_id,
            data=options,
            value=value or [],
            placeholder=f"Select {param.label.lower()}...",
            disabled=disabled,
            searchable=True,
            size="md",  # Make dropdown larger
            comboboxProps={"withinPortal": False},  # Prevents dropdown from going behind modals
            style={"width": "100%", "minHeight": "40px"},  # Increase height
        )

    def _build_features_multi_select(
        self, param: ParameterDefinition, component_id: Dict, value: Any, disabled: bool
    ) -> html.Div:
        """Build enhanced multi-select for features with Select All functionality."""
        numeric_columns = self._get_numeric_columns()
        options = [{"label": col, "value": col} for col in numeric_columns]

        select_all_id = {"type": f"select-all-{param.name}", "index": self.component_index}

        return html.Div(
            [
                dmc.Group(
                    [
                        dmc.MultiSelect(
                            id=component_id,
                            data=options,
                            value=value or [],
                            placeholder=f"Select {param.label.lower()}... ({len(numeric_columns)} numeric columns available)",
                            disabled=disabled,
                            searchable=True,
                            size="md",
                            comboboxProps={"withinPortal": False},
                            style={"flex": "1", "minHeight": "40px"},
                        ),
                        dmc.Button(
                            "Select All",
                            id=select_all_id,
                            variant="outline",
                            size="sm",
                            leftSection=DashIconify(icon="mdi:select-all", width=16),
                            disabled=disabled,
                            style={"minWidth": "100px"},
                        ),
                    ],
                    gap="xs",
                    style={"width": "100%"},
                ),
                # Information about selected features
                html.Div(
                    id={"type": f"features-info-{param.name}", "index": self.component_index},
                    style={"marginTop": "5px", "fontSize": "12px", "color": "gray"},
                ),
            ]
        )

    def _build_text_input(
        self, param: ParameterDefinition, component_id: Dict, value: Any, disabled: bool
    ) -> dmc.TextInput:
        """Build text input."""
        return dmc.TextInput(
            id=component_id,
            value=value or "",
            placeholder=param.label,
            disabled=disabled,
            style={"width": "100%"},
        )

    def _build_numeric_input(
        self, param: ParameterDefinition, component_id: Dict, value: Any, disabled: bool
    ) -> dmc.NumberInput:
        """Build numeric input."""
        step = 1 if param.type == ParameterType.INTEGER else 0.1

        return dmc.NumberInput(
            id=component_id,
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
    ) -> dmc.Checkbox:
        """Build boolean checkbox (using Checkbox instead of Switch for better compatibility)."""
        return dmc.Checkbox(
            id=component_id,
            checked=bool(value) if value is not None else False,
            disabled=disabled,
            label=param.label,
            size="md",
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
                dmc.Group(
                    [
                        dmc.Stack(
                            [
                                dmc.Text("Min", size="sm"),
                                dmc.NumberInput(
                                    id=min_id,
                                    value=min_val,
                                    placeholder="Min",
                                    disabled=disabled,
                                    size="sm",
                                    style={"width": "120px"},
                                ),
                            ],
                            gap="xs",
                        ),
                        dmc.Stack(
                            [
                                dmc.Text("Max", size="sm"),
                                dmc.NumberInput(
                                    id=max_id,
                                    value=max_val,
                                    placeholder="Max",
                                    disabled=disabled,
                                    size="sm",
                                    style={"width": "120px"},
                                ),
                            ],
                            gap="xs",
                        ),
                    ],
                    grow=True,
                )
            ]
        )

    def _build_color_picker(
        self, param: ParameterDefinition, component_id: Dict, value: Any, disabled: bool
    ) -> dmc.ColorInput:
        """Build color picker input."""
        return dmc.ColorInput(
            id=component_id,
            value=value or "#1f77b4",
            disabled=disabled,
            style={"width": "100%"},
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

            # Create label with tooltip and required indicator
            label_text = param.label
            if param.required:
                label_text += " *"

            # Create tooltip for parameter description if available
            if param.description:
                label_component = dmc.Tooltip(
                    label=param.description,
                    position="top",
                    multiline=True,
                    withArrow=True,
                    withinPortal=False,  # Prevent tooltip from being hidden behind modal
                    children=[
                        dmc.Text(
                            label_text,
                            size="sm",
                            fw="bold",
                            c="red" if param.required else "dark",
                            style={
                                "cursor": "help",
                                "textDecoration": "underline dotted"
                                if param.description
                                else "none",
                                "minWidth": "120px",
                                "display": "flex",
                                "alignItems": "center",
                            },
                        )
                    ],
                )
            else:
                label_component = dmc.Text(
                    label_text,
                    size="sm",
                    fw="bold",
                    c="red" if param.required else "dark",
                    style={
                        "minWidth": "120px",
                        "display": "flex",
                        "alignItems": "center",
                    },
                )

            # Create horizontal parameter row with label on left, input on right
            parameter_row = dmc.Group(
                [
                    html.Div(label_component, style={"width": "30%", "minWidth": "120px"}),
                    html.Div(input_component, style={"width": "70%", "flex": "1"}),
                ],
                gap="md",
                align="center",
                style={"width": "100%"},
            )

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
