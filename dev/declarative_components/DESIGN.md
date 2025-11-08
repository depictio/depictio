# Declarative Component System for Depictio

**Author**: Claude Code + Thomas Weber
**Date**: 2025-11-06
**Status**: Design Phase
**Goal**: Create a Vizro-like declarative system for building Depictio dashboards with Pydantic models

---

## Executive Summary

This design document outlines a declarative component system that allows users to define Depictio dashboards using:
- **Python API** with type-safe Pydantic models
- **YAML configuration** files (Vizro-style)
- **JSON** for API integration
- **Unified OOP architecture** with base classes and polymorphism

The system focuses initially on **Card** and **Interactive** components, with extensibility for future component types.

---

## Current State Analysis

### Existing Component Architecture

Depictio currently has 7 component types:
1. **Card** - Statistical aggregations (count, sum, mean, etc.)
2. **Interactive** - Data filters (sliders, selects, date pickers)
3. **Figure** - Plotly visualizations
4. **Table** - DataTables
5. **Text** - Rich text editor
6. **MultiQC** - Quality control reports
7. **JBrowse** - Genome browser

Each component follows this structure:
```
depictio/dash/modules/{component_type}/
├── utils.py           # Core build_{component}() function
├── frontend.py        # Legacy compatibility layer
├── design_ui.py       # Design mode UI
└── callbacks/
    ├── core.py        # Rendering callbacks
    └── design.py      # Edit callbacks
```

### Current Component Instantiation Flow

```python
# 1. Direct function call with dict of parameters
component = build_card(
    index=str(uuid.uuid4()),
    title="Total Samples",
    wf_id="workflow-1",
    dc_id="metadata",
    column_name="sample",
    aggregation="count",
    # ... 15+ more parameters
)

# 2. Metadata stored in dcc.Store for persistence
store = dcc.Store(
    id={"type": "stored-metadata-component", "index": index},
    data={
        "index": index,
        "component_type": "card",
        "title": "Total Samples",
        # ... all parameters as dict
    }
)
```

### Gaps for Declarative System

- ❌ **No Pydantic validation** - Component configs are plain dicts
- ❌ **No YAML support** - Only programmatic creation
- ❌ **No component factory** - Direct function calls
- ❌ **No formal schema** - Parameter documentation in docstrings only
- ❌ **No type safety** - Easy to pass invalid parameters

### Existing Building Blocks (Assets)

- ✅ **Centralized registry** - `component_metadata.py` with build function mapping
- ✅ **Pattern-matching callbacks** - Flexible ID-based callback system
- ✅ **Lazy callback loading** - Performance optimized
- ✅ **Dashboard data model** - `DashboardData` Pydantic model exists
- ✅ **Save/restore infrastructure** - API endpoints for persistence

---

## Proposed Architecture

### 1. Component Model Hierarchy

```
BaseComponent (Abstract Pydantic Model)
├── CardComponent
├── InteractiveComponent
├── FigureComponent (future)
├── TableComponent (future)
└── CustomComponent (plugin system)
```

#### Base Component Class

```python
# depictio/models/components/base.py

from pydantic import BaseModel, Field, ConfigDict
from typing import Any, Optional, Dict
from abc import abstractmethod
import uuid

class GridPosition(BaseModel):
    """Grid layout positioning."""
    x: int = 0
    y: int = 0
    w: int = 6  # Width in grid units
    h: int = 4  # Height in grid units
    minW: Optional[int] = None
    minH: Optional[int] = None
    maxW: Optional[int] = None
    maxH: Optional[int] = None

    model_config = ConfigDict(extra="forbid")

class BaseComponent(BaseModel):
    """
    Abstract base class for all Depictio components.

    Provides common functionality:
    - Unique indexing
    - Pydantic validation
    - Metadata export/import
    - Grid positioning
    - Abstract methods for UI building and callback registration
    """

    component_type: str
    index: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    wf_id: str = Field(description="Workflow ID")
    dc_id: str = Field(description="Data Collection ID")

    # Layout
    grid_position: Optional[GridPosition] = None
    parent_index: Optional[str] = None

    # Common styling
    color: Optional[str] = None

    model_config = ConfigDict(
        extra="forbid",  # Catch typos/invalid params
        validate_assignment=True,  # Re-validate on attribute changes
    )

    @abstractmethod
    def build(self, stepper: bool = False, **context) -> Any:
        """
        Generate the Dash component tree.

        Args:
            stepper: Whether component is in stepper/wizard mode
            **context: Additional runtime context (access_token, df, etc.)

        Returns:
            Dash component (dmc.Paper, dmc.Stack, etc.)
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement build() method"
        )

    def register_callbacks(self, app: "Dash") -> None:
        """
        Register component-specific callbacks with the Dash app.

        Default implementation does nothing - override in subclasses
        that need callbacks (e.g., CardComponent, InteractiveComponent).

        Args:
            app: Dash application instance
        """
        pass

    def to_metadata(self) -> Dict[str, Any]:
        """
        Export component to stored-metadata format.

        Compatible with existing DashboardData.stored_metadata structure.

        Returns:
            Dict with all component parameters
        """
        metadata = self.model_dump(exclude_none=True)

        # Convert grid_position to flat dict for compatibility
        if self.grid_position:
            metadata.update(self.grid_position.model_dump())
            del metadata["grid_position"]

        return metadata

    @classmethod
    def from_metadata(cls, metadata: Dict[str, Any]) -> "BaseComponent":
        """
        Create component instance from stored metadata.

        Args:
            metadata: Component parameters dict (from DashboardData.stored_metadata)

        Returns:
            Component instance
        """
        # Extract grid position if present
        grid_keys = {"x", "y", "w", "h", "minW", "minH", "maxW", "maxH"}
        grid_data = {k: v for k, v in metadata.items() if k in grid_keys}

        if grid_data:
            metadata = metadata.copy()
            for key in grid_keys:
                metadata.pop(key, None)
            metadata["grid_position"] = GridPosition(**grid_data)

        return cls(**metadata)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(title='{self.title}', index='{self.index[:8]}...')"
```

#### Card Component Implementation

