import copy
from typing import Any, Optional

import dash
import dash_mantine_components as dmc
from dash import MATCH, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import return_joins_dict
from depictio.dash.component_metadata import get_component_color, get_dmc_button_color, is_enabled
from depictio.dash.modules.figure_component.multiqc_vis import create_multiqc_plot
from depictio.dash.modules.multiqc_component.models import MultiQCDashboardComponent
from depictio.dash.modules.multiqc_component.utils import get_multiqc_reports_for_data_collection
from depictio.dash.utils import UNSELECTED_STYLE


def create_stepper_multiqc_button(n, disabled=None):
    """
    Create the stepper MultiQC button
    Args:
        n (_type_): The index for the button
        disabled (bool, optional): Override enabled state. If None, uses metadata.
    Returns:
        tuple: (button, store) components
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


def design_multiqc(id, workflow_id=None, data_collection_id=None, local_data=None, **kwargs):
    """
    Design MultiQC component with orange styling.
    """
    logger.info(f"Designing MultiQC component with id: {id}")
    logger.info(f"Workflow ID: {workflow_id}, Data Collection ID: {data_collection_id}")

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
    logger.info(
        f"Initial state - Module: {initial_module}, Plot: {initial_plot}, Dataset: {initial_dataset}"
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


def expand_canonical_samples_to_variants(canonical_samples, sample_mappings):
    """
    Expand canonical sample IDs to all their MultiQC variants using stored mappings.

    Args:
        canonical_samples: List of canonical sample IDs from external metadata (e.g., ['SRR10070130'])
        sample_mappings: Dictionary mapping canonical IDs to variants
                        (e.g., {'SRR10070130': ['SRR10070130', 'SRR10070130_1', ...]})

    Returns:
        List of all sample variants to filter MultiQC plots
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


def get_samples_from_metadata_filter(
    workflow_id, metadata_dc_id, join_column, interactive_components_dict, token
):
    """
    Get sample names from filtered metadata table.

    Args:
        workflow_id: Workflow ID
        metadata_dc_id: Metadata data collection ID
        join_column: Column name containing sample identifiers (e.g., 'sample')
        interactive_components_dict: Filters to apply {component_index: {value, metadata}}
        token: Auth token

    Returns:
        List of canonical sample names that match the filters (not expanded to variants)
    """
    from bson import ObjectId

    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    # Load metadata table
    logger.info(f"Loading metadata table {metadata_dc_id}")
    df = load_deltatable_lite(
        workflow_id=ObjectId(workflow_id),
        data_collection_id=ObjectId(metadata_dc_id),
        metadata=None,
        TOKEN=token,
    )

    if df is None or df.is_empty():
        logger.warning("Metadata table is empty")
        return []

    logger.info(f"Loaded metadata table with columns: {df.columns}")
    logger.info(f"Metadata table shape: {df.shape}")

    # Apply filters from interactive components
    for comp_data in interactive_components_dict.values():
        comp_metadata = comp_data.get("metadata", {})
        column_name = comp_metadata.get("column_name")
        filter_values = comp_data.get("value", [])

        if column_name and filter_values and column_name in df.columns:
            logger.info(f"Filtering {column_name} = {filter_values}")
            df = df.filter(df[column_name].is_in(filter_values))
            logger.info(f"After filtering: {df.shape[0]} rows remaining")

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

    logger.info(f"Creating sample filter patch for {len(selected_samples)} selected samples")

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


