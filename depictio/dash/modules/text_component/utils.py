"""
Text component utilities for inline editable text elements.

This module provides utilities for building inline editable text components
that serve as section delimiters and titles within dashboards. Supports
markdown-style headers with configurable alignment and styling.

Key Functions:
    get_first_available_wf_dc_for_text: Get suitable workflow/data collection for text
    create_inline_editable_text: Create an inline editable text component
    build_text_frame: Build the text component frame container
    build_text: Build the complete text component
    build_text_async: Async wrapper for background callbacks
"""

import dash_mantine_components as dmc
import httpx
from dash import dcc
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger


def get_first_available_wf_dc_for_text(dashboard_id, token):
    """
    Get the first available workflow and data collection for text components.

    Text components are mapped to 'table' data collection type. This function
    finds the first workflow that has a 'table' type data collection, making
    text components compatible with the existing data processing pipeline.

    Args:
        dashboard_id: Dashboard ID to get project context.
        token: Authentication token for API calls.

    Returns:
        Tuple of (wf_id, dc_id) if found, or (None, None) if no suitable
        workflow/data collection exists.
    """
    try:
        # Get project from dashboard ID
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/projects/get/from_dashboard_id/{dashboard_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        project = response.json()

        all_wf_dc = project["workflows"]

        # Find first workflow that has a 'table' type data collection (which supports text components)
        for wf in all_wf_dc:
            for dc in wf["data_collections"]:
                if dc["config"]["type"] == "table":
                    logger.info(
                        f"Found suitable workflow for text component: wf_id={wf['id']}, dc_id={dc['id']}"
                    )
                    return wf["id"], dc["id"]

        logger.warning("No suitable workflow/data collection found for text component")
        return None, None

    except Exception as e:
        logger.error(f"Error getting first available wf/dc for text component: {e}")
        return None, None


def create_inline_editable_text(
    component_id, initial_text="# Section Title", initial_order=1, initial_alignment="left"
):
    """
    Create an inline editable text component for dashboard section delimiters.

    Creates a Paper-wrapped Title component that supports inline editing via
    double-click. Includes hidden input and store components for state management.

    Args:
        component_id: Unique identifier for pattern-matching callbacks.
        initial_text: Initial text content (markdown headers supported).
            Defaults to '# Section Title'.
        initial_order: Header order (1-6) for Title component.
            Defaults to 1 (H1).
        initial_alignment: Text alignment ('left', 'center', 'right').
            Defaults to 'left'.

    Returns:
        dmc.Paper component containing the editable text structure.
    """

    return dmc.Paper(
        [
            # The editable text display - just the title, no container
            dmc.Title(
                initial_text.lstrip("#").strip() if initial_text.startswith("#") else initial_text,
                order=initial_order,
                id={"type": "editable-title", "index": component_id},
                style={
                    "cursor": "text",
                    "padding": "4px 8px",
                    "borderRadius": "4px",
                    "transition": "background-color 0.2s",
                    "margin": "0",  # Remove margin to fill container
                    "minHeight": "100%",  # Fill container height
                    "width": "100%",  # Fill container width
                    "border": "1px dashed transparent",
                    "textAlign": initial_alignment,  # Add text alignment
                    "display": "flex",
                    "alignItems": "center",  # Center text vertically within title
                    "justifyContent": initial_alignment
                    if initial_alignment in ["left", "center", "right"]
                    else "left",  # Align horizontally
                },
            ),
            # Hidden input for editing
            dmc.TextInput(
                id={"type": "edit-input", "index": component_id},
                value=initial_text,
                style={"display": "none"},
            ),
            # Hidden edit button (needed for callback infrastructure)
            dmc.ActionIcon(
                DashIconify(icon="material-symbols:edit", width=12),
                size="xs",
                variant="light",
                color="blue",
                id={"type": "edit-btn", "index": component_id},
                style={"display": "none"},  # Keep hidden since we use double-click
            ),
            # Store for component state
            dcc.Store(
                id={"type": "text-store", "index": component_id},
                data={
                    "text": initial_text,
                    "order": initial_order,
                    "editing": False,
                    "alignment": initial_alignment,
                },
            ),
        ],
        id={"type": "text-container", "index": component_id},
        className="text-container-hoverable",  # Add class for hover styling
        w="100%",
        h="100%",
        pos="relative",
        withBorder=False,  # No border by default
        radius="sm",
        p="xs",
        style={
            "width": "100%",
            "height": "100%",
            "display": "flex",
            "flexDirection": "column",
            "justifyContent": "flex-start",  # Let the title handle centering itself
            "alignItems": "stretch",  # Stretch title to fill width
        },
    )


def build_text_frame(index, children=None, show_border=False):
    """
    Build the text component frame container.

    Args:
        index: Component index for pattern-matching callbacks.
        children: Child components to render inside the frame.
        show_border: Whether to show border (for editing mode).

    Returns:
        dmc.Paper: Text component frame container.
    """
    body_id = {"type": "text-body", "index": index}
    component_id = {"type": "text-component", "index": index}

    if children:
        body_content = dmc.Stack(children=children, id=body_id, gap="xs", h="100%")
        padding = "xs"
    else:
        body_content = dmc.Center(
            dmc.Text(
                "Configure your text component using the edit menu",
                size="sm",
                fs="italic",
                ta="center",
            ),
            id=body_id,
            style={"minHeight": "150px", "height": "100%", "minWidth": "150px"},
        )
        padding = "md"

    return dmc.Paper(
        children=[body_content],
        id=component_id,
        withBorder=show_border,
        radius="sm",
        p=padding,
        w="100%",
        h="100%",
    )


def build_text(**kwargs):
    """
    Build the text component with inline editable text.

    Creates a text component with support for inline editing, configurable
    styling, and proper index handling for both stepper and dashboard modes.

    Args:
        **kwargs: Component configuration parameters including:
            - index: Component index for pattern-matching.
            - title: Text component title (optional).
            - content: Initial text content (markdown headers supported).
            - build_frame: Whether to wrap in frame container.
            - stepper: Whether in stepper mode (design workflow).
            - parent_index: Parent component index for editing.
            - show_toolbar: Legacy parameter for formatting controls.
            - show_title: Whether to display the component title.
            - alignment: Text alignment ('left', 'center', 'right').
            - wf_id: Workflow ID (auto-detected if not provided).
            - dc_id: Data collection ID (auto-detected if not provided).
            - access_token: Authentication token.
            - dashboard_id: Dashboard identifier.

    Returns:
        Component tree for inline editable text, optionally wrapped in frame.
    """
    logger.info("Building inline editable text component")

    # Extract parameters
    index = kwargs.get("index")
    title = kwargs.get("title", "Text Component")
    content = kwargs.get("content", "# Section Title")
    build_frame = kwargs.get("build_frame", False)
    stepper = kwargs.get("stepper", False)
    parent_index = kwargs.get("parent_index", None)
    show_toolbar = kwargs.get("show_toolbar", True)  # Legacy parameter
    show_title = kwargs.get("show_title", True)
    alignment = kwargs.get("alignment", "left")  # Text alignment (fallback to left if missing)
    wf_id = kwargs.get("wf_id", None)
    dc_id = kwargs.get("dc_id", None)

    # CRITICAL FIX: Instead of using None, get first available wf_id and dc_id for text components
    # This makes text components compatible with the existing data processing pipeline
    if wf_id is None or dc_id is None:
        # Try to get dashboard context from kwargs
        access_token = kwargs.get("access_token")
        dashboard_id = kwargs.get("dashboard_id")

        # If we have the necessary context, get first available wf_id and dc_id
        if access_token and dashboard_id:
            try:
                first_wf_id, first_dc_id = get_first_available_wf_dc_for_text(
                    dashboard_id, access_token
                )
                if first_wf_id and first_dc_id:
                    wf_id = wf_id or first_wf_id
                    dc_id = dc_id or first_dc_id
                    logger.info(
                        f"Using first available wf_id={wf_id}, dc_id={dc_id} for text component"
                    )
                else:
                    logger.warning(
                        "Could not find suitable wf_id/dc_id for text component, keeping as None"
                    )
            except Exception as e:
                logger.error(f"Error getting first available wf_id/dc_id for text component: {e}")
        else:
            logger.info("No dashboard context available, keeping wf_id/dc_id as None")

    logger.info(
        f"Building text component with index: {index}, stepper: {stepper}, wf_id: {wf_id}, dc_id: {dc_id}, alignment: {alignment}"
    )
    logger.info(f"All kwargs passed to build_text: {list(kwargs.keys())}")

    if stepper:
        # Check if index already has -tmp to avoid double suffixes
        if str(index).endswith("-tmp"):
            store_index = str(index)  # Use as-is if already has -tmp
            data_index = str(index).replace("-tmp", "")  # Clean index for data
        else:
            store_index = f"{index}-tmp"  # Add -tmp suffix
            data_index = str(index)  # Original index for data
    else:
        store_index = (
            str(index).replace("-tmp", "") if index else "unknown"
        )  # Remove -tmp if present
        data_index = store_index

    logger.info(f"Using store index: {store_index}, data index: {data_index}")

    # Create metadata store component with proper index handling
    store_component = dcc.Store(
        id={
            "type": "stored-metadata-component",
            "index": store_index,
        },
        data={
            "index": data_index,  # Store the clean index without -tmp
            "component_type": "text",
            "content": str(content) if content else "# Section Title",
            "parent_index": str(parent_index) if parent_index else None,
            "show_toolbar": bool(show_toolbar),
            "show_title": bool(show_title),
            "alignment": str(alignment) if alignment else "left",  # Store text alignment
            "wf_id": wf_id,
            "dc_id": dc_id,
        },
    )
    logger.info(f"Store component: {store_component}")

    # Convert content to initial text and determine header order
    clean_content = str(content) if content else "# Section Title"

    # Parse initial header level
    initial_order = 1  # Default to H1
    if clean_content.startswith("#####"):
        initial_order = 5
    elif clean_content.startswith("####"):
        initial_order = 4
    elif clean_content.startswith("###"):
        initial_order = 3
    elif clean_content.startswith("##"):
        initial_order = 2
    elif clean_content.startswith("#"):
        initial_order = 1
    else:
        initial_order = 6  # Regular text

    # Create the inline editable text component
    inline_editable_text = create_inline_editable_text(
        component_id=store_index,
        initial_text=clean_content,
        initial_order=initial_order,
        initial_alignment=alignment,  # Use the alignment from kwargs or metadata
    )

    # For dashboard use (build_frame=True, stepper=False), return minimal structure
    if build_frame and not stepper:
        # Dashboard mode - just return the inline editable text with metadata store
        return dmc.Paper(
            [
                inline_editable_text,
                store_component,
            ],
            id={"index": store_index},
            w="100%",
            h="100%",
            withBorder=False,
            radius="sm",
            p="0",  # No padding since inner container has padding
        )

    # For stepper mode or no frame, use more structured layout
    text_content = dmc.Stack(
        [
            # Optional title for the entire component
            dmc.Text(
                title,
                fw="bold",
                size="lg",
                mb="xs",
            )
            if title and show_title
            else None,
            # The inline editable text component
            inline_editable_text,
            # Metadata store
            store_component,
        ],
        gap="xs",
    )

    if not build_frame:
        return text_content
    else:
        # Stepper mode - use frame container
        text_component = build_text_frame(
            index=store_index, children=text_content, show_border=stepper
        )
        return dmc.Paper(
            text_component,
            id={"index": store_index},
            withBorder=False,
            radius="sm",
        )


async def build_text_async(**kwargs):
    """
    Async wrapper for build_text function.

    Used in background callbacks where async execution is needed.
    Currently calls the synchronous build_text function, but could be
    extended to run in a thread pool for true parallelism.

    Args:
        **kwargs: Same parameters as build_text().

    Returns:
        Component tree for inline editable text.
    """
    from depictio.api.v1.configs.logging_init import logger

    logger.info(
        f"🔄 ASYNC TEXT: Building text component asynchronously - Index: {kwargs.get('index', 'UNKNOWN')}"
    )

    # Call the synchronous build_text function
    # In the future, this could run in a thread pool if needed for true parallelism
    result = build_text(**kwargs)

    logger.info(
        f"✅ ASYNC TEXT: Text component built successfully - Index: {kwargs.get('index', 'UNKNOWN')}"
    )
    return result
