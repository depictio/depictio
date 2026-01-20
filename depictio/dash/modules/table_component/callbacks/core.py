"""
Table Component Core Callbacks

View mode callbacks for table component:
- Theme switching for AG Grid
- Infinite scroll with filtering, sorting, and interactive component integration
"""

import polars as pl
from dash import ALL, MATCH, Input, Output, State, ctx, no_update

from depictio.api.v1.configs.logging_init import logger

# AG Grid filter operators mapping to Polars operations
OPERATORS = {
    "greaterThanOrEqual": "ge",
    "lessThanOrEqual": "le",
    "lessThan": "lt",
    "greaterThan": "gt",
    "notEqual": "ne",
    "equals": "eq",
}


def apply_ag_grid_filter(df: pl.DataFrame, filter_model: dict, col: str) -> pl.DataFrame:
    """
    Apply AG Grid filter to a Polars DataFrame.
    Based on dash-ag-grid documentation examples.
    """
    filter_type = filter_model.get("filterType")

    if filter_type == "text":
        filter_value = filter_model.get("filter", "")
        filter_operator = filter_model.get("type", "contains")

        if filter_operator == "contains":
            df = df.filter(pl.col(col).cast(pl.Utf8).str.contains(filter_value, literal=False))
        elif filter_operator == "notContains":
            df = df.filter(~pl.col(col).cast(pl.Utf8).str.contains(filter_value, literal=False))
        elif filter_operator == "equals":
            df = df.filter(pl.col(col) == filter_value)
        elif filter_operator == "notEqual":
            df = df.filter(pl.col(col) != filter_value)
        elif filter_operator == "startsWith":
            df = df.filter(pl.col(col).cast(pl.Utf8).str.starts_with(filter_value))
        elif filter_operator == "endsWith":
            df = df.filter(pl.col(col).cast(pl.Utf8).str.ends_with(filter_value))

    elif filter_type == "number":
        filter_value = filter_model.get("filter")
        filter_operator = filter_model.get("type", "equals")

        if filter_operator in OPERATORS:
            df = df.filter(getattr(pl.col(col), OPERATORS[filter_operator])(filter_value))

    elif filter_type == "date":
        date_from = filter_model.get("dateFrom")
        date_to = filter_model.get("dateTo")
        filter_operator = filter_model.get("type", "equals")

        if filter_operator == "equals" and date_from:
            df = df.filter(pl.col(col) == date_from)
        elif filter_operator == "notEqual" and date_from:
            df = df.filter(pl.col(col) != date_from)
        elif filter_operator == "greaterThan" and date_from:
            df = df.filter(pl.col(col) > date_from)
        elif filter_operator == "greaterThanOrEqual" and date_from:
            df = df.filter(pl.col(col) >= date_from)
        elif filter_operator == "lessThan" and date_from:
            df = df.filter(pl.col(col) < date_from)
        elif filter_operator == "lessThanOrEqual" and date_from:
            df = df.filter(pl.col(col) <= date_from)
        elif filter_operator == "inRange" and date_from and date_to:
            df = df.filter((pl.col(col) >= date_from) & (pl.col(col) <= date_to))

    elif filter_type == "set":
        # Set filter - include only specific values
        values = filter_model.get("values", [])
        if values:
            df = df.filter(pl.col(col).is_in(values))

    return df


def apply_ag_grid_sorting(df: pl.DataFrame, sort_model: list) -> pl.DataFrame:
    """
    Apply AG Grid sorting to a Polars DataFrame.
    """
    if not sort_model:
        return df

    # Build list of column/descending pairs for Polars sort
    sort_cols = []
    sort_descending = []

    for sort in sort_model:
        col_id = sort["colId"]
        sort_order = sort["sort"]  # 'asc' or 'desc'

        sort_cols.append(col_id)
        sort_descending.append(sort_order == "desc")

    return df.sort(sort_cols, descending=sort_descending)


