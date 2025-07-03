import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import polars as pl
from bson import ObjectId
from dash import dcc, html

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite


def build_table_frame(index, children=None):
    if not children:
        return dbc.Card(
            dbc.CardBody(
                id={
                    "type": "table-body",
                    "index": index,
                },
                style={
                    "padding": "5px",  # Reduce padding inside the card body
                    "display": "flex",
                    "flexDirection": "column",
                    "justifyContent": "center",
                    "height": "100%",  # Make sure it fills the parent container
                },
            ),
            style={
                "width": "100%",
                "height": "100%",  # Ensure the card fills the container's height
                "padding": "0",  # Remove default padding
                "margin": "0",  # Remove default margin
                "boxShadow": "none",  # Optional: Remove shadow for a cleaner look
                # "border": "1px solid #ddd",  # Optional: Add a light border
                # "borderRadius": "4px",  # Optional: Slightly round the corners
                "border": "0px",  # Optional: Remove border
            },
            id={
                "type": "table-component",
                "index": index,
            },
        )
    else:
        return dbc.Card(
            dbc.CardBody(
                children=children,
                id={
                    "type": "table-body",
                    "index": index,
                },
                style={
                    "padding": "5px",  # Reduce padding inside the card body
                    "display": "flex",
                    "flexDirection": "column",
                    "justifyContent": "center",
                    "height": "100%",  # Make sure it fills the parent container
                },
            ),
            style={
                "width": "100%",
                "height": "100%",  # Ensure the card fills the container's height
                "padding": "0",  # Remove default padding
                "margin": "0",  # Remove default margin
                "boxShadow": "none",  # Optional: Remove shadow for a cleaner look
                # "border": "1px solid #ddd",  # Optional: Add a light border
                # "borderRadius": "4px",  # Optional: Slightly round the corners
                "border": "0px",  # Optional: Remove border
            },
            id={
                "type": "table-component",
                "index": index,
            },
        )