def patch_multiqc_figures(figures, selected_samples, metadata=None, trace_metadata=None):
    """
    Apply sample filtering to MultiQC figures based on interactive selections.

    Args:
        figures: List of Plotly figure objects to patch
        selected_samples: List of selected sample names for filtering
        metadata: Optional metadata dictionary with plot information
        trace_metadata: Original trace metadata with x, y, z arrays and orientation

    Returns:
        List of patched figure objects
    """
    if not figures or not selected_samples:
        return figures

    logger.info(f"Patching MultiQC figures with {len(selected_samples)} selected samples")
    patched_figures = []

    for fig_idx, fig in enumerate(figures):
        logger.info(f"Processing figure {fig_idx}")
        patched_fig = copy.deepcopy(fig)
        figure_replaced = False

        # Get all samples from metadata if available
        all_samples = metadata.get("samples", []) if metadata else []
        if not all_samples:
            # Fallback: try to extract samples from figure data
            all_samples = []
            for trace in fig.get("data", []):
                if "x" in trace and isinstance(trace["x"], (list, tuple)):
                    all_samples.extend(trace["x"])
                if "y" in trace and isinstance(trace["y"], (list, tuple)):
                    all_samples.extend(trace["y"])
            all_samples = list(set(all_samples))

        logger.info(f"  Figure has {len(all_samples)} total samples")
        logger.info(f"  Selected samples: {selected_samples}")

        # Get original trace data from metadata (critical for proper patching)
        original_traces = []
        if trace_metadata and "original_data" in trace_metadata:
            original_traces = trace_metadata["original_data"]
            logger.debug(f"  Using stored trace metadata with {len(original_traces)} traces")

        for i, trace in enumerate(patched_fig.get("data", [])):
            trace_type = trace.get("type", "").lower()
            trace_name = trace.get("name", "")

            # Get original data from trace metadata if available, otherwise use current trace
            if i < len(original_traces):
                trace_info = original_traces[i]
                original_x = trace_info.get("original_x", [])
                original_y = trace_info.get("original_y", [])
                original_z = trace_info.get("original_z", [])
                orientation = trace_info.get("orientation", "v")
                logger.debug(
                    f"    Trace {i}: Using stored original data - "
                    f"x_len={len(original_x)}, y_len={len(original_y)}, orientation={orientation}"
                )
            else:
                # Fallback to current trace data
                original_x = trace.get("x", [])
                original_y = trace.get("y", [])
                original_z = trace.get("z", [])
                orientation = trace.get("orientation", "v")
                logger.debug(f"    Trace {i}: Using current trace data (no stored metadata)")

            logger.info(f"    Trace {i}: type='{trace_type}', name='{trace_name}'")

            # Method 1: Handle bar charts - check orientation to determine sample axis
            if trace_type == "bar":
                logger.debug(f"      Processing bar plot with orientation '{orientation}'")
                if orientation == "h":
                    # Horizontal bars: samples are in Y-axis
                    if original_y and original_x:
                        # Filter from original data based on selected samples AND valid X values
                        filtered_indices = [
                            idx
                            for idx, sample in enumerate(original_y)
                            if sample in selected_samples
                            and idx < len(original_x)
                            and str(original_x[idx]).lower() != "nan"
                            and original_x[idx] is not None
                        ]
                        if filtered_indices:
                            new_y = [original_y[idx] for idx in filtered_indices]
                            new_x = [original_x[idx] for idx in filtered_indices]
                            patched_fig["data"][i]["y"] = (
                                tuple(new_y) if isinstance(original_y, tuple) else new_y
                            )
                            patched_fig["data"][i]["x"] = (
                                tuple(new_x) if isinstance(original_x, tuple) else new_x
                            )
                            patched_fig["data"][i]["visible"] = True
                            logger.info(
                                f"      Filtered horizontal bar chart: {len(new_y)} samples"
                            )
                        else:
                            patched_fig["data"][i]["visible"] = False
                            logger.debug("      No valid data after filtering - hiding trace")
                else:
                    # Vertical bars: samples are in X-axis
                    if original_x and original_y:
                        # Filter from original data based on selected samples AND valid Y values
                        filtered_indices = [
                            idx
                            for idx, sample in enumerate(original_x)
                            if sample in selected_samples
                            and idx < len(original_y)
                            and str(original_y[idx]).lower() != "nan"
                            and original_y[idx] is not None
                        ]
                        if filtered_indices:
                            new_x = [original_x[idx] for idx in filtered_indices]
                            new_y = [original_y[idx] for idx in filtered_indices]
                            patched_fig["data"][i]["x"] = (
                                tuple(new_x) if isinstance(original_x, tuple) else new_x
                            )
                            patched_fig["data"][i]["y"] = (
                                tuple(new_y) if isinstance(original_y, tuple) else new_y
                            )
                            patched_fig["data"][i]["visible"] = True
                            logger.info(f"      Filtered vertical bar chart: {len(new_x)} samples")
                        else:
                            patched_fig["data"][i]["visible"] = False
                            logger.debug("      No valid data after filtering - hiding trace")

            # Method 2: Handle heatmaps - Return full figure (Patch doesn't handle Y-axis properly)
            elif trace_type == "heatmap":
                logger.info("      Processing heatmap - using full figure replacement")
                if original_y:
                    # Always filter from original data (even when restoring all samples)
                    # This matches the working dev pattern and ensures clean state
                    filtered_indices = [
                        idx for idx, sample in enumerate(original_y) if sample in selected_samples
                    ]
                    logger.info(
                        f"      Filtering heatmap: {len(filtered_indices)}/{len(original_y)} samples selected"
                    )

                    if filtered_indices:
                        new_y = [original_y[idx] for idx in filtered_indices]

                        # For heatmaps, replace with full figure instead of Patch
                        full_fig = copy.deepcopy(fig)

                        # Update the heatmap data properly
                        full_fig["data"][i]["y"] = (
                            tuple(new_y) if isinstance(original_y, tuple) else new_y
                        )

                        if original_z:
                            new_z = [original_z[idx] for idx in filtered_indices]
                            full_fig["data"][i]["z"] = (
                                tuple(new_z) if isinstance(original_z, tuple) else new_z
                            )

                        if original_x:
                            # X-axis typically doesn't need filtering for heatmaps, but update if needed
                            full_fig["data"][i]["x"] = (
                                tuple(original_x) if isinstance(original_x, tuple) else original_x
                            )

                        # Ensure proper heatmap axis configuration
                        if "layout" in full_fig and "yaxis" in full_fig["layout"]:
                            # Clear any pre-set tickvals/ticktext that might override the y data
                            if "tickvals" in full_fig["layout"]["yaxis"]:
                                del full_fig["layout"]["yaxis"]["tickvals"]
                            if "ticktext" in full_fig["layout"]["yaxis"]:
                                del full_fig["layout"]["yaxis"]["ticktext"]
                            # Ensure y-axis shows all ticks
                            full_fig["layout"]["yaxis"]["type"] = "category"

                        logger.info(f"      ✅ Heatmap updated with {len(new_y)} samples")
                        patched_figures.append(full_fig)
                        figure_replaced = True
                        break  # Skip normal patch processing for this figure
                    else:
                        logger.warning("      No valid data after filtering - hiding heatmap")
                        patched_fig["data"][i]["visible"] = False

            # Method 3: Handle other plot types (scatter, line, etc.)
            else:
                # For scatter plots and others, check if trace name matches a sample
                # Show trace only if its name matches one of the selected samples
                trace_matches_selected = any(sample in trace_name for sample in selected_samples)
                patched_fig["data"][i]["visible"] = trace_matches_selected
                logger.info(
                    f"      Trace '{trace_name}': visible={trace_matches_selected} "
                    f"(matches selected samples: {trace_matches_selected})"
                )

        # Only append the patched figure if we didn't replace it with a full figure
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

    # Debug callback
    @app.callback(
        Input("interactive-values-store", "data"),
        prevent_initial_call=True,
    )
    def debug_interactive_values(interactive_values):
        logger.info(f"Interactive values updated: {interactive_values}")

    # Callback to patch MultiQC figures based on interactive filtering
    @app.callback(
        # Output(
        #     {"type": "multiqc-plot-container", "index": MATCH}, "children", allow_duplicate=True
        # ),
        Output({"type": "multiqc-graph", "index": MATCH}, "figure", allow_duplicate=True),
        Input("interactive-values-store", "data"),
        State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        State({"type": "multiqc-graph", "index": MATCH}, "figure"),
        State({"type": "multiqc-trace-metadata", "index": MATCH}, "data"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def patch_multiqc_plot_with_interactive_filtering(
        interactive_values,
        stored_metadata,
        current_figure,
        trace_metadata,
        local_data,
    ):
        """Patch MultiQC plots when interactive filtering is applied (only for joined workflows).

        Uses existing figure and patches it directly without regenerating from S3.

        RESET SUPPORT: Empty interactive_values reloads unfiltered data.
        """
        logger.info("MultiQC patching callback triggered")

        # Early exit if no stored metadata (interactive_values can be empty for reset)
        if not stored_metadata:
            logger.debug("No stored metadata - skipping")
            return dash.no_update

        # RESET SUPPORT: Allow empty interactive_values to reload unfiltered data
        if not interactive_values:
            logger.info(
                "🔄 RESET DETECTED: Empty interactive values - reloading unfiltered MultiQC data"
            )
            interactive_values = {"interactive_components_values": []}

        # Get authentication token
        token = local_data.get("access_token") if local_data else None
        if not token:
            logger.warning("No access token available for MultiQC patching")
            return dash.no_update

        # Extract MultiQC component data from stored metadata
        s3_locations = stored_metadata.get("s3_locations", [])
        selected_module = stored_metadata.get("selected_module")
        selected_plot = stored_metadata.get("selected_plot")
        metadata = stored_metadata.get("metadata", {})
        workflow_id = stored_metadata.get("workflow_id") or stored_metadata.get("wf_id")
        interactive_patching_enabled = stored_metadata.get("interactive_patching_enabled", False)

        logger.info(
            f"Processing MultiQC component - module: {selected_module}, "
            f"plot: {selected_plot}, s3_locations count: {len(s3_locations)}, "
            f"patching enabled: {interactive_patching_enabled}"
        )

        # Skip if patching is not enabled or basic requirements not met
        if not interactive_patching_enabled:
            logger.debug("Interactive patching not enabled for this component")
            return dash.no_update

        if not selected_module or not selected_plot or not s3_locations:
            logger.debug("Missing required data for MultiQC patching")
            return dash.no_update

        if not workflow_id:
            logger.debug("No workflow_id for this component")
            return dash.no_update

        # Get the MultiQC data collection ID to check for joins
        multiqc_dc_id = stored_metadata.get("dc_id") or stored_metadata.get("data_collection_id")
        if not multiqc_dc_id:
            logger.warning("No dc_id found for MultiQC component")
            return dash.no_update

        # Build a complete metadata list including interactive components for join detection
        # return_joins_dict needs to see ALL components to properly identify joins
        stored_metadata_for_joins = [stored_metadata]

        # Add interactive component metadata from the interactive_values structure
        if (
            isinstance(interactive_values, dict)
            and "interactive_components_values" in interactive_values
        ):
            for component_data in interactive_values["interactive_components_values"]:
                if isinstance(component_data, dict) and "metadata" in component_data:
                    comp_metadata = component_data["metadata"]
                    # Only add if it has a dc_id and is from the same workflow
                    if comp_metadata.get("dc_id") and comp_metadata.get("wf_id") == workflow_id:
                        stored_metadata_for_joins.append(comp_metadata)
                        logger.debug(
                            f"Added component metadata: dc_id={comp_metadata.get('dc_id')}, "
                            f"type={comp_metadata.get('component_type')}"
                        )

        logger.info(
            f"Checking joins for workflow {workflow_id} with {len(stored_metadata_for_joins)} components "
            f"(MultiQC dc_id: {multiqc_dc_id})"
        )

        # Use extra_dc to include MultiQC DC since it's excluded from dc_ids_all_components
        joins_dict = return_joins_dict(
            workflow_id, stored_metadata_for_joins, token, extra_dc=multiqc_dc_id
        )
        if not joins_dict:
            logger.info(f"No joins configured for workflow {workflow_id} - skipping patching")
            return dash.no_update

        logger.info(f"Joins detected for workflow {workflow_id}: {joins_dict}")

        # Build interactive_components_dict in the format expected by iterative_join
        # Structure: {component_index: {"index": ..., "value": [...], "metadata": {...}}}
        interactive_components_dict = {}
        has_active_filters = False  # Track if any filters have actual values

        if "interactive_components_values" in interactive_values:
            for component_data in interactive_values["interactive_components_values"]:
                component_index = component_data.get("index")
                component_value = component_data.get("value", [])

                # Check if this component has any active filter values
                if component_value and len(component_value) > 0:
                    has_active_filters = True
                if component_index:
                    interactive_components_dict[component_index] = component_data
                    comp_metadata = component_data.get("metadata", {})
                    logger.info(
                        f"Interactive component {component_index}: "
                        f"dc_id={comp_metadata.get('dc_id')}, "
                        f"column={comp_metadata.get('column_name')}, "
                        f"value={component_data.get('value')}"
                    )

        # Early exit if no interactive components exist
        if not interactive_components_dict:
            logger.info("No interactive components - skipping patching")
            return dash.no_update

        # Check if figure has been previously filtered by looking at the figure layout
        # We store a custom flag _depictio_filter_applied when patching
        figure_was_patched = False
        if current_figure and isinstance(current_figure, dict):
            layout = current_figure.get("layout", {})
            # Check if filters were previously applied to this figure
            figure_was_patched = layout.get("_depictio_filter_applied", False)

        # Early exit if no filters are active AND figure hasn't been patched before
        # (This prevents unnecessary patching on initial load with empty filters)
        # BUT allow patching if figure was previously filtered (user is clearing filters)
        if not has_active_filters and not figure_was_patched:
            logger.info("No active filters on initial load - skipping patching")
            return dash.no_update

        # If user is clearing filters (no active filters but was previously patched),
        # we need to restore the original unfiltered data
        if not has_active_filters and figure_was_patched:
            logger.info("Clearing filters - restoring original unfiltered data")
            # We'll let the patching continue with empty selected_samples to restore all data

        try:
            # Extract metadata DC ID and join column from joins_dict
            metadata_dc_id = None
            join_column = None

            for join_key, join_configs in joins_dict.items():
                if multiqc_dc_id in join_key:
                    # Get the other DC (metadata table) from the join key
                    other_dcs = [dc for dc in join_key if dc != multiqc_dc_id]

                    if other_dcs:
                        # Standard case: join_key contains both MultiQC and metadata DC
                        metadata_dc_id = other_dcs[0]
                    else:
                        # Fallback: join_key only contains MultiQC DC
                        # Extract metadata DC from interactive components
                        logger.debug(
                            f"Join key {join_key} only contains MultiQC DC, "
                            "extracting metadata DC from interactive components"
                        )
                        for comp_data in interactive_components_dict.values():
                            comp_dc_id = comp_data.get("metadata", {}).get("dc_id")
                            if comp_dc_id and comp_dc_id != multiqc_dc_id:
                                metadata_dc_id = comp_dc_id
                                logger.info(
                                    f"Found metadata DC from interactive component: {metadata_dc_id}"
                                )
                                break

                    # Get join column from config (if available)
                    for join_config_dict in join_configs:
                        for join_info in join_config_dict.values():
                            join_column = join_info.get("on_columns", [None])[0]
                            break

                    # Fallback: If join_column not found in joins_dict, use default 'sample'
                    if not join_column:
                        logger.warning(
                            "Join column not found in joins_dict, using default 'sample'"
                        )
                        join_column = "sample"

                    break

            if not metadata_dc_id or not join_column:
                logger.error(
                    f"Could not find metadata DC or join column. "
                    f"metadata_dc_id={metadata_dc_id}, join_column={join_column}, "
                    f"joins_dict={joins_dict}"
                )
                return dash.no_update

            # Get canonical sample IDs from filtered metadata table
            canonical_samples = get_samples_from_metadata_filter(
                workflow_id=workflow_id,
                metadata_dc_id=metadata_dc_id,
                join_column=join_column,
                interactive_components_dict=interactive_components_dict,
                token=token,
            )

            if not canonical_samples:
                logger.warning("No canonical samples found after filtering")
                return dash.no_update

            # Expand canonical IDs to all MultiQC variants using stored mappings
            sample_mappings = metadata.get("sample_mappings", {})
            selected_samples = expand_canonical_samples_to_variants(
                canonical_samples, sample_mappings
            )

            if not selected_samples:
                logger.warning("No samples found after expansion")
                return dash.no_update

            # Check if we have a current figure to patch
            if not current_figure:
                logger.warning("No current figure available for patching")
                return dash.no_update

            # Check if we have trace metadata for proper patching
            if not trace_metadata or not trace_metadata.get("original_data"):
                logger.warning("No trace metadata available - cannot perform proper patching")
                return dash.no_update

            # Use existing figure and patch it directly (no regeneration)
            logger.info(f"Patching existing figure with {len(selected_samples)} selected samples")
            logger.debug(
                f"Trace metadata available: {len(trace_metadata.get('original_data', []))} traces"
            )

            # Apply patching to filter the plot with the resolved sample names
            patched_figures = patch_multiqc_figures(
                [current_figure], selected_samples, metadata, trace_metadata
            )

            # Return the patched figure
            if patched_figures:
                patched_fig = patched_figures[0]
                # Mark the figure as having been patched so we know to restore when filters are cleared
                if "layout" not in patched_fig:
                    patched_fig["layout"] = {}
                patched_fig["layout"]["_depictio_filter_applied"] = has_active_filters
                logger.info(
                    f"Successfully patched MultiQC figure (filter_applied={has_active_filters})"
                )
                return patched_fig
            else:
                logger.warning("No data available after filtering")
                return dash.no_update

        except Exception as e:
            logger.error(f"Error patching MultiQC plot: {e}", exc_info=True)
            return dash.no_update

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

        logger.info(f"🎨 MultiQC THEME PATCH: Applied {template_name} (theme_data: {theme_data})")
        return patch

    # Background callback to render MultiQC plots during dashboard restoration
    @app.callback(
        Output({"type": "multiqc-graph", "index": MATCH}, "figure"),
        Output({"type": "multiqc-trace-metadata", "index": MATCH}, "data"),
        Input({"type": "multiqc-trigger", "index": MATCH}, "data"),
        background=False,  # Disabled background mode - using synchronous rendering
        prevent_initial_call=False,
    )
    def render_multiqc_plot_background(trigger_data):
        """Generate MultiQC plot for dashboard restoration."""
        # Move import to top to avoid issues in background context
        from depictio.dash.modules.multiqc_component.utils import analyze_multiqc_plot_structure

        logger.info("=" * 80)
        logger.info("🎬 RENDER CALLBACK STARTED")
        logger.info(f"🔍 Trigger data received: {trigger_data}")

        if not trigger_data:
            logger.warning("⚠️ No trigger_data - returning no_update")
            return dash.no_update, dash.no_update

        logger.info(f"✅ Trigger data is valid, type: {type(trigger_data)}")

        try:
            # Log each extracted parameter
            logger.info("📦 Extracting parameters from trigger_data...")
            s3_locations = trigger_data.get("s3_locations", [])
            logger.info(f"  - s3_locations: {s3_locations} (count: {len(s3_locations)})")

            module = trigger_data.get("module")
            logger.info(f"  - module: {module}")

            plot = trigger_data.get("plot")
            logger.info(f"  - plot: {plot}")

            dataset_id = trigger_data.get("dataset_id")
            logger.info(f"  - dataset_id: {dataset_id}")

            theme = trigger_data.get("theme", "light")
            logger.info(f"  - theme: {theme}")

            component_id = trigger_data.get("component_id")
            logger.info(f"  - component_id: {component_id}")

            # Validate required parameters
            if not s3_locations:
                logger.error("❌ ERROR: s3_locations is empty!")
                error_fig = {
                    "data": [],
                    "layout": {
                        "title": "Error: No S3 locations",
                        "xaxis": {"visible": False},
                        "yaxis": {"visible": False},
                        "annotations": [
                            {
                                "text": "Missing S3 locations for MultiQC data",
                                "xref": "paper",
                                "yref": "paper",
                                "x": 0.5,
                                "y": 0.5,
                                "showarrow": False,
                                "font": {"size": 16, "color": "red"},
                            }
                        ],
                    },
                }
                return error_fig, {}

            if not module:
                logger.error("❌ ERROR: module is missing!")
                error_fig = {
                    "data": [],
                    "layout": {
                        "title": "Error: No module specified",
                        "xaxis": {"visible": False},
                        "yaxis": {"visible": False},
                        "annotations": [
                            {
                                "text": "MultiQC module not specified",
                                "xref": "paper",
                                "yref": "paper",
                                "x": 0.5,
                                "y": 0.5,
                                "showarrow": False,
                                "font": {"size": 16, "color": "red"},
                            }
                        ],
                    },
                }
                return error_fig, {}

            if not plot:
                logger.error("❌ ERROR: plot is missing!")
                error_fig = {
                    "data": [],
                    "layout": {
                        "title": "Error: No plot specified",
                        "xaxis": {"visible": False},
                        "yaxis": {"visible": False},
                        "annotations": [
                            {
                                "text": "MultiQC plot name not specified",
                                "xref": "paper",
                                "yref": "paper",
                                "x": 0.5,
                                "y": 0.5,
                                "showarrow": False,
                                "font": {"size": 16, "color": "red"},
                            }
                        ],
                    },
                }
                return error_fig, {}

            logger.info("✅ All required parameters present")
            logger.info(f"🎨 Rendering MultiQC plot: {module}/{plot}")

            # Call create_multiqc_plot with extensive logging
            logger.info("📞 Calling create_multiqc_plot...")
            logger.info(
                f"   Parameters: module={module}, plot={plot}, dataset_id={dataset_id}, theme={theme}"
            )
            logger.info(f"   S3 locations: {s3_locations}")

            fig = create_multiqc_plot(
                s3_locations=s3_locations,
                module=module,
                plot=plot,
                dataset_id=dataset_id,
                theme=theme,
            )

            logger.info("✅ create_multiqc_plot returned successfully")
            logger.info(f"   Figure type: {type(fig)}")
            logger.info(
                f"   Figure has {len(fig.data) if hasattr(fig, 'data') else 'unknown'} traces"
            )

            # Analyze plot structure
            logger.info("🔍 Analyzing plot structure...")
            trace_metadata = analyze_multiqc_plot_structure(fig)
            logger.info("✅ Plot structure analyzed")
            logger.info(f"   Trace count: {trace_metadata.get('summary', {}).get('traces', 0)}")

            # Return figure object directly (dcc.Graph already exists in DOM)
            logger.info("✅ Returning figure object for dcc.Graph")
            logger.info(f"   Figure type: {type(fig)}")
            logger.info(f"   Figure traces: {len(fig.data)}")

            logger.info("🎉 RENDER CALLBACK COMPLETED SUCCESSFULLY")
            logger.info("=" * 80)
            return fig, trace_metadata

        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ EXCEPTION in render callback: {type(e).__name__}")
            logger.error(f"❌ Exception message: {str(e)}")
            logger.error("❌ Exception details:", exc_info=True)
            logger.error("=" * 80)

            error_fig = {
                "data": [],
                "layout": {
                    "title": "Error Rendering MultiQC Plot",
                    "xaxis": {"visible": False},
                    "yaxis": {"visible": False},
                    "annotations": [
                        {
                            "text": f"{type(e).__name__}: {str(e)}",
                            "xref": "paper",
                            "yref": "paper",
                            "x": 0.5,
                            "y": 0.5,
                            "showarrow": False,
                            "font": {"size": 14, "color": "red"},
                        }
                    ],
                },
            }
            return error_fig, {}

        # # Early exit if basic requirements not met
        # if not selected_module or not selected_plot or not s3_locations or not interactive_values:
        #     return dash.no_update

        # # Check if this workflow has joins configured
        # workflow_id = stored_metadata.get("workflow_id") if stored_metadata else None
        # if not workflow_id:
        #     return dash.no_update

        # # Get authentication token
        # token = local_data.get("access_token") if local_data else None
        # if not token:
        #     logger.warning("No access token available for MultiQC patching")
        #     return dash.no_update

        # try:
        #     # Check for joins in this workflow
        #     joins_dict = return_joins_dict(workflow_id, [stored_metadata], token)
        #     if not joins_dict:
        #         logger.info("No joins configured for workflow - skipping MultiQC patching")
        #         return dash.no_update

        #     logger.info(f"MultiQC patching triggered by interactive values: {interactive_values}")
        #     logger.info(f"Joins detected for workflow {workflow_id}: {joins_dict}")

        #     # Extract selected samples from interactive values
        #     # Interactive values structure: {dc_id: {column: [selected_values]}}
        #     selected_samples = []
        #     for dc_filters in interactive_values.values():
        #         for column_name, selected_values in dc_filters.items():
        #             # Look for sample-related columns (common names)
        #             if column_name.lower() in ["sample", "sample_id", "sample_name", "samples"]:
        #                 selected_samples.extend(selected_values)

        #     if not selected_samples:
        #         logger.info(
        #             "No sample selections found in interactive values - using original plot"
        #         )
        #         return dash.no_update

        #     logger.info(f"Found {len(selected_samples)} selected samples for filtering")

        #     # Create the original plot
        #     fig = create_multiqc_plot(
        #         s3_locations=s3_locations,
        #         module=selected_module,
        #         plot=selected_plot,
        #         dataset_id=selected_dataset,
        #     )

        #     # Apply patching to filter the plot
        #     patched_figures = patch_multiqc_figures([fig], selected_samples, metadata)

        #     # Return the patched plot
        #     if patched_figures:
        #         return dcc.Graph(
        #             figure=patched_figures[0],
        #             style={"height": "500px"},
        #             config={"displayModeBar": True, "responsive": True},
        #         )
        #     else:
        #         return dmc.Center(
        #             [dmc.Text("No data available after filtering", c="gray")],
        #             style={"height": "400px"},
        #         )

        # except Exception as e:
        #     logger.error(f"Error patching MultiQC plot: {e}")
        #     # Return original plot on error
        #     try:
        #         fig = create_multiqc_plot(
        #             s3_locations=s3_locations,
        #             module=selected_module,
        #             plot=selected_plot,
        #             dataset_id=selected_dataset,
        #         )
        #         return dcc.Graph(figure=fig, style={"height": "500px"})
        #     except Exception:
        #         return dmc.Center(
        #             [dmc.Text("Error loading plot", c="red")],
        #             style={"height": "400px"},
        #         )
