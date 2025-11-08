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
                        "color": "#FF6B6B",
                        "fontSize": "14px",
                        "fontWeight": "500",
                    },
                    target="_self",
                ),
                html.Span(" | ", style={"margin": "0 10px", "color": "#ccc"}),
                html.A(
                    "Go to Page 1 →",
                    href="/page1/",
                    style={
                        "textDecoration": "none",
                        "color": "#FF6B6B",
                        "fontSize": "14px",
                        "fontWeight": "500",
                    },
                    target="_self",
                ),
            ],
            style={"marginBottom": "20px", "padding": "10px 0"},
        ),
        # Page content
        html.H3("📈 Welcome to Page 2", style={"color": "#FF6B6B"}),
        html.P(
            "This page has its own isolated callback registry. Click the button below to test the callback:",
            style={"color": "#666", "marginBottom": "20px"},
        ),
        html.Button(
            "Click Page 2 Button",
            id="btn2",
            n_clicks=0,
            style={
                "padding": "10px 20px",
                "fontSize": "16px",
                "backgroundColor": "#FF6B6B",
                "color": "white",
                "border": "none",
                "borderRadius": "5px",
                "cursor": "pointer",
            },
        ),
        html.Div(
            id="out2",
            style={
                "marginTop": "20px",
                "fontSize": "18px",
                "color": "#FF6B6B",
                "fontWeight": "bold",
            },
        ),
    ],
    style={"padding": "20px", "maxWidth": "800px", "margin": "0 auto"},
)


def register_callbacks(app):
    @app.callback(Output("out2", "children"), Input("btn2", "n_clicks"))
    def show_clicks(n):
        return f"✅ Clicked {n} times on Page 2 (isolated callback!)"
