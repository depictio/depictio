"""
Centralized component metadata configuration for Depictio dashboard components.
This module provides consistent color schemes, icons, and other metadata across all components.

Available Functions:
- get_component_metadata(component_type) -> dict: Get full metadata dictionary
- get_component_color(component_type) -> str: Get component color
- get_component_icon(component_type) -> str: Get component icon
- get_component_display_name(component_type) -> str: Get display name
- get_component_build_function(component_type) -> callable: Get component build function
- get_component_dimensions(component_type) -> dict: Get component default dimensions
- get_build_functions() -> dict: Get all build functions dictionary
- get_component_dimensions_dict() -> dict: Get all component dimensions dictionary
- supports_edit(component_type) -> bool: Check if component supports editing
- supports_reset(component_type) -> bool: Check if component supports reset
- is_enabled(component_type) -> bool: Check if component is enabled
- get_skeleton_loader_color(component_type) -> str: Get skeleton loader color (alias for get_component_color)

Legacy Support Functions:
- get_component_type_from_display_name(display_name) -> str | None: Convert display name to component type
- get_component_metadata_by_display_name(display_name) -> dict: Get metadata using display name
"""

from typing import Literal

from depictio.dash.colors import colors

# Import build functions for centralized registration
from depictio.dash.modules.card_component.utils import build_card
from depictio.dash.modules.figure_component.utils import build_figure
from depictio.dash.modules.image_component.utils import build_image
from depictio.dash.modules.interactive_component.utils import build_interactive
from depictio.dash.modules.jbrowse_component.utils import build_jbrowse
from depictio.dash.modules.map_component.utils import build_map
from depictio.dash.modules.multiqc_component.utils import build_multiqc
from depictio.dash.modules.table_component.utils import build_table
from depictio.dash.modules.text_component.utils import build_text

# Component metadata dictionary - centralized configuration
# NOTE: Only Card & Interactive components are currently enabled for editing
# Other component types (Figure, Table, Text, JBrowse, MultiQC) are disabled
COMPONENT_METADATA = {
    "figure": {
        "icon": "mdi:graph-box",
        "display_name": "Figure",
        "description": "Interactive data visualizations",
        "color": colors["purple"],  # Purple #9966cc matches stepper grid
        "supports_edit": True,  # Phase 2A: Edit mode enabled (design UI, save, pre-populate)
        "supports_reset": False,  # Phase 1: No reset functionality yet
        "enabled": True,  # ENABLED: Phase 2A with edit mode support
        "build_function": build_figure,
        "default_dimensions": {"w": 20, "h": 16},  # Adjusted for 48-column grid with rowHeight=20
    },
    "card": {
        "icon": "formkit:number",
        "display_name": "Card",
        "description": "Statistical summary cards",
        "color": colors["teal"],  # Teal #45b8ac matches stepper grid
        "supports_edit": True,
        "supports_reset": False,
        "enabled": True,  # ENABLED: Card component available
        "build_function": build_card,
        "default_dimensions": {
            "w": 10,
            "h": 8,
        },  # Adjusted for 48-column grid with rowHeight=20 - compact cards
    },
    "interactive": {
        "icon": "bx:slider-alt",
        "display_name": "Interactive",
        "description": "Interactive data controls",
        "color": colors["green"],  # Green #8bc34a matches stepper grid
        "supports_edit": True,
        "supports_reset": False,
        "enabled": True,  # ENABLED: Interactive component available
        "build_function": build_interactive,
        "default_dimensions": {
            "w": 16,
            "h": 10,
        },  # Adjusted for 48-column grid with rowHeight=20 - wider interactive controls
    },
    "table": {
        "icon": "octicon:table-24",
        "display_name": "Table",
        "description": "Data tables and grids",
        "color": colors["blue"],  # Blue #6495ed matches stepper grid
        "supports_edit": False,  # Table edit/design functionality restored
        "supports_reset": False,
        "enabled": True,  # ENABLED: Table component with design/edit support
        "build_function": build_table,
        "default_dimensions": {
            "w": 24,
            "h": 20,
        },  # Adjusted for 48-column grid with rowHeight=20 - tables need substantial space
    },
    "jbrowse": {
        "icon": "material-symbols:table-rows-narrow-rounded",
        "display_name": "JBrowse",
        "description": "Genome browser visualization",
        "color": colors["orange"],
        "supports_edit": False,  # JBrowse doesn't have edit functionality
        "supports_reset": False,
        "enabled": False,  # DISABLED: Focus on Card & Interactive only
        "build_function": build_jbrowse,
        "default_dimensions": {
            "w": 24,
            "h": 16,
        },  # Adjusted for 48-column grid with rowHeight=20 - large genome browser
    },
    "text": {
        "icon": "mdi:text-box-edit",
        "display_name": "Text",
        "description": "Rich text editor for documentation and notes",
        "color": colors["pink"],
        "supports_edit": True,  # Text supports editing
        "supports_reset": True,  # Can clear/reset text content
        "enabled": False,  # DISABLED: Focus on Card & Interactive only
        "build_function": build_text,
        "default_dimensions": {
            "w": 10,
            "h": 8,
        },  # Adjusted for 48-column grid with rowHeight=20 - compact text area
    },
    "multiqc": {
        "icon": "mdi:chart-line",
        "display_name": "MultiQC",
        "description": "MultiQC quality control reports and visualizations",
        "color": colors["orange"],
        "supports_edit": True,  # MultiQC supports edit mode (module/plot/dataset selection)
        "supports_reset": False,
        "enabled": True,  # ENABLED: Phase 1 with view mode callbacks
        "build_function": build_multiqc,
        "default_dimensions": {
            "w": 24,
            "h": 24,
        },  # Adjusted for 48-column grid with rowHeight=20 - full-featured MultiQC reports
    },
    "map": {
        "icon": "mdi:map-marker-multiple",
        "display_name": "Map",
        "description": "Geospatial map visualization with markers",
        "color": colors["blue"],  # Blue #6495ED
        "supports_edit": True,
        "supports_reset": False,
        "enabled": True,
        "build_function": build_map,
        "default_dimensions": {"w": 24, "h": 20},
    },
    "image": {
        "icon": "mdi:image-area",  # Gallery-style icon for image data collections
        "display_name": "Image Gallery",
        "description": "Interactive image grid with modal viewer",
        "color": colors["pink"],  # Pink #e6779f matches stepper grid
        "supports_edit": True,
        "supports_reset": False,
        "enabled": True,  # ENABLED: Image gallery component
        "build_function": build_image,
        "default_dimensions": {
            "w": 24,
            "h": 20,
        },  # Adjusted for 48-column grid - gallery needs substantial space
    },
}

