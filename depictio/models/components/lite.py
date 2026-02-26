"""
Lite Component Models.

Minimal component models for user-defined dashboards (YAML/Python).
Full component models inherit from these and add runtime fields.

Architecture:
    FigureLiteComponent (user-definable, YAML-friendly)
        ↓ inherits
    FigureComponent (adds runtime/rendering fields)

Index vs Tag:
    - `tag`: User-friendly identifier written in YAML (e.g., 'scatter-1', 'my-chart')
    - `index`: Internal UUID, auto-generated if not provided

    Users write `tag` in YAML, system manages `index` as UUID internally.
"""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from depictio.models.components.constants import (
    AGGREGATION_COMPATIBILITY,
    COLUMN_TYPES,
    INTERACTIVE_COMPATIBILITY,
    MAP_STYLES,
    MAP_TYPES,
    VISU_TYPES,
)


class BaseLiteComponent(BaseModel):
    """Base class for lite dashboard components.

    Contains only the fields users need to define a component.
    Runtime fields (wf_id, dc_id, dc_config, etc.) are added by full components.

    Users should provide `tag` for identification. The `index` (UUID) is
    auto-generated if not provided.
    """

    model_config = ConfigDict(extra="allow")

    # Component identification
    tag: str | None = Field(
        default=None, description="User-friendly identifier (e.g., 'scatter-1')"
    )
    index: str | None = Field(
        default=None, description="Internal UUID (auto-generated if not provided)"
    )
    component_type: str = Field(..., description="Component type")

    # Display
    title: str = Field(default="", description="Component title")
    description: str = Field(default="", description="Component description/subtitle")
    title_size: str = Field(
        default="sm",
        description="Title size: 'h1', 'h2', 'h3', or 'sm' (default)",
    )
    title_align: str = Field(
        default="left",
        description="Title alignment: 'left' (default), 'center', or 'right'",
    )

    # Data source references (human-readable tags)
    workflow_tag: str = Field(default="", description="Workflow tag (e.g., 'python/iris_workflow')")
    data_collection_tag: str = Field(
        default="", description="Data collection tag (e.g., 'iris_table')"
    )

    @model_validator(mode="after")
    def ensure_index(self) -> "BaseLiteComponent":
        """Auto-generate index UUID if not provided."""
        if not self.index:
            self.index = str(uuid.uuid4())
        return self


class FigureLiteComponent(BaseLiteComponent):
    """Lite figure component for user definition.

    Example YAML:
        - tag: scatter-1
          component_type: figure
          workflow_tag: python/iris_workflow
          data_collection_tag: iris_table
          visu_type: scatter
          dict_kwargs:
            x: sepal.length
            y: sepal.width
            color: variety
          selection_enabled: true
          selection_column: sample_id
    """

    component_type: Literal["figure"] = "figure"

    # Visualization type
    visu_type: str = Field(
        default="scatter", description="Chart type (scatter, box, histogram, etc.)"
    )

    # Plotly Express parameters
    dict_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters passed to Plotly Express (x, y, color, etc.)",
    )

    # Code mode (alternative to dict_kwargs for custom transformations)
    mode: str = Field(default="ui", description="Rendering mode: 'ui' or 'code'")
    code_content: str | None = Field(default=None, description="Python code for code mode figures")

    # Selection filtering (enables scatter selection to filter other components)
    selection_enabled: bool = Field(default=False, description="Enable scatter selection filtering")
    selection_column: str | None = Field(
        default=None, description="Column to extract from selected points"
    )

    @model_validator(mode="after")
    def validate_figure_constraints(self) -> "FigureLiteComponent":
        """Validate figure-specific cross-field constraints."""
        if self.mode == "ui":
            if self.visu_type not in VISU_TYPES:
                valid = ", ".join(VISU_TYPES)
                raise ValueError(
                    f"Invalid visu_type '{self.visu_type}' for mode='ui'. Valid values: {valid}"
                )
        elif self.mode == "code":
            if not self.code_content or not self.code_content.strip():
                raise ValueError("code_content is required and must be non-empty when mode='code'")
        else:
            raise ValueError(f"Invalid mode '{self.mode}'. Valid values: 'ui', 'code'")

        if self.selection_enabled and not self.selection_column:
            raise ValueError("selection_column is required when selection_enabled=True")

        return self