```python
# depictio/models/components/card.py

from typing import Literal, Optional, Any
from pydantic import Field, field_validator
from .base import BaseComponent

class CardComponent(BaseComponent):
    """
    Declarative model for Card components (statistical aggregations).

    Example:
        >>> card = CardComponent(
        ...     title="Total Samples",
        ...     wf_id="ampliseq",
        ...     dc_id="metadata",
        ...     column_name="sample",
        ...     aggregation="count",
        ...     background_color="#3b82f6",
        ...     icon_name="mdi:test-tube"
        ... )
        >>> component_ui = card.build()
    """

    component_type: Literal["card"] = "card"

    # Data configuration
    column_name: str = Field(description="Column to aggregate")
    column_type: Optional[str] = Field(None, description="Data type (auto-detected if None)")
    aggregation: Literal["count", "sum", "average", "median", "min", "max"] = Field(
        description="Aggregation function to apply"
    )

    # Display configuration
    value: Optional[Any] = Field(None, description="Pre-computed value (optional)")
    background_color: Optional[str] = Field(None, description="Card background color (hex)")
    title_color: Optional[str] = Field(None, description="Title text color (hex)")
    icon_name: Optional[str] = Field("mdi:card", description="MDI icon name")
    icon_color: Optional[str] = Field(None, description="Icon color (hex)")
    title_font_size: Optional[str] = Field(None, description="Title font size (CSS)")
    value_font_size: Optional[str] = Field(None, description="Value font size (CSS)")
    metric_theme: Optional[str] = Field(None, description="Preset theme name")

    # Advanced
    build_frame: bool = Field(True, description="Whether to build frame around card")

    @field_validator("background_color", "title_color", "icon_color")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        """Validate hex color format."""
        if v is None:
            return v

        if not v.startswith("#"):
            raise ValueError(f"Color must be hex format (e.g., #3b82f6), got: {v}")

        if len(v) not in (4, 7):  # #RGB or #RRGGBB
            raise ValueError(f"Invalid hex color length: {v}")

        return v

    @field_validator("icon_name")
    @classmethod
    def validate_icon(cls, v: Optional[str]) -> Optional[str]:
        """Validate MDI icon format."""
        if v and not v.startswith("mdi:"):
            raise ValueError(f"Icon must be MDI format (e.g., mdi:test-tube), got: {v}")
        return v

    def build(self, stepper: bool = False, **context) -> Any:
        """
        Build card UI by delegating to existing build_card() function.

        Args:
            stepper: Stepper mode flag
            **context: Additional context (access_token, init_data, cols_json, etc.)

        Returns:
            dmc.Paper or dmc.Card component
        """
        from depictio.dash.modules.card_component.utils import build_card

        # Merge validated model data with runtime context
        build_params = self.model_dump(exclude={"grid_position"})
        build_params.update(context)
        build_params["stepper"] = stepper

        return build_card(**build_params)

    def register_callbacks(self, app: "Dash") -> None:
        """
        Register card-specific callbacks.

        Callbacks registered:
        - update_aggregation_options: Populate aggregation dropdown based on column type
        - reset_aggregation_value: Reset aggregation when column changes
        - render_card_value_background: Async value computation
        - patch_card_with_filters: Update card when filters change
        - Clientside callback: Loading overlay toggle
        """
        from depictio.dash.modules.card_component.callbacks.core import (
            register_card_callbacks
        )
        register_card_callbacks(app, self.index)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "title": "Total Samples",
                    "wf_id": "ampliseq-workflow",
                    "dc_id": "metadata",
                    "column_name": "sample",
                    "aggregation": "count",
                    "background_color": "#3b82f6",
                    "icon_name": "mdi:test-tube",
                    "grid_position": {"x": 0, "y": 0, "w": 6, "h": 4}
                }
            ]
        }
    }
```

#### Interactive Component Implementation

```python
# depictio/models/components/interactive.py

from typing import Literal, Optional, Any, List
from pydantic import Field, field_validator
from .base import BaseComponent

class InteractiveComponent(BaseComponent):
    """
    Declarative model for Interactive components (data filters).

    Supports multiple filter types:
    - RangeSlider: Numeric range selection
    - Slider: Single value selection
    - DateRangePicker: Date range selection
    - DatePicker: Single date selection
    - MultiSelect: Multiple category selection
    - Select: Single category selection

    Example:
        >>> filter_component = InteractiveComponent(
        ...     title="Filter by Habitat",
        ...     wf_id="ampliseq",
        ...     dc_id="metadata",
        ...     column_name="habitat",
        ...     interactive_component_type="MultiSelect"
        ... )
    """

    component_type: Literal["interactive"] = "interactive"

    # Data configuration
    column_name: str = Field(description="Column to filter on")
    column_type: Optional[str] = Field(None, description="Data type (auto-detected if None)")

    # Filter type
    interactive_component_type: Literal[
        "RangeSlider",
        "Slider",
        "DateRangePicker",
        "DatePicker",
        "MultiSelect",
        "Select"
    ] = Field(description="Type of interactive filter")

    # Filter behavior
    value: Optional[Any] = Field(None, description="Default/initial value")
    scale: Optional[Literal["linear", "log"]] = Field(
        "linear",
        description="Scale for numeric sliders"
    )
    marks_number: Optional[int] = Field(
        5,
        ge=2,
        le=20,
        description="Number of marks on sliders"
    )

    # Display configuration
    icon_name: Optional[str] = Field("mdi:filter", description="MDI icon name")
    title_size: Optional[str] = Field(None, description="Title font size (CSS)")

    # Advanced
    df: Optional[Any] = Field(None, description="Pre-loaded dataframe (optional)")
    access_token: Optional[str] = Field(None, description="API access token")

    @field_validator("interactive_component_type")
    @classmethod
    def validate_component_type_compatibility(cls, v: str, info) -> str:
        """
        Validate component type compatibility with column type.

        Note: Full validation requires runtime data, so this is a basic check.
        """
        # Numeric types require sliders
        numeric_types = {"RangeSlider", "Slider"}
        # Date types require date pickers
        date_types = {"DateRangePicker", "DatePicker"}
        # Categorical types require selects
        categorical_types = {"MultiSelect", "Select"}

        # Could add more validation here based on column_type if provided
        return v

    def build(self, stepper: bool = False, **context) -> Any:
        """
        Build interactive filter UI.

        Args:
            stepper: Stepper mode flag
            **context: Additional context (init_data, cols_json, etc.)

        Returns:
            dmc.Stack or dmc.Paper component
        """
        from depictio.dash.modules.interactive_component.utils import build_interactive

        build_params = self.model_dump(exclude={"grid_position"})
        build_params.update(context)
        build_params["stepper"] = stepper

        return build_interactive(**build_params)

    def register_callbacks(self, app: "Dash") -> None:
        """
        Register interactive filter callbacks.

        Callbacks registered:
        - Clientside callback: Filter value propagation to components
        - Reset callback: Clear filter values
        - Options data population: For Select/MultiSelect components
        """
        from depictio.dash.modules.interactive_component.callbacks.core import (
            register_interactive_callbacks
        )
        register_interactive_callbacks(app, self.index)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "title": "Habitat Filter",
                    "wf_id": "ampliseq-workflow",
                    "dc_id": "metadata",
                    "column_name": "habitat",
                    "interactive_component_type": "MultiSelect",
                    "grid_position": {"x": 6, "y": 0, "w": 6, "h": 4}
                },
                {
                    "title": "Sample Count Range",
                    "wf_id": "ampliseq-workflow",
                    "dc_id": "metadata",
                    "column_name": "sample_count",
                    "interactive_component_type": "RangeSlider",
                    "scale": "linear",
                    "marks_number": 10
                }
            ]
        }
    }
```

