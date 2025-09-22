"""
Dashboard creators module for creating sections, components, and filters.
Uses Pydantic models for type-safe dashboard element creation.
"""

from datetime import datetime
from typing import Any, Dict, Optional

import dash_mantine_components as dmc

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.utils import generate_unique_index
from depictio.models.models.dashboard_structure import (
    ComponentType,
    DashboardComponent,
    DashboardSection,
    SectionType,
)


def generate_component_id() -> str:
    """Generate a unique component ID."""
    return f"comp-{generate_unique_index()}"


def generate_section_id() -> str:
    """Generate a unique section ID."""
    return f"sect-{generate_unique_index()}"


def create_dashboard_component(
    component_type: ComponentType,
    config: Dict[str, Any],
    component_id: Optional[str] = None,
    position: Optional[Dict[str, Any]] = None,
) -> DashboardComponent:
    """
    Create a new dashboard component with the given configuration.

    Args:
        component_type: Type of component to create
        config: Component-specific configuration
        component_id: Optional custom component ID
        position: Optional position/layout information

    Returns:
        DashboardComponent instance
    """
    if component_id is None:
        component_id = generate_component_id()

    if position is None:
        position = {}

    component = DashboardComponent(
        id=component_id,
        type=component_type,
        config=config,
        position=position,
    )

    logger.info(f"🔧 CREATOR: Created {component_type} component with ID {component_id}")
    return component


def create_dashboard_section(
    name: str,
    section_type: SectionType = SectionType.MIXED,
    section_id: Optional[str] = None,
    description: Optional[str] = None,
    icon: Optional[str] = None,
    layout_type: str = "grid",
    columns: int = 2,
    collapsible: bool = False,
) -> DashboardSection:
    """
    Create a new dashboard section.

    Args:
        name: Display name for the section
        section_type: Type of section (determines component compatibility)
        section_id: Optional custom section ID
        description: Optional description
        icon: Optional icon
        layout_type: Layout type for the section
        columns: Number of columns for grid layout
        collapsible: Whether section can be collapsed

    Returns:
        DashboardSection instance
    """
    if section_id is None:
        section_id = generate_section_id()

    # Set default icon based on section type
    if icon is None:
        icon_map = {
            SectionType.CARDS: "📋",
            SectionType.CHARTS: "📊",
            SectionType.TABLES: "📋",
            SectionType.INTERACTIVE: "🎛️",
            SectionType.TEXT: "📝",
            SectionType.MULTIQC: "🔬",
            SectionType.MIXED: "📦",
        }
        icon = icon_map.get(section_type, "📦")

    section = DashboardSection(
        id=section_id,
        name=name,
        section_type=section_type,
        description=description,
        icon=icon,
        layout_type=layout_type,
        columns=columns,
        collapsible=collapsible,
    )

    logger.info(f"🔧 CREATOR: Created {section_type} section '{name}' with ID {section_id}")
    return section


def create_demo_component_config(component_type: ComponentType, **kwargs) -> Dict[str, Any]:
    """
    Create demo configuration for a component type.

    Args:
        component_type: Type of component
        **kwargs: Additional configuration parameters

    Returns:
        Configuration dictionary for the component
    """
    base_config = {
        "title": f"Demo {component_type.value.title()} Component",
        "created_at": datetime.now().isoformat(),
        **kwargs,
    }

    # Add type-specific demo configuration
    if component_type == ComponentType.CARD:
        base_config.update(
            {
                "value": "Demo Value",
                "unit": "units",
                "description": "This is a demo card component",
            }
        )
    elif component_type == ComponentType.FIGURE:
        base_config.update(
            {
                "chart_type": "bar",
                "data_source": "demo_data",
                "x_axis": "category",
                "y_axis": "value",
            }
        )
    elif component_type == ComponentType.TABLE:
        base_config.update(
            {
                "data_source": "demo_table",
                "columns": ["Column A", "Column B", "Column C"],
                "page_size": 10,
            }
        )
    elif component_type == ComponentType.INTERACTIVE:
        base_config.update(
            {
                "filter_type": "dropdown",
                "options": ["Option 1", "Option 2", "Option 3"],
                "default_value": "Option 1",
            }
        )
    elif component_type == ComponentType.TEXT:
        base_config.update(
            {
                "content": "This is demo text content for the component.",
                "format": "markdown",
            }
        )

    return base_config


