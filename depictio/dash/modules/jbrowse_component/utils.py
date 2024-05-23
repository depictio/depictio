import collections
import json
import os
import httpx
from depictio.api.v1.configs.config import API_BASE_URL, TOKEN, logger
from dash import html, dcc
import dash_bootstrap_components as dbc


def build_jbrowse_df_mapping_dict(stored_metadata, df_dict_processed):
    jbrowse_df_mapping_dict = collections.defaultdict(dict)

    stored_metadata_jbrowse_components = [e for e in stored_metadata if e["component_type"] == "jbrowse"]

    logger.info(f"{API_BASE_URL}")
    for e in stored_metadata:
        if e["component_type"] != "jbrowse":
            logger.info(f"df_dict_processed keys {df_dict_processed.keys()}")
            # find df in df_dict_processed key (join) where e["dc_id"] is in the join["with_dc_id"]
            new_df = [df_dict_processed[key] for key in df_dict_processed if e["dc_id"] in "--".join(key)][0]
            logger.info(f"new_df {new_df}")
            for jbrowse in stored_metadata_jbrowse_components:
                if e["dc_id"] in jbrowse["dc_config"]["join"]["with_dc_id"]:
                    for col in jbrowse["dc_config"]["join"]["on_columns"]:
                        logger.info(f"col {col}")
                        jbrowse_df_mapping_dict[int(jbrowse["index"])][col] = list(new_df[col].unique())
    # save to a json file
    os.makedirs("data", exist_ok=True)
    json.dump(jbrowse_df_mapping_dict, open("data/jbrowse_df_mapping_dict.json", "w"), indent=4)
    httpx.post(f"{API_BASE_URL}/depictio/api/v1/jbrowse/dynamic_mapping_dict", json=jbrowse_df_mapping_dict)


def build_jbrowse_frame(index, children=None):
    if not children:
        return dbc.Card(
            dbc.CardBody(
                id={
                    "type": "jbrowse-body",
                    "index": index,
                }
            ),
            style={"width": "100%"},
            id={
                "type": "jbrowse-component",
                "index": index,
            },
        )
    else:
        return dbc.Card(
            dbc.CardBody(
                children=children,
                id={
                    "type": "jbrowse-body",
                    "index": index,
                },
            ),
            style={"width": "100%"},
            id={
                "type": "jbrowse-component",
                "index": index,
            },
        )