---

## Configuration Format Support

### 1. Python API (Type-Safe)

```python
# examples/declarative_dashboards/python_api_example.py

from depictio.dash.components import CardComponent, InteractiveComponent, Page, Dashboard

# Create components with type safety and validation
total_samples_card = CardComponent(
    title="Total Samples",
    wf_id="ampliseq",
    dc_id="metadata",
    column_name="sample",
    aggregation="count",
    background_color="#3b82f6",
    icon_name="mdi:test-tube",
    grid_position={"x": 0, "y": 0, "w": 6, "h": 4}
)

habitat_filter = InteractiveComponent(
    title="Filter by Habitat",
    wf_id="ampliseq",
    dc_id="metadata",
    column_name="habitat",
    interactive_component_type="MultiSelect",
    grid_position={"x": 6, "y": 0, "w": 6, "h": 4}
)

# Create page with components
overview_page = Page(
    title="Overview",
    components=[total_samples_card, habitat_filter]
)

# Create dashboard
dashboard = Dashboard(
    title="Sample Analysis Dashboard",
    subtitle="Ampliseq metadata overview",
    pages=[overview_page]
)

# Build and run
app = dashboard.build()
app.run(debug=True)
```

### 2. YAML Configuration (Vizro-Style)

```yaml
# examples/declarative_dashboards/analytics_dashboard.yaml

dashboard:
  title: "Sample Analysis Dashboard"
  subtitle: "Ampliseq metadata overview"
  icon: "mdi:chart-box"
  icon_color: "blue"

pages:
  - title: "Overview"
    layout: "grid"

    components:
      # Card component
      - type: card
        title: "Total Samples"
        wf_id: "ampliseq"
        dc_id: "metadata"
        column_name: "sample"
        aggregation: "count"
        background_color: "#3b82f6"
        icon_name: "mdi:test-tube"
        grid_position:
          x: 0
          y: 0
          w: 6
          h: 4

      # Interactive filter
      - type: interactive
        title: "Filter by Habitat"
        wf_id: "ampliseq"
        dc_id: "metadata"
        column_name: "habitat"
        interactive_component_type: "MultiSelect"
        icon_name: "mdi:filter-variant"
        grid_position:
          x: 6
          y: 0
          w: 6
          h: 4

      # Another card
      - type: card
        title: "Average Read Length"
        wf_id: "ampliseq"
        dc_id: "multiqc_data"
        column_name: "avg_sequence_length"
        aggregation: "average"
        background_color: "#10b981"
        icon_name: "mdi:dna"
        grid_position:
          x: 0
          y: 4
          w: 6
          h: 4

      # Date range filter
      - type: interactive
        title: "Date Range"
        wf_id: "ampliseq"
        dc_id: "metadata"
        column_name: "collection_date"
        interactive_component_type: "DateRangePicker"
        grid_position:
          x: 6
          y: 4
          w: 6
          h: 4
```

**YAML Loader Implementation:**

```python
# depictio/dash/config/yaml_loader.py

import yaml
from typing import Dict, Any, List
from pathlib import Path
from depictio.models.components.registry import create_component
from depictio.models.components.dashboard import Dashboard, Page

def load_dashboard_from_yaml(path: str | Path) -> Dashboard:
    """
    Load dashboard definition from YAML file.

    Args:
        path: Path to YAML configuration file

    Returns:
        Dashboard instance with validated components

    Raises:
        ValidationError: If configuration is invalid
        FileNotFoundError: If YAML file doesn't exist

    Example:
        >>> dashboard = load_dashboard_from_yaml("dashboards/analytics.yaml")
        >>> app = dashboard.build()
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"YAML configuration not found: {path}")

    with open(path) as f:
        config = yaml.safe_load(f)

    if not config or "dashboard" not in config:
        raise ValueError("Invalid YAML: missing 'dashboard' key")

    # Parse dashboard metadata
    dashboard_config = config["dashboard"]

    # Parse pages
    pages = []
    for page_config in config.get("pages", []):
        page_title = page_config.get("title", "Untitled Page")

        # Parse components for this page
        components = []
        for comp_config in page_config.get("components", []):
            # Create component using factory
            component = create_component(comp_config)
            components.append(component)

        # Create page
        page = Page(title=page_title, components=components)
        pages.append(page)

    # Create dashboard
    dashboard = Dashboard(
        title=dashboard_config.get("title", "Untitled Dashboard"),
        subtitle=dashboard_config.get("subtitle", ""),
        icon=dashboard_config.get("icon", "mdi:view-dashboard"),
        icon_color=dashboard_config.get("icon_color", "orange"),
        pages=pages
    )

    return dashboard

def save_dashboard_to_yaml(dashboard: Dashboard, path: str | Path) -> None:
    """
    Save dashboard to YAML configuration file.

    Args:
        dashboard: Dashboard instance to save
        path: Output YAML file path
    """
    path = Path(path)

    config = {
        "dashboard": {
            "title": dashboard.title,
            "subtitle": dashboard.subtitle,
            "icon": dashboard.icon,
            "icon_color": dashboard.icon_color,
        },
        "pages": []
    }

    for page in dashboard.pages:
        page_config = {
            "title": page.title,
            "components": [
                comp.to_metadata() for comp in page.components
            ]
        }
        config["pages"].append(page_config)

    with open(path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
```

### 3. JSON API Support