def load_table_data_with_filters(
    workflow_id: str,
    data_collection_id: str,
    stored_metadata: dict,
    interactive_values: dict | None,
    interactive_metadata_list: list,
    interactive_metadata_ids: list,
    filter_model: dict | None = None,
    sort_model: list | None = None,
    TOKEN: str | None = None,
) -> pl.DataFrame:
    """
    Load table data with interactive filters, AG Grid filters, and sorting applied.

    This function centralizes data loading logic used by both:
    - infinite_scroll_component (with pagination)
    - export_table_to_csv (complete dataset)

    Args:
        workflow_id: Workflow ID
        data_collection_id: Data collection ID
        stored_metadata: Table component metadata
        interactive_values: Interactive component filter values
        interactive_metadata_list: List of interactive component metadata
        interactive_metadata_ids: List of interactive component IDs
        filter_model: AG Grid filter model
        sort_model: AG Grid sort model
        TOKEN: Authentication token

    Returns:
        pl.DataFrame: Filtered and sorted DataFrame
    """
    from bson import ObjectId

    from depictio.api.v1.deltatables_utils import load_deltatable_lite
    from depictio.dash.utils import get_result_dc_for_workflow

    logger.info("🔄 load_table_data_with_filters: Loading table data")

    # CRITICAL: Enrich lightweight store data with full metadata from States
    # Pattern from card callback - fixes missing metadata issue

    # Step 1: Build metadata mapping (index → full metadata)
    metadata_by_index = {}
    if interactive_metadata_list and interactive_metadata_ids:
        for i, meta_id in enumerate(interactive_metadata_ids):
            if i < len(interactive_metadata_list):
                index = meta_id["index"]
                metadata_by_index[index] = interactive_metadata_list[i]
                logger.debug(f"Mapped metadata for interactive component {index}")

    # Step 2: Extract lightweight components from store
    lightweight_components = (
        interactive_values.get("interactive_components_values", []) if interactive_values else []
    )

    logger.debug(
        f"Enrichment starting - {len(lightweight_components)} lightweight components, "
        f"{len(metadata_by_index)} metadata entries available"
    )

    # Step 3: Enrich lightweight data with full metadata
    interactive_components_dict = {}

    for component in lightweight_components:
        index = component.get("index")
        value = component.get("value")

        if not index:
            continue

        # Get full metadata from mapping
        full_metadata = metadata_by_index.get(index)

        if full_metadata:
            # Build enriched component data
            enriched_component = {
                "index": index,
                "value": value,
                "component_type": "interactive",  # Type is known
                "metadata": full_metadata,  # Full metadata added
            }

            interactive_components_dict[index] = enriched_component

            logger.debug(
                f"✅ Enriched component {index}: DC={full_metadata.get('dc_id')}, "
                f"Column={full_metadata.get('column_name')}, "
                f"Type={full_metadata.get('interactive_component_type')}"
            )
        else:
            logger.warning(f"⚠️ Component {index} has value but no metadata - skipping")

    logger.info(f"📊 Enrichment complete - {len(interactive_components_dict)} components enriched")

    # CRITICAL FIX: Prepare metadata for iterative join INCLUDING all interactive components
    # When interactive components exist, we need to include their metadata for proper joining
    stored_metadata_for_join = []

    # Always include the table metadata
    table_metadata = dict(stored_metadata)  # Convert to regular dict
    table_metadata["component_type"] = "table"  # Ensure component type is set
    stored_metadata_for_join.append(table_metadata)

    # CRITICAL: Include metadata from all interactive components for join calculation
    if interactive_components_dict:
        for component_index, component_data in interactive_components_dict.items():
            if component_data.get("metadata"):
                interactive_meta = dict(component_data["metadata"])
                interactive_meta["component_type"] = "interactive"
                stored_metadata_for_join.append(interactive_meta)
                logger.info(
                    f"✅ Including interactive component {component_index} in join calculation"
                )

    logger.info(
        f"📊 Metadata for join prepared: {len(stored_metadata_for_join)} component(s) (table + interactive)"
    )

    # INTERACTIVE COMPONENT FILTERING LOGIC
    if interactive_components_dict:
        logger.info(
            f"🎯 Active interactive components: {len(interactive_components_dict)} component(s)"
        )

        if interactive_components_dict:
            # Extract DC IDs
            table_dc_id = stored_metadata.get("dc_id")
            table_dc_ids = {table_dc_id}
            interactive_dc_ids = {
                comp_data.get("metadata", {}).get("dc_id")
                for comp_data in interactive_components_dict.values()
            }

            logger.info(f"📋 Table DC: {table_dc_id}")
            logger.info(f"📋 Interactive DCs: {interactive_dc_ids}")

            # MIGRATED: Check for pre-computed joins
            result_dc_id = get_result_dc_for_workflow(workflow_id, TOKEN)

            # Check DC compatibility
            if table_dc_ids & interactive_dc_ids:
                logger.info("✅ DC COMPATIBLE: Interactive filters target same DC as table")

                # MIGRATED: With pre-computed joins, we no longer need semi-join optimization
                # Just load the result DC (or single DC if no joins) with interactive filters
                try:
                    if result_dc_id:
                        # Load pre-computed join result DC with interactive filters
                        logger.info("🔗 Loading pre-computed joined table with interactive filters")
                        df = load_deltatable_lite(
                            ObjectId(workflow_id),
                            ObjectId(result_dc_id),
                            metadata=list(interactive_components_dict.values()),
                            TOKEN=TOKEN,
                        )
                        logger.info(
                            f"✅ Successfully loaded FILTERED data from result DC (shape: {df.shape})"
                        )
                    else:
                        # No join - load single DC with interactive filters
                        logger.info("📊 No joins - loading single DC with interactive filters")
                        df = load_deltatable_lite(
                            ObjectId(workflow_id),
                            ObjectId(data_collection_id),
                            metadata=list(interactive_components_dict.values()),
                            TOKEN=TOKEN,
                        )
                        logger.info(
                            f"✅ Successfully loaded FILTERED single DC (shape: {df.shape})"
                        )
                except Exception as interactive_error:
                    logger.error(f"❌ Loading data failed: {str(interactive_error)}")
                    # Fallback to unfiltered data
                    df = load_deltatable_lite(
                        ObjectId(workflow_id),
                        ObjectId(data_collection_id),
                        metadata=None,
                        TOKEN=TOKEN,
                    )
                    logger.info("✅ Fallback: Loaded unfiltered data")
            else:
                # DC INCOMPATIBLE
                logger.warning(
                    f"⚠️ DC INCOMPATIBLE: Interactive filters target different DCs ({interactive_dc_ids}) than table ({table_dc_id})"
                )
                logger.warning("🔧 Loading table data UNJOINED")

                df = load_deltatable_lite(
                    ObjectId(workflow_id),
                    ObjectId(data_collection_id),
                    metadata=None,
                    TOKEN=TOKEN,
                )
                logger.info(f"✅ Loaded unjoined table data (shape: {df.shape})")
        else:
            # No active interactive components
            df = load_deltatable_lite(
                ObjectId(workflow_id),
                ObjectId(data_collection_id),
                metadata=None,
                TOKEN=TOKEN,
            )
            logger.info(f"✅ Loaded table data without interactive filters (shape: {df.shape})")
    else:
        # No interactive components - check if table needs joins
        logger.info(
            f"💾 Loading delta table data (no interactive components): {workflow_id}:{data_collection_id}"
        )

        try:
            # MIGRATED: Load pre-computed join or single DC
            result_dc_id = get_result_dc_for_workflow(workflow_id, TOKEN)

            if result_dc_id:
                # Table has pre-computed join - load result DC
                logger.info("🔗 Table has pre-computed join - loading result DC")
                df = load_deltatable_lite(
                    ObjectId(workflow_id), ObjectId(result_dc_id), metadata=None, TOKEN=TOKEN
                )
                logger.info(f"✅ Successfully loaded joined table data (shape: {df.shape})")
            else:
                # No joins needed - load single DC
                df = load_deltatable_lite(
                    ObjectId(workflow_id),
                    ObjectId(data_collection_id),
                    metadata=None,
                    TOKEN=TOKEN,
                )
                logger.info(f"✅ Successfully loaded single table data (shape: {df.shape})")

        except Exception as join_error:
            logger.warning(f"⚠️ Error checking table joins: {str(join_error)}")
            # Fallback
            df = load_deltatable_lite(
                ObjectId(workflow_id),
                ObjectId(data_collection_id),
                metadata=None,
                TOKEN=TOKEN,
            )
            logger.info(f"✅ Fallback: Loaded single table data (shape: {df.shape})")

    logger.info(f"📊 Loaded initial dataset: {df.shape[0]} rows, {df.shape[1]} columns")

    # APPLY AG GRID FILTERS
    if filter_model:
        logger.info(f"🔍 Applying {len(filter_model)} AG Grid filters")
        for col, filter_def in filter_model.items():
            try:
                if "operator" in filter_def:
                    # Handle complex filters with AND/OR operators
                    if filter_def["operator"] == "AND":
                        df = apply_ag_grid_filter(df, filter_def["condition1"], col)
                        df = apply_ag_grid_filter(df, filter_def["condition2"], col)
                        logger.debug(f"Applied AND filter to column {col}")
                    else:  # OR operator
                        df1 = apply_ag_grid_filter(df, filter_def["condition1"], col)
                        df2 = apply_ag_grid_filter(df, filter_def["condition2"], col)
                        df = pl.concat([df1, df2]).unique()
                        logger.debug(f"Applied OR filter to column {col}")
                else:
                    # Handle simple filters
                    df = apply_ag_grid_filter(df, filter_def, col)
                    logger.debug(f"Applied simple filter to column {col}")
            except Exception as e:
                logger.warning(f"Failed to apply filter for column {col}: {e}")
                continue

        logger.info(f"📊 After filtering: {df.shape[0]} rows remaining")

    # APPLY AG GRID SORTING
    if sort_model:
        logger.info(f"🔤 Applying sorting: {[(s['colId'], s['sort']) for s in sort_model]}")
        df = apply_ag_grid_sorting(df, sort_model)
        logger.info("✅ Sorting applied successfully")

    logger.info(
        f"📊 Final dataset after filters/sorting: {df.shape[0]} rows, {df.shape[1]} columns"
    )

    return df


