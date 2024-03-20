import collections
import numpy as np
from depictio.dash.utils import analyze_structure_and_get_deepest_type


def apply_dropdowns(df, n_dict):
    # if there is a filter applied, filter the df
    if n_dict["value"] is not None:
        # if the value is a string, convert it to a list
        n_dict["value"] = list(n_dict["value"]) if isinstance(n_dict["value"], str) else n_dict["value"]
        # filter the df based on the selected values using pandas isin method
        df = df[df[n_dict["metadata"]["column_value"]].isin(n_dict["value"])]
    else:
        df = df
    return df


def apply_textinput(df, n_dict):
    # if the value is not an empty string, filter the df
    if n_dict["value"] != "":
        # filter the df based on the input value using pandas str.contains method
        df = df[
            df[n_dict["metadata"]["column_value"]].str.contains(
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
        df = df[(df[n_dict["metadata"]["column_value"]] >= n_dict["value"][0]) & (df[n_dict["metadata"]["column_value"]] <= n_dict["value"][1])]
    # if the interactive component is a Slider
    elif n_dict["metadata"]["interactive_component_type"] == "Slider":
        # filter the df based on the selected value
        df = df[df[n_dict["metadata"]["column_value"]] == n_dict["value"]]
    return df


def filter_data(new_df, n_dict):
    """
    Filter the data based on the interactive component type and the selected value
    """

    # Handles the case of the object type
    if n_dict["metadata"]["type"] == "object":
        # if the interactive component is a Select or MultiSelect
        if n_dict["metadata"]["interactive_component_type"] in ["Select", "MultiSelect", "SegmentedControl"]:
            new_df = apply_dropdowns(new_df, n_dict)
        # if the interactive component is a TextInput
        elif n_dict["metadata"]["interactive_component_type"] == "TextInput":
            new_df = apply_textinput(new_df, n_dict)

    # Handles the case of the int64 and float64 types
    elif n_dict["metadata"]["type"] == "int64" or n_dict["metadata"]["type"] == "float64":
        # if the interactive component is a RangeSlider or Slider
        if n_dict["metadata"]["interactive_component_type"] in ["RangeSlider", "Slider"]:
            new_df = apply_sliders(new_df, n_dict)
    return new_df


def update_interactive_component(stored_metadata, interactive_components_dict, plotly_vizu_dict, join_deltatables, current_draggable_children):
    print("\n\n\n")
    print("INTERACTIVE COMPONENT")

    # Iterate over the stored metadata (all components) to retrieve the corresponding data
    # e - all components
    print(stored_metadata)
    print(interactive_components_dict)

    # Sort sorted_metadata by component type using that order: graph, card, table & exclude interactive components
    stored_metadata = sorted(stored_metadata, key=lambda x: x["component_type"])
    stored_metadata_table_components = [e for e in stored_metadata if e["component_type"] in ["graph", "card", "table-aggrid"]]
    stored_metadata_jbrowse_components = [e for e in stored_metadata if e["component_type"] in ["jbrowse"]]

    # Create a dict to store which new_df is related to jbrowse components, if dc_config["dc_specific_properties"]["regex_wildcars"]["join_data_collection"]
    jbrowse_df_mapping_dict = collections.defaultdict(dict)

    for j, e in enumerate(stored_metadata_table_components):
        print(j, e)

        # Check if the component type is not an interactive component in order to update its content
        if e["component_type"] not in ["interactive_component"]:
            # FIXME: find a more efficient way to update than loading the data again
            new_df = join_deltatables(e["wf_id"], e["dc_id"])

            # NOTE: order stored_metadata in a way that the components impacted by new_df are at the end, then find a way to give new_df/related list to that category

            print(new_df)
            # Iterate over the interactive components to filter the data (new_df)
            # n - interactive components
            for i, n in enumerate(list(interactive_components_dict.keys())):
                print(i, n)
                # Retrieve corresponding metadata
                n_dict = interactive_components_dict[n]

                # Retrieve the join data collection if it exists
                if n_dict["metadata"]["dc_config"]["join"]:
                    n_join_dc = n_dict["metadata"]["dc_config"]["join"]["with_dc_id"]
                else:
                    n_join_dc = []

                # Check if interactive component is part of the join data collection of standard component
                # check_join = [e["dc_id"] for sub_join in n_join_dc if e["dc_id"] in sub_join["with_dc"]]
                check_join = e["dc_id"] in n_join_dc

                # Check if the workflow id and the data collection id are matching
                if e["wf_id"] == n_dict["metadata"]["wf_id"]:
                    if (e["dc_id"] == n_dict["metadata"]["dc_id"]) or (check_join):
                        # if (e["dc_id"] == n_dict["metadata"]["dc_id"]) or (len(check_join) > 0):
                        ## filter based on the column and the interactive component handle if the column is categorical or numerical

                        # if the value is None or an empty list, do not filter
                        if n_dict["value"] is None or n_dict["value"] == []:
                            pass
                        else:
                            # filter the data based on the interactive component type and the selected value
                            # NOTE - iterative filtering
                            new_df = filter_data(new_df, n_dict)

                            # Check if e is part of a join with a jbrowse collection
                            for jbrowse in stored_metadata_jbrowse_components:
                                if e["dc_id"] in jbrowse["dc_config"]["join"]["with_dc_id"]:
                                    print("JBROWSE")
                                    print(e["dc_id"])
                                    print(new_df)
                                    for col in jbrowse["dc_config"]["join"]["on_columns"]:
                                        jbrowse_df_mapping_dict[jbrowse["index"]][col] = new_df[col].unique().tolist()
                        
                        print("\n")
                        print("jbrowse_df_mapping_dict")
                        print(jbrowse_df_mapping_dict)

                        # Iterate over the current draggable children to update the content of the components
                        for child in current_draggable_children:
                            # Get the deepest element type
                            (
                                max_depth,
                                deepest_element_type,
                            ) = analyze_structure_and_get_deepest_type(child)
                            print("\n")
                            print("analyze_structure_and_get_deepest_type")
                            print(max_depth, deepest_element_type)
                            print(child["props"]["id"], e["index"])

                            # If the deepest element type is a card, update the content of the card
                            if deepest_element_type == "card-value":
                                if int(child["props"]["id"]) == int(e["index"]):
                                    for k, sub_child in enumerate(
                                        child["props"]["children"][0]["props"]["children"]["props"]["children"][-1]["props"]["children"]["props"]["children"]
                                    ):
                                        if "id" in sub_child["props"]:
                                            if sub_child["props"]["id"]["type"] == "card-value":
                                                aggregation = e["aggregation"]
                                                new_value = new_df[e["column_value"]].agg(aggregation)
                                                if type(new_value) is np.float64:
                                                    new_value = round(new_value, 2)
                                                sub_child["props"]["children"] = new_value
                                                continue

                            # If the deepest element type is a graph, update the content of the graph
                            elif deepest_element_type == "graph":
                                if int(child["props"]["id"]) == int(e["index"]):
                                    for k, sub_child in enumerate(
                                        child["props"]["children"][0]["props"]["children"]["props"]["children"][-1]["props"]["children"]["props"]["children"]
                                    ):
                                        if sub_child["props"]["id"]["type"] == "graph":
                                            new_figure = plotly_vizu_dict[e["visu_type"].lower()](new_df, **e["dict_kwargs"])
                                            sub_child["props"]["figure"] = new_figure

                            # If the deepest element type is a graph, update the content of the graph
                            elif deepest_element_type == "table-aggrid":
                                if int(child["props"]["id"]) == int(e["index"]):
                                    for k, sub_child in enumerate(
                                        child["props"]["children"][0]["props"]["children"]["props"]["children"][-1]["props"]["children"]["props"]["children"]
                                    ):
                                        if sub_child["props"]["id"]["type"] == "table-aggrid":
                                            print("\ntable-aggrid")
                                            sub_child["props"]["rowData"] = new_df.to_dict("records")
                                            # new_figure = plotly_vizu_dict[e["visu_type"].lower()](new_df, **e["dict_kwargs"])
                                            # sub_child["props"]["figure"] = new_figure

                            # If the deepest element type is a graph, update the content of the graph
                            elif deepest_element_type == "iframe-jbrowse":
                                print("\nIFRAME-JBROWSE")
                                print(child["props"]["id"], e["index"])
                                if int(child["props"]["id"]) == int(e["index"]):
                                    for k, sub_child in enumerate(
                                        child["props"]["children"][0]["props"]["children"]["props"]["children"][-1]["props"]["children"]["props"]["children"]
                                    ):
                                        print("\niframe-jbrowse")
                                        print(sub_child)
                                        # if sub_child["props"]["id"]["type"] == "table-aggrid":

                                        #     print("\ntable-aggrid")
                                        #     sub_child["props"]["rowData"] = new_df.to_dict("records")
                                        #     # new_figure = plotly_vizu_dict[e["visu_type"].lower()](new_df, **e["dict_kwargs"])
                                        #     # sub_child["props"]["figure"] = new_figure

                            else:
                                pass

    return current_draggable_children