```python
# depictio/api/v1/endpoints/dashboards_endpoints/routes.py

from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from depictio.models.components.dashboard import Dashboard
from depictio.models.components.registry import create_component

@router.post("/dashboards/create-declarative", response_model=dict)
async def create_dashboard_from_config(
    config: Dict[str, Any],
    user: dict = Depends(get_current_user)
):
    """
    Create dashboard from declarative JSON configuration.

    Request body:
    {
        "dashboard": {
            "title": "My Dashboard",
            "subtitle": "Description",
            "project_id": "..."
        },
        "pages": [
            {
                "title": "Page 1",
                "components": [
                    {
                        "type": "card",
                        "title": "Total Samples",
                        "wf_id": "...",
                        "dc_id": "...",
                        "column_name": "sample",
                        "aggregation": "count"
                    }
                ]
            }
        ]
    }

    Returns:
        {
            "dashboard_id": "...",
            "status": "created",
            "component_count": 5
        }
    """
    try:
        # Parse and validate dashboard configuration
        dashboard_config = config.get("dashboard", {})

        # Validate components
        all_components = []
        for page_config in config.get("pages", []):
            for comp_data in page_config.get("components", []):
                component = create_component(comp_data)
                all_components.append(component)

        # Create dashboard data model for storage
        dashboard_data = DashboardData(
            title=dashboard_config["title"],
            subtitle=dashboard_config.get("subtitle", ""),
            icon=dashboard_config.get("icon", "mdi:view-dashboard"),
            project_id=dashboard_config["project_id"],
            stored_metadata=[c.to_metadata() for c in all_components],
            declarative_config=config,  # Store original config
            config_format="json",
            permissions={"owner": user["user_id"]},
            last_saved_ts=datetime.now().isoformat()
        )

        # Save to MongoDB
        await dashboard_data.insert()

        return {
            "dashboard_id": str(dashboard_data.id),
            "status": "created",
            "component_count": len(all_components)
        }

    except ValidationError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid component configuration: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create dashboard: {e}"
        )

@router.get("/dashboards/{dashboard_id}/export-yaml")
async def export_dashboard_to_yaml(
    dashboard_id: str,
    user: dict = Depends(get_current_user)
):
    """
    Export dashboard to YAML configuration.

    Returns YAML string that can be saved to file.
    """
    # Fetch dashboard
    dashboard_data = await DashboardData.get(dashboard_id)

    if not dashboard_data:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    # Check permissions
    # ... permission check logic

    # Convert to YAML
    if dashboard_data.declarative_config:
        # Use stored config
        config = dashboard_data.declarative_config
    else:
        # Reconstruct from stored_metadata (legacy dashboards)
        config = {
            "dashboard": {
                "title": dashboard_data.title,
                "subtitle": dashboard_data.subtitle,
                "icon": dashboard_data.icon
            },
            "pages": [{
                "title": "Main",
                "components": dashboard_data.stored_metadata
            }]
        }

    yaml_string = yaml.dump(config, default_flow_style=False, sort_keys=False)

    return {"yaml": yaml_string}
```

---

## Component Registry & Factory Pattern

```python
# depictio/models/components/registry.py

from typing import Dict, Type, Any
from .base import BaseComponent
from .card import CardComponent
from .interactive import InteractiveComponent

# Global component registry
COMPONENT_REGISTRY: Dict[str, Type[BaseComponent]] = {
    "card": CardComponent,
    "interactive": InteractiveComponent,
    # Future additions:
    # "figure": FigureComponent,
    # "table": TableComponent,
}

def register_component(name: str, component_class: Type[BaseComponent]) -> None:
    """
    Register a new component type.

    Allows plugins and extensions to add custom component types.

    Args:
        name: Component type identifier
        component_class: Component class (must inherit from BaseComponent)

    Example:
        >>> class CustomGaugeComponent(BaseComponent):
        ...     # Implementation
        >>> register_component("gauge", CustomGaugeComponent)
    """
    if not issubclass(component_class, BaseComponent):
        raise TypeError(
            f"Component class must inherit from BaseComponent, got {component_class}"
        )

    COMPONENT_REGISTRY[name] = component_class

def get_component_class(component_type: str) -> Type[BaseComponent]:
    """
    Get component class by type name.

    Args:
        component_type: Component type identifier

    Returns:
        Component class

    Raises:
        ValueError: If component type not registered
    """
    if component_type not in COMPONENT_REGISTRY:
        raise ValueError(
            f"Unknown component type: '{component_type}'. "
            f"Available types: {list(COMPONENT_REGISTRY.keys())}"
        )

    return COMPONENT_REGISTRY[component_type]

def create_component(config: Dict[str, Any]) -> BaseComponent:
    """
    Factory function to create component from configuration dict.

    Args:
        config: Component configuration dictionary
               Must contain 'type' or 'component_type' key

    Returns:
        Validated component instance

    Raises:
        ValueError: If component type unknown
        ValidationError: If configuration invalid

    Example:
        >>> config = {
        ...     "type": "card",
        ...     "title": "Total Samples",
        ...     "wf_id": "workflow-1",
        ...     "dc_id": "metadata",
        ...     "column_name": "sample",
        ...     "aggregation": "count"
        ... }
        >>> card = create_component(config)
    """
    # Get component type (support both 'type' and 'component_type' keys)
    component_type = config.get("component_type") or config.get("type")

    if not component_type:
        raise ValueError("Configuration must specify 'type' or 'component_type'")

    # Get component class
    component_class = get_component_class(component_type)

    # Prepare config (remove 'type' key if present, keep 'component_type')
    config_clean = config.copy()
    if "type" in config_clean and "component_type" not in config_clean:
        config_clean["component_type"] = config_clean.pop("type")
    elif "type" in config_clean:
        config_clean.pop("type")

    # Instantiate and validate
    return component_class(**config_clean)

def list_component_types() -> List[str]:
    """Get list of registered component types."""
    return list(COMPONENT_REGISTRY.keys())

def get_component_schema(component_type: str) -> Dict[str, Any]:
    """
    Get JSON schema for component type.

    Useful for documentation and frontend validation.

    Args:
        component_type: Component type identifier

    Returns:
        JSON schema dict
    """
    component_class = get_component_class(component_type)
    return component_class.model_json_schema()
```

---

## Dashboard & Page Orchestration

