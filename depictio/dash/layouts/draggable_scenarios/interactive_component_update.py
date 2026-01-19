import collections
from typing import Any

import httpx
import pandas as pd

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import join_deltatables_dev, load_deltatable_lite
from depictio.dash.component_metadata import get_build_functions
from depictio.dash.layouts.edit import enable_box_edit_mode
from depictio.dash.modules.jbrowse_component.utils import (
    build_jbrowse_df_mapping_dict,
)
from depictio.dash.utils import get_result_dc_for_workflow


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


def apply_boolean(df, n_dict):
    # if the interactive component is a Checkbox or Switch
    if n_dict["metadata"]["interactive_component_type"] in ["Checkbox", "Switch"]:
        # filter the df based on the boolean value
        value = n_dict["value"]
        if isinstance(value, str):
            # Convert string to boolean
            value = value.lower() in ["true", "1", "yes", "on"]
        df = df[df[n_dict["metadata"]["column_name"]] == value]
    return df


def filter_data(new_df, n_dict):
    """
    Filter the data based on the interactive component type and the selected value
    """
    pd.set_option("display.max_columns", None)
    # logger.info(f"n_dict - {n_dict}")

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

    # Handles the case of the bool type
    elif n_dict["metadata"]["column_type"] == "bool":
        # if the interactive component is a Checkbox or Switch
        if n_dict["metadata"]["interactive_component_type"] in [
            "Checkbox",
            "Switch",
        ]:
            new_df = apply_boolean(new_df, n_dict)

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
    for v in interactive_components_dict.values():
        grouped[v["metadata"]["wf_id"], v["metadata"]["dc_id"]].append(v)
    return grouped


# Get helpers mapping from centralized metadata
helpers_mapping = get_build_functions()


