"""Plotly Express keyword metadata: which kwargs name DataFrame columns.

Pure data, no Plotly import — so both the figure builder (scan-level column
projection) and the reuse column-contract extractor can share these sets without
dragging Plotly (and the whole figure-render stack) into a lightweight import.
"""

# Plotly Express keyword args whose value is a single DataFrame column name.
_PX_COLUMN_PARAMS: frozenset[str] = frozenset(
    {
        "x", "y", "z", "color", "size", "symbol", "line_dash", "line_group",
        "pattern_shape", "hover_name", "names", "values", "facet_col", "facet_row",
        "animation_frame", "animation_group", "base", "r", "theta", "a", "b", "c",
        "error_x", "error_y", "error_z",
    }
)  # fmt: skip

# Plotly Express keyword args whose value is a list (or ``{col: bool}`` dict) of
# column names.
_PX_COLUMN_LIST_PARAMS: frozenset[str] = frozenset({"hover_data", "custom_data", "dimensions"})

# Visualisations that read the whole frame (or a column set we can't reliably
# enumerate from dict_kwargs): projecting them risks dropping needed columns, so
# signal a full load instead.
_WHOLE_FRAME_VISU: frozenset[str] = frozenset(
    {
        "heatmap", "scatter_matrix", "parallel_coordinates",
        "parallel_categories", "imshow", "scatter_geo", "choropleth",
    }
)  # fmt: skip
