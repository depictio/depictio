# app.py
import dash
from dash import html

app = dash.Dash(__name__)
app.layout = html.Div("Production Test HELLO HELLO ")

# Enable only dev tools UI
# app.enable_dev_tools(debug=False, dev_tools_ui=True, dev_tools_hot_reload=False)

app.enable_dev_tools(
    dev_tools_ui=True,
    dev_tools_serve_dev_bundles=True,
    # dev_tools_hot_reload=True,  # Disable hot reload for production
)


# Expose server for production runners
server = app.server

if __name__ == '__main__':
    app.run(debug=False)