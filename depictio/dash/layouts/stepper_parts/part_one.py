"""
Stepper Part One: Component type and data source selection.

This module implements the first step of the component creation stepper workflow,
where users select:
1. The type of component to create (Figure, Card, Table, Interactive, Text, etc.)
2. The data source (workflow and data collection)

The step displays:
- Component type selection buttons with icons and descriptions
- Workflow and data collection dropdowns
- Data collection information panel showing metadata, shape, and type

Callbacks:
    - update_component_selected_display: Updates the component type badge for Text
      components (which don't require data selection)
    - update_step_1: Main callback that handles workflow/data collection selection
      and displays the data collection information panel

The module supports:
    - Regular data collections (table, JBrowse, MultiQC)
    - Joined data collections (synthetic specs for joined tables)
    - Shape information display (rows and columns count)
"""

import dash
import dash_mantine_components as dmc
import httpx
from dash import ALL, MATCH, Input, Output, State, ctx, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.component_metadata import (
    get_component_color,
    get_component_metadata_by_display_name,
)


def register_callbacks_stepper_part_one(app: dash.Dash) -> None:
    """
    Register callbacks for stepper part one (component type and data selection).

    Registers:
    - update_component_selected_display: Badge update for Text components
    - update_step_1: Main workflow/data collection selection handler

    Args:
        app: The Dash application instance.
    """

    @app.callback(
        Output({"type": "component-selected", "index": MATCH}, "children", allow_duplicate=True),
        Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        State({"type": "last-button", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def update_component_selected_display(n_clicks, component_selected):
        """
        Update component-selected badge for components that don't need data selection.

        Text components can be created without selecting a data source, so their
        badge is displayed immediately upon selection.
        """
        if ctx.triggered_id and isinstance(ctx.triggered_id, dict):
            if ctx.triggered_id["type"] == "btn-option":
                selected_component = ctx.triggered_id["value"]
                if selected_component == "Text":
                    # For Text components, show selection immediately since no data selection is needed
                    component_metadata = get_component_metadata_by_display_name(selected_component)
                    hex_color = get_component_color("text")  # Get hex color from colors.py
                    return dmc.Badge(
                        selected_component,
                        size="xl",
                        radius="xl",
                        variant="outline",
                        style={"fontFamily": "Virgil", "fontSize": "16px"},
                        color=component_metadata["color"],
                        leftSection=DashIconify(
                            icon=component_metadata["icon"],
                            width=15,
                            color=hex_color,
                        ),
                    )
        return dash.no_update

    @app.callback(
        Output({"type": "dropdown-output", "index": MATCH}, "children"),
        Output({"type": "component-selected", "index": MATCH}, "children"),
        # Output({"type": "component-selected", "index": MATCH}, "color"),
        Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
        Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        State({"type": "last-button", "index": MATCH}, "data"),
        State({"type": "workflow-selection-label", "index": MATCH}, "id"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def update_step_1(
        workflow_id,
        data_collection_id,
        input_btn_values,
        component_selected,
        id,
        local_store,
    ):
        """
        Handle step 1 interactions: workflow/data collection selection and component type.

        Fetches data collection specifications and displays an information panel
        with metadata including type, description, rows, and columns count.
        Supports both regular and joined data collections.

        Returns:
            Tuple of (layout component, component badge).
        """
        if not local_store:
            raise dash.exceptions.PreventUpdate

        # Guard: require both workflow and data collection to be selected
        if not workflow_id or not data_collection_id:
            raise dash.exceptions.PreventUpdate

        TOKEN = local_store["access_token"]

        # Determine current component selection from trigger
        if (isinstance(ctx.triggered_id, dict)) and (ctx.triggered_id["type"] == "btn-option"):
            component_selected = ctx.triggered_id["value"]

        # Component metadata is now handled by centralized functions

        # Determine the index of the most recently modified (clicked) button
        # latest_index = store_btn_ts.index(max(store_btn_ts))
        # component_selected = components_list[latest_index]

        # workflow_id, data_collection_id = return_mongoid(
        #     workflow_tag=workflow_selection,
        #     data_collection_tag=data_collection_selection,
        #     TOKEN=TOKEN,
        # )
        # workflows = list_workflows(TOKEN)

        # workflow_id = [e for e in workflows if e["workflow_tag"] == workflow_selection][0]["_id"]
        # data_collection_id = [f for e in workflows if e["_id"] == workflow_id for f in e["data_collections"] if f["data_collection_tag"] == data_collection_selection][0]["_id"]

        # print(data_collection_selection)

        # Handle both regular and joined data collection IDs
        if isinstance(data_collection_id, str) and "--" in data_collection_id:
            # Handle joined data collection - create synthetic specs
            dc_ids = data_collection_id.split("--")
            try:
                # Get individual DC specs for display
                dc1_specs = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{dc_ids[0]}",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                ).json()
                dc2_specs = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{dc_ids[1]}",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                ).json()

                # Create synthetic specs for joined DC
                dc_specs = {
                    "config": {
                        "type": "table",  # Joined DCs are always table type
                        "metatype": "joined",  # Custom metatype for joined DCs
                    },
                    "data_collection_tag": f"Joined: {dc1_specs['data_collection_tag']} + {dc2_specs['data_collection_tag']}",
                    "description": f"Joined data collection combining {dc1_specs['data_collection_tag']} and {dc2_specs['data_collection_tag']}",
                    "_id": data_collection_id,
                }
            except Exception as e:
                logger.error(f"Error fetching specs for joined DC: {e}")
                # Fallback specs
                dc_specs = {
                    "config": {"type": "table", "metatype": "joined"},
                    "data_collection_tag": f"Joined: {data_collection_id}",
                    "description": "Joined data collection",
                    "_id": data_collection_id,
                }
        else:
            # Regular data collection
            dc_specs = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{data_collection_id}",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                },
            ).json()

        # Fetch shape information (rows and columns count)
        try:
            shape_response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/deltatables/shape/{data_collection_id}",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                },
            )
            if shape_response.status_code == 200:
                shape_info = shape_response.json()
                num_rows = shape_info.get("num_rows", "N/A")
                num_columns = shape_info.get("num_columns", "N/A")
            else:
                num_rows = "N/A"
                num_columns = "N/A"
        except Exception as e:
            logger.warning(f"Failed to fetch shape information: {e}")
            num_rows = "N/A"
            num_columns = "N/A"

        if workflow_id is not None and data_collection_id is not None:
            # component_selected = html.Div(f"{component_selected}")

            # config_title = dmc.Title(
            #     "Data collection config", order=3, align="left", fw="normal"
            # )
            # json_formatted = yaml.dump(dc_specs["config"], indent=2)
            # prism = dbc.Col(
            #     [
            #         dmc.AccordionPanel(
            #             dmc.Prism(
            #                 f"""{json_formatted}""",
            #                 language="yaml",
            #                 colorScheme="light",
            #                 noCopy=True,
            #             )
            #         ),
            #     ],
            #     width=6,
            # )

            dc_main_info = dmc.Title(
                "Data Collection Information",
                order=4,
                ta="left",
                fw="bold",
                size="md",
                mb="sm",
            )

            main_info = html.Table(
                [
                    html.Tr(
                        [
                            html.Td(
                                "Workflow ID:",
                                style={
                                    "font-weight": "bold",
                                    "text-align": "left",
                                    "width": "25%",
                                },
                            ),
                            html.Td(
                                workflow_id,
                                style={
                                    "text-align": "left",
                                    "word-break": "break-all",
                                    "overflow-wrap": "break-word",
                                    "font-family": "monospace",
                                    "font-size": "0.9em",
                                },
                            ),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td(
                                "Data Collection ID:",
                                style={
                                    "font-weight": "bold",
                                    "text-align": "left",
                                    "width": "25%",
                                },
                            ),
                            html.Td(
                                dc_specs["_id"],
                                style={
                                    "text-align": "left",
                                    "word-break": "break-all",
                                    "overflow-wrap": "break-word",
                                    "font-family": "monospace",
                                    "font-size": "0.9em",
                                },
                            ),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td(
                                "Type:",
                                style={
                                    "font-weight": "bold",
                                    "text-align": "left",
                                    "width": "25%",
                                },
                            ),
                            html.Td(
                                [
                                    dc_specs["config"]["type"].capitalize(),
                                    # Add MultiQC logo if this is a MultiQC data collection
                                    html.Img(
                                        src="/assets/images/logos/multiqc.png",
                                        style={
                                            "height": "20px",
                                            "marginLeft": "8px",
                                            "verticalAlign": "middle",
                                        },
                                    )
                                    if dc_specs["config"]["type"].lower() == "multiqc"
                                    else None,
                                ],
                                style={"text-align": "left"},
                            ),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td(
                                "MetaType:",
                                style={
                                    "font-weight": "bold",
                                    "text-align": "left",
                                    "width": "25%",
                                },
                            ),
                            html.Td(
                                (dc_specs["config"]["metatype"] or "Unknown").capitalize(),
                                style={"text-align": "left"},
                            ),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td(
                                "Name:",
                                style={
                                    "font-weight": "bold",
                                    "text-align": "left",
                                    "width": "25%",
                                },
                            ),
                            html.Td(
                                dc_specs["data_collection_tag"] or "Unknown",
                                style={
                                    "text-align": "left",
                                    "word-break": "break-all",
                                    "overflow-wrap": "break-word",
                                },
                            ),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td(
                                "Description:",
                                style={
                                    "font-weight": "bold",
                                    "text-align": "left",
                                    "width": "25%",
                                },
                            ),
                            html.Td(
                                dc_specs["description"] or "No description available",
                                style={
                                    "text-align": "left",
                                    "word-break": "break-all",
                                    "overflow-wrap": "break-word",
                                },
                            ),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td(
                                "Delta Table version:",
                                style={
                                    "font-weight": "bold",
                                    "text-align": "left",
                                    "width": "25%",
                                },
                            ),
                            html.Td("v1", style={"text-align": "left"}),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td(
                                "Rows:",
                                style={
                                    "font-weight": "bold",
                                    "text-align": "left",
                                    "width": "25%",
                                },
                            ),
                            html.Td(
                                f"{num_rows:,}" if isinstance(num_rows, int) else num_rows,
                                style={
                                    "text-align": "left",
                                    "font-family": "monospace",
                                    "font-size": "0.9em",
                                },
                            ),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td(
                                "Columns:",
                                style={
                                    "font-weight": "bold",
                                    "text-align": "left",
                                    "width": "25%",
                                },
                            ),
                            html.Td(
                                f"{num_columns:,}" if isinstance(num_columns, int) else num_columns,
                                style={
                                    "text-align": "left",
                                    "font-family": "monospace",
                                    "font-size": "0.9em",
                                },
                            ),
                        ]
                    ),
                ],
                style={
                    "width": "100%",
                    "table-layout": "fixed",
                    "overflow-wrap": "break-word",
                    "word-break": "break-all",
                },
            )

            # turn main_info into 4 rows with 2 columns

            # Create improved layout with consistent DMC components
            layout = dmc.Stack(
                [
                    dc_main_info,
                    dmc.Divider(variant="solid"),
                    dmc.Card(
                        main_info,
                        withBorder=True,
                        shadow="sm",
                        radius="md",
                        p="md",
                    ),
                    dmc.Space(h="md"),
                ],
                gap="md",
            )
            # if dc_specs["config"]["type"] == "Table":
            #     df = load_deltatable_lite(workflow_id, data_collection_id, TOKEN=TOKEN)
            #     cols = get_columns_from_data_collection(
            #         workflow_selection, data_collection_selection, TOKEN
            #     )
            #     columnDefs = [
            #         {"field": c, "headerTooltip": f"Type: {e['type']}"}
            #         for c, e in cols.items()
            #     ]

            #     # if description in col sub dict, update headerTooltip
            #     for col in columnDefs:
            #         if (
            #             "description" in cols[col["field"]]
            #             and cols[col["field"]]["description"] is not None
            #         ):
            #             col["headerTooltip"] = (
            #                 f"{col['headerTooltip']} | Description: {cols[col['field']]['description']}"
            #             )

            #     if "depictio_run_id" in cols:
            #         run_nb = cols["depictio_run_id"]["specs"]["nunique"]
            #         run_nb_title = dmc.Title(
            #             f"Run Nb : {run_nb}", order=3, align="left", fw="normal"
            #         )
            #     else:
            #         run_nb_title = dmc.Title(
            #             "Run Nb : 0", order=3, align="left", fw="normal"
            #         )

            #     data_previz_title = dmc.Title(
            #         "Data previsualization", order=3, align="left", fw="normal"
            #     )
            #     config_title = dmc.Title(
            #         "Data collection configuration", order=3, align="left", fw="normal"
            #     )
            #     # print(df.head(20).to_dict("records"))
            #     # cellClicked, cellDoubleClicked, cellRendererData, cellValueChanged, className, columnDefs, columnSize, columnSizeOptions, columnState, csvExportParams, dangerously_allow_code, dashGridOptions, defaultColDef, deleteSelectedRows, deselectAll, detailCellRendererParams, enableEnterpriseModules, exportDataAsCsv, filterModel, getDetailRequest, getDetailResponse, getRowId, getRowStyle, getRowsRequest, getRowsResponse, id, licenseKey, masterDetail, paginationGoTo, paginationInfo, persisted_props, persistence, persistence_type, resetColumnState, rowClass, rowClassRules, rowData, rowModelType, rowStyle, rowTransaction, scrollTo, selectAll, selectedRows, style, suppressDragLeaveHidesColumns, updateColumnState, virtualRowData
            #     grid = dag.AgGrid(
            #         # id={"type": "get-started-example-basic", "index": id["index"]},
            #         # rowModelType="infinite",
            #         rowData=df.to_pandas().head(100).to_dict("records"),
            #         columnDefs=columnDefs,
            #         dashGridOptions={
            #             "tooltipShowDelay": 500,
            #             "pagination": True,
            #             "paginationAutoPageSize": False,
            #             "animateRows": False,
            #             # The number of rows rendered outside the viewable area the grid renders.
            #             # "rowBuffer": 0,
            #             # # How many blocks to keep in the store. Default is no limit, so every requested block is kept.
            #             # "maxBlocksInCache": 2,
            #             # "cacheBlockSize": 100,
            #             # "cacheOverflowSize": 2,
            #             # "maxConcurrentDatasourceRequests": 2,
            #             # "infiniteInitialRowCount": 1,
            #             # "rowSelection": "multiple",
            #         },
            #         # columnSize="sizeToFit",
            #         defaultColDef={"resizable": True, "sortable": True, "filter": True},
            #         # use the parameters above
            #     )
            #     # layout += [run_nb_title, html.Hr(), data_previz_title, html.Hr(), grid]
            #     # print(layout)

            #     layout += [
            #         dmc.Accordion(
            #             children=[
            #                 dmc.AccordionItem(
            #                     [
            #                         dmc.AccordionControl(data_previz_title),
            #                         dmc.AccordionPanel(grid),
            #                     ],
            #                     value="data_collection_table_previz",
            #                 ),
            #                 dmc.AccordionItem(
            #                     [
            #                         dmc.AccordionControl(config_title),
            #                         dmc.AccordionPanel(prism),
            #                     ],
            #                     value="data_collection_config",
            #                 ),
            #             ],
            #         ),
            #         # buttons_list
            #     ]

            # elif dc_specs["config"]["type"] == "JBrowse2":
            #     if dc_specs["config"]["dc_specific_properties"][
            #         "jbrowse_template_location"
            #     ]:
            #         template_json = json.load(
            #             open(
            #                 dc_specs["config"]["dc_specific_properties"][
            #                     "jbrowse_template_location"
            #                 ]
            #             )
            #         )
            #         template_title = dmc.Title(
            #             "JBrowse template", order=3, align="left", fw="normal"
            #         )
            #         prism_template = dbc.Col(
            #             [
            #                 dmc.Prism(
            #                     f"""{json.dumps(template_json, indent=2)}""",
            #                     language="json",
            #                     colorScheme="light",
            #                     noCopy=True,
            #                 ),
            #             ],
            #             width=6,
            #         )
            #         layout += [
            #             dmc.Accordion(
            #                 children=[
            #                     dmc.AccordionItem(
            #                         [
            #                             dmc.AccordionControl(config_title),
            #                             dmc.AccordionPanel(prism),
            #                         ],
            #                         value="data_collection_config",
            #                     ),
            #                     dmc.AccordionItem(
            #                         [
            #                             dmc.AccordionControl(template_title),
            #                             dmc.AccordionPanel(prism_template),
            #                         ],
            #                         value="jbrowse_template",
            #                     ),
            #                 ],
            #             )
            #             # ,buttons_list
            #         ]

        else:
            layout = html.Div("No data to display")

        # Get metadata for the selected component
        component_metadata = get_component_metadata_by_display_name(component_selected)
        hex_color = get_component_color(component_selected.lower())  # Get hex color from colors.py

        return layout, dmc.Badge(
            component_selected,
            size="xl",
            radius="xl",
            variant="outline",
            style={"fontFamily": "Virgil", "fontSize": "16px"},
            color=component_metadata["color"],
            leftSection=DashIconify(
                icon=component_metadata["icon"],
                width=15,
                color=hex_color,
            ),
        )

    # @app.callback(
    #     Output({"type": "get-started-example-basic", "index": MATCH}, "getRowsResponse"),
    #     Input({"type": "get-started-example-basic", "index": MATCH}, "getRowsRequest"),
    #     Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
    #     Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
    #     State("local-store", "data"),
    #     prevent_initial_call=True,
    # )
    # def infinite_scroll(request, workflow_selection, data_collection_selection, local_store):
    #     # simulate slow callback
    #     # time.sleep(2)

    #     if request is None:
    #         return dash.no_update

    #     if local_store is None:
    #         raise dash.exceptions.PreventUpdate

    #     TOKEN = local_store["access_token"]

    #     if workflow_selection is not None and data_collection_selection is not None:

    #         workflow_id, data_collection_id = return_mongoid(workflow_tag=workflow_selection, data_collection_tag=data_collection_selection, TOKEN=TOKEN)

    #         dc_specs = httpx.get(
    #             f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{data_collection_id}",
    #             headers={
    #                 "Authorization": f"Bearer {TOKEN}",
    #             },
    #         ).json()

    #         if dc_specs["config"]["type"] == "Table":
    #             df = load_deltatable_lite(workflow_id, data_collection_id, TOKEN=TOKEN)

    #             partial = df[request["startRow"] : request["endRow"]]
    #             rows_response = {"rowData": partial.to_dicts(), "rowCount": df.shape[0]}
    #             return rows_response
    #         else:
    #             return dash.no_update
    #     else:
    #         return dash.no_update
