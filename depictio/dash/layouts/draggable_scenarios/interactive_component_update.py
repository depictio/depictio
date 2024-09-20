import collections
import itertools
import json
import os
from pprint import pprint
from bson import ObjectId
import httpx
import numpy as np
import pandas as pd
from depictio.api.v1.configs.config import API_BASE_URL, logger
from depictio.api.v1.deltatables_utils import iterative_join, join_deltatables_dev, load_deltatable_lite
from depictio.dash.layouts.edit import enable_box_edit_mode
from depictio.dash.modules.card_component.utils import build_card, compute_value
from depictio.dash.modules.figure_component.utils import build_figure
from depictio.dash.modules.interactive_component.utils import build_interactive

from depictio.dash.modules.jbrowse_component.utils import build_jbrowse, build_jbrowse_df_mapping_dict
from depictio.dash.modules.table_component.utils import build_table
from depictio.dash.utils import analyze_structure_and_get_deepest_type


def apply_dropdowns(df, n_dict):
    # if there is a filter applied, filter the df
    if n_dict["value"] is not None:
        # if the value is a string, convert it to a list
        n_dict["value"] = list(n_dict["value"]) if isinstance(n_dict["value"], str) else n_dict["value"]
        # filter the df based on the selected values using pandas isin method
        df = df[df[n_dict["metadata"]["column_name"]].isin(n_dict["value"])]
    else:
        df = df
    return df


def apply_textinput(df, n_dict):
    # if the value is not an empty string, filter the df
    if n_dict["value"] != "":
        # filter the df based on the input value using pandas str.contains method
        df = df[
            df[n_dict["metadata"]["column_name"]].str.contains(
                n_dict["value"],
                regex=True,
                na=False,
            )
        ]
    else:
        df = df
    return df


def apply_sliders(df, n_dict):
    # if the interactive component is a RangeSlider
    if n_dict["metadata"]["interactive_component_type"] == "RangeSlider":
        # filter the df based on the selected range
        df = df[(df[n_dict["metadata"]["column_name"]] >= n_dict["value"][0]) & (df[n_dict["metadata"]["column_name"]] <= n_dict["value"][1])]
    # if the interactive component is a Slider
    elif n_dict["metadata"]["interactive_component_type"] == "Slider":
        # filter the df based on the selected value
        df = df[df[n_dict["metadata"]["column_name"]] == n_dict["value"]]
    return df


def filter_data(new_df, n_dict):
    """
    Filter the data based on the interactive component type and the selected value
    """
    pd.set_option("display.max_columns", None)
    logger.info(f"n_dict - {n_dict}")

    # Handles the case of the object type
    if n_dict["metadata"]["column_type"] == "object":
        # if the interactive component is a Select or MultiSelect
        if n_dict["metadata"]["interactive_component_type"] in ["Select", "MultiSelect", "SegmentedControl"]:
            new_df = apply_dropdowns(new_df, n_dict)
        # if the interactive component is a TextInput
        elif n_dict["metadata"]["interactive_component_type"] == "TextInput":
            new_df = apply_textinput(new_df, n_dict)

    # Handles the case of the int64 and float64 types
    elif n_dict["metadata"]["column_type"] == "int64" or n_dict["metadata"]["column_type"] == "float64":
        # if the interactive component is a RangeSlider or Slider
        if n_dict["metadata"]["interactive_component_type"] in ["RangeSlider", "Slider"]:
            new_df = apply_sliders(new_df, n_dict)
    return new_df


def get_join_tables(wf, TOKEN):
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/datacollections/get_dc_joined/{wf}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    if response.status_code == 200:
        return response.json()
    return {}


# def process_individual_df(wf_dc, interactive_components, TOKEN):
#     return load_deltatable_lite(wf_dc[0], wf_dc[1], interactive_components, TOKEN)


def process_joins(wf, wf_dc, joins, interactive_components, TOKEN):
    join_df = join_deltatables_dev(wf, joins, interactive_components, TOKEN)
    for join in joins:
        for join_id in join:
            dc_id1, dc_id2 = join_id.split("--")
            yield (wf, dc_id1), join_df
            yield (wf, dc_id2), join_df
    yield wf_dc, join_df


def group_interactive_components(interactive_components_dict):
    grouped = collections.defaultdict(list)
    for k, v in interactive_components_dict.items():
        grouped[v["metadata"]["wf_id"], v["metadata"]["dc_id"]].append(v)
    return grouped


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, item):
        if item not in self.parent:
            self.parent[item] = item
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, item1, item2):
        root1 = self.find(item1)
        root2 = self.find(item2)
        if root1 != root2:
            self.parent[root2] = root1