# ============================================================================
# DUAL-PANEL GRID LAYOUT DIMENSIONS
# ============================================================================
# Centralized dimensions for the current dual-panel dashboard layout system
# LEFT panel: 1 column grid, rowHeight=50
# RIGHT panel: 8 column grid, rowHeight=100
#
# To adjust component sizes, modify these values:
# - w: width in grid columns
# - h: height in grid units (multiplied by rowHeight to get pixels)
# ============================================================================

DUAL_PANEL_DIMENSIONS = {
    # LEFT PANEL: Interactive components (1-column grid, rowHeight=50)
    "interactive": {
        "w": 1,  # Always 1 (single column grid)
        "h": 2,  # 3 × 50px = 150px - comfortable height for controls
    },
    # RIGHT PANEL: Cards and other components (8-column grid, rowHeight=100)
    "card": {
        "w": 2,  # 2/8 columns = 25% width (4 cards per row)
        "h": 2,  # 3 × 100px = 300px - reasonable card height
    },
    "figure": {
        "w": 4,  # 4/8 columns = 50% width (2 figures per row)
        "h": 4,  # 4 × 100px = 400px
    },
    "table": {
        "w": 8,  # 8/8 columns = 100% width (full row)
        "h": 6,  # 6 × 100px = 600px
    },
    "map": {
        "w": 8,  # 8/8 columns = 100% width (full row for map)
        "h": 6,  # 6 × 100px = 600px
    },
    "image": {
        "w": 8,  # 8/8 columns = 100% width (full row for image gallery)
        "h": 7,  # 7 × 100px = 700px (allows multiple rows with scrolling)
    },
}


def get_dual_panel_dimensions(component_type: str) -> dict:
    """
    Get grid dimensions for a component type in the dual-panel layout.

    Args:
        component_type: Component type ('interactive', 'card', 'figure', 'table').

    Returns:
        Dictionary with 'w' (width) and 'h' (height) in grid units.
        Defaults to card dimensions if component type not found.

    Example:
        >>> get_dual_panel_dimensions('card')
        {'w': 2, 'h': 3}
    """
    return DUAL_PANEL_DIMENSIONS.get(
        component_type,
        {"w": 2, "h": 3},  # Default: card dimensions
    )


