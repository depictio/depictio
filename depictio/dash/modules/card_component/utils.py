from dash import html, dcc
import dash_bootstrap_components as dbc
import numpy as np


def compute_value(data, column_name, aggregation):
    # FIXME : optimisation
    data = data.to_pandas()
    new_value = data[column_name].agg(aggregation)
    if type(new_value) is np.float64:
        new_value = round(new_value, 2)
    return new_value


def build_card_frame(index, children=None):
    if not children:
        return dbc.Card(
            dbc.CardBody(
                id={
                    "type": "card-body",
                    "index": index,
                }
            ),
            style={"width": "100%"},
            id={
                "type": "card-component",
                "index": index,
            },
        )
    else:
        return dbc.Card(
            dbc.CardBody(
                children=children,
                id={
                    "type": "card-body",
                    "index": index,
                },
            ),
            style={"width": "100%"},
            id={
                "type": "card-component",
                "index": index,
            },
        )


def build_card(**kwargs):
    # def build_card(index, title, wf_id, dc_id, dc_config, column_name, column_type, aggregation, v, build_frame=False):
    index = kwargs.get("index")
    title = kwargs.get("title", "Default Title")  # Example of default parameter
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    dc_config = kwargs.get("dc_config")
    column_name = kwargs.get("column_name")
    column_type = kwargs.get("column_type")
    aggregation = kwargs.get("aggregation")
    v = kwargs.get("value")
    build_frame = kwargs.get("build_frame", False)
    refresh = kwargs.get("refresh", False)

    if refresh:
        data = kwargs.get("df")
        v = compute_value(data, column_name, aggregation)

    try:
        v = round(float(v), 2)
    except:
        pass

    # Metadata management - Create a store component to store the metadata of the card
    store_component = dcc.Store(
        id={
            "type": "stored-metadata-component",
            "index": str(index),
        },
        data={
            "index": str(index),
            "component_type": "card",
            "title": title,
            "wf_id": wf_id,
            "dc_id": dc_id,
            "dc_config": dc_config,
            "aggregation": aggregation,
            "column_type": column_type,
            "column_name": column_name,
            "value": v,
        },
    )

    # Create the card body - default title is the aggregation value on the selected column
    if not title:
        card_title = html.H5(f"{aggregation} on {column_name}")
    else:
        card_title = html.H5(f"{title}")

    # Create the card body
    new_card_body = html.Div(
        [
            card_title,
            html.P(
                f"{v}",
                id={
                    "type": "card-value",
                    "index": str(index),
                },
            ),
            store_component,
        ],
        id={
            "type": "card",
            "index": str(index),
        },
    )
    if not build_frame:
        return new_card_body
    else:
        return build_card_frame(index=index, children=new_card_body)


# List of all the possible aggregation methods for each data type
# TODO: reference in the documentation
