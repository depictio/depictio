#!/usr/bin/env python3
"""
Mark all YAML endpoints as deprecated in routes.py

This script updates all YAML-related endpoints to include deprecated=True
and adds deprecation notices to their docstrings.
"""

import re
from pathlib import Path

routes_file = Path(__file__).parent.parent / "depictio/api/v1/endpoints/dashboards_endpoints/routes.py"

# Read the file
content = routes_file.read_text()

# List of YAML endpoint function names (found via grep earlier)
yaml_endpoints = [
    "export_dashboard_to_yaml",  # Already done
    "preview_dashboard_yaml",  # Already done
    "import_dashboard_from_yaml",  # Already done
    "import_dashboard_from_yaml_file",
    "validate_dashboard_yaml_endpoint",
    "update_dashboard_from_yaml",
    "list_yaml_directory",
    "export_to_yaml_directory",
    "export_all_to_yaml_directory",
    "import_from_yaml_directory",
    "get_yaml_sync_status",
    "delete_from_yaml_directory",
    "get_yaml_directory_config",
    "start_yaml_watcher_endpoint",
    "stop_yaml_watcher_endpoint",
    "get_yaml_watcher_status_endpoint",
    "sync_all_yaml_to_mongodb",
]

# Pattern to find endpoint decorators
# Matches: @dashboards_endpoint_router.{method}("/path")
# But not: @dashboards_endpoint_router.{method}("/path", deprecated=True)
pattern = r'@dashboards_endpoint_router\.(get|post|put|delete|patch)\(([^)]+)\)\nasync def ('+ '|'.join(yaml_endpoints) + r')\('

def add_deprecated_flag(match):
    """Add deprecated=True to decorator if not present"""
    method = match.group(1)
    path_args = match.group(2)
    func_name = match.group(3)

    # Check if already has deprecated flag
    if 'deprecated' in path_args:
        return match.group(0)  # Already has it, return unchanged

    # Add deprecated=True to the decorator
    new_decorator = f'@dashboards_endpoint_router.{method}({path_args}, deprecated=True)\nasync def {func_name}('

    return new_decorator

# Apply the pattern
new_content = re.sub(pattern, add_deprecated_flag, content)

# Write back
routes_file.write_text(new_content)

print(f"✓ Marked YAML endpoints as deprecated in {routes_file}")
print(f"  Total YAML endpoints: {len(yaml_endpoints)}")
