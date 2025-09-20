from typing import Any, Optional

import dash
import dash_mantine_components as dmc
from dash import MATCH, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
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
        # If id is a button ID dict, extract the index value
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
            dcc.Store(
                id={"type": "stored-metadata-component", "index": component_id},
                data={
                    "index": component_id,
                    "component_type": "multiqc",  # Use lowercase for helpers mapping compatibility
                    "workflow_id": workflow_id,
                    "data_collection_id": data_collection_id,
                    "wf_id": workflow_id,
                    "dc_id": data_collection_id,
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

    # Callback to generate the actual plot
    @app.callback(
        Output({"type": "multiqc-plot-container", "index": MATCH}, "children"),
        Input({"type": "multiqc-module-select", "index": MATCH}, "value"),
        Input({"type": "multiqc-plot-select", "index": MATCH}, "value"),
        Input({"type": "multiqc-dataset-select", "index": MATCH}, "value"),
        State({"type": "multiqc-s3-store", "index": MATCH}, "data"),
    )
    def generate_multiqc_plot(selected_module, selected_plot, selected_dataset, s3_locations):
        if not selected_module or not selected_plot or not s3_locations:
            return dmc.Center(
                [dmc.Text("Select a module and plot to view visualization", c="gray")],
                style={"height": "400px"},
            )

        # Create the plot
        fig = create_multiqc_plot(
            s3_locations=s3_locations,
            module=selected_module,
            plot=selected_plot,
            dataset_id=selected_dataset,
        )

        return dcc.Graph(figure=fig, style={"height": "500px"})

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