```python
# depictio/models/components/dashboard.py

from typing import List, Optional, Any
from pydantic import BaseModel, Field
from dash import Dash
import dash_mantine_components as dmc
from .base import BaseComponent

class Page(BaseModel):
    """
    Dashboard page containing multiple components.

    Example:
        >>> page = Page(
        ...     title="Overview",
        ...     components=[card1, card2, filter1]
        ... )
    """
    title: str
    components: List[BaseComponent] = Field(default_factory=list)
    layout_type: str = Field("grid", description="Layout type (grid, flex, custom)")

    def add_component(self, component: BaseComponent) -> None:
        """Add component to page."""
        self.components.append(component)

    def build(self, **context) -> Any:
        """
        Build page layout with all components.

        Returns:
            Dash component tree for the page
        """
        # Build all components
        component_uis = []
        for component in self.components:
            component_ui = component.build(**context)
            component_uis.append(component_ui)

        # Wrap in layout (grid or other)
        if self.layout_type == "grid":
            # Use react-grid-layout
            from depictio.dash.layouts.draggable import create_draggable_grid
            return create_draggable_grid(component_uis, self.components)
        else:
            # Simple stack layout
            return dmc.Stack(children=component_uis, gap="md")

class Dashboard(BaseModel):
    """
    Top-level dashboard orchestrator.

    Manages:
    - Dashboard metadata (title, icon, etc.)
    - Pages and components
    - Callback registration
    - App building

    Example:
        >>> dashboard = Dashboard(
        ...     title="Analytics Dashboard",
        ...     pages=[overview_page, details_page]
        ... )
        >>> app = dashboard.build()
        >>> app.run(debug=True)
    """
    title: str
    subtitle: str = ""
    icon: str = "mdi:view-dashboard"
    icon_color: str = "orange"
    pages: List[Page] = Field(default_factory=list)

    # MongoDB reference (if saved)
    dashboard_id: Optional[str] = None
    project_id: Optional[str] = None

    def add_page(self, page: Page) -> None:
        """Add page to dashboard."""
        self.pages.append(page)

    def add_component(self, component: BaseComponent, page_index: int = 0) -> None:
        """
        Add component to specific page.

        Args:
            component: Component to add
            page_index: Page index (default: 0, first page)
        """
        if not self.pages:
            # Create default page
            self.pages.append(Page(title="Main"))

        self.pages[page_index].add_component(component)

    def get_all_components(self) -> List[BaseComponent]:
        """Get flat list of all components across all pages."""
        components = []
        for page in self.pages:
            components.extend(page.components)
        return components

    def build(self, register_callbacks: bool = True, **context) -> Dash:
        """
        Build complete Dash application.

        Args:
            register_callbacks: Whether to auto-register component callbacks
            **context: Additional context passed to components

        Returns:
            Dash app instance
        """
        from dash import Dash
        import dash_mantine_components as dmc

        # Create Dash app
        app = Dash(__name__)

        # Build layout
        if len(self.pages) == 1:
            # Single page - direct layout
            app.layout = self.pages[0].build(**context)
        else:
            # Multi-page - tabs
            tabs = []
            for page in self.pages:
                tab_content = page.build(**context)
                tab = dmc.TabsPanel(children=tab_content, value=page.title)
                tabs.append(tab)

            app.layout = dmc.Tabs(
                children=tabs,
                value=self.pages[0].title if self.pages else None
            )

        # Register callbacks
        if register_callbacks:
            for component in self.get_all_components():
                component.register_callbacks(app)

        return app

    def to_dashboard_data(self) -> "DashboardData":
        """
        Convert to DashboardData model for MongoDB storage.

        Returns:
            DashboardData instance ready for database insertion
        """
        from depictio.models.models.dashboards import DashboardData

        return DashboardData(
            title=self.title,
            subtitle=self.subtitle,
            icon=self.icon,
            icon_color=self.icon_color,
            stored_metadata=[
                comp.to_metadata()
                for comp in self.get_all_components()
            ],
            declarative_config={
                "dashboard": {
                    "title": self.title,
                    "subtitle": self.subtitle,
                    "icon": self.icon,
                    "icon_color": self.icon_color
                },
                "pages": [
                    {
                        "title": page.title,
                        "components": [
                            comp.to_metadata()
                            for comp in page.components
                        ]
                    }
                    for page in self.pages
                ]
            },
            config_format="python",
            dashboard_id=self.dashboard_id,
            project_id=self.project_id
        )

    @classmethod
    def from_dashboard_data(cls, dashboard_data: "DashboardData") -> "Dashboard":
        """
        Create Dashboard from DashboardData MongoDB document.

        Args:
            dashboard_data: DashboardData instance from database

        Returns:
            Dashboard instance
        """
        from depictio.models.components.registry import create_component

        # Use declarative config if available
        if dashboard_data.declarative_config:
            config = dashboard_data.declarative_config

            pages = []
            for page_config in config.get("pages", []):
                components = [
                    create_component(comp_data)
                    for comp_data in page_config.get("components", [])
                ]
                pages.append(Page(
                    title=page_config.get("title", "Main"),
                    components=components
                ))

            return cls(
                title=config["dashboard"]["title"],
                subtitle=config["dashboard"].get("subtitle", ""),
                icon=config["dashboard"].get("icon", "mdi:view-dashboard"),
                icon_color=config["dashboard"].get("icon_color", "orange"),
                pages=pages,
                dashboard_id=str(dashboard_data.id),
                project_id=str(dashboard_data.project_id)
            )
        else:
            # Legacy: reconstruct from stored_metadata
            components = [
                create_component(metadata)
                for metadata in dashboard_data.stored_metadata
            ]

            page = Page(title="Main", components=components)

            return cls(
                title=dashboard_data.title,
                subtitle=dashboard_data.subtitle,
                icon=dashboard_data.icon,
                icon_color=dashboard_data.icon_color,
                pages=[page],
                dashboard_id=str(dashboard_data.id),
                project_id=str(dashboard_data.project_id)
            )
```

---

## Callback Registration Strategies

### Strategy A: Auto-Registration (Simplest)

**Pros:**
- Zero configuration required
- Consistent callback behavior
- Easy to understand and maintain

**Cons:**
- Less flexible for custom interactions
- All callbacks registered even if not needed

**Implementation:**

```python
# In Dashboard.build()
for component in self.get_all_components():
    component.register_callbacks(app)

# In CardComponent
def register_callbacks(self, app: Dash) -> None:
    from depictio.dash.modules.card_component.callbacks.core import (
        register_card_callbacks
    )
    register_card_callbacks(app, self.index)
```

### Strategy B: Declarative Callback Hooks (Vizro-Style)

**Pros:**
- Flexible custom interactions
- Declarative configuration
- Powerful for advanced users

**Cons:**
- More complex API
- Requires understanding of callback system

**Implementation:**

```python
from typing import Callable, Optional

class CardComponent(BaseComponent):
    # Callback hooks
    on_click: Optional[Callable] = None
    on_value_change: Optional[Callable] = None
    on_hover: Optional[Callable] = None

    def register_callbacks(self, app: Dash) -> None:
        # Register standard callbacks
        super().register_callbacks(app)

        # Register custom hooks
        if self.on_click:
            @app.callback(
                Output({"type": "card-container", "index": self.index}, "className"),
                Input({"type": "card-container", "index": self.index}, "n_clicks")
            )
            def handle_click(n_clicks):
                return self.on_click(n_clicks)

        if self.on_value_change:
            @app.callback(
                Output({"type": "notification", "index": self.index}, "children"),
                Input({"type": "card-value", "index": self.index}, "children")
            )
            def handle_value_change(value):
                return self.on_value_change(value)

# Usage
def alert_on_click(n_clicks):
    if n_clicks:
        return "card-clicked"
    return ""

card = CardComponent(
    title="Interactive Card",
    on_click=alert_on_click,
    # ... other params
)
```

