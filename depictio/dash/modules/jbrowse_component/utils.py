import collections
import json
import os

import dash_bootstrap_components as dbc
import httpx

from dash import dcc, html
from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_fetch_user_from_token


def build_jbrowse_df_mapping_dict(stored_metadata, df_dict_processed, access_token):
    jbrowse_df_mapping_dict = collections.defaultdict(dict)

    stored_metadata_jbrowse_components = [
        e for e in stored_metadata if e["component_type"] == "jbrowse"
    ]
    logger.info(f"stored_metadata_jbrowse_components - {stored_metadata_jbrowse_components}")

    logger.info(f"{API_BASE_URL}")
    for e in stored_metadata:
        if e["component_type"] != "jbrowse":
            logger.info(f"df_dict_processed keys {df_dict_processed.keys()}")
            # find df in df_dict_processed key (join) where e["dc_id"] is in the join["with_dc_id"]
            new_df = [
                df_dict_processed[key] for key in df_dict_processed if e["dc_id"] in "--".join(key)
            ][0]
            logger.info(f"new_df {new_df}")
            for jbrowse in stored_metadata_jbrowse_components:
                if e["dc_id"] in jbrowse["dc_config"]["join"]["with_dc_id"]:
                    for col in jbrowse["dc_config"]["join"]["on_columns"]:
                        logger.info(f"col {col}")
                        jbrowse_df_mapping_dict[str(jbrowse["index"])][col] = list(
                            new_df[col].unique()
                        )
    # save to a json file
    logger.info(f"jbrowse_df_mapping_dict - {jbrowse_df_mapping_dict}")
    os.makedirs("data", exist_ok=True)
    json.dump(
        jbrowse_df_mapping_dict,
        open("data/jbrowse_df_mapping_dict.json", "w"),
        indent=4,
    )
    httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/jbrowse/dynamic_mapping_dict",
        json=jbrowse_df_mapping_dict,
        headers={"Authorization": f"Bearer {access_token}"},
    )


