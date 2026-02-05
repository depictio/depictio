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

import re
from pathlib import Path
from typing import Any, ClassVar, Optional

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    model_validator,
)

from depictio.models.components.lite import (
    CardLiteComponent,
    FigureLiteComponent,
    ImageLiteComponent,
    InteractiveLiteComponent,
    LiteComponent,
    MultiQCLiteComponent,
    TableLiteComponent,
)
from depictio.models.logging import logger
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
# Validation helpers
# ============================================================================

_VALUE_ERROR_PREFIX = re.compile(r"^Value error,\s*")


def _strip_value_error_prefix(msg: str) -> str:
    """Remove Pydantic v2's 'Value error, ' prefix from a message."""
    return _VALUE_ERROR_PREFIX.sub("", msg)


def _parse_component_lines(raw_msg: str) -> list[dict[str, Any]]:
    """Parse '[tag] loc: msg' lines from validate_components_domain output.

    Each line has format: [component_tag] field_location: error message
    Returns a list of structured error dicts with type, tag, loc, and msg.
    """
    clean = _strip_value_error_prefix(raw_msg)
    result: list[dict[str, Any]] = []
    for line in clean.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"\[([^\]]+)\]\s*([^:]*?):\s*(.*)", line)
        if m:
            result.append(
                {
                    "type": "component_error",
                    "tag": m.group(1),
                    "loc": m.group(2).strip() or None,
                    "msg": _strip_value_error_prefix(m.group(3).strip()),
                }
            )
    return result


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

    # Tab support for YAML import/export
    is_main_tab: bool = Field(
        default=True, description="Whether this is the main tab (root dashboard)"
    )
    parent_dashboard_tag: str | None = Field(
        default=None,
        description="Parent dashboard title for child tabs (resolved during import)",
    )
    tab_order: int = Field(default=0, description="Order of tab within parent (0 = main tab)")
    main_tab_name: str | None = Field(
        default=None, description="Custom name for main tab (defaults to 'Main' if None)"
    )
    tab_icon: str | None = Field(
        default=None, description="Icon for child tabs (e.g., 'mdi:chart-bar')"
    )
    tab_icon_color: str | None = Field(default=None, description="Color for tab icon")

    # Dashboard display icon (shown on the management page card)
    icon: str | None = Field(default=None, description="Dashboard icon identifier")
    icon_color: str | None = Field(default=None, description="Dashboard icon color")
    icon_variant: str | None = Field(default=None, description="Dashboard icon variant")
    workflow_system: str | None = Field(
        default=None, description="Workflow system (e.g., 'nf-core', 'snakemake')"
    )

    # Components using Lite models
    components: list[LiteComponent | dict[str, Any]] = Field(
        default_factory=list, description="List of dashboard components"
    )

    # Map component_type string → typed Lite model for domain validation
    _COMPONENT_TYPE_MAP: ClassVar[dict[str, type]] = {
        "figure": FigureLiteComponent,
        "card": CardLiteComponent,
        "interactive": InteractiveLiteComponent,
        "table": TableLiteComponent,
        "image": ImageLiteComponent,
        "multiqc": MultiQCLiteComponent,
    }

    @model_validator(mode="after")
    def validate_components_domain(self) -> "DashboardDataLite":
        """Re-validate components that fell through to dict due to union fallback.

        Pydantic's union resolution tries each variant left-to-right. When a typed
        LiteComponent variant fails (e.g., invalid visu_type), Pydantic falls back
        to dict[str, Any] which always succeeds. This validator catches those cases.
        """
        errors: list[str] = []
        for i, comp in enumerate(self.components):
            if not isinstance(comp, dict):
                # Already validated as a typed model — skip
                continue
            comp_type = comp.get("component_type")
            model_cls = self._COMPONENT_TYPE_MAP.get(comp_type or "")
            if model_cls is None:
                # Unknown component_type — skip (no typed model to validate against)
                continue
            try:
                model_cls.model_validate(comp)
            except ValidationError as exc:
                for err in exc.errors():
                    loc = ".".join(str(x) for x in err.get("loc", ()))
                    tag = comp.get("tag") or f"component[{i}]"
                    errors.append(f"[{tag}] {loc}: {err['msg']}")

        if errors:
            raise ValueError("\n".join(errors))

        return self

    # Sentinel key names used to inject YAML comment separators between sections.
    # After yaml.dump(), these are replaced by comment lines via _apply_section_comments().
    SENTINEL_OPTIONAL: ClassVar[str] = "__section_optional__"
    SENTINEL_GENERATED: ClassVar[str] = "__section_generated_on_export__"

    # Dashboard-level optional user fields (non-mandatory, non-generated)
    OPTIONAL_DASHBOARD_FIELDS: ClassVar[list[str]] = [
        "subtitle",
        "project_tag",
        "main_tab_name",
        "tab_order",
        "tab_icon",
        "tab_icon_color",
        "is_main_tab",
        "parent_dashboard_tag",
        "icon",
        "icon_color",
        "icon_variant",
        "workflow_system",
    ]

    @staticmethod
    def _apply_section_comments(yaml_str: str) -> str:
        """Replace sentinel keys with YAML comment separators.

        Converts ``__section_optional__: null`` and
        ``__section_generated_on_export__: null`` lines (at any indent level)
        into human-readable comment lines preserving the original indentation.
        """
        import re

        labels = {
            DashboardDataLite.SENTINEL_OPTIONAL: "optional",
            DashboardDataLite.SENTINEL_GENERATED: "generated on export",
        }
        for sentinel, label in labels.items():
            yaml_str = re.sub(
                rf"^(\s*){re.escape(sentinel)}: null\n",
                lambda m, lbl=label: f"{m.group(1)}# --- {lbl} ---\n",
                yaml_str,
                flags=re.MULTILINE,
            )
        return yaml_str

    @classmethod
    def _strip_dashboard_defaults(cls, data: dict[str, Any]) -> None:
        """Strip dashboard-level fields that equal their defaults (in-place)."""
        default_value_fields = {
            "subtitle": "",
            "project_tag": "",
            "parent_dashboard_tag": "",
            "main_tab_name": "",
            "tab_icon": "",
            "tab_icon_color": "",
            "icon": "mdi:view-dashboard",
            "icon_color": "orange",
            "icon_variant": "filled",
        }
        for field, default in default_value_fields.items():
            if not data.get(field) or data.get(field) == default:
                data.pop(field, None)
        if data.get("is_main_tab", True) is True:
            data.pop("is_main_tab", None)
        if data.get("tab_order", 0) == 0:
            data.pop("tab_order", None)
        if not data.get("workflow_system") or data.get("workflow_system") == "none":
            data.pop("workflow_system", None)

    @classmethod
    def _build_ordered_dashboard_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Build an ordered dashboard dict with sentinel section separators.

        Sections:
          - Mandatory  : title
          - Optional   : user-defined metadata (subtitle, project_tag, icon …)
          - Generated  : dashboard_id (set by the system on export)
          - Content    : components list (last, it's large)

        Sentinel keys (``__section_optional__``, ``__section_generated_on_export__``)
        are replaced by comment lines after ``yaml.dump()`` via
        ``_apply_section_comments()``.
        """
        ordered: dict[str, Any] = {}

        # --- mandatory ---
        if "title" in data:
            ordered["title"] = data["title"]

        # --- optional ---
        optional_data = {f: data[f] for f in cls.OPTIONAL_DASHBOARD_FIELDS if f in data}
        if optional_data:
            ordered[cls.SENTINEL_OPTIONAL] = None
            ordered.update(optional_data)

        # --- generated on export ---
        if "dashboard_id" in data:
            ordered[cls.SENTINEL_GENERATED] = None
            ordered["dashboard_id"] = data["dashboard_id"]

        # --- content ---
        if "components" in data:
            ordered["components"] = data["components"]

        # Catch-all for any unexpected fields
        known = {"title", "dashboard_id", "components"} | set(cls.OPTIONAL_DASHBOARD_FIELDS)
        for key, val in data.items():
            if key not in known and key not in ordered:
                ordered[key] = val

        return ordered

    def to_yaml(self) -> str:
        """Export to YAML string with section comment separators.

        Sections are separated by ``# --- optional ---`` and
        ``# --- generated on export ---`` comment lines for clarity.
        Mandatory fields come first, generated export metadata last.
        """
        data = self.model_dump(exclude_none=True, mode="json")

        self._strip_dashboard_defaults(data)

        # Clean and order each component
        if "components" in data:
            data["components"] = [
                self._clean_component_for_yaml(comp) for comp in data["components"]
            ]

        ordered = self._build_ordered_dashboard_dict(data)

        raw = yaml.dump(
            ordered, default_flow_style=False, sort_keys=False, allow_unicode=True, indent=4
        )
        return self._apply_section_comments(raw)

    @staticmethod
    def _is_uuid_like(value: str) -> bool:
        """Check whether a string looks like an auto-generated UUID."""
        return value.count("-") >= 4 or len(value) > 30

    @staticmethod
    def _is_empty_value(value: Any) -> bool:
        """Check whether a value is empty/falsy for YAML export purposes."""
        return value in ("", None, [], {})

    @staticmethod
    def _get_component_field_order(comp_type: str) -> list[str]:
        """Return field ordering for a component type.

        Fields are grouped into three sections:
          1. Mandatory common fields (required for all components)
          2. Type-specific required + optional user-defined fields
          3. Export-generated fields (tag, layout) — present on export but not
             needed when writing YAML from scratch
        """
        mandatory_common = ["component_type", "workflow_tag", "data_collection_tag"]

        type_sections: dict[str, list[str]] = {
            "figure": [
                # mandatory
                "visu_type",
                # optional user-defined
                "dict_kwargs",
                "figure_params",
                "mode",
                "code_content",
                "selection_enabled",
                "selection_column",
            ],
            "card": [
                # mandatory
                "aggregation",
                "column_name",
                # optional user-defined
                "column_type",
                "display",
            ],
            "interactive": [
                # mandatory
                "interactive_component_type",
                "column_name",
                # optional user-defined
                "column_type",
                "display",
            ],
            "table": [
                # optional user-defined
                "columns",
                "page_size",
                "sortable",
                "filterable",
                "row_selection_enabled",
                "row_selection_column",
            ],
            "image": [
                # mandatory
                "image_column",
                # optional user-defined
                "s3_base_folder",
                "thumbnail_size",
                "columns",
                "max_images",
            ],
            "multiqc": [
                # mandatory
                "selected_module",
                "selected_plot",
            ],
        }

        # Generated on export — placed last to separate from user-authored fields
        generated = ["tag", "index", "layout", "title"]

        return mandatory_common + type_sections.get(comp_type, []) + generated

    @staticmethod
    def _clean_component_for_yaml(comp: dict[str, Any]) -> dict[str, Any]:
        """Clean a single component dict for YAML export.

        Applies per-type field ordering with sentinel section separators:
          1. Mandatory common + type-specific required fields
          2. ``# --- optional ---`` sentinel (if optional fields are present)
          3. Optional user-defined fields
          4. ``# --- generated on export ---`` sentinel (if generated fields are present)
          5. Export-generated fields (tag, layout)

        Also strips empty values, auto-generated UUIDs, and table defaults.
        Sentinels are replaced by comment lines via ``_apply_section_comments()``.
        """
        comp_type = comp.get("component_type", "")

        # Per-type mandatory field sets
        _MANDATORY_COMMON: set[str] = {"component_type", "workflow_tag", "data_collection_tag"}
        _MANDATORY_BY_TYPE: dict[str, set[str]] = {
            "figure": {"visu_type"},
            "card": {"aggregation", "column_name"},
            "interactive": {"interactive_component_type", "column_name"},
            "image": {"image_column"},
            "multiqc": {"selected_module", "selected_plot"},
            "table": set(),
        }
        _GENERATED: set[str] = {"tag", "index", "layout", "title"}

        mandatory_keys = _MANDATORY_COMMON | _MANDATORY_BY_TYPE.get(comp_type, set())
        table_defaults = {"page_size": 10, "sortable": True, "filterable": True}
        is_table = comp_type == "table"

        field_order = DashboardDataLite._get_component_field_order(comp_type)
        all_keys = list(field_order) + [k for k in comp if k not in field_order]

        mandatory: dict[str, Any] = {}
        optional: dict[str, Any] = {}
        generated: dict[str, Any] = {}

        for key in all_keys:
            if key in mandatory or key in optional or key in generated:
                continue
            if key not in comp:
                continue
            value = comp[key]
            if DashboardDataLite._is_empty_value(value):
                continue
            if key == "index" and isinstance(value, str) and DashboardDataLite._is_uuid_like(value):
                continue
            if is_table and key in table_defaults and value == table_defaults[key]:
                continue
            if key in mandatory_keys:
                mandatory[key] = value
            elif key in _GENERATED:
                generated[key] = value
            else:
                optional[key] = value

        # Assemble with sentinel separators between non-empty sections
        result: dict[str, Any] = dict(mandatory)
        if optional:
            result[DashboardDataLite.SENTINEL_OPTIONAL] = None
            result.update(optional)
        if generated:
            result[DashboardDataLite.SENTINEL_GENERATED] = None
            result.update(generated)

        return result

    @classmethod
    def from_yaml(cls, content: str) -> "DashboardDataLite":
        """Parse and validate YAML content.

        Supports both single-tab and multi-tab formats:
        - Single: {dashboard_id, title, components, ...}
        - Multi:  {main_dashboard: {...}, tabs: [...]}

        Args:
            content: YAML string content

        Returns:
            Validated DashboardDataLite instance (main dashboard only for multi-tab)

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

        # Check if this is multi-tab format (has main_dashboard key)
        if "main_dashboard" in data:
            # Multi-tab format: extract main dashboard only
            # Note: Child tabs are ignored during validation (they're imported separately)
            data = data["main_dashboard"]

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
            - errors: List of error dictionaries (empty if valid).
              Component-level errors have: {type, tag, loc, msg}
              Other errors have: {type, msg}
        """
        try:
            cls.from_yaml(content)
            return True, []
        except ValidationError as e:
            # ValidationError must be caught before ValueError because
            # Pydantic v2's ValidationError is a ValueError subclass.
            parsed: list[dict[str, Any]] = []
            for pydantic_err in e.errors():
                msg = pydantic_err.get("msg", "")
                component_errors = _parse_component_lines(msg)
                if component_errors:
                    parsed.extend(component_errors)
                else:
                    parsed.append(
                        {
                            "type": pydantic_err.get("type", "validation_error"),
                            "loc": pydantic_err.get("loc", ()),
                            "msg": _strip_value_error_prefix(msg),
                        }
                    )
            return False, parsed
        except ValueError as e:
            return False, [{"type": "yaml_error", "msg": str(e)}]

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

        def collect_display_fields(comp: dict, field_names: list[str]) -> dict[str, Any]:
            """Collect non-empty display/styling fields from a component."""
            return {f: comp[f] for f in field_names if comp.get(f)}

        _COLUMN_TYPE_MAP = {
            "datetime64": "datetime",
            "datetime64[ns]": "datetime",
            "timedelta64": "timedelta",
            "timedelta64[ns]": "timedelta",
            "int32": "int64",
            "int16": "int64",
            "uint64": "int64",
            "uint32": "int64",
            "float32": "float64",
        }

        def normalize_column_type(raw: str, default: str) -> str:
            """Normalize raw pandas/numpy dtype strings to valid ColumnType values."""
            return _COLUMN_TYPE_MAP.get(raw, raw) if raw else default

        dashboard_id = extract_id(dashboard_data.get("dashboard_id") or dashboard_data.get("_id"))
        lite_components = []

        # Import tag generation function
        from depictio.models.yaml_serialization.utils import generate_component_id

        # Build layout lookup: component_index → {x, y, w, h}
        # All dashboards use split-panel layout: interactives in left_panel_layout_data,
        # all other components in right_panel_layout_data. stored_layout_data is legacy/empty.
        layout_lookup: dict[str, dict[str, int]] = {}
        for panel_key in [
            "stored_layout_data",
            "left_panel_layout_data",
            "right_panel_layout_data",
        ]:
            for layout_item in dashboard_data.get(panel_key, []):
                i_field = layout_item.get("i", "")
                if i_field.startswith("box-"):
                    comp_index = i_field[4:]  # Strip "box-" prefix
                    layout_lookup[comp_index] = {
                        "x": layout_item.get("x", 0),
                        "y": layout_item.get("y", 0),
                        "w": layout_item.get("w", 6),
                        "h": layout_item.get("h", 4),
                    }

        for idx, comp in enumerate(dashboard_data.get("stored_metadata", [])):
            comp_type = comp.get("component_type", "figure")

            # Generate semantic tag with format: {type}-{semantic_id}-{hash[:6]}
            # Uses existing index if available, otherwise generates from component data
            tag = comp.get("tag") or generate_component_id(comp, idx)

            # Extract workflow and data collection tags (mandatory fields)
            workflow_tag = comp.get("workflow_tag") or comp.get("wf_tag", "")
            dc_config = comp.get("dc_config", {})
            data_collection_tag = comp.get("data_collection_tag") or dc_config.get(
                "data_collection_tag", ""
            )

            # Log warning if mandatory tags are missing
            if not workflow_tag:
                logger.warning(
                    f"Component {tag} (type: {comp_type}) missing workflow_tag. "
                    f"Component has wf_id: {comp.get('wf_id') is not None}"
                )
            if not data_collection_tag:
                logger.warning(
                    f"Component {tag} (type: {comp_type}) missing data_collection_tag. "
                    f"Component has dc_id: {comp.get('dc_id') is not None}"
                )

            lite_comp: dict[str, Any] = {
                "tag": tag,
                "component_type": comp_type,
                "workflow_tag": workflow_tag,
                "data_collection_tag": data_collection_tag,
            }

            # Layout fields - read from stored_layout_data lookup (keyed by component index)
            comp_index_str = str(comp.get("index", ""))
            comp_layout = layout_lookup.get(comp_index_str, {"x": 0, "y": 0, "w": 6, "h": 4})
            lite_comp["layout"] = comp_layout

            if comp.get("title"):
                lite_comp["title"] = comp["title"]

            if comp_type == "figure":
                lite_comp["visu_type"] = comp.get("visu_type", "scatter")
                figure_params = filter_dict_kwargs(comp.get("dict_kwargs", {}))
                if figure_params:
                    lite_comp["figure_params"] = figure_params
                # Export mode (ui/code), code_content, and selection_enabled
                lite_comp["mode"] = comp.get("mode", "ui")
                if comp.get("code_content"):
                    lite_comp["code_content"] = comp["code_content"]
                if comp.get("selection_enabled") is not None:
                    lite_comp["selection_enabled"] = comp["selection_enabled"]
                # Preserve customizations if present
                if comp.get("customizations"):
                    lite_comp["customizations"] = comp["customizations"]

            elif comp_type == "card":
                lite_comp["aggregation"] = comp.get("aggregation", "")
                lite_comp["column_name"] = comp.get("column_name", "")
                lite_comp["column_type"] = normalize_column_type(
                    comp.get("column_type", ""), "float64"
                )
                display = collect_display_fields(
                    comp,
                    [
                        "icon_name",
                        "icon_color",
                        "title_color",
                        "title_font_size",
                        "value_font_size",
                    ],
                )
                if display:
                    lite_comp["display"] = display

            elif comp_type == "interactive":
                lite_comp["interactive_component_type"] = comp.get("interactive_component_type", "")
                lite_comp["column_name"] = comp.get("column_name", "")
                lite_comp["column_type"] = normalize_column_type(
                    comp.get("column_type", ""), "object"
                )
                display = collect_display_fields(comp, ["title_size", "custom_color", "icon_name"])
                if display:
                    lite_comp["display"] = display

            elif comp_type == "table":
                if comp.get("columns"):
                    lite_comp["columns"] = comp["columns"]
                if comp.get("page_size") and comp["page_size"] != 10:
                    lite_comp["page_size"] = comp["page_size"]
                if comp.get("sortable") is False:
                    lite_comp["sortable"] = False
                if comp.get("filterable") is False:
                    lite_comp["filterable"] = False

            elif comp_type == "image":
                lite_comp["image_column"] = comp.get("image_column", "")
                # NOTE: s3_base_folder is NOT exported - regenerated on import from DC config
                # This keeps YAML minimal and ensures data collection paths are current
                if comp.get("thumbnail_size") and comp["thumbnail_size"] != 150:
                    lite_comp["thumbnail_size"] = comp["thumbnail_size"]
                if comp.get("columns") and comp["columns"] != 4:
                    lite_comp["columns"] = comp["columns"]
                if comp.get("max_images") and comp["max_images"] != 20:
                    lite_comp["max_images"] = comp["max_images"]

            elif comp_type == "multiqc":
                # MultiQC parameters - export only if present in DB
                if comp.get("selected_module"):
                    lite_comp["selected_module"] = comp["selected_module"]
                if comp.get("selected_plot"):
                    lite_comp["selected_plot"] = comp["selected_plot"]

            # Export index field only if it's meaningful (not an auto-generated UUID)
            comp_index = comp.get("index", "").strip()
            if comp_index and not cls._is_uuid_like(comp_index):
                lite_comp["index"] = comp_index

            lite_components.append(lite_comp)

        return cls(
            dashboard_id=dashboard_id,
            title=dashboard_data.get("title", "Untitled Dashboard"),
            subtitle=dashboard_data.get("subtitle", ""),
            components=lite_components,
            # Tab fields
            is_main_tab=dashboard_data.get("is_main_tab", True),
            tab_order=dashboard_data.get("tab_order", 0),
            main_tab_name=dashboard_data.get("main_tab_name"),
            tab_icon=dashboard_data.get("tab_icon"),
            tab_icon_color=dashboard_data.get("tab_icon_color"),
            # Dashboard display icon fields
            icon=dashboard_data.get("icon"),
            icon_color=dashboard_data.get("icon_color"),
            icon_variant=dashboard_data.get("icon_variant"),
            workflow_system=dashboard_data.get("workflow_system"),
            # parent_dashboard_tag is not set here - it needs to be resolved separately
            # during export by looking up the parent dashboard title
        )

    def to_full(self) -> dict[str, Any]:
        """Convert lite format back to full dashboard dict.

        Returns:
            Full dashboard dictionary ready for MongoDB insertion
        """
        import uuid
        from datetime import datetime

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
            "icon": self.icon or "mdi:view-dashboard",
            "icon_color": self.icon_color or "orange",
            "icon_variant": self.icon_variant or "filled",
            "workflow_system": self.workflow_system or "none",
            "notes_content": "",
            "is_public": False,
            "permissions": {"owners": [], "editors": [], "viewers": []},
            # Tab support fields
            "is_main_tab": self.is_main_tab,
            "tab_order": self.tab_order,
            "main_tab_name": self.main_tab_name,
            "tab_icon": self.tab_icon,
            "tab_icon_color": self.tab_icon_color,
            # parent_dashboard_tag is resolved to parent_dashboard_id during import
        }

        if self.dashboard_id:
            full_dict["dashboard_id"] = self.dashboard_id

        full_components = []
        for comp in self.components:
            comp_dict = comp if isinstance(comp, dict) else comp.model_dump()

            # Unpack nested layout dict (new format) into flat comp_dict fields
            layout_nested = comp_dict.get("layout", {})
            if layout_nested and isinstance(layout_nested, dict):
                comp_dict = {**comp_dict, **layout_nested}

            # Unpack nested display dict (card/interactive styling) into flat comp_dict fields
            display_nested = comp_dict.get("display", {})
            if display_nested and isinstance(display_nested, dict):
                comp_dict = {**comp_dict, **display_nested}

            full_comp = build_base_component(comp_dict)
            comp_type = comp_dict.get("component_type", "figure")

            if comp_type == "figure":
                # Support figure_params (new YAML key) and dict_kwargs (legacy/internal)
                figure_params = comp_dict.get("figure_params") or comp_dict.get("dict_kwargs", {})
                figure_fields: dict[str, Any] = {
                    "visu_type": comp_dict.get("visu_type", "scatter"),
                    "dict_kwargs": figure_params,
                    "mode": comp_dict.get("mode", "ui"),  # Use imported mode (ui/code)
                    "code_content": comp_dict.get("code_content"),  # Preserved for code mode
                    "displayed_data_count": 0,
                    "total_data_count": 0,
                    "was_sampled": False,
                    "filter_applied": False,
                    # Selection filtering fields
                    "selection_enabled": comp_dict.get("selection_enabled", False),
                    "selection_column": comp_dict.get("selection_column"),
                }
                # Pass through customizations if present
                if comp_dict.get("customizations"):
                    figure_fields["customizations"] = comp_dict["customizations"]
                full_comp.update(figure_fields)

            elif comp_type == "card":
                full_comp.update(
                    {
                        "aggregation": comp_dict.get("aggregation", ""),
                        "column_name": comp_dict.get("column_name", ""),
                        "column_type": comp_dict.get("column_type", "float64"),
                        "value": None,
                    }
                )
                for f in [
                    "icon_name",
                    "icon_color",
                    "title_color",
                    "title_font_size",
                    "value_font_size",
                ]:
                    if comp_dict.get(f):
                        full_comp[f] = comp_dict[f]

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
                for f in ["title_size", "custom_color", "icon_name"]:
                    if comp_dict.get(f):
                        full_comp[f] = comp_dict[f]

            elif comp_type == "table":
                full_comp.update(
                    {
                        "columns": comp_dict.get("columns", []),
                        "page_size": comp_dict.get("page_size", 10),
                        "sortable": comp_dict.get("sortable", True),
                        "filterable": comp_dict.get("filterable", True),
                        # Row selection filtering fields
                        "row_selection_enabled": comp_dict.get("row_selection_enabled", False),
                        "row_selection_column": comp_dict.get("row_selection_column"),
                    }
                )

            elif comp_type == "image":
                # s3_base_folder regeneration: fetch from DC config if not provided
                s3_base_folder = comp_dict.get("s3_base_folder")
                if not s3_base_folder:
                    # Regenerate from dc_config if available
                    dc_config = full_comp.get("dc_config", {})
                    dc_specific_props = dc_config.get("dc_specific_properties", {})
                    s3_base_folder = dc_specific_props.get("s3_base_folder")

                full_comp.update(
                    {
                        "image_column": comp_dict.get("image_column", ""),
                        "s3_base_folder": s3_base_folder,  # Will be None if not found
                        "thumbnail_size": comp_dict.get("thumbnail_size", 150),
                        "columns": comp_dict.get("columns", 4),
                        "max_images": comp_dict.get("max_images", 20),
                    }
                )

            elif comp_type == "multiqc":
                for f in ["selected_module", "selected_plot"]:
                    if comp_dict.get(f):
                        full_comp[f] = comp_dict[f]

            full_components.append(full_comp)

        full_dict["stored_metadata"] = full_components

        # Generate layout using split-panel system:
        # - interactive components → left_panel_layout_data (w=1, static=False)
        # - all other components → right_panel_layout_data (cards static=True, others resizable)
        from depictio.models.yaml_serialization.utils import auto_generate_layout

        left_panel_layout_data: list[dict[str, Any]] = []
        right_panel_layout_data: list[dict[str, Any]] = []
        left_auto_y = 0
        right_auto_y = 0

        for idx, comp in enumerate(full_components):
            comp_dict = (
                self.components[idx]
                if isinstance(self.components[idx], dict)
                else self.components[idx].model_dump()
            )
            comp_type = comp.get("component_type", "figure")

            # Extract x/y/w/h from nested layout (new format), flat fields (legacy), or auto-generate
            layout_nested = comp_dict.get("layout", {})
            if layout_nested and isinstance(layout_nested, dict):
                x = layout_nested.get("x", 0)
                y = layout_nested.get("y", 0)
                w = layout_nested.get("w", 6)
                h = layout_nested.get("h", 4)
            elif all(key in comp_dict for key in ["x", "y", "w", "h"]):
                x = comp_dict["x"]
                y = comp_dict["y"]
                w = comp_dict["w"]
                h = comp_dict["h"]
            else:
                # Auto-generate position based on panel
                if comp_type == "interactive":
                    x, w, h = 0, 1, 3
                    y = left_auto_y
                    left_auto_y += h
                else:
                    auto = auto_generate_layout(idx, comp_type)
                    x, y, w, h = auto["x"], right_auto_y, auto["w"], auto["h"]
                    right_auto_y += h

            # Build layout item -- static and resizeHandles inferred from component type
            layout_item: dict[str, Any] = {
                "i": f"box-{comp['index']}",
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "static": comp_type == "card",
            }
            if comp_type not in ("interactive", "card"):
                layout_item["resizeHandles"] = ["se", "s", "e", "sw", "w"]

            if comp_type == "interactive":
                left_panel_layout_data.append(layout_item)
            else:
                right_panel_layout_data.append(layout_item)

        full_dict["stored_layout_data"] = []
        full_dict["left_panel_layout_data"] = left_panel_layout_data
        full_dict["right_panel_layout_data"] = right_panel_layout_data
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
    main_tab_name: Optional[str] = None  # Custom name for main tab (defaults to "Main" if None)
    tab_icon: Optional[str] = None  # Icon for child tabs (e.g., "mdi:chart-bar")
    tab_icon_color: Optional[str] = None  # Color for tab icon
    parent_dashboard_title: Optional[str] = (
        None  # Populated at runtime for child tabs (header display)
    )

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