class CardLiteComponent(BaseLiteComponent):
    """Lite card component for user definition.

    Example YAML:
        - tag: card-1
          component_type: card
          workflow_tag: python/iris_workflow
          data_collection_tag: iris_table
          aggregation: average
          column_name: sepal.length
          column_type: float64
    """

    component_type: Literal["card"] = "card"

    # Aggregation configuration
    aggregation: str = Field(..., description="Aggregation function (average, sum, count, etc.)")
    column_name: str = Field(..., description="Column to aggregate")
    column_type: str | None = Field(
        default=None,
        description="Data type of column (int64, float64, bool, datetime, timedelta, "
        "category, object). When provided, aggregation compatibility is validated.",
    )

    # Styling (optional)
    icon_name: str | None = Field(default=None, description="Iconify icon name")
    icon_color: str | None = Field(default=None, description="Icon color")
    title_color: str | None = Field(default=None, description="Title text color")
    title_font_size: str | None = Field(default=None, description="Title font size")
    value_font_size: str | None = Field(default=None, description="Value font size")

    @field_validator("column_type")
    @classmethod
    def validate_column_type(cls, v: str | None) -> str | None:
        if v is not None and v not in COLUMN_TYPES:
            valid = ", ".join(COLUMN_TYPES)
            raise ValueError(f"Invalid column_type '{v}'. Valid values: {valid}")
        return v

    @model_validator(mode="after")
    def validate_aggregation_for_column_type(self) -> "CardLiteComponent":
        """Validate aggregation × column_type compatibility when column_type is provided."""
        if self.column_type is None:
            return self
        valid_aggs = AGGREGATION_COMPATIBILITY.get(self.column_type, [])
        if valid_aggs and self.aggregation not in valid_aggs:
            valid = ", ".join(valid_aggs)
            raise ValueError(
                f"Invalid aggregation '{self.aggregation}' for column_type='{self.column_type}'. "
                f"Valid aggregations: {valid}"
            )
        return self


class InteractiveLiteComponent(BaseLiteComponent):
    """Lite interactive component for user definition.

    Example YAML:
        - tag: filter-1
          component_type: interactive
          workflow_tag: python/iris_workflow
          data_collection_tag: iris_table
          interactive_component_type: MultiSelect
          column_name: variety
          column_type: object
    """

    component_type: Literal["interactive"] = "interactive"

    # Filter configuration
    interactive_component_type: str = Field(
        ..., description="Filter type (RangeSlider, MultiSelect, etc.)"
    )
    column_name: str = Field(..., description="Column to filter on")
    column_type: str | None = Field(
        default=None,
        description="Data type of column (int64, float64, bool, datetime, timedelta, "
        "category, object). When provided, component type compatibility is validated.",
    )

    # Styling (optional)
    title_size: str | None = Field(default=None, description="Title size")
    custom_color: str | None = Field(default=None, description="Custom accent color")
    icon_name: str | None = Field(default=None, description="Iconify icon name")

    @field_validator("column_type")
    @classmethod
    def validate_column_type(cls, v: str | None) -> str | None:
        if v is not None and v not in COLUMN_TYPES:
            valid = ", ".join(COLUMN_TYPES)
            raise ValueError(f"Invalid column_type '{v}'. Valid values: {valid}")
        return v

    @model_validator(mode="after")
    def validate_interactive_type_for_column_type(self) -> "InteractiveLiteComponent":
        """Validate interactive_component_type × column_type when column_type is provided."""
        if self.column_type is None:
            return self
        valid_types = INTERACTIVE_COMPATIBILITY.get(self.column_type, [])
        if not valid_types:
            raise ValueError(
                f"No interactive components are supported for column_type='{self.column_type}'"
            )
        if self.interactive_component_type not in valid_types:
            valid = ", ".join(valid_types)
            raise ValueError(
                f"Invalid interactive_component_type '{self.interactive_component_type}' "
                f"for column_type='{self.column_type}'. "
                f"Valid types: {valid}"
            )
        return self


