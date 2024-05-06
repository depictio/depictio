from dash import html, dcc, Input, Output, State
import dash
import pymongo
import dash_draggable

# Load build_car from /Users/tweber/Gits/depictio/depictio/dash/modules/card_component/utils.py
from depictio.dash.modules.card_component.utils import build_card

# Connect to MongoDB
client = pymongo.MongoClient("mongodb://localhost:27018/")
db = client["depictioDB"]
collection = db["dashboards_collection"]

# Retrieve the single document from the collection
doc = collection.find_one()
print(doc)
layout = doc["stored_layout_data"]
# metadata_first_component
metadata = doc["stored_metadata"][0]
from pprint import pprint

pprint(metadata)
# Create a card from the document
card = build_card(
    index="TEST",
    title=metadata["title"],
    wf_id=metadata["wf_id"],
    dc_id=metadata["dc_id"],
    dc_config=metadata["dc_config"],
    column_name=metadata["column_name"],
    column_type=metadata["column_type"],
    aggregation=metadata["aggregation"],
    v=metadata["value"],
)
print(card)


# Create empty dash app
app = dash.Dash(__name__)
app.layout = html.Div(
    [
        dcc.Interval(id="interval", interval=3000, n_intervals=0),
        html.Div(id="dummy-output"),
        dash_draggable.ResponsiveGridLayout(
            id="draggagle",
            clearSavedLayout=True,
            # layouts=init_layout,
            children=card,
            isDraggable=True,
            isResizable=True,
        ),
    ]
)



@app.callback(
    Output("dummy-output", "children"),
    State("draggagle", "layouts"),
    State("draggagle", "children"),
    Input("interval", "n_intervals"),
    prevent_initial_call=True,
)
def update_layouts(layout,children, n_intervals):
    print(layout)
    print(children)
    return None



if __name__ == "__main__":
    app.run_server(debug=True, port=8052)
