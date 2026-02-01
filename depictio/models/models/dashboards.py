"""
Dashboard Models.

Provides DashboardDataLite (minimal format for YAML/API) and
DashboardData (full model with MongoDB/auth fields).

Architecture:
    DashboardData (MongoDB full)
        ↓ to_lite()
    DashboardDataLite (YAML - user-friendly)
        ↓ to_full()
    DashboardData (MongoDB full)

Component Architecture:
    FigureLiteComponent (user-definable, YAML)
        ↓ inherits
    FigureComponent (adds runtime fields)
"""

from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
)

from depictio.models.components.lite import LiteComponent
from depictio.models.models.base import MongoModel, PyObjectId, convert_objectid_to_str
from depictio.models.models.users import Permission


class LayoutItem(BaseModel):
    """Layout item for grid positioning.

    Represents a component's position and size in the react-grid-layout system.
    """

    i: str = Field(description="Component index/identifier (e.g., 'box-uuid')")
    x: int = Field(default=0, description="X position in grid units")
    y: int = Field(default=0, description="Y position in grid units")
    w: int = Field(default=6, description="Width in grid units")
    h: int = Field(default=4, description="Height in grid units")

    # Additional layout options
    static: bool = Field(default=False, description="Whether the item is fixed/not draggable")
    resizeHandles: list[str] | None = Field(
        default=None, description="Resize handles (e.g., ['se', 's', 'e', 'sw', 'w'])"
    )

    model_config = ConfigDict(extra="allow")


# ============================================================================
# DashboardDataLite - User-friendly YAML format
# ============================================================================


