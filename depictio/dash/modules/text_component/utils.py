import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger


def create_inline_editable_text(component_id, initial_text="# Section Title", initial_order=1):
    """Create an inline editable text component for dashboard section delimiters."""

    return html.Div(
        [
            # The editable text display
            dmc.Title(
                initial_text.lstrip("#").strip() if initial_text.startswith("#") else initial_text,
                order=initial_order,
                id={"type": "editable-title", "index": component_id},
                style={
                    "cursor": "text",
                    "padding": "4px 8px",
                    "borderRadius": "4px",
                    "transition": "background-color 0.2s",
                    "margin": "8px 0",
                    "minHeight": "24px",
                    "border": "1px dashed transparent",
                },
                c="dark",
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
                data={"text": initial_text, "order": initial_order, "editing": False},
            ),
        ],
        style={
            "border": "1px solid transparent",
            "borderRadius": "8px",
            "padding": "8px",
            "marginBottom": "8px",
            "position": "relative",
        },
        id={"type": "text-container", "index": component_id},
    )


def build_text_frame(index, children=None, show_border=False):
    """
    Build the text component frame container.

    Args:
        index: Component index
        children: Children components to render inside
        show_border: Whether to show border (for editing mode)

    Returns:
        dbc.Card: Text component frame
    """
    if not children:
        return dbc.Card(
            dbc.CardBody(
                html.Div(
                    "Configure your text component using the edit menu",
                    style={
                        "textAlign": "center",
                        "color": "#999",
                        "fontSize": "14px",
                        "fontStyle": "italic",
                    },
                ),
                id={
                    "type": "text-body",
                    "index": index,
                },
                style={
                    "padding": "20px",
                    "display": "flex",
                    "flexDirection": "column",
                    "justifyContent": "center",
                    "alignItems": "center",
                    "minHeight": "150px",  # Ensure minimum height
                    "height": "100%",
                    "minWidth": "150px",  # Ensure minimum width
                },
            ),
            style={
                "width": "100%",
                "height": "100%",
                "padding": "0",
                "margin": "0",
                "boxShadow": "none",
                "border": "1px solid var(--app-border-color, #ddd)",  # Always show border for draggable delimitation
                "borderRadius": "4px",
                "backgroundColor": "var(--app-surface-color, #ffffff)",
            },
            id={
                "type": "text-component",
                "index": index,
            },
        )
    else:
        return dbc.Card(
            dbc.CardBody(
                children=children,
                id={
                    "type": "text-body",
                    "index": index,
                },
                style={
                    "padding": "5px",  # Reduce padding inside the card body
                    "display": "flex",
                    "flexDirection": "column",
                    "justifyContent": "flex-start",  # Align text to top
                    "height": "100%",  # Make sure it fills the parent container
                },
            ),
            style={
                "width": "100%",
                "height": "100%",  # Ensure the card fills the container's height
                "padding": "0",  # Remove default padding
                "margin": "0",  # Remove default margin
                "boxShadow": "none",  # Remove shadow for a cleaner look
                "border": f"1px solid {'var(--app-border-color, #ddd)' if show_border else 'transparent'}",  # Conditional border
                "borderRadius": "4px",
                "backgroundColor": "var(--app-surface-color, #ffffff)",
            },
            id={
                "type": "text-component",
                "index": index,
            },
        )


def build_text(**kwargs):
    """
    Build the text component with inline editable text.

    Args:
        **kwargs: Component configuration parameters including:
            - index: Component index
            - title: Text component title
            - content: Initial text content
            - build_frame: Whether to wrap in frame container
            - stepper: Whether in stepper mode
            - parent_index: Parent component index for editing
            - show_toolbar: Whether to display formatting controls (legacy, kept for compatibility)
            - show_title: Whether to display the component title

    Returns:
        Component tree for inline editable text
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
    wf_id = kwargs.get("wf_id", None)
    dc_id = kwargs.get("dc_id", None)

    logger.info(f"Building text component with index: {index}, stepper: {stepper}")

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
            "title": str(title) if title else None,
            "content": str(content) if content else "# Section Title",
            "parent_index": str(parent_index) if parent_index else None,
            "show_toolbar": bool(show_toolbar),
            "show_title": bool(show_title),
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
        component_id=store_index, initial_text=clean_content, initial_order=initial_order
    )

    # Create the main content container
    text_content = html.Div(
        [
            # Optional title for the entire component
            html.H5(
                title,
                style={
                    "marginBottom": "10px",
                    "color": "var(--app-text-color, #000000)",
                    "fontWeight": "bold",
                },
            )
            if title and show_title
            else None,
            # The inline editable text component
            inline_editable_text,
            # Metadata store
            store_component,
        ]
    )

    if not build_frame:
        return text_content
    else:
        # Build the text component with frame using proper index
        text_component = build_text_frame(
            index=store_index, children=text_content, show_border=stepper
        )

        # Always return the component directly for text components
        # Text components should work immediately without loading delays
        return html.Div(
            text_component,
            id={"index": store_index},  # Preserve the expected id structure
        )
