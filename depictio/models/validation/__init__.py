"""
Component Validation Module.

Provides Pydantic models and validators for validating dashboard component
configurations against their respective library schemas.

Modules:
    ag_grid: Dash AG Grid column definition validation
    plotly_express: Plotly Express parameter validation
    dash_mantine: Dash Mantine Components validation
"""

from depictio.models.validation.ag_grid import (
    AGGridColumnConfig,
    AGGridColumnDef,
    AGGridFilterParams,
    AGGridFilterType,
    ColsJson,
    cols_json_to_column_defs,
    validate_ag_grid_column_defs,
    validate_cols_json,
)
from depictio.models.validation.dash_mantine import (
    SUPPORTED_INTERACTIVE_TYPES,
    get_recommended_component,
    validate_interactive_component,
)
from depictio.models.validation.plotly_express import (
    SUPPORTED_CHART_TYPES,
    get_common_parameters,
    get_px_parameters,
    validate_dict_kwargs,
    validate_figure_component,
)

__all__ = [
    # AG Grid validation
    "AGGridFilterType",
    "AGGridFilterParams",
    "AGGridColumnConfig",
    "AGGridColumnDef",
    "ColsJson",
    "validate_cols_json",
    "validate_ag_grid_column_defs",
    "cols_json_to_column_defs",
    # Plotly Express validation
    "SUPPORTED_CHART_TYPES",
    "get_px_parameters",
    "get_common_parameters",
    "validate_dict_kwargs",
    "validate_figure_component",
    # Dash Mantine validation
    "SUPPORTED_INTERACTIVE_TYPES",
    "validate_interactive_component",
    "get_recommended_component",
]