def register_core_callbacks(app):
    """Register core view mode callbacks for table component."""
    from depictio.api.v1.configs.logging_init import logger as core_logger

    core_logger.info("🔧 Registering table component core callbacks (theme + infinite scroll)")

    @app.callback(
        Output({"type": "table-aggrid", "index": MATCH}, "className"),
        Input("theme-store", "data"),
        prevent_initial_call=False,
    )
    def update_table_ag_grid_theme(theme_data):
        """Update AG Grid theme class based on current theme."""
        theme = theme_data or "light"
        if theme == "dark":
            return "ag-theme-alpine-dark"
        else:
            return "ag-theme-alpine"

    @app.callback(
        Output({"type": "table-aggrid", "index": MATCH}, "getRowsResponse"),
        [
            Input({"type": "table-aggrid", "index": MATCH}, "getRowsRequest"),
            Input("interactive-values-store", "data"),
        ],
        [
            State({"type": "stored-metadata-component", "index": MATCH}, "data"),
            State("local-store", "data"),
            State("url", "pathname"),
            State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
            State({"type": "interactive-stored-metadata", "index": ALL}, "id"),
        ],
        prevent_initial_call=False,  # Allow callback to fire on mount for initial data load
    )
    def infinite_scroll_component(
        request,
        interactive_values,
        stored_metadata,
        local_store,
        pathname,
        interactive_metadata_list,
        interactive_metadata_ids,
    ):
        """
        INFINITE SCROLL + PAGINATION CALLBACK WITH INTERACTIVE COMPONENT SUPPORT

        This callback handles ALL tables using infinite row model with pagination and includes:
        - Interactive component filtering via iterative_join
        - AG Grid server-side filtering and sorting
        - Pagination with configurable page sizes (50, 100, 200, 500 rows)
        - Cache invalidation when interactive values change

        Note: Dash AG Grid uses "infinite" rowModelType for server-side data loading with pagination
        """

        logger.info("🚀 TABLE INFINITE SCROLL + PAGINATION CALLBACK FIRED!")

        # CACHE INVALIDATION: Detect if triggered by interactive component changes
        triggered_by_interactive = ctx.triggered and any(
            "interactive-values-store" in str(trigger["prop_id"]) for trigger in ctx.triggered
        )

        logger.debug(f"🔄 Infinite scroll callback triggered - {ctx.triggered}")

        # Detailed analysis of interactive values
        if interactive_values and "interactive_components_values" in interactive_values:
            components_count = len(interactive_values["interactive_components_values"])
            logger.debug(f"🎯 Table: {components_count} interactive components detected")
        else:
            logger.debug("🎯 Table: No interactive values")

        # LOGGING: Track pagination requests and trigger source
        logger.debug(f"📊 Request: {request}")
        logger.debug(f"🎯 Triggered by: {ctx.triggered_id if ctx.triggered else 'Unknown'}")

        # Validate inputs
        if not local_store or not stored_metadata:
            logger.warning(
                "❌ Missing required data for infinite scroll - local_store or stored_metadata"
            )
            return no_update

        # Handle missing request (initial load or interactive changes)
        if request is None:
            if triggered_by_interactive:
                # Interactive component changed - always process immediately
                logger.info("🔄 Interactive component changed - processing data immediately")
            else:
                # Initial load - AG Grid hasn't sent first request yet
                logger.info("🆕 INITIAL LOAD: Creating synthetic request for first page")

            # Create a synthetic request for the first page
            request = {
                "startRow": 0,
                "endRow": 100,  # Standard first page size
                "filterModel": {},
                "sortModel": [],
            }
            logger.info("✅ Created synthetic request to load initial data")

        # Extract authentication token
        TOKEN = local_store["access_token"]

        # Extract table metadata
        workflow_id = stored_metadata["wf_id"]
        data_collection_id = stored_metadata["dc_id"]
        table_index = stored_metadata["index"]

        # LOGGING: Track data request parameters
        start_row = request.get("startRow", 0)
        end_row = request.get("endRow", 100)
        requested_rows = end_row - start_row
        filter_model = request.get("filterModel", {})
        sort_model = request.get("sortModel", [])

        # Detect page size from request
        page_size = end_row - start_row
        logger.info(f"📄 Page size: {page_size} rows (user selected or default)")

        logger.info(
            f"📈 Table {table_index}: Loading rows {start_row}-{end_row} ({requested_rows} rows)"
        )
        logger.info(
            f"🔍 Active filters: {len(filter_model)} filter(s) - {list(filter_model.keys()) if filter_model else 'none'}"
        )
        logger.info(
            f"🔤 Active sorts: {len(sort_model)} sort(s) - {[(s['colId'], s['sort']) for s in sort_model] if sort_model else 'none'}"
        )

        # NOTE: Interactive component enrichment is handled inside load_table_data_with_filters()
        # The helper function performs all necessary metadata enrichment, join calculations,
        # filtering, and sorting - ensuring consistency between infinite scroll and export

        try:
            # REFACTORED: Use centralized data loading helper function
            df = load_table_data_with_filters(
                workflow_id=workflow_id,
                data_collection_id=data_collection_id,
                stored_metadata=stored_metadata,
                interactive_values=interactive_values,
                interactive_metadata_list=interactive_metadata_list,
                interactive_metadata_ids=interactive_metadata_ids,
                filter_model=filter_model,
                sort_model=sort_model,
                TOKEN=TOKEN,
            )

            total_rows = df.shape[0]
            logger.info(
                f"📊 Final dataset after filters/sorting: {total_rows} rows, {df.shape[1]} columns"
            )

            # OLD LOGIC REMOVED - Now handled by load_table_data_with_filters():
            # - Interactive component compatibility checking
            # - Semi-join vs full join logic
            # - Data loading via load_deltatable_lite or iterative_join
            # - AG Grid filter application
            # - AG Grid sorting application
            # SLICE DATA: Extract the requested row range
            partial_df = df[start_row:end_row]
            actual_rows_returned = partial_df.shape[0]

            # Transform column names to replace dots with underscores for AgGrid compatibility
            # Do this BEFORE conversion to avoid schema issues
            if any("." in col for col in partial_df.columns):
                column_mapping = {
                    col: col.replace(".", "_") for col in partial_df.columns if "." in col
                }
                partial_df = partial_df.rename(column_mapping)
                logger.debug(
                    f"🔍 Renamed {len(column_mapping)} columns for AgGrid: {list(column_mapping.keys())}"
                )

            # Add ID field for row indexing
            partial_df = partial_df.with_columns(
                pl.Series("ID", range(start_row, start_row + len(partial_df)))
            )

            # Convert directly to dicts (AG Grid supports Polars natively - no Pandas conversion needed)
            # This avoids the Polars -> Pandas -> dict conversion chain and potential Arrow RecordBatch errors
            row_data = partial_df.to_dicts()
            logger.debug(f"✅ Converted {len(row_data)} rows to dicts using Polars native method")

            # LOGGING: Track successful data delivery
            logger.info(
                f"✅ Table {table_index}: Delivered {actual_rows_returned} rows ({start_row}-{start_row + actual_rows_returned})"
            )
            logger.info(f"📋 Response: {actual_rows_returned} rows from {total_rows} total")

            # Return data in format expected by dash-ag-grid infinite model
            response = {
                "rowData": row_data,
                "rowCount": total_rows,  # Total number of rows available
            }

            logger.info(
                f"🚀 INFINITE SCROLL + PAGINATION RESPONSE SENT - {actual_rows_returned}/{total_rows} rows"
            )

            # HYBRID SUCCESS: Log successful integration of interactive + pagination
            has_interactive_values = (
                interactive_values
                and "interactive_components_values" in interactive_values
                and len(interactive_values["interactive_components_values"]) > 0
            )

            if has_interactive_values:
                # Check if filtering actually reduced the dataset
                active_filters = [
                    (comp.get("index"), comp.get("value"))
                    for comp in interactive_values.get("interactive_components_values", [])
                    if comp.get("value") is not None
                ]
                logger.info(
                    f"🎯 HYBRID SUCCESS: Interactive + pagination delivered {actual_rows_returned}/{total_rows} rows"
                )
                logger.info(f"🎛️ Active interactive filters: {active_filters}")
                logger.info(
                    f"📊 Dataset after filtering: {total_rows} total rows available for pagination"
                )

                if active_filters:
                    logger.info(
                        f"✅ FILTERING CONFIRMED: {len(active_filters)} active filters reduced dataset"
                    )
                else:
                    logger.info(
                        "📭 NO ACTIVE FILTERS: Interactive components exist but no values set"
                    )
            else:
                logger.info(
                    f"📊 INFINITE SCROLL + PAGINATION: Standard pagination delivered {actual_rows_returned}/{total_rows} rows"
                )

            return response

        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"❌ Error in infinite scroll callback for table {table_index}: {error_msg}"
            )
            logger.error(f"🔧 Error details - wf_id: {workflow_id}, dc_id: {data_collection_id}")

            # Return empty response on error
            return {"rowData": [], "rowCount": 0}

    @app.callback(
        Output({"type": "download-table-csv", "index": MATCH}, "data"),
        Output({"type": "export-notification-container", "index": MATCH}, "children"),
        Input({"type": "export-table-button", "index": MATCH}, "n_clicks"),
        [
            State({"type": "stored-metadata-component", "index": MATCH}, "data"),
            State("interactive-values-store", "data"),
            State("local-store", "data"),
            State({"type": "table-aggrid", "index": MATCH}, "filterModel"),
            State({"type": "table-aggrid", "index": MATCH}, "sortModel"),
            State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
            State({"type": "interactive-stored-metadata", "index": ALL}, "id"),
        ],
        prevent_initial_call=True,
    )
    def export_table_to_csv(
        n_clicks,
        stored_metadata,
        interactive_values,
        local_store,
        filter_model,
        sort_model,
        interactive_metadata_list,
        interactive_metadata_ids,
    ):
        """
        Export complete table data as CSV with filters and sorting applied.

        Size Limits:
        - < 100k rows: Instant export
        - 100k - 1M rows: Warning logged, export allowed
        - > 1M rows: Error, export blocked (memory concern)

        Strategy:
        1. Call load_table_data_with_filters() to get complete dataset
        2. Check row count and show warning/error notifications if needed
        3. Convert to CSV in memory (never writes to disk)
        4. Return via dcc.Download (streams directly to browser)
        """
        import datetime

        import dash_mantine_components as dmc
        from dash_iconify import DashIconify

        logger.info("📥 CSV EXPORT: Export button clicked")

        if not n_clicks:
            return no_update, no_update

        # Validate inputs
        if not local_store or not stored_metadata:
            logger.error("❌ CSV EXPORT: Missing required data")
            error_notification = dmc.Notification(
                title="Export failed",
                message="Missing required authentication or metadata",
                color="red",
                icon=DashIconify(icon="mdi:alert-circle"),
                action="show",
            )
            return no_update, error_notification

        # Extract metadata
        TOKEN = local_store.get("access_token")
        workflow_id = stored_metadata.get("wf_id")
        data_collection_id = stored_metadata.get("dc_id")
        table_index = stored_metadata.get("index", "table")

        logger.info(
            f"📊 CSV EXPORT: Starting export for table {table_index} (wf: {workflow_id}, dc: {data_collection_id})"
        )

        try:
            # Load complete filtered/sorted dataset using helper function
            df = load_table_data_with_filters(
                workflow_id=workflow_id,
                data_collection_id=data_collection_id,
                stored_metadata=stored_metadata,
                interactive_values=interactive_values,
                interactive_metadata_list=interactive_metadata_list,
                interactive_metadata_ids=interactive_metadata_ids,
                filter_model=filter_model,
                sort_model=sort_model,
                TOKEN=TOKEN,
            )

            row_count = df.shape[0]
            col_count = df.shape[1]
            logger.info(f"📊 CSV EXPORT: Loaded {row_count:,} rows, {col_count} columns")

            # Check size limits
            MAX_EXPORT_ROWS = 1_000_000  # 1M row limit

            if row_count > MAX_EXPORT_ROWS:
                # Too large - block export
                logger.error(
                    f"❌ CSV EXPORT BLOCKED: Table too large ({row_count:,} rows > {MAX_EXPORT_ROWS:,} limit)"
                )
                notification_error = dmc.Notification(
                    title="Export blocked",
                    message=f"Table too large: {row_count:,} rows (limit: {MAX_EXPORT_ROWS:,})",
                    color="red",
                    icon=DashIconify(icon="mdi:alert-circle"),
                    action="show",
                    autoClose=10000,
                )
                return no_update, notification_error

            elif row_count > 100_000:
                # Large table - warn but allow
                logger.warning(f"⚠️ CSV EXPORT: Large export ({row_count:,} rows)")

            # Convert to CSV (in memory, never written to disk)
            csv_string = df.write_csv()
            csv_size_mb = len(csv_string) / (1024 * 1024)
            logger.info(f"💾 CSV EXPORT: Generated CSV ({csv_size_mb:.2f} MB)")

            # Generate filename
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"depictio_table_{table_index}_{timestamp}.csv"

            # Success notification
            notification_success = dmc.Notification(
                title="Export complete!",
                message=f"Downloaded {row_count:,} rows as CSV ({csv_size_mb:.1f} MB)",
                color="green",
                icon=DashIconify(icon="mdi:check-circle"),
                action="show",
                autoClose=5000,
            )

            logger.info(
                f"✅ CSV EXPORT SUCCESS: {filename} ({row_count:,} rows, {csv_size_mb:.2f} MB)"
            )

            # Return CSV download + notification
            return dict(content=csv_string, filename=filename), notification_success

        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ CSV EXPORT ERROR: {error_msg}")
            import traceback

            logger.error(f"❌ Traceback: {traceback.format_exc()}")

            # Error notification
            notification_error = dmc.Notification(
                title="Export failed",
                message=f"Error: {error_msg[:100]}",
                color="red",
                icon=DashIconify(icon="mdi:alert-circle"),
                action="show",
                autoClose=10000,
            )
            return no_update, notification_error

    core_logger.info(
        "✅ Table component core callbacks registered (theme + infinite scroll + pagination + export)"
    )
