from dash import Input, Output, html

layout = html.Div(
    [
        # Navigation bar
        html.Div(
            [
                html.A(
                    "← Back to Home",
                    href="/",
                    style={
                        "textDecoration": "none",
                        "color": "#119DFF",
                        "fontSize": "14px",
                        "fontWeight": "500",
                    },
                    target="_self",
                ),
                html.Span(" | ", style={"margin": "0 10px", "color": "#ccc"}),
                html.A(
                    "Go to Page 2 →",
                    href="/page2/",
                    style={
                        "textDecoration": "none",
                        "color": "#119DFF",
                        "fontSize": "14px",
                        "fontWeight": "500",
                    },
                    target="_self",
                ),
            ],
            style={"marginBottom": "20px", "padding": "10px 0"},
        ),
        # Page content
        html.H3("📊 Welcome to Page 1", style={"color": "#119DFF"}),
        html.P(
            "This page has its own isolated callback registry. Click the button below to test the callback:",
            style={"color": "#666", "marginBottom": "20px"},
        ),
        html.Button(
            "Click Page 1 Button",
            id="btn1",
            n_clicks=0,
            style={
                "padding": "10px 20px",
                "fontSize": "16px",
                "backgroundColor": "#119DFF",
                "color": "white",
                "border": "none",
                "borderRadius": "5px",
                "cursor": "pointer",
            },
        ),
        html.Div(
            id="out1",
            style={
                "marginTop": "20px",
                "fontSize": "18px",
                "color": "#119DFF",
                "fontWeight": "bold",
            },
        ),
    ],
    style={"padding": "20px", "maxWidth": "800px", "margin": "0 auto"},
)


def register_callbacks(app):
    @app.callback(Output("out1", "children"), Input("btn1", "n_clicks"))
    def show_clicks(n):
        return f"✅ Clicked {n} times on Page 1 (isolated callback!)"
