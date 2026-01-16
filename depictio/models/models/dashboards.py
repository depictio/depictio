from pathlib import Path
from typing import Any, Optional

from pydantic import ConfigDict, field_serializer

from depictio.models.models.base import MongoModel, PyObjectId, convert_objectid_to_str
from depictio.models.models.users import Permission


class DashboardData(MongoModel):
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
        # json_encoders={ObjectId: lambda oid: str(oid)},
    )

    @field_serializer("permissions")
    def serialize_permissions(self, permissions: Permission):
        # Convert any ObjectIds in the permissions object to strings
        # The exact implementation depends on what's in your Permission class
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
        # Convert any ObjectIds in the stored_metadata list to strings
        return convert_objectid_to_str(stored_metadata)

    def to_yaml(self, include_metadata: bool = True) -> str:
        """
        Export this dashboard to a YAML string.

        Args:
            include_metadata: Whether to include export metadata (timestamp, version)

        Returns:
            YAML string representation of the dashboard
        """
        from depictio.models.yaml_serialization import dashboard_to_yaml

        return dashboard_to_yaml(self.model_dump(), include_metadata=include_metadata)

    def to_yaml_file(self, filepath: str | Path) -> Path:
        """
        Export this dashboard to a YAML file.

        Args:
            filepath: Destination file path

        Returns:
            Path to the written file
        """
        from depictio.models.yaml_serialization import export_dashboard_to_file

        return export_dashboard_to_file(self.model_dump(), filepath)

    @classmethod
    def from_yaml(cls, yaml_content: str) -> "DashboardData":
        """
        Create a DashboardData instance from YAML string.

        Args:
            yaml_content: YAML string content

        Returns:
            DashboardData instance

        Raises:
            ValueError: If YAML is invalid or doesn't match schema
        """
        from depictio.models.yaml_serialization import yaml_to_dashboard_dict

        data = yaml_to_dashboard_dict(yaml_content)
        return cls(**data)

    @classmethod
    def from_yaml_file(cls, filepath: str | Path) -> "DashboardData":
        """
        Create a DashboardData instance from a YAML file.

        Args:
            filepath: Source YAML file path

        Returns:
            DashboardData instance

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file content is invalid
        """
        from depictio.models.yaml_serialization import import_dashboard_from_file

        data = import_dashboard_from_file(filepath)
        return cls(**data)

    def to_dict_yaml_safe(self) -> dict[str, Any]:
        """
        Convert to a dictionary suitable for YAML serialization.

        All ObjectIds and datetime objects are converted to strings.

        Returns:
            Dictionary with JSON/YAML serializable values
        """
        from depictio.models.yaml_serialization import convert_for_yaml

        return convert_for_yaml(self.model_dump())
