"""Frontend components and callbacks for MultiQC dashboard integration.

This module provides Dash components and callbacks for displaying and interacting
with MultiQC quality control reports. It includes:

- Stepper button creation for component selection
- MultiQC component design and layout
- Interactive filtering and sample-based patching of plots
- Dashboard restoration with background rendering
- Theme-aware styling with dark/light mode support

The module integrates with pre-computed joins for efficient cross-table filtering
and supports real-time updates based on interactive component selections.
"""

import copy
from typing import Any, Optional

import dash
import dash_mantine_components as dmc
import polars as pl
from dash import MATCH, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.component_metadata import get_component_color, get_dmc_button_color, is_enabled
from depictio.dash.modules.figure_component.multiqc_vis import create_multiqc_plot
from depictio.dash.modules.multiqc_component.models import MultiQCDashboardComponent
from depictio.dash.modules.multiqc_component.utils import get_multiqc_reports_for_data_collection
from depictio.dash.utils import UNSELECTED_STYLE


def _create_error_figure(title: str, message: str, font_size: int = 16) -> dict:
    """Create a Plotly figure displaying an error message.

    Args:
        title: The title for the figure layout.
        message: The error message to display as an annotation.
        font_size: Font size for the error message.

    Returns:
        A Plotly figure dict with the error displayed as a centered annotation.
    """
    return {
        "data": [],
        "layout": {
            "title": title,
            "xaxis": {"visible": False},
            "yaxis": {"visible": False},
            "annotations": [
                {
                    "text": message,
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "showarrow": False,
                    "font": {"size": font_size, "color": "red"},
                }
            ],
        },
    }


def create_stepper_multiqc_button(n: int, disabled: Optional[bool] = None) -> tuple:
    """Create the stepper MultiQC button for component selection.

    Args:
        n: The index for the button, used in component IDs.
        disabled: Override enabled state. If None, uses metadata configuration.

    Returns:
        Tuple of (button, store) Dash components for the MultiQC option.
    """
    # Use metadata enabled field if disabled not explicitly provided
    if disabled is None:
        disabled = not is_enabled("multiqc")

    color = get_dmc_button_color("multiqc")
    hex_color = get_component_color("multiqc")

    # Use standard DashIconify icon like other components
    # Alternative: For MultiQC logo, uncomment the html.Img section below
    multiqc_icon = DashIconify(icon="mdi:chart-line", color=hex_color)

    # Uncomment this to use the actual MultiQC logo instead:
    # multiqc_icon = html.Img(
    #     src="/assets/images/logos/multiqc.png",
    #     style={
    #         "height": "24px",
    #         "width": "24px",
    #         "backgroundColor": "transparent",
    #         "objectFit": "contain",
    #     },
    # )

    button = dmc.Button(
        "MultiQC",
        id={
            "type": "btn-option",
            "index": n,
            "value": "MultiQC",
        },
        n_clicks=0,
        style={**UNSELECTED_STYLE, "fontSize": "26px"},
        size="xl",
        variant="outline",
        color=color,
        leftSection=multiqc_icon,
        disabled=disabled,
    )

    store = dcc.Store(
        id={
            "type": "store-btn-option",
            "index": n,
            "value": "MultiQC",
        },
        data=0,
        storage_type="memory",
    )

    return button, store


