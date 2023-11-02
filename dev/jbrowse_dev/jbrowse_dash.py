import dash
import dash_jbrowse
from dash import Dash, html, dcc, Input, Output, dash_table
import dash_bootstrap_components as dbc
import sys, os
from pprint import pprint

# print(dash_jbrowse.__version__)
app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
# dash.register_page(__name__)

my_assembly = {
    "name": "GRCh38",
    "sequence": {
        "type": "ReferenceSequenceTrack",
        "trackId": "GRCh38-ReferenceSequenceTrack",
        "adapter": {
            "type": "BgzipFastaAdapter",
            "fastaLocation": {
                "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/fasta/GRCh38.fa.gz",
            },
            "faiLocation": {
                "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/fasta/GRCh38.fa.gz.fai",
            },
            "gziLocation": {
                "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/fasta/GRCh38.fa.gz.gzi",
            },
        },
    },
    "aliases": ["hg38"],
    "refNameAliases": {
        "adapter": {
            "type": "RefNameAliasAdapter",
            "location": {
                "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/hg38_aliases.txt",
            },
        },
    },
}

import os
from collections import defaultdict

# Base directory
base_dir = "assets/Counts_BW"

# Using defaultdict
runs_samples_dict = defaultdict(list)

# Loop through each directory (i.e., each Run_X, Run_Y, etc.)
for run_dir in os.listdir(base_dir):
    # Check if it's a directory
    if os.path.isdir(os.path.join(base_dir, run_dir)):
        # Get the list of all bigWig files that end with "-W.bigWig" under this directory
        samples = [
            file.replace("-W.bigWig", "")
            for file in os.listdir(os.path.join(base_dir, run_dir))
            if file.endswith("-W.bigWig")
        ]
        # Sort and store
        runs_samples_dict[run_dir] = sorted(samples)


pprint(runs_samples_dict)

# my_tracks = [
#     {
#         "type": "MultiQuantitativeTrack",
#         "trackId": "multiwiggle_{cell}-sessionTrack".format(cell=e),
#         "name": e,
#         "assemblyNames": ["GRCh38"],
#         "category": [f"{r}", f"{e}"],
#         "adapter": {
#             "type": "MultiWiggleAdapter",
#             #     "layout": [
#             #     {
#             #         "name": "Watson",
#             #         "type": "BigWigAdapter",
#             #         "bigWigLocation": {
#             #             "uri": f"http://localhost:8090/assets/Counts_BW/{e}-W.bigWig",
#             #         },
#             #         "color": "rgb(244, 164, 96)",
#             #     },
#             #     {
#             #         "name": "Crick",
#             #         "type": "BigWigAdapter",
#             #         "bigWigLocation": {
#             #             "uri": f"http://localhost:8090/assets/Counts_BW/{e}-C.bigWig",
#             #         },
#             #         "color": "rgb(102, 139, 139)",
#             #     },
#             # ],
#             "subadapters": [
#                 {
#                     "name": "Watson",
#                     "type": "BigWigAdapter",
#                     "bigWigLocation": {
#                         "uri": f"http://localhost:8090/assets/Counts_BW/{r}/{e}-W.bigWig",
#                     },
#                 },
#                 {
#                     "name": "Crick",
#                     "type": "BigWigAdapter",
#                     "bigWigLocation": {
#                         "uri": f"http://localhost:8090/assets/Counts_BW/{r}/{e}-C.bigWig",
#                     },
#                 },
#             ],
#         },
#     }
#     for r in runs_samples_dict.keys()
#     for e in sorted(runs_samples_dict[r])
# ]

my_tracks = [
    {
        "type": "FeatureTrack",
        "trackId": "ncbi_refseq_109_hg38",
        "name": "NCBI RefSeq (GFF3Tabix)",
        "assemblyNames": ["GRCh38"],
        "category": ["Annotation"],
        "height": 70,
        "adapter": {
            "type": "Gff3TabixAdapter",
            "gffGzLocation": {
                "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/ncbi_refseq/GCA_000001405.15_GRCh38_full_analysis_set.refseq_annotation.sorted.gff.gz"
            },
            "index": {
                "location": {
                    "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/ncbi_refseq/GCA_000001405.15_GRCh38_full_analysis_set.refseq_annotation.sorted.gff.gz.tbi"
                }
            },
        },
    }
]


tracks_session = []


from dash import State

@dash.callback(
    Output("dev-log", "children"),
    Input("interval-component", "n_intervals"),
    State("lgv-hg38", "defaultSession"),
)
def update_output(n, param):
    print("update_output")
    print(n)
    print(param)
    return f"{param}."




# @dash.callback(
#     Output("lgv-hg38", "defaultSession"),
#     Input("sample-dropdown-jbrowse", "value"),
# )
# def set_sample_value(value):
#     # print(value)
#     # print(df_datatable.loc[df_datatable["sample"].isin(value)].sort_values(["run", "sample"])["sample"].unique().tolist())
#     print(value)