### Strategy C: Action System (Most Powerful)

**Pros:**
- Highly composable
- YAML-friendly
- Framework for inter-component communication

**Cons:**
- Most complex to implement
- Requires action handler infrastructure

**Implementation:**

```python
from typing import List, Literal, Optional
from pydantic import BaseModel

class Action(BaseModel):
    """
    Declarative action that triggers on component events.

    Example:
        >>> # When card is clicked, filter a figure
        >>> Action(
        ...     type="filter",
        ...     target="figure-123",
        ...     trigger="on_click"
        ... )
    """
    type: Literal["filter", "navigate", "export", "update", "custom"]
    trigger: Literal["on_click", "on_change", "on_hover", "on_load"] = "on_click"
    target: Optional[str] = None  # Target component index
    parameters: Dict[str, Any] = {}
    function: Optional[Callable] = None  # Custom function for type="custom"

class CardComponent(BaseComponent):
    actions: List[Action] = Field(default_factory=list)

    def register_callbacks(self, app: Dash) -> None:
        # Register standard callbacks
        super().register_callbacks(app)

        # Register action handlers
        for action in self.actions:
            self._register_action(app, action)

    def _register_action(self, app: Dash, action: Action) -> None:
        """Register callback for a specific action."""
        if action.type == "filter":
            @app.callback(
                Output({"type": "figure-trigger", "index": action.target}, "data"),
                Input({"type": "card-container", "index": self.index}, "n_clicks")
            )
            def trigger_filter(n_clicks):
                if n_clicks:
                    return {"filter": action.parameters}
                return {}

        elif action.type == "navigate":
            # Navigate to another page
            pass

        elif action.type == "custom":
            # Execute custom function
            pass

# Usage in YAML:
"""
- type: card
  title: "Total Samples"
  wf_id: "workflow-1"
  dc_id: "metadata"
  column_name: "sample"
  aggregation: "count"
  actions:
    - type: filter
      trigger: on_click
      target: "figure-overview"
      parameters:
        column: "sample"
        operator: ">"
        value: 100
"""
```

**Recommendation:** Start with **Strategy A (Auto-Registration)** for MVP, add **Strategy B (Hooks)** for custom use cases.

---

## Integration with Existing System

### Extend DashboardData Model

```python
# depictio/models/models/dashboards.py

class DashboardData(MongoModel):
    # ... existing fields ...

    # NEW: Store declarative configuration
    declarative_config: Optional[Dict[str, Any]] = Field(
        None,
        description="Original declarative configuration (YAML/JSON/Python)"
    )

    config_format: Optional[Literal["yaml", "json", "python"]] = Field(
        None,
        description="Format of declarative config"
    )

    # NEW: Schema version for migrations
    config_version: int = Field(
        1,
        description="Configuration schema version"
    )

    def to_dashboard_object(self) -> "Dashboard":
        """
        Convert stored data to Dashboard object.

        Returns:
            Dashboard instance with all components
        """
        from depictio.models.components.dashboard import Dashboard
        return Dashboard.from_dashboard_data(self)

    @classmethod
    def from_dashboard_object(cls, dashboard: "Dashboard", **kwargs) -> "DashboardData":
        """
        Create DashboardData from Dashboard object.

        Args:
            dashboard: Dashboard instance
            **kwargs: Additional DashboardData fields (project_id, permissions, etc.)

        Returns:
            DashboardData instance
        """
        dashboard_data = dashboard.to_dashboard_data()

        # Merge additional fields
        for key, value in kwargs.items():
            setattr(dashboard_data, key, value)

        return dashboard_data
```

### Backward Compatibility Strategy

**Existing dashboards continue to work:**
- `stored_metadata` field remains primary source of truth
- `declarative_config` is optional enhancement
- Existing `build_card()`, `build_interactive()` functions still work
- New system calls these functions internally

**Migration path:**
1. New dashboards created with declarative system
2. Existing dashboards can be "upgraded" by calling:
   ```python
   dashboard_data = await DashboardData.get(dashboard_id)
   dashboard_obj = dashboard_data.to_dashboard_object()
   dashboard_obj.to_dashboard_data()  # Adds declarative_config
   ```

---

## CLI Integration

```python
# depictio/cli/dashboard_cli.py

import typer
from pathlib import Path
from depictio.dash.config.yaml_loader import load_dashboard_from_yaml

app = typer.Typer(help="Dashboard management commands")

@app.command()
def create(
    yaml_path: Path = typer.Argument(..., help="Path to YAML dashboard definition"),
    project_id: str = typer.Option(..., help="Project ID to associate dashboard with"),
    api_url: str = typer.Option("http://localhost:8000", help="API base URL")
):
    """
    Create dashboard from YAML definition.

    Example:
        depictio dashboard create dashboards/analytics.yaml --project-id 123
    """
    # Load and validate YAML
    dashboard = load_dashboard_from_yaml(yaml_path)

    # Convert to API payload
    payload = {
        "dashboard": {
            "title": dashboard.title,
            "subtitle": dashboard.subtitle,
            "project_id": project_id
        },
        "pages": [
            {
                "title": page.title,
                "components": [
                    comp.to_metadata()
                    for comp in page.components
                ]
            }
            for page in dashboard.pages
        ]
    }

    # Call API
    response = requests.post(
        f"{api_url}/depictio/api/v1/dashboards/create-declarative",
        json=payload,
        headers=get_auth_headers()
    )

    if response.ok:
        data = response.json()
        typer.secho(
            f"✓ Dashboard created: {data['dashboard_id']}",
            fg=typer.colors.GREEN
        )
    else:
        typer.secho(f"✗ Error: {response.text}", fg=typer.colors.RED)

@app.command()
def export(
    dashboard_id: str = typer.Argument(..., help="Dashboard ID to export"),
    output: Path = typer.Option("dashboard.yaml", help="Output YAML file"),
    api_url: str = typer.Option("http://localhost:8000", help="API base URL")
):
    """
    Export dashboard to YAML definition.

    Example:
        depictio dashboard export 6903cea73b50da870e2ba4d7 -o my_dashboard.yaml
    """
    # Call API
    response = requests.get(
        f"{api_url}/depictio/api/v1/dashboards/{dashboard_id}/export-yaml",
        headers=get_auth_headers()
    )

    if response.ok:
        yaml_content = response.json()["yaml"]
        output.write_text(yaml_content)
        typer.secho(f"✓ Dashboard exported to {output}", fg=typer.colors.GREEN)
    else:
        typer.secho(f"✗ Error: {response.text}", fg=typer.colors.RED)

@app.command()
def validate(
    yaml_path: Path = typer.Argument(..., help="Path to YAML dashboard definition")
):
    """
    Validate YAML dashboard definition without creating it.

    Example:
        depictio dashboard validate dashboards/analytics.yaml
    """
    try:
        dashboard = load_dashboard_from_yaml(yaml_path)

        typer.secho("✓ YAML is valid", fg=typer.colors.GREEN)
        typer.echo(f"  Title: {dashboard.title}")
        typer.echo(f"  Pages: {len(dashboard.pages)}")
        typer.echo(f"  Total Components: {len(dashboard.get_all_components())}")

        # Show component breakdown
        for i, page in enumerate(dashboard.pages):
            typer.echo(f"  Page {i+1} '{page.title}': {len(page.components)} components")
            for comp in page.components:
                typer.echo(f"    - {comp.component_type}: {comp.title}")

    except Exception as e:
        typer.secho(f"✗ Validation failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)
```

