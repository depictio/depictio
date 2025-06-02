import collections
from typing import Any

import pandas as pd

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import (
    iterative_join,
    join_deltatables_dev,
    return_joins_dict,
)
from depictio.dash.layouts.edit import enable_box_edit_mode
from depictio.dash.modules.card_component.utils import build_card
from depictio.dash.modules.figure_component.utils import build_figure
from depictio.dash.modules.interactive_component.utils import build_interactive
from depictio.dash.modules.jbrowse_component.utils import (
    build_jbrowse,
    build_jbrowse_df_mapping_dict,
)
from depictio.dash.modules.table_component.utils import build_table


def apply_dropdowns(df, n_dict):
    # if there is a filter applied, filter the df
    if n_dict["value"] is not None:
        # if the value is a string, convert it to a list
        n_dict["value"] = (
            list(n_dict["value"]) if isinstance(n_dict["value"], str) else n_dict["value"]
        )
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
        df = df[
            (df[n_dict["metadata"]["column_name"]] >= n_dict["value"][0])
            & (df[n_dict["metadata"]["column_name"]] <= n_dict["value"][1])
        ]
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
        if n_dict["metadata"]["interactive_component_type"] in [
            "Select",
            "MultiSelect",
            "SegmentedControl",
        ]:
            new_df = apply_dropdowns(new_df, n_dict)
        # if the interactive component is a TextInput
        elif n_dict["metadata"]["interactive_component_type"] == "TextInput":
            new_df = apply_textinput(new_df, n_dict)

    # Handles the case of the int64 and float64 types
    elif (
        n_dict["metadata"]["column_type"] == "int64"
        or n_dict["metadata"]["column_type"] == "float64"
    ):
        # if the interactive component is a RangeSlider or Slider
        if n_dict["metadata"]["interactive_component_type"] in [
            "RangeSlider",
            "Slider",
        ]:
            new_df = apply_sliders(new_df, n_dict)
    return new_df


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


helpers_mapping = {
    "card": build_card,
    "figure": build_figure,
    "interactive": build_interactive,
    "table": build_table,
    "jbrowse": build_jbrowse,
}


def render_raw_children(
    stored_metadata: dict[str, Any],
    # current_draggable_children: List[Dict[str, Any]],
    switch_state: bool,
    dashboard_id: str,
    TOKEN: str,
    interactive_components_dict: dict[str, Any] | None = None,
) -> tuple[list[Any], list[str]]:
    """
    Render raw children components based on stored metadata and current draggable children.

    Args:
        stored_metadata (List[Dict[str, Any]]): Metadata for each component.
        current_draggable_children (List[Dict[str, Any]]): Current state of draggable children.
        switch_state (bool): State of a toggle/switch component.
        dashboard_id (str): Identifier for the dashboard.
        TOKEN (str): Authorization token.
        stored_metadata_complete (Dict[str, Any], optional): Complete metadata. Defaults to None.
        interactive_components_dict (Dict[str, Any], optional): Dictionary of interactive components. Defaults to None.

    Returns:
        Tuple[List[Any], List[str]]: A tuple containing the list of rendered children and their indexes.
    """
    children = []
    indexes = []
    interactive_components_dict = interactive_components_dict or {}
    component = stored_metadata

    # Process 'jbrowse' components first
    # children.extend(
    #     child for child, component in zip(current_draggable_children, stored_metadata)
    #     if component.get("component_type") == "jbrowse"
    # )

    # Log the addition of 'jbrowse' children
    # logger.info(f"Added 'jbrowse' children. Total children so far: {len(children)}")

    # Process non-'jbrowse' components
    comp_type = component.get("component_type")

    logger.info(f"Processing component type: {comp_type}")

    # Update interactive components
    if comp_type == "interactive":
        component.pop("value", None)

    # Generate a unique index for the component
    # component["parent_index"] = str(component["index"])
    # component["index"] = generate_unique_index()
    component["index"] = component["index"].replace("-tmp", "")
    index = component["index"]

    # Set flags and tokens
    component.update(
        {"build_frame": True, "refresh": True, "access_token": TOKEN, "no_store": True}
    )
    logger.info(f"Component: {component}")

    # Attach relevant metadata if available
    # if stored_metadata_complete:
    #     relevant_metadata = [
    #         meta for meta in stored_metadata_complete
    #         if meta.get("wf_id") == component.get("wf_id") and meta.get("component_type") == "interactive"
    #     ]
    #     if relevant_metadata:
    #         component["dashboard_metadata"] = relevant_metadata
    #         component["interactive_components_dict"] = interactive_components_dict

    # Log specific component types
    # if comp_type == "figure":
    #     logger.info(f"Processing figure component: {component}")
    # if comp_type == "card":
    #     logger.info(f"Processing card component: {component}")

    # Build the component using the helpers_mapping
    try:
        child = helpers_mapping[comp_type](**component)
    except KeyError as e:
        logger.error(f"No helper found for component type '{comp_type}': {e}")

    # Enable edit mode on the component
    child = enable_box_edit_mode(
        child.to_plotly_json(),
        switch_state=switch_state,
        dashboard_id=dashboard_id,
        component_data=component,
        TOKEN=TOKEN,
    )

    # Append the processed child
    children.append(child)
    # logger.info(f"Child added: {child}")

    logger.info(f"Total children rendered: {len(children)}")
    logger.info(f"Child indexes: {indexes}")

    return child, index


