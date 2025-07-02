import dash
import dash_ag_grid as dag

app = dash.Dash(__name__)

app.layout = dag.AgGrid(
    id='grid',
    columnDefs=[
        {'field': 'make'},
        {'field': 'model'},
        {'field': 'price'}
    ],
    rowData=[
        {'make': 'Toyota', 'model': 'Celica', 'price': 35000},
        {'make': 'Ford', 'model': 'Mondeo', 'price': 32000},
        {'make': 'Porsche', 'model': 'Boxster', 'price': 72000}
    ],
    defaultColDef={
        'sortable': True,
        'filter': True,
        'resizable': True,
        'editable': True
    },
)

if __name__ == '__main__':
    app.run(debug=True, port=8053)