def get_component_metadata(component_type: str) -> dict:
    """
    Get metadata for a specific component type.

    Args:
        component_type: The type of component ('figure', 'card', 'interactive', etc.).

    Returns:
        Component metadata dictionary containing color, icon, display_name,
        description, supports_edit, supports_reset, and enabled flags.
        Returns default values if component type not found.
    """
    return COMPONENT_METADATA.get(
        component_type,
        {
            "color": "gray",
            "icon": "mdi:help-circle",
            "display_name": "Unknown",
            "description": "Unknown component type",
            "supports_edit": False,
            "supports_reset": False,
            "enabled": True,
        },
    )


def get_component_color(component_type: str) -> str:
    """
    Get the primary color for a component type.

    Args:
        component_type: The type of component.

    Returns:
        Color name or hex value for the component.
    """
    metadata = get_component_metadata(component_type)
    return metadata["color"]


def get_component_icon(component_type: str) -> str:
    """
    Get the icon for a component type.

    Args:
        component_type: The type of component.

    Returns:
        Icon name/identifier (e.g., 'mdi:graph-box').
    """
    metadata = get_component_metadata(component_type)
    return metadata["icon"]


def get_component_display_name(component_type: str) -> str:
    """
    Get the display name for a component type.

    Args:
        component_type: The type of component.

    Returns:
        Human-readable display name (e.g., 'Figure', 'Card').
    """
    metadata = get_component_metadata(component_type)
    return metadata["display_name"]


def is_enabled(component_type: str) -> bool:
    """
    Check if a component type is enabled.

    Args:
        component_type: The type of component.

    Returns:
        True if component is enabled for use, False otherwise.
        Defaults to True if not specified in metadata.
    """
    metadata = get_component_metadata(component_type)
    return metadata.get("enabled", True)


def supports_edit(component_type: str) -> bool:
    """
    Check if a component type supports editing.

    Args:
        component_type: The type of component.

    Returns:
        True if component supports edit mode, False otherwise.
    """
    metadata = get_component_metadata(component_type)
    return metadata.get("supports_edit", False)


def supports_reset(component_type: str) -> bool:
    """
    Check if a component type supports reset functionality.

    Args:
        component_type: The type of component.

    Returns:
        True if component supports reset, False otherwise.
    """
    metadata = get_component_metadata(component_type)
    return metadata.get("supports_reset", False)


def get_component_dimensions(component_type: str) -> dict:
    """
    Get default grid dimensions for a component type.

    Args:
        component_type: The type of component.

    Returns:
        Dictionary with 'w' (width) and 'h' (height) in grid units.
    """
    metadata = get_component_metadata(component_type)
    return metadata.get("default_dimensions", {"w": 20, "h": 16})


def get_component_build_function(component_type: str):
    """
    Get the build function for a component type.

    Args:
        component_type: The type of component.

    Returns:
        Callable build function for the component, or None if not found.
    """
    metadata = get_component_metadata(component_type)
    return metadata.get("build_function")


def get_skeleton_loader_color(component_type: str) -> str:
    """
    Get the skeleton loader color for a component type.

    Alias for get_component_color, used for loading state visual feedback.

    Args:
        component_type: The type of component.

    Returns:
        Color name or hex value for the skeleton loader.
    """
    return get_component_color(component_type)


def get_build_functions() -> dict:
    """
    Get a dictionary mapping component types to their build functions.

    Returns build functions wrapped with logging to track executions and
    detect double-rendering issues. Includes a special '_reset_counts'
    function to clear counters between dashboard loads.

    Returns:
        Dictionary with component types as keys and wrapped build functions
        as values. Also includes '_reset_counts' key with the reset function.
    """
    import functools

    def wrap_build_function(component_type, original_func):
        """Wrapper for build function executions"""

        @functools.wraps(original_func)
        def wrapper(**kwargs):
            return original_func(**kwargs)

        return wrapper

    # Wrap each build function
    wrapped_functions = {
        component_type: wrap_build_function(component_type, metadata["build_function"])
        for component_type, metadata in COMPONENT_METADATA.items()
        if "build_function" in metadata
    }

    return wrapped_functions


def get_async_build_functions() -> dict:
    """
    Get build functions dictionary (deprecated async version).

    Deprecated:
        Use get_build_functions() instead. Async functionality has been disabled.
        This function now returns the same sync functions as get_build_functions().

    Returns:
        Dictionary with component types as keys and sync build functions as values.
    """
    # Return sync functions instead of async to disable async functionality
    return get_build_functions()


