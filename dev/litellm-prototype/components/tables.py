"""AG Grid data table component."""

from __future__ import annotations

import dash_ag_grid as dag
import dash_mantine_components as dmc
import pandas as pd


def _column_defs(df: pd.DataFrame) -> list[dict]:
    """Auto-generate AG Grid column definitions from DataFrame dtypes."""
    defs = []
    for col in df.columns:
        col_def: dict = {
            "field": col,
            "headerName": col.replace("_", " ").title(),
            "sortable": True,
            "filter": True,
            "resizable": True,
            "floatingFilter": True,
        }
        if pd.api.types.is_numeric_dtype(df[col]):
            col_def["filter"] = "agNumberColumnFilter"
        else:
            col_def["filter"] = "agTextColumnFilter"
        defs.append(col_def)
    return defs


def create_table(df: pd.DataFrame, table_id: str = "data-table") -> dmc.Paper:
    """Create an AG Grid table from a DataFrame.

    Args:
        df: Source DataFrame.
        table_id: Dash component ID.
    """
    return dmc.Paper(
        dag.AgGrid(
            id=table_id,
            rowData=df.to_dict("records"),
            columnDefs=_column_defs(df),
            defaultColDef={
                "flex": 1,
                "minWidth": 120,
                "sortable": True,
                "resizable": True,
                "floatingFilter": True,
                "filter": True,
            },
            dashGridOptions={
                "pagination": True,
                "paginationPageSize": 50,
                "paginationPageSizeSelector": [25, 50, 100],
                "rowSelection": "multiple",
                "enableCellTextSelection": True,
                "animateRows": True,
            },
            style={"height": "400px", "width": "100%"},
            className="ag-theme-alpine",
        ),
        withBorder=True,
        radius="md",
        p="xs",
        style={"overflow": "hidden"},
    )
