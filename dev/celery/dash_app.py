import dash
from dash import html, dcc, dash_table
from dash.dependencies import Input, Output, State
import requests

app = dash.Dash(__name__)

app.layout = html.Div(
    [
        html.H1("Job Queue Dashboard"),
        html.Button("Create Job", id="create-job-button", n_clicks=0),
        dash_table.DataTable(
            id="job-history-table",
            columns=[{"name": "Job ID", "id": "job_id"}, {"name": "Status", "id": "status"}, {"name": "Result", "id": "result"}],
            data=[],
            row_selectable="single",
            selected_rows=[],
        ),
        html.Div(id="selected-job-details"),
        dcc.Interval(id="interval-component", interval=1 * 1000, n_intervals=0),
        dcc.Store(id="store-nclicks", data=0),
    ]
)


@app.callback(
    Output("job-history-table", "data"),
    Output("store-nclicks", "data"),
    [
        Input("create-job-button", "n_clicks"),
        State("store-nclicks", "data"),
        Input("interval-component", "n_intervals"),
    ],
)
def update_job_table(n_clicks, store_n_clicks, n_intervals):
    if n_clicks > store_n_clicks:
        requests.post("http://127.0.0.1:8000/create_job/")

    job_history_response = requests.get("http://127.0.0.1:8000/jobs_history/").json()
    return job_history_response, n_clicks


@app.callback(Output("selected-job-details", "children"), [Input("job-history-table", "selected_rows"), Input("job-history-table", "data")])
def display_selected_job_details(selected_rows, data):
    if selected_rows:
        selected_job = data[selected_rows[0]]
        job_status_response = requests.get(f"http://127.0.0.1:8000/job_status/{selected_job['job_id']}").json()
        return html.Div(
            [html.H3(f"Job ID: {job_status_response['job_id']}"), html.P(f"Status: {job_status_response['status']}"), html.P(f"Result: {job_status_response['result']}")]
        )
    return html.Div("Select a job to see details.")


if __name__ == "__main__":
    app.run_server(debug=True, port=8055)
