# Import necessary libraries
import dash
import dash_mantine_components as dmc
from dash import MATCH, Input, Output, State, callback_context, dcc, html
from dash_iconify import DashIconify

# Depictio imports
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.component_metadata import (
    get_dmc_button_color,
    is_enabled,
)
from depictio.dash.modules.text_component.utils import build_text, build_text_frame
from depictio.dash.utils import UNSELECTED_STYLE


def register_callbacks_text_component(app):
    # Inline editable text callbacks

    # Toggle edit mode when double-clicking on title (triggered via clientside callback)
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
        """Toggle between display and edit modes."""
        ctx = callback_context
        logger.info(f"Toggle edit mode triggered by: {ctx.triggered}")
        if not ctx.triggered:
            return dash.no_update, dash.no_update, dash.no_update

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        logger.info(f"Toggle edit mode triggered by: {trigger_id}")

        # Initialize store_data if None
        if not store_data:
            store_data = {
                "text": "# Section Title",
                "order": 1,
                "editing": False,
                "alignment": "left",
            }

        # Base styles
        title_style = {
            "cursor": "text",
            "padding": "4px 8px",
            "borderRadius": "4px",
            "transition": "background-color 0.2s",
            "margin": "8px 0",
            "minHeight": "24px",
            "border": "1px dashed transparent",
        }
        input_style = {"display": "none"}

        if "edit-input" in trigger_id and (
            "n_submit" in ctx.triggered[0]["prop_id"] or "n_blur" in ctx.triggered[0]["prop_id"]
        ):
            # Stop editing and save
            logger.info(f"Stopping edit mode, saving: {input_value}")
            title_style["display"] = "block"
            input_style["display"] = "none"
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
        """Start edit mode when title is clicked (triggered by double-click via clientside)."""
        if not title_clicks and not edit_btn_clicks:
            return dash.no_update, dash.no_update, dash.no_update

        # Initialize store_data if None
        if not store_data:
            store_data = {
                "text": "# Section Title",
                "order": 1,
                "editing": False,
                "alignment": "left",
            }

        logger.info("Starting edit mode via double-click")

        # Start editing
        title_style = {
            "cursor": "text",
            "padding": "4px 8px",
            "borderRadius": "4px",
            "transition": "background-color 0.2s",
            "margin": "8px 0",
            "minHeight": "24px",
            "border": "1px dashed transparent",
            "display": "none",
        }
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
        """Update title content and order when data changes."""
        if not store_data:
            return "Click to edit", 3

        text = store_data.get("text", "Click to edit")

        # Parse header level from text
        if text.startswith("#####"):
            return text[5:].strip(), 5
        elif text.startswith("####"):
            return text[4:].strip(), 4
        elif text.startswith("###"):
            return text[3:].strip(), 3
        elif text.startswith("##"):
            return text[2:].strip(), 2
        elif text.startswith("#"):
            return text[1:].strip(), 1
        else:
            return text, 6  # Use order 6 for regular text (smaller than h5)

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
        """Update text alignment when alignment buttons are clicked."""
        from dash import callback_context

        ctx = callback_context
        if not ctx.triggered:
            return dash.no_update, dash.no_update, dash.no_update

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        # Initialize store_data if None
        if not store_data:
            store_data = {
                "text": "# Section Title",
                "order": 1,
                "editing": False,
                "alignment": "left",
            }

        # Initialize current_style if None
        if not current_style:
            current_style = {
                "cursor": "text",
                "padding": "4px 8px",
                "borderRadius": "4px",
                "transition": "background-color 0.2s",
                "margin": "8px 0",
                "minHeight": "24px",
                "border": "1px dashed transparent",
                "textAlign": "left",
            }

        # Determine alignment and icon based on trigger
        if "align-left-btn" in trigger_id:
            alignment = "left"
            icon = DashIconify(icon="tabler:align-left", width=16)
        elif "align-center-btn" in trigger_id:
            alignment = "center"
            icon = DashIconify(icon="tabler:align-center", width=16)
        elif "align-right-btn" in trigger_id:
            alignment = "right"
            icon = DashIconify(icon="tabler:align-right", width=16)
        else:
            return dash.no_update, dash.no_update, dash.no_update

        # Update style with new alignment
        new_style = current_style.copy()
        new_style["textAlign"] = alignment

        # Update store data with new alignment
        new_store_data = store_data.copy()
        new_store_data["alignment"] = alignment

        logger.info(f"Text alignment changed to: {alignment} - this should trigger dashboard save")

        return new_style, new_store_data, icon

    # Sync text-store updates with stored-metadata-component for save functionality
    @app.callback(
        Output({"type": "stored-metadata-component", "index": MATCH}, "data"),
        Input({"type": "text-store", "index": MATCH}, "data"),
        State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        prevent_initial_call=False,  # Allow initial call to sync alignment from restored text-store
    )
    def sync_text_content_for_save(text_store_data, stored_metadata):
        """
        Sync text-store updates with stored-metadata-component
        to ensure text/alignment changes trigger dashboard saves properly.

        CRITICAL: This callback only updates existing stored-metadata-component stores.
        Store creation is handled by build_text() to prevent duplicate store conflicts.

        IMPORTANT: During dashboard restore, this callback preserves existing database
        metadata and only updates when there are genuine content or alignment changes.
        """
        # Extract component index and trigger information from callback context
        from dash import callback_context

        ctx = callback_context
        if not ctx.triggered:
            return dash.no_update

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        logger.info(f"sync_text_content_for_save triggered by: {trigger_id}")

        if not text_store_data:
            return dash.no_update

        # Get the updated text and alignment from text-store
        updated_text = text_store_data.get("text", "")
        updated_alignment = text_store_data.get("alignment", "left")

        logger.info(
            f"Text store updated - text: {updated_text[:50]}..., alignment: {updated_alignment}"
        )

        # Get the component index from the triggered input
        triggered_input = ctx.triggered[0]["prop_id"]
        try:
            import json

            component_id_dict = json.loads(triggered_input.split(".")[0])
            component_index = component_id_dict.get("index", "unknown")
        except (json.JSONDecodeError, KeyError, IndexError):
            component_index = "unknown"

        # If stored_metadata doesn't exist yet, wait for build_text() to create it
        # This prevents duplicate store creation but allows initial sync once store exists
        if not stored_metadata:
            logger.debug(
                f"stored-metadata-component not ready yet for text component {component_index} - waiting for build_text()"
            )
            # Return no_update to prevent creating duplicate stores
            # The build_text() function should handle store creation
            return dash.no_update

        # If stored_metadata exists, check if it needs updating
        # CRITICAL FIX: During dashboard restore, preserve existing metadata unless there's a real change
        existing_content = stored_metadata.get("content", "")
        existing_alignment = stored_metadata.get("alignment", "left")

        # If text and alignment haven't changed from what's already stored, don't update
        if existing_content == updated_text and existing_alignment == updated_alignment:
            logger.debug(
                f"No content/alignment change for text component {component_index}, preserving existing metadata"
            )
            return dash.no_update

        # Only update if there's a real content or alignment change (user edited the text or changed alignment)
        # This prevents overwriting database metadata during restore
        logger.info(
            f"Text alignment/content changed for component {component_index}: alignment '{existing_alignment}' -> '{updated_alignment}'"
        )

        # Update the stored metadata with new content and alignment, preserving other fields
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

                    // Hover effects for text containers
                    container.addEventListener('mouseenter', function() {
                        this.style.border = '1px dashed #ddd';
                        this.style.backgroundColor = 'var(--app-surface-color, #f9f9f9)';
                        this.style.cursor = 'pointer';
                    });

                    container.addEventListener('mouseleave', function() {
                        this.style.border = '1px solid transparent';
                        this.style.backgroundColor = 'transparent';
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
        """
        Callback to update text component based on configuration settings
        """
        # Handle case where component is in edit mode with temporary ID
        if id and str(id["index"]).endswith("-tmp"):
            logger.debug(f"Processing temporary component ID in stepper mode: {id['index']}")
            # For temporary components in stepper mode, create a basic text component
            try:
                # Extract dashboard_id from pathname for context
                dashboard_id = pathname.split("/")[-1] if pathname else None
                access_token = data.get("access_token") if data else None

                text_kwargs = {
                    "index": id["index"],
                    "title": None,
                    "content": "# Section Title",  # Default content for new text components
                    "stepper": True,  # Important: this is stepper mode
                    "build_frame": True,
                    "show_toolbar": True,
                    "show_title": False,
                    "alignment": "left",  # Default text alignment
                    "wf_id": None,  # Will be auto-filled by build_text if context available
                    "dc_id": None,  # Will be auto-filled by build_text if context available
                    "dashboard_id": dashboard_id,  # Pass dashboard context for wf_id/dc_id lookup
                    "access_token": access_token,  # Pass token for API calls
                }
                new_text = build_text(**text_kwargs)
                return new_text
            except Exception as e:
                logger.error(f"Error creating stepper text component: {e}")
                # Fallback to basic frame if creation fails
                return build_text_frame(index=id["index"])

        if not data or not n_clicks or n_clicks == 0:
            return build_text_frame(index=id["index"])

        # For text components, wf_id and dc_id are optional since they don't depend on data collections
        wf_id = None
        dc_id = None

        logger.info(f"wf_id: {wf_id} (optional for text components)")
        logger.info(f"dc_id: {dc_id} (optional for text components)")

        try:
            # Extract dashboard_id from pathname for context
            dashboard_id = pathname.split("/")[-1] if pathname else None
            access_token = data.get("access_token") if data else None

            # Build the text component with configuration options
            text_kwargs = {
                "index": id["index"],
                "title": None,  # No title needed for inline editable text components
                "content": "# Section Title",  # Changed to markdown format
                "stepper": True,
                "build_frame": True,  # Use frame for editing with loading
                "show_toolbar": True,  # Legacy parameter, not used
                "show_title": False,  # No title needed for inline editable text components
                "alignment": "left",  # Default text alignment
                "wf_id": None,  # Will be auto-filled by build_text if context available
                "dc_id": None,  # Will be auto-filled by build_text if context available
                "dashboard_id": dashboard_id,  # Pass dashboard context for wf_id/dc_id lookup
                "access_token": access_token,  # Pass token for API calls
            }
            new_text = build_text(**text_kwargs)
            return new_text
        except Exception as e:
            logger.error(f"Error creating text component: {e}")
            # Fallback to simple textarea if inline editable text fails
            return html.Div(
                [
                    html.H5("Text Component (Fallback Mode)"),
                    dcc.Textarea(
                        id={"type": "text-editor-fallback", "index": id["index"]},
                        placeholder="Enter your text content here (use # for headers)...",
                        style={"width": "100%", "minHeight": "200px"},
                        value="# Section Title",
                    ),
                ]
            )


def design_text(id):
    # Simplified design for text components - they're meant to be inline editable
    return dmc.Stack(
        [
            dmc.Alert(
                [
                    dmc.Text(
                        "Text components are designed to be simple section delimiters.", fw="bold"
                    ),
                    dmc.Text(
                        "Double-click on any text in your dashboard to edit it directly.", size="sm"
                    ),
                    dmc.Text(
                        "Use # for H1, ## for H2, ### for H3, #### for H4, ##### for H5",
                        size="sm",
                        c="gray",
                    ),
                    dmc.Text(
                        "Type your header format directly (e.g., ## My Section)",
                        size="sm",
                        c="gray",
                    ),
                ],
                title="How to use Text Components",
                icon=DashIconify(icon="material-symbols:info"),
                color="blue",
                style={"marginBottom": "20px"},
            ),
            dmc.Card(
                [
                    dmc.Button(
                        "Add Text Component",
                        id={"type": "btn-apply-text-settings", "index": id["index"]},
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
            ),
            # Simple preview
            html.Div(
                [
                    dmc.Text("Preview:", fw="bold", style={"marginBottom": "10px"}),
                    html.Div(
                        build_text_frame(index=id["index"]),
                        id={
                            "type": "component-container",
                            "index": id["index"],
                        },
                        style={
                            "border": "1px dashed var(--app-border-color, #ddd)",
                            "borderRadius": "4px",
                            "minHeight": "150px",
                            "padding": "10px",
                        },
                    ),
                ],
                style={"marginTop": "20px"},
            ),
        ]
    )


def create_stepper_text_button(n, disabled=None):
    """
    Create the stepper text button

    Args:
        n (_type_): _description_
        disabled (bool, optional): Override enabled state. If None, uses metadata.
    """

    # Use metadata enabled field if disabled not explicitly provided
    if disabled is None:
        disabled = not is_enabled("text")

    color = get_dmc_button_color("text")
    logger.info(f"Text button color: {color}")

    # Create the text button
    button = dmc.Button(
        "Text",
        id={
            "type": "btn-option",
            "index": n,
            "value": "Text",
        },
        n_clicks=0,
        style=UNSELECTED_STYLE,
        size="xl",
        color=get_dmc_button_color("text"),
        leftSection=DashIconify(icon="mdi:text-box-edit", color="white"),
        disabled=disabled,
    )
    store = dcc.Store(
        id={
            "type": "store-btn-option",
            "index": n,
            "value": "Text",
        },
        data=0,
        storage_type="memory",
    )

    return button, store
