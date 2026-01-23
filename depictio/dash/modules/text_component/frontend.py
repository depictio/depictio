"""Frontend module for text components in the Depictio dashboard.

This module provides the UI components, callbacks, and interaction handlers for
inline-editable text elements. It supports markdown-style headers (# through #####)
with text alignment options (left, center, right).

Key Features:
    - Inline editing with double-click activation
    - Markdown header level support (H1-H6)
    - Text alignment controls
    - Auto-save to dashboard metadata
    - Client-side hover and focus effects
"""

import json

import dash
import dash_mantine_components as dmc
from dash import MATCH, Input, Output, State, callback_context, dcc
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.component_metadata import (
    get_component_color,
    get_dmc_button_color,
    is_enabled,
)
from depictio.dash.modules.text_component.utils import build_text, build_text_frame
from depictio.dash.utils import UNSELECTED_STYLE

_ALIGNMENT_TO_JUSTIFY = {
    "left": "flex-start",
    "center": "center",
    "right": "flex-end",
}


def get_centered_title_style(alignment: str = "left", display: str = "block") -> dict:
    """Build CSS style dictionary for centered title elements.

    Args:
        alignment: Text alignment ('left', 'center', or 'right').
        display: CSS display value ('block' or 'none').

    Returns:
        Dictionary of CSS style properties for the title element.
    """
    justify_content = _ALIGNMENT_TO_JUSTIFY.get(alignment, "flex-start")

    return {
        "cursor": "text",
        "padding": "4px 8px",
        "borderRadius": "4px",
        "transition": "background-color 0.2s",
        "margin": "0",
        "minHeight": "100%",
        "width": "100%",
        "border": "1px dashed transparent",
        "textAlign": alignment,
        "display": "flex" if display == "block" else display,
        "alignItems": "center",
        "justifyContent": justify_content,
    }


def _get_default_store_data() -> dict:
    """Return default store data for text components.

    Returns:
        Dictionary with default text, order, editing state, and alignment.
    """
    return {
        "text": "# Section Title",
        "order": 1,
        "editing": False,
        "alignment": "left",
    }


def _extract_component_index(prop_id: str) -> str:
    """Extract component index from a callback triggered prop_id.

    Args:
        prop_id: The prop_id string from callback context.

    Returns:
        The component index or 'unknown' if extraction fails.
    """
    try:
        component_id_dict = json.loads(prop_id.split(".")[0])
        return component_id_dict.get("index", "unknown")
    except (json.JSONDecodeError, KeyError, IndexError):
        return "unknown"


def _parse_header_level(text: str) -> tuple[str, int]:
    """Parse markdown header level from text content.

    Args:
        text: Text content potentially starting with # characters.

    Returns:
        Tuple of (stripped text content, header order level).
        Order 1-5 for H1-H5, order 6 for regular text.
    """
    if text.startswith("#####"):
        return text[5:].strip(), 5
    if text.startswith("####"):
        return text[4:].strip(), 4
    if text.startswith("###"):
        return text[3:].strip(), 3
    if text.startswith("##"):
        return text[2:].strip(), 2
    if text.startswith("#"):
        return text[1:].strip(), 1
    return text, 6


def _create_text_component(
    component_index: str, data: dict | None, pathname: str | None, is_stepper: bool = True
):
    """Create a text component with the given configuration.

    Args:
        component_index: The unique index for the component.
        data: Local store data containing access token.
        pathname: Current URL pathname for extracting dashboard_id.
        is_stepper: Whether the component is in stepper mode.

    Returns:
        Built text component or fallback textarea on error.
    """
    try:
        dashboard_id = pathname.split("/")[-1] if pathname else None
        access_token = data.get("access_token") if data else None

        text_kwargs = {
            "index": component_index,
            "title": None,
            "content": "# Section Title",
            "stepper": is_stepper,
            "build_frame": True,
            "show_toolbar": True,
            "show_title": False,
            "alignment": "left",
            "wf_id": None,
            "dc_id": None,
            "dashboard_id": dashboard_id,
            "access_token": access_token,
        }
        return build_text(**text_kwargs)
    except Exception as e:
        logger.error(f"Error creating text component: {e}")
        return _create_fallback_textarea(component_index)


def _create_fallback_textarea(component_index: str):
    """Create a fallback textarea when text component creation fails.

    Args:
        component_index: The unique index for the component.

    Returns:
        Stack containing a fallback textarea component.
    """
    return dmc.Stack(
        [
            dmc.Title("Text Component (Fallback Mode)", order=5),
            dmc.Textarea(
                id={"type": "text-editor-fallback", "index": component_index},
                placeholder="Enter your text content here (use # for headers)...",
                style={"width": "100%", "minHeight": "200px"},
                value="# Section Title",
                autosize=True,
                minRows=8,
            ),
        ],
        gap="sm",
    )


