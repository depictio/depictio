"""
New tab-based dashboard structure models for Depictio.

This module defines the modern tab-based structure that replaces the legacy
stored_layout_data and stored_children_data approach with a more structured
tabs → sections → components hierarchy.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


class ComponentType(str, Enum):
    """Available component types in the dashboard."""

    CARD = "card"
    FIGURE = "figure"
    TABLE = "table"
    INTERACTIVE = "interactive"
    TEXT = "text"
    JBROWSE = "jbrowse"


class InteractiveControlType(str, Enum):
    """Available interactive control types."""

    RANGE_SLIDER = "range_slider"
    MULTI_SELECT = "multi_select"
    DROPDOWN = "dropdown"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    DATE_PICKER = "date_picker"


class AggregationType(str, Enum):
    """Available aggregation types for card components."""

    COUNT = "count"
    SUM = "sum"
    AVERAGE = "average"
    MEDIAN = "median"
    MIN = "min"
    MAX = "max"
    RANGE = "range"
    VARIANCE = "variance"
    STD_DEV = "std_dev"
    PERCENTILE = "percentile"
    MODE = "mode"
    NUNIQUE = "nunique"


class InteractiveComponentConfig(BaseModel):
    """Configuration for interactive filter components."""

    id: str = Field(..., description="Unique identifier for the interactive control")
    control_type: InteractiveControlType = Field(..., description="Type of interactive control")
    field: str = Field(..., description="Data field this control filters on")
    label: str = Field(..., description="Display label for the control")

    # Range slider specific
    min_value: Optional[float] = Field(None, description="Minimum value for range slider")
    max_value: Optional[float] = Field(None, description="Maximum value for range slider")
    step: Optional[float] = Field(None, description="Step size for range slider")

    # Select/dropdown specific
    options: Optional[List[Dict[str, Any]]] = Field(None, description="Options for select controls")
    multiple: Optional[bool] = Field(None, description="Whether multiple selection is allowed")

    # Default values
    default_value: Optional[Union[str, int, float, List[Any]]] = Field(
        None, description="Default value for the control"
    )

    # Metadata
    description: Optional[str] = Field(None, description="Optional description for the control")

    @field_validator("id")
    @classmethod
    def id_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("ID cannot be empty")
        return v.strip()


class CardComponentConfig(BaseModel):
    """Configuration for card metric components."""

    id: str = Field(..., description="Unique identifier for the card")
    title: str = Field(..., description="Display title for the card")

    # Data source configuration
    workflow_id: Optional[str] = Field(None, description="ID of the workflow for data source")
    data_collection_id: Optional[str] = Field(None, description="ID of the data collection")
    column_name: Optional[str] = Field(None, description="Column to aggregate")
    aggregation_type: Optional[AggregationType] = Field(None, description="Type of aggregation")

    # Visual customization - using existing card component structure
    color: Optional[str] = Field("blue", description="Color theme for the card")
    icon: Optional[str] = Field("mdi:chart-box", description="Icon for the card")
    font_size: Optional[str] = Field("lg", description="Font size for the card value")

    # Additional metadata
    description: Optional[str] = Field(None, description="Optional description")
    metric_key: Optional[str] = Field(None, description="Key for accessing metric data")
    format_type: Optional[str] = Field("int", description="Format type for the value")


class FigureComponentConfig(BaseModel):
    """Configuration for figure/chart components."""

    id: str = Field(..., description="Unique identifier for the figure")
    title: str = Field(..., description="Display title for the chart")

    # Chart configuration
    chart_type: str = Field(..., description="Type of chart (scatter, bar, line, etc.)")

    # Data columns
    x_col: Optional[str] = Field(None, description="X-axis column")
    y_col: Optional[str] = Field(None, description="Y-axis column")
    color_col: Optional[str] = Field(None, description="Color grouping column")
    size_col: Optional[str] = Field(None, description="Size column for scatter plots")

    # Data source configuration
    workflow_id: Optional[str] = Field(None, description="ID of the workflow for data source")
    data_collection_id: Optional[str] = Field(None, description="ID of the data collection")

    # Chart styling and configuration
    height: Optional[int] = Field(450, description="Chart height in pixels")
    theme: Optional[str] = Field("plotly", description="Chart theme")

    # Advanced configuration (stores figure component parameters)
    figure_params: Optional[Dict[str, Any]] = Field({}, description="Advanced figure parameters")

    # Additional metadata
    description: Optional[str] = Field(None, description="Optional description")


class TableComponentConfig(BaseModel):
    """Configuration for table components."""

    id: str = Field(..., description="Unique identifier for the table")
    title: str = Field(..., description="Display title for the table")

    # Data source configuration
    workflow_id: Optional[str] = Field(None, description="ID of the workflow for data source")
    data_collection_id: Optional[str] = Field(None, description="ID of the data collection")

    # Table configuration
    columns: Optional[List[str]] = Field(None, description="Columns to display")
    page_size: Optional[int] = Field(10, description="Number of rows per page")
    sortable: Optional[bool] = Field(True, description="Whether table is sortable")
    filterable: Optional[bool] = Field(True, description="Whether table is filterable")

    # Additional metadata
    description: Optional[str] = Field(None, description="Optional description")


class TextComponentConfig(BaseModel):
    """Configuration for text components."""

    id: str = Field(..., description="Unique identifier for the text component")
    title: Optional[str] = Field(None, description="Optional title for the text")

    # Text content
    content: str = Field(..., description="Text content (supports markdown)")
    content_type: Optional[str] = Field(
        "markdown", description="Content type (markdown, html, plain)"
    )

    # Styling
    font_size: Optional[str] = Field("md", description="Font size")
    text_align: Optional[str] = Field("left", description="Text alignment")

    # Additional metadata
    description: Optional[str] = Field(None, description="Optional description")


class DashboardComponent(BaseModel):
    """Generic dashboard component that can be any component type."""

    id: str = Field(..., description="Unique identifier for the component")
    type: ComponentType = Field(..., description="Type of component")

    # Component-specific configuration stored as Union
    config: Union[
        CardComponentConfig,
        FigureComponentConfig,
        TableComponentConfig,
        InteractiveComponentConfig,
        TextComponentConfig,
        Dict[str, Any],  # Fallback for other component types
    ] = Field(..., description="Component-specific configuration")

    # Layout information
    position: Optional[Dict[str, Any]] = Field({}, description="Component position and layout info")

    # Metadata
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")


class DashboardSection(BaseModel):
    """A section within a dashboard tab containing related components."""

    id: str = Field(..., description="Unique identifier for the section")
    name: str = Field(..., description="Display name for the section")

    # Section configuration
    components: List[DashboardComponent] = Field(
        default_factory=list, description="Components in this section"
    )

    # Section layout and styling
    layout_type: Optional[str] = Field("grid", description="Layout type (grid, stack, custom)")
    columns: Optional[int] = Field(None, description="Number of columns for grid layout")

    # Section metadata
    description: Optional[str] = Field(None, description="Optional description for the section")
    icon: Optional[str] = Field(None, description="Optional icon for the section")
    collapsible: Optional[bool] = Field(False, description="Whether section can be collapsed")

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Section name cannot be empty")
        return v.strip()


class DashboardTab(BaseModel):
    """A tab in the dashboard containing sections and filters."""

    id: str = Field(..., description="Unique identifier for the tab")
    name: str = Field(..., description="Display name for the tab")
    icon: Optional[str] = Field(None, description="Icon for the tab")

    # Tab content structure
    filters: List[InteractiveComponentConfig] = Field(
        default_factory=list, description="Interactive filters for this tab"
    )
    sections: List[DashboardSection] = Field(
        default_factory=list, description="Sections containing components"
    )

    # Tab configuration
    is_default: Optional[bool] = Field(False, description="Whether this is the default active tab")
    order: Optional[int] = Field(0, description="Order of the tab")

    # Tab metadata
    description: Optional[str] = Field(None, description="Optional description for the tab")

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Tab name cannot be empty")
        return v.strip()


class DashboardTabStructure(BaseModel):
    """Complete tab-based structure for a dashboard."""

    tabs: List[DashboardTab] = Field(default_factory=list, description="Dashboard tabs")

    # Global dashboard configuration
    default_tab_id: Optional[str] = Field(None, description="ID of the default active tab")
    theme: Optional[str] = Field("light", description="Dashboard theme")

    # Layout configuration
    sidebar_width: Optional[int] = Field(300, description="Sidebar width in pixels")
    header_height: Optional[int] = Field(60, description="Header height in pixels")

    # Metadata
    version: str = Field("2.0", description="Structure version")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")

    def get_tab_by_id(self, tab_id: str) -> Optional[DashboardTab]:
        """Get a tab by its ID."""
        for tab in self.tabs:
            if tab.id == tab_id:
                return tab
        return None

    def get_default_tab(self) -> Optional[DashboardTab]:
        """Get the default tab or first tab if no default is set."""
        if self.default_tab_id:
            default_tab = self.get_tab_by_id(self.default_tab_id)
            if default_tab:
                return default_tab

        # Return first tab marked as default
        for tab in self.tabs:
            if tab.is_default:
                return tab

        # Return first tab if available
        return self.tabs[0] if self.tabs else None

    def add_tab(self, tab: DashboardTab) -> None:
        """Add a new tab to the dashboard."""
        # Ensure unique ID
        existing_ids = {t.id for t in self.tabs}
        if tab.id in existing_ids:
            raise ValueError(f"Tab with ID '{tab.id}' already exists")

        self.tabs.append(tab)

    def remove_tab(self, tab_id: str) -> bool:
        """Remove a tab by ID. Returns True if removed, False if not found."""
        for i, tab in enumerate(self.tabs):
            if tab.id == tab_id:
                del self.tabs[i]
                return True
        return False
