import json
from dash import html, Input, Output, State, ALL, MATCH, ctx
import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import httpx
import yaml
import dash_ag_grid as dag

from depictio.dash.utils import list_workflows, join_deltatables, get_columns_from_data_collection, load_deltatable_lite, return_mongoid
from depictio.api.v1.configs.config import API_BASE_URL, TOKEN, logger


def register_callbacks_stepper_part_one(app):
    @app.callback(
        Output({"type": "dropdown-output", "index": MATCH}, "children"),
        Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
        Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        prevent_initial_call=True,
    )
    def update_step_2(workflow_selection, data_collection_selection):
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
                df = load_deltatable_lite(workflow_id, data_collection_id, raw=True)
                cols = get_columns_from_data_collection(workflow_selection, data_collection_selection)
                logger.info(cols)
                columnDefs = [{"field": c, "headerTooltip": f"Column type: {e['type']}"} for c, e in cols.items()]
                logger.info(columnDefs)
                

                run_nb = cols["depictio_run_id"]["specs"]["nunique"]
                run_nb_title = dmc.Title(f"Run Nb : {run_nb}", order=3, align="left", weight=500)

                data_previz_title = dmc.Title("Data previsualization", order=3, align="left", weight=500)
                config_title = dmc.Title("Data collection configuration", order=3, align="left", weight=500)
                # print(df.head(20).to_dict("records"))
                # cellClicked, cellDoubleClicked, cellRendererData, cellValueChanged, className, columnDefs, columnSize, columnSizeOptions, columnState, csvExportParams, dangerously_allow_code, dashGridOptions, defaultColDef, deleteSelectedRows, deselectAll, detailCellRendererParams, enableEnterpriseModules, exportDataAsCsv, filterModel, getDetailRequest, getDetailResponse, getRowId, getRowStyle, getRowsRequest, getRowsResponse, id, licenseKey, masterDetail, paginationGoTo, paginationInfo, persisted_props, persistence, persistence_type, resetColumnState, rowClass, rowClassRules, rowData, rowModelType, rowStyle, rowTransaction, scrollTo, selectAll, selectedRows, style, suppressDragLeaveHidesColumns, updateColumnState, virtualRowData
                grid = dag.AgGrid(
                    id="get-started-example-basic",
                    rowData=df.head(2000).to_dict("records"),
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
                    print(template_json)
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

        return layout
