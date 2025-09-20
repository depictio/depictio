"""
Minimal alternative to draggable.py without dash dynamic grid layout.
Simple row-based layout using basic DMC components.
"""

import dash_mantine_components as dmc
from dash import Input, Output, State, html

from depictio.api.v1.configs.logging_init import logger


def design_draggable_minimal(
    init_layout: dict,
    init_children: list[dict],
    dashboard_id: str,
    local_data: dict,
    cached_project_data: dict | None = None,
):
    """
    Minimal draggable layout with two panels:
    - Left panel (1/4): Filters with Create Filter button
    - Right panel (3/4): Sections with Create Section button
    """
    logger.info("🔧 MINIMAL: Creating two-panel minimal draggable layout")

    # Left Panel (1/4) - Filters
    create_filter_button = dmc.Button(
        "Create Filter",
        id="create-filter-button",
        leftSection=dmc.Text("🔍"),
        variant="filled",
        color="green",
        fullWidth=True,
        style={"marginBottom": "1rem"},
    )

    # Initial filter welcome message
    initial_filters = [
        dmc.Paper(
            children=[
                dmc.Text("Filters Panel", size="lg", w=600),
                dmc.Text("Click 'Create Filter' to add filters", size="sm", c="gray"),
            ],
            p="md",
            radius="md",
            withBorder=True,
            style={
                "backgroundColor": "var(--app-surface-color, #ffffff)",
                "color": "var(--app-text-color, #000000)",
                "border": "1px solid var(--app-border-color, #ddd)",
                "marginBottom": "0.5rem",
            },
        )
    ]

    filters_container = html.Div(
        children=initial_filters,
        id="filters-container",
        style={"width": "100%"},
    )

    left_panel = dmc.Paper(
        children=[
            dmc.Text("Filters", size="xl", w=700, style={"marginBottom": "1rem"}),
            create_filter_button,
            filters_container,
        ],
        p="lg",
        radius="md",
        withBorder=True,
        style={
            "height": "100%",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "color": "var(--app-text-color, #000000)",
            "border": "1px solid var(--app-border-color, #ddd)",
        },
    )

    # Right Panel (3/4) - Sections
    create_section_button = dmc.Button(
        "Create Section",
        id="create-section-button",
        leftSection=dmc.Text("📊"),
        variant="filled",
        color="blue",
        fullWidth=True,
        style={"marginBottom": "1rem"},
    )

    # Initial section welcome message
    initial_sections = [
        dmc.Paper(
            children=[
                dmc.Text("Sections Panel", size="lg", w=600),
                dmc.Text("Click 'Create Section' to add sections", size="sm", c="gray"),
            ],
            p="md",
            radius="md",
            withBorder=True,
            style={
                "backgroundColor": "var(--app-surface-color, #ffffff)",
                "color": "var(--app-text-color, #000000)",
                "border": "1px solid var(--app-border-color, #ddd)",
                "marginBottom": "0.5rem",
            },
        )
    ]

    sections_container = html.Div(
        children=initial_sections,
        id="sections-container",
        style={"width": "100%"},
    )

    right_panel = dmc.Paper(
        children=[
            dmc.Text("Sections", size="xl", w=700, style={"marginBottom": "1rem"}),
            create_section_button,
            sections_container,
        ],
        p="lg",
        radius="md",
        withBorder=True,
        style={
            "height": "100%",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "color": "var(--app-text-color, #000000)",
            "border": "1px solid var(--app-border-color, #ddd)",
        },
    )

    # Two-panel layout using DMC Grid
    main_container = html.Div(
        children=[
            dmc.Grid(
                children=[
                    dmc.GridCol(left_panel, span=3),  # 1/4 width (3/12)
                    dmc.GridCol(right_panel, span=9),  # 3/4 width (9/12)
                ],
                gutter="md",
                style={"height": "100%"},
            )
        ],
        id="minimal-draggable-container",
        style={
            "width": "100%",
            "height": "100%",
            "padding": "1rem",
            "backgroundColor": "var(--app-bg-color, #f8f9fa)",
        },
    )

    return main_container