#     tracks_session_counts = [
#         # e
#         {
#             "type": "MultiQuantitativeTrack",
#             "configuration": "multiwiggle_{cell}-sessionTrack".format(cell=e),
#             "displays": [
#                 {
#                     "id": "lTY7_5KzL5",
#                     "type": "MultiLinearWiggleDisplay",
#                     "height": 70,
#                     "selectedRendering": "",
#                     "rendererTypeNameState": "xyplot",
#                     "autoscale": "global",
#                     "displayCrossHatches": True,
#                     "layout": [
#                         {
#                             "name": "Watson",
#                             "type": "BigWigAdapter",
#                             "bigWigLocation": {
#                                 "uri": f"http://localhost:8090/assets/Counts_BW/{r}/{e}-W.bigWig",
#                             },
#                             "color": "rgb(244, 164, 96)",
#                         },
#                         {
#                             "name": "Crick",
#                             "type": "BigWigAdapter",
#                             "bigWigLocation": {
#                                 "uri": f"http://localhost:8090/assets/Counts_BW/{r}/{e}-C.bigWig",
#                             },
#                             "color": "rgb(102, 139, 139)",
#                         },
#                     ],
#                 },
#             ],
#         }
#         for r in runs_samples_dict.keys()
#         for e in sorted(runs_samples_dict[r])
#         if value and e in value
#     ]
#     print("tracks_session_counts")
#     print(tracks_session_counts)

#     my_default_session = {
#         "name": "My session",
#         "view": {
#             "id": "linearGenomeView",
#             "type": "LinearGenomeView",
#             "tracks": tracks_session_counts,
#         },
#     }

#     return my_default_session


# tracks_session_svs = [
#     {
#         "type": "FeatureTrack",
#         "configuration": "test_sv.bed-sessionTrack",
#         "displays": [
#             {
#                 "displayId": "test_sv.bed-sessionTrack-LinearBasicDisplay",
#                 "type": "LinearBasicDisplay",
#                 "height": 30,
#                 "trackShowDescriptions": False,
#                 "trackDisplayMode": "collapse",
#                 "renderer": {
#                     "type": "SvgFeatureRenderer",
#                     "color1": "black",
#                 },
#             },
#         ],
#     },
# ]

# tracks_session += tracks_session_counts
# tracks_session += tracks_session_svs
# print(tracks_session)


my_aggregate_text_search_adapters = [
    {
        "type": "TrixTextSearchAdapter",
        "textSearchAdapterId": "hg38-index",
        "ixFilePath": {
            "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/trix/hg38.ix"
        },
        "ixxFilePath": {
            "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/trix/hg38.ixx"
        },
        "metaFilePath": {
            "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/trix/meta.json"
        },
        "assemblyNames": ["GRCh38"],
    }
]
my_location = "17:79900000..80000000"
# my_location = {"refName": "10", "start": 1, "end": 800}

my_theme = {
    "theme": {
        "palette": {
            "primary": {
                "main": "#311b92",
            },
            "secondary": {
                "main": "#0097a7",
            },
            "tertiary": {
                "main": "#f57c00",
            },
            "quaternary": {
                "main": "#d50000",
            },
            "bases": {
                "A": {"main": "#98FB98"},
                "C": {"main": "#87CEEB"},
                "G": {"main": "#DAA520"},
                "T": {"main": "#DC143C"},
            },
        },
    },
}

# @app.callback(
#     Output("sample-dropdown-jbrowse", "options"),
#     Output("sample-dropdown-jbrowse", "value"),
#     Input("run-dropdown-jbrowse", "value"),
# )
# def update_sample_dropdown(selected_runs):
#     if selected_runs:
#         # Since multi=True, selected_runs will be a list of runs. We gather all samples from all selected runs.
#         samples = []
#         for run in selected_runs:
#             samples.extend(runs_samples_dict.get(run, []))

#         # Deduplicate the samples list
#         samples = list(set(samples))

#         return [{"label": sample, "value": sample} for sample in samples], samples
#     else:
#         return [], []


my_default_session = {
    "name": "My session",
    "view": {
        "id": "linearGenomeView",
        "type": "LinearGenomeView",
        # "tracks": my_tracks,
    },
}


# app.layout = html.Div(
app.layout = dbc.Container(
    [
        html.H2(
            "JBrowse2 genome viewer", style={"margin-top": 5}, className="display-4"
        ),
        html.Hr(),
        # dbc.Row(
        #     [
        #         dbc.Col(
        #             [
        #                 html.H2("Run selection:", className="card-title"),
        #                 dcc.Dropdown(
        #                     # sorted(df_datatable["sample"].unique().tolist()),
        #                     # value=sorted(runs_samples_dict.values)[0],
        #                     options=[
        #                         {"label": run, "value": run}
        #                         for run in sorted(runs_samples_dict.keys())
        #                     ],
        #                     id="run-dropdown-jbrowse",
        #                     style={"fontSize": 18, "font-family": "sans-serif"},
        #                     multi=True,
        #                 ),
        #             ]
        #         ),
        #         dbc.Col(
        #             [
        #                 html.H2("Sample selection:", className="card-title"),
        #                 dcc.Dropdown(
        #                     # sorted(df_datatable["sample"].unique().tolist()),
        #                     # value=sorted(listdir_counts)[0],
        #                     # options=list(runs_samples_dict.keys()),
        #                     id="sample-dropdown-jbrowse",
        #                     style={"fontSize": 18, "font-family": "sans-serif"},
        #                     multi=True,
        #                 ),
        #             ]
        #         ),
        #     ]
        # ),
        html.Br(),
        # html.Div(id="dd-output-container"),
        html.Div(
            [
                dash_jbrowse.LinearGenomeView(
                    id="lgv-hg38",
                    assembly=my_assembly,
                    tracks=my_tracks,
                    defaultSession=my_default_session,
                    location=my_location,
                    aggregateTextSearchAdapters=my_aggregate_text_search_adapters,
                    configuration=my_theme,
                ),
            ],
            id="test",
        ),
        dcc.Interval("interval-component", interval=2000, n_intervals=0),
        html.Div(id="dev-log"),
    ]
)


if __name__ == "__main__":
    app.run_server(port=5500, host="localhost", debug=True)
