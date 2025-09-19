"""
Compatibility layer for bridging new tab-based dashboard structure with existing component metadata.

This module provides utilities to convert between the new structured approach and the
legacy metadata system used by existing dashboard components.
"""

from typing import Any, Dict, List, Optional

from depictio.models.dashboard_tab_structure import (
    CardComponentConfig,
    ComponentType,
    DashboardComponent,
    DashboardSection,
    DashboardTab,
    DashboardTabStructure,
    FigureComponentConfig,
    InteractiveComponentConfig,
    InteractiveControlType,
    TableComponentConfig,
    TextComponentConfig,
)


def create_sample_dashboard_structure() -> DashboardTabStructure:
    """
    Create a sample dashboard structure with the basic components for testing.
    This matches the current simplified dashboard_content.py structure.
    """

    # Create interactive filters
    score_filter = InteractiveComponentConfig(
        id="control-0",
        control_type=InteractiveControlType.RANGE_SLIDER,
        field="score",
        label="Score Range",
        min_value=1,
        max_value=100,
        step=1,
        default_value=[1, 100],
    )

    # Create metric cards
    metric_cards = [
        CardComponentConfig(
            id="metric-0",
            title="Count",
            metric_key="count",
            color="blue",
            icon="mdi:chart-box",
            format_type="int",
        ),
        CardComponentConfig(
            id="metric-1",
            title="Average",
            metric_key="average",
            color="blue",
            icon="mdi:chart-box",
            format_type="int",
        ),
        CardComponentConfig(
            id="metric-2",
            title="Total",
            metric_key="total",
            color="blue",
            icon="mdi:chart-box",
            format_type="int",
        ),
        CardComponentConfig(
            id="metric-3",
            title="Score",
            metric_key="score",
            color="blue",
            icon="mdi:chart-box",
            format_type="int",
        ),
    ]

    # Create chart component
    chart_config = FigureComponentConfig(
        id="chart-0",
        title="Data Visualization",
        chart_type="scatter",
        x_col="x_value",
        y_col="y_value",
    )

    # Convert to dashboard components
    metric_components = [
        DashboardComponent(
            id=card.id,
            type=ComponentType.CARD,
            config=card,
        )
        for card in metric_cards
    ]

    chart_component = DashboardComponent(
        id=chart_config.id,
        type=ComponentType.FIGURE,
        config=chart_config,
    )

    # Create sections
    metrics_section = DashboardSection(
        id="metrics-section",
        name="Metrics Overview",
        components=metric_components,
        layout_type="grid",
        columns=4,
        icon="material-symbols:analytics",
    )

    charts_section = DashboardSection(
        id="charts-section",
        name="Visualizations",
        components=[chart_component],
        layout_type="stack",
        icon="material-symbols:bar-chart",
    )

    # Create main tab
    overview_tab = DashboardTab(
        id="overview",
        name="Overview",
        icon="mdi:view-dashboard",
        is_default=True,
        filters=[score_filter],
        sections=[metrics_section, charts_section],
    )

    # Create tab structure
    return DashboardTabStructure(
        tabs=[overview_tab],
        default_tab_id="overview",
        version="2.0",
    )


def convert_tab_structure_to_legacy_metadata(
    tab_structure: DashboardTabStructure,
) -> List[Dict[str, Any]]:
    """
    Convert new tab structure to legacy metadata format for backward compatibility.
    Returns a list that can be used as stored_metadata.
    """
    metadata = []

    for tab in tab_structure.tabs:
        for section in tab.sections:
            for component in section.components:
                # Create legacy metadata entry
                meta_entry = {
                    "component_id": component.id,
                    "component_type": component.type.value,
                    "tab_id": tab.id,
                    "section_id": section.id,
                    "section_name": section.name,
                }

                # Add component-specific metadata
                if isinstance(component.config, dict):
                    meta_entry.update(component.config)
                else:
                    meta_entry.update(component.config.model_dump())

                metadata.append(meta_entry)

    return metadata


