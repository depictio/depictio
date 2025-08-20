import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import polars as pl
from bson import ObjectId

from dash import dcc, html

# PERFORMANCE OPTIMIZATION: Use centralized config
from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.dash.modules.figure_component.utils import stringify_id


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
                "border": "1px solid var(--app-border-color, #ddd)",  # Always show border for draggable delimitation  # Optional: Remove border
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
                "border": "1px solid var(--app-border-color, #ddd)",  # Always show border for draggable delimitation  # Optional: Remove border
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
    theme = kwargs.get("theme", "light")
    df = kwargs.get("df", pl.DataFrame())
    TOKEN = kwargs.get("access_token")
    stepper = kwargs.get("stepper", False)

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
                # Handle joined data collection IDs - don't convert to ObjectId
                if isinstance(dc_id, str) and "--" in dc_id:
                    # For joined data collections, pass the DC ID as string
                    df = load_deltatable_lite(ObjectId(wf_id), dc_id, TOKEN=TOKEN)
                else:
                    # Regular data collection - convert to ObjectId
                    df = load_deltatable_lite(ObjectId(wf_id), ObjectId(dc_id), TOKEN=TOKEN)
        else:
            # If refresh=False and df is empty, this means filters resulted in no data
            # Keep the empty DataFrame to properly reflect the filtered state
            logger.info(
                f"Table component {index}: Using empty DataFrame from filters (shape: {df.shape}) - filters exclude all data"
            )
    else:
        logger.debug(f"Table component {index}: Using pre-loaded DataFrame (shape: {df.shape})")

    # Add dash aggrid filters to the columns with enhanced filter configuration
    if cols:
        for c in cols:
            logger.debug(f"Configuring column {c} with type {cols[c]['type']}")
            if c in cols and "type" in cols[c]:
                logger.debug(f"Configuring column {c} with type {cols[c]['type']}")
                if cols[c]["type"] == "object":
                    cols[c]["filter"] = "agTextColumnFilter"
                    # Enable floating filters for better UX
                    cols[c]["floatingFilter"] = True
                elif cols[c]["type"] in ["int64", "float64"]:
                    cols[c]["filter"] = "agNumberColumnFilter"
                    cols[c]["floatingFilter"] = True
                    # Add filter parameters for number columns
                    cols[c]["filterParams"] = {
                        "filterOptions": ["equals", "lessThan", "greaterThan", "inRange"],
                        "maxNumConditions": 2,
                    }
                # FIXME: use properly this: https://dash.plotly.com/dash-ag-grid/date-filters
                elif cols[c]["type"] == "datetime":
                    cols[c]["filter"] = "agDateColumnFilter"
                    cols[c]["floatingFilter"] = True

    # PERFORMANCE OPTIMIZATION: Conditionally add ID column based on loading spinner setting
    if settings.performance.disable_loading_spinners:
        # Performance mode: Simple ID column without spinner renderer
        columnDefs = [{"field": "ID", "maxWidth": 100}]
        logger.info("🚀 PERFORMANCE MODE: Ag-grid loading spinners disabled for ID column")
    else:
        # Add ID column for SpinnerCellRenderer (following documentation example exactly)
        columnDefs = [{"field": "ID", "maxWidth": 100, "cellRenderer": "SpinnerCellRenderer"}]

    # Add data columns with enhanced filtering and sorting support
    if cols:
        data_columns = []
        for c, e in cols.items():  # type: ignore[possibly-unbound-attribute]
            column_def = {
                "headerName": " ".join(
                    word.capitalize() for word in c.split(".")
                ),  # Transform display name
                "headerTooltip": f"Column type: {e['type']}",
                "filter": e["filter"],
                "floatingFilter": e.get("floatingFilter", False),
                "filterParams": e.get("filterParams", {}),
                "sortable": True,  # Enable sorting for all columns
                "resizable": True,  # Enable column resizing
                "minWidth": 150,  # Ensure readable column width
            }

            # Handle field names with dots - replace dots with underscores
            if "." in c:
                logger.debug(
                    f"🔍 DEBUG: Found column with dot: '{c}', replacing dots with underscores"
                )
                # Create a safe field name by replacing dots with underscores
                safe_field_name = c.replace(".", "_")
                column_def["field"] = safe_field_name
                logger.debug(f"🔍 DEBUG: Column def for '{c}': field='{safe_field_name}'")
            else:
                logger.debug(f"🔍 DEBUG: Regular column: '{c}', using field")
                column_def["field"] = c  # Use field for simple names

            data_columns.append(column_def)
        columnDefs.extend(data_columns)

    # if description in col sub dict, update headerTooltip
    for col in columnDefs:
        if (
            cols
            and "field" in col  # Check if field exists in column definition
            and col["field"] in cols
            and "description" in cols[col["field"]]
            and cols[col["field"]]["description"] is not None
        ):
            col["headerTooltip"] = (
                f"{col['headerTooltip']} | Description: {cols[col['field']]['description']}"
            )
    logger.info(f"Columns definitions for table {index}: {columnDefs}")

    # INFINITE ROW MODEL: Always use infinite scroll with interactive component support
    # The infinite scroll callback handles:
    # - Interactive component filtering via iterative_join
    # - AG Grid server-side filtering and sorting
    # - Efficient pagination for all table sizes

    logger.info(f"📊 Table {index}: Using INFINITE row model with interactive component support")
    logger.info("🔄 Interactive filters and pagination handled by infinite scroll callback")

    logger.info(f"Table {index}: Building AG Grid with theme {theme}")

    # Always use infinite scroll configuration
    table_aggrid = dag.AgGrid(
        id={"type": value_div_type, "index": str(index)},
        # CRITICAL: Don't set rowData for infinite model - data comes from getRowsResponse
        rowModelType="infinite",
        columnDefs=columnDefs,
        dashGridOptions={
            "tooltipShowDelay": 500,
            # INFINITE MODEL CONFIGURATION (optimized for interactive + pagination)
            "rowBuffer": 0,  # Match documentation example
            "maxBlocksInCache": 10,  # Reasonable cache size
            "cacheBlockSize": 100,  # Each block contains 100 rows
            "cacheOverflowSize": 2,  # Allow 2 extra blocks beyond maxBlocksInCache
            "infiniteInitialRowCount": 1000,  # Initial estimate
            # OTHER OPTIONS
            "rowSelection": "multiple",
            "enableCellTextSelection": True,
            "ensureDomOrder": True,
            "pagination": True,
            # CRITICAL: Cache management for interactive components
            "purgeClosedRowNodes": True,  # Clean up when filters change
            "resetRowDataOnUpdate": True,  # Force refresh when interactive values change
            # CRITICAL: Ensure AG Grid makes new requests after cache invalidation
            "maxConcurrentDatasourceRequests": 1,  # Prevent racing conditions
            "blockLoadDebounceMillis": 0,  # Immediate loading after cache reset
        },
        getRowId="params.data.ID",
        defaultColDef={
            "flex": 1,
            "minWidth": 150,
            "sortable": True,
            "resizable": True,
            "floatingFilter": True,
            "filter": True,
        },
        style={"width": "100%"},
        className="ag-theme-alpine" if theme == "light" else "ag-theme-alpine-dark",
    )

    logger.info(f"✅ Table {index}: Infinite row model configured with interactive support")

    # Metadata management - Create a store component to store the metadata of the card
    # CRITICAL: The stored-metadata-component index must match the table component index
    # for MATCH patterns to work correctly in callbacks like infinite_scroll_component
    #
    # However, the draggable callback expects clean metadata index and appends -tmp
    # Solution: Create with matching index, but store clean index in data
    store_index = str(index)  # Keep same index as table component for MATCH patterns
    clean_index = str(index).replace("-tmp", "")  # Clean index for data storage

    store_component = dcc.Store(
        id={
            "type": "stored-metadata-component",
            "index": store_index,  # Same as table component index
        },
        data={
            "index": clean_index,  # Clean index for draggable callback
            "component_type": "table",
            "wf_id": wf_id,
            "dc_id": dc_id,
            "dc_config": dc_config,
            "cols_json": cols,
            "parent_index": None,
        },
    )

    # Create the card body - default title is the aggregation value on the selected column

    # Create the card body - simple structure
    new_card_body = html.Div(
        [
            # infinite_scroll_badge,  # Removed as requested
            table_aggrid,
            store_component,
        ]
    )
    if not build_frame:
        return new_card_body
    else:
        # Build the table component with frame
        table_component = build_table_frame(index=index, children=new_card_body)

        if not stepper:
            # Add targeted loading for the AG Grid component specifically
            from depictio.dash.layouts.draggable_scenarios.progressive_loading import (
                create_skeleton_component,
            )

            graph_id_dict = {"type": "table-aggrid", "index": str(index)}
            target_id = stringify_id(graph_id_dict)
            logger.debug(f"Target ID for loading: {target_id}")

            # PERFORMANCE OPTIMIZATION: Conditional loading spinner
            if settings.performance.disable_loading_spinners:
                logger.info("🚀 PERFORMANCE MODE: Table loading spinners disabled")
                return table_component  # Return content directly, no loading wrapper
            else:
                # Optimized loading with fast delays
                return dcc.Loading(
                    children=table_component,
                    custom_spinner=create_skeleton_component("table"),
                    target_components={target_id: "rowData"},
                    delay_show=5,  # Fast delay for better UX
                    delay_hide=25,  # Quick hide for performance
                    id={"index": index},
                )

        else:
            # For stepper mode without loading
            return table_component


# Async wrapper for background callbacks (following card component pattern)
async def build_table_async(**kwargs):
    """
    Async wrapper for build_table function.
    Used in background callbacks where async execution is needed.
    """
    logger.info(
        f"🔄 ASYNC TABLE: Building table component asynchronously - Index: {kwargs.get('index', 'UNKNOWN')}"
    )

    # Call the synchronous build_table function
    # In the future, this could run in a thread pool if needed for true parallelism
    result = build_table(**kwargs)

    logger.info(
        f"✅ ASYNC TABLE: Table component built successfully - Index: {kwargs.get('index', 'UNKNOWN')}"
    )
    return result
