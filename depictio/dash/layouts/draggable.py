import json
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash


def register_callbacks_draggable(app):

    # Add a callback to update the isDraggable property
    @app.callback(
        [
            Output("draggable", "isDraggable"),
            Output("draggable", "isResizable"),
            Output("add-button", "disabled"),
            Output("save-button-dashboard", "disabled"),
        ],
        [Input("edit-dashboard-mode-button", "value")],
    )
    def freeze_layout(switch_state):
        # print("\n\n\n")
        # print("freeze_layout")
        # print(switch_state)
        print("\n\n\n")
        # switch based on button's value
        # switch_state = True if len(value) > 0 else False

        if len(switch_state) == 0:
            return False, False, True, True
        else:
            return True, True, False, False