---

## Testing Strategy

### Unit Tests

```python
# tests/test_declarative_components.py

import pytest
from pydantic import ValidationError
from depictio.models.components.card import CardComponent
from depictio.models.components.interactive import InteractiveComponent

def test_card_component_validation():
    """Test card component Pydantic validation."""
    # Valid configuration
    card = CardComponent(
        title="Total Samples",
        wf_id="workflow-1",
        dc_id="metadata",
        column_name="sample",
        aggregation="count"
    )

    assert card.component_type == "card"
    assert card.title == "Total Samples"
    assert len(card.index) == 36  # UUID format

def test_card_component_invalid_aggregation():
    """Test validation error for invalid aggregation."""
    with pytest.raises(ValidationError):
        CardComponent(
            title="Test",
            wf_id="w1",
            dc_id="d1",
            column_name="col",
            aggregation="invalid"  # Should fail
        )

def test_card_component_color_validation():
    """Test hex color validation."""
    # Valid hex color
    card = CardComponent(
        title="Test",
        wf_id="w1",
        dc_id="d1",
        column_name="col",
        aggregation="count",
        background_color="#3b82f6"
    )
    assert card.background_color == "#3b82f6"

    # Invalid color format
    with pytest.raises(ValidationError):
        CardComponent(
            title="Test",
            wf_id="w1",
            dc_id="d1",
            column_name="col",
            aggregation="count",
            background_color="blue"  # Should be hex
        )

def test_interactive_component_validation():
    """Test interactive component validation."""
    filter_comp = InteractiveComponent(
        title="Habitat Filter",
        wf_id="workflow-1",
        dc_id="metadata",
        column_name="habitat",
        interactive_component_type="MultiSelect"
    )

    assert filter_comp.component_type == "interactive"
    assert filter_comp.interactive_component_type == "MultiSelect"

def test_component_metadata_export():
    """Test to_metadata() conversion."""
    card = CardComponent(
        title="Test Card",
        wf_id="w1",
        dc_id="d1",
        column_name="sample",
        aggregation="count",
        background_color="#3b82f6"
    )

    metadata = card.to_metadata()

    assert metadata["component_type"] == "card"
    assert metadata["title"] == "Test Card"
    assert metadata["aggregation"] == "count"
    assert metadata["background_color"] == "#3b82f6"

def test_component_from_metadata():
    """Test from_metadata() reconstruction."""
    metadata = {
        "component_type": "card",
        "index": "test-123",
        "title": "Test Card",
        "wf_id": "w1",
        "dc_id": "d1",
        "column_name": "sample",
        "aggregation": "count"
    }

    card = CardComponent.from_metadata(metadata)

    assert card.title == "Test Card"
    assert card.index == "test-123"
    assert card.aggregation == "count"
```

### Integration Tests

```python
# tests/test_yaml_loader.py

import pytest
from pathlib import Path
from depictio.dash.config.yaml_loader import load_dashboard_from_yaml

@pytest.fixture
def sample_yaml(tmp_path):
    """Create sample YAML dashboard config."""
    yaml_content = """
dashboard:
  title: "Test Dashboard"
  subtitle: "Testing"

pages:
  - title: "Overview"
    components:
      - type: card
        title: "Total Samples"
        wf_id: "workflow-1"
        dc_id: "metadata"
        column_name: "sample"
        aggregation: "count"

      - type: interactive
        title: "Habitat Filter"
        wf_id: "workflow-1"
        dc_id: "metadata"
        column_name: "habitat"
        interactive_component_type: "MultiSelect"
"""

    yaml_file = tmp_path / "test_dashboard.yaml"
    yaml_file.write_text(yaml_content)
    return yaml_file

def test_load_dashboard_from_yaml(sample_yaml):
    """Test loading dashboard from YAML."""
    dashboard = load_dashboard_from_yaml(sample_yaml)

    assert dashboard.title == "Test Dashboard"
    assert dashboard.subtitle == "Testing"
    assert len(dashboard.pages) == 1
    assert len(dashboard.pages[0].components) == 2

    # Check component types
    components = dashboard.pages[0].components
    assert components[0].component_type == "card"
    assert components[1].component_type == "interactive"

def test_invalid_yaml_format(tmp_path):
    """Test error handling for invalid YAML."""
    invalid_yaml = tmp_path / "invalid.yaml"
    invalid_yaml.write_text("not: valid: yaml: format:")

    with pytest.raises(ValueError):
        load_dashboard_from_yaml(invalid_yaml)
```

### E2E Tests

```python
# tests/e2e/test_declarative_dashboard.py

import pytest
from playwright.sync_api import Page, expect
from depictio.models.components import CardComponent, Dashboard, Page as DashPage

def test_declarative_dashboard_renders(page: Page, test_dashboard_url):
    """Test that declaratively-defined dashboard renders correctly."""
    # Create dashboard programmatically
    card = CardComponent(
        title="Total Samples",
        wf_id="test-workflow",
        dc_id="test-data",
        column_name="sample",
        aggregation="count"
    )

    dashboard = Dashboard(
        title="E2E Test Dashboard",
        pages=[DashPage(title="Main", components=[card])]
    )

    # Build and start app (in test fixture)
    # ... app setup code

    # Navigate to dashboard
    page.goto(test_dashboard_url)

    # Wait for card to render
    expect(page.locator("text=Total Samples")).to_be_visible()
    expect(page.locator('[data-component-type="card"]')).to_be_visible()
```

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1)
- [ ] Create base component infrastructure
  - [ ] `depictio/models/components/base.py`
  - [ ] `depictio/models/components/registry.py`
  - [ ] Unit tests for base classes
