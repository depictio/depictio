"""
YAML Serialization utilities for dashboard documents.

Provides bidirectional conversion between MongoDB documents and YAML format.

The main models are:
- DashboardDataLite: Dashboard-level YAML format
- FigureLiteComponent, CardLiteComponent, etc.: Component-level models

Usage:
    from depictio.models.yaml_serialization import (
        DashboardDataLite,
        FigureLiteComponent,
        CardLiteComponent,
    )

    # Create a dashboard from YAML
    lite = DashboardDataLite.from_yaml_file("dashboard.yaml")

    # Convert to full format
    full_dict = lite.to_full()
"""

# Re-export Lite models from components
from depictio.models.components.lite import (
    BaseLiteComponent,
    CardLiteComponent,
    FigureLiteComponent,
    InteractiveLiteComponent,
    LiteComponent,
    TableLiteComponent,
)

# Re-export DashboardDataLite
from depictio.models.models.dashboards import DashboardDataLite

# Re-export export functions
from depictio.models.yaml_serialization.export import (
    export_dashboard_to_yaml_dir,
)

# Re-export loader functions
from depictio.models.yaml_serialization.loader import (
    delete_dashboard_yaml,
    ensure_yaml_directory,
    import_dashboard_from_yaml_dir,
    list_yaml_dashboards,
    sync_status,
    validate_dashboard_yaml,
    yaml_to_dashboard_dict,
)

# Re-export utility functions
from depictio.models.yaml_serialization.utils import (
    DashboardYAMLDumper,
    auto_generate_layout,
    convert_for_yaml,
    convert_from_yaml,
    dump_yaml,
    filter_defaults,
    generate_component_id,
    sanitize_filename,
)

__all__ = [
    # Dashboard model
    "DashboardDataLite",
    # Component models
    "BaseLiteComponent",
    "FigureLiteComponent",
    "CardLiteComponent",
    "InteractiveLiteComponent",
    "TableLiteComponent",
    "LiteComponent",
    # Utilities
    "DashboardYAMLDumper",
    "auto_generate_layout",
    "convert_for_yaml",
    "convert_from_yaml",
    "dump_yaml",
    "filter_defaults",
    "generate_component_id",
    "sanitize_filename",
    # Loader functions
    "delete_dashboard_yaml",
    "ensure_yaml_directory",
    "import_dashboard_from_yaml_dir",
    "list_yaml_dashboards",
    "sync_status",
    "validate_dashboard_yaml",
    "yaml_to_dashboard_dict",
    # Export functions
    "export_dashboard_to_yaml_dir",
]
