import importlib
import sys

from dash import Dash, Input, Output, dcc, html

# 👇 Allow dynamic callbacks for components not in the initial layout
app = Dash(__name__, suppress_callback_exceptions=True)
app.title = "Dynamic Dash Pages"

app.layout = html.Div([
    html.H2("Main Navigation"),
    html.Div([
        dcc.Link("Home", href="/", style={"marginRight": "20px"}),
        dcc.Link("Page 1", href="/page1", style={"marginRight": "20px"}),
        dcc.Link("Page 2", href="/page2"),
    ]),
    html.Hr(),
    dcc.Location(id="url"),
    html.Div(id="page-content")
])


@app.callback(Output("page-content", "children"), Input("url", "pathname"))
def display_page(path):
    import importlib
    import sys

    # Unload existing page modules
    for mod in list(sys.modules):
        if mod.startswith("pages.page"):
            del sys.modules[mod]

    # 🔥 Clear the callback registry
    if hasattr(app, "callback_map"):
        app.callback_map.clear()

    # Dynamically import and register the new page
    if path in ("/", "/page1"):
        page = importlib.import_module("pages.page1")
    elif path == "/page2":
        page = importlib.import_module("pages.page2")
    else:
        return html.Div("404 - Page not found")

    page.register_callbacks(app)
    return page.layout




if __name__ == "__main__":
    app.run(debug=True)