- [ ] Set up component factory pattern
- [ ] Create JSON schema generation utilities

### Phase 2: Card & Interactive Models (Week 1-2)
- [ ] Implement `CardComponent` with full validation
- [ ] Implement `InteractiveComponent` with type-specific validation
- [ ] Add `build()` methods calling existing functions
- [ ] Add `register_callbacks()` methods
- [ ] Unit tests for both components

### Phase 3: Configuration Loaders (Week 2)
- [ ] Implement YAML parser (`yaml_loader.py`)
- [ ] Add JSON API endpoint for dashboard creation
- [ ] Create Python API helper functions
- [ ] Integration tests for all formats

### Phase 4: Dashboard Orchestration (Week 2-3)
- [ ] Implement `Page` class
- [ ] Implement `Dashboard` class with `build()` method
- [ ] Add callback auto-registration system
- [ ] Test multi-page dashboards

### Phase 5: MongoDB Integration (Week 3)
- [ ] Extend `DashboardData` model with `declarative_config`
- [ ] Add `to_dashboard_object()` and `from_dashboard_object()` methods
- [ ] Create migration utility for legacy dashboards
- [ ] Test save/restore flows

### Phase 6: CLI & API Endpoints (Week 3)
- [ ] Add `depictio dashboard create` CLI command
- [ ] Add `depictio dashboard validate` CLI command
- [ ] Add `depictio dashboard export` CLI command
- [ ] Create FastAPI endpoints for declarative creation

### Phase 7: Documentation & Examples (Week 4)
- [ ] Write YAML dashboard examples
- [ ] Create Python API usage guide
- [ ] Document component schemas
- [ ] Migration guide for existing dashboards
- [ ] Tutorial videos/screenshots

### Phase 8: Testing & Polish (Week 4)
- [ ] Comprehensive unit test coverage (>90%)
- [ ] Integration tests for all workflows
- [ ] E2E tests with Playwright
- [ ] Performance benchmarking
- [ ] Type checking with `ty`
- [ ] Pre-commit hooks validation

---

## Files to Create

### New Files

```
depictio/models/components/
├── __init__.py                    # Exports: CardComponent, InteractiveComponent, Dashboard, Page
├── base.py                        # BaseComponent, GridPosition
├── card.py                        # CardComponent
├── interactive.py                 # InteractiveComponent
├── dashboard.py                   # Dashboard, Page
└── registry.py                    # COMPONENT_REGISTRY, create_component()

depictio/dash/config/
├── __init__.py
├── yaml_loader.py                 # load_dashboard_from_yaml(), save_dashboard_to_yaml()
└── dashboard_builder.py           # Helper functions for building dashboards

depictio/cli/commands/
└── dashboard_cli.py               # CLI commands for dashboard management

examples/declarative_dashboards/
├── basic_dashboard.yaml           # Simple card + filter example
├── advanced_dashboard.yaml        # Multi-page, complex layout
├── python_api_example.py          # Python API usage
└── README.md                      # Usage instructions

tests/
├── test_components/
│   ├── test_base_component.py
│   ├── test_card_component.py
│   └── test_interactive_component.py
├── test_config/
│   ├── test_yaml_loader.py
│   └── test_component_registry.py
└── test_integration/
    └── test_declarative_dashboard_e2e.py
```

### Modified Files

```
depictio/models/models/dashboards.py
  + Add declarative_config field
  + Add config_format field
  + Add to_dashboard_object() method
  + Add from_dashboard_object() classmethod

depictio/api/v1/endpoints/dashboards_endpoints/routes.py
  + Add POST /dashboards/create-declarative endpoint
  + Add GET /dashboards/{id}/export-yaml endpoint

depictio/dash/modules/card_component/callbacks/core.py
  + Extract register_card_callbacks() function

depictio/dash/modules/interactive_component/callbacks/core.py
  + Extract register_interactive_callbacks() function
```

---

## Success Criteria

### MVP Definition
- [ ] Card and Interactive components can be defined via Python API
- [ ] YAML dashboards can be loaded and rendered
- [ ] Components auto-register callbacks
- [ ] Backward compatibility with existing dashboards
- [ ] All tests pass (unit, integration, E2E)
- [ ] Type checking passes with `ty`

### Nice-to-Have Features
- [ ] Callback hook system (Strategy B)
- [ ] Action system (Strategy C)
- [ ] Dashboard templates library
- [ ] Visual YAML editor
- [ ] Dashboard versioning and rollback

---

## Open Questions

1. **Callback Strategy**: Which approach to prioritize?
   - Recommendation: Start with auto-registration (A), add hooks (B) later

2. **Grid Layout Configuration**: How to specify component positioning?
   - Option 1: Explicit grid_position in each component
   - Option 2: Auto-layout with hints (flex, grid)
   - Recommendation: Both - explicit for full control, auto for quick setup

3. **Data Source Integration**: How to reference data collections in YAML?
   - Option 1: Reference by ID (requires prior setup)
   - Option 2: Inline data source definition
   - Recommendation: Reference by ID for MVP, inline for future

4. **Theme/Styling**: How to apply consistent theming?
   - Option 1: Global theme config in dashboard
   - Option 2: Component-level overrides
   - Recommendation: Both - global theme + overrides

---

## Comparison to Vizro

| Feature | Vizro | Depictio (Proposed) |
|---------|-------|---------------------|
| Declarative Config | ✅ YAML/Python | ✅ YAML/Python/JSON |
| Pydantic Models | ✅ Yes | ✅ Yes |
| Component Types | Charts, Tables, Cards, Buttons | Cards, Interactives (Filters), Figures (future) |
| Callback Auto-Registration | ✅ Yes | ✅ Yes |
| Custom Callbacks | ✅ Yes | 🔄 Phase 2 |
| Multi-Page | ✅ Yes | ✅ Yes |
| Theming | ✅ Built-in themes | ✅ DMC 2.0 themes |
| Data Management | Data manager | Delta tables + API |
| Persistence | File-based | MongoDB + S3 |
| CLI Support | Limited | ✅ Full CLI |

---

## Next Steps

1. **Review & Approve**: Get feedback on architecture design
2. **Start Implementation**: Begin with Phase 1 (base classes)
3. **Iterate**: Build incrementally, test frequently
4. **Document**: Write docs as code is developed
5. **Migrate**: Convert example dashboards to declarative format

---

## References

- **Vizro Documentation**: https://vizro.readthedocs.io/
- **Pydantic V2 Docs**: https://docs.pydantic.dev/latest/
- **Dash Mantine Components**: https://www.dash-mantine-components.com/
- **Existing Depictio Research**: See section "Current State Analysis" above

---

**End of Design Document**
