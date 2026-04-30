"""
Project Data Collections Management Module

This module provides a Dash layout and callbacks for managing data collections
within a project. It allows administrators and project owners to add, modify,
and remove data collections, as well as upload new datasets.

The module is organized into:
- API utility functions for data fetching and manipulation
- UI component definitions
- Layout definition
- Modular callback functions for handling user interactions
"""

import base64

import dash
import dash_ag_grid as dag
import dash_mantine_components as dmc
import polars as pl
from bson import ObjectId
from dash import ALL, MATCH, Input, Output, State, ctx, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.dash.api_calls import (
    api_call_append_to_multiqc_data_collection,
    api_call_clear_multiqc_data_collection,
    api_call_create_link,
    api_call_delete_link,
    api_call_fetch_all_multiqc_reports,
    api_call_fetch_delta_table_info,
    api_call_fetch_multiqc_report,
    api_call_fetch_project_by_id,
    api_call_get_dc_columns,
    api_call_get_project_links,
    api_call_overwrite_multiqc_data_collection,
)
from depictio.dash.colors import colors
from depictio.dash.components.depictio_cytoscape_joins import (
    create_joins_visualization_section,
    generate_elements_from_project,
    register_joins_callbacks,
)
from depictio.dash.layouts.layouts_toolbox import (
    create_data_collection_delete_modal,
    create_data_collection_edit_name_modal,
    create_data_collection_modal,
    create_data_collection_overwrite_modal,
    create_dc_link_modal,
)
from depictio.models.models.projects import ProjectResponse

MULTIQC_PARQUET_BASENAME = "multiqc.parquet"


def _multiqc_folder_from_path(filename: str, fallback_idx: int) -> str:
    """Mirror of api_calls._extract_multiqc_folder_name for UI-side previews.

    Kept separate (not imported) to avoid leaking a private symbol; the logic
    is small and identical to the server's, which guarantees the preview
    reflects the temp layout the server will create.
    """
    parts = [p for p in filename.replace("\\", "/").split("/") if p]
    if len(parts) >= 3 and parts[-2] == "multiqc_data":
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return f"report_{fallback_idx}"


def _normalize_upload_to_lists(contents, filename) -> tuple[list, list]:
    """Coerce ``dcc.Upload`` contents/filename to parallel lists.

    Single-file uploads come through as scalars; multi-file uploads as lists.
    Callers downstream (MultiQC ingest, validators) want a uniform list view.
    """
    if isinstance(contents, str):
        contents_list = [contents]
        filenames_list = [filename] if isinstance(filename, str) else filename
    else:
        contents_list = contents
        filenames_list = filename if isinstance(filename, list) else [filename]
    return contents_list, filenames_list


def _build_multiqc_report_detail(report: dict) -> list:
    """Build the per-report detail block (info row + samples + modules accordions).

    Used both for the initial render (in ``populate_multiqc_metadata_content``)
    and for the selector-driven swap callback so the two stay in lockstep.
    """
    if not report:
        return [dmc.Text("No report selected", size="sm", c="gray", ta="center")]

    metadata = report.get("metadata", {}) or {}
    modules = metadata.get("modules", []) or []
    plots = metadata.get("plots", {}) or {}

    canonical_samples = metadata.get("canonical_samples", []) or []
    if not canonical_samples:
        all_samples = metadata.get("samples", []) or []
        canonical_samples = [
            s
            for s in all_samples
            if not any(
                suffix in s
                for suffix in [
                    "_1",
                    "_2",
                    "_R1",
                    "_R2",
                    " - First read",
                    " - Second read",
                    " - Adapter",
                    " - adapter",
                ]
            )
        ]

    multiqc_version = report.get("multiqc_version", "N/A")
    report_name = report.get("report_name", "N/A")
    processed_at = report.get("processed_at", "N/A") or "N/A"
    file_size_bytes = report.get("file_size_bytes")

    if file_size_bytes and isinstance(file_size_bytes, (int, float)):
        formatted_size, unit = format_storage_size(file_size_bytes)
        file_size_display = f"{formatted_size} {unit}"
    else:
        file_size_display = "Unknown"

    samples_list = dmc.Stack(
        [dmc.Text(sample, size="xs", ff="monospace") for sample in sorted(canonical_samples)],
        gap=2,
    )

    module_plot_items = []
    for module in sorted(modules):
        module_plots = plots.get(module, []) if isinstance(plots, dict) else []
        plot_names: list[str] = []
        if isinstance(module_plots, list):
            for plot in module_plots:
                if isinstance(plot, str):
                    plot_names.append(plot)
                elif isinstance(plot, dict):
                    plot_names.extend(plot.keys())

        if plot_names:
            plot_list = dmc.Stack(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:chart-box", width=14, color=colors["orange"]),
                            dmc.Text(plot_name, size="xs"),
                        ],
                        gap="xs",
                    )
                    for plot_name in plot_names
                ],
                gap=4,
                pl="md",
            )
        else:
            plot_list = dmc.Text("No plots", size="xs", c="gray", fs="italic", pl="md")

        module_plot_items.append(
            dmc.AccordionItem(
                value=module,
                children=[
                    dmc.AccordionControl(
                        dmc.Group(
                            [
                                DashIconify(icon="mdi:puzzle", width=16, color=colors["green"]),
                                dmc.Text(module, size="sm", fw=500),
                                dmc.Text(f"({len(plot_names)} plots)", size="xs", c="gray"),
                            ],
                            gap="xs",
                        ),
                    ),
                    dmc.AccordionPanel(plot_list),
                ],
            )
        )

    info_row = dmc.SimpleGrid(
        cols={"base": 2, "sm": 4},
        spacing="md",
        children=[
            dmc.Stack(
                [
                    dmc.Text("Report", size="xs", c="gray"),
                    dmc.Text(report_name, size="sm", ff="monospace", truncate=True),
                ],
                gap=2,
            ),
            dmc.Stack(
                [
                    dmc.Text("Version", size="xs", c="gray"),
                    dmc.Text(multiqc_version, size="sm", ff="monospace"),
                ],
                gap=2,
            ),
            dmc.Stack(
                [
                    dmc.Text("Processed", size="xs", c="gray"),
                    dmc.Text(
                        processed_at[:10] if len(processed_at) > 10 else processed_at,
                        size="sm",
                    ),
                ],
                gap=2,
            ),
            dmc.Stack(
                [
                    dmc.Text("Size", size="xs", c="gray"),
                    dmc.Text(file_size_display, size="sm", ff="monospace"),
                ],
                gap=2,
            ),
        ],
    )

    samples_panel = (
        dmc.ScrollArea(samples_list, h=150, type="auto", offsetScrollbars=True)
        if canonical_samples
        else dmc.Text("No samples found", size="sm", c="gray", fs="italic")
    )

    modules_panel = (
        dmc.Accordion(
            variant="contained",
            chevronPosition="left",
            children=module_plot_items,
        )
        if module_plot_items
        else dmc.Text("No modules found", size="sm", c="gray", fs="italic")
    )

    accordions = dmc.Accordion(
        variant="separated",
        chevronPosition="left",
        children=[
            dmc.AccordionItem(
                value="samples",
                children=[
                    dmc.AccordionControl(
                        dmc.Group(
                            [
                                DashIconify(icon="mdi:test-tube", width=18, color=colors["blue"]),
                                dmc.Text("Samples", size="sm", fw=500),
                                dmc.Text(f"({len(canonical_samples)})", size="sm", c="gray"),
                            ],
                            gap="xs",
                        ),
                    ),
                    dmc.AccordionPanel(samples_panel),
                ],
            ),
            dmc.AccordionItem(
                value="modules-plots",
                children=[
                    dmc.AccordionControl(
                        dmc.Group(
                            [
                                DashIconify(icon="mdi:puzzle", width=18, color=colors["green"]),
                                dmc.Text("Modules & Plots", size="sm", fw=500),
                                dmc.Text(f"({len(modules)} modules)", size="sm", c="gray"),
                            ],
                            gap="xs",
                        ),
                    ),
                    dmc.AccordionPanel(modules_panel),
                ],
            ),
        ],
    )

    return [dmc.Divider(my="sm"), info_row, dmc.Divider(my="sm"), accordions]


def _create_template_origin_section(project) -> html.Div:
    """Create a template origin info section if the project was created from a template."""
    template_origin = getattr(project, "template_origin", None)
    if template_origin is None:
        return html.Div()

    # Handle both Pydantic model and raw dict
    if isinstance(template_origin, dict):
        template_id = template_origin.get("template_id", "")
    else:
        template_id = template_origin.template_id
    if not template_id:
        return html.Div()
    docs_base = "https://depictio.github.io/depictio-docs/usage/projects/templates"
    docs_url = f"{docs_base}#{template_id.replace('/', '').replace('.', '')}"

    if hasattr(template_origin, "model_dump"):
        to_dict = template_origin.model_dump()
    elif isinstance(template_origin, dict):
        to_dict = template_origin
    else:
        to_dict = {}

    # Template variables (stored explicitly on TemplateOrigin)
    variables = to_dict.get("variables", {})
    var_rows = []
    for var_name, var_value in variables.items():
        if var_name == "DATA_ROOT":
            continue  # shown in info section
        var_rows.append(
            html.Tr(
                [
                    html.Td(
                        dmc.Code(var_name, style={"fontSize": "12px"}),
                        style={"paddingRight": "12px", "verticalAlign": "top"},
                    ),
                    html.Td(
                        dmc.Text(str(var_value), size="sm", style={"wordBreak": "break-all"}),
                    ),
                ]
            )
        )

    return dmc.Paper(
        children=[
            # Header: icon + title + badge link
            dmc.Group(
                [
                    DashIconify(
                        icon="mdi:layers-outline",
                        width=22,
                        color=colors.get("indigo", "indigo"),
                    ),
                    dmc.Text("Template", fw="bold", size="lg"),
                    dmc.Anchor(
                        dmc.Badge(
                            template_id,
                            color="indigo",
                            variant="light",
                            size="sm",
                            rightSection=DashIconify(icon="mdi:open-in-new", width=12),
                            style={"cursor": "pointer"},
                        ),
                        href=docs_url,
                        target="_blank",
                        style={"textDecoration": "none"},
                    ),
                ],
                gap="sm",
            ),
            dmc.Divider(my="xs"),
            # Two-column layout: info left, variables right
            dmc.SimpleGrid(
                cols=2,
                spacing="xl",
                children=[
                    # Left column: template info
                    dmc.Stack(
                        [
                            dmc.Text("Info", size="xs", fw=600, c="dimmed", tt="uppercase"),
                            dmc.Stack(
                                gap=2,
                                children=[
                                    dmc.Group(
                                        [
                                            DashIconify(icon=icon, width=14, color="gray"),
                                            dmc.Text(f"{label}:", size="sm", c="dimmed"),
                                            dmc.Text(
                                                str(to_dict[key]),
                                                size="sm",
                                                style={"wordBreak": "break-all"},
                                            ),
                                        ],
                                        gap=4,
                                    )
                                    for key, label, icon in [
                                        ("template_version", "Version", "mdi:tag-outline"),
                                        ("data_root", "Data root", "mdi:folder-outline"),
                                        ("applied_at", "Applied", "mdi:clock-outline"),
                                    ]
                                    if to_dict.get(key)
                                ],
                            ),
                        ],
                        gap=4,
                    ),
                    # Right column: variables
                    dmc.Stack(
                        [
                            dmc.Text("Variables", size="xs", fw=600, c="dimmed", tt="uppercase"),
                            html.Table(
                                html.Tbody(var_rows),
                                style={"borderCollapse": "collapse"},
                            )
                            if var_rows
                            else dmc.Text("No variables", size="sm", c="dimmed", fs="italic"),
                        ],
                        gap=4,
                    ),
                ],
            ),
        ],
        withBorder=True,
        radius="md",
        p="md",
    )


def calculate_total_storage_size(data_collections):
    """
    Calculate the total storage size across all data collections.

    Args:
        data_collections: List of data collection objects

    Returns:
        int: Total size in bytes across all data collections
    """
    total_bytes = 0

    if not data_collections:
        return total_bytes

    for dc in data_collections:
        # Handle dict or object access
        if isinstance(dc, dict):
            flexible_metadata = dc.get("flexible_metadata", {})
        else:
            flexible_metadata = getattr(dc, "flexible_metadata", {})

        if isinstance(flexible_metadata, dict):
            deltatable_size_bytes = flexible_metadata.get("deltatable_size_bytes", 0)
        else:
            deltatable_size_bytes = (
                getattr(flexible_metadata, "deltatable_size_bytes", 0) if flexible_metadata else 0
            )

        if deltatable_size_bytes and isinstance(deltatable_size_bytes, (int, float)):
            total_bytes += int(deltatable_size_bytes)

    return total_bytes


def format_storage_size(size_bytes):
    """
    Format storage size in bytes to human-readable format.

    Args:
        size_bytes (int): Size in bytes

    Returns:
        tuple: (formatted_size_str, unit_str) for display
    """
    if size_bytes == 0:
        return "0", "bytes"
    elif size_bytes < 1024:
        return f"{size_bytes}", "bytes"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.1f}", "KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / (1024**2):.1f}", "MB"
    elif size_bytes < 1024**4:
        return f"{size_bytes / (1024**3):.1f}", "GB"
    else:
        return f"{size_bytes / (1024**4):.1f}", "TB"


def get_data_collection_size_display(data_collection):
    """
    Get formatted size display string for a data collection.

    Args:
        data_collection: Data collection object or dict

    Returns:
        str: Formatted size string for display
    """
    try:
        # Extract flexible_metadata and type
        if isinstance(data_collection, dict):
            flexible_metadata = data_collection.get("flexible_metadata", {})
            dc_type = data_collection.get("config", {}).get("type", "unknown").lower()
        else:
            flexible_metadata = getattr(data_collection, "flexible_metadata", {})
            dc_type = getattr(data_collection.config, "type", "unknown").lower()

        # Extract size_bytes based on data collection type
        if isinstance(flexible_metadata, dict):
            if dc_type == "multiqc":
                # For MultiQC, try different size fields
                size_bytes = (
                    flexible_metadata.get("total_file_size_bytes", 0)
                    or flexible_metadata.get("file_size_bytes", 0)
                    or flexible_metadata.get("s3_size_bytes", 0)
                )
            else:
                # For tables/other types, use deltatable size
                size_bytes = flexible_metadata.get("deltatable_size_bytes", 0)
        else:
            if dc_type == "multiqc":
                size_bytes = (
                    getattr(flexible_metadata, "total_file_size_bytes", 0)
                    or getattr(flexible_metadata, "file_size_bytes", 0)
                    or getattr(flexible_metadata, "s3_size_bytes", 0)
                    if flexible_metadata
                    else 0
                )
            else:
                size_bytes = (
                    getattr(flexible_metadata, "deltatable_size_bytes", 0)
                    if flexible_metadata
                    else 0
                )

        # Format and return
        if size_bytes and isinstance(size_bytes, (int, float)):
            formatted_size, unit = format_storage_size(size_bytes)
            return f"{formatted_size} {unit}"
        else:
            return "Unknown"
    except Exception:
        return "N/A"


def create_multiqc_metadata_summary(dc) -> dmc.Group | html.Div | dmc.Text:
    """
    Create a metadata summary row for MultiQC data collections.

    Returns a placeholder with a unique ID that will be populated by a callback
    that fetches the actual MultiQC metadata via API.

    Args:
        dc: Data collection object or dict.

    Returns:
        html.Div with placeholder for metadata (populated by callback).
    """
    # Get the DC ID for the callback
    if isinstance(dc, dict):
        dc_id = str(dc.get("_id", "") or dc.get("id", ""))
    else:
        dc_id = str(getattr(dc, "_id", "") or getattr(dc, "id", ""))

    if not dc_id:
        return dmc.Text(
            "MultiQC report",
            size="xs",
            c="gray",
            fs="italic",
        )

    # Return a div that will be populated by a callback
    return html.Div(
        id={"type": "multiqc-metadata-summary", "index": dc_id},
        children=[
            dmc.Group(
                [
                    dmc.Loader(size="xs", type="dots"),
                    dmc.Text("Loading metadata...", size="xs", c="gray"),
                ],
                gap="xs",
            )
        ],
    )


def create_image_dc_preview(dc) -> html.Div:
    """
    Create a thumbnail preview for Image data collections.

    Shows configuration info, image count badge, and a "Preview Gallery" button
    that opens a modal with sample images.

    Args:
        dc: Data collection object or dict.

    Returns:
        html.Div with image DC preview including config info and preview button.
    """
    # Extract data collection info
    if isinstance(dc, dict):
        dc_id = str(dc.get("_id", ""))
        config = dc.get("config", {})
        dc_specific = config.get("dc_specific_properties", {})
    else:
        dc_id = str(getattr(dc, "_id", "") or getattr(dc, "id", ""))
        config = getattr(dc, "config", None)
        if config:
            dc_specific = getattr(config, "dc_specific_properties", {})
            if hasattr(dc_specific, "model_dump"):
                dc_specific = dc_specific.model_dump()
            elif not isinstance(dc_specific, dict):
                dc_specific = {}
        else:
            dc_specific = {}

    # Get image configuration
    image_column = dc_specific.get("image_column", "Not configured")
    s3_base_folder = dc_specific.get("s3_base_folder", "")
    thumbnail_size = dc_specific.get("thumbnail_size", 150)

    # Build configuration info
    config_items = [
        dmc.Group(
            [
                DashIconify(icon="mdi:table-column", width=14, color=colors["grey"]),
                dmc.Text(f"Column: {image_column}", size="xs", c="gray"),
            ],
            gap=4,
        ),
    ]

    if s3_base_folder:
        # Show full S3 path with word break for long paths
        config_items.append(
            dmc.Group(
                [
                    DashIconify(icon="mdi:cloud-outline", width=14, color=colors["grey"]),
                    dmc.Text(
                        s3_base_folder,
                        size="xs",
                        c="gray",
                        style={"wordBreak": "break-all"},
                    ),
                ],
                gap=4,
                align="flex-start",
            )
        )

    # Build the preview component
    preview_content = [
        # Configuration details
        dmc.Stack(config_items, gap=4),
        # Preview button
        dmc.Group(
            [
                dmc.Button(
                    "Preview Gallery",
                    id={"type": "image-dc-preview-button", "index": dc_id},
                    size="compact-xs",
                    variant="light",
                    color="teal",
                    leftSection=DashIconify(icon="mdi:image-area", width=14),
                ),
            ],
            gap="xs",
        ),
        # Modal for image gallery preview
        dmc.Modal(
            id={"type": "image-dc-preview-modal", "index": dc_id},
            title="Image Gallery Preview",
            size="90%",
            centered=True,
            children=[
                dmc.ScrollArea(
                    html.Div(
                        id={"type": "image-dc-preview-grid", "index": dc_id},
                        children=[
                            dmc.Center(
                                dmc.Loader(type="dots", size="lg"),
                                style={"padding": "2rem"},
                            )
                        ],
                    ),
                    h="70vh",
                    type="auto",
                ),
            ],
        ),
        # Secondary modal for viewing individual images
        dmc.Modal(
            id={"type": "image-dc-viewer-modal", "index": dc_id},
            size="xl",
            centered=True,
            withCloseButton=True,
            children=[
                html.Img(
                    id={"type": "image-dc-viewer-img", "index": dc_id},
                    style={
                        "maxWidth": "100%",
                        "maxHeight": "80vh",
                        "objectFit": "contain",
                        "display": "block",
                        "margin": "0 auto",
                    },
                ),
                dmc.Text(
                    id={"type": "image-dc-viewer-title", "index": dc_id},
                    ta="center",
                    mt="md",
                    c="gray",
                ),
            ],
        ),
        # Store for DC metadata needed by the callback
        dcc.Store(
            id={"type": "image-dc-preview-store", "index": dc_id},
            data={
                "dc_id": dc_id,
                "image_column": image_column,
                "s3_base_folder": s3_base_folder,
                "thumbnail_size": thumbnail_size,
            },
        ),
    ]

    return dmc.Stack(preview_content, gap="xs")


def create_project_type_indicator(project_type):
    """
    Create a project type indicator badge.

    Args:
        project_type: "basic" or "advanced"

    Returns:
        dmc.Group: Project type indicator component
    """
    if project_type.lower() == "basic":
        color = "teal"
        description = "Simple project with direct data collection management"
    else:  # advanced
        color = "orange"
        description = "Advanced project with workflow-based data collections"

    return dmc.Group(
        [
            dmc.Group(
                [
                    DashIconify(icon="mdi:jira", width=20, color=color),
                    dmc.Text("Project Type:", size="sm", fw="bold", c="gray"),
                    dmc.Badge(project_type.title(), color=color, variant="light"),
                ],
                gap="xs",
                align="center",
            ),
            dmc.Text(description, size="xs", c="gray", style={"fontStyle": "italic"}),
        ],
        justify="space-between",
        align="center",
        # style={
        #     "padding": "0.5rem 1rem",
        #     "backgroundColor": "var(--app-surface-color, #f8f9fa)",
        #     "borderRadius": "0.5rem",
        #     "border": "1px solid var(--app-border-color, #dee2e6)",
        # },
    )