def update_interactive_component(stored_metadata_raw, interactive_components_dict, current_draggable_children, switch_state, TOKEN, dashboard_id):
    helpers_mapping = {
        "card": build_card,
        "figure": build_figure,
        "interactive": build_interactive,
        "table": build_table,
        "jbrowse": build_jbrowse,
    }

    children = list()

    workflow_ids = list(set([v["metadata"]["wf_id"] for k, v in interactive_components_dict.items()]))
    stored_metadata = list()

    for wf in workflow_ids:
        df_dict_processed = collections.defaultdict(dict)

        # stored_metadata = sorted(stored_metadata, key=lambda x: x["index"])
        # Filter stored_metadata based on the workflow id
        logger.info(f"wf - {wf}")
        logger.info(f"stored_metadata_raw - {stored_metadata_raw}")
        stored_metadata = [v for v in stored_metadata_raw if v["wf_id"] == wf]
        stored_metadata_interactive_components = [e for e in stored_metadata if e["component_type"] in ["interactive"]]
        logger.info(f"stored_metadata - {stored_metadata}")
        stored_metadata_table_components = [e for e in stored_metadata if e["component_type"] in ["graph", "card", "table"]]
        stored_metadata_jbrowse_components = [e for e in stored_metadata if e["component_type"] in ["jbrowse"]]

        dc_ids_all_components = list(set([v["dc_id"] for v in stored_metadata if v["component_type"] not in ["jbrowse"]]))
        logger.info(f"dc_ids_all_components - {dc_ids_all_components}")

        # Using itertools, generate all the combinations of dc_ids in order to get all the possible joins
        dc_ids_all_joins = list(itertools.combinations(dc_ids_all_components, 2))
        # Turn the list of tuples into a list of strings with -- as separator, and store it in dc_ids_all_joins in the 2 possible orders
        dc_ids_all_joins = [f"{dc_id1}--{dc_id2}" for dc_id1, dc_id2 in dc_ids_all_joins] + [f"{dc_id2}--{dc_id1}" for dc_id1, dc_id2 in dc_ids_all_joins]

        logger.info(f"dc_ids_all_joins - {dc_ids_all_joins}")

        stored_metadata_interactive_components_wf = [v for k, v in interactive_components_dict.items() if v["metadata"]["wf_id"] == wf]
        join_tables_for_wf = get_join_tables(wf, TOKEN)
        logger.info(f"join_tables_for_wf - {join_tables_for_wf}")

        # Extract the intersection between dc_ids_all_joins and join_tables_for_wf[wf].keys()
        join_tables_for_wf[wf] = {k: join_tables_for_wf[wf][k] for k in join_tables_for_wf[wf].keys() if k in dc_ids_all_joins}
        logger.info(f"join_tables_for_wf - {join_tables_for_wf}")

        # Initialize Union-Find structure
        uf = UnionFind()

        joins = []
        for interactive_component in stored_metadata_interactive_components_wf:
            wf_dc_key = (interactive_component["metadata"]["wf_id"], interactive_component["metadata"]["dc_id"])
            logger.info(f"wf_dc - {wf_dc_key}")

            # Gather joins for the current workflow data collection
            for j in join_tables_for_wf[wf_dc_key[0]].keys():
                if (wf_dc_key[1] in j) and (wf_dc_key[1] in dc_ids_all_components):
                    logger.info(f"j - {j}")
                    logger.info(f"dc_ids_all_components - {dc_ids_all_components}")
                    logger.info(f"wf_dc[1] - {wf_dc_key[1]}")
                    joins.append({j: join_tables_for_wf[wf_dc_key[0]][j]})

            # Union the related data collection IDs
            for join in joins:
                for join_id in join.keys():
                    dc_id1, dc_id2 = join_id.split("--")
                    uf.union(dc_id1, dc_id2)

        # Create groups of related data collection IDs
        groups = {}
        for dc_id in dc_ids_all_components:
            root = uf.find(dc_id)
            if root not in groups:
                groups[root] = set()
            groups[root].add(dc_id)

        # Create the joins dictionary based on these groups
        joins_dict = {}
        for root, group in groups.items():
            join_key_tuple = tuple(sorted(group))
            joins_dict[join_key_tuple] = []

        # Populate the joins dictionary
        added_joins = set()
        for join in joins:
            for join_id in join.keys():
                dc_id1, dc_id2 = join_id.split("--")
                root = uf.find(dc_id1)
                join_key_tuple = tuple(sorted(groups[root]))
                if join_id not in added_joins and f"{dc_id2}--{dc_id1}" not in added_joins:
                    joins_dict[join_key_tuple].append(join)
                    added_joins.add(join_id)

        logger.info(f"joins_dict - {joins_dict}")

        # Identify and add missing joins
        for join_key_tuple, join_list in joins_dict.items():
            dc_ids = list(join_key_tuple)
            all_possible_joins = list(itertools.combinations(dc_ids, 2))
            for dc_id1, dc_id2 in all_possible_joins:
                join_id = f"{dc_id1}--{dc_id2}"
                reverse_join_id = f"{dc_id2}--{dc_id1}"
                if join_id not in added_joins and reverse_join_id not in added_joins:
                    # Create a placeholder join based on available join details
                    if dc_id1 in join_tables_for_wf[wf] and dc_id2 in join_tables_for_wf[wf]:
                        example_join = next(iter(join_tables_for_wf[wf].values()))
                        new_join = {join_id: {"how": example_join["how"], "on_columns": example_join["on_columns"], "dc_tags": example_join["dc_tags"]}}
                        joins_dict[join_key_tuple].append(new_join)
                        added_joins.add(join_id)

        logger.info(f"Updated joins_dict - {joins_dict}")

        # for join_key_tuple, joins in joins_dict.items():
        logger.info(f"Processing joins for: {join_key_tuple}")

        # Perform the joins
        for join_key_tuple, joins in joins_dict.items():
            logger.info(f"Processing joins for: {join_key_tuple}")
            logger.info(f"joins - {joins}")
            logger.info(f"interactive_components_dict - {interactive_components_dict}")
            merged_df = iterative_join(wf, {join_key_tuple: joins}, interactive_components_dict, TOKEN)
            df_dict_processed[wf][join_key_tuple] = merged_df
        for e in stored_metadata:
            if e["component_type"] == "jbrowse":
                logger.info(f"build_jbrowse_df_mapping_dict - access_token: {TOKEN}")
                build_jbrowse_df_mapping_dict(stored_metadata, df_dict_processed[wf], access_token=TOKEN)

    # Initialize the children list with the interactive components
    # children = [
    #     child
    #     for child in current_draggable_children
    #     if any(child["props"]["id"] == f'box-{component["index"]}' for component in stored_metadata if component["component_type"] in ["interactive", "jbrowse"])
    # ]


    children = list()

    if not stored_metadata:
        return current_draggable_children


    for child, component in zip(current_draggable_children, stored_metadata):
        if component["component_type"] in ["jbrowse"]:
            children.append(child)
            # if component["component_type"] == "interactive":
            #     logger.info(f"Interactive CHILD - {child}")
            #     child["props"]["children"][1]["props"]["children"]["props"]["children"]["props"]["children"][2]["props"]["data"]["value"] = interactive_components_dict[component["index"]]["value"]
            #     logger.info(f"Interactive CHILD - {child}")


    # Add or update the non-interactive components
    for component in stored_metadata:

        if component["component_type"] not in ["jbrowse"]:
            # retrieve the key from df_dict_processed based on the wf_id and dc_id, checking which join encompasses the dc_id
            for key, df in df_dict_processed[component["wf_id"]].items():
                if component["dc_id"] in key:
                    component["df"] = df
                    break
            
            if component["component_type"] == "interactive":
                component["value"] = interactive_components_dict[component["index"]]["value"]

            # component["df"] = df_dict_processed[component["wf_id"], component["dc_id"]]
            component["build_frame"] = True
            component["refresh"] = True
            component["access_token"] = TOKEN


            child = helpers_mapping[component["component_type"]](**component)
            if component["component_type"] == "card":
                logger.info(f"Card CHILD - {child}")
            child = enable_box_edit_mode(child.to_plotly_json(), switch_state=switch_state)
            children.append(child)



        elif component["component_type"] == "jbrowse":
            component["stored_metadata_jbrowse"] = stored_metadata_jbrowse_components
            component["refresh"] = True
            component["access_token"] = TOKEN
            component["dashboard_id"] = dashboard_id


            child = helpers_mapping[component["component_type"]](**component)

            logger.info(f"JBROWSE CHILD - {child}")

            child = enable_box_edit_mode(child.to_plotly_json(), switch_state=switch_state)
            children.append(child)




    logger.info(f"Len children - {len(children)}")
    # logger.info(f"Children - {children}")
    return children