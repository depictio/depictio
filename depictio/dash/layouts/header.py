import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc


def design_header(data):
    """
    Design the header of the dashboard
    """
    init_nclicks_add_button = data["stored_add_button"] if data else {"count": 0}
    init_nclicks_edit_dashboard_mode_button = data["stored_edit_dashboard_mode_button"] if data else [int(0)]

    # Backend components - dcc.Store for storing children and layout - memory storage
    # https://dash.plotly.com/dash-core-components/store
    backend_components = html.Div(
        [
            dcc.Store(id="stored-children", storage_type="memory"),
            dcc.Store(id="stored-layout", storage_type="memory"),
        ]
    )

    # Modal for success message when clicking the save button
    modal_save_button = dbc.Modal(
        [
            dbc.ModalHeader(
                html.H1(
                    "Success!",
                    className="text-success",
                )
            ),
            dbc.ModalBody(
                html.H5(
                    "Your amazing dashboard was successfully saved!",
                    className="text-success",
                ),
                style={"background-color": "#F0FFF0"},
            ),
            dbc.ModalFooter(
                dbc.Button(
                    "Close",
                    id="success-modal-close",
                    className="ml-auto",
                    color="success",
                )
            ),
        ],
        id="success-modal-dashboard",
        centered=True,
    )

    # APP Header

    header_style = {
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "space-between",
        "padding": "10px 20px",
        "backgroundColor": "#f5f5f5",
        "borderBottom": "1px solid #eaeaea",
        "fontFamily": "'Open Sans', sans-serif",
    }

    title_style = {"fontWeight": "bold", "fontSize": "24px", "color": "#333"}
    button_style = {"margin": "0 10px", "fontWeight": "500"}

    header = html.Div(
        [
            html.H1("Depictio", style=title_style),
            html.Div(
                [
                    # Left side of the header - Add new component button
                    dmc.Button(
                        "Add new component",
                        id="add-button",
                        size="lg",
                        radius="xl",
                        variant="gradient",
                        n_clicks=init_nclicks_add_button["count"],
                        style=button_style,
                    ),
                    # Center part of the header - Save button + related modal
                    modal_save_button,
                    dmc.Button(
                        "Save",
                        id="save-button-dashboard",
                        size="lg",
                        radius="xl",
                        variant="gradient",
                        gradient={"from": "teal", "to": "lime", "deg": 105},
                        n_clicks=0,
                    ),
                ],
                style={"display": "flex", "alignItems": "center"},
            ),
            # Right side of the header - Edit dashboard mode button
            dbc.Checklist(
                id="edit-dashboard-mode-button",
                style={"fontSize": "22px"},
                options=[{"label": "Edit dashboard", "value": 0}],
                value=init_nclicks_edit_dashboard_mode_button,
                switch=True,
            ),
            # Store the number of clicks for the add button and edit dashboard mode button
            dcc.Store(
                id="stored-add-button",
                storage_type="memory",
                # storage_type="session",
                data=init_nclicks_add_button,
            ),
            dcc.Store(
                id="stored-edit-dashboard-mode-button",
                storage_type="memory",
                # storage_type="session",
                data=init_nclicks_edit_dashboard_mode_button,
            ),
        ],
        style=header_style,
    )
    return header, backend_components
