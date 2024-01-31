# Import necessary libraries
from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import pandas as pd
from dash_iconify import DashIconify


import dash_jbrowse



# Depictio imports
from depictio.dash.modules.jbrowse_component.utils import (
    my_assembly,
    my_tracks,
    my_location,
    # my_aggregate_text_search_adapters,
    # my_theme,
)

from depictio.dash.utils import (
    SELECTED_STYLE,
    UNSELECTED_STYLE,
    list_data_collections_for_dropdown,
    list_workflows_for_dropdown,
    get_columns_from_data_collection,
    load_deltatable,
)



my_assembly = {
    "name": "GRCh38",
    "aliases": ["hg38"],
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
    "refNameAliases": {
        "adapter": {
            "type": "RefNameAliasAdapter",
            "location": {
                "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/hg38_aliases.txt",
                "locationType": 'UriLocation',
            },
        },
    },
}

my_tracks = [
    # {
    #     "type": "FeatureTrack",
    #     "trackId": "sv_calls",
    #     "name": "SV calls",
    #     "assemblyNames": ["GRCh38"],
    #     "category": ["SV"],
    #     "adapter": {
    #         "type": "BedAdapter",
    #         "bedLocation": {
    #             "uri": 'stringent_filterTRUE.tsv',
    #             "locationType": 'UriLocation',
    #         },
    #         # "colRef": 3,
    #         "scoreColumn": "llr_to_ref"
    #     },
    # },
{
  "type": "FeatureTrack",
  "trackId": "ncbi_refseq_109_hg38",
  "name": "NCBI RefSeq analysis set (GFF3Tabix)",
  "assemblyNames": [
    "hg38"
  ],
  "category": [
    "Annotation"
  ],
  "adapter": {
    "type": "Gff3TabixAdapter",
    "gffGzLocation": {
      "locationType": "UriLocation",
      "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/ncbi_refseq/GCA_000001405.15_GRCh38_full_analysis_set.refseq_annotation.sorted.gff.gz",
      "baseUri": "https://jbrowse.org/code/jb2/v2.3.4/config.json"
    },
    "index": {
      "location": {
        "locationType": "UriLocation",
        "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/ncbi_refseq/GCA_000001405.15_GRCh38_full_analysis_set.refseq_annotation.sorted.gff.gz.tbi",
        "baseUri": "https://jbrowse.org/code/jb2/v2.3.4/config.json"
      }
    }
  },
#   "displays": [
#     {
#       "type": "LinearBasicDisplay",
#       "displayId": "ncbi_refseq_109_hg38-LinearBasicDisplay"
#     },
#     {
#       "type": "LinearArcDisplay",
#       "displayId": "ncbi_refseq_109_hg38-LinearArcDisplay"
#     }
#   ]
}
]



# TODO: try both dash-jbrowse and dash-iframe with full jbrowse instance

def design_jbrowse(id):
    row = [
        html.Div(
            # html.Div("TOTO",  id={"type": "jbrowse", "index": id["index"]}),
            html.Iframe(src="http://localhost:3000?config=http://localhost:9010/config.json", width="100%", height="1000px", id={"type": "jbrowse", "index": id["index"]}),
            # html.Iframe(src="http://localhost:5500/", width="100%", height="500px", id={"type": "jbrowse", "index": id["index"]}),
            # dash_jbrowse.LinearGenomeView(
            #     id={"type": "jbrowse", "index": id["index"]},
            #     assembly=my_assembly,
            #     tracks=my_tracks,
            #     # # defaultSession=my_default_session,
            #     location=my_location,
            #     # aggregateTextSearchAdapters=my_aggregate_text_search_adapters,
            #     # configuration=my_theme,
            # ),
            id={"type": "test-container", "index": id["index"]},
        )
    ]
    return row


def create_stepper_jbrowse_button(n):
    """
    Create the stepper interactive button

    Args:
        n (_type_): _description_

    Returns:
        _type_: _description_
    """

    button = dbc.Col(dmc.Button(
        "Genome browser",
        id={
            "type": "btn-option",
            "index": n,
            "value": "genome_browser",
        },
        n_clicks=0,
        style=UNSELECTED_STYLE,
        size="xl",
        color="yellow",
        leftIcon=DashIconify(
            icon="material-symbols:table-rows-narrow-rounded", color="white"
        ),
    ))
    store = dcc.Store(
        id={
            "type": "store-btn-option",
            "index": n,
            "value": "Genome browser",
        },
        data=0,
        storage_type="memory",
    )

    return button, store
