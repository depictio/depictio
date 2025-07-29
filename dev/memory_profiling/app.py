
import dash_ag_grid as dag
import polars as pl
from dash import Dash, Input, Output, callback, html, no_update

app = Dash(__name__)

# df = pd.read_csv(
#     "https://raw.githubusercontent.com/plotly/datasets/master/ag-grid/olympic-winners.csv"
# )
df = pl.read_csv(
    "https://raw.githubusercontent.com/plotly/datasets/master/ag-grid/olympic-winners.csv"
)

columnDefs = [
    # this row shows the row index, doesn't use any data from the row
    {
        "headerName": "ID",
        "maxWidth": 100,
        # it is important to have node.id here, so that when the id changes (which happens
        # when the row is loaded) then the cell is refreshed.
        "valueGetter": {"function": "params.node.id"},
        "cellRenderer": "SpinnerCellRenderer",
    },
    {"field": "athlete", "minWidth": 150},
    {"field": "country", "minWidth": 150},
    {"field": "year"},
    {"field": "sport", "minWidth": 150},
    {"field": "total"},
]

defaultColDef = {
    "flex": 1,
    "minWidth": 150,
    "sortable": False,
    "resizable": True,
}

app.layout = html.Div(
    [
        dag.AgGrid(
            id="grid",
            columnDefs=columnDefs,
            defaultColDef=defaultColDef,
            rowModelType="infinite",
            dashGridOptions={
                # The number of rows rendered outside the viewable area the grid renders.
                "rowBuffer": 0,
                # How many blocks to keep in the store. Default is no limit, so every requested block is kept.
                "maxBlocksInCache": 2,
                "cacheBlockSize": 100,
                "cacheOverflowSize": 2,
                "maxConcurrentDatasourceRequests": 2,
                "infiniteInitialRowCount": 1,
                "rowSelection": "multiple",
                "pagination": True,
                "paginationAutoPageSize": True,
            },
        ),
    ],
)


@callback(
    Output("grid", "getRowsResponse"),
    Input("grid", "getRowsRequest"),
)
def infinite_scroll(request):
    # simulate slow callback
    # time.sleep(2)

    if request is None:
        return no_update
    # partial = df.iloc[request["startRow"]: request["endRow"]]
    partial = df[request["startRow"] : request["endRow"]]
    return {"rowData": partial.to_dicts(), "rowCount": df.shape[0]}


if __name__ == "__main__":
    app.run(debug=True)