def update_interactive_component(
    stored_metadata_raw,
    interactive_components_dict,
    current_draggable_children,
    switch_state,
    TOKEN,
    dashboard_id,
):
    children = list()

    logger.info(f"interactive_components_dict - {interactive_components_dict}")

    if not interactive_components_dict:
        for metadata in stored_metadata_raw:
            child, index = render_raw_children(metadata, switch_state, dashboard_id, TOKEN)
            children.append(child)
        return children

    workflow_ids = list(
        set([v["metadata"]["wf_id"] for k, v in interactive_components_dict.items()])
    )
    stored_metadata = list()

    for wf in workflow_ids:
        df_dict_processed = collections.defaultdict(dict)

        # stored_metadata = sorted(stored_metadata, key=lambda x: x["index"])
        # Filter stored_metadata based on the workflow id
        logger.info(f"wf - {wf}")
        logger.info(f"stored_metadata_raw - {stored_metadata_raw}")
        stored_metadata = [v for v in stored_metadata_raw if v["wf_id"] == wf]
        stored_metadata_interactive_components = [
            e for e in stored_metadata if e["component_type"] in ["interactive"]
        ]
        logger.info(f"stored_metadata - {stored_metadata}")
        # stored_metadata_table_components = [
        #     e
        #     for e in stored_metadata
        #     if e["component_type"] in ["graph", "card", "table"]
        # ]
        stored_metadata_jbrowse_components = [
            e for e in stored_metadata if e["component_type"] in ["jbrowse"]
        ]

        joins_dict = return_joins_dict(wf, stored_metadata, TOKEN)

        logger.info(f"Updated joins_dict - {joins_dict}")

        # Perform the joins
        for join_key_tuple, joins in joins_dict.items():
            logger.info(f"Processing joins for: {join_key_tuple}")
            logger.info(f"joins - {joins}")
            logger.info(f"interactive_components_dict - {interactive_components_dict}")
            logger.info(
                f"stored_metadata_interactive_components - {stored_metadata_interactive_components}"
            )
            merged_df = iterative_join(
                wf, {join_key_tuple: joins}, interactive_components_dict, TOKEN
            )
            logger.info(f"merged_df - {merged_df}")
            df_dict_processed[wf][join_key_tuple] = merged_df
        for e in stored_metadata:
            if e["component_type"] == "jbrowse":
                logger.info(f"build_jbrowse_df_mapping_dict - access_token: {TOKEN}")
                build_jbrowse_df_mapping_dict(
                    stored_metadata, df_dict_processed[wf], access_token=TOKEN
                )

    # Initialize the children list with the interactive components
    # children = [
    #     child
    #     for child in current_draggable_children
    #     if any(child["props"]["id"] == f'box-{component["index"]}' for component in stored_metadata if component["component_type"] in ["interactive", "jbrowse"])
    # ]

    children = list()

    if not stored_metadata:
        return current_draggable_children

    # for child, component in zip(current_draggable_children, stored_metadata):
    #     if component["component_type"] in ["jbrowse"]:
    #         children.append(child)
    #     elif component["component_type"] == "interactive":
    #         logger.info(f"Interactive CHILD - {child}")
    #         logger.info(f"Interactive CHILD keys - {child.keys()}")

    #         try:
    #             level1 = child["props"]
    #             logger.info(f"Level 1 props: {level1}")

    #             level2 = level1["children"][1]
    #             logger.info(f"Level 2 children[1]: {level2}")

    #             level3 = level2["props"]
    #             logger.info(f"Level 3 props: {level3}")

    #             level4 = level3["children"]["props"]
    #             logger.info(f"Level 4 children.props: {level4}")

    #             level5 = level4["children"]["props"]
    #             logger.info(f"Level 5 children.props: {level5}")

    #             level6 = level5["children"]["props"]
    #             logger.info(f"Level 6 children.props: {level6}")

    #             level7 = level6["children"][2]["props"]["data"]["value"]
    #             logger.info(f"Level 7 data.value: {level7}")

    #             # Now perform the assignment
    #             child["props"]["children"][1]["props"]["children"]["props"]["children"]["props"]["children"][2]["props"]["data"]["value"] = interactive_components_dict[component["index"]]["value"]

    #         except KeyError as e:
    #             logger.error(f"KeyError encountered: {e}")
    #             # Handle the error or re-raise with more context
    #             raise

    #         logger.info(f"Interactive CHILD after update - {child}")

    logger.info(f"df_dict_processed - {df_dict_processed}")

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

            if component["component_type"] == "figure":
                logger.info(f"GRAPH COMPONENT - {component}")

            child = helpers_mapping[component["component_type"]](**component)
            if component["component_type"] == "card":
                logger.info(f"Card CHILD - {child}")
            child = enable_box_edit_mode(
                child.to_plotly_json(),
                switch_state=switch_state,
                dashboard_id=dashboard_id,
                TOKEN=TOKEN,
            )
            children.append(child)

        elif component["component_type"] == "jbrowse":
            component["stored_metadata_jbrowse"] = stored_metadata_jbrowse_components
            component["refresh"] = True
            component["access_token"] = TOKEN
            component["dashboard_id"] = dashboard_id

            child = helpers_mapping[component["component_type"]](**component)

            logger.info(f"JBROWSE CHILD - {child}")

            child = enable_box_edit_mode(
                child.to_plotly_json(),
                switch_state=switch_state,
                dashboard_id=dashboard_id,
                TOKEN=TOKEN,
            )
            children.append(child)
        logger.info(f"ITERATIVE - len(children) - {len(children)}")

    logger.info(f"Len children - {len(children)}")
    # logger.info(f"Children - {children}")
    return children