def design_multiqc(
    id: Any,
    workflow_id: Optional[str] = None,
    data_collection_id: Optional[str] = None,
    local_data: Optional[dict] = None,
    **kwargs: Any,
) -> dmc.Paper:
    """Design MultiQC component with orange styling.

    Creates the full MultiQC visualization component including header, status alert,
    control panel with module/plot/dataset selectors, plot container, and hidden
    stores for state management.

    Args:
        id: Component ID, can be a string or dict (from stepper context).
        workflow_id: Associated workflow identifier.
        data_collection_id: Associated data collection identifier.
        local_data: Local data containing access tokens and other config.
        **kwargs: Additional options including selected_module, selected_plot,
            and selected_dataset for initial state.

    Returns:
        DMC Paper component containing the complete MultiQC visualization.
    """

    # Extract string ID if id is a dictionary (from stepper context)
    if isinstance(id, dict):
        # If id is a button ID dict, extract the index value (preserves -tmp suffix for stepper)
        component_id = id.get("index", "multiqc-component")
    else:
        component_id = str(id)  # Ensure it's a string

    # Extract initial state if provided
    initial_module = kwargs.get("selected_module")
    initial_plot = kwargs.get("selected_plot")
    initial_dataset = kwargs.get("selected_dataset")

    # MultiQC component with orange theme
    multiqc_content = dmc.Paper(
        id=component_id,  # Add ID to the Paper component
        children=[
            # Header with title
            dmc.Group(
                [
                    dmc.ThemeIcon(
                        DashIconify(icon="mdi:chart-line"),
                        size="xl",
                        variant="light",
                        color="orange",
                    ),
                    dmc.Title("MultiQC Report", order=3, c="orange"),
                ],
                gap="md",
                mb="lg",
            ),
            # Status indicator
            dmc.Alert(
                children=[
                    dmc.Group(
                        [
                            dmc.ThemeIcon(
                                DashIconify(icon="mdi:chart-line"),
                                size="lg",
                                variant="light",
                                color="orange",
                            ),
                            dmc.Text(
                                "Loading MultiQC visualization...",
                                id={"type": "multiqc-status", "index": component_id},
                                fw="normal",
                            ),
                        ],
                        gap="sm",
                    )
                ],
                color="orange",
                variant="light",
                id={"type": "multiqc-alert", "index": component_id},
                mb="md",
            ),
            # Interactive controls and plot area
            dmc.Stack(
                [
                    # Control panel
                    dmc.Card(
                        [
                            dmc.Text("MultiQC Plot Controls", fw="bold", size="lg", mb="md"),
                            dmc.SimpleGrid(
                                [
                                    # Module selector
                                    dmc.Stack(
                                        [
                                            dmc.Text("Module", size="sm", fw="bold"),
                                            dmc.Select(
                                                id={
                                                    "type": "multiqc-module-select",
                                                    "index": component_id,
                                                },
                                                data=[],
                                                value=None,
                                                placeholder="Select module",
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                    # Plot selector
                                    dmc.Stack(
                                        [
                                            dmc.Text("Plot", size="sm", fw="bold"),
                                            dmc.Select(
                                                id={
                                                    "type": "multiqc-plot-select",
                                                    "index": component_id,
                                                },
                                                data=[],
                                                value=None,
                                                placeholder="Select plot",
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                    # Dataset selector (conditional)
                                    dmc.Stack(
                                        [
                                            dmc.Text("Dataset", size="sm", fw="bold"),
                                            dmc.Select(
                                                id={
                                                    "type": "multiqc-dataset-select",
                                                    "index": component_id,
                                                },
                                                data=[],
                                                value=None,
                                                placeholder="Select dataset",
                                                style={"display": "none"},  # Hidden by default
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                ],
                                cols=3,
                                spacing="md",
                            ),
                        ],
                        p="md",
                        withBorder=True,
                        mb="md",
                    ),
                    # Plot area
                    html.Div(
                        id={"type": "multiqc-plot-container", "index": component_id},
                        children=[
                            dmc.Center(
                                [
                                    dmc.Text(
                                        "Select a module and plot to view visualization", c="gray"
                                    )
                                ],
                                style={"height": "400px"},
                            )
                        ],
                        style={"height": "100%"},
                    ),
                ]
            ),
            # Hidden stores for component data
            dcc.Store(
                id={"type": "multiqc-store-workflow", "index": component_id},
                data=workflow_id,
            ),
            dcc.Store(
                id={"type": "multiqc-store-datacollection", "index": component_id},
                data=data_collection_id,
            ),
            dcc.Store(
                id={"type": "multiqc-store-local-data", "index": component_id},
                data=local_data,
            ),
            dcc.Store(
                id={"type": "multiqc-metadata-store", "index": component_id},
                data={},
            ),
            dcc.Store(
                id={"type": "multiqc-s3-store", "index": component_id},
                data=[],
            ),
            # CRITICAL: stored-metadata-component store for save functionality
            # Follow same pattern as card component for -tmp suffix handling
            dcc.Store(
                id={
                    "type": "stored-metadata-component",
                    "index": component_id,
                },  # Store ID includes -tmp
                data={
                    "index": component_id.replace("-tmp", "")
                    if component_id
                    else "unknown",  # Data index clean for btn-done matching
                    "component_type": "multiqc",  # Use lowercase for helpers mapping compatibility
                    "workflow_id": workflow_id,
                    "data_collection_id": data_collection_id,
                    "wf_id": workflow_id,
                    "dc_id": data_collection_id,
                    "project_id": kwargs.get("project_id"),  # For cross-DC link resolution
                    # Include initial selection state if provided
                    "selected_module": initial_module,
                    "selected_plot": initial_plot,
                    "selected_dataset": initial_dataset,
                },
            ),
        ],
        p="xl",
        withBorder=True,
        radius="md",
        style={
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "borderColor": "var(--mantine-color-orange-4)",
            "borderWidth": "2px",
        },
        w="100%",
        mih=500,
    )

    return multiqc_content


def design_multiqc_from_model(component: MultiQCDashboardComponent) -> dmc.Paper:
    """
    Design MultiQC component using a Pydantic model for type safety.

    Args:
        component: MultiQCDashboardComponent model with complete state

    Returns:
        DMC Paper component for MultiQC visualization
    """
    logger.info(f"Designing MultiQC component from model: {component.index}")
    logger.info(f"Component state: {component.state}")

    # Extract component data
    component_id = component.index
    workflow_id = component.workflow_id
    data_collection_id = component.data_collection_id
    state = component.state

    # Get initial values from state
    initial_module_value = state.selected_module
    initial_plot_value = state.selected_plot
    initial_dataset_value = state.selected_dataset

    logger.info(
        f"Initial values - Module: {initial_module_value}, "
        f"Plot: {initial_plot_value}, Dataset: {initial_dataset_value}"
    )

    # MultiQC component with orange theme
    multiqc_content = dmc.Paper(
        id=component_id,  # Add ID to the Paper component
        children=[
            # Header with title
            dmc.Group(
                [
                    dmc.ThemeIcon(
                        DashIconify(icon="mdi:chart-line"),
                        size="xl",
                        variant="light",
                        color="orange",
                    ),
                    dmc.Title("MultiQC Report", order=3, c="orange"),
                ],
                gap="md",
                mb="lg",
            ),
            # Status indicator
            dmc.Alert(
                children=[
                    dmc.Group(
                        [
                            dmc.ThemeIcon(
                                DashIconify(icon="mdi:chart-line"),
                                size="lg",
                                variant="light",
                                color="orange",
                            ),
                            dmc.Text(
                                "Loading MultiQC visualization...",
                                id={"type": "multiqc-status", "index": component_id},
                                fw="normal",
                            ),
                        ],
                        gap="sm",
                    )
                ],
                color="orange",
                variant="light",
                id={"type": "multiqc-alert", "index": component_id},
                mb="md",
            ),
            # Interactive controls and plot area
            dmc.Stack(
                [
                    # Control panel
                    dmc.Card(
                        [
                            dmc.Text("MultiQC Plot Controls", fw="bold", size="lg", mb="md"),
                            dmc.SimpleGrid(
                                [
                                    # Module selector
                                    dmc.Stack(
                                        [
                                            dmc.Text("Module", size="sm", fw="bold"),
                                            dmc.Select(
                                                id={
                                                    "type": "multiqc-module-select",
                                                    "index": component_id,
                                                },
                                                data=[],
                                                value=initial_module_value,
                                                placeholder="Select module",
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                    # Plot selector
                                    dmc.Stack(
                                        [
                                            dmc.Text("Plot", size="sm", fw="bold"),
                                            dmc.Select(
                                                id={
                                                    "type": "multiqc-plot-select",
                                                    "index": component_id,
                                                },
                                                data=[],
                                                value=initial_plot_value,
                                                placeholder="Select plot",
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                    # Dataset selector (conditional)
                                    dmc.Stack(
                                        [
                                            dmc.Text("Dataset", size="sm", fw="bold"),
                                            dmc.Select(
                                                id={
                                                    "type": "multiqc-dataset-select",
                                                    "index": component_id,
                                                },
                                                data=[],
                                                value=initial_dataset_value,
                                                placeholder="Select dataset",
                                                style={"display": "none"},  # Hidden by default
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                ],
                                cols=3,
                                spacing="md",
                            ),
                        ],
                        p="md",
                        withBorder=True,
                        mb="md",
                    ),
                    # Plot area
                    html.Div(
                        id={"type": "multiqc-plot-container", "index": component_id},
                        children=[
                            dmc.Center(
                                [
                                    dmc.Text(
                                        "Select a module and plot to view visualization", c="gray"
                                    )
                                ],
                                style={"height": "400px"},
                            )
                        ],
                        style={"height": "100%"},
                    ),
                ]
            ),
            # Hidden stores for component data
            dcc.Store(
                id={"type": "multiqc-store-workflow", "index": component_id},
                data=workflow_id,
            ),
            dcc.Store(
                id={"type": "multiqc-store-datacollection", "index": component_id},
                data=data_collection_id,
            ),
            dcc.Store(
                id={"type": "multiqc-store-local-data", "index": component_id},
                data={"access_token": component.access_token} if component.access_token else {},
            ),
            dcc.Store(
                id={"type": "multiqc-metadata-store", "index": component_id},
                data=state.metadata,
            ),
            dcc.Store(
                id={"type": "multiqc-s3-store", "index": component_id},
                data=state.s3_locations,
            ),
            dcc.Store(
                id={"type": "multiqc-trace-metadata", "index": component_id},
                data={},  # Will be populated by callbacks
            ),
            # CRITICAL: stored-metadata-component store for save functionality with rich metadata
            dcc.Store(
                id={"type": "stored-metadata-component", "index": component_id},
                data=component.to_stored_metadata(),
            ),
        ],
        p="xl",
        withBorder=True,
        radius="md",
        style={
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "borderColor": "var(--mantine-color-orange-4)",
            "borderWidth": "2px",
        },
        w="100%",
        mih=500,
    )

    return multiqc_content


def expand_canonical_samples_to_variants(
    canonical_samples: list[str], sample_mappings: dict[str, list[str]]
) -> list[str]:
    """Expand canonical sample IDs to all their MultiQC variants using stored mappings.

    Args:
        canonical_samples: List of canonical sample IDs from external metadata
            (e.g., ['SRR10070130']).
        sample_mappings: Dictionary mapping canonical IDs to variants
            (e.g., {'SRR10070130': ['SRR10070130', 'SRR10070130_1', ...]}).

    Returns:
        List of all sample variants to filter MultiQC plots.
    """
    if not sample_mappings:
        logger.warning("No sample mappings available - returning canonical samples as-is")
        return canonical_samples

    expanded_samples = []
    for canonical_id in canonical_samples:
        # Get all variants for this canonical ID
        variants = sample_mappings.get(canonical_id, [])

        if variants:
            expanded_samples.extend(variants)
            logger.debug(
                f"Expanded '{canonical_id}' to {len(variants)} variants: {variants[:3]}..."
            )
        else:
            # If no mapping found, include the canonical ID itself
            expanded_samples.append(canonical_id)
            logger.debug(f"No variants found for '{canonical_id}' - using as-is")

    logger.info(
        f"Expanded {len(canonical_samples)} canonical IDs to {len(expanded_samples)} MultiQC variants"
    )
    return expanded_samples


def _filter_date_column(
    df: pl.DataFrame, column_name: str, filter_values: list, comp_metadata: dict
) -> pl.DataFrame:
    """Apply date filtering to a Polars DataFrame column.

    Args:
        df: The DataFrame to filter.
        column_name: Name of the date column to filter.
        filter_values: List of date values to filter by.
        comp_metadata: Component metadata containing default_state.

    Returns:
        Filtered DataFrame.
    """
    from datetime import datetime

    # Check if this is the default range (no actual filtering needed)
    default_state = comp_metadata.get("default_state", {})
    default_range = default_state.get("default_range")

    if default_range and filter_values == default_range:
        logger.debug(
            f"Date filter '{column_name}' at default range {default_range} - "
            "skipping (not an active filter)"
        )
        return df

    # Try parsing filter values as Python date objects
    try:
        parsed_dates = [datetime.strptime(str(v), "%Y-%m-%d").date() for v in filter_values]
        df = df.filter(pl.col(column_name).is_in(parsed_dates))
        logger.debug(f"After filtering: {df.shape[0]} rows remaining (Date parsing)")
        return df
    except Exception as e:
        logger.warning(f"Failed to filter Date column '{column_name}' with date parsing: {e}")

    # Fallback to string casting with explicit date format
    try:
        string_values = [str(v) for v in filter_values]
        df = df.filter(pl.col(column_name).dt.strftime("%Y-%m-%d").is_in(string_values))
        logger.info(f"After filtering: {df.shape[0]} rows remaining (Date as formatted string)")
        return df
    except Exception as e2:
        logger.error(
            f"All Date filtering methods failed on '{column_name}': {e2}. Skipping filter."
        )
        return df


def _filter_range_column(
    df: pl.DataFrame, column_name: str, filter_values: list, comp_metadata: dict
) -> pl.DataFrame:
    """Apply range filtering to a Polars DataFrame column.

    Args:
        df: The DataFrame to filter.
        column_name: Name of the column to filter.
        filter_values: Two-element list [min, max] for range filtering.
        comp_metadata: Component metadata containing default_state.

    Returns:
        Filtered DataFrame.
    """
    default_state = comp_metadata.get("default_state", {})
    default_range = default_state.get("default_range")

    if default_range and filter_values == default_range:
        logger.debug(
            f"Range filter '{column_name}' at default range {default_range} - "
            "skipping (not an active filter)"
        )
        return df

    min_val, max_val = filter_values[0], filter_values[1]
    logger.debug(f"Applying range filter: {min_val} <= {column_name} <= {max_val}")

    try:
        df = df.filter((pl.col(column_name) >= min_val) & (pl.col(column_name) <= max_val))
        logger.info(f"After filtering: {df.shape[0]} rows remaining (range filter)")
    except Exception as e:
        logger.error(f"Range filtering failed on '{column_name}': {e}. Skipping filter.")

    return df


def _filter_discrete_column(
    df: pl.DataFrame, column_name: str, filter_values: list
) -> pl.DataFrame:
    """Apply discrete value filtering to a Polars DataFrame column.

    Args:
        df: The DataFrame to filter.
        column_name: Name of the column to filter.
        filter_values: List of values to match.

    Returns:
        Filtered DataFrame.
    """
    logger.debug(f"Applying discrete filter: {column_name} in {filter_values}")

    try:
        df = df.filter(df[column_name].is_in(filter_values))
        logger.info(f"After filtering: {df.shape[0]} rows remaining (discrete filter)")
        return df
    except Exception as e:
        logger.warning(f"Direct filtering failed on '{column_name}': {e}")

    # Fallback: try string casting for type safety
    try:
        string_values = [str(v) for v in filter_values]
        df = df.filter(df[column_name].cast(pl.String).is_in(string_values))
        logger.info(f"After filtering: {df.shape[0]} rows remaining (string casting fallback)")
        return df
    except Exception as e2:
        logger.error(f"All filtering methods failed on '{column_name}': {e2}. Skipping filter.")
        return df


def _is_range_filter(filter_values: Any) -> bool:
    """Check if filter values represent a range filter.

    Args:
        filter_values: The filter values to check.

    Returns:
        True if this is a two-element numeric list (range filter).
    """
    return (
        isinstance(filter_values, list)
        and len(filter_values) == 2
        and all(isinstance(v, (int, float)) for v in filter_values)
    )


def get_samples_from_metadata_filter(
    workflow_id: str,
    metadata_dc_id: str,
    join_column: str,
    interactive_components_dict: dict,
    token: str,
) -> list[str]:
    """Get sample names from filtered metadata table.

    Loads the metadata table and applies all interactive component filters
    to determine which samples should be displayed.

    Args:
        workflow_id: Workflow ID.
        metadata_dc_id: Metadata data collection ID.
        join_column: Column name containing sample identifiers (e.g., 'sample').
        interactive_components_dict: Filters to apply {component_index: {value, metadata}}.
        token: Auth token for data access.

    Returns:
        List of canonical sample names that match the filters (not expanded to variants).
    """
    from bson import ObjectId

    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    logger.debug(f"Loading metadata table {metadata_dc_id}")
    df = load_deltatable_lite(
        workflow_id=ObjectId(workflow_id),
        data_collection_id=ObjectId(metadata_dc_id),
        metadata=None,
        TOKEN=token,
    )

    if df is None or df.is_empty():
        logger.warning("Metadata table is empty")
        return []

    logger.debug(f"Loaded metadata table with columns: {df.columns}")
    logger.info(f"Metadata table shape: {df.shape}")

    # Apply filters from interactive components
    for comp_data in interactive_components_dict.values():
        comp_metadata = comp_data.get("metadata", {})
        column_name = comp_metadata.get("column_name")
        filter_values = comp_data.get("value", [])

        if not (column_name and filter_values and column_name in df.columns):
            continue

        logger.info(f"Filtering {column_name} = {filter_values}")
        column_dtype = df[column_name].dtype

        if column_dtype in (pl.Date, pl.Datetime):
            df = _filter_date_column(df, column_name, filter_values, comp_metadata)
        elif _is_range_filter(filter_values):
            df = _filter_range_column(df, column_name, filter_values, comp_metadata)
        else:
            df = _filter_discrete_column(df, column_name, filter_values)

    # Extract sample names from join column
    if join_column not in df.columns:
        logger.error(
            f"Join column '{join_column}' not found in metadata. Available columns: {df.columns}"
        )
        return []

    canonical_samples = df[join_column].unique().to_list()
    logger.info(
        f"Found {len(canonical_samples)} canonical samples after filtering: {canonical_samples}"
    )
    return canonical_samples


def create_sample_filter_patch(selected_samples, metadata=None):
    """
    Create Dash Patch operations to filter MultiQC figure by samples.

    This function generates patch operations without needing the original figure,
    based on the filtering logic for different plot types.

    Args:
        selected_samples: List of selected sample names for filtering
        metadata: Optional metadata dictionary with plot information

    Returns:
        Dash Patch object with visibility updates, or None if full figure needed (heatmaps)
    """
    from dash import Patch

    if not selected_samples:
        return None

    logger.debug(f"Creating sample filter patch for {len(selected_samples)} selected samples")

    # Create a patch that will update trace visibility
    # Note: We can't determine trace types without the figure, so we need to use
    # a callback pattern that has access to the figure state

    # For now, return a simple visibility patch that can be applied
    # The actual filtering logic needs access to figure structure
    patch = Patch()

    # Store selected samples in patch metadata for use by receiving callback
    # This is a marker that filtering should be applied
    patch.__dict__["_multiqc_filter_samples"] = selected_samples

    return patch


def _sample_matches_fuzzy(y_sample: str, selected_samples_set: set[str]) -> bool:
    """Check if a heatmap Y-axis sample matches any selected sample.

    Supports fuzzy matching for sample variants:
    - Direct match
    - y_sample is canonical and variants are selected (e.g., "SRR123" matches "SRR123_1")
    - y_sample is variant and canonical is selected (e.g., "SRR123_1" matches "SRR123")

    Args:
        y_sample: The sample name from the heatmap Y-axis.
        selected_samples_set: Set of selected sample names.

    Returns:
        True if the sample should be included based on fuzzy matching.
    """
    if y_sample in selected_samples_set:
        return True

    for selected in selected_samples_set:
        # y_sample is canonical, selected is variant
        if selected.startswith(y_sample + "_") or selected.startswith(y_sample + "-"):
            return True
        # y_sample is variant, selected is canonical
        if y_sample.startswith(selected + "_") or y_sample.startswith(selected + "-"):
            return True

    return False


def _get_filtered_indices_for_bar(
    sample_axis: list,
    value_axis: list,
    selected_samples: list[str],
) -> list[int]:
    """Get filtered indices for bar chart based on sample selection.

    Args:
        sample_axis: The axis containing sample names (X for vertical, Y for horizontal).
        value_axis: The corresponding value axis.
        selected_samples: List of selected sample names.

    Returns:
        List of indices to keep after filtering.
    """
    return [
        idx
        for idx, sample in enumerate(sample_axis)
        if sample in selected_samples
        and idx < len(value_axis)
        and str(value_axis[idx]).lower() != "nan"
        and value_axis[idx] is not None
    ]


def _patch_bar_trace(
    patched_fig: dict,
    trace_idx: int,
    original_x: list,
    original_y: list,
    orientation: str,
    selected_samples: list[str],
) -> None:
    """Patch a bar chart trace with filtered sample data.

    Args:
        patched_fig: The figure dict to patch (modified in place).
        trace_idx: Index of the trace to patch.
        original_x: Original X-axis data.
        original_y: Original Y-axis data.
        orientation: Bar orientation ('h' for horizontal, 'v' for vertical).
        selected_samples: List of selected sample names.
    """
    if orientation == "h":
        # Horizontal bars: samples in Y-axis
        if not (original_y and original_x):
            return
        filtered_indices = _get_filtered_indices_for_bar(original_y, original_x, selected_samples)
        if filtered_indices:
            new_y = [original_y[idx] for idx in filtered_indices]
            new_x = [original_x[idx] for idx in filtered_indices]
            patched_fig["data"][trace_idx]["y"] = (
                tuple(new_y) if isinstance(original_y, tuple) else new_y
            )
            patched_fig["data"][trace_idx]["x"] = (
                tuple(new_x) if isinstance(original_x, tuple) else new_x
            )
            patched_fig["data"][trace_idx]["visible"] = True
            logger.info(f"      Filtered horizontal bar chart: {len(new_y)} samples")
        else:
            patched_fig["data"][trace_idx]["visible"] = False
            logger.debug("      No valid data after filtering - hiding trace")
    else:
        # Vertical bars: samples in X-axis
        if not (original_x and original_y):
            return
        filtered_indices = _get_filtered_indices_for_bar(original_x, original_y, selected_samples)
        if filtered_indices:
            new_x = [original_x[idx] for idx in filtered_indices]
            new_y = [original_y[idx] for idx in filtered_indices]
            patched_fig["data"][trace_idx]["x"] = (
                tuple(new_x) if isinstance(original_x, tuple) else new_x
            )
            patched_fig["data"][trace_idx]["y"] = (
                tuple(new_y) if isinstance(original_y, tuple) else new_y
            )
            patched_fig["data"][trace_idx]["visible"] = True
            logger.info(f"      Filtered vertical bar chart: {len(new_x)} samples")
        else:
            patched_fig["data"][trace_idx]["visible"] = False
            logger.debug("      No valid data after filtering - hiding trace")


def _patch_heatmap_trace(
    fig: dict,
    trace_idx: int,
    original_x: list,
    original_y: list,
    original_z: list,
    selected_samples: list[str],
) -> Optional[dict]:
    """Patch a heatmap trace with filtered sample data.

    Args:
        fig: The original figure dict.
        trace_idx: Index of the trace to patch.
        original_x: Original X-axis data.
        original_y: Original Y-axis data.
        original_z: Original Z-axis data (2D array).
        selected_samples: List of selected sample names.

    Returns:
        A new figure dict with filtered heatmap, or None if no data matches.
    """
    if not (original_y and original_z):
        if original_y and not original_z:
            logger.error("      Heatmap has Y data but no Z data in trace metadata - cannot filter")
        return None

    logger.info(
        f"      DEBUG: selected_samples: {list(selected_samples)[:5]}... "
        f"(total: {len(selected_samples)})"
    )

    selected_samples_set = set(selected_samples)
    filtered_indices = [
        idx
        for idx, sample in enumerate(original_y)
        if _sample_matches_fuzzy(sample, selected_samples_set)
    ]

    logger.info(
        f"      DEBUG: Matched samples after fuzzy matching: "
        f"{len(filtered_indices)}/{len(original_y)}"
    )

    if not filtered_indices:
        logger.warning("      No valid data after filtering - hiding heatmap")
        return None

    # Build filtered figure
    full_fig = copy.deepcopy(fig)
    new_y = [original_y[idx] for idx in filtered_indices]
    new_z = [original_z[idx] for idx in filtered_indices]

    full_fig["data"][trace_idx]["y"] = tuple(new_y) if isinstance(original_y, tuple) else new_y
    full_fig["data"][trace_idx]["z"] = tuple(new_z) if isinstance(original_z, tuple) else new_z

    if original_x:
        full_fig["data"][trace_idx]["x"] = (
            tuple(original_x) if isinstance(original_x, tuple) else original_x
        )

    # Configure Y-axis for proper display
    if "layout" in full_fig and "yaxis" in full_fig["layout"]:
        full_fig["layout"]["yaxis"].pop("tickvals", None)
        full_fig["layout"]["yaxis"].pop("ticktext", None)
        full_fig["layout"]["yaxis"]["type"] = "category"

    logger.info(
        f"      Heatmap rebuilt from trace metadata: {len(new_y)} samples, {len(new_z)} Z-rows"
    )
    return full_fig


def _get_trace_data(trace: dict, original_traces: list, trace_idx: int) -> tuple:
    """Extract original trace data from metadata or current trace.

    Args:
        trace: Current trace dict.
        original_traces: List of original trace metadata dicts.
        trace_idx: Index of the trace.

    Returns:
        Tuple of (original_x, original_y, original_z, orientation).
    """
    if trace_idx < len(original_traces):
        trace_info = original_traces[trace_idx]
        original_x = trace_info.get("original_x", [])
        original_y = trace_info.get("original_y", [])
        original_z = trace_info.get("original_z", [])
        orientation = trace_info.get("orientation", "v")
        logger.debug(
            f"    Trace {trace_idx}: Using stored original data - "
            f"x_len={len(original_x)}, y_len={len(original_y)}, orientation={orientation}"
        )
    else:
        original_x = trace.get("x", [])
        original_y = trace.get("y", [])
        original_z = trace.get("z", [])
        orientation = trace.get("orientation", "v")
        logger.debug(f"    Trace {trace_idx}: Using current trace data (no stored metadata)")

    return original_x, original_y, original_z, orientation


def patch_multiqc_figures(
    figures: list[dict],
    selected_samples: list[str],
    metadata: Optional[dict] = None,
    trace_metadata: Optional[dict] = None,
) -> list[dict]:
    """Apply sample filtering to MultiQC figures based on interactive selections.

    Supports filtering bar charts, heatmaps, and scatter/line plots based on
    selected sample names.

    Args:
        figures: List of Plotly figure objects to patch.
        selected_samples: List of selected sample names for filtering.
        metadata: Optional metadata dictionary with plot information.
        trace_metadata: Original trace metadata with x, y, z arrays and orientation.

    Returns:
        List of patched figure objects.
    """
    if not figures or not selected_samples:
        return figures

    logger.info(f"Patching MultiQC figures with {len(selected_samples)} selected samples")
    patched_figures = []

    original_traces = []
    if trace_metadata and "original_data" in trace_metadata:
        original_traces = trace_metadata["original_data"]
        logger.debug(f"  Using stored trace metadata with {len(original_traces)} traces")

    for fig_idx, fig in enumerate(figures):
        logger.debug(f"Processing figure {fig_idx}")
        patched_fig = copy.deepcopy(fig)
        figure_replaced = False

        for i, trace in enumerate(patched_fig.get("data", [])):
            trace_type = trace.get("type", "").lower()
            trace_name = trace.get("name", "")
            logger.info(f"    Trace {i}: type='{trace_type}', name='{trace_name}'")

            original_x, original_y, original_z, orientation = _get_trace_data(
                trace, original_traces, i
            )

            if trace_type == "bar":
                _patch_bar_trace(
                    patched_fig, i, original_x, original_y, orientation, selected_samples
                )

            elif trace_type == "heatmap":
                logger.debug("      Processing heatmap - using full figure replacement")
                full_fig = _patch_heatmap_trace(
                    fig, i, original_x, original_y, original_z, selected_samples
                )
                if full_fig:
                    patched_figures.append(full_fig)
                    figure_replaced = True
                    break
                else:
                    patched_fig["data"][i]["visible"] = original_y and not original_z

            else:
                # Scatter, line, and other plot types
                trace_matches_selected = any(sample in trace_name for sample in selected_samples)
                patched_fig["data"][i]["visible"] = trace_matches_selected
                logger.info(
                    f"      Trace '{trace_name}': visible={trace_matches_selected} "
                    f"(matches selected samples: {trace_matches_selected})"
                )

        if not figure_replaced:
            patched_figures.append(patched_fig)

    logger.info(f"Returning {len(patched_figures)} patched figures")
    return patched_figures


def register_callbacks_multiqc_component(app):
    """Register callbacks for MultiQC component functionality."""

    @app.callback(
        Output({"type": "multiqc-store-workflow", "index": MATCH}, "data", allow_duplicate=True),
        Input({"type": "multiqc-refresh", "index": MATCH}, "n_clicks"),
        State({"type": "multiqc-store-workflow", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def refresh_multiqc_component(refresh_clicks, current_workflow_id):
        """Trigger a refresh of the MultiQC component by updating the store data."""
        if refresh_clicks and refresh_clicks > 0:
            # Trigger a refresh by updating the store (this will cause the main callback to fire)
            return current_workflow_id
        return dash.no_update

    # Callback to update stored metadata when user selections change using Pydantic models
    @app.callback(
        Output({"type": "stored-metadata-component", "index": MATCH}, "data", allow_duplicate=True),
        Input({"type": "multiqc-module-select", "index": MATCH}, "value"),
        Input({"type": "multiqc-plot-select", "index": MATCH}, "value"),
        Input({"type": "multiqc-dataset-select", "index": MATCH}, "value"),
        State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        State({"type": "multiqc-s3-store", "index": MATCH}, "data"),
        State({"type": "multiqc-metadata-store", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def update_stored_metadata(
        selected_module: Optional[str],
        selected_plot: Optional[str],
        selected_dataset: Optional[str],
        current_metadata: dict,
        s3_locations: list,
        metadata: dict,
    ) -> Any:
        """Update stored metadata with current MultiQC visualization state using Pydantic models."""
        if not current_metadata:
            return dash.no_update

        try:
            # Create component from current metadata
            component = MultiQCDashboardComponent.from_stored_metadata(current_metadata)

            # Update state with new selections
            component.state.selected_module = selected_module
            component.state.selected_plot = selected_plot
            component.state.selected_dataset = selected_dataset
            component.state.s3_locations = s3_locations or []
            component.state.metadata = metadata or {}

            # Convert back to storable format
            updated_metadata = component.to_stored_metadata()

            logger.info(
                f"Updated MultiQC metadata with selections: module={selected_module}, "
                f"plot={selected_plot}, dataset={selected_dataset}"
            )

            return updated_metadata

        except Exception as e:
            logger.error(f"Error updating MultiQC metadata with models: {e}")
            # Fallback to dictionary update
            updated_metadata = current_metadata.copy()
            updated_metadata.update(
                {
                    "selected_module": selected_module,
                    "selected_plot": selected_plot,
                    "selected_dataset": selected_dataset,
                    "s3_locations": s3_locations or [],
                    "metadata": metadata or {},
                }
            )
            return updated_metadata

    # Callback to populate module dropdown when metadata is loaded
    @app.callback(
        Output({"type": "multiqc-module-select", "index": MATCH}, "data"),
        Output({"type": "multiqc-module-select", "index": MATCH}, "value", allow_duplicate=True),
        Input({"type": "multiqc-metadata-store", "index": MATCH}, "data"),
        State({"type": "multiqc-module-select", "index": MATCH}, "value"),
        prevent_initial_call="initial_duplicate",
    )
    def populate_module_options(metadata, current_value):
        if not metadata or not metadata.get("modules"):
            return [], dash.no_update

        module_options = [{"value": m, "label": m.upper()} for m in metadata.get("modules", [])]

        # If there's already a value set (from restoration), keep it
        # Otherwise, select the first module
        if current_value and current_value in metadata.get("modules", []):
            return module_options, dash.no_update
        else:
            first_value = metadata.get("modules", [])[0] if metadata.get("modules") else None
            return module_options, first_value

    # Callback to update plot dropdown based on module selection
    @app.callback(
        Output({"type": "multiqc-plot-select", "index": MATCH}, "data"),
        Output({"type": "multiqc-plot-select", "index": MATCH}, "value", allow_duplicate=True),
        Input({"type": "multiqc-module-select", "index": MATCH}, "value"),
        State({"type": "multiqc-metadata-store", "index": MATCH}, "data"),
        State({"type": "multiqc-plot-select", "index": MATCH}, "value"),
        prevent_initial_call="initial_duplicate",
    )
    def update_plot_options(selected_module, metadata, current_plot_value):
        if not selected_module or not metadata:
            return [], dash.no_update

        plots_data = metadata.get("plots", {})
        available_plots = plots_data.get(selected_module, [])

        # Convert plot list to dropdown format
        plot_options = []
        available_plot_values = []
        for plot in available_plots:
            if isinstance(plot, dict):
                # Plot with sub-options (like "Per Sequence GC Content": ["Percentages", "Counts"])
                for plot_name in plot.keys():
                    plot_options.append({"value": plot_name, "label": plot_name})
                    available_plot_values.append(plot_name)
            else:
                # Simple plot name
                plot_options.append({"value": plot, "label": plot})
                available_plot_values.append(plot)

        # If there's already a value set (from restoration) and it's valid for this module, keep it
        # Otherwise, select the first plot
        if current_plot_value and current_plot_value in available_plot_values:
            return plot_options, dash.no_update
        else:
            first_value = plot_options[0]["value"] if plot_options else None
            return plot_options, first_value

    # Callback to update dataset dropdown based on plot selection
    @app.callback(
        Output({"type": "multiqc-dataset-select", "index": MATCH}, "data"),
        Output({"type": "multiqc-dataset-select", "index": MATCH}, "value", allow_duplicate=True),
        Output({"type": "multiqc-dataset-select", "index": MATCH}, "style"),
        Input({"type": "multiqc-plot-select", "index": MATCH}, "value"),
        State({"type": "multiqc-module-select", "index": MATCH}, "value"),
        State({"type": "multiqc-metadata-store", "index": MATCH}, "data"),
        State({"type": "multiqc-dataset-select", "index": MATCH}, "value"),
        prevent_initial_call="initial_duplicate",
    )
    def update_dataset_options(selected_plot, selected_module, metadata, current_dataset_value):
        if not selected_plot or not selected_module or not metadata:
            return [], dash.no_update, {"display": "none"}

        plots_data = metadata.get("plots", {})
        available_plots = plots_data.get(selected_module, [])

        # Find datasets for the selected plot
        datasets = []
        for plot in available_plots:
            if isinstance(plot, dict) and selected_plot in plot:
                datasets = plot[selected_plot]
                break

        if datasets:
            dataset_options = [{"value": d, "label": d} for d in datasets]
            # If there's already a dataset value set (from restoration) and it's valid, keep it
            # Otherwise, select the first dataset
            if current_dataset_value and current_dataset_value in datasets:
                return dataset_options, dash.no_update, {"display": "block"}
            else:
                return dataset_options, datasets[0], {"display": "block"}
        else:
            return [], dash.no_update, {"display": "none"}

    # Background callback to generate the actual plot (Celery-backed for multi-worker performance)
    @app.callback(
        Output({"type": "multiqc-plot-container", "index": MATCH}, "children"),
        Input({"type": "multiqc-module-select", "index": MATCH}, "value"),
        Input({"type": "multiqc-plot-select", "index": MATCH}, "value"),
        Input({"type": "multiqc-dataset-select", "index": MATCH}, "value"),
        State({"type": "multiqc-s3-store", "index": MATCH}, "data"),
        State("theme-store", "data"),
        # background=True,
    )
    def generate_multiqc_plot(
        selected_module, selected_plot, selected_dataset, s3_locations, theme_data
    ):
        if not selected_module or not selected_plot or not s3_locations:
            return dmc.Center(
                [dmc.Text("Select a module and plot to view visualization", c="gray")],
                style={"height": "400px"},
            )

        theme = "light"
        # Extract theme from theme_data
        if isinstance(theme_data, dict):
            theme = "dark" if theme_data.get("colorScheme") == "dark" else "light"
        elif isinstance(theme_data, str):
            theme = theme_data
        else:
            theme = "light"

        # Create the plot with theme (Celery worker will cache this automatically)
        try:
            fig = create_multiqc_plot(
                s3_locations=s3_locations,
                module=selected_module,
                plot=selected_plot,
                dataset_id=selected_dataset,
                theme=theme,
            )
        except ValueError as e:
            # Plot doesn't exist for this module (transition state when switching modules)
            logger.debug(f"Plot validation error (expected during module switch): {e}")
            return dmc.Center(
                [dmc.Text(f"Loading plots for {selected_module}...", c="gray")],
                style={"height": "400px"},
            )

        # Wrap with logo overlay for consistent sizing across all plots
        return html.Div(
            style={
                "position": "relative",
                "height": "100%",
                "width": "100%",
                "display": "flex",
                "flexDirection": "column",
            },
            children=[
                dcc.Graph(figure=fig, style={"flex": "1", "minHeight": "0"}),
                # MultiQC logo overlay - CSS positioned for consistent size
                html.Img(
                    src="/assets/images/logos/multiqc.png",
                    style={
                        "position": "absolute",
                        "top": "10px",
                        "right": "10px",
                        "width": "40px",
                        "height": "40px",
                        "opacity": "0.6",
                        "pointerEvents": "none",
                        "zIndex": "1000",
                    },
                    title="Generated with MultiQC",
                ),
            ],
        )

    @app.callback(
        Output({"type": "multiqc-metadata-store", "index": MATCH}, "data"),
        Output({"type": "multiqc-s3-store", "index": MATCH}, "data"),
        Output({"type": "multiqc-status", "index": MATCH}, "children"),
        Output({"type": "multiqc-alert", "index": MATCH}, "color"),
        Input({"type": "multiqc-store-workflow", "index": MATCH}, "data"),
        Input({"type": "multiqc-store-datacollection", "index": MATCH}, "data"),
        State({"type": "multiqc-store-local-data", "index": MATCH}, "data"),
        State({"type": "multiqc-metadata-store", "index": MATCH}, "data"),
        State({"type": "multiqc-s3-store", "index": MATCH}, "data"),
        prevent_initial_call=False,
    )
    def update_multiqc_component(
        workflow_id, data_collection_id, local_data, existing_metadata, existing_s3_locations
    ):
        """Update MultiQC component with actual data and visualizations."""
        # Get the component ID from the callback context

        logger.info(f"MultiQC callback triggered for data collection: {data_collection_id}")
        logger.info(
            f"Existing metadata: {bool(existing_metadata)}, Existing S3 locations: {len(existing_s3_locations) if existing_s3_locations else 0}"
        )

        # Check if we already have restored metadata and s3_locations
        # This happens when a dashboard is being restored from saved state
        if existing_metadata and existing_s3_locations:
            logger.info("Using existing restored MultiQC metadata and S3 locations")
            return (
                existing_metadata,  # Keep existing metadata
                existing_s3_locations,  # Keep existing s3 locations
                "MultiQC Interactive Dashboard (Restored)",  # status
                "green",  # alert color
            )

        # Get token and reports for fresh load
        TOKEN = local_data.get("access_token") if local_data else None
        if not TOKEN:
            logger.warning("No access token available for MultiQC component")
            return (
                existing_metadata or {},  # Fallback to existing or empty
                existing_s3_locations or [],  # Fallback to existing or empty
                "No access token available",  # status
                "yellow",  # alert color
            )

        reports = get_multiqc_reports_for_data_collection(data_collection_id, TOKEN)

        # Extract S3 locations and metadata
        s3_locations = []
        for report_response in reports:
            multiqc_report = report_response.get("report", {})
            s3_location = multiqc_report.get("s3_location")
            if s3_location:
                s3_locations.append(s3_location)

        metadata = reports[0].get("report", {}).get("metadata", {}) if reports else {}

        # If no reports were fetched but we have existing data, keep the existing data
        if not reports and (existing_metadata or existing_s3_locations):
            logger.info("No reports fetched from API, keeping existing data")
            return (
                existing_metadata or {},
                existing_s3_locations or [],
                "MultiQC Dashboard (Cached)",
                "orange",
            )

        # Return data for stores and status
        return (
            metadata,  # metadata store
            s3_locations,  # s3 store
            "MultiQC Interactive Dashboard",  # status
            "blue",  # alert color
        )

    # NOTE: Debug callback and patching callback removed - they are now in callbacks/core.py
    # The core.py version has proper metadata enrichment from interactive-stored-metadata stores

    # Callback to update MultiQC figures when theme changes (matches figure component pattern)
    @app.callback(
        Output({"type": "multiqc-graph", "index": MATCH}, "figure", allow_duplicate=True),
        Input("theme-store", "data"),
        prevent_initial_call=True,
    )
    def update_multiqc_theme(theme_data):
        """Update MultiQC figure theme using Patch - matches figure component pattern."""
        import plotly.io as pio
        from dash import Patch

        # Handle different theme_data formats
        if isinstance(theme_data, dict):
            is_dark = theme_data.get("colorScheme") == "dark"
        elif isinstance(theme_data, str):
            is_dark = theme_data == "dark"
        else:
            is_dark = False

        # Use mantine templates for consistency
        template_name = "mantine_dark" if is_dark else "mantine_light"
        template = pio.templates[template_name]

        patch = Patch()
        patch.layout.template = template

        return patch

    # NOTE: VIEW MODE rendering callback (render_multiqc_from_trigger) has been moved to
    # callbacks/core.py to ensure it's always registered via register_core_callbacks().
    # The callback handles:
    # - Input: multiqc-trigger
    # - Output: multiqc-graph (figure) + multiqc-trace-metadata (data)