def create_workflow_card(workflow, selected_workflow_id=None):
    """
    Create a clickable workflow card displaying workflow information.

    Args:
        workflow: Workflow object
        selected_workflow_id: ID of currently selected workflow

    Returns:
        html.Div: Clickable workflow card component
    """
    is_selected = str(workflow.id) == selected_workflow_id

    # Get engine icon - prioritize nf-core catalog if present
    use_image_icon = False
    if workflow.catalog and workflow.catalog.name.lower() == "nf-core":
        # Use nf-core logo from assets
        engine_icon = "/assets/images/workflows/nf-core.png"
        use_image_icon = True
    else:
        engine_icons = {
            "snakemake": "vscode-icons:file-type-snakemake",
            "nextflow": "vscode-icons:file-type-nextflow",
            "python": "vscode-icons:file-type-python",
            "r": "vscode-icons:file-type-r",
            "bash": "vscode-icons:file-type-bash",
            "galaxy": "vscode-icons:file-type-galaxy",
            "cwl": "vscode-icons:file-type-cwl",
            "rust": "vscode-icons:file-type-rust",
        }
        engine_icon = engine_icons.get(workflow.engine.name.lower(), "hugeicons:workflow-square-01")

    return html.Div(
        [
            dmc.Paper(
                [
                    dmc.Group(
                        [
                            (
                                html.Img(
                                    src=engine_icon,
                                    style={"width": "24px", "height": "24px"},
                                )
                                if use_image_icon
                                else DashIconify(icon=engine_icon, width=24)
                            ),
                            dmc.Stack(
                                [
                                    dmc.Text(workflow.name, fw="bold", size="sm"),
                                    dmc.Group(
                                        [
                                            dmc.Badge(
                                                workflow.engine.name, color="blue", size="xs"
                                            ),
                                            dmc.Badge(
                                                f"{len(workflow.data_collections)} DCs",
                                                color="green",
                                                size="xs",
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                ],
                                gap="xs",
                            ),
                        ],
                        gap="sm",
                        justify="flex-start",
                    ),
                    dmc.Stack(
                        [
                            dmc.Group(
                                [
                                    dmc.Text("Repository:", size="xs", fw="bold", c="gray"),
                                    dmc.Anchor(
                                        workflow.repository_url.split("/")[-1]
                                        if workflow.repository_url
                                        else "N/A",
                                        href=workflow.repository_url,
                                        target="_blank",
                                        size="xs",
                                        c="blue",
                                    )
                                    if workflow.repository_url
                                    else dmc.Text("N/A", size="xs", c="gray"),
                                ],
                                gap="xs",
                            ),
                            dmc.Group(
                                [
                                    dmc.Text("Catalog:", size="xs", fw="bold", c="gray"),
                                    dmc.Text(
                                        workflow.catalog.name if workflow.catalog else "N/A",
                                        size="xs",
                                        c="gray",
                                    ),
                                ],
                                gap="xs",
                            ),
                            dmc.Group(
                                [
                                    dmc.Text("Version:", size="xs", fw="bold", c="gray"),
                                    dmc.Text(
                                        workflow.version if workflow.version else "N/A",
                                        size="xs",
                                        c="gray",
                                    ),
                                ],
                                gap="xs",
                            ),
                        ],
                        gap="xs",
                        mt="sm",
                    ),
                ],
                withBorder=True,
                shadow="sm" if not is_selected else "md",
                radius="md",
                p="md",
                # bg="var(--mantine-color-teal-5)" if is_selected else "var(--app-surface-color)",
                style={
                    "cursor": "pointer",
                    "transition": "all 0.2s ease",
                    "border": "2px solid var(--mantine-color-teal-6)"
                    if is_selected
                    else "1px solid var(--app-border-color)",
                },
            )
        ],
        id={"type": "workflow-card", "index": str(workflow.id)},
        n_clicks=0,
        style={"cursor": "pointer"},
    )


def _get_ag_grid_theme_class(theme: str) -> str:
    """Get the appropriate AG Grid theme class based on the theme.

    Args:
        theme: Theme name ("light", "dark", or other)

    Returns:
        AG Grid CSS theme class name
    """
    # Handle case where theme is empty dict, None, or other falsy value
    if not theme or theme == {} or theme == "{}":
        theme = "light"

    logger.debug(f"PROJECT DATA COLLECTIONS - Using theme: {theme} for AG Grid")
    return "ag-theme-alpine-dark" if theme == "dark" else "ag-theme-alpine"


def create_workflows_manager_section(workflows, selected_workflow_id=None):
    """
    Create the workflows manager section.

    Args:
        workflows: List of workflow objects
        selected_workflow_id: ID of currently selected workflow

    Returns:
        dmc.Stack: Workflows manager section
    """
    if not workflows:
        return dmc.Card(
            [
                dmc.Center(
                    [
                        dmc.Stack(
                            [
                                DashIconify(
                                    icon="mdi:workflow",
                                    width=48,
                                    color="gray",
                                    style={"opacity": 0.5},
                                ),
                                dmc.Text(
                                    "No workflows available",
                                    size="lg",
                                    c="gray",
                                    ta="center",
                                ),
                                dmc.Text(
                                    "This project doesn't have any workflows configured",
                                    size="sm",
                                    c="gray",
                                    ta="center",
                                ),
                            ],
                            align="center",
                            gap="sm",
                        )
                    ],
                    p="xl",
                ),
            ],
            withBorder=True,
            shadow="sm",
            radius="md",
            p="lg",
        )

    workflow_cards = [create_workflow_card(wf, selected_workflow_id) for wf in workflows]

    return dmc.Stack(
        [
            dmc.Group(
                [
                    DashIconify(icon="mdi:workflow", width=24, color=colors["blue"]),
                    dmc.Text("Workflows Manager", fw="bold", size="lg"),
                    dmc.Badge(
                        f"{len(workflows)} {'workflow' if len(workflows) == 1 else 'workflows'}",
                        color="blue",
                        variant="light",
                    ),
                ],
                gap="sm",
            ),
            dmc.Text(
                "Select a workflow to view its data collections",
                size="sm",
                c="gray",
            ),
            dmc.SimpleGrid(
                cols=3,
                children=workflow_cards,
                spacing="lg",
            ),
        ],
        gap="xl",
    )


def create_unified_data_collections_manager_section(
    data_collections, project_type="basic", workflow_name=None
):
    """
    Create a unified data collections manager section for both Basic and Advanced projects.

    Args:
        data_collections: List of data collection objects
        project_type: "basic" or "advanced"
        workflow_name: Name of selected workflow (for advanced projects only)

    Returns:
        dmc.Stack: Unified data collections manager section
    """
    # Overview cards
    overview_cards = dmc.SimpleGrid(
        cols=3,
        children=[
            # Total Collections card
            dmc.Card(
                [
                    dmc.Stack(
                        [
                            dmc.Group(
                                [
                                    DashIconify(
                                        icon="mdi:database-outline",
                                        width=20,
                                        color=colors["blue"],
                                    ),
                                    dmc.Text("Total Collections", fw="bold", size="sm"),
                                ],
                                justify="center",
                                align="center",
                                gap="xs",
                            ),
                            dmc.Center(
                                dmc.Text(
                                    str(len(data_collections)) if data_collections else "0",
                                    size="xl",
                                    fw="bold",
                                    c=colors["blue"],
                                )
                            ),
                            dmc.Center(dmc.Text("Data Collections", size="xs", c="gray")),
                        ],
                        gap="sm",
                        align="center",
                    )
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                p="lg",
            ),
            # Metatypes card
            dmc.Card(
                [
                    dmc.Stack(
                        [
                            dmc.Group(
                                [
                                    DashIconify(
                                        icon="mdi:tag-multiple",
                                        width=20,
                                        color=colors["green"],
                                    ),
                                    dmc.Text("Collection Types", fw="bold", size="sm"),
                                ],
                                justify="center",
                                align="center",
                                gap="xs",
                            ),
                            dmc.Group(
                                [
                                    dmc.Stack(
                                        [
                                            dmc.Text(
                                                str(
                                                    sum(
                                                        1
                                                        for dc in data_collections
                                                        if dc.config.metatype
                                                        and dc.config.metatype.lower()
                                                        == "aggregate"
                                                    )
                                                )
                                                if data_collections
                                                else "0",
                                                size="lg",
                                                fw="bold",
                                                c=colors["green"],
                                                ta="center",
                                            ),
                                            dmc.Text("Aggregate", size="xs", c="gray", ta="center"),
                                        ],
                                        gap="xs",
                                        align="center",
                                    ),
                                    dmc.Divider(
                                        orientation="vertical",
                                        style={"height": "50px", "alignSelf": "center"},
                                    ),
                                    dmc.Stack(
                                        [
                                            dmc.Text(
                                                str(
                                                    sum(
                                                        1
                                                        for dc in data_collections
                                                        if dc.config.metatype
                                                        and dc.config.metatype.lower() == "metadata"
                                                    )
                                                )
                                                if data_collections
                                                else "0",
                                                size="lg",
                                                fw="bold",
                                                c=colors["green"],
                                                ta="center",
                                            ),
                                            dmc.Text("Metadata", size="xs", c="gray", ta="center"),
                                        ],
                                        gap="xs",
                                        align="center",
                                    ),
                                ],
                                justify="space-around",
                                align="center",
                                style={"flex": 1},  # Take up remaining space in the card
                            ),
                        ],
                        gap="md",  # Add space between title and content
                        justify="center",
                    )
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                p="lg",
            ),
            # Total Size card - re-enabled with storage calculation
            dmc.Card(
                [
                    dmc.Stack(
                        [
                            dmc.Group(
                                [
                                    DashIconify(
                                        icon="mdi:harddisk",
                                        width=20,
                                        color=colors["orange"],
                                    ),
                                    dmc.Text("Total Storage", fw="bold", size="sm"),
                                ],
                                justify="center",
                                align="center",
                                gap="xs",
                            ),
                            html.Div(
                                id="storage-size-display",
                                style={"textAlign": "center"},
                            ),
                        ],
                        gap="sm",
                        align="center",
                    )
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                p="lg",
            ),
        ],
    )

    # Data collections list
    if data_collections:
        dc_items = []
        for dc in data_collections:
            dc_type = dc.config.type.lower()

            # Determine icon based on data collection type
            if dc_type == "table":
                dc_icon = DashIconify(
                    icon="mdi:table",
                    width=20,
                    color=colors["teal"],
                )
            elif dc_type == "multiqc":
                dc_icon = html.Img(
                    src="/assets/images/logos/multiqc.png",
                    style={"width": "20px", "height": "20px"},
                )
            elif dc_type == "image":
                dc_icon = DashIconify(
                    icon="mdi:image-area",
                    width=20,
                    color=colors["teal"],
                )
            else:
                dc_icon = DashIconify(
                    icon="mdi:file-document",
                    width=20,
                    color=colors["teal"],
                )

            # Create type-specific metadata summary row
            if dc_type == "multiqc":
                metadata_row = create_multiqc_metadata_summary(dc)
            elif dc_type == "image":
                metadata_row = create_image_dc_preview(dc)
            else:
                metadata_row = None

            # Build card content
            card_content = [
                dmc.Group(
                    [
                        # Main data collection info
                        dmc.Group(
                            [
                                dc_icon,
                                dmc.Badge(dc.config.type, color="blue", size="xs"),
                                # Only show metatype badge for non-MultiQC/Image types
                                (
                                    dmc.Badge(
                                        dc.config.metatype or "Unknown",
                                        color="gray",
                                        size="xs",
                                    )
                                    if dc_type not in ("multiqc", "image")
                                    else html.Div()  # Empty placeholder
                                ),
                                dmc.Text(dc.data_collection_tag, fw="bold", size="sm"),
                            ],
                            gap="sm",
                            align="center",
                            style={"flex": 1},
                        ),
                        # Action buttons
                        dmc.Group(
                            [
                                # Single "Manage data" entry point for all
                                # content-modification flows (overwrite for
                                # tabular DCs, modify/clear for MultiQC). The
                                # actual modal opened depends on dc_type and
                                # is decided by callbacks downstream.
                                dmc.Tooltip(
                                    dmc.ActionIcon(
                                        DashIconify(icon="mdi:database-cog", width=18),
                                        id={
                                            "type": "dc-manage-button",
                                            "index": str(
                                                getattr(dc, "id", "") or getattr(dc, "_id", "")
                                            ),
                                        },
                                        variant="subtle",
                                        color="blue",
                                        size="sm",
                                        disabled=(
                                            dc_type == "image"
                                            or (
                                                dc.config.metatype
                                                and dc.config.metatype.lower() == "aggregate"
                                            )
                                        ),
                                    ),
                                    label=(
                                        "Manage data"
                                        if dc_type in ("multiqc", "table")
                                        else "Manage data not available for this type"
                                    ),
                                    position="top",
                                ),
                                dmc.Tooltip(
                                    dmc.ActionIcon(
                                        DashIconify(icon="mdi:pencil", width=16),
                                        id={
                                            "type": "dc-edit-name-button",
                                            "index": dc.data_collection_tag,
                                        },
                                        variant="subtle",
                                        color="blue",
                                        size="sm",
                                        disabled=(
                                            dc_type in ("multiqc", "image")
                                            or (
                                                dc.config.metatype
                                                and dc.config.metatype.lower() == "aggregate"
                                            )
                                        ),
                                    ),
                                    label="Edit name",
                                    position="top",
                                ),
                                dmc.Tooltip(
                                    dmc.ActionIcon(
                                        DashIconify(icon="mdi:delete", width=16),
                                        id={
                                            "type": "dc-delete-button",
                                            "index": dc.data_collection_tag,
                                        },
                                        variant="subtle",
                                        color="red",
                                        size="sm",
                                        disabled=False,
                                    ),
                                    label="Delete",
                                    position="top",
                                ),
                            ],
                            gap="xs",
                            align="center",
                        ),
                    ],
                    justify="space-between",
                    align="center",
                ),
            ]

            # Add metadata row for MultiQC and Image types
            if metadata_row is not None:
                card_content.append(
                    html.Div(
                        metadata_row,
                        style={"marginTop": "8px", "paddingLeft": "28px"},
                    )
                )

            dc_card = html.Div(
                [
                    dmc.Card(
                        card_content,
                        withBorder=True,
                        shadow="xs",
                        radius="md",
                        p="sm",
                        style={
                            "cursor": "pointer",
                            "transition": "box-shadow 0.2s ease",
                        },
                    )
                ],
                id={"type": "data-collection-card", "index": dc.data_collection_tag},
                n_clicks=0,
                style={"cursor": "pointer"},
            )
            dc_items.append(dc_card)

        data_collections_list = dmc.Stack(dc_items, gap="sm")
    else:
        data_collections_list = dmc.Center(
            [
                dmc.Stack(
                    [
                        DashIconify(
                            icon="mdi:database-off-outline",
                            width=48,
                            color="gray",
                            style={"opacity": 0.5},
                        ),
                        dmc.Text(
                            "No data collections yet",
                            size="lg",
                            c="gray",
                            ta="center",
                        ),
                        dmc.Text(
                            "Upload your first data collection to get started",
                            size="sm",
                            c="gray",
                            ta="center",
                        ),
                    ],
                    align="center",
                    gap="sm",
                )
            ],
            p="xl",
        )

    # Create project type badge and description
    if project_type == "basic":
        project_badge = dmc.Badge("Basic Project", color="cyan", variant="light")
        description = "Managing data collections for this basic project"
    else:
        project_badge = dmc.Badge("Advanced Project", color="orange", variant="light")
        if workflow_name:
            description = f"Managing data collections for workflow: {workflow_name}"
        else:
            description = "Managing data collections for this advanced project"

    return dmc.Stack(
        [
            dmc.Group(
                [
                    DashIconify(icon="mdi:database", width=24, color=colors["teal"]),
                    dmc.Text("Data Collections Manager", fw="bold", size="lg"),
                    project_badge,
                ],
                gap="sm",
            ),
            dmc.Text(
                description,
                size="sm",
                c="gray",
            ),
            overview_cards,
            dmc.Card(
                [
                    dmc.Group(
                        [
                            dmc.Group(
                                [
                                    dmc.Text("Data Collections", fw="bold", size="lg"),
                                    dmc.Badge(
                                        f"{len(data_collections)} collections",
                                        color="teal",
                                        variant="light",
                                    ),
                                ],
                                gap="md",
                                align="center",
                            ),
                            dmc.Button(
                                "Create Data Collection",
                                id="create-data-collection-button",
                                leftSection=DashIconify(icon="mdi:plus", width=16),
                                variant="filled",
                                color="teal",
                                size="sm",
                                radius="md",
                                disabled=False,  # Will be controlled by callback
                            ),
                        ],
                        justify="space-between",
                        align="center",
                    ),
                    dmc.Divider(my="md"),
                    data_collections_list,
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                p="lg",
                mt="md",
            ),
            # Data Collection Viewer Section
            dmc.Card(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:eye", width=24, color=colors["blue"]),
                            dmc.Text("Data Collection Viewer", fw="bold", size="lg"),
                            dmc.Badge("Select a Data Collection", color="gray", variant="light"),
                        ],
                        gap="md",
                        align="center",
                    ),
                    dmc.Divider(my="md"),
                    html.Div(id="data-collection-viewer-content"),
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                p="lg",
                mt="xl",
            ),
            # Hidden modals for data collection actions
            html.Div(id="dc-action-modals-container", children=[]),
        ],
        gap="xl",
    )


def create_basic_project_data_collections_section(data_collections):
    """
    Legacy wrapper for basic projects - redirects to unified function.

    Args:
        data_collections: List of data collection objects

    Returns:
        dmc.Stack: Data collections section for basic projects
    """
    return create_unified_data_collections_manager_section(
        data_collections=data_collections, project_type="basic"
    )


def create_data_collections_manager_section(workflow=None):
    """
    Create the data collections manager section based on selected workflow.

    Args:
        workflow: Selected workflow object (None if no workflow selected)

    Returns:
        dmc.Stack: Data collections manager section
    """
    if not workflow:
        return dmc.Card(
            [
                dmc.Center(
                    [
                        dmc.Stack(
                            [
                                DashIconify(
                                    icon="mdi:database-outline",
                                    width=48,
                                    color="gray",
                                    style={"opacity": 0.5},
                                ),
                                dmc.Text(
                                    "Select a workflow to continue",
                                    size="lg",
                                    c="gray",
                                    ta="center",
                                ),
                                dmc.Text(
                                    "Choose a workflow from above to view its data collections",
                                    size="sm",
                                    c="gray",
                                    ta="center",
                                ),
                            ],
                            align="center",
                            gap="sm",
                        )
                    ],
                    p="xl",
                ),
            ],
            withBorder=True,
            shadow="sm",
            radius="md",
            p="lg",
        )

    # Use the unified function for advanced projects with selected workflow
    data_collections = workflow.data_collections if workflow else []
    workflow_name = getattr(workflow, "name", "Unknown Workflow")

    return create_unified_data_collections_manager_section(
        data_collections=data_collections, project_type="advanced", workflow_name=workflow_name
    )


# =============================================================================
# Data Collection Viewer Helper Functions
# =============================================================================


def _extract_dc_info(data_collection) -> tuple[str, str, str, str]:
    """Extract data collection info from dict or object.

    Args:
        data_collection: Data collection dict or object.

    Returns:
        Tuple of (dc_tag, dc_id, dc_type, dc_metatype).
    """
    if isinstance(data_collection, dict):
        dc_tag = data_collection.get("data_collection_tag", "Unknown")
        dc_id = data_collection.get("id", "unknown")
        dc_type = data_collection.get("config", {}).get("type", "unknown")
        dc_metatype = data_collection.get("config", {}).get("metatype", "Unknown")
    else:
        dc_tag = getattr(data_collection, "data_collection_tag", "Unknown")
        dc_id = getattr(data_collection, "id", "unknown")
        dc_type = getattr(data_collection.config, "type", "unknown")
        dc_metatype = getattr(data_collection.config, "metatype", "Unknown")

    return dc_tag, dc_id, dc_type, dc_metatype


def _get_dc_icon(dc_type: str):
    """Get icon component based on data collection type.

    Args:
        dc_type: Data collection type string.

    Returns:
        Icon component (DashIconify or html.Img).
    """
    if dc_type.lower() == "table":
        return DashIconify(icon="mdi:table", width=32, color=colors["teal"])
    elif dc_type.lower() == "multiqc":
        return html.Img(
            src="/assets/images/logos/multiqc.png",
            style={"width": "32px", "height": "32px"},
        )
    else:
        return DashIconify(icon="mdi:file-document", width=32, color=colors["teal"])


def _create_dc_header_section(dc_tag: str, dc_type: str) -> dmc.Group:
    """Create the header section with icon and tag.

    Args:
        dc_tag: Data collection tag.
        dc_type: Data collection type.

    Returns:
        Group component with header.
    """
    return dmc.Group(
        [
            _get_dc_icon(dc_type),
            dmc.Stack([dmc.Text(dc_tag, fw="bold", size="xl")]),
        ],
        gap="md",
        align="center",
    )


def _create_configuration_card(data_collection, dc_type: str, dc_metatype: str) -> dmc.Card:
    """Create the configuration details card.

    Args:
        data_collection: Data collection dict or object.
        dc_type: Data collection type.
        dc_metatype: Data collection metatype.

    Returns:
        Card component with configuration details.
    """
    dc_id_display = (
        data_collection.get("id")
        if isinstance(data_collection, dict)
        else str(getattr(data_collection, "id", "N/A"))
    )

    metatype_row = (
        dmc.Group(
            [
                dmc.Text("Metatype:", size="sm", fw="bold", c="gray"),
                dmc.Badge(dc_metatype or "Unknown", color="gray", size="xs"),
            ],
            justify="space-between",
        )
        if dc_type.lower() != "multiqc"
        else html.Div()
    )

    return dmc.Card(
        [
            dmc.Group(
                [
                    DashIconify(icon="mdi:cog", width=20, color=colors["blue"]),
                    dmc.Text("Configuration", fw="bold", size="md"),
                ],
                gap="xs",
                align="center",
            ),
            dmc.Divider(my="sm"),
            dmc.Stack(
                [
                    dmc.Group(
                        [
                            dmc.Text("Data Collection ID:", size="sm", fw="bold", c="gray"),
                            dmc.Text(dc_id_display, size="sm", ff="monospace"),
                        ],
                        justify="space-between",
                    ),
                    dmc.Group(
                        [
                            dmc.Text("Type:", size="sm", fw="bold", c="gray"),
                            dmc.Badge(dc_type, color="blue", size="xs"),
                        ],
                        justify="space-between",
                    ),
                    metatype_row,
                ],
                gap="xs",
            ),
        ],
        withBorder=True,
        shadow="xs",
        radius="md",
        p="md",
    )


def _get_storage_location(data_collection, dc_type: str, dc_id: str, delta_info) -> str:
    """Get storage location based on data collection type.

    Args:
        data_collection: Data collection dict or object.
        dc_type: Data collection type.
        dc_id: Data collection ID.
        delta_info: Delta table information.

    Returns:
        Storage location string.
    """
    if dc_type.lower() == "multiqc":
        flex_metadata = getattr(data_collection, "flexible_metadata", {})
        return (
            flex_metadata.get("s3_location")
            or flex_metadata.get("primary_s3_location")
            or f"s3://depictio-bucket/{dc_id}/"
        )
    else:
        return delta_info.get("delta_table_location", "N/A") if delta_info else "N/A"


def _get_data_format(data_collection) -> str:
    """Get data format from data collection.

    Args:
        data_collection: Data collection dict or object.

    Returns:
        Format string.
    """
    if isinstance(data_collection, dict):
        return (
            data_collection.get("config", {}).get("dc_specific_properties", {}).get("format")
            or "Unknown"
        )
    elif hasattr(data_collection, "config"):
        dc_props = getattr(data_collection.config, "dc_specific_properties", None)
        return getattr(dc_props, "format", "Unknown") if dc_props else "Unknown"
    return "Unknown"


def _create_storage_card(data_collection, dc_type: str, dc_id: str, delta_info) -> dmc.Card:
    """Create the storage details card.

    Args:
        data_collection: Data collection dict or object.
        dc_type: Data collection type.
        dc_id: Data collection ID.
        delta_info: Delta table information.

    Returns:
        Card component with storage details.
    """
    is_multiqc = dc_type.lower() == "multiqc"
    icon_name = "mdi:cloud" if is_multiqc else "mdi:delta"
    title = "S3 Storage Details" if is_multiqc else "Delta Table Details"
    location_label = "S3 Location:" if is_multiqc else "Delta Location:"

    storage_location = _get_storage_location(data_collection, dc_type, dc_id, delta_info)

    last_aggregated = "Never"
    if delta_info and delta_info.get("aggregation"):
        last_aggregated = delta_info.get("aggregation", [{}])[-1].get("aggregation_time", "Never")

    data_format = _get_data_format(data_collection)

    return dmc.Card(
        [
            dmc.Group(
                [
                    DashIconify(icon=icon_name, width=20, color=colors["green"]),
                    dmc.Text(title, fw="bold", size="md"),
                ],
                gap="xs",
                align="center",
            ),
            dmc.Divider(my="sm"),
            dmc.Stack(
                [
                    dmc.Group(
                        [
                            dmc.Text(location_label, size="sm", fw="bold", c="gray"),
                            dmc.Text(storage_location, size="sm", ff="monospace"),
                        ],
                        justify="space-between",
                    ),
                    dmc.Group(
                        [
                            dmc.Text("Last Aggregated:", size="sm", fw="bold", c="gray"),
                            dmc.Text(last_aggregated, size="sm"),
                        ],
                        justify="space-between",
                    ),
                    dmc.Group(
                        [
                            dmc.Text("Format:", size="sm", fw="bold", c="gray"),
                            dmc.Badge(data_format, color="blue", size="xs"),
                        ],
                        justify="space-between",
                    ),
                    dmc.Group(
                        [
                            dmc.Text("Size:", size="sm", fw="bold", c="gray"),
                            dmc.Text(
                                get_data_collection_size_display(data_collection),
                                size="sm",
                                ff="monospace",
                            ),
                        ],
                        justify="space-between",
                    ),
                ],
                gap="xs",
            ),
        ],
        withBorder=True,
        shadow="xs",
        radius="md",
        p="md",
    )


def _create_additional_info_card(data_collection, workflow_info) -> dmc.Card:
    """Create the additional information card.

    Args:
        data_collection: Data collection dict or object.
        workflow_info: Workflow information dict.

    Returns:
        Card component with additional info.
    """
    description = (
        data_collection.get("description")
        if isinstance(data_collection, dict)
        else getattr(data_collection, "description", "No description available")
    )

    created_time = workflow_info.get("registration_time", "N/A") if workflow_info else "N/A"

    return dmc.Card(
        [
            dmc.Group(
                [
                    DashIconify(icon="mdi:information-outline", width=20, color=colors["orange"]),
                    dmc.Text("Additional Information", fw="bold", size="md"),
                ],
                gap="xs",
                align="center",
            ),
            dmc.Divider(my="sm"),
            dmc.Stack(
                [
                    dmc.Group(
                        [
                            dmc.Text("Description:", size="sm", fw="bold", c="gray"),
                            dmc.Text(description, size="sm"),
                        ],
                        justify="flex-start",
                        align="flex-start",
                    ),
                    dmc.Group(
                        [
                            dmc.Text("Created:", size="sm", fw="bold", c="gray"),
                            dmc.Text(created_time, size="sm"),
                        ],
                        gap="xs",
                    ),
                ],
                gap="sm",
            ),
        ],
        withBorder=True,
        shadow="xs",
        radius="md",
        p="md",
        mt="md",
    )


def _create_data_preview_card(dc_type: str, dc_id: str) -> dmc.Card:
    """Create the data preview card (table or MultiQC metadata).

    Args:
        dc_type: Data collection type.
        dc_id: Data collection ID.

    Returns:
        Card component with data preview controls.
    """
    if dc_type.lower() == "multiqc":
        return dmc.Card(
            [
                dmc.Group(
                    [
                        html.Img(
                            src="/assets/images/logos/multiqc.png",
                            style={"width": "20px", "height": "20px"},
                        ),
                        dmc.Text("MultiQC Report Metadata", fw="bold", size="md"),
                    ],
                    gap="xs",
                    align="center",
                ),
                dmc.Divider(my="sm"),
                html.Div(id={"type": "dc-viewer-multiqc-metadata-content", "index": dc_id}),
            ],
            withBorder=True,
            shadow="xs",
            radius="md",
            p="md",
            mt="md",
        )

    return dmc.Card(
        [
            dmc.Group(
                [
                    DashIconify(icon="mdi:table-eye", width=20, color=colors["teal"]),
                    dmc.Text("Data Preview", fw="bold", size="md"),
                ],
                gap="xs",
                align="center",
            ),
            dmc.Divider(my="sm"),
            dmc.Stack(
                [
                    dmc.Group(
                        [
                            dmc.NumberInput(
                                id="dc-viewer-row-limit",
                                value=1000,
                                min=100,
                                max=10000,
                                step=100,
                                w="120px",
                                style={"display": "none"},
                            ),
                            dmc.Button(
                                "Load Data",
                                id="dc-viewer-load-btn",
                                leftSection=DashIconify(icon="mdi:table-refresh"),
                                variant="light",
                                size="sm",
                            ),
                        ],
                        gap="md",
                        align="center",
                    ),
                    dmc.Divider(),
                    html.Div(id="dc-viewer-data-content"),
                ],
                gap="md",
            ),
        ],
        withBorder=True,
        shadow="xs",
        radius="md",
        p="md",
        mt="md",
    )


def _create_empty_dc_viewer() -> dmc.Center:
    """Create empty state for data collection viewer.

    Returns:
        Center component with empty state message.
    """
    return dmc.Center(
        [
            dmc.Stack(
                [
                    DashIconify(
                        icon="mdi:table-eye",
                        width=48,
                        color="gray",
                        style={"opacity": 0.5},
                    ),
                    dmc.Text(
                        "No data collection selected",
                        size="lg",
                        c="gray",
                        ta="center",
                    ),
                    dmc.Text(
                        "Select a data collection above to preview its contents",
                        size="sm",
                        c="gray",
                        ta="center",
                    ),
                ],
                align="center",
                gap="sm",
            )
        ],
        p="xl",
    )


def create_data_collection_viewer_content(
    data_collection=None, delta_info=None, workflow_info=None, theme="light"
):
    """Create the content for the data collection viewer section.

    Args:
        data_collection: Selected data collection object or data.
        delta_info: Delta table information from API.
        workflow_info: Workflow information containing registration_time.
        theme: Current theme ("light" or "dark") for AG Grid styling.

    Returns:
        html.Div: Data collection viewer content.
    """
    if not data_collection:
        return _create_empty_dc_viewer()

    # Extract data collection info
    dc_tag, dc_id, dc_type, dc_metatype = _extract_dc_info(data_collection)

    # Build sections
    header_section = _create_dc_header_section(dc_tag, dc_type)
    config_card = _create_configuration_card(data_collection, dc_type, dc_metatype)
    storage_card = _create_storage_card(data_collection, dc_type, dc_id, delta_info)
    additional_info_card = _create_additional_info_card(data_collection, workflow_info)
    data_preview_card = _create_data_preview_card(dc_type, dc_id)

    return dmc.Stack(
        [
            header_section,
            dmc.Divider(my="md"),
            dmc.SimpleGrid(
                cols=2,
                spacing="lg",
                children=[config_card, storage_card],
            ),
            additional_info_card,
            data_preview_card,
        ],
        gap="md",
    )


def create_data_collections_landing_ui():
    """
    Create the landing UI for data collections management.

    Returns:
        html.Div: The complete landing UI layout
    """
    # Unified data collection modal (handles create, update, and clear modes
    # via a sibling `data-collection-modal-mode` Store; section visibility is
    # toggled by callbacks rather than rebuilt per mode).
    data_collection_modal, data_collection_modal_id = create_data_collection_modal()
    # Create DC link modal
    dc_link_modal, dc_link_modal_id = create_dc_link_modal()

    return html.Div(
        [
            # Store components for state management
            dcc.Store(id="project-data-store", data={}),
            dcc.Store(id="selected-workflow-store", data=None),
            dcc.Store(id="selected-data-collection-store", data=None),
            # Mode store driving the unified modal:
            #   {"mode": "create" | "update" | "clear" | None,
            #    "dc_id": str | None,
            #    "expected_name": str | None}
            dcc.Store(
                id="data-collection-modal-mode",
                data={"mode": None, "dc_id": None, "expected_name": None},
            ),
            # Interval to trigger MultiQC metadata loading after page render
            dcc.Interval(
                id="multiqc-metadata-interval",
                interval=2000,  # 2 second delay to ensure DC cards are rendered
                n_intervals=0,
                max_intervals=1,  # Fire only once
            ),
            # Unified data collection modal (create/update/clear)
            data_collection_modal,
            # DC link creation modal
            dc_link_modal,
            # Header section
            dmc.Stack(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:database", width=32, color=colors["teal"]),
                            dmc.Title(
                                "Project Data Manager",
                                order=2,
                                style={"color": colors["teal"]},
                            ),
                        ],
                        gap="md",
                    ),
                    dmc.Text(
                        "Manage workflows and data collections for your project",
                        size="lg",
                        c="gray",
                    ),
                    # Project type indicator
                    html.Div(id="project-type-indicator"),
                    # Template origin info (populated by callback if project is from a template)
                    html.Div(id="template-origin-info"),
                    dmc.Divider(),
                ],
                gap="lg",
                mb="xl",
            ),
            # Workflows Manager Section
            html.Div(id="workflows-manager-section", style={"marginBottom": "3rem"}),
            # Data Collections Manager Section
            html.Div(id="data-collections-manager-section", style={"marginTop": "2rem"}),
            # DC Links Manager Section
            html.Div(
                id="dc-links-manager-section",
                style={"marginTop": "2rem"},
            ),
            # Data Collection Joins Visualization Section
            html.Div(
                id="joins-visualization-section",
                children=[
                    dmc.Divider(
                        label="Data Collection Relationships", labelPosition="center", my="xl"
                    ),
                    create_joins_visualization_section(
                        elements=[],  # Will be populated by callback
                        theme="light",  # Will be updated by theme callback
                    ),
                ],
                style={"display": "none", "marginTop": "3rem"},  # Hidden by default
            ),
            # Hidden placeholder for future content
            html.Div(id="data-collections-content", style={"display": "none"}),
        ],
        style={"padding": "2rem", "maxWidth": "1400px", "margin": "0 auto"},
    )


# Main layout for the data collections management page
layout = create_data_collections_landing_ui()


# =============================================================================
# Helper functions for project data callbacks
# =============================================================================


def _find_data_collection_by_tag(
    project_data: dict, dc_tag: str, selected_workflow_id: str | None = None
) -> tuple[dict | None, str | None, dict | None]:
    """
    Find a data collection by its tag in project data.

    Args:
        project_data: Project data dictionary containing data collections.
        dc_tag: Data collection tag to search for.
        selected_workflow_id: Optional workflow ID for advanced projects.

    Returns:
        Tuple of (data_collection_dict, dc_id, workflow_info)
    """
    selected_dc = None
    dc_id = None
    workflow_info = None

    if project_data.get("project_type") == "basic":
        data_collections = project_data.get("data_collections", [])
        for dc in data_collections:
            if dc.get("data_collection_tag") == dc_tag:
                selected_dc = dc
                dc_id = dc.get("id")
                break
    else:
        if selected_workflow_id:
            workflows = project_data.get("workflows", [])
            for workflow in workflows:
                if str(workflow.get("id")) == selected_workflow_id:
                    workflow_info = workflow
                    for dc in workflow.get("data_collections", []):
                        if dc.get("data_collection_tag") == dc_tag:
                            selected_dc = dc
                            dc_id = dc.get("id")
                            break
                    break

    return selected_dc, dc_id, workflow_info


def _build_project_store_data(
    project, project_id: str, all_data_collections: list | None = None
) -> dict:
    """
    Build project store data dictionary from project response.

    Args:
        project: ProjectResponse object.
        project_id: Project ID string.
        all_data_collections: Optional list of all data collections (for basic projects).

    Returns:
        Dictionary containing project store data.
    """
    if project.project_type == "basic":
        if all_data_collections is None:
            all_data_collections = []
            if project.data_collections:
                all_data_collections.extend(project.data_collections)
            if project.workflows:
                for workflow in project.workflows:
                    if workflow.data_collections:
                        all_data_collections.extend(workflow.data_collections)

        return {
            "project_id": project_id,
            "project_type": project.project_type,
            "workflows": [w.model_dump() for w in project.workflows] if project.workflows else [],
            "data_collections": [dc.model_dump() for dc in all_data_collections],
            "permissions": project.permissions.dict() if project.permissions else {},
        }
    else:
        return {
            "project_id": project_id,
            "project_type": project.project_type,
            "workflows": [w.model_dump() for w in project.workflows] if project.workflows else [],
            "data_collections": [dc.model_dump() for dc in project.data_collections]
            if project.data_collections
            else [],
            "permissions": project.permissions.dict() if project.permissions else {},
        }


def _create_mock_workflow_from_data(workflow_data: dict):
    """
    Create a mock workflow object from workflow data dictionary.

    Args:
        workflow_data: Dictionary containing workflow data.

    Returns:
        SimpleNamespace object mimicking a workflow.
    """
    from types import SimpleNamespace

    mock_wf = SimpleNamespace()
    mock_wf.id = workflow_data.get("id")
    mock_wf.name = workflow_data.get("name", "Unknown")
    mock_wf.engine = SimpleNamespace()
    mock_wf.engine.name = workflow_data.get("engine", {}).get("name", "unknown")
    mock_wf.data_collections = workflow_data.get("data_collections", [])
    mock_wf.repository_url = workflow_data.get("repository_url")
    mock_wf.catalog = SimpleNamespace() if workflow_data.get("catalog") else None
    if mock_wf.catalog:
        mock_wf.catalog.name = workflow_data.get("catalog", {}).get("name", "Unknown")
    mock_wf.version = workflow_data.get("version")
    return mock_wf


def _create_mock_data_collections_from_workflow(workflow_data: dict) -> list:
    """
    Create mock data collection objects from workflow data.

    Args:
        workflow_data: Dictionary containing workflow data with data_collections.

    Returns:
        List of SimpleNamespace objects mimicking data collections.
    """
    from types import SimpleNamespace

    mock_dcs = []
    if "data_collections" in workflow_data:
        for dc_data in workflow_data["data_collections"]:
            mock_dc = SimpleNamespace()
            mock_dc.data_collection_tag = dc_data.get("data_collection_tag", "Unknown DC")
            mock_dc.config = SimpleNamespace()
            mock_dc.config.type = dc_data.get("config", {}).get("type", "unknown")
            mock_dc.config.metatype = dc_data.get("config", {}).get("metatype", "Unknown")
            mock_dcs.append(mock_dc)
    return mock_dcs


def _handle_modal_result(
    success: bool, result: dict | None, project_data: dict, success_action: str
) -> tuple:
    """
    Handle modal submission result with consistent error/success handling.

    Args:
        success: Whether the operation succeeded.
        result: API result dictionary.
        project_data: Current project data for refresh.
        success_action: Description of successful action for logging.

    Returns:
        Tuple of (modal_opened, updated_project_data, error_message, error_style)
    """
    from datetime import datetime

    if success and result and result.get("success"):
        logger.info(f"{success_action}: {result.get('message')}")
        updated_project_data = project_data.copy()
        updated_project_data["refresh_timestamp"] = datetime.now().isoformat()
        return False, updated_project_data, "", {"display": "none"}
    else:
        error_msg = result.get("message", "Unknown error") if result else "API call failed"
        logger.error(f"Failed: {error_msg}")
        return (
            dash.no_update,
            dash.no_update,
            f"Operation failed: {error_msg}",
            {"display": "block"},
        )


def register_project_data_collections_callbacks(app):
    """
    Register callbacks for project data collections functionality.

    Args:
        app: Dash application instance
    """

    # Register the joins visualization callbacks
    register_joins_callbacks(app)

    # Callback to populate MultiQC metadata summaries in DC cards
    # Triggered by interval after page renders (avoids circular dependency)
    @app.callback(
        Output({"type": "multiqc-metadata-summary", "index": ALL}, "children"),
        Input("multiqc-metadata-interval", "n_intervals"),
        State({"type": "multiqc-metadata-summary", "index": ALL}, "id"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def populate_multiqc_summary_cards(n_intervals, summary_ids, local_data):
        """
        Populate MultiQC metadata summary badges in DC cards.

        Fetches metadata via API for each MultiQC DC and returns compact
        display showing samples, modules, and plots.

        Args:
            n_intervals: Interval trigger count (fires once after 500ms).
            summary_ids: List of pattern-matching IDs for MultiQC summaries.
            local_data: Local storage containing access token.

        Returns:
            List of components to populate each summary div.
        """
        print(
            f"🔍 populate_multiqc_summary_cards triggered: n_intervals={n_intervals}, "
            f"summary_ids={summary_ids}",
            flush=True,
        )

        if not summary_ids:
            print("No summary_ids found, returning empty list", flush=True)
            return []

        print(f"Processing {len(summary_ids)} MultiQC summary IDs: {summary_ids}", flush=True)

        if not local_data or not local_data.get("access_token"):
            logger.warning("No access token, returning auth required")
            return [dmc.Text("Auth required", size="xs", c="gray") for _ in summary_ids]

        access_token = local_data["access_token"]
        results = []

        for summary_id in summary_ids:
            dc_id = summary_id.get("index", "")
            if not dc_id:
                results.append(dmc.Text("Invalid DC", size="xs", c="red"))
                continue

            try:
                # Fetch MultiQC metadata via API
                print(f"Fetching MultiQC data for DC: {dc_id}", flush=True)
                multiqc_data = api_call_fetch_multiqc_report(dc_id, access_token)
                print(f"MultiQC API response: {multiqc_data is not None}", flush=True)

                if not multiqc_data:
                    print(f"No MultiQC data returned for {dc_id}", flush=True)
                    results.append(
                        dmc.Text(
                            "Metadata not yet extracted",
                            size="xs",
                            c="gray",
                            fs="italic",
                        )
                    )
                    continue

                # Extract metadata
                metadata = multiqc_data.get("metadata", {})
                print(
                    f"MultiQC metadata: canonical_samples={len(metadata.get('canonical_samples', []))}, "
                    f"modules={metadata.get('modules', [])}, plots_keys={list(metadata.get('plots', {}).keys())}",
                    flush=True,
                )
                modules = metadata.get("modules", [])
                plots = metadata.get("plots", {})

                # Use canonical_samples (already filtered) or fallback to filtering
                canonical_samples = metadata.get("canonical_samples", [])
                if not canonical_samples:
                    samples = metadata.get("samples", [])
                    canonical_samples = [
                        s
                        for s in samples
                        if not any(
                            suffix in s
                            for suffix in [
                                "_1",
                                "_2",
                                "_R1",
                                "_R2",
                                " - First read",
                                " - Second read",
                                " - Adapter",
                                " - adapter",
                            ]
                        )
                    ]

                # Build sample badges (show up to 12 samples)
                max_samples_shown = 12
                sample_badges = [
                    dmc.Badge(sample, color="blue", size="xs", variant="light")
                    for sample in sorted(canonical_samples)[:max_samples_shown]
                ]
                if len(canonical_samples) > max_samples_shown:
                    sample_badges.append(
                        dmc.Badge(
                            f"+{len(canonical_samples) - max_samples_shown} more",
                            color="blue",
                            size="xs",
                            variant="outline",
                        )
                    )

                # Build module badges
                module_badges = [
                    dmc.Badge(module, color="green", size="xs", variant="light")
                    for module in sorted(modules)
                ]

                # Flatten plot names from nested structure
                plot_names = []
                if isinstance(plots, dict):
                    for module_plots in plots.values():
                        if isinstance(module_plots, list):
                            for plot in module_plots:
                                if isinstance(plot, str):
                                    plot_names.append(plot)
                                elif isinstance(plot, dict):
                                    plot_names.extend(plot.keys())

                max_plots_shown = 8
                plot_badges = [
                    dmc.Badge(plot_name, color="orange", size="xs", variant="light")
                    for plot_name in plot_names[:max_plots_shown]
                ]
                if len(plot_names) > max_plots_shown:
                    plot_badges.append(
                        dmc.Badge(
                            f"+{len(plot_names) - max_plots_shown} more",
                            color="orange",
                            size="xs",
                            variant="outline",
                        )
                    )

                # Create display with sections
                print(
                    f"Building display: {len(canonical_samples)} samples, "
                    f"{len(modules)} modules, {len(plot_names)} plots",
                    flush=True,
                )
                results.append(
                    dmc.Stack(
                        [
                            # Samples row
                            dmc.Group(
                                [
                                    dmc.Text(
                                        f"Samples ({len(canonical_samples)}):", size="xs", fw=500
                                    ),
                                    dmc.Group(sample_badges, gap=4, style={"flexWrap": "wrap"}),
                                ],
                                gap="xs",
                                align="flex-start",
                            )
                            if sample_badges
                            else None,
                            # Modules row
                            dmc.Group(
                                [
                                    dmc.Text(f"Modules ({len(modules)}):", size="xs", fw=500),
                                    dmc.Group(module_badges, gap=4, style={"flexWrap": "wrap"}),
                                ],
                                gap="xs",
                                align="flex-start",
                            )
                            if module_badges
                            else None,
                            # Plots row
                            dmc.Group(
                                [
                                    dmc.Text(f"Plots ({len(plot_names)}):", size="xs", fw=500),
                                    dmc.Group(plot_badges, gap=4, style={"flexWrap": "wrap"}),
                                ],
                                gap="xs",
                                align="flex-start",
                            )
                            if plot_badges
                            else None,
                        ],
                        gap=4,
                    )
                )

            except Exception as e:
                print(f"Failed to fetch MultiQC metadata for {dc_id}: {e}", flush=True)
                results.append(
                    dmc.Text(
                        "Error loading metadata",
                        size="xs",
                        c="red",
                    )
                )

        return results

    # Data collection viewer data visualization callback
    @app.callback(
        Output("dc-viewer-data-content", "children"),
        [
            Input("dc-viewer-load-btn", "n_clicks"),
            Input("dc-viewer-row-limit", "value"),
        ],
        [
            dash.State("selected-data-collection-store", "data"),
            dash.State("project-data-store", "data"),
            dash.State("local-store", "data"),
            dash.State("theme-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def load_dc_viewer_data(
        n_clicks, row_limit, selected_dc_data, project_data, local_data, theme_data
    ):
        """
        Load and display data in the data collection viewer using AG Grid.

        Fetches data from the selected data collection's Delta table and renders
        it in an AG Grid component with pagination, sorting, and filtering.

        Args:
            n_clicks: Number of times load button has been clicked.
            row_limit: Maximum number of rows to load from the Delta table.
            selected_dc_data: Selected data collection tag from store.
            project_data: Project data dictionary containing data collections.
            local_data: Local storage data containing access token.
            theme_data: Current theme for AG Grid styling.

        Returns:
            Dash component containing AG Grid with data or error alert.
        """
        if not n_clicks or not selected_dc_data:
            return dmc.Center(
                [
                    dmc.Text(
                        "Click 'Load Data' to preview the data collection contents",
                        size="sm",
                        c="gray",
                        ta="center",
                    )
                ],
                py="xl",
            )

        theme = theme_data or "light"
        try:
            # selected_dc_data is the selected_dc_tag (string), not the DC ID
            # We need to find the actual DC ID from project_data using the tag
            selected_dc_tag = selected_dc_data
            selected_dc_id = None

            if not isinstance(project_data, dict):
                return dmc.Alert("Invalid project data format", color="red")

            # Find the data collection ID based on the tag
            if project_data.get("project_type") == "basic":
                # For basic projects, look in direct data collections
                data_collections = project_data.get("data_collections", [])
                for dc in data_collections:
                    if dc.get("data_collection_tag") == selected_dc_tag:
                        selected_dc_id = dc.get("id")
                        break
            else:
                # For advanced projects, look in workflows
                workflows = project_data.get("workflows", [])
                for workflow in workflows:
                    for dc in workflow.get("data_collections", []):
                        if dc.get("data_collection_tag") == selected_dc_tag:
                            selected_dc_id = dc.get("id")
                            break
                    if selected_dc_id:
                        break

            if not selected_dc_id:
                return dmc.Alert(
                    f"Could not find data collection ID for tag: {selected_dc_tag}", color="red"
                )

            # Handle project_data - could be string or dict
            if isinstance(project_data, dict):
                project_type = project_data.get("type", "basic")
            else:
                project_type = "basic"  # Default fallback
            workflow_id = None

            if project_type == "advanced" and isinstance(project_data, dict):
                # For advanced projects, get workflow from stored data
                workflows = project_data.get("workflows", [])
                if workflows:
                    # Use first workflow for now
                    workflow_id = workflows[0].get("id")

            # Get authentication token - handle both dict and other types
            if isinstance(local_data, dict):
                token = local_data.get("access_token")
            else:
                token = None

            # Load the dataframe
            df, error = load_data_collection_dataframe(
                workflow_id=workflow_id,
                data_collection_id=selected_dc_id,
                token=token,
                limit_rows=row_limit or 1000,
            )

            if error:
                return dmc.Alert(
                    f"Error loading data: {error}",
                    color="red",
                    title="Loading Error",
                )

            if df is None or df.height == 0:
                return dmc.Alert(
                    "No data found in the selected data collection.",
                    color="yellow",
                    title="No Data",
                )

            # Convert to pandas for AG Grid (more compatible)
            df_pd = df.to_pandas()

            # Handle column names with dots - rename DataFrame columns for AG Grid compatibility
            column_mapping = {}
            for col in df_pd.columns:
                if "." in col:
                    safe_col_name = col.replace(".", "_")
                    column_mapping[col] = safe_col_name
                    logger.debug(
                        f"🔍 DC Viewer: Found column with dot: '{col}', mapping to '{safe_col_name}'"
                    )
                else:
                    column_mapping[col] = col

            # Rename DataFrame columns to safe names
            df_pd = df_pd.rename(columns=column_mapping)

            # Create column definitions
            column_defs = []
            original_columns = list(column_mapping.keys())
            for original_col in original_columns:
                safe_col = column_mapping[original_col]

                col_def = {
                    "headerName": original_col,  # Keep original name for display
                    "field": safe_col,  # Use safe name for field reference
                    "filter": True,
                    "sortable": True,
                    "resizable": True,
                }

                # Set appropriate column types based on the DataFrame data
                if df_pd[safe_col].dtype in ["int64", "float64"]:
                    col_def["type"] = "numericColumn"
                elif df_pd[safe_col].dtype == "bool":
                    col_def["cellRenderer"] = "agCheckboxCellRenderer"
                    col_def["cellEditor"] = "agCheckboxCellEditor"

                column_defs.append(col_def)

            # Create AG Grid
            grid = dag.AgGrid(
                id="dc-viewer-grid",
                columnDefs=column_defs,
                rowData=df_pd.to_dict("records"),
                defaultColDef={
                    "filter": True,
                    "sortable": True,
                    "resizable": True,
                    "minWidth": 100,
                },
                dashGridOptions={
                    "pagination": True,
                    "paginationPageSize": 25,
                    "domLayout": "normal",
                    "animateRows": True,
                },
                style={"height": "400px", "width": "100%"},
                className=_get_ag_grid_theme_class(theme),
            )

            # Create summary info
            summary = dmc.Group(
                [
                    dmc.Text(
                        f"Showing {min(row_limit or 1000, df.height):,} of {df.height:,} rows",
                        size="sm",
                        c="gray",
                    ),
                    dmc.Text(f"{df.width} columns", size="sm", c="gray"),
                ],
                gap="lg",
            )

            return dmc.Stack([summary, dmc.Divider(), grid], gap="sm")

        except Exception as e:
            logger.error(f"Error in DC viewer data callback: {e}")
            return dmc.Alert(
                f"Unexpected error: {str(e)}",
                color="red",
                title="Error",
            )

    @app.callback(
        [
            Output("project-data-store", "data"),
            Output("workflows-manager-section", "children"),
            Output("data-collections-manager-section", "children"),
            Output("project-type-indicator", "children"),
            Output("template-origin-info", "children"),
        ],
        [
            Input("url", "pathname"),
            Input("local-store", "data"),
            Input("project-data-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def load_project_data_and_workflows(pathname, local_data, project_data_store):
        """
        Load project data and populate workflows manager based on project type.

        Handles initial page load and data refresh. For basic projects, flattens
        data collections from workflows. For advanced projects, displays workflow
        manager with selectable workflows.

        Args:
            pathname: Current URL pathname containing project ID.
            local_data: Local storage data containing access token.
            project_data_store: Existing project data store (for refresh detection).

        Returns:
            Tuple of (project_store_data, workflows_section, data_collections_section,
                      project_type_indicator)
        """
        ctx_trigger = ctx.triggered_id

        # If triggered by project-data-store change (refresh), handle differently
        if ctx_trigger == "project-data-store" and project_data_store:
            # Only refresh the data collections section, keep other sections unchanged
            try:
                project_id = project_data_store.get("project_id")
                if not project_id or not local_data or not local_data.get("access_token"):
                    return (
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )

                # Fetch fresh project data from API
                project_data = api_call_fetch_project_by_id(project_id, local_data["access_token"])
                if not project_data:
                    return (
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )

                project = ProjectResponse.model_validate(project_data)

                # Update the stored project data with fresh data
                if project.project_type == "basic":
                    all_data_collections = []
                    if project.data_collections:
                        all_data_collections.extend(project.data_collections)
                    if project.workflows:
                        for workflow in project.workflows:
                            if workflow.data_collections:
                                all_data_collections.extend(workflow.data_collections)

                    updated_project_store_data = {
                        "project_id": project_id,
                        "project_type": project.project_type,
                        "workflows": [w.model_dump() for w in project.workflows]
                        if project.workflows
                        else [],
                        "data_collections": [dc.model_dump() for dc in all_data_collections],
                        "joins": [j.model_dump() for j in project.joins] if project.joins else [],
                        "links": [lnk.model_dump() for lnk in project.links]
                        if project.links
                        else [],
                        "permissions": project.permissions.dict() if project.permissions else {},
                    }
                    data_collections_section = create_basic_project_data_collections_section(
                        all_data_collections
                    )
                else:
                    updated_project_store_data = {
                        "project_id": project_id,
                        "project_type": project.project_type,
                        "workflows": [w.model_dump() for w in project.workflows]
                        if project.workflows
                        else [],
                        "data_collections": [dc.model_dump() for dc in project.data_collections]
                        if project.data_collections
                        else [],
                        "joins": [j.model_dump() for j in project.joins] if project.joins else [],
                        "links": [lnk.model_dump() for lnk in project.links]
                        if project.links
                        else [],
                        "permissions": project.permissions.dict() if project.permissions else {},
                    }
                    data_collections_section = create_data_collections_manager_section()

                return (
                    updated_project_store_data,
                    dash.no_update,
                    data_collections_section,
                    dash.no_update,
                )

            except Exception as e:
                logger.error(f"Error refreshing project data: {e}")
                return (
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                )

        # Original logic for URL/local-store changes
        if not pathname or not pathname.startswith("/project/") or not pathname.endswith("/data"):
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        # Extract project ID from URL
        try:
            project_id = pathname.split("/")[-2]
        except IndexError:
            logger.error(f"Could not extract project ID from pathname: {pathname}")
            return {}, html.Div("Error: Invalid project URL"), html.Div(), html.Div(), html.Div()

        # Get authentication token
        if not local_data or not local_data.get("access_token"):
            logger.error("No authentication token available")
            return (
                {"project_id": project_id},
                html.Div("Authentication required"),
                html.Div(),
                html.Div(),
                html.Div(),
            )

        try:
            # Fetch project data to determine project type
            project_data = api_call_fetch_project_by_id(project_id, local_data["access_token"])
            if not project_data:
                logger.error(f"Failed to fetch project data for {project_id}")
                return (
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                )
            project = ProjectResponse.model_validate(project_data)

            # Debug project information
            logger.debug(f"Project loaded: {project.name}, type: {project.project_type}")
            logger.debug(
                f"Project workflows count: {len(project.workflows) if project.workflows else 0}"
            )
            logger.debug(
                f"Project data_collections count: {len(project.data_collections) if project.data_collections else 0}"
            )

            # Store project data
            # For basic projects, flatten data collections from workflows into the main data_collections array
            if project.project_type == "basic":
                # Collect all data collections from workflows and direct data collections
                all_data_collections = []
                if project.data_collections:
                    all_data_collections.extend(project.data_collections)
                if project.workflows:
                    for workflow in project.workflows:
                        if workflow.data_collections:
                            all_data_collections.extend(workflow.data_collections)

                project_store_data = {
                    "project_id": project_id,
                    "project_type": project.project_type,
                    "workflows": [w.model_dump() for w in project.workflows]
                    if project.workflows
                    else [],
                    "data_collections": [dc.model_dump() for dc in all_data_collections],
                    "joins": [j.model_dump() for j in project.joins] if project.joins else [],
                    "links": [lnk.model_dump() for lnk in project.links] if project.links else [],
                    "permissions": project.permissions.dict() if project.permissions else {},
                }
            else:
                # Advanced projects store data collections within workflows
                project_store_data = {
                    "project_id": project_id,
                    "project_type": project.project_type,
                    "workflows": [w.model_dump() for w in project.workflows]
                    if project.workflows
                    else [],
                    "data_collections": [dc.model_dump() for dc in project.data_collections]
                    if project.data_collections
                    else [],
                    "joins": [j.model_dump() for j in project.joins] if project.joins else [],
                    "links": [lnk.model_dump() for lnk in project.links] if project.links else [],
                    "permissions": project.permissions.dict() if project.permissions else {},
                }

            # Create sections based on project type
            if project.project_type == "advanced":
                # Advanced projects: Show workflows manager with project workflows
                workflows_section = create_workflows_manager_section(project.workflows)
                data_collections_section = create_data_collections_manager_section()
            else:
                # Basic projects: Skip workflows manager, show data collections directly
                workflows_section = html.Div()  # Empty div

                # For basic projects, data collections might be stored in the workflow
                # Check both direct data collections and workflow data collections
                basic_data_collections = []
                if project.data_collections:
                    basic_data_collections.extend(project.data_collections)

                # Also check if there are data collections in workflows (common for basic projects)
                if project.workflows:
                    for workflow in project.workflows:
                        if workflow.data_collections:
                            basic_data_collections.extend(workflow.data_collections)

                logger.debug(
                    f"Basic project direct data collections count: {len(project.data_collections) if project.data_collections else 0}"
                )
                logger.debug(
                    f"Basic project workflow data collections count: {sum(len(w.data_collections) for w in project.workflows if w.data_collections) if project.workflows else 0}"
                )
                logger.debug(
                    f"Basic project total data collections count: {len(basic_data_collections)}"
                )
                logger.debug(
                    f"Basic project data collections: {[dc.data_collection_tag for dc in basic_data_collections]}"
                )

                data_collections_section = create_basic_project_data_collections_section(
                    basic_data_collections
                )

            # Create project type indicator
            project_type_indicator = create_project_type_indicator(project.project_type)

            # Create template origin section
            template_section = _create_template_origin_section(project)

            return (
                project_store_data,
                workflows_section,
                data_collections_section,
                project_type_indicator,
                template_section,
            )

        except Exception as e:
            logger.error(f"Error loading project data: {e}")
            error_msg = html.Div(
                [
                    dmc.Alert(
                        f"Error loading project: {str(e)}",
                        title="Loading Error",
                        color="red",
                        icon=DashIconify(icon="mdi:alert"),
                    )
                ]
            )
            return {"project_id": project_id}, error_msg, html.Div(), html.Div(), html.Div()

    @app.callback(
        [
            Output("selected-workflow-store", "data"),
            Output("data-collections-manager-section", "children", allow_duplicate=True),
        ],
        [Input({"type": "workflow-card", "index": dash.ALL}, "n_clicks")],
        [dash.State("project-data-store", "data")],
        prevent_initial_call=True,
    )
    def handle_workflow_selection(workflow_clicks, project_data):
        """
        Handle workflow card selection for advanced projects.

        Updates the selected workflow store and refreshes the data collections
        manager section to display the selected workflow's data collections.
        Only active for advanced project types.

        Args:
            workflow_clicks: List of click counts for workflow cards.
            project_data: Project data dictionary containing workflows.

        Returns:
            Tuple of (selected_workflow_id, data_collections_section)
        """
        if not any(workflow_clicks) or not project_data:
            return dash.no_update, dash.no_update

        # Only handle workflow selection for advanced projects
        if project_data.get("project_type") != "advanced":
            return dash.no_update, dash.no_update

        # Find which workflow was clicked
        ctx_trigger = ctx.triggered_id
        if not ctx_trigger:
            return dash.no_update, dash.no_update

        selected_workflow_id = ctx_trigger["index"]

        # Find the selected workflow from the stored data
        workflows = project_data.get("workflows", [])
        selected_workflow = None
        for wf in workflows:
            if str(wf.get("id")) == selected_workflow_id:
                selected_workflow = wf
                break

        # Create data collections section for the selected workflow
        if selected_workflow:
            # Reconstruct a mock workflow object with the necessary data
            from types import SimpleNamespace

            # Create a simple workflow-like object with the data we need
            mock_workflow = SimpleNamespace()
            mock_workflow.name = selected_workflow.get("name", "Unknown Workflow")
            mock_workflow.data_collections = []

            # Extract data collections if they exist in the workflow data
            if "data_collections" in selected_workflow:
                for dc_data in selected_workflow["data_collections"]:
                    # Create mock data collection objects
                    mock_dc = SimpleNamespace()
                    mock_dc.data_collection_tag = dc_data.get("data_collection_tag", "Unknown DC")
                    mock_dc.config = SimpleNamespace()
                    mock_dc.config.type = dc_data.get("config", {}).get("type", "unknown")
                    mock_dc.config.metatype = dc_data.get("config", {}).get("metatype", "Unknown")
                    mock_workflow.data_collections.append(mock_dc)

            data_collections_section = create_data_collections_manager_section(mock_workflow)
        else:
            data_collections_section = create_data_collections_manager_section()

        return selected_workflow_id, data_collections_section

    @app.callback(
        Output("workflows-manager-section", "children", allow_duplicate=True),
        [Input("selected-workflow-store", "data")],
        [dash.State("project-data-store", "data")],
        prevent_initial_call=True,
    )
    def update_workflow_selection_visual(selected_workflow_id, project_data):
        """
        Update workflow cards to show selected state.

        Recreates the workflows manager section with updated visual styling
        to highlight the currently selected workflow. Only active for
        advanced project types.

        Args:
            selected_workflow_id: ID of the currently selected workflow.
            project_data: Project data dictionary containing workflows.

        Returns:
            Updated workflows manager section component.
        """
        if not project_data or project_data.get("project_type") != "advanced":
            return dash.no_update

        # Get workflows from project data and reconstruct workflow objects
        workflows_data = project_data.get("workflows", [])
        if not workflows_data:
            return dash.no_update

        # For this visual update, we need to create mock workflow objects to pass to the function
        from types import SimpleNamespace

        workflows = []
        for wf_data in workflows_data:
            mock_wf = SimpleNamespace()
            mock_wf.id = wf_data.get("id")
            mock_wf.name = wf_data.get("name", "Unknown")
            mock_wf.engine = SimpleNamespace()
            mock_wf.engine.name = wf_data.get("engine", {}).get("name", "unknown")
            mock_wf.data_collections = wf_data.get("data_collections", [])
            mock_wf.repository_url = wf_data.get("repository_url")
            mock_wf.catalog = SimpleNamespace() if wf_data.get("catalog") else None
            if mock_wf.catalog:
                mock_wf.catalog.name = wf_data.get("catalog", {}).get("name", "Unknown")
            mock_wf.version = wf_data.get("version")
            workflows.append(mock_wf)

        # Recreate workflows manager section with updated selection
        return create_workflows_manager_section(workflows, selected_workflow_id)

    @app.callback(
        Output("data-collection-viewer-content", "children", allow_duplicate=True),
        [Input("url", "pathname")],
        [dash.State("theme-store", "data")],
        prevent_initial_call=True,
    )
    def initialize_data_collection_viewer(pathname, theme_data):
        """
        Initialize the data collection viewer with empty state.

        Called on URL change to reset the viewer to its default empty state,
        showing a placeholder message to select a data collection.

        Args:
            pathname: Current URL pathname.
            theme_data: Current theme setting for consistent styling.

        Returns:
            Empty data collection viewer content component.
        """
        if not pathname or not pathname.startswith("/project/") or not pathname.endswith("/data"):
            return dash.no_update

        theme = theme_data or "light"
        return create_data_collection_viewer_content(None, None, None, theme)

    @app.callback(
        [
            Output("selected-data-collection-store", "data"),
            Output("data-collection-viewer-content", "children", allow_duplicate=True),
        ],
        [Input({"type": "data-collection-card", "index": dash.ALL}, "n_clicks")],
        [
            dash.State("project-data-store", "data"),
            dash.State("selected-workflow-store", "data"),
            dash.State("local-store", "data"),
            dash.State("theme-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_data_collection_selection(
        dc_clicks, project_data, selected_workflow_id, local_data, theme_data
    ):
        """
        Handle data collection card selection and populate viewer.

        Finds the selected data collection from project data, fetches its
        delta table information, and populates the viewer with detailed
        information including configuration and storage details.

        Args:
            dc_clicks: List of click counts for data collection cards.
            project_data: Project data dictionary containing data collections.
            selected_workflow_id: Currently selected workflow ID (for advanced projects).
            local_data: Local storage data containing access token.
            theme_data: Current theme setting for styling.

        Returns:
            Tuple of (selected_dc_tag, viewer_content)
        """
        if not any(dc_clicks) or not project_data:
            return dash.no_update, dash.no_update

        # Find which data collection was clicked
        ctx_trigger = ctx.triggered_id
        if not ctx_trigger:
            return dash.no_update, dash.no_update

        selected_dc_tag = ctx_trigger["index"]

        # Find the selected data collection from the project data
        selected_dc = None
        dc_id = None
        workflow_info = None

        if project_data.get("project_type") == "basic":
            # For basic projects, look in direct data collections
            data_collections = project_data.get("data_collections", [])
            for dc in data_collections:
                if dc.get("data_collection_tag") == selected_dc_tag:
                    selected_dc = dc
                    dc_id = dc.get("id")
                    break
        else:
            # For advanced projects, look in the selected workflow's data collections
            if selected_workflow_id:
                workflows = project_data.get("workflows", [])
                for workflow in workflows:
                    if str(workflow.get("id")) == selected_workflow_id:
                        workflow_info = workflow  # Store workflow info for registration_time
                        for dc in workflow.get("data_collections", []):
                            if dc.get("data_collection_tag") == selected_dc_tag:
                                selected_dc = dc
                                dc_id = dc.get("id")
                                break
                        break

        # Fetch delta table info only for non-MultiQC types
        # MultiQC is document-based and doesn't have deltatable data
        delta_info = None
        dc_type = selected_dc.get("config", {}).get("type", "").lower() if selected_dc else ""

        if dc_id and local_data and local_data.get("access_token") and dc_type != "multiqc":
            try:
                delta_info = api_call_fetch_delta_table_info(str(dc_id), local_data["access_token"])
            except Exception as e:
                logger.error(f"Error fetching delta table info: {e}")

        # Create viewer content with delta information
        theme = theme_data or "light"
        viewer_content = create_data_collection_viewer_content(
            selected_dc, delta_info, workflow_info, theme
        )

        return selected_dc_tag, viewer_content

    @app.callback(
        Output({"type": "dc-viewer-multiqc-metadata-content", "index": MATCH}, "children"),
        [
            # The metadata-content div is itself created by the dc-card click
            # callback (handle_data_collection_selection) — i.e. it does NOT
            # exist in the DOM until that callback's viewer_content output
            # lands. If we triggered only on selected-data-collection-store
            # changes, the MATCH output target wouldn't resolve on the first
            # click and the user would have to click the card twice. Adding
            # the viewer-content children as an Input gives us a second
            # trigger that fires AFTER the new container is mounted.
            Input("selected-data-collection-store", "data"),
            Input("project-data-store", "data"),
            Input("data-collection-viewer-content", "children"),
        ],
        [
            State("selected-workflow-store", "data"),
            State("local-store", "data"),
        ],
    )
    def populate_multiqc_metadata_content(
        selected_dc_tag, project_data, _viewer_children, selected_workflow_id, local_data
    ):
        """Populate MultiQC metadata content when a MultiQC data collection is selected.

        Features:
        - Support for multiple reports per DC with selector dropdown
        - Collapsible accordion for samples with scrollable area
        - Combined modules & plots view showing hierarchy (module > plots)
        """
        if not selected_dc_tag or not project_data or not local_data:
            return dmc.Text("No MultiQC metadata available", size="sm", c="gray", ta="center")

        # Find the selected data collection
        selected_dc = None
        dc_id = None

        if project_data.get("project_type") == "basic":
            data_collections = project_data.get("data_collections", [])
            for dc in data_collections:
                if dc.get("data_collection_tag") == selected_dc_tag:
                    selected_dc = dc
                    dc_id = dc.get("id")
                    break
        else:
            if selected_workflow_id:
                workflows = project_data.get("workflows", [])
                for workflow in workflows:
                    if str(workflow.get("id")) == selected_workflow_id:
                        for dc in workflow.get("data_collections", []):
                            if dc.get("data_collection_tag") == selected_dc_tag:
                                selected_dc = dc
                                dc_id = dc.get("id")
                                break
                        break

        # Check if this is a MultiQC data collection
        if not selected_dc or selected_dc.get("config", {}).get("type", "").lower() != "multiqc":
            return dash.no_update

        # Fetch all MultiQC reports for this DC
        if dc_id and local_data.get("access_token"):
            try:
                all_reports_data = api_call_fetch_all_multiqc_reports(
                    str(dc_id), local_data["access_token"]
                )

                if not all_reports_data or not all_reports_data.get("reports"):
                    return dmc.Alert(
                        "No MultiQC report metadata found for this data collection",
                        color="yellow",
                        icon=DashIconify(icon="mdi:alert"),
                    )

                reports = all_reports_data.get("reports", [])
                total_count = all_reports_data.get("total_count", len(reports))

                # Build report selector options
                report_options = []
                for idx, report in enumerate(reports):
                    report_name = report.get("report_name", f"Report {idx + 1}")
                    report_options.append({"value": str(idx), "label": report_name})

                # Pattern-matched IDs so the selector callback can target the
                # right detail container + reports store for this DC.
                dc_id_str = str(dc_id)
                report_detail = _build_multiqc_report_detail(reports[0] if reports else {})

                content_children = [
                    # Hidden cache of all reports for this DC; keyed by dc_id
                    # so multiple MultiQC viewers on the same page don't fight.
                    dcc.Store(
                        id={"type": "multiqc-reports-store", "index": dc_id_str},
                        data=reports,
                    ),
                    # Report count badge
                    dmc.Group(
                        [
                            DashIconify(
                                icon="mdi:file-document-multiple", width=18, color=colors["blue"]
                            ),
                            dmc.Text(
                                f"{total_count} report{'s' if total_count > 1 else ''} available",
                                size="sm",
                                fw=500,
                            ),
                        ],
                        gap="xs",
                    ),
                ]

                # Selector — pattern-matched id wires to a MATCH callback
                # below that re-renders the detail container on change.
                if total_count > 1:
                    content_children.append(
                        dmc.Select(
                            id={"type": "multiqc-report-selector", "index": dc_id_str},
                            data=report_options,
                            value="0",
                            label="Select Report",
                            size="xs",
                            w=250,
                            leftSection=DashIconify(icon="mdi:file-document"),
                            allowDeselect=False,
                        )
                    )

                # Per-report detail block lives in its own container so the
                # selector callback can swap its children without touching
                # the surrounding header / store.
                content_children.append(
                    html.Div(
                        id={"type": "multiqc-report-detail", "index": dc_id_str},
                        children=report_detail,
                    )
                )

                return dmc.Stack(content_children, gap="sm")

            except Exception as e:
                logger.error(f"Error fetching MultiQC metadata: {e}")
                return dmc.Alert(
                    f"Error loading MultiQC metadata: {str(e)}",
                    color="red",
                    icon=DashIconify(icon="mdi:alert-circle"),
                )

        return dmc.Text("Unable to load MultiQC metadata", size="sm", c="gray", ta="center")

    @app.callback(
        Output({"type": "multiqc-report-detail", "index": MATCH}, "children"),
        Input({"type": "multiqc-report-selector", "index": MATCH}, "value"),
        State({"type": "multiqc-reports-store", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def render_selected_multiqc_report(selected_idx, reports):
        """Swap the per-report detail block when the selector value changes.

        Reads from the per-DC reports Store populated by
        :func:`populate_multiqc_metadata_content`, so no new API call fires
        on selection change.
        """
        if reports is None or selected_idx is None:
            raise dash.exceptions.PreventUpdate
        try:
            idx = int(selected_idx)
        except (TypeError, ValueError):
            raise dash.exceptions.PreventUpdate
        if idx < 0 or idx >= len(reports):
            raise dash.exceptions.PreventUpdate
        return _build_multiqc_report_detail(reports[idx])

    @app.callback(
        Output("data-collections-content", "children"),
        [
            Input("upload-data-collection-btn", "n_clicks"),
            Input("import-from-url-btn", "n_clicks"),
            Input("create-from-template-btn", "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def handle_data_collection_actions(upload_clicks, import_clicks, template_clicks):
        """
        Handle data collection action button clicks.

        Placeholder callback for future functionality including file upload,
        URL import, and template-based creation of data collections.

        Args:
            upload_clicks: Click count for upload button.
            import_clicks: Click count for URL import button.
            template_clicks: Click count for template creation button.

        Returns:
            Alert component indicating feature status.
        """
        ctx_trigger = ctx.triggered_id

        if ctx_trigger == "upload-data-collection-btn":
            logger.info("Upload data collection button clicked")
            # TODO: Implement upload functionality
            return dmc.Alert(
                "Upload functionality coming soon!",
                title="Feature in Development",
                color="blue",
                icon=DashIconify(icon="mdi:information"),
            )
        elif ctx_trigger == "import-from-url-btn":
            logger.info("Import from URL button clicked")
            # TODO: Implement URL import functionality
            return dmc.Alert(
                "URL import functionality coming soon!",
                title="Feature in Development",
                color="blue",
                icon=DashIconify(icon="mdi:information"),
            )
        elif ctx_trigger == "create-from-template-btn":
            logger.info("Create from template button clicked")
            # TODO: Implement template creation functionality
            return dmc.Alert(
                "Template creation functionality coming soon!",
                title="Feature in Development",
                color="blue",
                icon=DashIconify(icon="mdi:information"),
            )

        return dash.no_update

    @app.callback(
        [
            Output("joins-visualization-section", "style"),
            Output("depictio-cytoscape-joins", "elements"),
        ],
        [
            Input("project-data-store", "data"),
            Input("selected-workflow-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_joins_visualization(project_data, selected_workflow_id):
        """
        Update joins visualization based on project data.

        Generates cytoscape elements to visualize relationships between
        data collections using project-level joins and links. Shows data
        collections as nodes without edges when no joins/links are defined.

        Args:
            project_data: Project data dictionary containing data collections,
                joins, and links.
            selected_workflow_id: Currently selected workflow ID (for advanced projects).

        Returns:
            Tuple of (section_style, cytoscape_elements)
        """

        if not project_data:
            return {"display": "none"}, []

        # Get data collections based on project type
        data_collections = []

        if project_data.get("project_type") == "basic":
            # Basic projects: use flattened data collections
            data_collections = project_data.get("data_collections", [])
        else:
            # Advanced projects: use selected workflow's data collections
            if selected_workflow_id:
                workflows = project_data.get("workflows", [])
                selected_workflow = next(
                    (w for w in workflows if str(w.get("id")) == selected_workflow_id), None
                )
                if selected_workflow:
                    data_collections = selected_workflow.get("data_collections", [])

        # Check for project-level joins and links
        has_joins = bool(project_data.get("joins"))
        has_links = bool(project_data.get("links"))

        # Also check legacy DC-level join configs
        has_dc_level_joins = False
        for dc in data_collections:
            config = dc.get("config", {})
            if config.get("join") is not None:
                has_dc_level_joins = True
                break

        # Generate visualization if we have multiple data collections
        if len(data_collections) > 1:
            if has_joins or has_links:
                # Use new function that handles project-level joins and links
                elements = generate_elements_from_project(
                    project_data=project_data,
                    data_collections=data_collections,
                )
            elif has_dc_level_joins:
                # Fallback to legacy DC-level join generation
                elements = generate_cytoscape_elements_from_project_data(data_collections)
            else:
                # Show DCs without connections (user preference: show DCs as nodes)
                elements = generate_elements_from_project(
                    project_data={"joins": [], "links": []},
                    data_collections=data_collections,
                )
            return {"display": "block"}, elements

        # Hide if no data collections or only one DC
        return {"display": "none"}, []

    # Data collection creation modal callbacks
    @app.callback(
        [
            Output("data-collection-creation-separator-container", "style"),
            Output("data-collection-creation-custom-separator-container", "style"),
        ],
        [
            Input("data-collection-creation-format-select", "value"),
            Input("data-collection-creation-separator-select", "value"),
        ],
    )
    def update_separator_visibility(file_format, separator_value):
        """
        Control visibility of separator options based on file format.

        Shows separator selection for delimited file formats (CSV, TSV) and
        custom separator input when 'custom' is selected.

        Args:
            file_format: Selected file format (csv, tsv, parquet, etc.).
            separator_value: Selected separator option.

        Returns:
            Tuple of (separator_container_style, custom_separator_container_style)
        """
        # Show separator options only for delimited file formats
        delimited_formats = ["csv", "tsv"]
        show_separator = file_format in delimited_formats

        separator_style = {"display": "block"} if show_separator else {"display": "none"}

        # Show custom separator input if "custom" is selected and format supports it
        show_custom = show_separator and separator_value == "custom"
        custom_style = {"display": "block"} if show_custom else {"display": "none"}

        return separator_style, custom_style

    # NOTE: Table-vs-MultiQC option visibility is folded into
    # :func:`update_modal_section_visibility` below — the unified mode
    # callback owns ``data-collection-creation-table-options-container``
    # and ``...-multiqc-options-container`` so we don't double-bind them.

    # Mark the upload component with a class when MultiQC is selected so the
    # client-side hook (assets/multiqc_folder_upload.js) can switch the
    # underlying <input> into folder-pick mode (webkitdirectory) and walk
    # dropped directory entries. Update mode is MultiQC-only, so we also
    # force folder-pick mode whenever the modal is in ``update`` mode (the
    # data-type select is hidden in that mode and may carry a stale value).
    @app.callback(
        Output("data-collection-creation-file-upload", "className"),
        [
            Input("data-collection-creation-type-select", "value"),
            Input("data-collection-modal-mode", "data"),
        ],
    )
    def set_dropzone_folder_mode(data_type, mode_data):
        mode = (mode_data or {}).get("mode")
        if mode == "update" or data_type == "multiqc":
            return "depictio-multiqc-folder-upload"
        return ""

    # =========================================================================
    # DC Link Modal Callbacks
    # =========================================================================

    @app.callback(
        [
            Output("dc-link-creation-modal", "opened"),
            Output("dc-link-creation-error-alert", "style", allow_duplicate=True),
        ],
        [
            Input("create-dc-link-button", "n_clicks"),
            Input("cancel-dc-link-creation-button", "n_clicks"),
        ],
        [dash.State("dc-link-creation-modal", "opened")],
        prevent_initial_call=True,
    )
    def toggle_dc_link_modal(open_clicks, cancel_clicks, opened):
        """Handle opening and closing of DC link creation modal."""
        if not ctx.triggered:
            return False, {"display": "none"}

        trigger = ctx.triggered_id
        if trigger == "create-dc-link-button" and open_clicks:
            return True, {"display": "none"}
        elif trigger == "cancel-dc-link-creation-button" and cancel_clicks:
            return False, {"display": "none"}
        return opened, {"display": "none"}

    @app.callback(
        [
            Output("dc-link-creation-source-dc-select", "data"),
            Output("dc-link-creation-target-dc-select", "data"),
        ],
        [Input("dc-link-creation-modal", "opened")],
        [dash.State("project-data-store", "data")],
        prevent_initial_call=True,
    )
    def populate_link_dc_selects(opened, project_data):
        """Populate source and target DC selects when the link modal opens."""
        if not opened or not project_data:
            return [], []

        # Gather all data collections from the project
        dc_options = []
        data_collections = project_data.get("data_collections", [])

        # Also check workflows
        for wf in project_data.get("workflows", []):
            for dc in wf.get("data_collections", []):
                if dc not in data_collections:
                    data_collections.append(dc)

        for dc in data_collections:
            dc_tag = dc.get("data_collection_tag", "Unknown")
            dc_id = str(dc.get("id", ""))
            dc_type = dc.get("config", {}).get("type", "unknown")
            label = f"{dc_tag} ({dc_type})"
            dc_options.append({"value": dc_id, "label": label})

        return dc_options, dc_options

    @app.callback(
        [
            Output("dc-link-creation-source-column-select", "data"),
            Output("dc-link-creation-source-column-select", "disabled"),
        ],
        [Input("dc-link-creation-source-dc-select", "value")],
        [dash.State("local-store", "data")],
        prevent_initial_call=True,
    )
    def load_source_dc_columns(source_dc_id, local_data):
        """Load columns for the selected source DC."""
        if not source_dc_id or not local_data or not local_data.get("access_token"):
            return [], True

        token = local_data["access_token"]
        columns = api_call_get_dc_columns(source_dc_id, token)

        if columns:
            col_options = [{"value": c, "label": c} for c in columns]
            return col_options, False
        return [], True

    @app.callback(
        Output("dc-link-creation-target-type-input", "value"),
        [Input("dc-link-creation-target-dc-select", "value")],
        [dash.State("project-data-store", "data")],
        prevent_initial_call=True,
    )
    def detect_target_dc_type(target_dc_id, project_data):
        """Auto-detect the target DC type when a target is selected."""
        if not target_dc_id or not project_data:
            return ""

        # Search in data_collections and workflows
        all_dcs = list(project_data.get("data_collections", []))
        for wf in project_data.get("workflows", []):
            all_dcs.extend(wf.get("data_collections", []))

        for dc in all_dcs:
            if str(dc.get("id", "")) == target_dc_id:
                return dc.get("config", {}).get("type", "unknown")
        return ""

    @app.callback(
        Output("create-dc-link-creation-submit", "disabled"),
        [
            Input("dc-link-creation-source-dc-select", "value"),
            Input("dc-link-creation-source-column-select", "value"),
            Input("dc-link-creation-target-dc-select", "value"),
        ],
    )
    def update_link_submit_state(source_dc, source_col, target_dc):
        """Enable link submit button only when all required fields are filled."""
        if source_dc and source_col and target_dc and source_dc != target_dc:
            return False
        return True

    @app.callback(
        Output("dc-link-creation-resolver-select", "value"),
        [Input("dc-link-creation-target-type-input", "value")],
        prevent_initial_call=True,
    )
    def auto_select_resolver(target_type):
        """Auto-select resolver based on target type."""
        if target_type == "multiqc":
            return "sample_mapping"
        return "direct"

    @app.callback(
        [
            Output("dc-link-creation-modal", "opened", allow_duplicate=True),
            Output("project-data-store", "data", allow_duplicate=True),
            Output("dc-link-creation-error-alert", "children"),
            Output("dc-link-creation-error-alert", "style"),
        ],
        [Input("create-dc-link-creation-submit", "n_clicks")],
        [
            dash.State("dc-link-creation-source-dc-select", "value"),
            dash.State("dc-link-creation-source-column-select", "value"),
            dash.State("dc-link-creation-target-dc-select", "value"),
            dash.State("dc-link-creation-target-type-input", "value"),
            dash.State("dc-link-creation-resolver-select", "value"),
            dash.State("dc-link-creation-description-input", "value"),
            dash.State("project-data-store", "data"),
            dash.State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def submit_dc_link_creation(
        n_clicks,
        source_dc_id,
        source_column,
        target_dc_id,
        target_type,
        resolver,
        description,
        project_data,
        local_data,
    ):
        """Handle DC link creation submission."""
        if not n_clicks or not source_dc_id or not source_column or not target_dc_id:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        if not local_data or not local_data.get("access_token"):
            return (
                dash.no_update,
                dash.no_update,
                "Authentication required.",
                {"display": "block"},
            )

        if source_dc_id == target_dc_id:
            return (
                dash.no_update,
                dash.no_update,
                "Source and target must be different data collections.",
                {"display": "block"},
            )

        token = local_data["access_token"]
        project_id = project_data.get("project_id")

        # Map target type - default to "table" if not recognized
        valid_types = ["table", "multiqc", "image"]
        effective_type = target_type if target_type in valid_types else "table"

        result = api_call_create_link(
            project_id=project_id,
            source_dc_id=source_dc_id,
            source_column=source_column,
            target_dc_id=target_dc_id,
            target_type=effective_type,
            resolver=resolver or "direct",
            description=description,
            token=token,
        )

        if result and result.get("success"):
            from datetime import datetime

            updated = project_data.copy()
            updated["refresh_timestamp"] = datetime.now().isoformat()
            return False, updated, "", {"display": "none"}
        else:
            error_msg = result.get("message", "Unknown error") if result else "API call failed"
            return (
                dash.no_update,
                dash.no_update,
                f"Failed to create link: {error_msg}",
                {"display": "block"},
            )

    # DC Links Manager Section callback
    @app.callback(
        Output("dc-links-manager-section", "children"),
        [Input("project-data-store", "data")],
        [dash.State("local-store", "data")],
    )
    def render_dc_links_section(project_data, local_data):
        """Render the DC links manager section with existing links and create button."""
        if not project_data or not project_data.get("project_id"):
            return []

        project_id = project_data.get("project_id")
        token = local_data.get("access_token") if local_data else None

        # Get all data collections for label lookup
        all_dcs = {}
        for dc in project_data.get("data_collections", []):
            dc_id = str(dc.get("id", ""))
            all_dcs[dc_id] = dc.get("data_collection_tag", "Unknown")
        for wf in project_data.get("workflows", []):
            for dc in wf.get("data_collections", []):
                dc_id = str(dc.get("id", ""))
                all_dcs[dc_id] = dc.get("data_collection_tag", "Unknown")

        # Need at least 2 DCs to create links
        if len(all_dcs) < 2:
            return []

        # Fetch existing links
        links = []
        if token:
            links = api_call_get_project_links(project_id, token)

        # Build link cards
        link_cards = []
        for link in links:
            link_id = str(link.get("id", ""))
            source_name = all_dcs.get(str(link.get("source_dc_id", "")), "Unknown DC")
            target_name = all_dcs.get(str(link.get("target_dc_id", "")), "Unknown DC")
            source_col = link.get("source_column", "?")
            resolver = link.get("link_config", {}).get("resolver", "direct")
            target_type = link.get("target_type", "unknown")
            desc = link.get("description", "")

            link_cards.append(
                dmc.Card(
                    [
                        dmc.Group(
                            [
                                dmc.Group(
                                    [
                                        DashIconify(
                                            icon="mdi:link-variant",
                                            width=20,
                                            color=colors["blue"],
                                        ),
                                        dmc.Stack(
                                            [
                                                dmc.Group(
                                                    [
                                                        dmc.Text(source_name, fw="bold", size="sm"),
                                                        dmc.Text(
                                                            f"({source_col})",
                                                            size="xs",
                                                            c="gray",
                                                        ),
                                                        DashIconify(
                                                            icon="mdi:arrow-right",
                                                            width=16,
                                                            color="gray",
                                                        ),
                                                        dmc.Text(target_name, fw="bold", size="sm"),
                                                    ],
                                                    gap="xs",
                                                ),
                                                dmc.Group(
                                                    [
                                                        dmc.Badge(
                                                            resolver,
                                                            color="blue",
                                                            variant="light",
                                                            size="xs",
                                                        ),
                                                        dmc.Badge(
                                                            target_type,
                                                            color="gray",
                                                            variant="outline",
                                                            size="xs",
                                                        ),
                                                        dmc.Text(
                                                            desc or "",
                                                            size="xs",
                                                            c="gray",
                                                            fs="italic",
                                                        ),
                                                    ],
                                                    gap="xs",
                                                ),
                                            ],
                                            gap="xs",
                                        ),
                                    ],
                                    gap="sm",
                                    align="center",
                                ),
                                dmc.ActionIcon(
                                    DashIconify(icon="mdi:delete", width=16),
                                    color="red",
                                    variant="subtle",
                                    id={"type": "dc-link-delete-button", "index": link_id},
                                    size="sm",
                                ),
                            ],
                            justify="space-between",
                            align="center",
                        ),
                    ],
                    withBorder=True,
                    shadow="xs",
                    radius="md",
                    p="sm",
                )
            )

        return dmc.Stack(
            [
                dmc.Divider(
                    label="Data Collection Links",
                    labelPosition="center",
                    my="md",
                ),
                dmc.Group(
                    [
                        dmc.Group(
                            [
                                DashIconify(
                                    icon="mdi:link-variant",
                                    width=24,
                                    color=colors["blue"],
                                ),
                                dmc.Text(
                                    "Cross-DC Links",
                                    fw="bold",
                                    size="lg",
                                ),
                                dmc.Text(
                                    f"({len(links)} active)",
                                    size="sm",
                                    c="gray",
                                ),
                            ],
                            gap="sm",
                        ),
                        dmc.Button(
                            "Link Collections",
                            id="create-dc-link-button",
                            leftSection=DashIconify(icon="mdi:link-variant-plus", width=16),
                            color="blue",
                            variant="light",
                            radius="md",
                            size="sm",
                        ),
                    ],
                    justify="space-between",
                ),
                dmc.Stack(
                    link_cards
                    if link_cards
                    else [
                        dmc.Text(
                            "No links defined yet. Create a link to enable cross-DC filtering.",
                            size="sm",
                            c="gray",
                            fs="italic",
                            ta="center",
                        )
                    ],
                    gap="sm",
                ),
            ],
            gap="md",
        )

    @app.callback(
        Output("project-data-store", "data", allow_duplicate=True),
        [Input({"type": "dc-link-delete-button", "index": ALL}, "n_clicks")],
        [
            dash.State("project-data-store", "data"),
            dash.State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_dc_link_delete(n_clicks_list, project_data, local_data):
        """Handle deletion of a DC link."""
        if not any(n_clicks_list):
            return dash.no_update

        trigger = ctx.triggered_id
        if not trigger:
            return dash.no_update

        link_id = trigger["index"]
        if not local_data or not local_data.get("access_token"):
            return dash.no_update

        token = local_data["access_token"]
        project_id = project_data.get("project_id")

        result = api_call_delete_link(project_id, link_id, token)
        if result and result.get("success"):
            from datetime import datetime

            updated = project_data.copy()
            updated["refresh_timestamp"] = datetime.now().isoformat()
            return updated

        return dash.no_update

    def _check_user_is_viewer(project_data, local_data):
        """Helper function to check if current user is a viewer."""
        if not project_data or not local_data:
            return True  # Treat as viewer if no data available

        try:
            # Get current user ID from local storage
            current_user_id = local_data.get("user_id")
            if not current_user_id:
                logger.debug("No user_id in local_data - treating as viewer")
                return True  # Treat as viewer if no user ID

            # Get project permissions
            permissions = project_data.get("permissions", {})
            logger.debug(f"Project data : {project_data}")
            if not permissions:
                logger.debug("No permissions in project_data - treating as viewer")
                return True  # Treat as viewer if no permissions data

            logger.debug(f"Checking permissions for user_id: {current_user_id}")
            logger.debug(f"Project permissions: {permissions}")

            # First, check if user is an owner (owners can modify data collections)
            owners = permissions.get("owners", [])
            logger.debug(f"Project owners: {owners}")
            for owner in owners:
                if isinstance(owner, dict):
                    # Project store data uses Pydantic format with 'id'
                    owner_id = owner.get("id")
                    logger.debug(
                        f"Comparing owner_id {owner_id} (type: {type(owner_id)}) with current_user_id {current_user_id} (type: {type(current_user_id)})"
                    )
                    # Handle both string and ObjectId comparisons
                    if str(owner_id) == str(current_user_id):
                        logger.debug("User is an owner - can create data collections")
                        return False  # User is an owner, not a viewer

            # Second, check if user is an editor (editors can modify data collections)
            editors = permissions.get("editors", [])
            for editor in editors:
                if isinstance(editor, dict):
                    # Project store data uses Pydantic format with 'id'
                    editor_id = editor.get("id")
                    # Handle both string and ObjectId comparisons
                    if str(editor_id) == str(current_user_id):
                        logger.debug("User is an editor - can create data collections")
                        return False  # User is an editor, not a viewer

            # Finally, check if user is explicitly a viewer or has wildcard viewer access
            viewers = permissions.get("viewers", [])
            for viewer in viewers:
                if isinstance(viewer, dict):
                    # Project store data uses Pydantic format with 'id'
                    viewer_id = viewer.get("id")
                    # Handle both string and ObjectId comparisons
                    if str(viewer_id) == str(current_user_id):
                        logger.debug("User is explicitly a viewer - cannot create data collections")
                        return True  # User is explicitly a viewer
                elif isinstance(viewer, str) and viewer == "*":
                    # Wildcard viewer access means user is a viewer
                    # (owners and editors already checked above)
                    logger.debug("User has wildcard viewer access - cannot create data collections")
                    return True

            # User has no explicit permissions - treat as viewer for safety
            logger.debug("User has no explicit permissions - treating as viewer for safety")
            logger.debug("User CANNOT create data collections")
            return True

        except Exception as e:
            logger.error(f"Error checking user permissions: {e}")
            return True  # Treat as viewer on error

    @app.callback(
        Output("create-data-collection-button", "disabled"),
        [
            Input("project-data-store", "data"),
            Input("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def control_create_button_access(project_data, local_data):
        """
        Control access to Create Data Collection button based on user role.

        Disables the button for users who are only viewers of the project.
        Owners and editors can create new data collections.

        Args:
            project_data: Project data dictionary containing permissions.
            local_data: Local storage data containing user ID.

        Returns:
            bool: True to disable button (viewer), False to enable (owner/editor).
        """
        return _check_user_is_viewer(project_data, local_data)

    @app.callback(
        [
            Output({"type": "dc-manage-button", "index": dash.ALL}, "disabled"),
            Output({"type": "dc-edit-name-button", "index": dash.ALL}, "disabled"),
            Output({"type": "dc-delete-button", "index": dash.ALL}, "disabled"),
        ],
        [
            Input("project-data-store", "data"),
            Input("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def control_dc_action_buttons_access(project_data, local_data):
        """Control DC action buttons based on user role.

        Disables Manage, Edit, and Delete buttons for viewers. Returns three
        disabled-state lists matching the number of rendered DCs.
        """
        is_viewer = _check_user_is_viewer(project_data, local_data)

        try:
            if project_data and project_data.get("data_collections"):
                num_dcs = len(project_data["data_collections"])
            else:
                num_dcs = 0

            disabled_states = [is_viewer] * num_dcs
            return disabled_states, disabled_states, disabled_states

        except Exception as e:
            logger.error(f"Error controlling DC action buttons: {e}")
            return [], [], []

    @app.callback(
        [
            Output("data-collection-creation-modal", "opened", allow_duplicate=True),
            Output("data-collection-creation-error-alert", "style", allow_duplicate=True),
            Output("data-collection-modal-mode", "data", allow_duplicate=True),
        ],
        [
            Input("create-data-collection-button", "n_clicks"),
            Input("cancel-data-collection-creation-button", "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def toggle_data_collection_modal(open_clicks, cancel_clicks):
        """
        Handle the top-of-page Create button + the modal's Cancel button.

        Opening sets the unified modal mode to ``create`` and clears the
        active-DC + expected-name fields. Cancel resets the mode to None so
        a stale store doesn't leak into the next open.
        """
        if not ctx.triggered:
            return dash.no_update, dash.no_update, dash.no_update

        ctx_trigger = ctx.triggered_id

        if ctx_trigger == "create-data-collection-button" and open_clicks:
            return (
                True,
                {"display": "none"},
                {"mode": "create", "dc_id": None, "expected_name": None},
            )
        if ctx_trigger == "cancel-data-collection-creation-button" and cancel_clicks:
            return (
                False,
                {"display": "none"},
                {"mode": None, "dc_id": None, "expected_name": None},
            )
        return dash.no_update, dash.no_update, dash.no_update

    @app.callback(
        Output("data-collection-creation-file-info", "children"),
        [Input("data-collection-creation-file-upload", "contents")],
        [
            dash.State("data-collection-creation-file-upload", "filename"),
            dash.State("data-collection-creation-file-upload", "last_modified"),
        ],
        prevent_initial_call=True,
    )
    def handle_file_upload(contents, filename, last_modified):
        """
        Handle file upload and display basic file information.

        Supports both single file and multi-file uploads.

        Args:
            contents: Base64-encoded file contents (string or list).
            filename: Original filename (string or list).
            last_modified: File last modified timestamp.

        Returns:
            Component showing file info or error alert.
        """
        if not contents or not filename:
            return []

        contents_list, filenames_list = _normalize_upload_to_lists(contents, filename)

        logger.info(
            "handle_file_upload received %d file(s); first 20 names: %s",
            len(filenames_list),
            filenames_list[:20],
        )

        try:
            # Detect a folder-style upload: any filename containing a path
            # separator means the user dropped folders (the dropzone JS hook
            # surfaces webkitRelativePath as file.name). In that case, present
            # a folder-grouped summary; otherwise fall back to the simple flat
            # listing used by the table flow.
            looks_like_folder_upload = any(
                "/" in (fname or "") or "\\" in (fname or "") for fname in filenames_list
            )

            if looks_like_folder_upload:
                kept_folders: dict[str, int] = {}
                multiqc_size = 0
                skipped = 0
                for i, (content, fname) in enumerate(zip(contents_list, filenames_list)):
                    basename = fname.replace("\\", "/").rsplit("/", 1)[-1]
                    if basename != MULTIQC_PARQUET_BASENAME:
                        skipped += 1
                        continue
                    _, content_string = content.split(",")
                    decoded = base64.b64decode(content_string)
                    multiqc_size += len(decoded)
                    folder = _multiqc_folder_from_path(fname, i)
                    kept_folders[folder] = kept_folders.get(folder, 0) + 1

                if not kept_folders:
                    return dmc.Alert(
                        "No 'multiqc.parquet' files found in the dropped folders.",
                        color="red",
                        icon=DashIconify(icon="mdi:alert"),
                    )

                summary_parts = [
                    f"{len(kept_folders)} folder(s)",
                    f"{sum(kept_folders.values())} multiqc.parquet",
                    f"{multiqc_size / 1024:.1f}KB",
                ]
                if skipped:
                    summary_parts.append(f"{skipped} other file(s) ignored")

                return dmc.Card(
                    [
                        dmc.Group(
                            [
                                DashIconify(icon="mdi:folder-multiple", width=20, color="green"),
                                dmc.Text(
                                    " • ".join(summary_parts),
                                    fw="bold",
                                    size="sm",
                                ),
                            ],
                            gap="md",
                            align="center",
                        ),
                    ],
                    withBorder=True,
                    shadow="xs",
                    radius="md",
                    p="sm",
                    style={"backgroundColor": "var(--mantine-color-green-0)"},
                )

            total_size = 0
            file_infos = []
            for content, fname in zip(contents_list, filenames_list):
                content_type, content_string = content.split(",")
                decoded = base64.b64decode(content_string)
                file_size = len(decoded)
                total_size += file_size
                file_infos.append((fname, file_size))

            if len(file_infos) == 1:
                fname, fsize = file_infos[0]
                return dmc.Card(
                    [
                        dmc.Group(
                            [
                                DashIconify(icon="mdi:file-check", width=20, color="green"),
                                dmc.Stack(
                                    [
                                        dmc.Text(fname, fw="bold", size="sm"),
                                        dmc.Text(
                                            f"Size: {fsize / 1024:.1f}KB",
                                            size="xs",
                                            c="gray",
                                        ),
                                    ],
                                    gap="xs",
                                ),
                            ],
                            gap="md",
                            align="center",
                        ),
                    ],
                    withBorder=True,
                    shadow="xs",
                    radius="md",
                    p="sm",
                    style={"backgroundColor": "var(--mantine-color-green-0)"},
                )
            else:
                return dmc.Card(
                    [
                        dmc.Group(
                            [
                                DashIconify(icon="mdi:file-check", width=20, color="green"),
                                dmc.Text(
                                    f"{len(file_infos)} files uploaded ({total_size / 1024:.1f}KB total)",
                                    fw="bold",
                                    size="sm",
                                ),
                            ],
                            gap="md",
                            align="center",
                        ),
                    ],
                    withBorder=True,
                    shadow="xs",
                    radius="md",
                    p="sm",
                    style={"backgroundColor": "var(--mantine-color-green-0)"},
                )

        except Exception as e:
            return dmc.Alert(
                f"Error processing file: {str(e)}",
                color="red",
                icon=DashIconify(icon="mdi:alert"),
            )

    @app.callback(
        Output("create-data-collection-creation-submit", "disabled"),
        [
            Input("data-collection-creation-name-input", "value"),
            Input("data-collection-creation-file-upload", "contents"),
            Input("data-collection-creation-clear-confirm-name-input", "value"),
            Input("data-collection-modal-mode", "data"),
        ],
    )
    def update_submit_button_state(name, file_contents, clear_typed_name, mode_data):
        """Enable/disable the unified submit button based on the active mode.

        - ``create``: requires both a DC name and a file upload.
        - ``update``: requires a file upload (the DC id comes from the mode store).
        - ``clear``: requires the typed-name guard to match (expected vs typed);
          the actual disabled toggle for clear is owned by a clientside callback
          (so this callback returns False to relinquish control to the JS).
        """
        mode = (mode_data or {}).get("mode")
        if mode == "update":
            return not bool(file_contents)
        if mode == "clear":
            expected = (mode_data or {}).get("expected_name") or ""
            return str(clear_typed_name or "") != str(expected) or not expected
        # create (or unknown — keep disabled until name + file are supplied).
        if not name or not file_contents:
            return True
        return False

    def _validate_multiqc_files(contents, filename):
        """Validate uploaded MultiQC files and return a folder-grouped preview.

        Filenames may arrive as relative paths (e.g.
        ``run_01/multiqc_data/multiqc.parquet``) when the user drops folders;
        the dropzone JS hook rewrites ``file.name`` to ``webkitRelativePath``.
        We strict-filter to ``basename == "multiqc.parquet"`` and skip the
        ~17 sibling support files MultiQC emits per run.
        """
        contents_list, filenames_list = _normalize_upload_to_lists(contents, filename)

        kept_per_folder: dict[str, int] = {}
        kept_count = 0
        skipped_count = 0
        total_size = 0

        for i, (content, fname) in enumerate(zip(contents_list, filenames_list)):
            basename = fname.replace("\\", "/").rsplit("/", 1)[-1]
            if basename != MULTIQC_PARQUET_BASENAME:
                skipped_count += 1
                continue

            try:
                _, content_string = content.split(",")
                decoded = base64.b64decode(content_string)
                file_size = len(decoded)
            except Exception as e:
                return dmc.Alert(
                    f"Error processing file '{fname}': {str(e)}",
                    color="red",
                    icon=DashIconify(icon="mdi:alert"),
                )

            if file_size > 50 * 1024 * 1024:
                return dmc.Alert(
                    f"File '{fname}' ({file_size / (1024 * 1024):.1f}MB) exceeds the 50MB limit",
                    color="red",
                    icon=DashIconify(icon="mdi:alert"),
                )

            folder = _multiqc_folder_from_path(fname, i)
            kept_per_folder[folder] = kept_per_folder.get(folder, 0) + 1
            kept_count += 1
            total_size += file_size

        if kept_count == 0:
            return dmc.Alert(
                "No 'multiqc.parquet' files found in the upload. "
                "Drop one or more folders that each contain a multiqc.parquet file.",
                color="red",
                icon=DashIconify(icon="mdi:alert"),
            )

        if total_size > 500 * 1024 * 1024:
            return dmc.Alert(
                f"Total file size ({total_size / (1024 * 1024):.1f}MB) exceeds the 500MB limit",
                color="red",
                icon=DashIconify(icon="mdi:alert"),
            )

        folder_cards = [
            dmc.Card(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:folder-check", width=20, color="green"),
                            dmc.Stack(
                                [
                                    dmc.Text(folder, fw="bold", size="sm"),
                                    dmc.Text(
                                        f"{count} multiqc.parquet • Format: Parquet (MultiQC)",
                                        size="xs",
                                        c="gray",
                                    ),
                                ],
                                gap="xs",
                            ),
                        ],
                        gap="md",
                        align="center",
                    ),
                ],
                withBorder=True,
                shadow="xs",
                radius="md",
                p="sm",
                style={"backgroundColor": "var(--mantine-color-green-0)"},
            )
            for folder, count in sorted(kept_per_folder.items())
        ]

        summary_parts = [
            f"{len(kept_per_folder)} folder(s)",
            f"{kept_count} multiqc.parquet",
            f"{total_size / 1024:.1f}KB total",
        ]
        if skipped_count:
            summary_parts.append(f"{skipped_count} non-multiqc file(s) ignored")
        summary = dmc.Text(
            " • ".join(summary_parts),
            size="xs",
            c="gray",
            fw="bold",
        )

        return dmc.Stack([summary] + folder_cards, gap="sm")

    @app.callback(
        Output("data-collection-creation-file-info", "children", allow_duplicate=True),
        [
            Input("data-collection-creation-file-upload", "contents"),
            Input("data-collection-creation-format-select", "value"),
            Input("data-collection-creation-separator-select", "value"),
            Input("data-collection-creation-custom-separator-input", "value"),
            Input("data-collection-creation-has-header-switch", "checked"),
        ],
        [
            dash.State("data-collection-creation-file-upload", "filename"),
            dash.State("data-collection-creation-type-select", "value"),
            dash.State("data-collection-modal-mode", "data"),
        ],
        prevent_initial_call=True,
    )
    def validate_file_with_polars(
        contents,
        file_format,
        separator,
        custom_separator,
        has_header,
        filename,
        data_type,
        mode_data,
    ):
        """
        Validate uploaded file(s) and display detailed information.

        For table type: validates with polars using format options.
        For MultiQC type: validates parquet files.

        In ``update`` mode, the data-type select is hidden and may carry a
        stale "table" default — but updates are MultiQC-only, so we coerce
        the validation path to the MultiQC validator.
        """
        mode = (mode_data or {}).get("mode")
        if mode == "update":
            data_type = "multiqc"
        if not contents or not filename:
            return []

        # Handle MultiQC type
        if data_type == "multiqc":
            return _validate_multiqc_files(contents, filename)

        # For table type, handle single file (contents may be a list with one element)
        if isinstance(contents, list):
            if len(contents) > 1:
                return dmc.Alert(
                    "Table data collections only support a single file upload.",
                    color="red",
                    icon=DashIconify(icon="mdi:alert"),
                )
            contents = contents[0]
            filename = filename[0] if isinstance(filename, list) else filename
        if isinstance(filename, list):
            filename = filename[0]

        try:
            # Decode file content
            content_type, content_string = contents.split(",")
            decoded = base64.b64decode(content_string)
            file_size = len(decoded)

            # Check file size limit (5MB)
            max_size = 5 * 1024 * 1024
            if file_size > max_size:
                return dmc.Alert(
                    f"File size ({file_size / (1024 * 1024):.1f}MB) exceeds the 5MB limit",
                    color="red",
                    icon=DashIconify(icon="mdi:alert"),
                )

            # Save file temporarily for polars validation
            import os
            import tempfile

            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_format}") as tmp_file:
                tmp_file.write(decoded)
                temp_file_path = tmp_file.name

            try:
                # Build polars kwargs based on format and user selections
                polars_kwargs = {}

                if file_format in ["csv", "tsv"]:
                    # Determine separator
                    if separator == "custom" and custom_separator:
                        polars_kwargs["separator"] = custom_separator
                    elif separator == "\t":
                        polars_kwargs["separator"] = "\t"
                    elif separator in [",", ";", "|"]:
                        polars_kwargs["separator"] = separator
                    else:
                        polars_kwargs["separator"] = "," if file_format == "csv" else "\t"

                    # Header handling
                    polars_kwargs["has_header"] = has_header

                    # Try to read with polars
                    df = pl.read_csv(temp_file_path, **polars_kwargs)

                elif file_format == "parquet":
                    df = pl.read_parquet(temp_file_path)

                elif file_format == "feather":
                    df = pl.read_ipc(temp_file_path)

                elif file_format in ["xls", "xlsx"]:
                    df = pl.read_excel(temp_file_path, **polars_kwargs)

                else:
                    raise ValueError(f"Unsupported format: {file_format}")

                # File validation successful - show detailed info
                return dmc.Stack(
                    [
                        dmc.Card(
                            [
                                dmc.Group(
                                    [
                                        DashIconify(icon="mdi:file-check", width=20, color="green"),
                                        dmc.Stack(
                                            [
                                                dmc.Text(filename, fw="bold", size="sm"),
                                                dmc.Text(
                                                    f"Size: {file_size / 1024:.1f}KB • Format: {file_format.upper()}",
                                                    size="xs",
                                                    c="gray",
                                                ),
                                            ],
                                            gap="xs",
                                        ),
                                    ],
                                    gap="md",
                                    align="center",
                                ),
                            ],
                            withBorder=True,
                            shadow="xs",
                            radius="md",
                            p="sm",
                            style={"backgroundColor": "var(--mantine-color-green-0)"},
                        ),
                        dmc.Card(
                            [
                                dmc.Text("Data Preview", fw="bold", size="sm", mb="sm"),
                                dmc.SimpleGrid(
                                    cols=2,
                                    children=[
                                        dmc.Stack(
                                            [
                                                dmc.Text("Rows:", size="xs", fw="bold", c="gray"),
                                                dmc.Text(f"{df.height:,}", size="sm"),
                                            ],
                                            gap="xs",
                                        ),
                                        dmc.Stack(
                                            [
                                                dmc.Text(
                                                    "Columns:", size="xs", fw="bold", c="gray"
                                                ),
                                                dmc.Text(f"{df.width}", size="sm"),
                                            ],
                                            gap="xs",
                                        ),
                                    ],
                                    spacing="sm",
                                ),
                                dmc.Text("Column Names:", size="xs", fw="bold", c="gray", mt="sm"),
                                dmc.Text(
                                    ", ".join(df.columns[:10])
                                    + ("..." if len(df.columns) > 10 else ""),
                                    size="xs",
                                    c="gray",
                                ),
                            ],
                            withBorder=True,
                            shadow="xs",
                            radius="md",
                            p="sm",
                            mt="sm",
                        ),
                    ],
                    gap="sm",
                )

            except Exception as e:
                return dmc.Alert(
                    f"File validation failed: {str(e)}",
                    color="red",
                    icon=DashIconify(icon="mdi:alert"),
                    title="Validation Error",
                )

            finally:
                # Clean up temp file
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)

        except Exception as e:
            return dmc.Alert(
                f"File processing error: {str(e)}",
                color="red",
                icon=DashIconify(icon="mdi:alert"),
            )

    @app.callback(
        [
            Output("data-collection-creation-modal", "opened", allow_duplicate=True),
            Output("project-data-store", "data", allow_duplicate=True),
            Output("data-collection-creation-error-alert", "children", allow_duplicate=True),
            Output("data-collection-creation-error-alert", "style", allow_duplicate=True),
            Output("data-collection-modal-mode", "data", allow_duplicate=True),
        ],
        [Input("create-data-collection-creation-submit", "n_clicks")],
        [
            dash.State("data-collection-modal-mode", "data"),
            dash.State("data-collection-creation-name-input", "value"),
            dash.State("data-collection-creation-description-input", "value"),
            dash.State("data-collection-creation-type-select", "value"),
            dash.State("data-collection-creation-format-select", "value"),
            dash.State("data-collection-creation-separator-select", "value"),
            dash.State("data-collection-creation-custom-separator-input", "value"),
            dash.State("data-collection-creation-compression-select", "value"),
            dash.State("data-collection-creation-has-header-switch", "checked"),
            dash.State("data-collection-creation-file-upload", "contents"),
            dash.State("data-collection-creation-file-upload", "filename"),
            dash.State("data-collection-creation-replace-toggle", "checked"),
            dash.State("data-collection-creation-clear-confirm-name-input", "value"),
            dash.State("project-data-store", "data"),
            dash.State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def submit_data_collection_modal(
        submit_clicks,
        mode_data,
        name,
        description,
        data_type,
        file_format,
        separator,
        custom_separator,
        compression,
        has_header,
        file_contents,
        filename,
        replace_toggle,
        clear_typed_name,
        project_data,
        local_data,
    ):
        """Unified submit handler — dispatches to create / update / clear based on mode.

        Reads ``data-collection-modal-mode.data`` to decide which API call to
        make. Mirrors the previous per-mode submit handlers' outputs so the
        modal closes on success, the error alert surfaces failures, and the
        ``project-data-store.refresh_timestamp`` triggers the page refresh.
        """
        # Helpers for the 5-tuple outputs of this callback.
        no_op = (dash.no_update,) * 5

        def err(msg: str) -> tuple:
            return (dash.no_update, dash.no_update, msg, {"display": "block"}, dash.no_update)

        if not submit_clicks:
            return no_op

        mode = (mode_data or {}).get("mode")
        dc_id = (mode_data or {}).get("dc_id")
        expected_name = (mode_data or {}).get("expected_name")

        # Common project + auth checks shared across all three modes.
        if not project_data or "project_id" not in project_data:
            return err("No project information available")
        project_id = project_data["project_id"]
        if not project_id:
            return err("No project ID available")
        if not local_data or not local_data.get("access_token"):
            return err("Authentication required. Please log in.")
        token = local_data["access_token"]

        try:
            from datetime import datetime

            if mode == "create":
                if not name or not file_contents or not filename:
                    return no_op

                if data_type == "multiqc":
                    from depictio.dash.api_calls import api_call_create_multiqc_data_collection

                    contents_list, filenames_list = _normalize_upload_to_lists(
                        file_contents, filename
                    )

                    result = api_call_create_multiqc_data_collection(
                        name=name,
                        description=description or "",
                        file_contents_list=contents_list,
                        filenames_list=filenames_list,
                        project_id=project_id,
                        token=token,
                    )
                else:
                    from depictio.dash.api_calls import api_call_create_data_collection

                    single_contents = file_contents
                    single_filename = filename
                    if isinstance(file_contents, list):
                        single_contents = file_contents[0]
                    if isinstance(filename, list):
                        single_filename = filename[0]

                    result = api_call_create_data_collection(
                        name=name,
                        description=description or "",
                        data_type=data_type,
                        file_format=file_format,
                        separator=separator,
                        custom_separator=custom_separator,
                        compression=compression,
                        has_header=has_header,
                        file_contents=single_contents,
                        filename=single_filename,
                        project_id=project_id,
                        token=token,
                    )

                action_label = "create"

            elif mode == "update":
                if not dc_id or not file_contents or not filename:
                    return no_op

                contents_list, filenames_list = _normalize_upload_to_lists(file_contents, filename)

                if replace_toggle:
                    result = api_call_overwrite_multiqc_data_collection(
                        project_id=project_id,
                        data_collection_id=str(dc_id),
                        file_contents_list=contents_list,
                        filenames_list=filenames_list,
                        token=token,
                    )
                else:
                    result = api_call_append_to_multiqc_data_collection(
                        project_id=project_id,
                        data_collection_id=str(dc_id),
                        file_contents_list=contents_list,
                        filenames_list=filenames_list,
                        token=token,
                    )

                action_label = "update"

            elif mode == "clear":
                if not dc_id:
                    return no_op
                # Defense-in-depth: clientside callback already gates the
                # button until the typed name matches, but we re-check here.
                if not expected_name or str(clear_typed_name or "") != str(expected_name):
                    return err("Typed name does not match the data collection name.")

                result = api_call_clear_multiqc_data_collection(
                    project_id=project_id,
                    data_collection_id=str(dc_id),
                    token=token,
                )

                action_label = "clear"

            else:
                return err(f"Unknown modal mode: {mode}")

            if result and result.get("success"):
                logger.debug(f"Data collection {action_label} succeeded: {result.get('message')}")
                updated_project_data = project_data.copy()
                updated_project_data["refresh_timestamp"] = datetime.now().isoformat()
                return (
                    False,
                    updated_project_data,
                    "",
                    {"display": "none"},
                    {"mode": None, "dc_id": None, "expected_name": None},
                )

            error_msg = result.get("message", "Unknown error") if result else "API call failed"
            logger.error(f"Data collection {action_label} failed: {error_msg}")
            return err(f"Failed to {action_label} data collection: {error_msg}")
        except Exception as e:
            logger.error(f"Error in modal submit ({mode}): {e}")
            import traceback

            traceback.print_exc()
            return err(f"Unexpected error: {str(e)}")

    # Data collection action buttons callbacks
    @app.callback(
        Output("dc-action-modals-container", "children"),
        [
            Input({"type": "dc-manage-button", "index": dash.ALL}, "n_clicks"),
            Input({"type": "dc-edit-name-button", "index": dash.ALL}, "n_clicks"),
            Input({"type": "dc-delete-button", "index": dash.ALL}, "n_clicks"),
        ],
        [
            dash.State("project-data-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_dc_action_buttons(manage_clicks, edit_clicks, delete_clicks, project_data):
        """Open the right modal for manage / edit-name / delete on a DC.

        ``dc-manage-button`` is a single entry point for all content-modification
        flows. For tabular DCs it opens the legacy overwrite modal. For MultiQC
        DCs we return [] here — the unified modal is opened by a sibling
        callback (``open_modal_for_dc_action``) that has access to the project
        store and can populate the clear-mode preview in one shot.
        """
        ctx_trigger = ctx.triggered_id

        if not ctx_trigger or not any([any(manage_clicks), any(edit_clicks), any(delete_clicks)]):
            return []

        if not project_data:
            return []

        triggered_index = ctx_trigger["index"]
        triggered_type = ctx_trigger["type"]

        data_collections = project_data.get("data_collections", [])

        # Resolve the DC by tag (edit/delete) or by id (manage). Manage button
        # ids are stringified DC ids, while edit/delete still use tags.
        dc_info = None
        if triggered_type == "dc-manage-button":
            for dc in data_collections:
                if str(dc.get("id", "") or dc.get("_id", "")) == str(triggered_index):
                    dc_info = dc
                    break
        else:
            for dc in data_collections:
                if dc.get("data_collection_tag") == triggered_index:
                    dc_info = dc
                    break

        if not dc_info:
            return []

        dc_name = dc_info.get("data_collection_tag", "Unknown")
        dc_id = str(dc_info.get("id", ""))
        dc_type = (dc_info.get("config") or {}).get("type", "")

        if triggered_type == "dc-manage-button":
            # MultiQC DCs are handled by the unified modal via a sibling
            # callback. Tabular DCs use the legacy overwrite modal.
            if dc_type == "multiqc":
                return []
            modal, modal_id = create_data_collection_overwrite_modal(
                opened=True,
                data_collection_name=dc_name,
                data_collection_id=dc_id,
            )
            return [modal]
        elif ctx_trigger["type"] == "dc-edit-name-button":
            modal, modal_id = create_data_collection_edit_name_modal(
                opened=True,
                current_name=dc_name,
                data_collection_id=dc_id,
            )
            return [modal]
        elif ctx_trigger["type"] == "dc-delete-button":
            modal, modal_id = create_data_collection_delete_modal(
                opened=True,
                data_collection_name=dc_name,
                data_collection_id=dc_id,
            )
            return [modal]

        return []

    # Modal close callbacks
    @app.callback(
        Output("data-collection-overwrite-modal", "opened", allow_duplicate=True),
        [Input("cancel-data-collection-overwrite-button", "n_clicks")],
        prevent_initial_call=True,
    )
    def close_overwrite_modal(cancel_clicks):
        """Close overwrite modal when cancel is clicked."""
        if cancel_clicks:
            return False
        return dash.no_update

    @app.callback(
        Output("data-collection-edit-name-modal", "opened", allow_duplicate=True),
        [Input("cancel-data-collection-edit-name-button", "n_clicks")],
        prevent_initial_call=True,
    )
    def close_edit_name_modal(cancel_clicks):
        """Close edit name modal when cancel is clicked."""
        if cancel_clicks:
            return False
        return dash.no_update

    @app.callback(
        Output("data-collection-delete-modal", "opened", allow_duplicate=True),
        [Input("cancel-data-collection-delete-button", "n_clicks")],
        prevent_initial_call=True,
    )
    def close_delete_modal(cancel_clicks):
        """Close delete modal when cancel is clicked."""
        if cancel_clicks:
            return False
        return dash.no_update

    # Edit name functionality callbacks
    @app.callback(
        [
            Output("data-collection-edit-name-modal", "opened", allow_duplicate=True),
            Output("project-data-store", "data", allow_duplicate=True),
            Output("data-collection-edit-name-error-alert", "children", allow_duplicate=True),
            Output("data-collection-edit-name-error-alert", "style", allow_duplicate=True),
        ],
        [Input("confirm-data-collection-edit-name-submit", "n_clicks")],
        [
            dash.State("data-collection-edit-name-name-input", "value"),
            dash.State("data-collection-edit-name-dc-id", "data"),
            dash.State("project-data-store", "data"),
            dash.State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_edit_name_submit(submit_clicks, new_name, dc_id, project_data, local_data):
        """
        Handle edit name modal submission.

        Validates inputs, calls API to update data collection name, and
        triggers project data refresh on success.

        Args:
            submit_clicks: Submit button click count.
            new_name: New name for the data collection.
            dc_id: Data collection ID to update.
            project_data: Project data for refresh timestamp.
            local_data: Local storage with access token.

        Returns:
            Tuple of (modal_opened, project_data, error_message, error_style)
        """
        if not submit_clicks or not new_name or not dc_id:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        try:
            from datetime import datetime

            from depictio.dash.api_calls import api_call_edit_data_collection_name

            logger.info(f"Editing data collection name: {dc_id} -> {new_name}")

            if not local_data or not local_data.get("access_token"):
                return (
                    dash.no_update,
                    dash.no_update,
                    "Authentication required",
                    {"display": "block"},
                )

            result = api_call_edit_data_collection_name(dc_id, new_name, local_data["access_token"])

            if result and result.get("success"):
                logger.debug(f"Data collection name updated successfully: {result.get('message')}")
                # Update project data store to trigger refresh
                updated_project_data = project_data.copy()
                updated_project_data["refresh_timestamp"] = datetime.now().isoformat()
                # Close modal and refresh project data (hide error alert)
                return False, updated_project_data, "", {"display": "none"}
            else:
                error_msg = result.get("message", "Unknown error") if result else "API call failed"
                logger.error(f"Failed to update data collection name: {error_msg}")
                return (
                    dash.no_update,
                    dash.no_update,
                    f"Failed to update name: {error_msg}",
                    {"display": "block"},
                )

        except Exception as e:
            logger.error(f"Error updating data collection name: {str(e)}")
            return (
                dash.no_update,
                dash.no_update,
                f"Unexpected error: {str(e)}",
                {"display": "block"},
            )

    # Delete functionality callbacks
    @app.callback(
        [
            Output("data-collection-delete-modal", "opened", allow_duplicate=True),
            Output("project-data-store", "data", allow_duplicate=True),
            Output("data-collection-delete-error-alert", "children", allow_duplicate=True),
            Output("data-collection-delete-error-alert", "style", allow_duplicate=True),
        ],
        [Input("confirm-data-collection-delete-submit", "n_clicks")],
        [
            dash.State("data-collection-delete-dc-id", "data"),
            dash.State("project-data-store", "data"),
            dash.State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_delete_submit(submit_clicks, dc_id, project_data, local_data):
        """
        Handle delete modal submission.

        Validates inputs, calls API to delete data collection, and
        triggers project data refresh on success.

        Args:
            submit_clicks: Submit button click count.
            dc_id: Data collection ID to delete.
            project_data: Project data for refresh timestamp.
            local_data: Local storage with access token.

        Returns:
            Tuple of (modal_opened, project_data, error_message, error_style)
        """
        if not submit_clicks or not dc_id:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        try:
            from datetime import datetime

            from depictio.dash.api_calls import api_call_delete_data_collection

            logger.info(f"Deleting data collection: {dc_id}")

            if not local_data or not local_data.get("access_token"):
                return (
                    dash.no_update,
                    dash.no_update,
                    "Authentication required",
                    {"display": "block"},
                )

            result = api_call_delete_data_collection(dc_id, local_data["access_token"])

            if result and result.get("success"):
                logger.info(f"Data collection deleted successfully: {result.get('message')}")
                # Update project data store to trigger refresh
                updated_project_data = project_data.copy()
                updated_project_data["refresh_timestamp"] = datetime.now().isoformat()
                # Close modal and refresh project data (hide error alert)
                return False, updated_project_data, "", {"display": "none"}
            else:
                error_msg = result.get("message", "Unknown error") if result else "API call failed"
                logger.error(f"Failed to delete data collection: {error_msg}")
                return (
                    dash.no_update,
                    dash.no_update,
                    f"Failed to delete: {error_msg}",
                    {"display": "block"},
                )

        except Exception as e:
            logger.error(f"Error deleting data collection: {str(e)}")
            return (
                dash.no_update,
                dash.no_update,
                f"Unexpected error: {str(e)}",
                {"display": "block"},
            )

    # Overwrite functionality callbacks
    @app.callback(
        Output("confirm-data-collection-overwrite-submit", "disabled"),
        [
            Input("data-collection-overwrite-file-upload", "contents"),
            Input("data-collection-overwrite-schema-validation", "children"),
        ],
    )
    def update_overwrite_submit_button_state(file_contents, validation_result):
        """
        Enable/disable overwrite submit button based on file upload and validation.

        Enables button only when file is uploaded and schema validation passes.
        Checks validation result for green color or 'validation passed' text.

        Args:
            file_contents: Uploaded file contents.
            validation_result: Schema validation result component(s).

        Returns:
            bool: True to disable button, False to enable.
        """
        logger.debug(
            f"Button state update: file_contents={'[PRESENT]' if file_contents else '[MISSING]'}"
        )
        logger.debug(f"Validation result type: {type(validation_result)}")
        logger.debug(f"Validation result: {validation_result}")

        if not file_contents:
            logger.debug("No file contents, disabling button")
            return True

        # Check if validation was successful
        if isinstance(validation_result, list) and len(validation_result) > 0:
            logger.debug(f"Validation result is list with {len(validation_result)} items")
            # Look for a successful validation indicator
            for i, child in enumerate(validation_result):
                logger.debug(f"Checking validation item {i}: {type(child)}")

                # Handle both dict format (from serialization) and component objects
                if isinstance(child, dict) and "props" in child:
                    props = child["props"]
                    logger.debug(f"Item {i} has dict props: color={props.get('color')}")
                    # Check for green color (success)
                    if props.get("color") == "green":
                        return False
                    # Check for validation passed text
                    if (
                        "children" in props
                        and "validation passed" in str(props["children"]).lower()
                    ):
                        return False

                elif hasattr(child, "props"):
                    logger.debug(
                        f"Item {i} has object props: {hasattr(child.props, 'color')}, {hasattr(child.props, 'children')}"
                    )
                    # Check for green color (success) and validation passed text
                    if hasattr(child.props, "color") and child.props.color == "green":
                        return False
                    if (
                        hasattr(child.props, "children")
                        and "validation passed" in str(child.props.children).lower()
                    ):
                        logger.debug(
                            "Found validation passed text (object format), enabling button"
                        )
                        return False

        # Also check for direct validation success
        if validation_result and isinstance(validation_result, list):
            for i, item in enumerate(validation_result):
                content = ""
                if isinstance(item, dict) and "props" in item and "children" in item["props"]:
                    content = str(item["props"]["children"]).lower()
                elif hasattr(item, "props") and hasattr(item.props, "children"):
                    content = str(item.props.children).lower()

                if content:
                    logger.debug(f"Item {i} content: {content[:100]}")
                    if "schema validation passed" in content or "validation passed" in content:
                        return False

        logger.debug("No validation success found, keeping button disabled")
        return True

    @app.callback(
        [
            Output("data-collection-overwrite-file-info", "children"),
            Output("data-collection-overwrite-schema-validation", "children"),
        ],
        [Input("data-collection-overwrite-file-upload", "contents")],
        [
            dash.State("data-collection-overwrite-file-upload", "filename"),
            dash.State("data-collection-overwrite-dc-id", "data"),
            dash.State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_overwrite_file_upload(file_contents, filename, dc_id, local_data):
        """
        Handle file upload for overwrite modal with schema validation.

        Uploads file, retrieves existing data collection schema from API,
        and validates that new file has matching columns (excluding system columns).

        Args:
            file_contents: Base64-encoded uploaded file contents.
            filename: Original filename.
            dc_id: Data collection ID to overwrite.
            local_data: Local storage with access token.

        Returns:
            Tuple of (file_info_component, validation_result_component)
        """
        if not file_contents or not filename or not dc_id:
            return [], []

        try:
            import base64
            import tempfile
            from pathlib import Path

            import polars as pl

            from depictio.api.v1.configs.config import settings

            # Decode and save the uploaded file temporarily for validation
            # Debug: Log the file_contents format
            logger.debug(
                f"file_contents format: {file_contents[:100] if file_contents else 'None'}"
            )

            # Handle different file_contents formats
            if file_contents and "," in file_contents:
                # Standard format: "data:mime/type;base64,base64_data"
                base64_data = file_contents.split(",")[1]
                logger.debug(f"Standard format detected, base64 length: {len(base64_data)}")
                file_data = base64.b64decode(base64_data)
            elif file_contents:
                # Fallback: Assume it's already base64 encoded
                try:
                    logger.debug(f"Fallback format detected, content length: {len(file_contents)}")
                    file_data = base64.b64decode(file_contents)
                except Exception as e:
                    logger.error(f"Failed to decode file contents: {e}")
                    return [dmc.Alert("Error decoding file", color="red")], []
            else:
                logger.warning("No file contents provided")
                return [dmc.Alert("No file contents provided", color="red")], []

            logger.debug(f"File data decoded successfully, size: {len(file_data)} bytes")
            temp_file_path = Path(tempfile.gettempdir()) / filename

            with open(temp_file_path, "wb") as f:
                f.write(file_data)

            # Get file size with appropriate units
            file_size = len(file_data)
            if file_size < 1024 * 1024:  # Less than 1MB, show in KB
                file_size_display = f"{file_size / 1024:.2f} KB"
            else:
                file_size_display = f"{file_size / (1024 * 1024):.2f} MB"

            logger.debug(f"File size display: {file_size} bytes = {file_size_display}")

            file_info = dmc.Alert(
                f"File uploaded: {filename} ({file_size_display})",
                color="blue",
                icon=DashIconify(icon="mdi:file-check"),
                variant="light",
            )

            # Get existing data collection schema using the specs endpoint
            try:
                import httpx

                # Get current token from local storage
                token = local_data.get("access_token") if local_data else None
                if not token:
                    return [file_info], [dmc.Alert("Authentication token not found", color="red")]

                # Call the specs endpoint to get data collection metadata
                specs_url = f"{settings.fastapi.url}/depictio/api/v1/datacollections/specs/{dc_id}"
                headers = {"Authorization": f"Bearer {token}"}

                response = httpx.get(specs_url, headers=headers, timeout=30.0)
                response.raise_for_status()

                existing_dc = response.json()

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return [file_info], [dmc.Alert("Data collection not found", color="red")]
                else:
                    return [file_info], [
                        dmc.Alert(
                            f"Failed to retrieve data collection info: {e.response.status_code}",
                            color="red",
                        )
                    ]
            except Exception as e:
                return [file_info], [
                    dmc.Alert(f"Failed to retrieve data collection info: {str(e)}", color="red")
                ]

            # Get existing schema from delta table metadata or try to read from Delta table
            existing_schema = existing_dc.get("delta_table_schema")
            if not existing_schema:
                try:
                    # Construct S3 path for the Delta table
                    s3_path = f"s3://{settings.minio.bucket}/{dc_id}"

                    # Configure S3 storage options for reading Delta table
                    storage_options = {
                        "AWS_ENDPOINT_URL": settings.minio.endpoint_url,
                        "AWS_ACCESS_KEY_ID": settings.minio.aws_access_key_id,
                        "AWS_SECRET_ACCESS_KEY": settings.minio.aws_secret_access_key,
                        "AWS_REGION": "us-east-1",
                        "AWS_ALLOW_HTTP": "true",
                        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
                    }

                    # Read a small sample to get schema
                    df_sample = pl.read_delta(s3_path, storage_options=storage_options).limit(1)

                    # Build schema dictionary from DataFrame
                    existing_schema = {}
                    for col_name in df_sample.columns:
                        col_type = str(df_sample[col_name].dtype)
                        existing_schema[col_name] = {"type": col_type}

                except Exception as e:
                    return [file_info], [
                        dmc.Alert(
                            f"Cannot validate schema: unable to retrieve existing data collection schema ({str(e)})",
                            color="yellow",
                        )
                    ]

            # Try to read the new file
            try:
                # Determine file format from extension
                file_ext = Path(filename).suffix.lower()
                if file_ext == ".csv":
                    df = pl.read_csv(temp_file_path)
                elif file_ext == ".tsv":
                    df = pl.read_csv(temp_file_path, separator="\t")
                elif file_ext == ".parquet":
                    df = pl.read_parquet(temp_file_path)
                elif file_ext == ".feather":
                    df = pl.read_ipc(temp_file_path)
                elif file_ext in [".xls", ".xlsx"]:
                    df = pl.read_excel(temp_file_path)
                else:
                    return [file_info], [
                        dmc.Alert(f"Unsupported file format: {file_ext}", color="red")
                    ]

                # Validate schema - exclude system-generated columns
                system_columns = {"depictio_run_id", "aggregation_time"}
                new_columns = set(df.columns)
                existing_columns = (
                    set(existing_schema.keys()) if isinstance(existing_schema, dict) else set()
                )

                # Remove system columns from existing schema for comparison
                existing_user_columns = existing_columns - system_columns

                if new_columns == existing_user_columns:
                    success_message = f"✓ Schema validation passed! File contains {df.shape[0]} rows and {df.shape[1]} columns with matching schema."
                    logger.debug(f"Schema validation SUCCESS: {success_message}")
                    validation_result = [
                        dmc.Alert(
                            success_message,
                            color="green",
                            icon=DashIconify(icon="mdi:check-circle"),
                            variant="light",
                        )
                    ]
                else:
                    missing_cols = existing_user_columns - new_columns
                    extra_cols = new_columns - existing_user_columns
                    error_msg = "Schema mismatch: "
                    if missing_cols:
                        error_msg += f"Missing columns: {list(missing_cols)}. "
                    if extra_cols:
                        error_msg += f"Extra columns: {list(extra_cols)}. "

                    validation_result = [
                        dmc.Alert(
                            error_msg,
                            color="red",
                            icon=DashIconify(icon="mdi:alert-circle"),
                            variant="light",
                        )
                    ]

            except Exception as e:
                validation_result = [
                    dmc.Alert(
                        f"Failed to read file: {str(e)}",
                        color="red",
                        icon=DashIconify(icon="mdi:alert"),
                    )
                ]

            # Cleanup temp file
            temp_file_path.unlink(missing_ok=True)

            return [file_info], validation_result

        except Exception as e:
            return [
                dmc.Alert(
                    f"File processing error: {str(e)}",
                    color="red",
                    icon=DashIconify(icon="mdi:alert"),
                )
            ], []

    @app.callback(
        [
            Output("data-collection-overwrite-modal", "opened", allow_duplicate=True),
            Output("project-data-store", "data", allow_duplicate=True),
            Output("data-collection-overwrite-error-alert", "children", allow_duplicate=True),
            Output("data-collection-overwrite-error-alert", "style", allow_duplicate=True),
        ],
        [Input("confirm-data-collection-overwrite-submit", "n_clicks")],
        [
            dash.State("data-collection-overwrite-file-upload", "contents"),
            dash.State("data-collection-overwrite-file-upload", "filename"),
            dash.State("data-collection-overwrite-dc-id", "data"),
            dash.State("project-data-store", "data"),
            dash.State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_overwrite_submit(
        submit_clicks, file_contents, filename, dc_id, project_data, local_data
    ):
        """
        Handle overwrite modal submission.

        Validates inputs, determines file format from extension, calls API
        to overwrite data collection with new file, and triggers refresh.

        Args:
            submit_clicks: Submit button click count.
            file_contents: Base64-encoded file contents.
            filename: Original filename (used to detect format).
            dc_id: Data collection ID to overwrite.
            project_data: Project data for refresh timestamp.
            local_data: Local storage with access token.

        Returns:
            Tuple of (modal_opened, project_data, error_message, error_style)
        """
        if not submit_clicks or not file_contents or not filename or not dc_id:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        try:
            from datetime import datetime

            from depictio.dash.api_calls import api_call_overwrite_data_collection

            logger.info(f"Overwriting data collection: {dc_id} with file: {filename}")

            if not local_data or not local_data.get("access_token"):
                return (
                    dash.no_update,
                    dash.no_update,
                    "Authentication required",
                    {"display": "block"},
                )

            # Determine file format and parameters from filename
            from pathlib import Path

            file_ext = Path(filename).suffix.lower()
            file_format = "csv"
            separator = ","
            if file_ext == ".tsv":
                file_format = "tsv"
                separator = "\t"
            elif file_ext == ".parquet":
                file_format = "parquet"
            elif file_ext == ".feather":
                file_format = "feather"
            elif file_ext in [".xls", ".xlsx"]:
                file_format = file_ext[1:]  # Remove the dot

            result = api_call_overwrite_data_collection(
                data_collection_id=dc_id,
                file_contents=file_contents,
                filename=filename,
                token=local_data["access_token"],
                file_format=file_format,
                separator=separator,
                compression="none",
                has_header=True,
            )

            if result and result.get("success"):
                logger.info(f"Data collection overwritten successfully: {result.get('message')}")
                # Update project data store to trigger refresh
                updated_project_data = project_data.copy()
                updated_project_data["refresh_timestamp"] = datetime.now().isoformat()
                # Close modal and refresh project data (hide error alert)
                return False, updated_project_data, "", {"display": "none"}
            else:
                error_msg = result.get("message", "Unknown error") if result else "API call failed"
                logger.error(f"Failed to overwrite data collection: {error_msg}")
                return (
                    dash.no_update,
                    dash.no_update,
                    f"Failed to overwrite: {error_msg}",
                    {"display": "block"},
                )

        except Exception as e:
            logger.error(f"Error overwriting data collection: {str(e)}")
            return (
                dash.no_update,
                dash.no_update,
                f"Unexpected error: {str(e)}",
                {"display": "block"},
            )

    # Storage size display callback
    @app.callback(
        Output("storage-size-display", "children"),
        [Input("project-data-store", "data")],
        prevent_initial_call=False,  # Allow initial call to show default state
    )
    def update_storage_size_display(project_data):
        """
        Update the storage size display card with cumulative size of all data collections.

        Calculates total storage used across all workflows' data collections
        and displays with appropriate color coding (gray=zero, orange=<1GB, red=>=1GB).

        Args:
            project_data: Project data containing workflows with data collections.

        Returns:
            List of Text components showing formatted size and unit.
        """
        if not project_data:
            return [
                dmc.Text("0", size="lg", fw="bold", c="gray", ta="center"),
                dmc.Text("bytes", size="xs", c="gray", ta="center"),
            ]

        try:
            # Extract data collections from project data
            workflows = project_data.get("workflows", [])
            all_data_collections = []

            for workflow in workflows:
                data_collections = workflow.get("data_collections", [])
                all_data_collections.extend(data_collections)

            # Calculate total storage size
            total_size_bytes = calculate_total_storage_size(all_data_collections)
            formatted_size, unit = format_storage_size(total_size_bytes)

            # Determine color based on size
            if total_size_bytes == 0:
                color = "gray"
                formatted_size = "0"
                unit = "bytes"
            elif total_size_bytes < 1024**3:  # Less than 1GB
                color = colors["orange"]
            else:  # 1GB or more
                color = colors["red"]

            return [
                dmc.Text(formatted_size, size="lg", fw="bold", c=color, ta="center"),
                dmc.Text(unit, size="xs", c="gray", ta="center"),
            ]

        except Exception as e:
            logger.error(f"Error calculating storage size: {e}")
            return [
                dmc.Text("Error", size="lg", fw="bold", c="red", ta="center"),
                dmc.Text("calc failed", size="xs", c="gray", ta="center"),
            ]

    # =========================================================================
    # Image DC Preview Modal Callbacks
    # =========================================================================

    @app.callback(
        Output({"type": "image-dc-preview-modal", "index": MATCH}, "opened"),
        [Input({"type": "image-dc-preview-button", "index": MATCH}, "n_clicks")],
        [State({"type": "image-dc-preview-modal", "index": MATCH}, "opened")],
        prevent_initial_call=True,
    )
    def toggle_image_dc_preview_modal(n_clicks, is_opened):
        """Toggle the image DC preview modal open/closed state."""
        if n_clicks:
            return not is_opened
        return is_opened

    @app.callback(
        Output({"type": "image-dc-preview-grid", "index": MATCH}, "children"),
        [Input({"type": "image-dc-preview-modal", "index": MATCH}, "opened")],
        [
            State({"type": "image-dc-preview-store", "index": MATCH}, "data"),
            State("project-data-store", "data"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def load_image_dc_preview_grid(is_opened, dc_store_data, project_data, local_data):
        """
        Load and display sample images when the preview modal is opened.

        Fetches up to 6 sample images from the data collection's delta table
        and displays them in a grid with click-to-enlarge functionality.
        """
        if not is_opened:
            return dash.no_update

        if not dc_store_data or not local_data:
            return dmc.Alert("Missing configuration data", color="yellow")

        dc_id = dc_store_data.get("dc_id")
        image_column = dc_store_data.get("image_column")
        s3_base_folder = dc_store_data.get("s3_base_folder", "")
        thumbnail_size = dc_store_data.get("thumbnail_size", 150)
        token = local_data.get("access_token")

        if not dc_id or not image_column:
            return dmc.Alert("Image column not configured", color="yellow")

        try:
            # Find workflow_id for this DC
            workflow_id = None
            if project_data:
                project_type = project_data.get("project_type", "basic")
                if project_type == "advanced":
                    for workflow in project_data.get("workflows", []):
                        for dc in workflow.get("data_collections", []):
                            if dc.get("id") == dc_id:
                                workflow_id = workflow.get("id")
                                # Get s3_base_folder from DC config if not in store
                                if not s3_base_folder:
                                    dc_config = dc.get("config", {})
                                    dc_specific = dc_config.get("dc_specific_properties", {})
                                    s3_base_folder = dc_specific.get("s3_base_folder", "")
                                break
                        if workflow_id:
                            break
                else:
                    # Basic project - DC ID is the workflow ID
                    workflow_id = dc_id
                    for dc in project_data.get("data_collections", []):
                        if dc.get("id") == dc_id and not s3_base_folder:
                            dc_config = dc.get("config", {})
                            dc_specific = dc_config.get("dc_specific_properties", {})
                            s3_base_folder = dc_specific.get("s3_base_folder", "")
                            break

            # Load sample data from delta table (max 6 images)
            df, error = load_data_collection_dataframe(
                workflow_id=workflow_id,
                data_collection_id=dc_id,
                token=token,
                limit_rows=6,
            )

            if error or df is None:
                return dmc.Alert(
                    f"Could not load image data: {error or 'Unknown error'}",
                    color="red",
                )

            if image_column not in df.columns:
                return dmc.Alert(
                    f"Image column '{image_column}' not found in data",
                    color="yellow",
                )

            # Get image paths from the dataframe
            image_paths = df[image_column].to_list()
            valid_paths = [p for p in image_paths if p and isinstance(p, str)]

            if not valid_paths:
                return dmc.Alert("No valid image paths found in data", color="yellow")

            # Build API base URL - use same approach as image component
            from depictio.api.v1.configs.config import settings
            from depictio.dash.modules.image_component.utils import build_image_url

            api_base_url = f"http://localhost:{settings.fastapi.port}"

            # Create image grid with clickable cards
            image_cards = []
            image_data_stores = []

            for i, img_path in enumerate(valid_paths[:6]):
                # Build image URL using the utility function
                img_url = build_image_url(
                    relative_path=str(img_path),
                    base_s3_folder=s3_base_folder or "",
                    api_base_url=api_base_url,
                )

                # Get filename for display
                filename = img_path.split("/")[-1] if "/" in img_path else img_path

                # Store image data for click handling
                image_data_stores.append(
                    dcc.Store(
                        id={
                            "type": "image-dc-thumb-data",
                            "index": dc_id,
                            "img_index": i,
                        },
                        data={"src": img_url, "title": filename},
                    )
                )

                image_cards.append(
                    html.Div(
                        dmc.Card(
                            [
                                dmc.CardSection(
                                    html.Img(
                                        src=img_url,
                                        style={
                                            "width": "100%",
                                            "height": f"{thumbnail_size}px",
                                            "objectFit": "cover",
                                            "display": "block",
                                        },
                                    ),
                                ),
                                dmc.Text(
                                    filename,
                                    size="xs",
                                    c="gray",
                                    ta="center",
                                    truncate=True,
                                    mt="xs",
                                    px="xs",
                                    pb="xs",
                                ),
                            ],
                            withBorder=True,
                            shadow="sm",
                            radius="md",
                            p=0,
                            style={"cursor": "pointer"},
                        ),
                        id={
                            "type": "image-dc-thumb-card",
                            "index": dc_id,
                            "img_index": i,
                        },
                        n_clicks=0,
                    )
                )

            # Build grid with SimpleGrid
            total_images = len(df)
            grid_content = [
                *image_data_stores,
                dmc.SimpleGrid(
                    children=image_cards,
                    cols={"base": 2, "sm": 3, "md": 4},
                    spacing="md",
                ),
            ]

            # Add note if there are more images
            if total_images > 6:
                grid_content.append(
                    dmc.Text(
                        f"Showing 6 of {total_images}+ images. "
                        "Add an Image component to a dashboard to view all.",
                        size="xs",
                        c="gray",
                        ta="center",
                        mt="md",
                        fs="italic",
                    )
                )

            return dmc.Stack(grid_content, gap="md")

        except Exception as e:
            logger.error(f"Error loading image preview for DC {dc_id}: {e}")
            return dmc.Alert(f"Error loading images: {str(e)}", color="red")

    @app.callback(
        Output({"type": "image-dc-viewer-modal", "index": MATCH}, "opened"),
        Output({"type": "image-dc-viewer-img", "index": MATCH}, "src"),
        Output({"type": "image-dc-viewer-title", "index": MATCH}, "children"),
        Input({"type": "image-dc-thumb-card", "index": MATCH, "img_index": ALL}, "n_clicks"),
        State({"type": "image-dc-thumb-data", "index": MATCH, "img_index": ALL}, "data"),
        State({"type": "image-dc-viewer-modal", "index": MATCH}, "opened"),
        prevent_initial_call=True,
    )
    def open_image_dc_viewer(n_clicks_list, thumb_data_list, current_opened):
        """Open the image viewer modal when a thumbnail is clicked."""
        if not ctx.triggered or not any(n_clicks_list):
            raise dash.exceptions.PreventUpdate

        triggered_id = ctx.triggered_id
        if not triggered_id:
            raise dash.exceptions.PreventUpdate

        clicked_idx = triggered_id.get("img_index")
        if clicked_idx is not None and clicked_idx < len(thumb_data_list):
            img_data = thumb_data_list[clicked_idx]
            if img_data:
                return True, img_data.get("src", ""), img_data.get("title", "")

        raise dash.exceptions.PreventUpdate

    # =========================================================================
    # Unified data-collection modal — open / close / mode-driven visibility
    # =========================================================================

    def _find_dc_in_project_data(project_data: dict | None, dc_id: str) -> dict | None:
        """Locate a data collection dict in the project store by stringified id."""
        if not project_data or not dc_id:
            return None
        for dc in project_data.get("data_collections", []) or []:
            if str(dc.get("id") or dc.get("_id") or "") == str(dc_id):
                return dc
        return None

    @app.callback(
        [
            Output("data-collection-creation-modal", "opened", allow_duplicate=True),
            Output("data-collection-modal-mode", "data", allow_duplicate=True),
            Output("data-collection-creation-clear-summary", "children"),
            Output("data-collection-creation-clear-folder-list", "children"),
            Output("data-collection-creation-clear-confirm-name-input", "value"),
            Output("data-collection-creation-clear-expected-name", "data"),
            Output("data-collection-creation-error-alert", "style", allow_duplicate=True),
            Output("data-collection-creation-action-segment", "value"),
        ],
        [
            Input({"type": "dc-manage-button", "index": ALL}, "n_clicks"),
        ],
        [
            State("project-data-store", "data"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def open_modal_for_dc_action(manage_clicks, project_data, local_data):
        """Open the unified modal in manage flow for a per-DC manage click.

        For MultiQC DCs the modal opens in ``update`` mode with the action
        segment defaulting to ``modify``. The user can flip to ``clear``
        inside the modal via the SegmentedControl. When that happens, the
        clear-mode preview ("N folders • X MB" + folder code block) is
        populated lazily; we pre-populate it on open too so switching is
        instant.

        Tabular DCs are handled by the legacy overwrite modal via the
        sibling ``handle_dc_action_buttons`` callback — this callback
        no-ops for them.
        """
        if not manage_clicks or not any(n for n in manage_clicks if n):
            raise dash.exceptions.PreventUpdate

        triggered_id = ctx.triggered_id
        if not triggered_id or not isinstance(triggered_id, dict):
            raise dash.exceptions.PreventUpdate

        dc_id = triggered_id.get("index")
        if not dc_id:
            raise dash.exceptions.PreventUpdate

        # Only proceed for MultiQC DCs; tabular DCs use the legacy modal.
        dc_info = _find_dc_in_project_data(project_data, str(dc_id))
        if not dc_info:
            raise dash.exceptions.PreventUpdate
        dc_type = (dc_info.get("config") or {}).get("type", "")
        if dc_type != "multiqc":
            raise dash.exceptions.PreventUpdate

        dc_name = dc_info.get("data_collection_tag", "") or str(dc_id)

        # Pre-populate clear preview so the segment-flip is instant.
        token = (local_data or {}).get("access_token", "")
        summary_text = "0 folders • 0.0 MB"
        folder_list_text = "(no reports)"

        if token:
            try:
                fetched = api_call_fetch_all_multiqc_reports(str(dc_id), token)
                reports = (fetched or {}).get("reports", []) or []
                folder_names: list[str] = []
                total_bytes = 0
                for idx, report in enumerate(reports):
                    if not isinstance(report, dict):
                        continue
                    original_path = report.get("original_file_path") or ""
                    folder = _multiqc_folder_from_path(original_path, idx)
                    folder_names.append(folder)

                    size = report.get("deltatable_size_bytes") or report.get("file_size") or 0
                    if isinstance(size, (int, float)):
                        total_bytes += int(size)

                if folder_names:
                    folder_list_text = "\n".join(folder_names)
                summary_text = (
                    f"{len(folder_names)} folder(s) • {total_bytes / (1024 * 1024):.1f} MB"
                )
            except Exception as e:
                logger.error(f"Error preparing clear preview for DC {dc_id}: {e}")
                folder_list_text = f"(error fetching reports: {e})"

        return (
            True,
            {"mode": "update", "dc_id": str(dc_id), "expected_name": dc_name},
            summary_text,
            folder_list_text,
            "",  # reset typed-name input
            dc_name,
            {"display": "none"},
            "modify",  # default segment value when opening
        )

    @app.callback(
        [
            Output("data-collection-creation-name-input-container", "style"),
            Output("data-collection-creation-description-input-container", "style"),
            Output("data-collection-creation-type-select-container", "style"),
            Output("data-collection-creation-table-options-container", "style"),
            Output("data-collection-creation-multiqc-options-container", "style"),
            Output("data-collection-creation-action-segment-container", "style"),
            Output("data-collection-creation-replace-toggle-container", "style"),
            Output("data-collection-creation-dropzone-container", "style"),
            Output("data-collection-creation-clear-warning-container", "style"),
            Output("data-collection-creation-clear-summary-container", "style"),
            Output("data-collection-creation-clear-confirm-container", "style"),
            Output("data-collection-creation-title-text", "children"),
            Output("data-collection-creation-title-text", "c"),
            Output("data-collection-creation-title-icon", "icon"),
            Output("data-collection-creation-title-icon", "color"),
            Output("create-data-collection-creation-submit", "color"),
            Output("create-data-collection-creation-submit-icon", "icon"),
        ],
        [
            Input("data-collection-modal-mode", "data"),
            Input("data-collection-creation-type-select", "value"),
        ],
    )
    def update_modal_section_visibility(mode_data, data_type):
        """Toggle modal sections + title + submit-button color based on mode.

        Sections are wrapped in stable container Divs (built unconditionally
        in :func:`create_data_collection_modal`); this callback flips each
        container's ``style.display`` to match the active mode. The title
        text + icon and the submit button's color/icon are also rebound here.
        """
        show: dict = {"width": "100%"}
        hide: dict = {"display": "none"}

        mode = (mode_data or {}).get("mode") or "create"
        # Unknown modes fall back to the create-mode visuals.
        if mode not in ("create", "update", "clear"):
            mode = "create"

        # Per-mode config for the simple boolean toggles + title/icon.
        # The data-type-dependent table/multiqc visibility is handled below
        # because it's the only field that depends on a non-mode input.
        per_mode = {
            "create": {
                "name": show,
                "description": show,
                "type": show,
                "segment": hide,
                "replace": hide,
                "dropzone": show,
                "clear_warning": hide,
                "clear_summary": hide,
                "clear_confirm": hide,
                "title_text": "Create Data Collection",
                "title_icon": "mdi:database-plus",
                "submit_icon": "mdi:plus",
            },
            "update": {
                "name": hide,
                "description": hide,
                "type": hide,
                "segment": show,
                "replace": show,
                "dropzone": show,
                "clear_warning": hide,
                "clear_summary": hide,
                "clear_confirm": hide,
                "title_text": "Manage Data Collection",
                "title_icon": "mdi:database-cog",
                "submit_icon": "mdi:cloud-upload",
            },
            "clear": {
                "name": hide,
                "description": hide,
                "type": hide,
                "segment": show,
                "replace": hide,
                "dropzone": hide,
                "clear_warning": show,
                "clear_summary": show,
                "clear_confirm": show,
                "title_text": "Manage Data Collection",
                "title_icon": "mdi:database-cog",
                "submit_icon": "mdi:database-remove",
            },
        }[mode]

        # Table/MultiQC option visibility is only meaningful in create mode;
        # in update/clear both the type-select and these option blocks are
        # hidden anyway, so we just gate on the data_type input here.
        if mode == "create":
            table_style = hide if data_type == "multiqc" else show
            multiqc_style = show if data_type == "multiqc" else hide
        else:
            table_style = hide
            multiqc_style = hide

        title_color = "teal"  # title + icon + submit share this color
        return (
            per_mode["name"],
            per_mode["description"],
            per_mode["type"],
            table_style,
            multiqc_style,
            per_mode["segment"],
            per_mode["replace"],
            per_mode["dropzone"],
            per_mode["clear_warning"],
            per_mode["clear_summary"],
            per_mode["clear_confirm"],
            per_mode["title_text"],
            title_color,
            per_mode["title_icon"],
            title_color,  # icon color shares the title color
            title_color,
            per_mode["submit_icon"],
        )

    # Clientside callback: drive the submit button label from mode + replace toggle.
    app.clientside_callback(
        dash.ClientsideFunction(
            namespace="depictio_multiqc",
            function_name="compute_modal_submit_label",
        ),
        Output("create-data-collection-creation-submit", "children"),
        Input("data-collection-modal-mode", "data"),
        Input("data-collection-creation-replace-toggle", "checked"),
    )

    @app.callback(
        Output("data-collection-modal-mode", "data", allow_duplicate=True),
        Input("data-collection-creation-action-segment", "value"),
        State("data-collection-modal-mode", "data"),
        prevent_initial_call=True,
    )
    def sync_segment_to_mode(segment_value, mode_data):
        """Flip the mode store when the user toggles the action segment.

        ``modify`` → ``update`` mode (drop folders + replace toggle).
        ``clear`` → ``clear`` mode (typed-name confirm). The dc_id and
        expected_name carried by the store are preserved.
        """
        if not mode_data or not isinstance(mode_data, dict):
            raise dash.exceptions.PreventUpdate
        current_mode = mode_data.get("mode")
        # The segment is only visible in update/clear modes; ignore the
        # callback while we're in create mode.
        if current_mode not in ("update", "clear"):
            raise dash.exceptions.PreventUpdate
        target_mode = "clear" if segment_value == "clear" else "update"
        if target_mode == current_mode:
            raise dash.exceptions.PreventUpdate
        return {**mode_data, "mode": target_mode}


def generate_cytoscape_elements_from_project_data(data_collections):
    """Convert project data collections to cytoscape elements."""
    elements = []

    # First, collect all available columns from each data collection
    dc_columns = {}
    dc_info = {}

    for dc in data_collections:
        dc_tag = dc.get("data_collection_tag", f"DC_{dc.get('id', 'unknown')}")
        dc_info[dc_tag] = dc

        # Try to get columns from the data collection
        columns = []

        # Priority order for finding columns:
        # 1. delta_table_schema if available
        if "delta_table_schema" in dc and dc["delta_table_schema"]:
            schema = dc["delta_table_schema"]
            if isinstance(schema, dict):
                columns = list(schema.keys())
            elif isinstance(schema, list):
                # Schema might be a list of field dictionaries
                columns = [
                    field.get("name", field.get("column", str(field)))
                    for field in schema
                    if isinstance(field, dict)
                ]

        # 2. Check config.dc_specific_properties.columns_description (from YAML)
        elif dc.get("config", {}).get("dc_specific_properties", {}).get("columns_description"):
            columns_desc = dc["config"]["dc_specific_properties"]["columns_description"]
            if isinstance(columns_desc, dict):
                columns = list(columns_desc.keys())

        # 3. Check config.columns
        elif dc.get("config", {}).get("columns"):
            columns = dc["config"]["columns"]

        # 4. Check direct columns field
        elif "columns" in dc:
            columns = dc["columns"]

        # 5. Try to infer from join config + add defaults
        else:
            join_config = dc.get("config", {}).get("join")
            if join_config and "on_columns" in join_config:
                columns.extend(join_config["on_columns"])
            # Add some common default columns for visualization
            defaults = ["id", "name", "created_at", "updated_at"]
            for default in defaults:
                if default not in columns:
                    columns.append(default)

        # Remove duplicates while preserving order and ensure we have at least some columns
        seen = set()
        dc_columns[dc_tag] = [col for col in columns if col and not (col in seen or seen.add(col))]

        # Ensure we have at least one column for visualization
        if not dc_columns[dc_tag]:
            dc_columns[dc_tag] = ["id", "name"]

    # First, collect all join columns from all DCs to mark them properly
    all_join_columns = {}  # dc_tag -> set of join column names

    # Initialize empty sets for all DCs
    for dc in data_collections:
        dc_tag = dc.get("data_collection_tag", f"DC_{dc.get('id', 'unknown')}")
        all_join_columns[dc_tag] = set()

    # Now find all join relationships and mark both source and target columns
    for dc in data_collections:
        dc_tag = dc.get("data_collection_tag", f"DC_{dc.get('id', 'unknown')}")
        join_config = dc.get("config", {}).get("join")

        if join_config and "on_columns" in join_config and "with_dc" in join_config:
            on_columns = join_config["on_columns"]
            target_dc_tags = join_config["with_dc"]

            # Mark source columns as join columns
            all_join_columns[dc_tag].update(on_columns)

            # Mark target columns as join columns (same column names)
            for target_dc_tag in target_dc_tags:
                if target_dc_tag in all_join_columns:
                    all_join_columns[target_dc_tag].update(on_columns)

    logger.debug(f"All join columns mapping: {all_join_columns}")

    # Positioning approach matching the reference file prototype

    # Create data collection groups and column nodes
    for i, dc in enumerate(data_collections):
        dc_id = dc.get("id", f"dc_{i}")
        dc_tag = dc.get("data_collection_tag", f"DC_{i}")
        dc_type = dc.get("config", {}).get("type", "table")
        dc_metatype = dc.get("config", {}).get("metatype", "unknown")

        if dc_type.lower() != "table":
            continue  # Skip non-table collections

        # Get columns for this DC
        columns = dc_columns.get(dc_tag, ["id", "name"])
        num_columns = len(columns)

        # Calculate positions exactly like reference file (lines 510, 515, 518-520)
        x_offset = 300 + i * 350  # More space between data collections horizontally
        box_height = max(
            320, num_columns * 45 + 100
        )  # Min 320px, or 45px per column + more padding

        # Center the background box on the column range (exact copy from reference)
        first_column_y = 140
        last_column_y = 140 + ((num_columns - 1) * 50)
        center_y = (first_column_y + last_column_y) / 2

        # Create data collection background
        elements.append(
            {
                "data": {
                    "id": f"dc_bg_{dc_id}",
                    "label": f"{dc_tag}\n[{dc_metatype}]",
                    "type": "dc_background",
                    "column_count": num_columns,
                    "box_height": box_height,
                },
                "position": {
                    "x": x_offset + 100,
                    "y": center_y,
                },  # Simple positioning like reference
                "classes": f"data-collection-background dc-columns-{min(num_columns, 10)}",
            }
        )

        # Create column nodes
        for j, column in enumerate(columns):
            column_id = f"{dc_tag}/{column}"
            y_offset = 140 + (j * 50)  # Start lower and tighter spacing

            # Check if this column is part of a join (from comprehensive list)
            is_join_column = column in all_join_columns.get(dc_tag, set())

            elements.append(
                {
                    "data": {
                        "id": column_id,
                        "label": column,
                        "type": "column",
                        "dc_tag": dc_tag,
                        "dc_id": dc_id,
                        "is_join_column": is_join_column,
                    },
                    "position": {"x": x_offset + 100, "y": y_offset},
                    "classes": "column-node join-column" if is_join_column else "column-node",
                }
            )

    # Create a mapping from DC tags to their data for easier lookup
    dc_tags_to_data = {}
    for dc in data_collections:
        dc_tag = dc.get("data_collection_tag", f"DC_{dc.get('id', f'dc_{i}')}")
        dc_tags_to_data[dc_tag] = dc

    # Create join edges in a second pass to ensure all nodes exist
    edges_created = set()  # Track edges to avoid duplicates

    for i, dc in enumerate(data_collections):
        dc_tag = dc.get("data_collection_tag", f"DC_{dc.get('id', f'dc_{i}')}")
        join_config = dc.get("config", {}).get("join")

        if not join_config:
            continue

        on_columns = join_config.get("on_columns", [])
        join_type = join_config.get("how", "inner")
        target_dc_tags = join_config.get("with_dc", [])

        for target_dc_tag in target_dc_tags:
            # Check if target DC exists in our data
            target_dc_exists = any(
                d.get("data_collection_tag") == target_dc_tag for d in data_collections
            )

            if not target_dc_exists:
                logger.warning(f"Target DC '{target_dc_tag}' not found in current data collections")
                continue

            for col in on_columns:
                # Check if source DC is MultiQC - skip column node creation for MultiQC
                source_dc_type = dc.get("config", {}).get("type", "table")
                if source_dc_type.lower() == "multiqc":
                    logger.debug(f"Skipping join edge creation for MultiQC collection '{dc_tag}'")
                    continue

                # Check if source node was created
                source_columns = dc_columns.get(dc_tag, [])
                if col not in source_columns:
                    logger.warning(
                        f"Source column '{col}' not found in DC '{dc_tag}' columns: {source_columns}"
                    )
                    # Try to add the column if it's a join column
                    if col not in dc_columns[dc_tag]:
                        dc_columns[dc_tag].append(col)
                        logger.debug(f"Added missing join column '{col}' to DC '{dc_tag}'")

                        # Create the missing column node
                        num_existing_columns = len(
                            [
                                e
                                for e in elements
                                if e["data"].get("dc_tag") == dc_tag
                                and e["data"].get("type") == "column"
                            ]
                        )
                        elements.append(
                            {
                                "data": {
                                    "id": f"{dc_tag}/{col}",
                                    "label": col,
                                    "type": "column",
                                    "dc_tag": dc_tag,
                                    "dc_id": dc.get("id", f"dc_{i}"),
                                    "is_join_column": True,
                                },
                                "position": {
                                    "x": x_offset + 100,
                                    "y": 140
                                    + (num_existing_columns * 50),  # Using 50 like reference
                                },
                                "classes": "column-node join-column",
                            }
                        )

                source_node = f"{dc_tag}/{col}"

                # For target, try the same column name first, then look for similar
                target_columns = dc_columns.get(target_dc_tag, [])
                target_col = col

                if col not in target_columns:
                    # If the exact column name doesn't exist in target, skip this edge
                    # In real joins, column names should match or be explicitly mapped
                    logger.warning(
                        f"Join column '{col}' not found in target DC '{target_dc_tag}' columns: {target_columns}"
                    )

                    # Check if target DC is MultiQC - skip column node creation for MultiQC
                    target_dc_data = dc_tags_to_data.get(target_dc_tag)
                    target_dc_type = (
                        target_dc_data.get("config", {}).get("type", "table")
                        if target_dc_data
                        else "table"
                    )
                    if target_dc_type.lower() == "multiqc":
                        logger.debug(
                            f"Skipping target column creation for MultiQC collection '{target_dc_tag}'"
                        )
                        continue

                    # Still create the target column node for visualization purposes
                    target_col = col
                    if target_col not in dc_columns[target_dc_tag]:
                        dc_columns[target_dc_tag].append(
                            target_col
                        )  # Add missing column to visualization

                        # Create the missing column node
                        target_column_id = f"{target_dc_tag}/{target_col}"
                        target_y = 140 + (
                            len(target_columns) * 50
                        )  # Position after existing columns, using 50 like reference
                        target_dc_index = next(
                            idx
                            for idx, tdc in enumerate(data_collections)
                            if tdc.get("data_collection_tag") == target_dc_tag
                        )
                        target_x_offset = (
                            target_dc_index * 350
                        )  # Simple offset calculation like reference

                        elements.append(
                            {
                                "data": {
                                    "id": target_column_id,
                                    "label": f"{target_col} (join)",
                                    "type": "column",
                                    "dc_tag": target_dc_tag,
                                    "dc_id": dc_tags_to_data[target_dc_tag].get(
                                        "id", f"dc_{target_dc_index}"
                                    ),
                                    "is_join_column": True,
                                },
                                "position": {
                                    "x": target_x_offset + 100,  # Simple positioning like reference
                                    "y": target_y,
                                },
                                "classes": "column-node join-column",
                            }
                        )

                target_node = f"{target_dc_tag}/{target_col}"

                # Create unique edge identifier to avoid duplicates
                edge_key = tuple(sorted([source_node, target_node]))
                if edge_key in edges_created:
                    continue
                edges_created.add(edge_key)

                # Determine adjacency for edge styling
                source_dc_index = i
                target_dc_index = next(
                    (
                        idx
                        for idx, d in enumerate(data_collections)
                        if d.get("data_collection_tag") == target_dc_tag
                    ),
                    0,
                )
                is_adjacent = abs(source_dc_index - target_dc_index) == 1
                adjacency_class = "edge-adjacent" if is_adjacent else "edge-distant"

                elements.append(
                    {
                        "data": {
                            "id": f"join_{dc_tag}_{target_dc_tag}_{col}",
                            "source": source_node,
                            "target": target_node,
                            "label": join_type,
                            "join_type": join_type,
                            "is_adjacent": is_adjacent,
                        },
                        "classes": f"join-edge join-{join_type} {adjacency_class}",
                    }
                )

                logger.debug(f"Created edge: {source_node} -> {target_node} ({join_type})")

    return elements


def load_data_collection_dataframe(
    workflow_id: str | None,
    data_collection_id: str,
    token: str | None = None,
    limit_rows: int = 1000,
) -> tuple[pl.DataFrame | None, str]:
    """
    Generic function to load dataframe from Delta table location.

    Args:
        workflow_id: Workflow ID (optional for basic projects)
        data_collection_id: Data collection ID
        token: Authorization token
        limit_rows: Maximum number of rows to load

    Returns:
        Tuple of (dataframe, error_message)
    """
    try:
        if workflow_id:
            # Advanced project with workflow
            df = load_deltatable_lite(
                workflow_id=ObjectId(workflow_id),
                data_collection_id=ObjectId(data_collection_id),
                metadata=None,
                TOKEN=token,
                limit_rows=limit_rows,
            )
        else:
            # Basic project - load directly using data collection ID
            df = load_deltatable_lite(
                workflow_id=ObjectId(
                    data_collection_id
                ),  # Use DC ID as workflow ID for basic projects
                data_collection_id=ObjectId(data_collection_id),
                metadata=None,
                TOKEN=token,
                limit_rows=limit_rows,
            )
        return df, ""
    except Exception as e:
        logger.error(f"Error loading data collection {data_collection_id}: {e}")
        return None, str(e)