class DashboardDataLite(BaseModel):
    """Minimal dashboard format for YAML import/export.

    Uses `tag` for user-friendly component identification, while `index` (UUID)
    is managed internally. Users write `tag` in YAML, system generates UUIDs.

    Example YAML:
        title: "Iris Dashboard demo"
        project_tag: "iris"  # Project name for server-side lookup
        components:
          - tag: scatter-1
            component_type: figure
            workflow_tag: python/iris_workflow
            data_collection_tag: iris_table
            visu_type: scatter
            dict_kwargs:
              x: sepal.length
              y: sepal.width
              color: variety

          - tag: card-1
            component_type: card
            workflow_tag: python/iris_workflow
            data_collection_tag: iris_table
            aggregation: average
            column_name: sepal.length
            column_type: float64

    Usage:
        # Parse YAML
        lite = DashboardDataLite.from_yaml(yaml_content)

        # Export to YAML
        yaml_str = lite.to_yaml()

        # Convert to full format (resolves IDs from MongoDB)
        full_dict = lite.to_full()
    """

    model_config = ConfigDict(extra="allow")

    # Dashboard ID (optional for new dashboards)
    dashboard_id: str | None = Field(default=None, description="Dashboard ID")

    # Project identification (for server-side lookup during import)
    project_tag: str | None = Field(
        default=None,
        description="Project name/tag for server-side lookup. "
        "Used during import to find the target project by name.",
    )

    # Display
    title: str = Field(..., description="Dashboard title")
    subtitle: str = Field(default="", description="Dashboard subtitle")

    # Components using Lite models
    components: list[LiteComponent | dict[str, Any]] = Field(
        default_factory=list, description="List of dashboard components"
    )

    def to_yaml(self) -> str:
        """Export to YAML string.

        Returns:
            YAML string representation with tag as primary identifier.
            The UUID index is omitted from YAML output (managed internally).
        """
        data = self.model_dump(exclude_none=True, mode="json")

        # Remove empty subtitle
        if not data.get("subtitle"):
            data.pop("subtitle", None)

        # Remove empty project_tag
        if not data.get("project_tag"):
            data.pop("project_tag", None)

        # Clean up components - remove empty values and order fields
        if "components" in data:
            cleaned_components = []
            # Define preferred field order (tag first, then type, then data source, then config)
            field_order = [
                "tag",
                "component_type",
                "workflow_tag",
                "data_collection_tag",
                "title",
                "visu_type",
                "dict_kwargs",
                "aggregation",
                "column_name",
                "column_type",
                "interactive_component_type",
            ]

            for comp in data["components"]:
                cleaned: dict[str, Any] = {}

                # Add fields in preferred order
                for key in field_order:
                    if key in comp:
                        value = comp[key]
                        # Skip empty values
                        if value in ("", None, [], {}):
                            continue
                        cleaned[key] = value

                # Add remaining fields (styling, etc.) in original order
                for key, value in comp.items():
                    if key in cleaned or key == "index":  # Skip index (UUID) - internal only
                        continue
                    # Skip empty values
                    if value in ("", None, [], {}):
                        continue
                    # Skip default values for table
                    if comp.get("component_type") == "table":
                        if key == "page_size" and value == 10:
                            continue
                        if key == "sortable" and value is True:
                            continue
                        if key == "filterable" and value is True:
                            continue
                    cleaned[key] = value

                cleaned_components.append(cleaned)
            data["components"] = cleaned_components

        return yaml.dump(
            data, default_flow_style=False, sort_keys=False, allow_unicode=True, indent=4
        )

    @classmethod
    def from_yaml(cls, content: str) -> "DashboardDataLite":
        """Parse and validate YAML content.

        Args:
            content: YAML string content

        Returns:
            Validated DashboardDataLite instance

        Raises:
            ValueError: If YAML is invalid
            ValidationError: If data doesn't match schema
        """
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}") from e

        if not isinstance(data, dict):
            raise ValueError("YAML must contain a dictionary at root level")

        return cls.model_validate(data)

    @classmethod
    def from_yaml_file(cls, path: str | Path) -> "DashboardDataLite":
        """Load and validate from YAML file.

        Args:
            path: Path to YAML file

        Returns:
            Validated DashboardDataLite instance

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If content is invalid
        """
        filepath = Path(path)
        if not filepath.exists():
            raise FileNotFoundError(f"YAML file not found: {filepath}")

        return cls.from_yaml(filepath.read_text(encoding="utf-8"))

    def to_yaml_file(self, path: str | Path) -> Path:
        """Export to YAML file.

        Args:
            path: Destination file path

        Returns:
            Path to written file
        """
        filepath = Path(path)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(self.to_yaml(), encoding="utf-8")
        return filepath

    @classmethod
    def validate_yaml(cls, content: str) -> tuple[bool, list[dict[str, Any]]]:
        """Validate YAML content without raising exceptions.

        Args:
            content: YAML string content

        Returns:
            Tuple of (is_valid, errors)
            - is_valid: True if validation passed
            - errors: List of error dictionaries (empty if valid)
        """
        try:
            cls.from_yaml(content)
            return True, []
        except ValueError as e:
            return False, [{"type": "yaml_error", "msg": str(e)}]
        except ValidationError as e:
            # e.errors() returns list of ErrorDetails which is compatible with dict[str, Any]
            return False, list(e.errors())  # type: ignore[return-value]

    @classmethod
    def from_full(cls, dashboard_data: dict[str, Any]) -> "DashboardDataLite":
        """Convert full dashboard dict to lite format.

        Extracts only user-definable fields from a full dashboard.

        Args:
            dashboard_data: Full dashboard dictionary (from model_dump or MongoDB)

        Returns:
            DashboardDataLite with minimal fields
        """

        def extract_id(value: Any) -> str | None:
            """Extract ID string from various formats (str, dict with $oid)."""
            if value is None:
                return None
            if isinstance(value, dict) and "$oid" in value:
                return value["$oid"]
            return str(value)

        def filter_dict_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
            """Filter out empty/default values from dict_kwargs."""
            defaults = {
                "template": "mantine_light",
                "orientation": "v",
                "log_x": False,
                "log_y": False,
            }
            return {
                k: v
                for k, v in kwargs.items()
                if v not in ("", None, [], {}) and not (k in defaults and v == defaults[k])
            }

        def copy_optional_fields(comp: dict, lite_comp: dict, fields: list[str]) -> None:
            """Copy non-empty optional fields from component to lite component."""
            for field in fields:
                if comp.get(field):
                    lite_comp[field] = comp[field]

        dashboard_id = extract_id(dashboard_data.get("dashboard_id") or dashboard_data.get("_id"))
        tag_counters: dict[str, int] = {}
        lite_components = []

        for comp in dashboard_data.get("stored_metadata", []):
            comp_type = comp.get("component_type", "figure")

            # Generate or use existing tag
            tag_counters[comp_type] = tag_counters.get(comp_type, 0) + 1
            tag = comp.get("tag") or f"{comp_type}-{tag_counters[comp_type]}"

            lite_comp: dict[str, Any] = {
                "tag": tag,
                "index": comp.get("index", ""),
                "component_type": comp_type,
                "workflow_tag": comp.get("workflow_tag") or comp.get("wf_tag", ""),
                "data_collection_tag": (
                    comp.get("data_collection_tag")
                    or comp.get("dc_config", {}).get("data_collection_tag", "")
                ),
            }

            if comp.get("title"):
                lite_comp["title"] = comp["title"]

            if comp_type == "figure":
                lite_comp["visu_type"] = comp.get("visu_type", "scatter")
                dict_kwargs = filter_dict_kwargs(comp.get("dict_kwargs", {}))
                if dict_kwargs:
                    lite_comp["dict_kwargs"] = dict_kwargs

            elif comp_type == "card":
                lite_comp["aggregation"] = comp.get("aggregation", "")
                lite_comp["column_name"] = comp.get("column_name", "")
                lite_comp["column_type"] = comp.get("column_type", "float64")
                copy_optional_fields(
                    comp,
                    lite_comp,
                    [
                        "icon_name",
                        "icon_color",
                        "title_color",
                        "title_font_size",
                        "value_font_size",
                    ],
                )

            elif comp_type == "interactive":
                lite_comp["interactive_component_type"] = comp.get("interactive_component_type", "")
                lite_comp["column_name"] = comp.get("column_name", "")
                lite_comp["column_type"] = comp.get("column_type", "object")
                copy_optional_fields(comp, lite_comp, ["title_size", "custom_color", "icon_name"])

            elif comp_type == "table":
                if comp.get("columns"):
                    lite_comp["columns"] = comp["columns"]
                if comp.get("page_size") and comp["page_size"] != 10:
                    lite_comp["page_size"] = comp["page_size"]
                if comp.get("sortable") is False:
                    lite_comp["sortable"] = False
                if comp.get("filterable") is False:
                    lite_comp["filterable"] = False

            lite_components.append(lite_comp)

        return cls(
            dashboard_id=dashboard_id,
            title=dashboard_data.get("title", "Untitled Dashboard"),
            subtitle=dashboard_data.get("subtitle", ""),
            components=lite_components,
        )

    def to_full(self) -> dict[str, Any]:
        """Convert lite format back to full dashboard dict.

        Returns:
            Full dashboard dictionary ready for MongoDB insertion
        """
        import uuid
        from datetime import datetime

        def copy_optional_fields(src: dict, dest: dict, fields: list[str]) -> None:
            """Copy non-empty optional fields from source to destination."""
            for field in fields:
                if src.get(field):
                    dest[field] = src[field]

        def build_base_component(comp_dict: dict[str, Any]) -> dict[str, Any]:
            """Build base component with common fields."""
            return {
                "index": comp_dict.get("index") or str(uuid.uuid4()),
                "component_type": comp_dict.get("component_type", "figure"),
                "title": comp_dict.get("title", ""),
                "workflow_tag": comp_dict.get("workflow_tag"),
                "data_collection_tag": comp_dict.get("data_collection_tag"),
                "wf_id": None,
                "dc_id": None,
                "dc_config": {},
                "cols_json": {},
                "parent_index": None,
                "last_updated": datetime.now().isoformat(),
            }

        full_dict: dict[str, Any] = {
            "title": self.title,
            "subtitle": self.subtitle,
            "version": 1,
            "icon": "mdi:view-dashboard",
            "icon_color": "orange",
            "icon_variant": "filled",
            "workflow_system": "none",
            "notes_content": "",
            "is_public": False,
            "permissions": {"owners": [], "editors": [], "viewers": []},
        }

        if self.dashboard_id:
            full_dict["dashboard_id"] = self.dashboard_id

        full_components = []
        for comp in self.components:
            comp_dict = comp if isinstance(comp, dict) else comp.model_dump()
            full_comp = build_base_component(comp_dict)
            comp_type = comp_dict.get("component_type", "figure")

            if comp_type == "figure":
                full_comp.update(
                    {
                        "visu_type": comp_dict.get("visu_type", "scatter"),
                        "dict_kwargs": comp_dict.get("dict_kwargs", {}),
                        "mode": "ui",
                        "displayed_data_count": 0,
                        "total_data_count": 0,
                        "was_sampled": False,
                        "filter_applied": False,
                    }
                )

            elif comp_type == "card":
                full_comp.update(
                    {
                        "aggregation": comp_dict.get("aggregation", ""),
                        "column_name": comp_dict.get("column_name", ""),
                        "column_type": comp_dict.get("column_type", "float64"),
                        "value": None,
                    }
                )
                copy_optional_fields(
                    comp_dict,
                    full_comp,
                    [
                        "icon_name",
                        "icon_color",
                        "title_color",
                        "title_font_size",
                        "value_font_size",
                    ],
                )

            elif comp_type == "interactive":
                full_comp.update(
                    {
                        "interactive_component_type": comp_dict.get(
                            "interactive_component_type", ""
                        ),
                        "column_name": comp_dict.get("column_name", ""),
                        "column_type": comp_dict.get("column_type", "object"),
                        "value": None,
                        "default_state": None,
                    }
                )
                copy_optional_fields(
                    comp_dict, full_comp, ["title_size", "custom_color", "icon_name"]
                )

            elif comp_type == "table":
                full_comp.update(
                    {
                        "columns": comp_dict.get("columns", []),
                        "page_size": comp_dict.get("page_size", 10),
                        "sortable": comp_dict.get("sortable", True),
                        "filterable": comp_dict.get("filterable", True),
                    }
                )

            full_components.append(full_comp)

        full_dict["stored_metadata"] = full_components

        # Auto-generate layout
        from depictio.models.yaml_serialization.utils import auto_generate_layout

        full_dict["stored_layout_data"] = [
            {
                **auto_generate_layout(idx, comp.get("component_type", "figure")),
                "i": f"box-{comp['index']}",
            }
            for idx, comp in enumerate(full_components)
        ]
        full_dict["left_panel_layout_data"] = []
        full_dict["right_panel_layout_data"] = []
        full_dict["tmp_children_data"] = []
        full_dict["stored_children_data"] = []
        full_dict["buttons_data"] = {
            "unified_edit_mode": True,
            "add_components_button": {"count": 0},
        }

        return full_dict


