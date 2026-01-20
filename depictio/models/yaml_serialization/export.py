"""
YAML export functions for dashboard serialization.

Provides functions for exporting dashboards to YAML files and directories.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from depictio.models.logging import logger
from depictio.models.yaml_serialization.compact_format import dashboard_to_yaml_dict
from depictio.models.yaml_serialization.mvp_format import dashboard_to_yaml_mvp
from depictio.models.yaml_serialization.utils import (
    convert_for_yaml,
    dump_yaml,
    enrich_dashboard_with_tags,
    sanitize_filename,
)


def dashboard_to_yaml(
    dashboard_data: dict,
    include_metadata: bool = True,
    compact_mode: bool = True,
    mvp_mode: bool = False,
    db_client: Any = None,
) -> str:
    """
    Convert a dashboard document to YAML string.

    Args:
        dashboard_data: Dashboard data as dictionary (from model_dump or MongoDB)
        include_metadata: Whether to include export metadata (timestamp, version)
        compact_mode: Use compact format with references (75-80% size reduction)
        mvp_mode: Use MVP minimal format (60-80 lines, human-readable, no layout)
        db_client: Optional MongoDB client for tag enrichment (MVP mode only)

    Returns:
        YAML string representation of the dashboard
    """
    if mvp_mode:
        enriched_data = enrich_dashboard_with_tags(dashboard_data, db_client=db_client)
        yaml_data = dashboard_to_yaml_mvp(enriched_data)
    elif compact_mode:
        yaml_data = dashboard_to_yaml_dict(
            dashboard_data,
            compact_mode=True,
            include_metadata=include_metadata,
        )
    else:
        yaml_data = convert_for_yaml(dashboard_data)

        if include_metadata:
            yaml_data = {
                "_export_metadata": {
                    "format_version": "1.0",
                    "exported_at": datetime.now().isoformat(),
                    "source": "depictio",
                },
                **yaml_data,
            }

    return dump_yaml(yaml_data)


def export_dashboard_to_file(
    dashboard_data: dict,
    filepath: str | Path,
    include_metadata: bool = True,
    compact_mode: bool = True,
    mvp_mode: bool = False,
) -> Path:
    """
    Export a dashboard to a YAML file.

    Args:
        dashboard_data: Dashboard data as dictionary
        filepath: Destination file path
        include_metadata: Include export metadata (default: True)
        compact_mode: Use compact format (default: True)
        mvp_mode: Use MVP minimal format (default: False)

    Returns:
        Path to the written file
    """
    filepath = Path(filepath)

    if filepath.suffix not in (".yaml", ".yml"):
        filepath = filepath.with_suffix(".yaml")

    yaml_content = dashboard_to_yaml(
        dashboard_data,
        include_metadata=include_metadata,
        compact_mode=compact_mode,
        mvp_mode=mvp_mode,
    )

    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(yaml_content, encoding="utf-8")

    mode_desc = "MVP" if mvp_mode else ("compact" if compact_mode else "full")
    logger.info(f"Dashboard exported to {filepath} ({mode_desc} format)")
    return filepath


def get_dashboard_yaml_path(
    dashboard_id: str,
    dashboard_title: str,
    project_name: str | None = None,
    base_dir: str | Path | None = None,
    organize_by_project: bool = True,
    use_dashboard_title: bool = True,
) -> Path:
    """
    Get the file path for a dashboard YAML file.

    Args:
        dashboard_id: The dashboard ID
        dashboard_title: The dashboard title
        project_name: Optional project name for subdirectory organization
        base_dir: Base directory for YAML files (defaults to settings)
        organize_by_project: Whether to organize by project subdirectories
        use_dashboard_title: Whether to include title in filename

    Returns:
        Path object for the dashboard YAML file
    """
    if base_dir is None:
        from depictio.api.v1.configs.config import settings

        base_dir = Path(settings.dashboard_yaml.yaml_dir_path)
    else:
        base_dir = Path(base_dir)

    if organize_by_project and project_name:
        safe_project = sanitize_filename(project_name)
        dir_path = base_dir / safe_project
    else:
        dir_path = base_dir

    full_id = str(dashboard_id)
    if use_dashboard_title:
        safe_title = sanitize_filename(dashboard_title)
        filename = f"{safe_title}_{full_id}.yaml"
    else:
        filename = f"{full_id}.yaml"

    return dir_path / filename


def export_dashboard_to_yaml_dir(
    dashboard_data: dict,
    project_name: str | None = None,
    base_dir: str | Path | None = None,
    organize_by_project: bool | None = None,
    use_dashboard_title: bool | None = None,
    include_metadata: bool | None = None,
    compact_mode: bool | None = None,
    mvp_mode: bool | None = None,
    db_client: Any = None,
) -> Path:
    """
    Export a dashboard to the YAML directory using configured settings.

    Args:
        dashboard_data: Dashboard data dictionary (from model_dump or MongoDB)
        project_name: Project name for organization
        base_dir: Override base directory
        organize_by_project: Override organize_by_project setting
        use_dashboard_title: Override use_dashboard_title setting
        include_metadata: Override include_export_metadata setting
        compact_mode: Override compact_mode setting
        mvp_mode: Override mvp_mode setting
        db_client: Optional MongoDB client for tag enrichment (MVP mode only)

    Returns:
        Path to the written YAML file
    """
    from depictio.api.v1.configs.config import settings

    yaml_config = settings.dashboard_yaml

    if base_dir is None:
        base_dir = Path(yaml_config.yaml_dir_path)
    if organize_by_project is None:
        organize_by_project = yaml_config.organize_by_project
    if use_dashboard_title is None:
        use_dashboard_title = yaml_config.use_dashboard_title
    if include_metadata is None:
        include_metadata = yaml_config.include_export_metadata
    if compact_mode is None:
        compact_mode = yaml_config.compact_mode
    if mvp_mode is None:
        mvp_mode = yaml_config.mvp_mode

    dashboard_id = str(dashboard_data.get("dashboard_id", ""))
    dashboard_title = dashboard_data.get("title", "untitled")

    filepath = get_dashboard_yaml_path(
        dashboard_id=dashboard_id,
        dashboard_title=dashboard_title,
        project_name=project_name,
        base_dir=base_dir,
        organize_by_project=organize_by_project,
        use_dashboard_title=use_dashboard_title,
    )

    yaml_content = dashboard_to_yaml(
        dashboard_data,
        include_metadata=include_metadata,
        compact_mode=compact_mode,
        mvp_mode=mvp_mode,
        db_client=db_client,
    )

    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(yaml_content, encoding="utf-8")

    mode_desc = "MVP" if mvp_mode else ("compact" if compact_mode else "full")
    logger.info(f"Dashboard exported to YAML directory ({mode_desc} format): {filepath}")
    return filepath


def create_dashboard_yaml_template() -> str:
    """
    Generate a template YAML for creating new dashboards.

    Returns:
        YAML string template with documented fields
    """
    template = {
        "_comment": "Dashboard configuration template - remove this field before import",
        "title": "My Dashboard",
        "subtitle": "Dashboard description",
        "icon": "mdi:view-dashboard",
        "icon_color": "orange",
        "icon_variant": "filled",
        "workflow_system": "none",
        "notes_content": "",
        "is_public": False,
        "stored_metadata": [
            {
                "_comment": "Component metadata - each component has its own configuration",
                "index": "uuid-will-be-generated",
                "component_type": "card",
                "title": "Example Component",
                "dict_kwargs": {},
            }
        ],
        "left_panel_layout_data": [],
        "right_panel_layout_data": [],
        "buttons_data": {
            "unified_edit_mode": True,
            "add_components_button": {"count": 0},
        },
    }

    return dump_yaml(template)


def create_figure_component_yaml_template(with_customizations: bool = True) -> str:
    """
    Generate a template YAML for a figure component with customizations.

    This shows all available customization options for Plotly figures.

    Args:
        with_customizations: Include full customization examples

    Returns:
        YAML string template with documented figure component fields
    """
    template: dict[str, Any] = {
        "_comment": "Figure component template with Plotly customizations",
        "index": "fig-001",
        "component_type": "figure",
        "title": "My Figure",
        "visu_type": "scatter",
        "dict_kwargs": {
            "_comment": "Plotly Express parameters",
            "x": "x_column",
            "y": "y_column",
            "color": "category_column",
            "title": "Figure Title",
            "template": "mantine_light",
            "opacity": 0.8,
        },
    }

    if with_customizations:
        template["customizations"] = {
            "_comment": "Post-rendering customizations applied to the Plotly figure",
            "axes": {
                "x": {
                    "scale": "linear",
                    "title": "X Axis Title",
                    "range": [0, 100],
                    "gridlines": True,
                    "zeroline": True,
                },
                "y": {
                    "scale": "log",
                    "title": "Y Axis Title (Log Scale)",
                },
            },
            "reference_lines": [
                {
                    "type": "hline",
                    "y": 0.05,
                    "line_color": "red",
                    "line_dash": "dash",
                    "line_width": 1,
                    "opacity": 0.7,
                    "annotation_text": "p = 0.05 threshold",
                    "annotation_position": "top right",
                },
                {
                    "type": "vline",
                    "x": 0,
                    "line_color": "gray",
                    "line_dash": "solid",
                },
            ],
            "highlights": [
                {
                    "conditions": [
                        {
                            "column": "significant",
                            "operator": "eq",
                            "value": True,
                        }
                    ],
                    "logic": "and",
                    "style": {
                        "marker_color": "red",
                        "marker_size": 10,
                        "dim_opacity": 0.3,
                    },
                    "label": "Significant",
                    "show_labels": False,
                }
            ],
            "annotations": [
                {
                    "text": "Important point",
                    "x": 50,
                    "y": 50,
                    "showarrow": True,
                    "arrowhead": 2,
                }
            ],
            "shapes": [
                {
                    "type": "rect",
                    "x0": 10,
                    "y0": 10,
                    "x1": 20,
                    "y1": 20,
                    "fillcolor": "rgba(255,0,0,0.1)",
                    "line_color": "red",
                    "layer": "below",
                }
            ],
            "legend": {
                "show": True,
                "orientation": "v",
                "x": 1.02,
                "y": 1,
            },
            "hover": {
                "mode": "closest",
            },
        }

    return dump_yaml(template)
