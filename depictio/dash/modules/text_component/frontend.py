# Import necessary libraries
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import MATCH, Input, Output, State, dcc, html
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
    # Callback to update text component based on configuration changes
    @app.callback(
        Output({"type": "component-container", "index": MATCH}, "children"),
        [
            Input({"type": "btn-apply-text-settings", "index": MATCH}, "n_clicks"),
            # State({"type": "input-text-title", "index": MATCH}, "value"),
            # State({"type": "switch-text-show-title", "index": MATCH}, "checked"),
            # State({"type": "switch-text-show-toolbar", "index": MATCH}, "checked"),
            # State({"type": "btn-apply-text-settings", "index": MATCH}, "id"),
            # Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            # Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            # State("local-store", "data"),
            State("url", "pathname"),
        ],
        prevent_initial_call=True,
    )
    def update_text_component(
        n_clicks,
        # title, show_title, show_toolbar, id, wf_id, dc_id, data,
        pathname,
    ):
        """
        Callback to update text component based on configuration settings
        """
        # if not data or not n_clicks or n_clicks == 0:
        #     return build_text_frame(index=id["index"])

        # logger.info(f"wf_id: {wf_id}")
        # logger.info(f"dc_id: {dc_id}")

        # try:
        #     # Build the text component with configuration options
        #     text_kwargs = {
        #         "index": id["index"],
        #         "title": title if show_title else None,
        #         "content": "<p>Start typing your content here...</p>",
        #         "stepper": True,
        #         "build_frame": True,  # Use frame for editing with loading
        #         "show_toolbar": show_toolbar,
        #         "show_title": show_title,
        #         "wf_id": wf_id,
        #         "dc_id": dc_id,
        #     }
        #     new_text = build_text(**text_kwargs)
        #     return new_text
        # except Exception as e:
        #     logger.error(f"Error creating text component: {e}")
        #     # Fallback to simple textarea if RichTextEditor fails
        #     return html.Div(
        #         [
        #             html.H5("Text Component (Fallback Mode)" if show_title else None),
        #             dcc.Textarea(
        #                 id={"type": "text-editor-fallback", "index": id["index"]},
        #                 placeholder="Enter your text content here...",
        #                 style={"width": "100%", "minHeight": "200px"},
        #                 value="<p>Start typing your content here...</p>",
        #             ),
        #         ]
        #     )

        # Get the component index from the callback context
        component_id = n_clicks if hasattr(n_clicks, "__dict__") else {"index": "text-component"}

        # Build text component with proper configuration
        return build_text(
            index=component_id.get("index", "text-component")
            if isinstance(component_id, dict)
            else "text-component",
            title="Text Component",
            content="<p>Start typing your content here...</p>",
            build_frame=True,
            stepper=True,
            show_toolbar=True,
            show_title=True,
        )


def design_text(id):
    # Configuration panel on the left
    left_column = dmc.GridCol(
        dmc.Stack(
            [
                html.H5("Text Component Settings", style={"textAlign": "center"}),
                dmc.Card(
                    dmc.CardSection(
                        dmc.Stack(
                            [
                                dmc.TextInput(
                                    label="Component Title",
                                    placeholder="Enter title (optional)",
                                    id={"type": "input-text-title", "index": id["index"]},
                                    value="Text Component",
                                ),
                                dmc.Switch(
                                    label="Show Title",
                                    description="Display the component title above the text editor",
                                    id={"type": "switch-text-show-title", "index": id["index"]},
                                    checked=True,
                                    size="md",
                                ),
                                dmc.Switch(
                                    label="Show Toolbar",
                                    description="Display the rich text formatting toolbar",
                                    id={"type": "switch-text-show-toolbar", "index": id["index"]},
                                    checked=True,
                                    size="md",
                                ),
                                dmc.Button(
                                    "Apply Settings",
                                    id={"type": "btn-apply-text-settings", "index": id["index"]},
                                    n_clicks=0,
                                    color="orange",
                                    variant="filled",
                                    leftSection=DashIconify(icon="mdi:check", color="white"),
                                ),
                            ],
                            gap="md",
                        ),
                        style={"padding": "1rem"},
                    ),
                    withBorder=True,
                    shadow="sm",
                    style={"maxHeight": "400px", "overflowY": "auto"},
                ),
            ]
        ),
        span="auto",
        style={"minWidth": "300px"},
    )

    # Preview area on the right
    right_column = dmc.GridCol(
        dmc.Stack(
            [
                html.H5("Preview", style={"textAlign": "center"}),
                html.Div(
                    build_text_frame(index=id["index"]),
                    id={
                        "type": "component-container",
                        "index": id["index"],
                    },
                    style={
                        "border": "1px dashed var(--app-border-color, #ddd)",
                        "borderRadius": "4px",
                        "minHeight": "300px",
                        "padding": "10px",
                    },
                ),
            ]
        ),
        span="auto",
    )

    return dmc.Grid([left_column, right_column], gutter="lg")


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
    button = dbc.Col(
        dmc.Button(
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