class TableLiteComponent(BaseLiteComponent):
    """Lite table component for user definition.

    Example YAML:
        - tag: table-1
          component_type: table
          workflow_tag: python/iris_workflow
          data_collection_tag: iris_table
          row_selection_enabled: true
          row_selection_column: sample_id
    """

    component_type: Literal["table"] = "table"

    # Table options (optional)
    columns: list[str] = Field(default_factory=list, description="Columns to display (empty = all)")
    page_size: int = Field(default=10, description="Rows per page")
    sortable: bool = Field(default=True, description="Enable column sorting")
    filterable: bool = Field(default=True, description="Enable column filtering")

    # Row selection filtering (enables table row selection to filter other components)
    row_selection_enabled: bool = Field(default=False, description="Enable row selection filtering")
    row_selection_column: str | None = Field(
        default=None, description="Column to extract from selected rows"
    )


class ImageLiteComponent(BaseLiteComponent):
    """Lite image component for user definition.

    Example YAML:
        - tag: image-gallery-1
          component_type: image
          workflow_tag: python/image_workflow
          data_collection_tag: image_table
          image_column: image_path
          thumbnail_size: 150
          columns: 4
          max_images: 20
    """

    component_type: Literal["image"] = "image"

    # Image configuration
    image_column: str = Field(..., description="Column containing image paths")
    s3_base_folder: str | None = Field(
        default=None, description="Base S3 folder for images (defaults to data collection folder)"
    )

    # Display options
    thumbnail_size: int = Field(default=150, description="Grid thumbnail size in pixels")
    columns: int = Field(default=4, description="Number of grid columns")
    max_images: int = Field(default=20, description="Maximum images to display")


class MultiQCLiteComponent(BaseLiteComponent):
    """Lite MultiQC component for user definition.

    Both selected_module and selected_plot are required: without them the
    component cannot render a specific plot and the YAML would be ambiguous.
    At runtime the Dash model allows None (auto-selects), but in user-defined
    YAML the choice must be explicit.

    Example YAML:
        - tag: fastqc-quality
          component_type: multiqc
          workflow_tag: python/nf_workflow
          data_collection_tag: multiqc_report
          selected_module: fastqc
          selected_plot: per_base_sequence_quality
    """

    component_type: Literal["multiqc"] = "multiqc"

    selected_module: str = Field(..., description="MultiQC module to display (e.g. 'fastqc')")
    selected_plot: str = Field(
        ..., description="Plot within the module (e.g. 'per_base_sequence_quality')"
    )