def build_jbrowse_frame(index, children=None):
    if not children:
        return dbc.Card(
            dbc.CardBody(
                id={
                    "type": "jbrowse-body",
                    "index": index,
                }
            ),
            style={
                "width": "100%",
                "border": "1px solid var(--app-border-color, #ddd)",  # Always show border for draggable delimitation
            },
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
            style={
                "width": "100%",
                "border": "1px solid var(--app-border-color, #ddd)",  # Always show border for draggable delimitation
            },
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
    stepper = kwargs.get("stepper", False)
    access_token = kwargs.get("access_token")
    dashboard_id = kwargs.get("dashboard_id")
    user_cache = kwargs.get("user_cache")

    # logger.info(f"build_jbrowse access_token {access_token}")
    logger.info(f"build_jbrowse dc_config {dc_config}")
    logger.info(f"build_jbrowse stored_metadata_jbrowse {stored_metadata_jbrowse}")
    logger.info(f"build_jbrowse index {index}")
    logger.info(f"build_jbrowse refresh {refresh}")
    logger.info(f"build_jbrowse wf_id {wf_id}")
    logger.info(f"build_jbrowse dc_id {dc_id}")
    logger.info(f"build_jbrowse dashboard_id {dashboard_id}")
    logger.info(f"build_jbrowse build_frame {build_frame}")

    # Use consolidated user cache instead of individual API call
    from depictio.models.models.users import UserContext

    user_context = UserContext.from_cache(user_cache)
    if user_context:
        logger.info("✅ JBrowse: Using consolidated cache for user data")
        user = user_context  # Use UserContext directly
    else:
        # Fallback to direct API call if cache not available
        logger.info("🔄 JBrowse: Using fallback API call for user data")
        user = api_call_fetch_user_from_token(access_token)
        logger.info(f"user {user}")

    # response = httpx.get(
    #     f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_token",
    #     headers={
    #         "Authorization": f"Bearer {access_token}",
    #     },
    # )

    # if response.status_code != 200:
    #     raise Exception("Error fetching user")

    # elif response.status_code == 200:
    # Session to define based on User ID & Dashboard ID
    # TODO: define dashboard ID

    user_id = user.id
    session = f"{user_id}_{dc_id}_lite.json"

    if refresh is False:
        updated_jbrowse_config = "loc=chr1:1-248956422&assembly=hg38"
        # updated_jbrowse_config = f'assembly={dc_config["assembly"]}&loc={dc_config["loc"]}'
        url = f"http://localhost:3000?config=http://localhost:9010/sessions/{session}&{updated_jbrowse_config}"

    elif refresh is True:
        jbrowse_df_mapping_dict = json.load(open("data/jbrowse_df_mapping_dict.json"))
        logger.info(f"jbrowse_mappind_dict OK {jbrowse_df_mapping_dict.keys()}")
        logger.info(f"jbrowse_mappind_dict values - {list(jbrowse_df_mapping_dict.values())[:10]}")

        last_jbrowse_status = httpx.get(f"{API_BASE_URL}/depictio/api/v1/jbrowse/last_status")
        last_jbrowse_status = last_jbrowse_status.json()

        # Cross jbrowse_df_mapping_dict and mapping_dict to update the jbrowse iframe
        track_ids = list()
        for e in stored_metadata_jbrowse:
            mapping_dict = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/jbrowse/map_tracks_using_wildcards/{e['wf_id']}/{e['dc_id']}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            mapping_dict = mapping_dict.json()
            logger.info(f"e {e}")
            for col in e["dc_config"]["join"]["on_columns"]:
                if str(e["index"]) in jbrowse_df_mapping_dict:
                    if col in jbrowse_df_mapping_dict[str(e["index"])]:
                        for elem in jbrowse_df_mapping_dict[str(e["index"])][col]:
                            if elem in mapping_dict[e["dc_id"]][col]:
                                track_ids.append(mapping_dict[e["dc_id"]][col][elem])

        logger.info(f"track_ids {track_ids}")

        if len(track_ids) > 100:
            track_ids = list()

        else:
            response = httpx.post(
                f"{API_BASE_URL}/depictio/api/v1/jbrowse/filter_config",
                json={
                    "tracks": track_ids,
                    "dashboard_id": dashboard_id,
                    "data_collection_id": dc_id,
                },
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                logger.error(f"Error filtering config {response.json()}")
                # pass
            else:
                logger.info(f"response {response.json()}")
                if response.json()["session"]:
                    session = response.json()["session"]

        updated_jbrowse_config = (
            f"assembly={last_jbrowse_status['assembly']}&loc={last_jbrowse_status['loc']}"
        )
        if track_ids:
            updated_jbrowse_config += f"&tracks={','.join(track_ids)}"
        logger.info(f"updated_jbrowse_config {updated_jbrowse_config}")

        # if not session.endswith("_lite.json"):
        # session = session.split(".")[0] + "_lite.json"
        url = f"http://localhost:3000?config=http://localhost:9010/sessions/{session}&{updated_jbrowse_config}"
        logger.info(f"url {url}")

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
    store_index = index.replace("-tmp", "") if index else "unknown"

    store_component = dcc.Store(
        id={"type": "stored-metadata-component", "index": store_index},
        data={
            "component_type": "jbrowse",
            "current_url": f"{url}",
            "index": store_index,
            "wf_id": wf_id,
            "dc_id": dc_id,
            "dc_config": dc_config,
        },
    )

    jbrowse_body = html.Div([store_component, iframe], id={"type": "jbrowse", "index": index})
    if not build_frame:
        return jbrowse_body
    else:
        # Build the jbrowse component with frame
        jbrowse_component = build_jbrowse_frame(index=index, children=jbrowse_body)

        # For stepper mode with loading
        if not stepper:
            # Use skeleton system for consistent loading experience
            from depictio.dash.layouts.draggable_scenarios.progressive_loading import (
                create_skeleton_component,
            )

            return dcc.Loading(
                children=jbrowse_component,
                custom_spinner=create_skeleton_component("jbrowse"),
                target_components={f'{{"index":"{index}","type":"iframe-jbrowse"}}': "src"},
                # delay_show=50,  # Minimal delay to prevent flashing
                # delay_hide=100,  # Quick dismissal
                id={"index": index},  # Move the id to the loading component
            )
        else:
            return jbrowse_component


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


# app.layout =