class DashboardData(MongoModel):
    """Full dashboard model with MongoDB and auth fields.

    Extends DashboardDataLite with:
    - MongoDB document fields (id, project_id, dashboard_id)
    - Permissions (owners, editors, viewers)
    - Versioning and timestamps
    - Tab support
    """

    dashboard_id: PyObjectId
    version: int = 1
    tmp_children_data: list | None = []
    stored_layout_data: list = []
    stored_children_data: list = []
    stored_metadata: list = []
    stored_edit_dashboard_mode_button: list = []
    # Dual-panel layout storage (for left/right grid layouts)
    left_panel_layout_data: list = []
    right_panel_layout_data: list = []
    buttons_data: dict = {
        "unified_edit_mode": True,  # Default edit mode ON for dashboard owners
        "add_components_button": {"count": 0},
    }
    stored_add_button: dict = {"count": 0}
    title: str
    subtitle: str = ""
    icon: str = "mdi:view-dashboard"
    icon_color: str = "orange"
    icon_variant: str = "filled"
    workflow_system: str = "none"
    notes_content: str = ""
    permissions: Permission
    is_public: bool = False
    last_saved_ts: str = ""
    project_id: PyObjectId

    # Tab support (backward compatible)
    is_main_tab: bool = True
    parent_dashboard_id: Optional[PyObjectId] = None
    tab_order: int = 0

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )

    @field_serializer("permissions")
    def serialize_permissions(self, permissions: Permission) -> dict[str, Any]:
        return permissions.model_dump()

    @field_serializer("project_id")
    def serialize_project_id(self, project_id: PyObjectId) -> str:
        return str(project_id)

    @field_serializer("dashboard_id")
    def serialize_dashboard_id(self, dashboard_id: PyObjectId) -> str:
        return str(dashboard_id)

    @field_serializer("parent_dashboard_id")
    def serialize_parent_dashboard_id(
        self, parent_dashboard_id: Optional[PyObjectId]
    ) -> Optional[str]:
        return str(parent_dashboard_id) if parent_dashboard_id else None

    @field_serializer("stored_metadata")
    def serialize_stored_metadata(self, stored_metadata: list) -> list:
        return convert_objectid_to_str(stored_metadata)

    def to_lite(self) -> DashboardDataLite:
        """Convert to lightweight model for export.

        Returns:
            DashboardDataLite with only user-definable fields
        """
        return DashboardDataLite.from_full(self.model_dump())

    def to_yaml(self) -> str:
        """Export this dashboard to a YAML string.

        Returns:
            YAML string representation of the dashboard
        """
        return self.to_lite().to_yaml()

    def to_yaml_file(self, filepath: str | Path) -> Path:
        """Export this dashboard to a YAML file.

        Args:
            filepath: Destination file path

        Returns:
            Path to the written file
        """
        return self.to_lite().to_yaml_file(filepath)

    @classmethod
    def from_yaml(cls, yaml_content: str, **defaults: Any) -> "DashboardData":
        """Create a DashboardData instance from YAML string.

        Args:
            yaml_content: YAML string content
            **defaults: Default values for required fields (project_id, permissions, etc.)

        Returns:
            DashboardData instance

        Raises:
            ValueError: If YAML is invalid or required fields missing
        """
        lite = DashboardDataLite.from_yaml(yaml_content)
        data = lite.to_full()

        # Merge defaults
        for key, value in defaults.items():
            if key not in data or data[key] is None:
                data[key] = value

        # Ensure required fields
        if "project_id" not in data:
            raise ValueError("project_id is required for DashboardData")
        if "permissions" not in data:
            raise ValueError("permissions is required for DashboardData")
        if "dashboard_id" not in data:
            data["dashboard_id"] = PyObjectId()

        return cls.model_validate(data)

    @classmethod
    def from_yaml_file(cls, filepath: str | Path, **defaults: Any) -> "DashboardData":
        """Create a DashboardData instance from a YAML file.

        Args:
            filepath: Source YAML file path
            **defaults: Default values for required fields

        Returns:
            DashboardData instance

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file content is invalid
        """
        content = Path(filepath).read_text(encoding="utf-8")
        return cls.from_yaml(content, **defaults)

    def to_dict_yaml_safe(self) -> dict[str, Any]:
        """Convert to a dictionary suitable for YAML serialization.

        All ObjectIds and datetime objects are converted to strings.

        Returns:
            Dictionary with JSON/YAML serializable values
        """
        return convert_objectid_to_str(self.model_dump())