def convert_legacy_metadata_to_tab_structure(
    stored_metadata: List[Dict[str, Any]],
    stored_layout_data: Optional[List[Dict[str, Any]]] = None,
) -> DashboardTabStructure:
    """
    Convert legacy stored_metadata and stored_layout_data to new tab structure.
    This is used for migrating existing dashboards.
    """
    # Group metadata by tab and section
    tabs_data: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    for meta in stored_metadata:
        tab_id = meta.get("tab_id", "overview")
        section_id = meta.get("section_id", "default-section")

        if tab_id not in tabs_data:
            tabs_data[tab_id] = {}

        if section_id not in tabs_data[tab_id]:
            tabs_data[tab_id][section_id] = []

        tabs_data[tab_id][section_id].append(meta)

    # Build tab structure
    tabs = []
    for tab_id, sections_data in tabs_data.items():
        sections = []

        for section_id, components_meta in sections_data.items():
            components = []

            for comp_meta in components_meta:
                # Convert component metadata to new structure
                component = _convert_component_metadata(comp_meta)
                if component:
                    components.append(component)

            # Create section
            section_name = components_meta[0].get(
                "section_name", section_id.replace("-", " ").title()
            )
            section = DashboardSection(
                id=section_id,
                name=section_name,
                components=components,
            )
            sections.append(section)

        # Create tab
        tab = DashboardTab(
            id=tab_id,
            name=tab_id.replace("-", " ").title(),
            icon="mdi:view-dashboard",
            is_default=tab_id == "overview",
            filters=[],  # TODO: Extract filters from metadata if available
            sections=sections,
        )
        tabs.append(tab)

    return DashboardTabStructure(
        tabs=tabs,
        default_tab_id="overview"
        if any(t.id == "overview" for t in tabs)
        else tabs[0].id
        if tabs
        else None,
        version="2.0",
    )


def _convert_component_metadata(meta: Dict[str, Any]) -> Optional[DashboardComponent]:
    """Convert a single component metadata entry to new DashboardComponent format."""
    component_type = meta.get("component_type", "card")
    component_id = meta.get("component_id", f"comp-{hash(str(meta)) % 1000}")

    try:
        if component_type == "card":
            config = CardComponentConfig(
                id=component_id,
                title=meta.get("title", "Untitled Card"),
                metric_key=meta.get("metric_key"),
                color=meta.get("color", "blue"),
                icon=meta.get("icon", "mdi:chart-box"),
                workflow_id=meta.get("workflow_id"),
                data_collection_id=meta.get("data_collection_id"),
                column_name=meta.get("column_name"),
                description=meta.get("description"),
            )
            return DashboardComponent(id=component_id, type=ComponentType.CARD, config=config)

        elif component_type == "figure" or component_type == "chart":
            config = FigureComponentConfig(
                id=component_id,
                title=meta.get("title", "Untitled Chart"),
                chart_type=meta.get("chart_type", "scatter"),
                x_col=meta.get("x_col"),
                y_col=meta.get("y_col"),
                color_col=meta.get("color_col"),
                workflow_id=meta.get("workflow_id"),
                data_collection_id=meta.get("data_collection_id"),
                description=meta.get("description"),
            )
            return DashboardComponent(id=component_id, type=ComponentType.FIGURE, config=config)

        elif component_type == "table":
            config = TableComponentConfig(
                id=component_id,
                title=meta.get("title", "Untitled Table"),
                workflow_id=meta.get("workflow_id"),
                data_collection_id=meta.get("data_collection_id"),
                columns=meta.get("columns"),
                description=meta.get("description"),
            )
            return DashboardComponent(id=component_id, type=ComponentType.TABLE, config=config)

        elif component_type == "text":
            config = TextComponentConfig(
                id=component_id,
                title=meta.get("title"),
                content=meta.get("content", ""),
                content_type=meta.get("content_type", "markdown"),
            )
            return DashboardComponent(id=component_id, type=ComponentType.TEXT, config=config)

        else:
            # Fallback to generic configuration
            config = meta.copy()
            config["id"] = component_id
            return DashboardComponent(id=component_id, type=ComponentType.CARD, config=config)

    except Exception as e:
        # Log error and skip invalid component
        print(f"Error converting component metadata: {e}")
        return None


def get_component_by_legacy_index(
    tab_structure: DashboardTabStructure, component_type: str, index: int
) -> Optional[DashboardComponent]:
    """
    Get a component by legacy type and index format (e.g., "metric", 0).
    This helps maintain compatibility with existing callback patterns.
    """
    components_of_type = []

    for tab in tab_structure.tabs:
        for section in tab.sections:
            for component in section.components:
                if component.type.value == component_type:
                    components_of_type.append(component)

    if 0 <= index < len(components_of_type):
        return components_of_type[index]

    return None


def get_legacy_component_config(component: DashboardComponent) -> Dict[str, Any]:
    """
    Convert a DashboardComponent back to legacy configuration format.
    This is useful for existing component builders that expect the old format.
    """
    if isinstance(component.config, dict):
        return component.config

    # Convert Pydantic model to dict and add type information
    config = component.config.model_dump()
    config["component_type"] = component.type.value
    config["component_id"] = component.id

    return config