class MapLiteComponent(BaseLiteComponent):
    """Lite map component for user definition.

    Supports scatter_map, density_map, and choropleth_map visualizations
    using Plotly Express tile-based map functions (no API key required).

    Example YAML:
        - tag: sample-locations
          component_type: map
          workflow_tag: nfcore/ampliseq
          data_collection_tag: sample_metadata
          lat_column: latitude
          lon_column: longitude
          color_column: biome
          size_column: read_count
          hover_columns: [sample_id, collection_date, depth_m]
          map_style: carto-positron
          selection_enabled: true
          selection_column: sample_id
    """

    component_type: Literal["map"] = "map"

    # Map type
    map_type: str = Field(
        default="scatter_map",
        description="Map visualization type (scatter_map, density_map, choropleth_map)",
    )

    # Column mappings (required for scatter_map and density_map, not for choropleth_map)
    lat_column: str | None = Field(default=None, description="Column containing latitude values")
    lon_column: str | None = Field(default=None, description="Column containing longitude values")

    # Optional column mappings
    color_column: str | None = Field(default=None, description="Column for marker color encoding")
    size_column: str | None = Field(default=None, description="Column for marker size encoding")
    hover_columns: list[str] = Field(
        default_factory=list, description="Columns to show on hover tooltip"
    )
    text_column: str | None = Field(default=None, description="Column for marker text labels")

    # Map styling
    map_style: str = Field(
        default="carto-positron",
        description="Tile style (open-street-map, carto-positron, carto-darkmatter)",
    )
    default_zoom: int | None = Field(
        default=None, description="Fixed zoom level (auto-computed if not set)"
    )
    default_center: dict[str, float] | None = Field(
        default=None, description="Fixed center as {lat: float, lon: float}"
    )
    opacity: float = Field(default=1.0, description="Marker opacity (0.0 to 1.0)")
    size_max: int = Field(default=15, description="Maximum marker size in pixels")

    # Density map specific
    z_column: str | None = Field(default=None, description="Weight column for density_map")
    radius: int | None = Field(default=None, description="Smoothing radius for density_map")

    # Choropleth map specific
    locations_column: str | None = Field(
        default=None, description="Column matching GeoJSON feature IDs"
    )
    featureidkey: str = Field(
        default="id", description="Property path in GeoJSON features to match locations"
    )
    geojson_data: dict[str, Any] | None = Field(
        default=None, description="Inline GeoJSON FeatureCollection dict"
    )
    geojson_url: str | None = Field(
        default=None,
        description="URL to a GeoJSON file (alternative to inline geojson_data)",
    )
    geojson_dc_id: str | None = Field(
        default=None,
        description="Data collection ID for a GeoJSON DC (alternative to geojson_data/geojson_url)",
    )
    geojson_dc_tag: str | None = Field(
        default=None,
        description="Human-readable tag for GeoJSON DC (resolved to geojson_dc_id during import)",
    )
    choropleth_aggregation: str | None = Field(
        default=None,
        description="Aggregation function for choropleth (count, sum, mean, min, max). "
        "Groups data by locations_column and aggregates color_column.",
    )
    color_continuous_scale: str | None = Field(
        default=None, description="Named Plotly color scale (e.g., 'Viridis')"
    )
    range_color: list[float] | None = Field(
        default=None, description="[min, max] for continuous color scale"
    )

    # Selection filtering
    selection_enabled: bool = Field(
        default=False, description="Enable click/lasso selection filtering"
    )
    selection_column: str | None = Field(
        default=None, description="Column to extract from selected points"
    )

    # Display title
    title: str | None = Field(default=None, description="Title displayed above the map")

    # Pass-through kwargs for extra Plotly Express parameters
    dict_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional parameters passed to Plotly Express map function",
    )

    @model_validator(mode="after")
    def validate_map_constraints(self) -> "MapLiteComponent":
        """Validate map-specific cross-field constraints."""
        if self.map_type not in MAP_TYPES:
            valid = ", ".join(MAP_TYPES)
            raise ValueError(f"Invalid map_type '{self.map_type}'. Valid values: {valid}")

        if self.map_style not in MAP_STYLES:
            valid = ", ".join(MAP_STYLES)
            raise ValueError(f"Invalid map_style '{self.map_style}'. Valid values: {valid}")

        if self.selection_enabled and not self.selection_column:
            raise ValueError("selection_column is required when selection_enabled=True")

        # scatter_map / density_map require lat/lon columns
        if self.map_type in ("scatter_map", "density_map"):
            if not self.lat_column:
                raise ValueError(
                    "lat_column is required when map_type is scatter_map or density_map"
                )
            if not self.lon_column:
                raise ValueError(
                    "lon_column is required when map_type is scatter_map or density_map"
                )

        if self.map_type == "density_map" and not self.z_column:
            raise ValueError("z_column is required when map_type='density_map'")

        # choropleth_map requires locations_column, geojson source, color_column
        if self.map_type == "choropleth_map":
            if not self.locations_column:
                raise ValueError("locations_column is required when map_type='choropleth_map'")
            if not self.geojson_data and not self.geojson_url and not self.geojson_dc_id:
                raise ValueError(
                    "geojson_data, geojson_url, or geojson_dc_id is required "
                    "when map_type='choropleth_map'"
                )
            if not self.color_column:
                raise ValueError("color_column is required when map_type='choropleth_map'")
            if self.selection_enabled:
                raise ValueError(
                    "selection_enabled is not supported for choropleth_map "
                    "(Plotly does not support lasso/click selection on choropleth traces)"
                )

        if self.choropleth_aggregation and self.choropleth_aggregation not in (
            "count",
            "sum",
            "mean",
            "min",
            "max",
        ):
            raise ValueError(
                f"Invalid choropleth_aggregation '{self.choropleth_aggregation}'. "
                "Valid values: count, sum, mean, min, max"
            )

        if self.range_color is not None and len(self.range_color) != 2:
            raise ValueError("range_color must have exactly 2 elements [min, max]")

        if self.default_center is not None:
            if "lat" not in self.default_center or "lon" not in self.default_center:
                raise ValueError("default_center must have 'lat' and 'lon' keys")

        return self


# Union type for any lite component
LiteComponent = (
    FigureLiteComponent
    | CardLiteComponent
    | InteractiveLiteComponent
    | TableLiteComponent
    | ImageLiteComponent
    | MultiQCLiteComponent
    | MapLiteComponent
)
