"""
YAML Serialization utilities for dashboard documents.

Provides bidirectional conversion between MongoDB documents and YAML format,
enabling declarative dashboard configuration and version-controlled dashboards.

This module re-exports all public APIs from the modular submodules for
backward compatibility:
- yaml_utils: Shared utilities
- yaml_compact_format: Compact format functions
- yaml_mvp_format: MVP format functions
- yaml_export: Export functions
- yaml_import: Import functions
"""

# Re-export compact format functions
from depictio.models.yaml_serialization.compact_format import (
    dashboard_to_yaml_dict,
    yaml_dict_to_dashboard,
)

# Re-export export functions
from depictio.models.yaml_serialization.export import (
    create_dashboard_yaml_template,
    create_figure_component_yaml_template,
    dashboard_to_yaml,
    export_dashboard_to_file,
    export_dashboard_to_yaml_dir,
    get_dashboard_yaml_path,
)

# Re-export import functions
from depictio.models.yaml_serialization.loader import (
    delete_dashboard_yaml,
    ensure_yaml_directory,
    import_dashboard_from_file,
    import_dashboard_from_yaml_dir,
    list_yaml_dashboards,
    sync_status,
    validate_dashboard_yaml,
    yaml_to_dashboard_dict,
)

# Re-export MVP format functions
from depictio.models.yaml_serialization.mvp_format import (
    dashboard_to_yaml_mvp,
    yaml_mvp_to_dashboard,
)

# Re-export shared utilities
from depictio.models.yaml_serialization.utils import (
    DashboardYAMLDumper,
    auto_generate_layout,
    convert_for_yaml,
    convert_from_yaml,
    dump_yaml,
    enrich_component_dc_tag,
    enrich_component_wf_tag,
    enrich_dashboard_with_tags,
    filter_defaults,
    generate_component_id,
    get_db_connection_for_enrichment,
    sanitize_filename,
)

# Define public API for explicit imports
__all__ = [
    # Utilities
    "DashboardYAMLDumper",
    "auto_generate_layout",
    "convert_for_yaml",
    "convert_from_yaml",
    "dump_yaml",
    "enrich_component_dc_tag",
    "enrich_component_wf_tag",
    "enrich_dashboard_with_tags",
    "filter_defaults",
    "generate_component_id",
    "get_db_connection_for_enrichment",
    "sanitize_filename",
    # Compact format
    "dashboard_to_yaml_dict",
    "yaml_dict_to_dashboard",
    # MVP format
    "dashboard_to_yaml_mvp",
    "yaml_mvp_to_dashboard",
    # Export
    "create_dashboard_yaml_template",
    "create_figure_component_yaml_template",
    "dashboard_to_yaml",
    "export_dashboard_to_file",
    "export_dashboard_to_yaml_dir",
    "get_dashboard_yaml_path",
    # Import
    "delete_dashboard_yaml",
    "ensure_yaml_directory",
    "import_dashboard_from_file",
    "import_dashboard_from_yaml_dir",
    "list_yaml_dashboards",
    "sync_status",
    "validate_dashboard_yaml",
    "yaml_to_dashboard_dict",
]
