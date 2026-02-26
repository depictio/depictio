"""
Table Component Core Callbacks

View mode callbacks for table component:
- Theme switching for AG Grid
- Infinite scroll with filtering, sorting, and interactive component integration
"""

from typing import Any

import polars as pl
from bson import ObjectId
from dash import ALL, MATCH, Input, Output, State, ctx, no_update

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.dash.utils import extend_filters_via_links, get_result_dc_for_workflow

# AG Grid filter operators mapping to Polars operations
OPERATORS = {
    "greaterThanOrEqual": "ge",
    "lessThanOrEqual": "le",
    "lessThan": "lt",
    "greaterThan": "gt",
    "notEqual": "ne",
    "equals": "eq",
}


def build_interactive_metadata_mapping(
    interactive_metadata_list: list[dict[str, Any]] | None,
    interactive_metadata_ids: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """
    Build a mapping from component index to full metadata.

    This function creates a lookup dictionary that maps interactive component
    indices to their complete metadata, enabling efficient metadata retrieval
    during component enrichment.

    Args:
        interactive_metadata_list: List of metadata dictionaries from State callbacks,
            containing full component configuration (dc_id, column_name, etc.)
        interactive_metadata_ids: List of component ID dictionaries from State callbacks,
            containing the 'index' field used as the mapping key

    Returns:
        Dictionary mapping component index strings to their full metadata dictionaries.
        Empty dictionary if either input is None or empty.

    Example:
        >>> metadata_list = [{"dc_id": "123", "column_name": "status"}]
        >>> metadata_ids = [{"index": "comp-1", "type": "interactive-stored-metadata"}]
        >>> mapping = build_interactive_metadata_mapping(metadata_list, metadata_ids)
        >>> mapping["comp-1"]
        {"dc_id": "123", "column_name": "status"}
    """
    metadata_by_index: dict[str, dict[str, Any]] = {}

    if not interactive_metadata_list or not interactive_metadata_ids:
        return metadata_by_index

    for i, meta_id in enumerate(interactive_metadata_ids):
        if i < len(interactive_metadata_list):
            index = meta_id["index"]
            metadata_by_index[index] = interactive_metadata_list[i]

    return metadata_by_index


def enrich_interactive_components(
    interactive_values: dict[str, Any] | None,
    metadata_by_index: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    Enrich lightweight component data from store with full metadata.

    The interactive values store contains only lightweight data (index + value).
    This function enriches each component with full metadata from the State
    callbacks, enabling proper filtering and join operations.

    Handles both regular interactive components (metadata from stores) and
    selection sources (scatter_selection, table_selection) which have metadata
    embedded in the store entry itself.

    Args:
        interactive_values: Store data containing 'interactive_components_values' list,
            where each item has 'index' and 'value' fields
        metadata_by_index: Mapping from component index to full metadata,
            built by build_interactive_metadata_mapping()

    Returns:
        Dictionary mapping component index to enriched component data containing:
        - index: Component identifier
        - value: Current filter value
        - component_type: Always "interactive"
        - metadata: Full component metadata (dc_id, column_name, etc.)

    Note:
        Components without matching metadata are skipped with a warning logged.
    """
    interactive_components_dict: dict[str, dict[str, Any]] = {}

    lightweight_components = (
        interactive_values.get("interactive_components_values", []) if interactive_values else []
    )

    for component in lightweight_components:
        index = component.get("index")
        value = component.get("value")
        source = component.get("source")

        if not index:
            continue

        # Handle selection sources (scatter_selection, table_selection)
        # These have metadata embedded directly in the store entry
        if source in ("scatter_selection", "table_selection", "map_selection"):
            selection_metadata = {
                "dc_id": component.get("dc_id"),
                "column_name": component.get("column_name"),
                "interactive_component_type": "MultiSelect",
                "source": source,
            }
            enriched_component = {
                "index": index,
                "value": value,
                "component_type": "interactive",
                "metadata": selection_metadata,
                "source": source,
            }
            interactive_components_dict[index] = enriched_component
        else:
            # Regular interactive components need metadata lookup
            full_metadata = metadata_by_index.get(index)

            if full_metadata:
                # Special handling for DateRangePicker values
                if full_metadata.get("interactive_component_type") == "DateRangePicker":
                    # Ensure value is a list of 2 string dates
                    if value and not isinstance(value, list):
                        value = [value]
                    if value and len(value) == 2:
                        # Skip if either value is None (incomplete selection)
                        if value[0] is None or value[1] is None:
                            continue  # Skip this component entirely - don't add to dict
                        else:
                            # Normalize to strings in YYYY-MM-DD format
                            normalized_value = []
                            for v in value:
                                # Handle ISO datetime strings (e.g., "2023-01-01T00:00:00")
                                if isinstance(v, str) and "T" in v:
                                    normalized_value.append(v.split("T")[0])
                                else:
                                    normalized_value.append(str(v))
                            value = normalized_value

                enriched_component = {
                    "index": index,
                    "value": value,
                    "component_type": "interactive",
                    "metadata": full_metadata,
                }
                interactive_components_dict[index] = enriched_component
            else:
                logger.warning(f"Component {index} has value but no metadata - skipping")

    return interactive_components_dict


def prepare_metadata_for_join(
    stored_metadata: dict[str, Any],
    interactive_components_dict: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Prepare metadata list for iterative join operations.

    Creates a list of metadata dictionaries that includes the table component
    and all interactive components, with component_type annotations for
    proper join calculation.

    Args:
        stored_metadata: Table component metadata containing wf_id, dc_id, etc.
        interactive_components_dict: Enriched interactive components from
            enrich_interactive_components()

    Returns:
        List of metadata dictionaries, each with 'component_type' field set.
        Always includes table metadata first, followed by interactive components.
    """
    stored_metadata_for_join: list[dict[str, Any]] = []

    table_metadata = dict(stored_metadata)
    table_metadata["component_type"] = "table"
    stored_metadata_for_join.append(table_metadata)

    if interactive_components_dict:
        for component_index, component_data in interactive_components_dict.items():
            if component_data.get("metadata"):
                interactive_meta = dict(component_data["metadata"])
                interactive_meta["component_type"] = "interactive"
                stored_metadata_for_join.append(interactive_meta)

    return stored_metadata_for_join


def load_data_with_interactive_filters(
    workflow_id: str,
    data_collection_id: str,
    stored_metadata: dict[str, Any],
    interactive_components_dict: dict[str, dict[str, Any]],
    TOKEN: str | None,
    project_metadata: dict | None = None,
) -> pl.DataFrame:
    """
    Load data from delta tables with interactive component filters applied.

    Handles the complex logic of determining whether interactive components
    target the same data collection as the table, and loads data accordingly
    using pre-computed joins when available.

    Args:
        workflow_id: Workflow identifier for data loading
        data_collection_id: Data collection identifier for the table
        stored_metadata: Table component metadata
        interactive_components_dict: Enriched interactive components with filters
        TOKEN: Authentication token for API calls

    Returns:
        Polars DataFrame with interactive filters applied where applicable.

    Note:
        Falls back to unfiltered data if filter application fails.
    """
    if not interactive_components_dict:
        return _load_data_without_interactive_filters(workflow_id, data_collection_id, TOKEN)

    table_dc_id = stored_metadata.get("dc_id")

    # Separate interactive components by DC: same-DC filters apply directly,
    # different-DC filters need link resolution
    same_dc_components = {}
    different_dc_components = {}

    for idx, comp_data in interactive_components_dict.items():
        comp_dc = comp_data.get("metadata", {}).get("dc_id")
        if comp_dc == table_dc_id:
            same_dc_components[idx] = comp_data
        else:
            different_dc_components[idx] = comp_data

    if different_dc_components == {} and same_dc_components:
        result_dc_id = get_result_dc_for_workflow(workflow_id, TOKEN)
        return _load_compatible_dc_data(
            workflow_id, data_collection_id, result_dc_id, same_dc_components, TOKEN
        )

    if same_dc_components == {} and different_dc_components:
        return _load_with_link_resolution_only(
            workflow_id,
            data_collection_id,
            table_dc_id,
            different_dc_components,
            project_metadata,
            TOKEN,
        )

    if same_dc_components and different_dc_components:
        return _load_with_mixed_dc_filters(
            workflow_id,
            data_collection_id,
            table_dc_id,
            same_dc_components,
            different_dc_components,
            project_metadata,
            TOKEN,
        )

    return _load_data_without_interactive_filters(workflow_id, data_collection_id, TOKEN)


def _load_with_link_resolution_only(
    workflow_id: str,
    data_collection_id: str,
    table_dc_id: str,
    different_dc_components: dict[str, dict[str, Any]],
    project_metadata: dict | None,
    TOKEN: str | None,
) -> pl.DataFrame:
    """
    Load data when ALL interactive components are on different DCs than the table.

    Uses link resolution to translate filters from source DCs to the table's DC.

    Args:
        workflow_id: Workflow identifier
        data_collection_id: Data collection identifier
        table_dc_id: Table's data collection ID
        different_dc_components: Components from different DCs
        project_metadata: Project metadata for link resolution
        TOKEN: Authentication token

    Returns:
        DataFrame with link-resolved filters applied.
    """
    logger.info(
        "DC INCOMPATIBLE: All interactive filters target different DCs. Attempting link resolution."
    )

    # Group filters by DC
    filters_by_dc: dict[str, list[dict]] = {}
    for comp_data in different_dc_components.values():
        comp_dc = str(comp_data.get("metadata", {}).get("dc_id", ""))
        if comp_dc:
            if comp_dc not in filters_by_dc:
                filters_by_dc[comp_dc] = []
            enriched_comp = {
                "value": comp_data.get("value"),
                "metadata": comp_data.get("metadata", {}),
            }
            filters_by_dc[comp_dc].append(enriched_comp)

    # Resolve filters via links
    link_resolved_filters = extend_filters_via_links(
        target_dc_id=table_dc_id,
        filters_by_dc=filters_by_dc,
        project_metadata=project_metadata,
        access_token=TOKEN,
        component_type="table",
    )

    if link_resolved_filters:
        logger.info(
            f"Link resolution successful: {len(link_resolved_filters)} filters resolved for table."
        )
        df = load_deltatable_lite(
            ObjectId(workflow_id),
            ObjectId(data_collection_id),
            metadata=link_resolved_filters,
            TOKEN=TOKEN,
        )
    else:
        logger.warning("Link resolution failed or returned no filters. Loading unfiltered data.")
        df = load_deltatable_lite(
            ObjectId(workflow_id), ObjectId(data_collection_id), metadata=None, TOKEN=TOKEN
        )
    return df


def _load_with_mixed_dc_filters(
    workflow_id: str,
    data_collection_id: str,
    table_dc_id: str,
    same_dc_components: dict[str, dict[str, Any]],
    different_dc_components: dict[str, dict[str, Any]],
    project_metadata: dict | None,
    TOKEN: str | None,
) -> pl.DataFrame:
    """
    Load data when interactive components come from BOTH same and different DCs.

    Combines direct filters (same DC) with link-resolved filters (different DCs).

    Args:
        workflow_id: Workflow identifier
        data_collection_id: Data collection identifier
        table_dc_id: Table's data collection ID
        same_dc_components: Components on the same DC as table
        different_dc_components: Components on different DCs
        project_metadata: Project metadata for link resolution
        TOKEN: Authentication token

    Returns:
        DataFrame with combined filters applied.
    """
    logger.info(
        f"MIXED DCs: {len(same_dc_components)} same-DC filters, "
        f"{len(different_dc_components)} different-DC filters"
    )

    filters_by_dc: dict[str, list[dict]] = {}
    for comp_data in different_dc_components.values():
        comp_dc = str(comp_data.get("metadata", {}).get("dc_id", ""))
        if comp_dc:
            if comp_dc not in filters_by_dc:
                filters_by_dc[comp_dc] = []
            enriched_comp = {
                "value": comp_data.get("value"),
                "metadata": comp_data.get("metadata", {}),
            }
            filters_by_dc[comp_dc].append(enriched_comp)

    link_resolved_filters = extend_filters_via_links(
        target_dc_id=table_dc_id,
        filters_by_dc=filters_by_dc,
        project_metadata=project_metadata,
        access_token=TOKEN,
        component_type="table",
    )

    combined_filters = list(same_dc_components.values())
    if link_resolved_filters:
        combined_filters.extend(link_resolved_filters)
    else:
        logger.warning("Link resolution failed for different-DC components, using same-DC only")

    df = load_deltatable_lite(
        ObjectId(workflow_id),
        ObjectId(data_collection_id),
        metadata=combined_filters,
        TOKEN=TOKEN,
    )
    return df


def _load_compatible_dc_data(
    workflow_id: str,
    data_collection_id: str,
    result_dc_id: str | None,
    interactive_components_dict: dict[str, dict[str, Any]],
    TOKEN: str | None,
) -> pl.DataFrame:
    """
    Load data when interactive components target compatible data collections.

    Uses pre-computed joins when available, otherwise loads single DC with filters.

    Args:
        workflow_id: Workflow identifier
        data_collection_id: Data collection identifier
        result_dc_id: Pre-computed join result DC ID (if available)
        interactive_components_dict: Enriched interactive components
        TOKEN: Authentication token

    Returns:
        Filtered DataFrame from compatible data collection.
    """
    try:
        if result_dc_id:
            df = load_deltatable_lite(
                ObjectId(workflow_id),
                ObjectId(result_dc_id),
                metadata=list(interactive_components_dict.values()),
                TOKEN=TOKEN,
            )
        else:
            df = load_deltatable_lite(
                ObjectId(workflow_id),
                ObjectId(data_collection_id),
                metadata=list(interactive_components_dict.values()),
                TOKEN=TOKEN,
            )
        return df
    except Exception as interactive_error:
        logger.error(f"Loading data failed: {str(interactive_error)}")
        df = load_deltatable_lite(
            ObjectId(workflow_id), ObjectId(data_collection_id), metadata=None, TOKEN=TOKEN
        )
        return df


def _load_data_without_interactive_filters(
    workflow_id: str,
    data_collection_id: str,
    TOKEN: str | None,
) -> pl.DataFrame:
    """
    Load data when no interactive component filters are active.

    Checks for pre-computed joins and loads from the appropriate source.

    Args:
        workflow_id: Workflow identifier
        data_collection_id: Data collection identifier
        TOKEN: Authentication token

    Returns:
        DataFrame loaded from delta table (joined or single DC).
    """
    try:
        result_dc_id = get_result_dc_for_workflow(workflow_id, TOKEN)

        if result_dc_id:
            df = load_deltatable_lite(
                ObjectId(workflow_id), ObjectId(result_dc_id), metadata=None, TOKEN=TOKEN
            )
        else:
            df = load_deltatable_lite(
                ObjectId(workflow_id), ObjectId(data_collection_id), metadata=None, TOKEN=TOKEN
            )
        return df
    except Exception as join_error:
        logger.warning(f"Error checking table joins: {str(join_error)}")
        df = load_deltatable_lite(
            ObjectId(workflow_id), ObjectId(data_collection_id), metadata=None, TOKEN=TOKEN
        )
        return df


def apply_ag_grid_filters(df: pl.DataFrame, filter_model: dict[str, Any]) -> pl.DataFrame:
    """
    Apply all AG Grid filters from the filter model to a DataFrame.

    Handles both simple filters and complex filters with AND/OR operators.
    Logs warnings for filters that fail to apply but continues processing.

    Args:
        df: Input Polars DataFrame to filter
        filter_model: AG Grid filter model dictionary mapping column names
            to filter definitions

    Returns:
        Filtered DataFrame with all applicable filters applied.

    Note:
        Complex filters with 'operator' field are handled specially:
        - AND: Both conditions must match
        - OR: Either condition matches (using concat + unique)
    """
    if not filter_model:
        return df

    for col, filter_def in filter_model.items():
        try:
            if "operator" in filter_def:
                if filter_def["operator"] == "AND":
                    df = apply_ag_grid_filter(df, filter_def["condition1"], col)
                    df = apply_ag_grid_filter(df, filter_def["condition2"], col)
                else:
                    df1 = apply_ag_grid_filter(df, filter_def["condition1"], col)
                    df2 = apply_ag_grid_filter(df, filter_def["condition2"], col)
                    df = pl.concat([df1, df2]).unique()
            else:
                df = apply_ag_grid_filter(df, filter_def, col)
        except Exception as e:
            logger.warning(f"Failed to apply filter for column {col}: {e}")
            continue

    return df


def create_synthetic_request(triggered_by_interactive: bool) -> dict[str, Any]:
    """
    Create a synthetic AG Grid request for initial data loading.

    Used when AG Grid hasn't sent its first request yet (initial load)
    or when interactive components change and need immediate processing.

    Args:
        triggered_by_interactive: Whether the callback was triggered by
            an interactive component change

    Returns:
        Synthetic request dictionary with default pagination parameters:
        - startRow: 0
        - endRow: 100 (standard first page size)
        - filterModel: empty
        - sortModel: empty
    """
    request = {
        "startRow": 0,
        "endRow": 100,
        "filterModel": {},
        "sortModel": [],
    }
    return request


def prepare_dataframe_for_aggrid(
    df: pl.DataFrame,
    start_row: int,
    end_row: int,
) -> tuple[pl.DataFrame, int]:
    """
    Prepare a DataFrame slice for AG Grid consumption.

    Performs the following transformations:
    1. Slices the DataFrame to the requested row range
    2. Renames columns containing dots (not supported by AG Grid)
    3. Adds an ID column for row indexing

    Args:
        df: Full filtered/sorted DataFrame
        start_row: Starting row index (inclusive)
        end_row: Ending row index (exclusive)

    Returns:
        Tuple of (prepared DataFrame slice, total row count).
    """
    total_rows = df.shape[0]
    partial_df = df[start_row:end_row]

    if any("." in col for col in partial_df.columns):
        column_mapping = {col: col.replace(".", "_") for col in partial_df.columns if "." in col}
        partial_df = partial_df.rename(column_mapping)

    partial_df = partial_df.with_columns(
        pl.Series("ID", range(start_row, start_row + len(partial_df)))
    )

    return partial_df, total_rows


def build_aggrid_response(
    partial_df: pl.DataFrame,
    total_rows: int,
    start_row: int,
    table_index: str,
) -> dict[str, Any]:
    """
    Build the response dictionary for AG Grid infinite row model.

    Args:
        partial_df: Prepared DataFrame slice for the current page
        total_rows: Total number of rows available (for pagination)
        start_row: Starting row index of this page
        table_index: Table component index for logging

    Returns:
        Response dictionary with 'rowData' (list of row dicts) and
        'rowCount' (total available rows).
    """
    row_data = partial_df.to_dicts()
    return {"rowData": row_data, "rowCount": total_rows}


def create_export_notification(
    notification_type: str,
    message: str,
    row_count: int | None = None,
    csv_size_mb: float | None = None,
) -> Any:
    """
    Create a DMC notification for export operations.

    Args:
        notification_type: One of "success", "error", or "blocked"
        message: Message to display in the notification
        row_count: Number of rows exported (for success notifications)
        csv_size_mb: Size of CSV in MB (for success notifications)

    Returns:
        dmc.Notification component configured for the specified type.
    """
    import dash_mantine_components as dmc
    from dash_iconify import DashIconify

    if notification_type == "success":
        return dmc.Notification(
            title="Export complete!",
            message=f"Downloaded {row_count:,} rows as CSV ({csv_size_mb:.1f} MB)",
            color="green",
            icon=DashIconify(icon="mdi:check-circle"),
            action="show",
            autoClose=5000,
        )
    elif notification_type == "blocked":
        return dmc.Notification(
            title="Export blocked",
            message=message,
            color="red",
            icon=DashIconify(icon="mdi:alert-circle"),
            action="show",
            autoClose=10000,
        )
    else:
        return dmc.Notification(
            title="Export failed",
            message=message,
            color="red",
            icon=DashIconify(icon="mdi:alert-circle"),
            action="show",
            autoClose=10000,
        )


def check_export_size_limit(row_count: int, max_rows: int = 1_000_000) -> tuple[bool, str | None]:
    """
    Check if the export size is within acceptable limits.

    Args:
        row_count: Number of rows to export
        max_rows: Maximum allowed rows (default 1 million)

    Returns:
        Tuple of (is_allowed, error_message).
        is_allowed is True if export should proceed.
        error_message is set only when export is blocked.
    """
    if row_count > max_rows:
        logger.error(
            f"CSV EXPORT BLOCKED: Table too large ({row_count:,} rows > {max_rows:,} limit)"
        )
        return False, f"Table too large: {row_count:,} rows (limit: {max_rows:,})"

    if row_count > 100_000:
        logger.warning(f"CSV EXPORT: Large export ({row_count:,} rows)")

    return True, None


def generate_csv_download(
    df: pl.DataFrame,
    table_index: str,
) -> tuple[str, str, float]:
    """
    Generate CSV content and filename for download.

    Args:
        df: DataFrame to export
        table_index: Table component index for filename

    Returns:
        Tuple of (csv_string, filename, size_in_mb).
    """
    import datetime

    csv_string = df.write_csv()
    csv_size_mb = len(csv_string) / (1024 * 1024)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"depictio_table_{table_index}_{timestamp}.csv"

    return csv_string, filename, csv_size_mb


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
    stored_metadata: dict[str, Any],
    interactive_values: dict[str, Any] | None,
    interactive_metadata_list: list[dict[str, Any]],
    interactive_metadata_ids: list[dict[str, Any]],
    filter_model: dict[str, Any] | None = None,
    sort_model: list[dict[str, Any]] | None = None,
    TOKEN: str | None = None,
    project_metadata: dict | None = None,
) -> pl.DataFrame:
    """
    Load table data with interactive filters, AG Grid filters, and sorting applied.

    This function centralizes data loading logic used by both:
    - infinite_scroll_component (with pagination)
    - export_table_to_csv (complete dataset)

    The function performs three main steps:
    1. Enrich interactive components with full metadata from State callbacks
    2. Load data from delta tables with interactive filters applied
    3. Apply AG Grid filters and sorting

    Args:
        workflow_id: Workflow ID for data loading
        data_collection_id: Data collection ID for the table
        stored_metadata: Table component metadata containing wf_id, dc_id, etc.
        interactive_values: Interactive component filter values from store
        interactive_metadata_list: List of interactive component metadata from State
        interactive_metadata_ids: List of interactive component IDs from State
        filter_model: AG Grid filter model dictionary
        sort_model: AG Grid sort model list
        TOKEN: Authentication token for API calls

    Returns:
        Filtered and sorted Polars DataFrame ready for display or export.
    """

    metadata_by_index = build_interactive_metadata_mapping(
        interactive_metadata_list, interactive_metadata_ids
    )
    interactive_components_dict = enrich_interactive_components(
        interactive_values, metadata_by_index
    )

    prepare_metadata_for_join(stored_metadata, interactive_components_dict)

    df = load_data_with_interactive_filters(
        workflow_id,
        data_collection_id,
        stored_metadata,
        interactive_components_dict,
        TOKEN,
        project_metadata,
    )

    if filter_model:
        df = apply_ag_grid_filters(df, filter_model)

    if sort_model:
        df = apply_ag_grid_sorting(df, sort_model)

    return df


def register_core_callbacks(app):
    """Register core view mode callbacks for table component."""

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
            State("project-metadata-store", "data"),
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
        project_metadata,
    ):
        """
        Handle infinite scroll pagination with interactive component support.

        This callback handles ALL tables using infinite row model with pagination and includes:
        - Interactive component filtering via iterative_join
        - AG Grid server-side filtering and sorting
        - Pagination with configurable page sizes (50, 100, 200, 500 rows)
        - Cache invalidation when interactive values change

        Note: Dash AG Grid uses "infinite" rowModelType for server-side data loading with pagination.
        """

        # Detect if triggered by interactive component changes
        triggered_by_interactive = ctx.triggered and any(
            "interactive-values-store" in str(trigger["prop_id"]) for trigger in ctx.triggered
        )

        # Validate inputs
        if not local_store or not stored_metadata:
            logger.warning(
                "Missing required data for infinite scroll - local_store or stored_metadata"
            )
            return no_update

        # Create synthetic request for both initial load and interactive changes
        # AG Grid infinite model needs getRowsResponse even when we trigger it
        if request is None:
            request = create_synthetic_request(triggered_by_interactive)

        # Extract parameters
        TOKEN = local_store["access_token"]
        workflow_id = stored_metadata["wf_id"]
        data_collection_id = stored_metadata["dc_id"]
        table_index = stored_metadata["index"]

        start_row = request.get("startRow", 0)
        end_row = request.get("endRow", 100)
        filter_model = request.get("filterModel", {})
        sort_model = request.get("sortModel", [])

        try:
            # Load filtered and sorted data
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
                project_metadata=project_metadata,
            )

            # Prepare DataFrame slice for AG Grid
            partial_df, total_rows = prepare_dataframe_for_aggrid(df, start_row, end_row)

            # Build and return response
            response = build_aggrid_response(partial_df, total_rows, start_row, table_index)
            return response

        except Exception as e:
            logger.error(
                f"Infinite scroll error for table {table_index}: {e} "
                f"(wf_id={workflow_id}, dc_id={data_collection_id})"
            )

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
            State("project-metadata-store", "data"),
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
        project_metadata,
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
        if not n_clicks:
            return no_update, no_update

        # Validate inputs
        if not local_store or not stored_metadata:
            logger.error("CSV EXPORT: Missing required data")
            return no_update, create_export_notification(
                "error", "Missing required authentication or metadata"
            )

        # Extract metadata
        TOKEN = local_store.get("access_token")
        workflow_id = stored_metadata.get("wf_id")
        data_collection_id = stored_metadata.get("dc_id")
        table_index = stored_metadata.get("index", "table")

        try:
            # Load complete filtered/sorted dataset
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
                project_metadata=project_metadata,
            )

            row_count = df.shape[0]

            # Check size limits
            is_allowed, error_message = check_export_size_limit(row_count)
            if not is_allowed:
                return no_update, create_export_notification("blocked", error_message or "")

            # Generate CSV and filename
            csv_string, filename, csv_size_mb = generate_csv_download(df, table_index)

            return (
                dict(content=csv_string, filename=filename),
                create_export_notification("success", "", row_count, csv_size_mb),
            )

        except Exception as e:
            import traceback

            error_msg = str(e)
            logger.error(f"CSV EXPORT ERROR: {error_msg}")
            logger.error(f"Traceback: {traceback.format_exc()}")

            return no_update, create_export_notification("error", f"Error: {error_msg[:100]}")