def build_jbrowse(**kwargs):
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    dc_config = kwargs.get("dc_config")
    refresh = kwargs.get("refresh", False)
    stored_metadata_jbrowse = kwargs.get("stored_metadata_jbrowse", {})
    index = kwargs.get("index")
    build_frame = kwargs.get("build_frame", False)

    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user",
        headers={
            "Authorization": f"Bearer {TOKEN}",
        },
    )

    if response.status_code != 200:
        raise Exception("Error fetching user")

    elif response.status_code == 200:
        # Session to define based on User ID & Dashboard ID
        # TODO: define dashboard ID

        user_id = response.json()["user_id"]
        dashboard_id = "1"
        session = f"{user_id}_{dashboard_id}.json"

    if refresh is False:
        updated_jbrowse_config = "loc=chr1:1-248956422&assembly=hg38"
        # updated_jbrowse_config = f'assembly={dc_config["assembly"]}&loc={dc_config["loc"]}'
        url = f"http://localhost:3000?config=http://localhost:9010/sessions/{session}&{updated_jbrowse_config}"

    elif refresh is True:
        jbrowse_df_mapping_dict = json.load(open("data/jbrowse_df_mapping_dict.json", "r"))
        logger.info(f"jbrowse_mappind_dict OK {jbrowse_df_mapping_dict.keys()}")

        last_jbrowse_status = httpx.get(f"{API_BASE_URL}/depictio/api/v1/jbrowse/last_status")
        last_jbrowse_status = last_jbrowse_status.json()
        print("last_jbrowse_status", last_jbrowse_status)

        # Cross jbrowse_df_mapping_dict and mapping_dict to update the jbrowse iframe
        track_ids = list()
        for e in stored_metadata_jbrowse:
            mapping_dict = httpx.get(f"{API_BASE_URL}/depictio/api/v1/jbrowse/map_tracks_using_wildcards/{e['wf_id']}/{e['dc_id']}")
            mapping_dict = mapping_dict.json()
            for col in e["dc_config"]["join"]["on_columns"]:
                for elem in jbrowse_df_mapping_dict[str(e["index"])][col]:
                    if elem in mapping_dict[e["dc_id"]][col]:
                        track_ids.append(mapping_dict[e["dc_id"]][col][elem])

        if len(track_ids) > 50:
            track_ids = track_ids[:50]
        # print("track_ids", track_ids)

        updated_jbrowse_config = f'assembly={last_jbrowse_status["assembly"]}&loc={last_jbrowse_status["loc"]}'
        if track_ids:
            updated_jbrowse_config += f'&tracks={",".join(track_ids)}'
        session = session.split(".")[0] + "_lite.json"
        url = f"http://localhost:3000?config=http://localhost:9010/sessions/{session}&{updated_jbrowse_config}"

    iframe = html.Iframe(
        src=f"{url}",
        width="100%",
        height="1000px",
        style={
            "transform": "scale(0.8)",
            "transform-origin": "0 0",  # Adjust as needed to change the scaling origin
            "width": "125%",  # Increase width to compensate for the scale down
        },
        id={"type": "iframe-jbrowse", "index": index},
    )
    store_component = dcc.Store(
        id={"type": "stored-metadata-component", "index": index},
        data={
            "component_type": "jbrowse",
            "current_url": f"{url}",
            "index": index,
            "wf_id": wf_id,
            "dc_id": dc_id,
            "dc_config": dc_config,
        },
    )

    jbrowse_body = html.Div([store_component, iframe], id={"type": "jbrowse", "index": index})
    if not build_frame:
        return jbrowse_body
    else:
        return build_jbrowse_frame(index=index, children=jbrowse_body)


# print(sub_child["props"]["id"]["type"])


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

# my_aggregate_text_search_adapters = [
#     {
#         "type": "TrixTextSearchAdapter",
#         "textSearchAdapterId": "hg38-index",
#         "ixFilePath": {
#             "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/trix/hg38.ix"
#         },
#         "ixxFilePath": {
#             "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/trix/hg38.ixx"
#         },
#         "metaFilePath": {
#             "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/trix/meta.json"
#         },
#         "assemblyNames": ["GRCh38"],
#     }
# ]
my_location = "17:79900000..80000000"


# # my_location = {"refName": "10", "start": 1, "end": 800}

# my_theme = {
#     "theme": {
#         "palette": {
#             "primary": {
#                 "main": "#311b92",
#             },
#             "secondary": {
#                 "main": "#0097a7",
#             },
#             "tertiary": {
#                 "main": "#f57c00",
#             },
#             "quaternary": {
#                 "main": "#d50000",
#             },
#             "bases": {
#                 "A": {"main": "#98FB98"},
#                 "C": {"main": "#87CEEB"},
#                 "G": {"main": "#DAA520"},
#                 "T": {"main": "#DC143C"},
#             },
#         },
#     },
# }

# my_tracks = [
#     {
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
#         } for e, r in zip(["BM510x04_PE20301"], ["Run_X"])
# ]

my_tracks = [
    {
        "type": "FeatureTrack",
        "trackId": "ncbi_refseq_109_hg38",
        "name": "NCBI RefSeq (GFF3Tabix)",
        "assemblyNames": ["GRCh38"],
        "category": ["Annotation"],
        "adapter": {
            "type": "Gff3TabixAdapter",
            "gffGzLocation": {"uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/ncbi_refseq/GCA_000001405.15_GRCh38_full_analysis_set.refseq_annotation.sorted.gff.gz"},
            "index": {
                "location": {"uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/ncbi_refseq/GCA_000001405.15_GRCh38_full_analysis_set.refseq_annotation.sorted.gff.gz.tbi"}
            },
        },
    }
]


# app.layout =
