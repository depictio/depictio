import json
from dash import html, Input, Output, State, ALL, MATCH, ctx
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import httpx
import yaml
import dash_ag_grid as dag

from depictio.dash.utils import get_columns_from_data_collection, return_mongoid
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.api.v1.configs.config import API_BASE_URL, TOKEN, logger


def register_callbacks_stepper_part_one(app):
    @app.callback(
        Output({"type": "dropdown-output", "index": MATCH}, "children"),
        Output({"type": "component-selected", "index": MATCH}, "children"),
        # Output({"type": "component-selected", "index": MATCH}, "color"),
        Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
        Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        State({"type": "last-button", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def update_step_1(workflow_selection, data_collection_selection, input_btn_values, component_selected):
        # Use dcc.Store in store-list to get the latest button clicked using timestamps

        logger.info(f"CTX Triggered ID: {ctx.triggered_id}")
        logger.info(f"CTX triggered: {ctx.triggered}")

        # if (isinstance(ctx.triggered_id, dict)) and (ctx.triggered_id["type"] == "btn-option"):
        #     # component_selected = ctx.triggered_id["value"]
        #     component_selected = component_selected

        # else:
        #     # component_selected = "None"
        #     component_selected = input_last_component

        component_metadata_dict = {
            "Card": {"color": "violet", "icon": "formkit:number"},
            "Figure": {"color": "grape", "icon": "mdi:graph-box"},
            "Interactive": {"color": "indigo", "icon": "bx:slider-alt"},
            "Table": {"color": "green", "icon": "octicon:table-24"},
            "JBrowse2": {"color": "yellow", "icon": "material-symbols:table-rows-narrow-rounded"},
            "None": {"color": "gray", "icon": "ph:circle"},
        }

        # Determine the index of the most recently modified (clicked) button
        # latest_index = store_btn_ts.index(max(store_btn_ts))
        # component_selected = components_list[latest_index]

        # logger.info(f"component_selected: {component_selected}")

        workflow_id, data_collection_id = return_mongoid(workflow_tag=workflow_selection, data_collection_tag=data_collection_selection)
        # workflows = list_workflows(TOKEN)

        # workflow_id = [e for e in workflows if e["workflow_tag"] == workflow_selection][0]["_id"]
        # data_collection_id = [f for e in workflows if e["_id"] == workflow_id for f in e["data_collections"] if f["data_collection_tag"] == data_collection_selection][0]["_id"]

        # print(data_collection_selection)

        dc_specs = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
            headers={
                "Authorization": f"Bearer {TOKEN}",
            },
        ).json()

        if workflow_selection is not None and data_collection_selection is not None:
            # component_selected = html.Div(f"{component_selected}")

            config_title = dmc.Title("Data collection config", order=3, align="left", weight=500)
            json_formatted = yaml.dump(dc_specs["config"], indent=2)
            prism = dbc.Col(
                [
                    dmc.AccordionPanel(
                        dmc.Prism(
                            f"""{json_formatted}""",
                            language="yaml",
                            colorScheme="light",
                            noCopy=True,
                        )
                    ),
                ],
                width=6,
            )

            dc_main_info = dmc.Title("Data collection info", order=3, align="left", weight=500)

            main_info = html.Table(
                [
                    html.Tr(
                        [
                            html.Td(
                                "Workflow ID:",
                                style={
                                    "font-weight": "bold",
                                    "text-align": "left",
                                    "width": "20%",
                                },
                            ),
                            html.Td(workflow_id, style={"text-align": "left"}),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td(
                                "Type:",
                                style={
                                    "font-weight": "bold",
                                    "text-align": "left",
                                    "width": "20%",
                                },
                            ),
                            html.Td(dc_specs["config"]["type"], style={"text-align": "left"}),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td(
                                "Name:",
                                style={
                                    "font-weight": "bold",
                                    "text-align": "left",
                                    "width": "20%",
                                },
                            ),
                            html.Td(
                                dc_specs["data_collection_tag"],
                                style={"text-align": "left"},
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
                                    "width": "20%",
                                },
                            ),
                            html.Td(dc_specs["description"], style={"text-align": "left"}),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td(
                                "MongoDB ID:",
                                style={
                                    "font-weight": "bold",
                                    "text-align": "left",
                                    "width": "20%",
                                },
                            ),
                            html.Td(dc_specs["_id"], style={"text-align": "left"}),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td(
                                "Delta Table version:",
                                style={
                                    "font-weight": "bold",
                                    "text-align": "left",
                                    "width": "20%",
                                },
                            ),
                            html.Td("v1", style={"text-align": "left"}),
                        ]
                    ),
                ],
                style={"width": "100%", "table-layout": "fixed"},
            )

            # turn main_info into 4 rows with 2 columns

            layout = [dc_main_info, html.Hr(), main_info, html.Hr()]
            if dc_specs["config"]["type"] == "Table":
                df = load_deltatable_lite(workflow_id, data_collection_id)
                cols = get_columns_from_data_collection(workflow_selection, data_collection_selection)
                logger.info(f"Columns: {cols}")
                columnDefs = [{"field": c, "headerTooltip": f"Type: {e['type']}"} for c, e in cols.items()]

                # if description in col sub dict, update headerTooltip
                for col in columnDefs:
                    if "description" in cols[col["field"]] and cols[col["field"]]["description"] is not None:
                        col["headerTooltip"] = f"{col['headerTooltip']}\nDescription: {cols[col['field']]['description']}"

                if "depictio_run_id" in cols:
                    run_nb = cols["depictio_run_id"]["specs"]["nunique"]
                    run_nb_title = dmc.Title(f"Run Nb : {run_nb}", order=3, align="left", weight=500)
                else:
                    run_nb_title = dmc.Title("Run Nb : 0", order=3, align="left", weight=500)

                data_previz_title = dmc.Title("Data previsualization", order=3, align="left", weight=500)
                config_title = dmc.Title("Data collection configuration", order=3, align="left", weight=500)
                # print(df.head(20).to_dict("records"))
                # cellClicked, cellDoubleClicked, cellRendererData, cellValueChanged, className, columnDefs, columnSize, columnSizeOptions, columnState, csvExportParams, dangerously_allow_code, dashGridOptions, defaultColDef, deleteSelectedRows, deselectAll, detailCellRendererParams, enableEnterpriseModules, exportDataAsCsv, filterModel, getDetailRequest, getDetailResponse, getRowId, getRowStyle, getRowsRequest, getRowsResponse, id, licenseKey, masterDetail, paginationGoTo, paginationInfo, persisted_props, persistence, persistence_type, resetColumnState, rowClass, rowClassRules, rowData, rowModelType, rowStyle, rowTransaction, scrollTo, selectAll, selectedRows, style, suppressDragLeaveHidesColumns, updateColumnState, virtualRowData
                grid = dag.AgGrid(
                    id="get-started-example-basic",
                    # FIXME : full polars
                    rowData=df.head(2000).to_pandas().to_dict("records"),
                    columnDefs=columnDefs,
                    dashGridOptions={
                        "tooltipShowDelay": 500,
                        "pagination": True,
                        "paginationAutoPageSize": False,
                        "animateRows": False,
                    },
                    columnSize="sizeToFit",
                    defaultColDef={"resizable": True, "sortable": True, "filter": True},
                    # use the parameters above
                )
                # layout += [run_nb_title, html.Hr(), data_previz_title, html.Hr(), grid]
                # print(layout)

                layout += [
                    dmc.Accordion(
                        children=[
                            dmc.AccordionItem(
                                [
                                    dmc.AccordionControl(data_previz_title),
                                    dmc.AccordionPanel(grid),
                                ],
                                value="data_collection_table_previz",
                            ),
                            dmc.AccordionItem(
                                [
                                    dmc.AccordionControl(config_title),
                                    dmc.AccordionPanel(prism),
                                ],
                                value="data_collection_config",
                            ),
                        ],
                    ),
                    # buttons_list
                ]

            elif dc_specs["config"]["type"] == "JBrowse2":
                if dc_specs["config"]["dc_specific_properties"]["jbrowse_template_location"]:
                    template_json = json.load(open(dc_specs["config"]["dc_specific_properties"]["jbrowse_template_location"]))
                    template_title = dmc.Title("JBrowse template", order=3, align="left", weight=500)
                    prism_template = dbc.Col(
                        [
                            dmc.Prism(
                                f"""{json.dumps(template_json, indent=2)}""",
                                language="json",
                                colorScheme="light",
                                noCopy=True,
                            ),
                        ],
                        width=6,
                    )
                    layout += [
                        dmc.Accordion(
                            children=[
                                dmc.AccordionItem(
                                    [
                                        dmc.AccordionControl(config_title),
                                        dmc.AccordionPanel(prism),
                                    ],
                                    value="data_collection_config",
                                ),
                                dmc.AccordionItem(
                                    [
                                        dmc.AccordionControl(template_title),
                                        dmc.AccordionPanel(prism_template),
                                    ],
                                    value="jbrowse_template",
                                ),
                            ],
                        )
                        # ,buttons_list
                    ]

        else:
            layout = html.Div("No data to display")

        return layout, dmc.Badge(
            component_selected,
            size="xl",
            radius="xl",
            style={"fontFamily": "Virgil"},
            color=component_metadata_dict[component_selected]["color"],
            leftSection=DashIconify(icon=component_metadata_dict[component_selected]["icon"], width=15, color=component_metadata_dict[component_selected]["color"]),
        )
