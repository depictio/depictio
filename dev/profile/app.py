from datetime import datetime

import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html

# Sample user metadata
user_metadata = {
    "Username": "snehil_vijay",
    "Email": "snehil.vijay@example.com",
    "Login Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "Role": "Admin",
}

# Design layout for the profile page
avatar = html.A(
    dmc.Tooltip(
        dmc.Avatar(
            src="https://e7.pngegg.com/pngimages/799/987/png-clipart-computer-icons-avatar-icon-design-avatar-heroes"
            "-computer-wallpaper-thumbnail.png",
            size="lg",
            radius="xl",
        ),
        label="Snehil Vijay",
        position="bottom",
    ),
    # href="https://www.linkedin.com/in/snehilvj/",
    # target="_blank",
)

# Metadata display
metadata_items = [dbc.ListGroupItem(f"{key}: {value}") for key, value in user_metadata.items()]

metadata_list = dbc.ListGroup(metadata_items, flush=True)

# Layout
layout = dbc.Container(
    [
        dbc.Row(
            [
                dbc.Col(avatar, width="auto"),
                dbc.Col(
                    [
                        html.H3("User Profile"),
                        metadata_list,
                        dmc.Button(
                            "Logout",
                            id="logout-button",
                            variant="outline",
                            color="red",
                            style={"marginTop": "20px"},
                        ),
                    ],
                    width=True,
                ),
            ],
            align="center",
            justify="center",
            className="mt-4",
        )
    ],
    fluid=True,
)

# Example to add this layout to a Dash app
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.layout = layout

if __name__ == "__main__":
    app.run_server(debug=True)
