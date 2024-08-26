import dash
from dash import html, dcc, Output, Input
import dash_mantine_components as dmc

app = dash.Dash(__name__)

# Improved JavaScript to stop event propagation and prevent default action
app.clientside_callback(
    """
    function(n_clicks) {
        if (n_clicks) {
            var navLinks = document.querySelectorAll('.mantine-NavLink-root');
            navLinks.forEach(function(navLink) {
                var chevron = navLink.querySelector('.mantine-NavLink-chevron');
                if (chevron) {
                    chevron.addEventListener('click', function(event) {
                        event.stopPropagation();
                        event.preventDefault();
                        // Toggle the expanded state
                        navLink.classList.toggle('mantine-NavLink-expanded');
                    });
                }
            });
        }
        return null;
    }
    """,
    Output("dummy-output", "children"),
    Input("main-nav-link", "n_clicks"),
)
app.layout = html.Div(
    [

        dmc.Grid(
            [
                dmc.NavLink(
                    label="Main NavLink",
                    id="main-nav-link",
                    href="www.google.com",
                    children=[
                        dmc.NavLink(label="Nested Link 1", id="nested-link-1", href="www.google.com"),
                        dmc.NavLink(label="Nested Link 2", id="nested-link-2", href="www.google.com"),
                    ],
                ),
                html.Div(id="dummy-output"),  # This is just to trigger the client-side callback
            ],
            style={"width": "300px"},
        ),
    ]
)


if __name__ == "__main__":
    app.run_server(debug=True)
