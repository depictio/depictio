from dash import Dash, html
import dash_dangerously_set_inner_html
import pandas as pd
import pygwalker as pyg

app = Dash(__name__)
df = pd.read_csv(
    "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv"
    # "https://raw.githubusercontent.com/plotly/datasets/master/titanic.csv"
)
print(df)
walker = pyg.walk(df, return_html=True, hideDataSourceConfig=False)
print(walker.replace('height="100px"', 'height="1000px"')[:1000])

app.layout = html.Div(
    children=[
        dash_dangerously_set_inner_html.DangerouslySetInnerHTML(
            walker.replace('height="100px"', 'height="1000px"')
        )
    ],
    style={"maxHeight": "40000px", "overflow": "visible"},
)

if __name__ == "__main__":
    app.run_server(debug=True, port=9050)
