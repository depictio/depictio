import dash
import dash_html_components as html

# initialize Dash app
app = dash.Dash(__name__)

# define app layout
app.layout = html.Div(
    [
        html.A(
            "Open Google",
            id="google-link",
            href="https://www.google.com",
            target="_blank",
            style={
                "display": "inline-block",
                "margin": "10px",
                "padding": "10px",
                "background-color": "#0275d8",
                "color": "white",
                "border": "none",
                "cursor": "pointer",
                "text-decoration": "none",
                "font-family": "Arial",
                "font-size": "16px",
            },
        )
    ]
)

if __name__ == "__main__":
    app.run_server(debug=True, port=8051)