def render_raw_children(
    stored_metadata: dict[str, Any],
    # current_draggable_children: List[Dict[str, Any]],
    switch_state: bool,
    dashboard_id: str,
    TOKEN: str,
    interactive_components_dict: dict[str, Any] | None = None,
    theme: str = "light",  # Add theme parameter
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

    # Log code mode component processing during filters
    if component.get("component_type") == "figure" and component.get("mode") == "code":
        if "code_content" in component:
            logger.info(
                f"🔄 FILTER: Code mode figure with code_content (length: {len(component['code_content'])})"
            )
        else:
            logger.warning("⚠️ FILTER: Code mode figure missing code_content - component may break")

    # Process 'jbrowse' components first
    # children.extend(
    #     child for child, component in zip(current_draggable_children, stored_metadata)
    #     if component.get("component_type") == "jbrowse"
    # )

    # Log the addition of 'jbrowse' children
    # logger.info(f"Added 'jbrowse' children. Total children so far: {len(children)}")

    # Process non-'jbrowse' components
    comp_type = component.get("component_type")

    # Convert component type to lowercase for helpers mapping compatibility
    # Button values like "MultiQC" need to be converted to "multiqc" for the metadata
    comp_type_lower = comp_type.lower() if comp_type else None

    logger.info(f"Processing component type: {comp_type} (mapped to: {comp_type_lower})")

    # Update interactive components
    if comp_type == "interactive":
        component.pop("value", None)

    # Handle component index based on component type
    # Text components need special handling for temporary IDs during creation
    if comp_type == "text":
        # For text components, preserve the original index (including -tmp if present)
        # The text component will handle -tmp removal internally when appropriate
        index = component["index"]
    else:
        # For other components, remove -tmp suffix to get the final ID
        component["index"] = component["index"].replace("-tmp", "")
        index = component["index"]

    # Set flags and tokens
    component.update(
        {
            "build_frame": True,
            "refresh": True,
            "access_token": TOKEN,
            "no_store": True,
            # "stepper": True,
        }
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

    # Add theme to component if it's a figure
    component["theme"] = theme
    logger.info(f"INTERACTIVE - Using theme: {theme} for component {comp_type}")

    # Build the component using the helpers_mapping
    try:
        child = helpers_mapping[comp_type_lower](**component)
    except KeyError as e:
        logger.error(
            f"No helper found for component type '{comp_type}' (mapped to '{comp_type_lower}'): {e}"
        )
        # Return empty results if no helper is found
        return [], []
    except Exception as e:
        logger.error(
            f"Error building component of type '{comp_type}' (mapped to '{comp_type_lower}'): {e}"
        )
        # Return empty results if there's an error during build
        return [], []

    # Enable edit mode on the native component (no JSON conversion needed)
    try:
        logger.info(f"Processing {comp_type} component as native Dash component")

        # Pass the native component directly to enable_box_edit_mode
        # This preserves dcc.Loading wrappers and eliminates JSON conversion overhead
        child = enable_box_edit_mode(
            child,  # Native Dash component
            switch_state=switch_state,
            dashboard_id=dashboard_id,
            component_data=component,
            TOKEN=TOKEN,
        )
    except Exception as e:
        logger.error(f"Error processing {comp_type} component in interactive update: {e}")
        # Fallback to prevent dashboard failure
        fallback_child = {
            "type": "Div",
            "props": {
                "id": {"index": component.get("index", "unknown")},
                "children": f"Error loading {comp_type} component",
            },
        }
        child = enable_box_edit_mode(
            fallback_child,
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


def update_interactive_component_sync(
    stored_metadata_raw,
    interactive_components_dict,
    current_draggable_children,
    switch_state,
    TOKEN,
    dashboard_id,
    theme="light",  # Add theme parameter with default
):
    children = list()

    # logger.info(f"interactive_components_dict - {interactive_components_dict}")
    interactive_components_dict_for_logging = [
        {
            "index": k,
            "value": v["value"],
            "metadata": {
                sub_k: sub_v
                for sub_k, sub_v in v["metadata"].items()
                if sub_k
                in ["wf_id", "dc_id", "column_name", "column_type", "interactive_component_type"]
            },
        }
        for k, v in interactive_components_dict.items()
    ]
    logger.info(
        f"Interactive components dict for logging: {interactive_components_dict_for_logging}"
    )
    if not interactive_components_dict:
        for metadata in stored_metadata_raw:
            child, index = render_raw_children(
                metadata, switch_state, dashboard_id, TOKEN, theme=theme
            )
            children.append(child)
            logger.info(f"Metadata processed: {metadata}")
        return children

    workflow_ids = list(
        set([v["metadata"]["wf_id"] for k, v in interactive_components_dict.items()])
    )
    stored_metadata = list()

    for wf in workflow_ids:
        df_dict_processed = collections.defaultdict(dict)

        # stored_metadata = sorted(stored_metadata, key=lambda x: x["index"])
        # Filter stored_metadata based on the workflow id
        # logger.info(f"wf - {wf}")
        # logger.info(f"stored_metadata_raw - {stored_metadata_raw}")
        stored_metadata = [v for v in stored_metadata_raw if v.get("wf_id") == wf]
        # stored_metadata_interactive_components = [
        #     e for e in stored_metadata if e["component_type"] in ["interactive"]
        # ]
        # logger.info(f"stored_metadata - {stored_metadata}")
        # stored_metadata_table_components = [
        #     e
        #     for e in stored_metadata
        #     if e["component_type"] in ["graph", "card", "table"]
        # ]
        stored_metadata_jbrowse_components = [
            e for e in stored_metadata if e["component_type"] in ["jbrowse"]
        ]

        # Create dc_type mapping BEFORE calling return_joins_dict() to filter non-table types early
        # Fetch ALL data collections for this workflow to get complete type mapping
        dc_type_mapping = {}

        try:
            # Fetch workflow data to get all data collections
            logger.info(f"Fetching workflow data for wf={wf} to build dc_type_mapping")
            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/workflows/get/from_id",
                params={"workflow_id": wf},
                headers={"Authorization": f"Bearer {TOKEN}"},
                timeout=5.0,
            )
            logger.info(f"Workflow fetch response: status={response.status_code}")
            if response.status_code == 200:
                workflow_data = response.json()
                data_collections = workflow_data.get("data_collections", [])
                logger.info(f"Found {len(data_collections)} data collections in workflow {wf}")
                for dc in data_collections:
                    dc_id = str(dc.get("_id"))
                    config = dc.get("config", {})
                    dc_type = config.get("type", "table")
                    dc_type_mapping[dc_id] = dc_type
                    logger.info(f"Mapped {dc_id} -> {dc_type} (from workflow data)")
            else:
                logger.warning(
                    f"Failed to fetch workflow data: HTTP {response.status_code}, response={response.text}"
                )
        except Exception as e:
            logger.error(f"Error fetching workflow data for dc types: {e}", exc_info=True)

        # Also map from stored_metadata components for any missing dc_ids
        for component in stored_metadata:
            dc_id = component.get("dc_id") or component.get("data_collection_id")
            component_type = component.get("component_type")

            if dc_id and dc_id not in dc_type_mapping:
                # Fallback: infer from component type if not in workflow data
                if component_type in ["jbrowse", "multiqc"]:
                    dc_type_mapping[dc_id] = component_type
                    logger.debug(f"Mapped {dc_id} -> {component_type} (from component type)")
                elif component_type in ["table", "figure", "card", "interactive"]:
                    dc_type_mapping[dc_id] = "table"
                    logger.debug(f"Mapped {dc_id} -> table (from component type)")

        logger.info(f"DC type mapping (before loading pre-computed join): {dc_type_mapping}")

        # MIGRATED: Load pre-computed join result DC
        result_dc_id = get_result_dc_for_workflow(wf, TOKEN)

        if result_dc_id:
            logger.info(f"Loading pre-computed join for workflow {wf}: {result_dc_id}")

            # Convert interactive_components_dict to metadata list for filtering
            metadata_list = (
                list(interactive_components_dict.values()) if interactive_components_dict else []
            )

            # Load pre-computed result DC with interactive filters
            from bson import ObjectId

            merged_df = load_deltatable_lite(
                ObjectId(wf), ObjectId(result_dc_id), metadata=metadata_list, TOKEN=TOKEN
            )

            logger.info(f"Loaded pre-computed join for workflow {wf} (shape: {merged_df.shape})")

            # Store the merged dataframe
            # For compatibility, store it with a simple key
            df_dict_processed[wf]["precomputed_join"] = merged_df
            logger.debug(f"Stored pre-computed join df (shape: {merged_df.shape})")
        else:
            logger.info(f"No pre-computed joins for workflow {wf}")

        for e in stored_metadata:
            if e["component_type"] == "jbrowse":
                # logger.info(f"build_jbrowse_df_mapping_dict - access_token: {TOKEN}")
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

    # logger.info(f"df_dict_processed - {df_dict_processed}")

    # Add or update the non-interactive components
    for component in stored_metadata:
        logger.info(f"DEBUG - interactive_component_update - Processing component: {component}")

        if component["component_type"] not in ["jbrowse", "multiqc"]:
            # retrieve the key from df_dict_processed based on the wf_id and dc_id, checking which join encompasses the dc_id
            for key, df in df_dict_processed[component["wf_id"]].items():
                if component["dc_id"] in key:
                    component["df"] = df
                    break

            if component["component_type"] == "interactive":
                # Preserve existing value if interactive_components_dict doesn't have it
                if component["index"] in interactive_components_dict:
                    component["value"] = interactive_components_dict[component["index"]]["value"]
                    logger.debug(
                        f"Restored value for component {component['index']}: {component['value']}"
                    )
                else:
                    logger.warning(
                        f"Component {component['index']} not found in interactive_components_dict, preserving existing value: {component.get('value', 'None')}"
                    )

            # Set component parameters to use pre-loaded data
            component["build_frame"] = True
            component["refresh"] = False
            component["access_token"] = TOKEN

            # Add theme to component if it's a figure
            # if component["component_type"] == "figure":
            component["theme"] = theme
            # logger.info(f"GRAPH COMPONENT - {component}")

            # Debug: Log component data for text components before calling helper
            if component["component_type"] == "text":
                logger.info(f"DEBUG - Calling build_text with component data: {component}")

            # Convert component type to lowercase for helpers mapping compatibility
            component_type_lower = component["component_type"].lower()
            child = helpers_mapping[component_type_lower](**component)

            # Debug: Log component type for verification
            if component["component_type"] == "figure":
                logger.info(f"Figure component child type: {type(child)}")
                # Check if Loading component is preserved (native component check)
                if hasattr(child, "type") and child.type == "Loading":
                    logger.info(
                        "✅ Loading component preserved in figure during interactive update"
                    )
                elif hasattr(child, "__class__") and "Loading" in str(child.__class__):
                    logger.info(
                        "✅ Loading component preserved in figure during interactive update"
                    )
                else:
                    logger.info(
                        f"ℹ️ Figure component type: {getattr(child, 'type', 'Unknown')} (may still have loading)"
                    )
            # Debug: Log card component info if needed
            # if component["component_type"] == "card":
            #     logger.debug(f"Card component type: {type(child)}")

            # Process component as native Dash component (no JSON conversion)
            # try:
            logger.info(
                f"DEBUG update_interacteive - {component['component_type']} component as native Dash component"
            )

            # Pass the native component directly - preserves Loading wrappers and improves performance
            child = enable_box_edit_mode(
                child,  # Native Dash component
                switch_state=switch_state,
                dashboard_id=dashboard_id,
                TOKEN=TOKEN,
            )

            if component["component_type"] == "text":
                logger.info(f"DEBUG text component {child.id} with content: {child}")

            # except Exception as e:
            #     logger.error(
            #         f"Error processing {component['component_type']} component (line 460 path): {e}"
            #     )
            #     # Fallback to prevent dashboard failure
            #     fallback_child = {
            #         "type": "Div",
            #         "props": {
            #             "id": {"index": component.get("index", "unknown")},
            #             "children": f"Error loading {component['component_type']} component",
            #         },
            #     }
            #     child = enable_box_edit_mode(
            #         fallback_child,
            #         switch_state=switch_state,
            #         dashboard_id=dashboard_id,
            #         TOKEN=TOKEN,
            #     )
            children.append(child)

        elif component["component_type"] == "jbrowse":
            component["stored_metadata_jbrowse"] = stored_metadata_jbrowse_components
            component["refresh"] = True
            component["access_token"] = TOKEN
            component["dashboard_id"] = dashboard_id

            # Add theme to component if it's a figure (though jbrowse shouldn't need it)
            if component["component_type"] == "figure":
                component["theme"] = theme

            # Convert component type to lowercase for helpers mapping compatibility
            component_type_lower = component["component_type"].lower()
            child = helpers_mapping[component_type_lower](**component)

            logger.debug(f"JBROWSE CHILD - {child}")

            # Process jbrowse component as native Dash component
            child = enable_box_edit_mode(
                child,  # Native Dash component (no JSON conversion needed)
                switch_state=switch_state,
                dashboard_id=dashboard_id,
                TOKEN=TOKEN,
            )

            children.append(child)

        elif component["component_type"] == "multiqc":
            # Handle MultiQC components specially - they don't use data joins
            # The dedicated patch_multiqc_plot_with_interactive_filtering callback
            # will update the figure property separately, so we keep the component
            # structure intact here
            component["index"] = component["index"].replace("-tmp", "")

            # Set component parameters
            component["refresh"] = True
            component["access_token"] = TOKEN
            component["theme"] = theme

            # Convert component type to lowercase for helpers mapping compatibility
            component_type_lower = component["component_type"].lower()
            child = helpers_mapping[component_type_lower](**component)

            logger.debug(f"MULTIQC CHILD (no data filtering applied here) - {child}")

            # Process multiqc component as native Dash component
            child = enable_box_edit_mode(
                child,  # Native Dash component (no JSON conversion needed)
                switch_state=switch_state,
                dashboard_id=dashboard_id,
                TOKEN=TOKEN,
            )

            children.append(child)
        # logger.info(f"ITERATIVE - len(children) - {len(children)}")

    # logger.info(f"Len children - {len(children)}")
    # logger.info(f"Children - {children}")
    return children
