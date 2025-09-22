"""
Dashboard structure models for organizing components into sections and tabs.
Provides a hierarchical structure for dashboard layout management.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator

# Import available component configs (some may not exist yet)
try:
    from depictio.dash.modules.figure_component.utils import FigureComponentConfig
except ImportError:
    FigureComponentConfig = dict

try:
    from depictio.dash.modules.interactive_component.utils import InteractiveComponentConfig
except ImportError:
    InteractiveComponentConfig = dict

# Fallback config classes for components that don't have specific configs yet
CardComponentConfig = dict
TableComponentConfig = dict
TextComponentConfig = dict


class ComponentType(str, Enum):
    """Supported component types in the dashboard."""

    CARD = "card"
    FIGURE = "figure"
    TABLE = "table"
    INTERACTIVE = "interactive"
    TEXT = "text"
    MULTIQC = "multiqc"


class SectionType(str, Enum):
    """Supported section types based on component compatibility."""

    CARDS = "cards"  # Can contain card components
    CHARTS = "charts"  # Can contain figure components
    TABLES = "tables"  # Can contain table components
    INTERACTIVE = "interactive"  # Can contain interactive components
    TEXT = "text"  # Can contain text components
    MULTIQC = "multiqc"  # Can contain multiqc components
    MIXED = "mixed"  # Can contain any component type


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
    position: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Component position and layout info"
    )

    # Metadata
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")

    def __init__(self, **data):
        # Set timestamps if not provided
        if "created_at" not in data or data["created_at"] is None:
            data["created_at"] = datetime.now().isoformat()
        if "updated_at" not in data or data["updated_at"] is None:
            data["updated_at"] = datetime.now().isoformat()
        super().__init__(**data)


class DashboardSection(BaseModel):
    """A section within a dashboard tab containing related components."""

    id: str = Field(..., description="Unique identifier for the section")
    name: str = Field(..., description="Display name for the section")
    section_type: SectionType = Field(
        SectionType.MIXED, description="Type of section determining component compatibility"
    )

    # Section configuration
    components: List[DashboardComponent] = Field(
        default_factory=list, description="Components in this section"
    )

    # Section layout and styling
    layout_type: Optional[str] = Field("grid", description="Layout type (grid, stack, custom)")
    columns: Optional[int] = Field(2, description="Number of columns for grid layout")

    # Section metadata
    description: Optional[str] = Field(None, description="Optional description for the section")
    icon: Optional[str] = Field(None, description="Optional icon for the section")
    collapsible: Optional[bool] = Field(False, description="Whether section can be collapsed")
    collapsed: Optional[bool] = Field(False, description="Current collapse state")

    # Timestamps
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Section name cannot be empty")
        return v.strip()

    def __init__(self, **data):
        # Set timestamps if not provided
        if "created_at" not in data or data["created_at"] is None:
            data["created_at"] = datetime.now().isoformat()
        if "updated_at" not in data or data["updated_at"] is None:
            data["updated_at"] = datetime.now().isoformat()
        super().__init__(**data)

    def can_accept_component(self, component_type: ComponentType) -> bool:
        """Check if this section can accept a component of the given type."""
        if self.section_type == SectionType.MIXED:
            return True

        compatibility_map = {
            SectionType.CARDS: [ComponentType.CARD],
            SectionType.CHARTS: [ComponentType.FIGURE],
            SectionType.TABLES: [ComponentType.TABLE],
            SectionType.INTERACTIVE: [ComponentType.INTERACTIVE],
            SectionType.TEXT: [ComponentType.TEXT],
            SectionType.MULTIQC: [ComponentType.MULTIQC],
        }

        return component_type in compatibility_map.get(self.section_type, [])

    def add_component(self, component: DashboardComponent) -> bool:
        """Add a component to this section if compatible."""
        if not self.can_accept_component(component.type):
            return False

        # Ensure unique ID within section
        existing_ids = {comp.id for comp in self.components}
        if component.id in existing_ids:
            return False

        self.components.append(component)
        self.updated_at = datetime.now().isoformat()
        return True

    def remove_component(self, component_id: str) -> bool:
        """Remove a component by ID. Returns True if removed, False if not found."""
        for i, comp in enumerate(self.components):
            if comp.id == component_id:
                del self.components[i]
                self.updated_at = datetime.now().isoformat()
                return True
        return False

    def get_component_by_id(self, component_id: str) -> Optional[DashboardComponent]:
        """Get a component by its ID."""
        for comp in self.components:
            if comp.id == component_id:
                return comp
        return None


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
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Tab name cannot be empty")
        return v.strip()

    def __init__(self, **data):
        # Set timestamps if not provided
        if "created_at" not in data or data["created_at"] is None:
            data["created_at"] = datetime.now().isoformat()
        if "updated_at" not in data or data["updated_at"] is None:
            data["updated_at"] = datetime.now().isoformat()
        super().__init__(**data)

    def add_section(self, section: DashboardSection) -> bool:
        """Add a section to this tab."""
        # Ensure unique ID within tab
        existing_ids = {sec.id for sec in self.sections}
        if section.id in existing_ids:
            return False

        self.sections.append(section)
        self.updated_at = datetime.now().isoformat()
        return True

    def remove_section(self, section_id: str) -> bool:
        """Remove a section by ID. Returns True if removed, False if not found."""
        for i, section in enumerate(self.sections):
            if section.id == section_id:
                del self.sections[i]
                self.updated_at = datetime.now().isoformat()
                return True
        return False

    def get_section_by_id(self, section_id: str) -> Optional[DashboardSection]:
        """Get a section by its ID."""
        for section in self.sections:
            if section.id == section_id:
                return section
        return None


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

    def __init__(self, **data):
        # Set timestamps if not provided
        if "created_at" not in data or data["created_at"] is None:
            data["created_at"] = datetime.now().isoformat()
        if "updated_at" not in data or data["updated_at"] is None:
            data["updated_at"] = datetime.now().isoformat()
        super().__init__(**data)

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
        self.updated_at = datetime.now().isoformat()

    def remove_tab(self, tab_id: str) -> bool:
        """Remove a tab by ID. Returns True if removed, False if not found."""
        for i, tab in enumerate(self.tabs):
            if tab.id == tab_id:
                del self.tabs[i]
                self.updated_at = datetime.now().isoformat()
                return True
        return False

    def ensure_default_tab(self, dashboard_id: str) -> DashboardTab:
        """Ensure there's at least one default tab, create if necessary."""
        default_tab = self.get_default_tab()
        if default_tab:
            return default_tab

        # Create a default tab
        default_tab = DashboardTab(
            id=f"tab-{dashboard_id}-default",
            name="Main Dashboard",
            icon="📊",
            is_default=True,
            order=0,
            description="Default dashboard tab",
        )

        self.add_tab(default_tab)
        self.default_tab_id = default_tab.id
        return default_tab


class DashboardLoadResponse(BaseModel):
    """Response model for loading dashboard data with user permissions."""

    # Use forward reference to avoid circular imports
    dashboard_data: Optional["DashboardData"] = Field(None, description="Dashboard data model")
    edit_components_button: bool = Field(False, description="Whether edit mode is enabled")
    theme: str = Field("light", description="Dashboard theme")

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Convert to legacy dictionary format for backward compatibility."""
        result = {
            "dashboard_data": self.dashboard_data,
            "edit_components_button": self.edit_components_button,
            "theme": self.theme,
        }

        # Add dashboard-specific fields if dashboard_data exists
        if self.dashboard_data:
            # Convert the entire dashboard_data to dict and merge it
            dashboard_dict = self.dashboard_data.model_dump()
            result.update(dashboard_dict)
        else:
            result.update(
                {
                    "stored_add_button": {"count": 0},
                    "buttons_data": {},
                    "title": "Dashboard",
                    "icon": "mdi:view-dashboard-outline",
                    "permissions": {"owners": [], "viewers": []},
                    "project_id": None,
                }
            )

        return result

    class Config:
        arbitrary_types_allowed = True


# Forward reference to avoid circular imports
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from depictio.models.models.dashboards import DashboardData
