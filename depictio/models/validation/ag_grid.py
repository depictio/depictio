"""
Dash AG Grid Column Definition Validation.

Provides Pydantic models for validating AG Grid column configurations used in
depictio table components. Supports both the internal `cols_json` format and
the AG Grid `columnDefs` format.

Usage:
    from depictio.models.validation.ag_grid import (
        validate_cols_json,
        validate_ag_grid_column_defs,
        ColsJson,
        AGGridColumnDef,
    )

    # Validate cols_json (internal format)
    cols_json = {"sample": {"type": "object", "filter": "agTextColumnFilter"}}
    validated = validate_cols_json(cols_json)

    # Validate AG Grid columnDefs
    column_defs = [{"field": "sample", "headerName": "Sample"}]
    validated = validate_ag_grid_column_defs(column_defs)
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# AG Grid filter types
AGGridFilterType = Literal[
    "agTextColumnFilter",
    "agNumberColumnFilter",
    "agDateColumnFilter",
    "agSetColumnFilter",
]

# Column data types (polars/pandas types)
ColumnDataType = Literal[
    "object",
    "string",
    "int64",
    "int32",
    "float64",
    "float32",
    "bool",
    "datetime",
    "date",
    "timedelta",
    "category",
]

# AG Grid number filter options
NumberFilterOption = Literal[
    "equals",
    "notEqual",
    "lessThan",
    "lessThanOrEqual",
    "greaterThan",
    "greaterThanOrEqual",
    "inRange",
    "blank",
    "notBlank",
]

# AG Grid text filter options
TextFilterOption = Literal[
    "equals",
    "notEqual",
    "contains",
    "notContains",
    "startsWith",
    "endsWith",
    "blank",
    "notBlank",
]


class AGGridFilterParams(BaseModel):
    """AG Grid filter parameters configuration.

    Used to customize filter behavior for columns.
    """

    model_config = ConfigDict(extra="allow")

    # Number filter options
    filterOptions: list[NumberFilterOption | TextFilterOption] | None = None
    maxNumConditions: int | None = Field(default=None, ge=1, le=10)

    # Text filter options
    caseSensitive: bool | None = None
    textMatcher: str | None = None  # Custom text matcher function name

    # Set filter options
    values: list[Any] | None = None  # Predefined filter values
    suppressMiniFilter: bool | None = None

    # Date filter options
    comparator: str | None = None  # Custom date comparator function name

    # General options
    debounceMs: int | None = Field(default=None, ge=0, le=5000)
    buttons: list[Literal["apply", "clear", "reset", "cancel"]] | None = None
    closeOnApply: bool | None = None


class AGGridColumnConfig(BaseModel):
    """Column configuration in the internal cols_json format.

    This is the format stored in dashboard metadata before being converted
    to AG Grid columnDefs.

    Example:
        {
            "type": "object",
            "description": "Sample identifier",
            "filter": "agTextColumnFilter",
            "floatingFilter": true
        }
    """

    model_config = ConfigDict(extra="allow")

    # Data type (required for proper filter selection)
    type: ColumnDataType | str

    # Optional metadata
    description: str | None = None

    # Filter configuration
    filter: AGGridFilterType | str | None = None
    floatingFilter: bool = False
    filterParams: AGGridFilterParams | dict[str, Any] | None = None

    # Column statistics (optional, may be populated from data)
    specs: dict[str, Any] | None = Field(
        default=None, description="Column statistics (min, max, unique, etc.)"
    )

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, v: str) -> str:
        """Normalize column type names."""
        type_mapping = {
            "str": "object",
            "string": "object",
            "int": "int64",
            "integer": "int64",
            "float": "float64",
            "double": "float64",
            "boolean": "bool",
            "timestamp": "datetime",
        }
        return type_mapping.get(v, v)

    @model_validator(mode="after")
    def set_default_filter(self) -> "AGGridColumnConfig":
        """Set default filter based on column type if not specified."""
        if self.filter is None:
            type_to_filter = {
                "object": "agTextColumnFilter",
                "string": "agTextColumnFilter",
                "int64": "agNumberColumnFilter",
                "int32": "agNumberColumnFilter",
                "float64": "agNumberColumnFilter",
                "float32": "agNumberColumnFilter",
                "bool": "agTextColumnFilter",
                "datetime": "agDateColumnFilter",
                "date": "agDateColumnFilter",
            }
            self.filter = type_to_filter.get(self.type, "agTextColumnFilter")
        return self


class AGGridColumnDef(BaseModel):
    """AG Grid column definition.

    This is the format passed directly to dag.AgGrid columnDefs parameter.

    Reference: https://www.ag-grid.com/javascript-data-grid/column-definitions/
    """

    model_config = ConfigDict(extra="allow")

    # Required field
    field: str = Field(..., description="Data field name to display")

    # Display
    headerName: str | None = Field(default=None, description="Column header text")
    headerTooltip: str | None = Field(default=None, description="Tooltip on header hover")

    # Sizing
    width: int | None = Field(default=None, ge=30, le=2000)
    minWidth: int | None = Field(default=None, ge=30, le=2000)
    maxWidth: int | None = Field(default=None, ge=30, le=2000)
    flex: int | None = Field(default=None, ge=0, le=10)

    # Behavior
    sortable: bool = True
    resizable: bool = True
    editable: bool = False
    suppressMenu: bool = False
    lockPosition: bool = False
    lockVisible: bool = False

    # Filtering
    filter: AGGridFilterType | str | bool | None = None
    floatingFilter: bool = False
    filterParams: AGGridFilterParams | dict[str, Any] | None = None

    # Rendering
    cellStyle: dict[str, Any] | None = None
    cellClass: str | list[str] | None = None
    cellRenderer: str | None = None
    valueFormatter: str | None = None

    # Selection
    checkboxSelection: bool = False
    headerCheckboxSelection: bool = False

    # Pinning
    pinned: Literal["left", "right"] | None = None
    lockPinned: bool = False

    # Grouping
    rowGroup: bool = False
    enableRowGroup: bool = False
    hide: bool = False

    @field_validator("field")
    @classmethod
    def validate_field_name(cls, v: str) -> str:
        """Validate field name is not empty."""
        if not v or not v.strip():
            raise ValueError("Field name cannot be empty")
        return v

    @model_validator(mode="after")
    def validate_width_constraints(self) -> "AGGridColumnDef":
        """Validate width constraints are consistent."""
        if self.minWidth and self.maxWidth and self.minWidth > self.maxWidth:
            raise ValueError(
                f"minWidth ({self.minWidth}) cannot be greater than maxWidth ({self.maxWidth})"
            )
        if self.width:
            if self.minWidth and self.width < self.minWidth:
                raise ValueError(
                    f"width ({self.width}) cannot be less than minWidth ({self.minWidth})"
                )
            if self.maxWidth and self.width > self.maxWidth:
                raise ValueError(
                    f"width ({self.width}) cannot be greater than maxWidth ({self.maxWidth})"
                )
        return self


class ColsJson(BaseModel):
    """Root model for cols_json validation.

    cols_json is a dictionary mapping column names to their configurations.
    This model validates the entire structure.

    Example:
        {
            "sample": {"type": "object", "filter": "agTextColumnFilter"},
            "count": {"type": "int64", "filter": "agNumberColumnFilter"}
        }
    """

    model_config = ConfigDict(extra="forbid")

    root: dict[str, AGGridColumnConfig]

    @classmethod
    def validate_dict(cls, cols: dict[str, Any]) -> "ColsJson":
        """Validate a cols_json dictionary.

        Args:
            cols: Dictionary of column configurations

        Returns:
            Validated ColsJson instance

        Raises:
            ValidationError: If validation fails
        """
        validated_cols = {}
        for col_name, col_config in cols.items():
            if isinstance(col_config, dict):
                validated_cols[col_name] = AGGridColumnConfig.model_validate(col_config)
            else:
                validated_cols[col_name] = col_config
        return cls(root=validated_cols)


def validate_cols_json(
    cols: dict[str, Any] | None,
    raise_on_error: bool = False,
) -> tuple[bool, list[dict[str, Any]], dict[str, AGGridColumnConfig] | None]:
    """Validate cols_json dictionary.

    Args:
        cols: Dictionary of column configurations (or None)
        raise_on_error: If True, raise ValidationError instead of returning errors

    Returns:
        Tuple of (is_valid, errors, validated_cols)
        - is_valid: True if validation passed
        - errors: List of error dictionaries
        - validated_cols: Validated column configs (None if invalid)
    """
    if cols is None:
        return True, [], None

    if not isinstance(cols, dict):
        error = {
            "loc": ("cols_json",),
            "msg": "cols_json must be a dictionary",
            "type": "type_error",
        }
        if raise_on_error:
            from pydantic import ValidationError

            raise ValidationError.from_exception_data("ColsJson", [error])
        return False, [error], None

    errors = []
    validated_cols = {}

    for col_name, col_config in cols.items():
        try:
            if isinstance(col_config, dict):
                validated_cols[col_name] = AGGridColumnConfig.model_validate(col_config)
            else:
                errors.append(
                    {
                        "loc": ("cols_json", col_name),
                        "msg": f"Column config must be a dictionary, got {type(col_config).__name__}",
                        "type": "type_error",
                    }
                )
        except Exception as e:
            errors.append(
                {
                    "loc": ("cols_json", col_name),
                    "msg": str(e),
                    "type": "validation_error",
                }
            )

    if errors:
        if raise_on_error:
            from pydantic import ValidationError

            raise ValidationError.from_exception_data("ColsJson", errors)
        return False, errors, None

    return True, [], validated_cols


def validate_ag_grid_column_defs(
    column_defs: list[dict[str, Any]] | None,
    df_columns: list[str] | None = None,
    raise_on_error: bool = False,
) -> tuple[bool, list[dict[str, Any]], list[AGGridColumnDef] | None]:
    """Validate AG Grid columnDefs array.

    Args:
        column_defs: List of column definition dictionaries
        df_columns: Optional list of DataFrame column names for field validation
        raise_on_error: If True, raise ValidationError instead of returning errors

    Returns:
        Tuple of (is_valid, errors, validated_defs)
        - is_valid: True if validation passed
        - errors: List of error dictionaries
        - validated_defs: Validated column definitions (None if invalid)
    """
    if column_defs is None:
        return True, [], None

    if not isinstance(column_defs, list):
        error = {"loc": ("columnDefs",), "msg": "columnDefs must be a list", "type": "type_error"}
        if raise_on_error:
            from pydantic import ValidationError

            raise ValidationError.from_exception_data("AGGridColumnDefs", [error])
        return False, [error], None

    errors = []
    validated_defs = []

    for i, col_def in enumerate(column_defs):
        try:
            if not isinstance(col_def, dict):
                errors.append(
                    {
                        "loc": ("columnDefs", i),
                        "msg": f"Column definition must be a dictionary, got {type(col_def).__name__}",
                        "type": "type_error",
                    }
                )
                continue

            validated = AGGridColumnDef.model_validate(col_def)
            validated_defs.append(validated)

            # Check field exists in DataFrame if columns provided
            if df_columns and validated.field not in df_columns and validated.field != "ID":
                errors.append(
                    {
                        "loc": ("columnDefs", i, "field"),
                        "msg": f"Field '{validated.field}' not found in DataFrame columns: {df_columns}",
                        "type": "value_error",
                    }
                )

        except Exception as e:
            errors.append(
                {
                    "loc": ("columnDefs", i),
                    "msg": str(e),
                    "type": "validation_error",
                }
            )

    if errors:
        if raise_on_error:
            from pydantic import ValidationError

            raise ValidationError.from_exception_data("AGGridColumnDefs", errors)
        return False, errors, None

    return True, [], validated_defs


def cols_json_to_column_defs(cols_json: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert cols_json format to AG Grid columnDefs format.

    This mirrors the logic in table_component/utils.py:_build_column_definitions()
    but with validation.

    Args:
        cols_json: Dictionary of column configurations

    Returns:
        List of AG Grid column definition dictionaries
    """
    # Validate first
    is_valid, errors, validated_cols = validate_cols_json(cols_json)
    if not is_valid:
        raise ValueError(f"Invalid cols_json: {errors}")

    # Start with ID column
    column_defs = [{"field": "ID", "maxWidth": 100}]

    if not validated_cols:
        return column_defs

    for col_name, col_config in validated_cols.items():
        # Handle field names with dots - replace with underscores
        safe_field_name = col_name.replace(".", "_") if "." in col_name else col_name

        column_def = {
            "headerName": " ".join(word.capitalize() for word in col_name.split(".")),
            "headerTooltip": f"Column type: {col_config.type}",
            "field": safe_field_name,
            "filter": col_config.filter or "agTextColumnFilter",
            "floatingFilter": col_config.floatingFilter,
            "sortable": True,
            "resizable": True,
            "minWidth": 150,
        }

        if col_config.filterParams:
            if isinstance(col_config.filterParams, AGGridFilterParams):
                column_def["filterParams"] = col_config.filterParams.model_dump(exclude_none=True)
            else:
                column_def["filterParams"] = col_config.filterParams

        if col_config.description:
            column_def["headerTooltip"] += f" | Description: {col_config.description}"

        column_defs.append(column_def)

    return column_defs