def build_table(**kwargs):
    logger.info("build_table")
    # def build_card(index, title, wf_id, dc_id, dc_config, column_name, column_type, aggregation, v, build_frame=False):
    index = kwargs.get("index")
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    dc_config = kwargs.get("dc_config")
    cols = kwargs.get("cols_json")
    build_frame = kwargs.get("build_frame", False)

    df = kwargs.get("df", pl.DataFrame())
    TOKEN = kwargs.get("access_token")
    # stepper = kwargs.get("stepper", False)

    df = kwargs.get("df", pl.DataFrame())

    # if stepper:
    #     value_div_type = "table-aggrid-tmp"
    # else:
    value_div_type = "table-aggrid"

    if df.is_empty():
        # Check if we're in a refresh context where we should load new data
        if kwargs.get("refresh", True):
            logger.info(
                f"Table component {index}: Loading delta table for {wf_id}:{dc_id} (no pre-loaded df)"
            )
            # Validate that we have valid IDs before calling load_deltatable_lite
            if not wf_id or not dc_id:
                logger.warning(f"Missing workflow_id ({wf_id}) or data_collection_id ({dc_id})")
                df = pl.DataFrame()  # Return empty DataFrame if IDs are missing
            else:
                df = load_deltatable_lite(ObjectId(wf_id), ObjectId(dc_id), TOKEN=TOKEN)
        else:
            # If refresh=False and df is empty, this means filters resulted in no data
            # Keep the empty DataFrame to properly reflect the filtered state
            logger.info(
                f"Table component {index}: Using empty DataFrame from filters (shape: {df.shape}) - filters exclude all data"
            )
    else:
        logger.debug(f"Table component {index}: Using pre-loaded DataFrame (shape: {df.shape})")

    # Add dah aggrid filters to the columns
    if cols:
        for c in cols:
            if c in cols and "type" in cols[c]:
                print(c, cols[c]["type"])
                if cols[c]["type"] == "object":
                    cols[c]["filter"] = "agTextColumnFilter"
                elif cols[c]["type"] in ["int64", "float64"]:
                    cols[c]["filter"] = "agNumberColumnFilter"
                # FIXME: use properly this: https://dash.plotly.com/dash-ag-grid/date-filters
                elif cols[c]["type"] == "datetime":
                    cols[c]["filter"] = "agDateColumnFilter"

    # print(cols)
    columnDefs = []
    for c, e in cols.items():  # type: ignore[possibly-unbound-attribute]
        # Use original column names for both field and header
        field_name = c
        header_name = c  # Keep original format like sepal.length
        
        col_def = {
            "field": field_name,
            "headerName": header_name,  # Use original column name
            "headerTooltip": f"Column type: {e['type']}",
            "filter": e.get("filter", "agTextColumnFilter"),
        }
        
        # Add specific formatting for numerical columns
        if e["type"] in ["int64", "float64"]:
            col_def.update({
                "type": "numericColumn",
                "cellClass": "ag-right-aligned-cell",  # Right-align numbers
            })
            # Only add formatter for float columns to show decimals
            if e["type"] == "float64":
                col_def["valueFormatter"] = {"function": "params.value != null ? Number(params.value).toFixed(2) : ''"}
        elif e["type"] == "object":
            col_def.update({
                "cellDataType": "text",
            })
        elif e["type"] == "datetime":
            col_def.update({
                "cellDataType": "dateString",
            })
        
        columnDefs.append(col_def)

    # Debug column definitions
    logger.debug(f"Generated column definitions: {columnDefs}")

    # if description in col sub dict, update headerTooltip
    for col in columnDefs:
        if (
            cols
            and col["field"] in cols
            and "description" in cols[col["field"]]
            and cols[col["field"]]["description"] is not None
        ):
            col["headerTooltip"] = (
                f"{col['headerTooltip']} | Description: {cols[col['field']]['description']}"
            )

    style_partial_data_displayed = {"display": "none"}

    from dash_iconify import DashIconify

    cutoff = 1000

    if df.shape[0] > cutoff:
        df = df.head(cutoff)
        if build_frame:
            style_partial_data_displayed = {"display": "block", "paddingBottom": "5px"}

    partial_data_badge = dmc.Tooltip(
        children=dmc.Badge(
            "Partial data displayed",
            id={"type": "graph-partial-data-displayed", "index": index},
            style=style_partial_data_displayed,
            leftSection=DashIconify(
                icon="mdi:alert-circle",
                width=20,
            ),
            # sx={"paddingLeft": 0},
            size="lg",
            radius="xl",
            color="red",
            fullWidth=False,
        ),
        label=f"Tables are currently loaded with a maximum of {cutoff} rows.",
        position="top",
        openDelay=500,
    )
    # Prepare ag grid table
    # For datasets larger than cutoff or when explicitly requested, use infinite row model
    # But disable for stepper tables (with -tmp suffix) until metadata access is resolved
    is_stepper_table = "-tmp" in str(index)
    use_infinite_model = (
        (df.shape[0] > cutoff or kwargs.get("force_infinite", False)) 
        and not is_stepper_table
    )

    if use_infinite_model:
        # Infinite row model configuration
        table_aggrid = dag.AgGrid(
            id={"type": value_div_type, "index": str(index)},
            rowModelType="infinite",
            columnDefs=columnDefs,
            dashGridOptions={
                "tooltipShowDelay": 500,
                "animateRows": False,
                # Row buffer for smooth scrolling
                "rowBuffer": 10,
                # Cache configuration for performance (optimized for MB to GB datasets)
                "maxBlocksInCache": 10,  # Keep up to 10 blocks in memory
                "cacheBlockSize": 100,  # 100 rows per block
                "cacheOverflowSize": 2,  # Load 2 extra blocks
                "maxConcurrentDatasourceRequests": 2,
                "infiniteInitialRowCount": 100,  # Initial rows to show
                "rowSelection": "multiple",
                "enableCellTextSelection": True,
                "ensureDomOrder": True,
                # Loading overlay configuration
                "loadingOverlayComponent": "agLoadingOverlay",
                "noRowsOverlayComponent": "agNoRowsOverlay",
            },
            defaultColDef={"resizable": True, "sortable": True, "filter": True},
        )
    else:
        # Standard pagination for smaller datasets
        # Convert data using pure Polars, preserving numerical types
        logger.debug(f"Original Polars schema: {df.schema}")
        logger.debug(f"Column info mapping: {cols}")
        logger.debug(f"DataFrame columns: {df.columns}")
        
        # Ensure numerical columns are properly typed in Polars and handle NaN values
        df_processed = df
        for col_name, col_info in (cols or {}).items():
            if col_name in df.columns:
                if col_info.get("type") in ["int64", "float64"]:
                    try:
                        # First, handle any string representations of numbers
                        current_col = pl.col(col_name)
                        
                        if col_info.get("type") == "int64":
                            df_processed = df_processed.with_columns(
                                current_col.cast(pl.Int64, strict=False).alias(col_name)
                            )
                        elif col_info.get("type") == "float64":
                            df_processed = df_processed.with_columns(
                                current_col.cast(pl.Float64, strict=False).alias(col_name)
                            )
                        logger.debug(f"Column {col_name} cast to {col_info.get('type')}")
                    except Exception as e:
                        logger.warning(f"Could not cast column {col_name} to {col_info.get('type')}: {e}")
        
        logger.debug(f"Final Polars schema: {df_processed.schema}")
        
        # Convert to dict with Polars, letting nulls be handled naturally by to_dicts()
        # Polars to_dicts() converts null values to None automatically in Python
        row_data = df_processed.to_dicts()
        
        # Log sample with specific focus on numerical columns
        if row_data:
            sample_data = row_data[:2]
            logger.info(f"Sample data: {sample_data}")
            
            # Check all columns in the first row
            if sample_data:
                first_row = sample_data[0]
                logger.info(f"First row keys: {list(first_row.keys())}")
                logger.info(f"First row values: {list(first_row.values())}")
                
            # Log specific numerical columns to debug
            for col_name, col_info in (cols or {}).items():
                if col_info.get("type") in ["int64", "float64"] and sample_data:
                    values = [row.get(col_name) for row in sample_data[:2]]
                    logger.info(f"Column '{col_name}' (type: {col_info.get('type')}) sample values: {values}")
        else:
            logger.info("No data available")
        
        table_aggrid = dag.AgGrid(
            id={"type": value_div_type, "index": str(index)},
            rowData=row_data,
            columnDefs=columnDefs,
            dashGridOptions={
                "tooltipShowDelay": 500,
                "pagination": True,
                "paginationAutoPageSize": False,
                "animateRows": False,
                "rowSelection": "multiple",
                "enableCellTextSelection": True,
                "ensureDomOrder": True,
            },
            defaultColDef={"resizable": True, "sortable": True, "filter": True},
        )

    # Metadata management - Create a store component to store the metadata of the card
    store_index = index.replace("-tmp", "")  # type: ignore[possibly-unbound-attribute]
    store_component = dcc.Store(
        id={
            "type": "stored-metadata-component",
            "index": str(store_index),
        },
        data={
            "index": str(store_index),
            "component_type": "table",
            "wf_id": wf_id,
            "dc_id": dc_id,
            "dc_config": dc_config,
            "cols_json": cols,
            "parent_index": None,
        },
    )

    # Create the card body - default title is the aggregation value on the selected column

    # Create the card body
    new_card_body = html.Div(
        [
            partial_data_badge,
            table_aggrid,
            store_component,
        ]
    )
    if not build_frame:
        return new_card_body
    else:
        return build_table_frame(index=index, children=new_card_body)