def get_component_dimensions_dict() -> dict:
    """
    Get a dictionary mapping all component types to their default dimensions.

    Provides backward compatibility for the old component_dimensions dictionary
    format used in the draggable layout system.

    Returns:
        Dictionary with component types as keys and dimension dicts as values.
        Each dimension dict contains 'w' (width) and 'h' (height) in grid units.
    """
    return {
        component_type: metadata.get("default_dimensions", {"w": 20, "h": 16})
        for component_type, metadata in COMPONENT_METADATA.items()
    }


# Display name to component type mapping for legacy compatibility
DISPLAY_NAME_TO_TYPE_MAPPING = {
    "Card": "card",
    "Figure": "figure",
    "Interactive": "interactive",
    "Table": "table",
    "JBrowse2": "jbrowse",
    "JBrowse": "jbrowse",  # Alternative name
    "Text": "text",
    "MultiQC": "multiqc",
    "Image": "image",
    "Image Gallery": "image",  # Alternative name
    "Map": "map",
    "None": None,  # Default case
}


def get_component_type_from_display_name(display_name: str) -> str | None:
    """
    Convert a display name to its internal component type.

    Args:
        display_name: Human-readable display name ('Card', 'Figure', etc.).

    Returns:
        Internal component type string, or None if not found.

    Example:
        >>> get_component_type_from_display_name('Card')
        'card'
    """
    return DISPLAY_NAME_TO_TYPE_MAPPING.get(display_name)


def get_component_metadata_by_display_name(display_name: str) -> dict:
    """
    Get metadata for a component using its display name.

    Provides backward compatibility for code that uses display names like
    'Card', 'Figure', etc. instead of internal component types.

    Args:
        display_name: The display name of the component ('Card', 'Figure', etc.).

    Returns:
        Dictionary with 'color' and 'icon' keys for the component.
        Returns default gray color and circle icon for unknown display names.
    """
    component_type = DISPLAY_NAME_TO_TYPE_MAPPING.get(display_name)
    if component_type:
        return {
            "color": get_component_color(component_type),
            "icon": get_component_icon(component_type),
        }
    return {"color": "gray", "icon": "ph:circle"}


def get_dmc_button_color(
    component_type: str,
) -> Literal[
    "dark",
    "gray",
    "red",
    "pink",
    "grape",
    "violet",
    "indigo",
    "blue",
    "cyan",
    "green",
    "lime",
    "yellow",
    "orange",
    "teal",
]:
    """
    Get a valid DMC Button color for a component type.

    Maps hex color values from component metadata to valid DMC Button color
    literals. This is necessary because DMC buttons require specific color
    names rather than hex values.

    Args:
        component_type: The type of component.

    Returns:
        Valid DMC Button color literal. Defaults to 'gray' if no mapping found.
    """
    metadata_color = get_component_color(component_type)

    # Map component colors (hex values) to valid DMC Button colors
    color_mapping = {
        # Direct DMC color name mappings
        "grape": "grape",
        "blue": "blue",
        "green": "green",
        "orange": "orange",
        "red": "red",
        "violet": "violet",
        "indigo": "indigo",
        "cyan": "cyan",
        "pink": "pink",
        "yellow": "yellow",
        "lime": "lime",
        "teal": "teal",
        "gray": "gray",
        "dark": "dark",
        # Hex value mappings from colors.py (case-insensitive)
        "#9966CC": "violet",  # purple (Figure component)
        "#9966cc": "violet",  # purple (lowercase)
        "#7A5DC7": "violet",  # violet
        "#6495ED": "blue",  # blue (Table component)
        "#6495ed": "blue",  # blue (lowercase)
        "#45B8AC": "teal",  # teal (Card component)
        "#45b8ac": "teal",  # teal (lowercase)
        "#8BC34A": "green",  # green (Interactive component)
        "#8bc34a": "green",  # green (lowercase)
        "#F9CB40": "yellow",  # yellow
        "#F68B33": "orange",  # orange
        "#E6779F": "pink",  # pink (Image component)
        "#e6779f": "pink",  # pink (lowercase)
        "#E53935": "red",  # red
        "#000000": "dark",  # black
        "#B0BEC5": "gray",  # grey
    }

    return color_mapping.get(metadata_color, "gray")
