import dash_mantine_components as dmc
from dash_iconify import DashIconify
from dash import Input, Output, State, MATCH
from depictio.api.v1.configs.logging import logger

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
        "type": f"{id_prefix}-delete-confirmation-modal",
        "index": item_id,
    }
    modal = dmc.Modal(
        opened=opened,
        id=modal_id,
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
                                    "type": f"cancel-{id_prefix}-delete-button",
                                    "index": item_id,
                                },
                                color="gray",
                                variant="outline",
                                radius="md",
                            ),
                            dmc.Button(
                                delete_button_text,
                                id={
                                    "type": f"confirm-{id_prefix}-delete-button",
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


# def register_delete_confirmation_modal_callbacks(
#     app,
#     id_prefix,
#     trigger_button_id,
# ):
    
#     logger.info(f"App: {app}")
#     logger.info(f"ID Prefix: {id_prefix}")
#     logger.info(f"Trigger Button ID: {trigger_button_id}")
#     # Register generic callbacks for the delete confirmation modal
#     @app.callback(
#         Output(
#             {"type": f"{id_prefix}-delete-confirmation-modal", "index": MATCH}, "opened"
#         ),
#         Input({"type": trigger_button_id["type"], "index": MATCH}, "n_clicks"),
#         State(
#             {"type": f"{id_prefix}-delete-confirmation-modal", "index": MATCH}, "opened"
#         ),
#     )
#     def toggle_delete_confirmation_modal(n_clicks, opened):
#         if n_clicks:
#             return not opened
#         return opened
