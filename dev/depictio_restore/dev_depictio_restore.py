from dash import html, dcc
import dash 
import pymongo 

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
    index=metadata["index"],
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
app.layout = html.Div(card)



if __name__ == "__main__":
    app.run_server(debug=True, port=8052)