def render_section_ui(
    section: DashboardSection,
    include_create_component_button: bool = True,
) -> dmc.Paper:
    """
    Render a dashboard section as a DMC component.

    Args:
        section: DashboardSection to render
        include_create_component_button: Whether to include create component button

    Returns:
        DMC Paper component representing the section
    """
    # Create section header
    section_header = dmc.Group(
        [
            dmc.Text(section.icon or "📦", size="lg"),
            dmc.Text(f"#{len(section.components) + 1}", fw="bold", c="blue"),
            dmc.Text(section.name, size="lg", fw="bold"),
            dmc.Badge(section.section_type.value, color="gray", size="sm"),
        ],
        justify="flex-start",
        align="center",
        gap="xs",
    )

    # Section description if available
    section_info = []
    if section.description:
        section_info.append(dmc.Text(section.description, size="sm", c="gray", mt="xs"))

    section_info.append(dmc.Text(f"Section ID: {section.id}", size="xs", c="gray", mt="xs"))

    # Components container
    components_content = []
    if section.components:
        for component in section.components:
            components_content.append(render_component_preview(component))
    else:
        components_content.append(
            dmc.Text(
                f"No {section.section_type.value} components yet. Use the button below to add components.",
                size="sm",
                c="gray",
                ta="center",
                p="md",
            )
        )

    # Create component button for this section
    section_controls = []
    if include_create_component_button:
        # Simple "Add Component" button - no dropdown, no component type restrictions
        create_button = dmc.Button(
            "Add Component",
            id={"type": "create-component-in-section", "section_id": section.id},
            leftSection=dmc.Text("➕"),
            variant="light",
            color="blue",
            size="sm",
            fullWidth=True,
        )
        # Add corresponding store for the debug button
        from dash import dcc

        debug_store = dcc.Store(
            id={"type": "debug-button-store", "section_id": section.id}, data={}
        )
        section_controls.append(create_button)
        section_controls.append(debug_store)

    # Build section content
    section_content = [
        section_header,
        *section_info,
    ]

    if section_controls:
        section_content.extend(
            [
                dmc.Divider(mt="md", mb="sm"),
                dmc.Stack(section_controls, gap="xs"),
            ]
        )

    if components_content:
        section_content.extend(
            [
                dmc.Divider(mt="md", mb="sm"),
                dmc.Stack(components_content, gap="sm"),
            ]
        )

    return dmc.Paper(
        id={"type": "dashboard-section", "section_id": section.id},
        children=section_content,
        p="md",
        radius="md",
        withBorder=True,
        mb="md",
    )


def render_component_preview(component: DashboardComponent) -> dmc.Paper:
    """
    Render a preview of a dashboard component.

    Args:
        component: DashboardComponent to render

    Returns:
        DMC Paper component showing component preview
    """
    return dmc.Paper(
        children=[
            dmc.Group(
                [
                    dmc.Text(get_component_icon(component.type), size="md"),
                    dmc.Text(f"{component.type.value.title()} Component", fw="bold"),
                    dmc.Badge(f"ID: {component.id[:8]}...", color="blue", size="xs"),
                ],
                justify="space-between",
                align="center",
            ),
            dmc.Text(
                f"Created: {component.created_at}",
                size="xs",
                c="gray",
                mt="xs",
            ),
        ],
        p="sm",
        radius="sm",
        withBorder=True,
    )


def get_compatible_component_types(section_type: SectionType) -> list[ComponentType]:
    """Get component types compatible with a section type."""
    if section_type == SectionType.MIXED:
        return list(ComponentType)

    compatibility_map = {
        SectionType.CARDS: [ComponentType.CARD],
        SectionType.CHARTS: [ComponentType.FIGURE],
        SectionType.TABLES: [ComponentType.TABLE],
        SectionType.INTERACTIVE: [ComponentType.INTERACTIVE],
        SectionType.TEXT: [ComponentType.TEXT],
        SectionType.MULTIQC: [ComponentType.MULTIQC],
    }

    return compatibility_map.get(section_type, [])


def get_component_icon(component_type: ComponentType) -> str:
    """Get icon for a component type."""
    icon_map = {
        ComponentType.CARD: "📋",
        ComponentType.FIGURE: "📊",
        ComponentType.TABLE: "📋",
        ComponentType.INTERACTIVE: "🎛️",
        ComponentType.TEXT: "📝",
        ComponentType.MULTIQC: "🔬",
    }
    return icon_map.get(component_type, "⚙️")
