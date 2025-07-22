import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import dcc, html

from depictio.api.v1.configs.logging_init import logger


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
    Build the text component with Rich Text Editor.

    Args:
        **kwargs: Component configuration parameters including:
            - index: Component index
            - title: Text component title
            - content: HTML content for the rich text editor
            - build_frame: Whether to wrap in frame container
            - stepper: Whether in stepper mode
            - parent_index: Parent component index for editing
            - show_toolbar: Whether to display the rich text formatting toolbar
            - show_title: Whether to display the component title

    Returns:
        Component tree for text editor
    """
    logger.info("Building text component")

    # Extract parameters
    index = kwargs.get("index")
    title = kwargs.get("title", "Text Component")
    content = kwargs.get("content", "")
    build_frame = kwargs.get("build_frame", False)
    stepper = kwargs.get("stepper", False)
    parent_index = kwargs.get("parent_index", None)
    show_toolbar = kwargs.get("show_toolbar", True)
    show_title = kwargs.get("show_title", True)
    wf_id = kwargs.get("wf_id", None)
    dc_id = kwargs.get("dc_id", None)

    # For stepper mode, use the temporary index to avoid conflicts with existing components
    # For normal mode, use the original index (remove -tmp suffix if present)

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
            "content": str(content) if content else "<p>Start typing your content here...</p>",
            "parent_index": str(parent_index) if parent_index else None,
            "show_toolbar": bool(show_toolbar),
            "show_title": bool(show_title),
            "wf_id": wf_id,
            "dc_id": dc_id,
        },
    )
    logger.info(f"Store component : {store_component}")

    logger.info(f"Has richtexteditor: {hasattr(dmc, 'RichTextEditor')}")

    # # Use the provided content or a simple default
    # if not content:
    #     content = "<p>Start typing your content here...</p>"

    # Create RichTextEditor with enhanced configuration to minimize circular reference issues
    logger.info("Building RichTextEditor with optimized configuration to prevent circular JSON")

    # Ensure we have valid HTML content as a clean string
    clean_content = str(content) if content else "<p>Start typing your content here...</p>"

    # Create the RichTextEditor with absolutely minimal configuration to reduce React Fiber complexity
    text_editor = dmc.RichTextEditor(
        id={
            "type": "text-editor",
            "index": store_index,  # Use the proper store_index
        },
        html=clean_content,  # Use clean string content
        style={
            "minHeight": "300px",
            "width": "100%",
        },
        # Use minimal toolbar to reduce component complexity
        toolbar={
            "controlsGroups": [
                ["Bold", "Italic", "Underline"],
                ["H1", "H2", "H3"],
                ["BulletList", "OrderedList"],
                ["Code", "CodeBlock"],
                ["Link", "Blockquote"],
            ]
        }
        if show_toolbar
        else None,
        # Minimal additional properties
        withTypographyStyles=True,
        withCodeHighlightStyles=True,
    )

    # No toolbar info needed since we're using default RichTextEditor
    toolbar_info = None

    # Create a data store to isolate RichTextEditor content and prevent direct serialization
    editor_content_store = dcc.Store(
        id={
            "type": "text-editor-content",
            "index": store_index,
        },
        data=clean_content,
        storage_type="memory",
    )

    # Create an isolation wrapper to prevent RichTextEditor from being serialized in certain contexts
    text_editor_wrapper = html.Div(
        [
            text_editor,
            editor_content_store,  # Add the content store to buffer data
        ],
        id={
            "type": "text-editor-wrapper",
            "index": store_index,
        },
        # Add some styling to ensure proper rendering
        style={
            "width": "100%",
            "minHeight": "300px",
        },
        # Prevent this wrapper from being included in certain serialization paths
        **{"data-component-type": "text-editor-isolated"},
    )

    # Create the main content
    text_content = html.Div(
        [
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
            toolbar_info,  # Add the toolbar info message
            text_editor_wrapper,  # Use the wrapper instead of direct editor
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

        # For stepper mode with loading
        if not stepper:
            # Use skeleton system for consistent loading experience
            from depictio.dash.layouts.draggable_scenarios.progressive_loading import (
                create_skeleton_component,
            )

            return html.Div(
                dcc.Loading(
                    children=text_component,
                    custom_spinner=create_skeleton_component("text"),
                    delay_show=100,  # Small delay to prevent flashing
                    delay_hide=800,  # Shorter delay for better UX
                ),
                id={"index": store_index},  # Use the proper store_index with -tmp
            )
        else:
            return text_component
