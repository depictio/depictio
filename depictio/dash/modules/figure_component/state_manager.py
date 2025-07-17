"""
State management for figure components.

This module provides robust state management for figure components,
replacing the fragile nested dictionary approach with type-safe operations.
"""

from typing import Any, Dict, Literal, Optional

from .definitions import get_available_visualizations, get_visualization_definition
from .models import FigureComponentState


class FigureStateManager:
    """Manages state for figure components in a type-safe way."""

    def __init__(self):
        """Initialize the state manager."""
        self._states: Dict[str, FigureComponentState] = {}

    def get_state(self, component_id: str) -> Optional[FigureComponentState]:
        """Get state for a component.

        Args:
            component_id: Component identifier

        Returns:
            Component state or None if not found
        """
        return self._states.get(component_id)

    def create_state(
        self,
        component_id: str,
        visualization_type: str = "scatter",
        data_collection_id: str = "",
        workflow_id: str = "",
        theme: str = "light",
    ) -> FigureComponentState:
        """Create new state for a component.

        Args:
            component_id: Component identifier
            visualization_type: Initial visualization type
            data_collection_id: Data collection ID
            workflow_id: Workflow ID
            theme: Theme setting

        Returns:
            New component state
        """
        # Ensure theme is a valid literal
        valid_theme: Literal["light", "dark"] = "light" if theme not in ["light", "dark"] else theme  # type: ignore

        state = FigureComponentState(
            component_id=component_id,
            visualization_type=visualization_type,
            data_collection_id=data_collection_id,
            workflow_id=workflow_id,
            theme=valid_theme,
        )
        self._states[component_id] = state
        return state

    def update_state(self, component_id: str, **kwargs) -> Optional[FigureComponentState]:
        """Update state for a component.

        Args:
            component_id: Component identifier
            **kwargs: State updates

        Returns:
            Updated state or None if not found
        """
        if component_id not in self._states:
            return None

        state = self._states[component_id]
        for key, value in kwargs.items():
            if hasattr(state, key):
                setattr(state, key, value)

        return state

    def set_parameter(self, component_id: str, param_name: str, value: Any) -> bool:
        """Set parameter value for a component.

        Args:
            component_id: Component identifier
            param_name: Parameter name
            value: Parameter value

        Returns:
            True if successful, False otherwise
        """
        if component_id not in self._states:
            return False

        self._states[component_id].set_parameter_value(param_name, value)
        return True

    def get_parameter(self, component_id: str, param_name: str, default: Any = None) -> Any:
        """Get parameter value for a component.

        Args:
            component_id: Component identifier
            param_name: Parameter name
            default: Default value if not found

        Returns:
            Parameter value or default
        """
        if component_id not in self._states:
            return default

        return self._states[component_id].get_parameter_value(param_name, default)

    def clear_parameters(self, component_id: str) -> bool:
        """Clear all parameters for a component.

        Args:
            component_id: Component identifier

        Returns:
            True if successful, False otherwise
        """
        if component_id not in self._states:
            return False

        self._states[component_id].clear_parameters()
        return True

    def get_visualization_parameters(self, component_id: str) -> Dict[str, Any]:
        """Get all parameters for a component's current visualization.

        Args:
            component_id: Component identifier

        Returns:
            Dictionary of parameter values
        """
        if component_id not in self._states:
            return {}

        state = self._states[component_id]

        try:
            viz_def = get_visualization_definition(state.visualization_type)
            result = {}

            for param in viz_def.parameters:
                value = state.get_parameter_value(param.name)
                if value is not None:
                    result[param.name] = value

            return result

        except Exception as e:
            # Defensive handling: ensure parameters is a dict before calling copy()
            if isinstance(state.parameters, dict):
                return state.parameters.copy()
            else:
                # If parameters is not a dict (e.g., accidentally set to string), return empty dict
                # Log this issue for debugging
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(
                    f"State parameters for component {component_id} is not a dict: "
                    f"type={type(state.parameters)}, value={state.parameters}. "
                    f"Original error: {e}"
                )
                return {}

    def validate_visualization_change(self, component_id: str, new_visu_type: str) -> bool:
        """Validate if visualization type change is allowed.

        Args:
            component_id: Component identifier
            new_visu_type: New visualization type

        Returns:
            True if change is valid, False otherwise
        """
        available_names = [viz.name for viz in get_available_visualizations()]
        if new_visu_type not in available_names:
            return False

        return True

    def change_visualization_type(self, component_id: str, new_visu_type: str) -> bool:
        """Change visualization type for a component.

        Args:
            component_id: Component identifier
            new_visu_type: New visualization type

        Returns:
            True if successful, False otherwise
        """
        if not self.validate_visualization_change(component_id, new_visu_type):
            return False

        if component_id not in self._states:
            return False

        state = self._states[component_id]
        old_visu_type = state.visualization_type

        # Update visualization type
        state.visualization_type = new_visu_type

        # Handle parameter migration if needed
        if old_visu_type != new_visu_type:
            self._migrate_parameters(state, old_visu_type, new_visu_type)

        return True

    def _migrate_parameters(self, state: FigureComponentState, old_type: str, new_type: str):
        """Migrate parameters when changing visualization types.

        Args:
            state: Component state
            old_type: Previous visualization type
            new_type: New visualization type
        """
        try:
            old_viz = get_visualization_definition(old_type)
            new_viz = get_visualization_definition(new_type)

            # Get common parameters between old and new visualization
            old_params = {p.name for p in old_viz.parameters}
            new_params = {p.name for p in new_viz.parameters}
            common_params = old_params.intersection(new_params)

            # Define common parameters that should be preserved across all visualizations
            always_preserve_params = {
                "title",
                "width",
                "height",
                "template",
                "opacity",
                "hover_name",
                "hover_data",
                "custom_data",
                "labels",
                "color_discrete_sequence",
                "color_continuous_scale",
                "log_x",
                "log_y",
                "range_x",
                "range_y",
                "category_orders",
                "color_discrete_map",
                "animation_frame",
                "animation_group",
                "facet_row",
                "facet_col",
                "facet_col_wrap",
            }

            # Keep parameters that are in common between visualizations OR are always preserved
            migrated_params = {
                k: v
                for k, v in state.parameters.items()
                if k in common_params or k in always_preserve_params
            }

            state.parameters = migrated_params

        except Exception:
            # If migration fails, clear all parameters
            state.clear_parameters()

    def extract_parameter_values(self, component_children: Any) -> Dict[str, Any]:
        """Extract parameter values from component children structure.

        This method provides a robust way to extract values from Dash components
        without relying on fragile nested dictionary access.

        Args:
            component_children: Dash component children structure

        Returns:
            Dictionary of parameter values
        """
        parameters = {}

        if not component_children:
            return parameters

        try:
            # Handle the new accordion structure
            if isinstance(component_children, dict) and "props" in component_children:
                parameters = self._extract_from_accordion(component_children)
            elif isinstance(component_children, list):
                # Handle list of components
                for child in component_children:
                    if isinstance(child, dict):
                        child_params = self._extract_from_accordion(child)
                        parameters.update(child_params)

        except Exception as e:
            # Log error but don't fail completely
            from depictio.api.v1.configs.logging_init import logger

            logger.warning(f"Failed to extract parameter values: {e}")

        return parameters

    def _extract_from_accordion(self, accordion_data: Dict) -> Dict[str, Any]:
        """Extract parameters from accordion structure.

        Args:
            accordion_data: Accordion component data

        Returns:
            Dictionary of parameter values
        """
        parameters = {}

        def find_parameter_inputs(data):
            """Recursively find parameter inputs in component structure."""
            if isinstance(data, dict):
                # Check if this is a parameter input
                if "id" in data and isinstance(data["id"], dict):
                    input_id = data["id"]
                    if "type" in input_id and input_id["type"].startswith("param-"):
                        param_name = input_id["type"].replace("param-", "")
                        if "value" in data:
                            parameters[param_name] = data["value"]
                        elif "checked" in data:  # For boolean switches
                            parameters[param_name] = data["checked"]

                # Recursively search children
                for value in data.values():
                    if isinstance(value, (dict, list)):
                        find_parameter_inputs(value)

            elif isinstance(data, list):
                for item in data:
                    find_parameter_inputs(item)

        find_parameter_inputs(accordion_data)
        return parameters


# Global state manager instance
state_manager = FigureStateManager()