def create_filter_component(text: str, index: int):
    """Create a filter component."""
    return dmc.Paper(
        id=f"filter-{index}",
        children=[
            dmc.Group(
                children=[
                    dmc.Text("🔍", size="lg"),
                    dmc.Text(f"#{index + 1}", w=700, c="green"),
                    dmc.Text(text, size="md"),
                ],
                justify="flex-start",
                align="center",
                gap="xs",
            ),
            dmc.Text(
                f"Filter ID: filter-{index}", size="xs", c="gray", style={"marginTop": "0.5rem"}
            ),
        ],
        p="md",
        radius="md",
        withBorder=True,
        style={
            "marginBottom": "0.5rem",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "color": "var(--app-text-color, #000000)",
            "border": "1px solid var(--app-border-color, #ddd)",
        },
    )


def create_section_component(text: str, index: int):
    """Create a section component."""
    return dmc.Paper(
        id=f"section-{index}",
        children=[
            dmc.Group(
                children=[
                    dmc.Text("📊", size="lg"),
                    dmc.Text(f"#{index + 1}", w=700, c="blue"),
                    dmc.Text(text, size="lg"),
                ],
                justify="flex-start",
                align="center",
                gap="xs",
            ),
            dmc.Text(
                f"Section ID: section-{index}", size="xs", c="gray", style={"marginTop": "0.5rem"}
            ),
        ],
        p="md",
        radius="md",
        withBorder=True,
        style={
            "marginBottom": "0.5rem",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "color": "var(--app-text-color, #000000)",
            "border": "1px solid var(--app-border-color, #ddd)",
        },
    )


def create_minimal_row_component(text: str, index: int):
    """Create a simple row component with text and index (legacy function)."""
    return dmc.Paper(
        children=[
            dmc.Group(
                children=[
                    dmc.Text(f"#{index + 1}", w=700, c="blue"),
                    dmc.Text(text, size="lg"),
                    dmc.Text(f"Component ID: minimal-{index}", size="xs", c="gray"),
                ],
                justify="space-between",
                align="center",
            )
        ],
        p="md",
        radius="md",
        withBorder=True,
    )


def register_minimal_callbacks(app):
    """Register callbacks for the minimal draggable system."""

    @app.callback(
        Output("filters-container", "children"),
        Input("create-filter-button", "n_clicks"),
        State("filters-container", "children"),
        prevent_initial_call=True,
    )
    def add_new_filter(n_clicks, current_filters):
        """Add a new filter component when Create Filter button is clicked."""
        if not n_clicks:
            return current_filters

        logger.info(f"🔧 MINIMAL: Create Filter button clicked {n_clicks} times")

        # Calculate new filter index (excluding welcome message)
        current_filters = current_filters or []
        # Count actual filter components (exclude welcome message)
        filter_count = len(
            [
                f
                for f in current_filters
                if isinstance(f, dict) and f.get("props", {}).get("id", "").startswith("filter-")
            ]
        )
        filter_letter = chr(65 + filter_count)  # A, B, C, etc.

        # Create new filter component
        new_filter = create_filter_component(f"Filter {filter_letter}", filter_count)

        # If this is the first filter, replace welcome message
        if filter_count == 0:
            updated_filters = [new_filter]
        else:
            updated_filters = current_filters + [new_filter]

        logger.info(
            f"🔧 MINIMAL: Added Filter {filter_letter}, total filters: {len(updated_filters)}"
        )
        return updated_filters

    @app.callback(
        Output("sections-container", "children"),
        Input("create-section-button", "n_clicks"),
        State("sections-container", "children"),
        prevent_initial_call=True,
    )
    def add_new_section(n_clicks, current_sections):
        """Add a new section component when Create Section button is clicked."""
        if not n_clicks:
            return current_sections

        logger.info(f"🔧 MINIMAL: Create Section button clicked {n_clicks} times")

        # Calculate new section index (excluding welcome message)
        current_sections = current_sections or []
        # Count actual section components (exclude welcome message)
        section_count = len(
            [
                s
                for s in current_sections
                if isinstance(s, dict) and s.get("props", {}).get("id", "").startswith("section-")
            ]
        )
        section_letter = chr(65 + section_count)  # A, B, C, etc.

        # Create new section component
        new_section = create_section_component(f"Section {section_letter}", section_count)

        # If this is the first section, replace welcome message
        if section_count == 0:
            updated_sections = [new_section]
        else:
            updated_sections = current_sections + [new_section]

        logger.info(
            f"🔧 MINIMAL: Added Section {section_letter}, total sections: {len(updated_sections)}"
        )
        return updated_sections