def register_callbacks_text_component(app) -> None:
    """Register all Dash callbacks for text component functionality.

    This function registers callbacks for:
        - Toggle edit mode (enter/exit editing)
        - Start edit mode (double-click activation)
        - Auto-focus input fields
        - Update title content from store
        - Text alignment changes
        - Sync with dashboard metadata
        - Client-side hover/interaction effects
        - Component configuration updates

    Args:
        app: The Dash application instance.
    """

    @app.callback(
        [
            Output({"type": "editable-title", "index": MATCH}, "style"),
            Output({"type": "edit-input", "index": MATCH}, "style"),
            Output({"type": "text-store", "index": MATCH}, "data"),
        ],
        [
            Input({"type": "edit-input", "index": MATCH}, "n_submit"),
            Input({"type": "edit-input", "index": MATCH}, "n_blur"),
        ],
        [
            State({"type": "edit-input", "index": MATCH}, "value"),
            State({"type": "text-store", "index": MATCH}, "data"),
        ],
        prevent_initial_call=True,
    )
    def toggle_edit_mode(input_submit, input_blur, input_value, store_data):
        """Toggle between display and edit modes.

        Args:
            input_submit: Number of times Enter was pressed in the input.
            input_blur: Number of times the input lost focus.
            input_value: Current value in the edit input field.
            store_data: Current text component store data.

        Returns:
            Tuple of (title_style, input_style, updated_store_data).
        """
        ctx = callback_context
        if not ctx.triggered:
            return dash.no_update, dash.no_update, dash.no_update

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if not store_data:
            store_data = _get_default_store_data()

        current_alignment = store_data.get("alignment", "left")
        title_style = get_centered_title_style(alignment=current_alignment, display="block")
        input_style = {"display": "none"}

        prop_id = ctx.triggered[0]["prop_id"]
        if "edit-input" in trigger_id and ("n_submit" in prop_id or "n_blur" in prop_id):
            store_data["editing"] = False
            store_data["text"] = input_value

        return title_style, input_style, store_data

    # Callback to start editing when double-clicked (triggered by clientside)
    @app.callback(
        [
            Output({"type": "editable-title", "index": MATCH}, "style", allow_duplicate=True),
            Output({"type": "edit-input", "index": MATCH}, "style", allow_duplicate=True),
            Output({"type": "text-store", "index": MATCH}, "data", allow_duplicate=True),
        ],
        [
            Input({"type": "editable-title", "index": MATCH}, "n_clicks"),
            Input({"type": "edit-btn", "index": MATCH}, "n_clicks"),
        ],
        State({"type": "text-store", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def start_edit_mode(title_clicks, edit_btn_clicks, store_data):
        """Start edit mode when title is clicked via double-click.

        Args:
            title_clicks: Number of clicks on the editable title.
            edit_btn_clicks: Number of clicks on the edit button.
            store_data: Current text component store data.

        Returns:
            Tuple of (title_style, input_style, updated_store_data).
        """
        if not title_clicks and not edit_btn_clicks:
            return dash.no_update, dash.no_update, dash.no_update

        if not store_data:
            store_data = _get_default_store_data()

        logger.debug("Starting edit mode via double-click")

        current_alignment = store_data.get("alignment", "left")
        title_style = get_centered_title_style(alignment=current_alignment, display="none")
        input_style = {"display": "block", "width": "100%"}
        store_data["editing"] = True

        return title_style, input_style, store_data

    # Auto-focus text input when it becomes visible
    app.clientside_callback(
        """
        function(input_style, store_data) {
            // Check if input just became visible
            if (input_style && input_style.display === 'block') {
                // Focus the input after a short delay
                setTimeout(function() {
                    const inputs = document.querySelectorAll('[id*="edit-input"]');
                    inputs.forEach(input => {
                        if (input.style.display === 'block') {
                            input.focus();
                            input.select(); // Select all text for easy editing
                        }
                    });
                }, 100);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output({"type": "edit-input", "index": MATCH}, "data-focus"),
        [
            Input({"type": "edit-input", "index": MATCH}, "style"),
            Input({"type": "text-store", "index": MATCH}, "data"),
        ],
        prevent_initial_call=True,
    )

    # Update title content and order from input
    @app.callback(
        [
            Output({"type": "editable-title", "index": MATCH}, "children"),
            Output({"type": "editable-title", "index": MATCH}, "order"),
        ],
        Input({"type": "text-store", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def update_title_content(store_data):
        """Update title content and order when data changes.

        Args:
            store_data: Current text component store data.

        Returns:
            Tuple of (display_text, header_order).
        """
        if not store_data:
            return "Click to edit", 3

        text = store_data.get("text", "Click to edit")
        return _parse_header_level(text)

    # Text alignment callbacks
    @app.callback(
        [
            Output({"type": "editable-title", "index": MATCH}, "style", allow_duplicate=True),
            Output({"type": "text-store", "index": MATCH}, "data", allow_duplicate=True),
            Output({"type": "alignment-menu-btn", "index": MATCH}, "children"),
        ],
        [
            Input({"type": "align-left-btn", "index": MATCH}, "n_clicks"),
            Input({"type": "align-center-btn", "index": MATCH}, "n_clicks"),
            Input({"type": "align-right-btn", "index": MATCH}, "n_clicks"),
        ],
        [
            State({"type": "text-store", "index": MATCH}, "data"),
            State({"type": "editable-title", "index": MATCH}, "style"),
        ],
        prevent_initial_call=True,
    )
    def update_text_alignment(left_clicks, center_clicks, right_clicks, store_data, current_style):
        """Update text alignment when alignment buttons are clicked.

        Args:
            left_clicks: Number of clicks on left alignment button.
            center_clicks: Number of clicks on center alignment button.
            right_clicks: Number of clicks on right alignment button.
            store_data: Current text component store data.
            current_style: Current style dictionary of the editable title.

        Returns:
            Tuple of (new_style, updated_store_data, alignment_icon).
        """
        ctx = callback_context
        if not ctx.triggered:
            return dash.no_update, dash.no_update, dash.no_update

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if not store_data:
            store_data = _get_default_store_data()

        alignment_config = {
            "align-left-btn": ("left", "tabler:align-left"),
            "align-center-btn": ("center", "tabler:align-center"),
            "align-right-btn": ("right", "tabler:align-right"),
        }

        for btn_type, (alignment, icon_name) in alignment_config.items():
            if btn_type in trigger_id:
                new_style = get_centered_title_style(alignment=alignment, display="block")
                new_store_data = store_data.copy()
                new_store_data["alignment"] = alignment
                icon = DashIconify(icon=icon_name, width=16)
                return new_style, new_store_data, icon

        return dash.no_update, dash.no_update, dash.no_update

    # Sync text-store updates with stored-metadata-component for save functionality
    @app.callback(
        Output({"type": "stored-metadata-component", "index": MATCH}, "data", allow_duplicate=True),
        Input({"type": "text-store", "index": MATCH}, "data"),
        State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        prevent_initial_call=True,  # Required when using allow_duplicate=True
    )
    def sync_text_content_for_save(text_store_data, stored_metadata):
        """Sync text-store updates with stored-metadata-component for save functionality.

        This callback ensures text/alignment changes trigger dashboard saves properly.
        It only updates existing stored-metadata-component stores; store creation is
        handled by build_text() to prevent duplicate store conflicts.

        During dashboard restore, this preserves existing database metadata and only
        updates when there are genuine content or alignment changes.

        Args:
            text_store_data: Data from the text-store component.
            stored_metadata: Current stored metadata for the component.

        Returns:
            Updated metadata dictionary or dash.no_update if no changes needed.
        """
        ctx = callback_context
        if not ctx.triggered:
            return dash.no_update

        if not text_store_data:
            return dash.no_update

        updated_text = text_store_data.get("text", "")
        updated_alignment = text_store_data.get("alignment", "left")

        component_index = _extract_component_index(ctx.triggered[0]["prop_id"])

        if not stored_metadata:
            logger.debug(
                f"stored-metadata-component not ready yet for text component {component_index} - waiting for build_text()"
            )
            return dash.no_update

        existing_content = stored_metadata.get("content", "")
        existing_alignment = stored_metadata.get("alignment", "left")

        if existing_content == updated_text and existing_alignment == updated_alignment:
            return dash.no_update

        updated_metadata = stored_metadata.copy()
        updated_metadata["content"] = updated_text
        updated_metadata["alignment"] = updated_alignment

        return updated_metadata

    # Client-side hover effects and double-click functionality for inline editable text
    app.clientside_callback(
        """
        function() {
            console.log('Text interaction clientside callback triggered');

            function addTextInteractions() {
                // Find all text containers and add interactions
                const textContainers = document.querySelectorAll('[id*="text-container"]');

                textContainers.forEach(container => {
                    if (container.hasAttribute('data-interactions-processed')) return;
                    container.setAttribute('data-interactions-processed', 'true');

                    // Simple hover effects for text containers
                    container.addEventListener('mouseenter', function() {
                        this.style.border = '1px dashed #adb5bd';
                        this.style.cursor = 'pointer';
                    });

                    container.addEventListener('mouseleave', function() {
                        this.style.border = '1px solid transparent';
                        this.style.cursor = 'default';
                    });

                    // Find the editable title and edit button within this container
                    const editableTitle = container.querySelector('[id*="editable-title"]');
                    const editBtn = container.querySelector('[id*="edit-btn"]');

                    if (editableTitle && editBtn) {
                        editableTitle.style.cursor = 'text';
                        editableTitle.title = 'Double-click to edit';

                        // Double-click handler
                        editableTitle.addEventListener('dblclick', function(e) {
                            console.log('Double-click detected, triggering edit button');
                            e.preventDefault();
                            e.stopPropagation();

                            // Trigger the hidden edit button instead of title click
                            editBtn.click();
                        });
                    }
                });
            }

            // Run immediately and periodically
            addTextInteractions();
            setInterval(addTextInteractions, 1000);

            return window.dash_clientside.no_update;
        }
        """,
        Output("page-content", "style"),
        Input("page-content", "children"),
        prevent_initial_call=False,
    )

    # Callback to update text component based on configuration changes
    @app.callback(
        Output({"type": "component-container", "index": MATCH}, "children"),
        [
            Input({"type": "btn-apply-text-settings", "index": MATCH}, "n_clicks"),
            State({"type": "btn-apply-text-settings", "index": MATCH}, "id"),
            State("local-store", "data"),
            State("url", "pathname"),
        ],
        prevent_initial_call=True,
    )
    def update_text_component(n_clicks, id, data, pathname):
        """Update text component based on configuration settings.

        Args:
            n_clicks: Number of clicks on the apply settings button.
            id: Component ID dictionary containing the index.
            data: Local store data containing access token.
            pathname: Current URL pathname.

        Returns:
            Updated text component or fallback component on error.
        """
        component_index = id["index"] if id else None

        if id and str(component_index).endswith("-tmp"):
            return _create_text_component(component_index, data, pathname, is_stepper=True)

        if not data or not n_clicks or n_clicks == 0:
            return build_text_frame(index=component_index)

        return _create_text_component(component_index, data, pathname, is_stepper=True)


def design_text(id: dict):
    """Build the design/configuration panel for text components.

    Creates a UI panel with usage instructions, an add button, and a preview
    area for new text components in the stepper workflow.

    Args:
        id: Component ID dictionary containing the index.

    Returns:
        DMC Stack containing the text component design interface.
    """
    component_index = id["index"]

    usage_alert = dmc.Alert(
        [
            dmc.Text("Text components are designed to be simple section delimiters.", fw="bold"),
            dmc.Text("Double-click on any text in your dashboard to edit it directly.", size="sm"),
            dmc.Text("Use # for H1, ## for H2, ### for H3, #### for H4, ##### for H5", size="sm"),
            dmc.Text("Type your header format directly (e.g., ## My Section)", size="sm"),
        ],
        title="How to use Text Components",
        icon=DashIconify(icon="material-symbols:info"),
        color="blue",
        style={"marginBottom": "20px"},
    )

    add_button_card = dmc.Card(
        [
            dmc.Button(
                "Add Text Component",
                id={"type": "btn-apply-text-settings", "index": component_index},
                n_clicks=0,
                color="orange",
                variant="filled",
                leftSection=DashIconify(icon="mdi:text-box-edit", color="white"),
                fullWidth=True,
                size="lg",
            ),
        ],
        withBorder=True,
        shadow="sm",
        p="lg",
    )

    preview_section = dmc.Stack(
        [
            dmc.Text("Preview:", fw="bold", size="sm"),
            dmc.Paper(
                build_text_frame(index=component_index),
                id={"type": "component-container", "index": component_index},
                withBorder=True,
                style={"border": "2px dashed var(--mantine-color-gray-4)"},
                radius="sm",
                p="md",
                mih=150,
            ),
        ],
        gap="sm",
        mt="md",
    )

    return dmc.Stack([usage_alert, add_button_card, preview_section])


def create_stepper_text_button(n: int, disabled: bool | None = None) -> tuple:
    """Create the stepper text button for the component selector.

    Args:
        n: The stepper index for the button.
        disabled: Override enabled state. If None, uses component metadata.

    Returns:
        Tuple of (button, store) components for the stepper.
    """
    if disabled is None:
        disabled = not is_enabled("text")

    color = get_dmc_button_color("text")
    hex_color = get_component_color("text")

    button = dmc.Button(
        "Text",
        id={"type": "btn-option", "index": n, "value": "Text"},
        n_clicks=0,
        style={**UNSELECTED_STYLE, "fontSize": "26px"},
        size="xl",
        variant="outline",
        color=color,
        leftSection=DashIconify(icon="mdi:text-box-edit", color=hex_color),
        disabled=disabled,
    )

    store = dcc.Store(
        id={"type": "store-btn-option", "index": n, "value": "Text"},
        data=0,
        storage_type="memory",
    )

    return button, store
