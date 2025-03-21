import dash
from dash import html, Input, Output, State, callback, ctx
import dash_mantine_components as dmc
from dash_iconify import DashIconify

# Create the Dash app
app = dash.Dash(__name__)


# Define the delete confirmation modal function
def create_delete_confirmation_modal(
    id_prefix,
    item_id,
    title="Confirm Deletion",
    message="Are you sure you want to delete this item? This action cannot be undone.",
    delete_button_text="Delete",
    cancel_button_text="Cancel",
    icon="mdi:alert-circle",
    opened=False,
):
    """
    Creates a reusable deletion confirmation modal with improved styling.
    """
    modal_id = {
        "type": f"{id_prefix}-confirmation-modal",
        "index": item_id,
    }
    modal = dmc.Modal(
        opened=opened,
        id={
            "type": f"{id_prefix}-confirmation-modal",
            "index": item_id,
        },
        centered=True,
        withCloseButton=False,
        overlayOpacity=0.55,
        overlayBlur=3,
        shadow="xl",
        radius="md",
        size="md",
        zIndex=1000,
        styles={
            "modal": {
                "padding": "24px",
            }
        },
        children=[
            dmc.Stack(
                spacing="lg",
                children=[
                    # Header with icon and title
                    dmc.Group(
                        position="left",
                        spacing="sm",
                        children=[
                            DashIconify(
                                icon=icon,
                                width=28,
                                height=28,
                                color="red",
                            ),
                            dmc.Title(
                                title,
                                order=4,
                                style={"margin": 0},
                            ),
                        ],
                    ),
                    # Divider
                    dmc.Divider(),
                    # Warning message
                    dmc.Text(
                        message,
                        size="sm",
                        color="dimmed",
                        style={"lineHeight": 1.5},
                    ),
                    # Buttons
                    dmc.Group(
                        position="right",
                        spacing="md",
                        mt="md",
                        children=[
                            dmc.Button(
                                cancel_button_text,
                                id={
                                    "type": f"cancel-{id_prefix}-delete",
                                    "index": item_id,
                                },
                                color="gray",
                                variant="outline",
                                radius="md",
                            ),
                            dmc.Button(
                                delete_button_text,
                                id={
                                    "type": f"confirm-{id_prefix}-delete",
                                    "index": item_id,
                                },
                                color="red",
                                radius="md",
                                leftIcon=DashIconify(icon="mdi:delete", width=16),
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
    return modal, modal_id


# Define some sample data
sample_items = [
    {"id": "item1", "name": "Dashboard Alpha"},
    {"id": "item2", "name": "Dashboard Beta"},
    {"id": "item3", "name": "Dashboard Gamma"},
]
modals = []
for item in sample_items:
    # Add a modal for each item
    modal, modal_id = create_delete_confirmation_modal(
        id_prefix="item",
        item_id=item["id"],
        title=f"Delete {item['name']}?",
        message=f"Are you sure you want to delete {item['name']}? This action cannot be undone.",
        delete_button_text="Delete Permanently",
        opened=False,
    )
    modals.append(modal)


# Define the layout


app.layout = dmc.Container(
    children=[
        dmc.Title("Delete Confirmation Modal Demo", order=1, mb="xl", mt="lg"),
        # Sample item cards
        dmc.SimpleGrid(
            cols=3,
            spacing="lg",
            breakpoints=[
                {"maxWidth": 980, "cols": 2},
                {"maxWidth": 600, "cols": 1},
            ],
            children=[
                dmc.Card(
                    withBorder=True,
                    shadow="sm",
                    radius="md",
                    p="lg",
                    id=item["id"],
                    children=[
                        dmc.Group(
                            position="apart",
                            children=[
                                dmc.Text(item["name"], weight=500, size="lg"),
                                dmc.ActionIcon(
                                    color="red",
                                    variant="light",
                                    radius="md",
                                    size="lg",
                                    id={"type": "delete-button", "index": item["id"]},
                                    children=[DashIconify(icon="mdi:delete", width=20)],
                                ),
                            ],
                        ),
                        dmc.Text(
                            f"Sample content for {item['name']}",
                            color="dimmed",
                            size="sm",
                            mt="md",
                        ),
                        modals,
                    ],
                ),
                # Notification area
                dmc.Notification(
                    id="delete-notification",
                    title="Item Deleted",
                    message="The item has been deleted successfully.",
                    color="green",
                    action="show",
                    autoClose=3000,
                    disallowClose=False,
                    style={"display": "none"},
                ),
            ],
            size="lg",
            pt="xl",
            pb="xl",
        ),
    ]
)


# Callback to open the modal
@callback(
    Output({"type": "item-confirmation-modal", "index": dash.MATCH}, "opened"),
    Input({"type": "delete-button", "index": dash.MATCH}, "n_clicks"),
    prevent_initial_call=True,
)
def open_delete_modal(n_clicks):
    if n_clicks:
        return True
    return False


# Callback to close the modal when Cancel is clicked
@callback(
    Output(
        {"type": "item-confirmation-modal", "index": dash.MATCH},
        "opened",
        allow_duplicate=True,
    ),
    Input({"type": "cancel-item-delete", "index": dash.MATCH}, "n_clicks"),
    prevent_initial_call=True,
)
def close_delete_modal(n_clicks):
    if n_clicks:
        return False
    return False


# Callback to handle delete confirmation - only update the modal and store data
@callback(
    Output(
        {"type": "item-confirmation-modal", "index": dash.MATCH},
        "opened",
        allow_duplicate=True,
    ),
    Input({"type": "confirm-item-delete", "index": dash.MATCH}, "n_clicks"),
    State({"type": "confirm-item-delete", "index": dash.MATCH}, "id"),
    prevent_initial_call=True,
)
def handle_delete_confirmation(n_clicks, button_id):
    if n_clicks:
        item_id = button_id["index"]
        # Here you would typically delete the item in your database

        # Find the item name
        item_name = next(
            (item["name"] for item in sample_items if item["id"] == item_id), "Unknown"
        )

        return False, item_name

    return False, ""


# Run the app
if __name__ == "__main__":
    app.run_server(debug=True)
