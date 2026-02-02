"""
Image Component - Design UI Creation Functions

Functions for creating the design/edit interface for image components.
Lazy-loaded only when entering edit mode or stepper.
"""

import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.component_metadata import get_component_color, get_dmc_button_color, is_enabled
from depictio.dash.modules.image_component.utils import build_image_frame
from depictio.dash.utils import UNSELECTED_STYLE

# Default values for image component
DEFAULT_IMAGE_CONFIG = {
    "image_column": None,
    "s3_base_folder": "",
    "thumbnail_size": 150,
}


def _get_dc_image_defaults(data_collection_id: str | None, local_data: dict | None) -> dict:
    """Fetch default values from Image DC config."""
    if not data_collection_id or not local_data:
        return DEFAULT_IMAGE_CONFIG.copy()

    token = local_data.get("access_token")
    if not token:
        return DEFAULT_IMAGE_CONFIG.copy()

    try:
        import httpx

        from depictio.api.v1.configs.config import API_BASE_URL

        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{data_collection_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )

        if response.status_code != 200:
            return DEFAULT_IMAGE_CONFIG.copy()

        dc_data = response.json()
        config = dc_data.get("config", {})

        if config.get("type", "").lower() != "image":
            return DEFAULT_IMAGE_CONFIG.copy()

        props = config.get("dc_specific_properties", {})
        return {
            "image_column": props.get("image_column"),
            "s3_base_folder": props.get("s3_base_folder", ""),
            "thumbnail_size": props.get("thumbnail_size", 150),
        }
    except Exception as e:
        logger.warning(f"Failed to fetch DC image defaults: {e}")
        return DEFAULT_IMAGE_CONFIG.copy()


def _create_image_edit_form(index: str, df, dc_defaults: dict | None = None) -> dmc.Card:
    """Create the image edit form with input controls."""
    defaults = dc_defaults or {}
    column_options = [{"label": col, "value": col} for col in df.columns]

    # Validate image_column exists in data
    image_column = defaults.get("image_column")
    if image_column and image_column not in df.columns:
        logger.warning(f"DC config image_column '{image_column}' not in data columns")
        image_column = None

    auto_detect_note = " (auto-detected)" if image_column else ""

    return dmc.Card(
        dmc.CardSection(
            dmc.Stack(
                [
                    dmc.TextInput(
                        label="Gallery title",
                        id={"type": "image-input", "index": index},
                        value="",
                        placeholder="Enter a title for the image gallery",
                    ),
                    dmc.Select(
                        label="Image column",
                        description=f"Column containing image paths{auto_detect_note}",
                        id={"type": "image-dropdown-column", "index": index},
                        data=column_options,
                        value=image_column,
                        searchable=True,
                        clearable=False,
                        required=True,
                    ),
                    dmc.TextInput(
                        label="S3 base folder (optional)",
                        description="Base S3 folder path. Leave empty to use DC folder.",
                        id={"type": "image-s3-base-folder", "index": index},
                        value=defaults.get("s3_base_folder", ""),
                        placeholder="s3://bucket/path/to/images/",
                    ),
                ],
                gap="sm",
            ),
            id={"type": "image", "index": index},
            style={"padding": "1rem"},
        ),
        withBorder=True,
        shadow="sm",
        style={"width": "100%"},
    )


def design_image(
    id,
    df,
    workflow_id: str | None = None,
    data_collection_id: str | None = None,
    local_data: dict | None = None,
):
    """Create the image design UI with edit controls and live preview."""
    index = id["index"]
    dc_defaults = _get_dc_image_defaults(data_collection_id, local_data)

    # Left column: edit form
    left_column = dmc.GridCol(
        dmc.Stack(
            [
                dmc.Title("Image Gallery edit menu", order=5, ta="center"),
                _create_image_edit_form(index, df, dc_defaults),
            ],
            align="flex-end",
            justify="center",
            gap="md",
            style={"height": "100%"},
        ),
        span="auto",
        style={"display": "flex", "alignItems": "center", "justifyContent": "flex-end"},
    )

    # Arrow column
    arrow_column = dmc.GridCol(
        dmc.Stack(
            [
                html.Div(style={"height": "50px"}),
                dmc.Center(DashIconify(icon="mdi:arrow-right-bold", width=40, height=40)),
            ],
            align="start",
            justify="start",
            style={"height": "100%"},
        ),
        span="content",
        style={"display": "flex", "alignItems": "center", "justifyContent": "center"},
    )

    # Right column: preview
    right_column = dmc.GridCol(
        dmc.Stack(
            [
                dmc.Title("Preview", order=5, ta="center"),
                dmc.Paper(
                    html.Div(
                        build_image_frame(index=index, show_border=False),
                        id={"type": "component-container", "index": index},
                    ),
                    withBorder=True,
                    radius="md",
                    p="md",
                    style={"width": "100%", "minHeight": "300px"},
                ),
            ],
            align="flex-start",
            justify="center",
            gap="md",
            style={"height": "100%"},
        ),
        span="auto",
        style={"display": "flex", "alignItems": "center", "justifyContent": "flex-start"},
    )

    main_layout = dmc.Grid(
        [left_column, arrow_column, right_column],
        justify="center",
        align="center",
        gutter="md",
        style={"height": "100%", "minHeight": "400px"},
    )

    bottom_section = dmc.Stack(
        [
            dmc.Title("Data Collection - Columns description", order=5, ta="center"),
            html.Div(id={"type": "image-columns-description", "index": index}),
        ],
        gap="md",
        style={"marginTop": "2rem"},
    )

    return [dmc.Stack([main_layout, html.Hr(), bottom_section], gap="lg")]


def create_stepper_image_button(n, disabled=None):
    """Create the stepper image button for component type selection."""
    if disabled is None:
        disabled = not is_enabled("image")

    color = get_dmc_button_color("image")
    hex_color = get_component_color("image")

    button = dmc.Button(
        "Image",
        id={"type": "btn-option", "index": n, "value": "Image"},
        n_clicks=0,
        style={**UNSELECTED_STYLE, "fontSize": "26px"},
        size="xl",
        variant="outline",
        color=color,
        leftSection=DashIconify(icon="mdi:image-multiple", color=hex_color),
        disabled=disabled,
    )

    store = dcc.Store(
        id={"type": "store-btn-option", "index": n, "value": "Image"},
        data=0,
        storage_type="memory",
    )

    return button, store
