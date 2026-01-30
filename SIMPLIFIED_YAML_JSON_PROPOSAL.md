# Simplified YAML/JSON System Proposal

**Date**: 2026-01-30
**Goal**: Keep YAML for human editing, simplify to single lightweight model
**Key Insight**: Problem isn't YAML vs JSON - it's overcomplexity and mixed concerns

---

## Executive Summary

**Current Problem**: 3,399 lines of code with 3 competing YAML formats, complex validation, mixed concerns

**Solution**: ONE lightweight `DashboardSchema` model that supports BOTH YAML and JSON

**Benefits**:
- ✅ Keep YAML (human-editable, git-friendly)
- ✅ Add JSON (API/programmatic access)
- ✅ Single format (not 3 competing formats)
- ✅ Simple: ~250 lines vs 3,399 lines (93% reduction)

---

## Architecture: Unified Simple Model

### Core Principle

**One Lightweight Model, Two Serialization Formats**

```python
# The SAME model handles both formats
schema = DashboardSchema(
    title="Sales Dashboard",
    stored_metadata=[...],
    stored_layout_data=[...],
)

# YAML serialization
schema.to_yaml_file("dashboard.yaml")
loaded = DashboardSchema.from_yaml_file("dashboard.yaml")

# JSON serialization
schema.to_json_file("dashboard.json")
loaded = DashboardSchema.from_json_file("dashboard.json")

# Convert to/from full DashboardData
dashboard = schema.to_dashboard_data(project_id="...", user=current_user)
schema = DashboardSchema.from_dashboard_data(dashboard)
```

### Benefits of Keeping YAML

| Use Case | YAML | JSON |
|----------|------|------|
| **Human Editing** | ✅ Best | ⚠️ OK |
| **Git Diffs** | ✅ Best | ⚠️ OK |
| **Comments** | ✅ Yes | ❌ No |
| **Readability** | ✅ Best | ⚠️ OK |
| **API Integration** | ⚠️ OK | ✅ Best |
| **Programmatic** | ⚠️ OK | ✅ Best |
| **MCP Tools** | ⚠️ OK | ✅ Best |

**Conclusion**: Support BOTH formats, let users choose based on their workflow.

---

## DashboardSchema Model (Single Format)

### Model Definition

```python
from pydantic import BaseModel, Field, field_validator
from typing import Any
import yaml
import json


class DashboardSchema(BaseModel):
    """
    Lightweight dashboard structure for YAML/JSON export/import.

    Supports BOTH YAML and JSON serialization through Pydantic.

    Excludes:
    - Authorization (permissions, is_public)
    - System metadata (dashboard_id, project_id, version)
    - Runtime state (tmp_*, buttons_data)

    Use Cases:
    - Export dashboard as portable template (YAML or JSON)
    - Import dashboard into different project
    - Version control dashboard structure (git-friendly YAML)
    - Programmatic creation (JSON via API/MCP)
    """

    # ===== REQUIRED FIELDS =====

    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Dashboard title",
    )

    stored_metadata: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Component configurations",
    )

    stored_layout_data: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Grid layout positions",
    )

    # ===== OPTIONAL FIELDS =====

    subtitle: str = Field(default="", max_length=500)
    icon: str = Field(default="mdi:view-dashboard")
    icon_color: str = Field(default="orange")
    icon_variant: str = Field(default="filled")
    notes_content: str = Field(default="")
    workflow_system: str = Field(default="none")

    # Dual-panel support
    left_panel_layout_data: list[dict[str, Any]] = Field(default_factory=list)
    right_panel_layout_data: list[dict[str, Any]] = Field(default_factory=list)

    # Tab support
    is_main_tab: bool = Field(default=True)
    tab_order: int = Field(default=0, ge=0)

    # ===== VALIDATION =====

    @field_validator("stored_metadata")
    @classmethod
    def validate_components(cls, components: list[dict]) -> list[dict]:
        """Validate component structure."""
        for idx, component in enumerate(components):
            if "index" not in component:
                raise ValueError(f"Component {idx} missing 'index' field")
        return components

    @field_validator("stored_layout_data")
    @classmethod
    def validate_layout(cls, layout: list[dict]) -> list[dict]:
        """Validate react-grid-layout structure."""
        for idx, item in enumerate(layout):
            required = ["i", "x", "y", "w", "h"]
            missing = [f for f in required if f not in item]
            if missing:
                raise ValueError(f"Layout item {idx} missing: {missing}")
        return layout

    # ===== YAML SERIALIZATION =====

    def to_yaml(self, **kwargs) -> str:
        """Export to YAML string."""
        data = self.model_dump()
        return yaml.dump(data, default_flow_style=False, sort_keys=False, **kwargs)

    def to_yaml_file(self, filepath: str | Path) -> Path:
        """Export to YAML file."""
        filepath = Path(filepath)
        filepath.write_text(self.to_yaml())
        return filepath

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "DashboardSchema":
        """Import from YAML string."""
        data = yaml.safe_load(yaml_str)
        return cls.model_validate(data)

    @classmethod
    def from_yaml_file(cls, filepath: str | Path) -> "DashboardSchema":
        """Import from YAML file."""
        filepath = Path(filepath)
        return cls.from_yaml(filepath.read_text())

    # ===== JSON SERIALIZATION =====

    def to_json(self, **kwargs) -> str:
        """Export to JSON string."""
        return json.dumps(self.model_dump(), indent=2, **kwargs)

    def to_json_file(self, filepath: str | Path) -> Path:
        """Export to JSON file."""
        filepath = Path(filepath)
        filepath.write_text(self.to_json())
        return filepath

    @classmethod
    def from_json(cls, json_str: str) -> "DashboardSchema":
        """Import from JSON string."""
        data = json.loads(json_str)
        return cls.model_validate(data)

    @classmethod
    def from_json_file(cls, filepath: str | Path) -> "DashboardSchema":
        """Import from JSON file."""
        filepath = Path(filepath)
        return cls.from_json(filepath.read_text())

    # ===== CONVERSION TO/FROM DashboardData =====

    @classmethod
    def from_dashboard_data(cls, dashboard: "DashboardData") -> "DashboardSchema":
        """
        Extract lightweight schema from full DashboardData.

        Excludes auth, metadata, runtime state.
        """
        return cls(
            title=dashboard.title,
            subtitle=dashboard.subtitle,
            stored_metadata=dashboard.stored_metadata,
            stored_layout_data=dashboard.stored_layout_data,
            icon=dashboard.icon,
            icon_color=dashboard.icon_color,
            icon_variant=dashboard.icon_variant,
            notes_content=dashboard.notes_content,
            workflow_system=dashboard.workflow_system,
            left_panel_layout_data=dashboard.left_panel_layout_data,
            right_panel_layout_data=dashboard.right_panel_layout_data,
            is_main_tab=dashboard.is_main_tab,
            tab_order=dashboard.tab_order,
        )

    def to_dashboard_data(
        self,
        project_id: str,
        user: "User",
        dashboard_id: str | None = None,
    ) -> "DashboardData":
        """
        Create full DashboardData with auth and metadata.

        Args:
            project_id: Project to associate with
            user: User creating dashboard (set as owner)
            dashboard_id: Optional existing ID (for updates)
        """
        from bson import ObjectId
        from depictio.models.models.users import UserBase, Permission

        dash_id = ObjectId(dashboard_id) if dashboard_id else ObjectId()

        permissions = Permission(
            owners=[UserBase(id=user.id, email=user.email, is_admin=user.is_admin)],
            editors=[],
            viewers=[],
        )

        return DashboardData(
            dashboard_id=dash_id,
            title=self.title,
            subtitle=self.subtitle,
            stored_metadata=self.stored_metadata,
            stored_layout_data=self.stored_layout_data,
            icon=self.icon,
            icon_color=self.icon_color,
            icon_variant=self.icon_variant,
            notes_content=self.notes_content,
            workflow_system=self.workflow_system,
            left_panel_layout_data=self.left_panel_layout_data,
            right_panel_layout_data=self.right_panel_layout_data,
            is_main_tab=self.is_main_tab,
            tab_order=self.tab_order,
            project_id=ObjectId(project_id),
            permissions=permissions,
            version=1,
        )
```

**Total Lines**: ~150 lines (one model, both formats)

---

## Example YAML Format

### Simple Dashboard (Human-Editable)

```yaml
# Sales Dashboard - Q4 2025
# Last updated: 2025-12-01

title: Sales Dashboard
subtitle: Q4 2025 Performance Metrics
icon: mdi:chart-line
icon_color: blue
icon_variant: filled

# Dashboard components
stored_metadata:
  - index: revenue-card
    type: card
    dc_id: "646b0f3c1e4a2d7f8e5b8c9c"
    config:
      aggregation_function: sum
      column_name: revenue
      title: Total Revenue

  - index: revenue-chart
    type: figure
    dc_id: "646b0f3c1e4a2d7f8e5b8c9c"
    config:
      chart_type: scatter
      x_column: date
      y_column: revenue
      title: Revenue Over Time

# Layout (react-grid-layout format)
stored_layout_data:
  - i: box-revenue-card
    x: 0
    y: 0
    w: 6
    h: 6

  - i: box-revenue-chart
    x: 6
    y: 0
    w: 12
    h: 8

# Optional features
workflow_system: none
notes_content: |
  ## Dashboard Notes

  This dashboard tracks Q4 2025 sales performance.
  Data source: sales_data table
  Update frequency: Daily
```

**Benefits**:
- ✅ Human-readable with comments
- ✅ Git-friendly (clear diffs when layout changes)
- ✅ Self-documenting
- ✅ Easy to edit by hand

---

## Comparison: Current vs Simplified

### Current YAML System (3,399 lines)

```
depictio/models/yaml_serialization/
├── export.py              # 800+ lines - 3 format export logic
├── loader.py              # 600+ lines - 3 format import logic
├── compact_format.py      # 500+ lines - Compact format
├── mvp_format.py          # 400+ lines - MVP format
├── utils.py               # 300+ lines - Conversions
└── validation.py          # 400+ lines - Custom validation

depictio/api/v1/services/
└── yaml_watcher.py        # 350+ lines - Thread management

Total: 3,399 lines
Formats: 3 competing formats
Validation: Custom system
```

### Simplified System (~250 lines)

```
depictio/models/schemas/
└── dashboard_schema.py    # 150 lines - ONE model, BOTH formats

depictio/api/v1/services/
└── file_watcher.py        # 30 lines - Optional async watcher (if needed)

depictio/api/v1/endpoints/dashboards_endpoints/
└── routes.py              # +70 lines - YAML/JSON endpoints

Total: ~250 lines
Formats: 1 unified format (YAML or JSON serialization)
Validation: Pydantic built-in
```

**Reduction**: 93% (3,399 → 250 lines)

---

## Implementation Plan

### Phase 1: Create DashboardSchema Model

**File**: `depictio/models/schemas/dashboard_schema.py`

```python
from pydantic import BaseModel, Field
import yaml
import json

class DashboardSchema(BaseModel):
    """One model, both YAML and JSON support."""

    # Fields (as shown above)
    title: str = Field(...)
    stored_metadata: list[dict] = Field(default_factory=list)
    # ... etc

    # YAML methods (using PyYAML)
    def to_yaml(self) -> str: ...
    def to_yaml_file(self, path) -> Path: ...
    @classmethod
    def from_yaml(cls, yaml_str) -> "DashboardSchema": ...

    # JSON methods (using stdlib json)
    def to_json(self) -> str: ...
    def to_json_file(self, path) -> Path: ...
    @classmethod
    def from_json(cls, json_str) -> "DashboardSchema": ...

    # Conversion methods
    @classmethod
    def from_dashboard_data(cls, dashboard) -> "DashboardSchema": ...
    def to_dashboard_data(self, project_id, user) -> "DashboardData": ...
```

**Lines**: ~150

---

### Phase 2: Update API Endpoints

**File**: `depictio/api/v1/endpoints/dashboards_endpoints/routes.py`

```python
# Export endpoints (support both formats)
@router.get("/dashboards/{dashboard_id}/export")
async def export_dashboard(
    dashboard_id: str,
    format: Literal["yaml", "json"] = "yaml",
    current_user: User = Depends(get_current_user),
):
    """Export dashboard as YAML or JSON."""
    dashboard = await DashboardData.find_one({"dashboard_id": ObjectId(dashboard_id)})

    # Convert to lightweight schema
    schema = DashboardSchema.from_dashboard_data(dashboard)

    # Serialize based on format
    if format == "yaml":
        content = schema.to_yaml()
        media_type = "application/x-yaml"
        filename = f"{dashboard.title}.yaml"
    else:
        content = schema.to_json()
        media_type = "application/json"
        filename = f"{dashboard.title}.json"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# Import endpoint (auto-detect format)
@router.post("/dashboards/import")
async def import_dashboard(
    content: str,
    format: Literal["yaml", "json"] = "auto",
    project_id: str,
    current_user: User = Depends(get_current_user),
):
    """Import dashboard from YAML or JSON."""

    # Auto-detect format
    if format == "auto":
        format = "yaml" if content.strip().startswith("title:") else "json"

    # Parse to schema
    if format == "yaml":
        schema = DashboardSchema.from_yaml(content)
    else:
        schema = DashboardSchema.from_json(content)

    # Convert to DashboardData with auth
    dashboard = schema.to_dashboard_data(project_id, current_user)

    # Save
    await dashboard.save()

    return {"dashboard_id": str(dashboard.dashboard_id)}


# Validation endpoint
@router.post("/dashboards/validate")
async def validate_dashboard(
    content: str,
    format: Literal["yaml", "json"] = "auto",
):
    """Validate dashboard YAML/JSON without importing."""
    try:
        if format == "auto":
            format = "yaml" if content.strip().startswith("title:") else "json"

        if format == "yaml":
            schema = DashboardSchema.from_yaml(content)
        else:
            schema = DashboardSchema.from_json(content)

        return {"valid": True, "schema": schema.model_dump()}

    except Exception as e:
        return {"valid": False, "error": str(e)}
```

**Lines**: ~70

---

### Phase 3: Add CLI Commands

**File**: `depictio/cli/commands/dashboards.py`

```python
@dashboard_cli.command("export")
def export_dashboard(
    dashboard_id: str,
    format: str = "yaml",  # or "json"
    output: str = None,
):
    """Export dashboard to YAML or JSON."""
    # Fetch dashboard
    dashboard = get_dashboard(dashboard_id)

    # Convert to schema
    schema = DashboardSchema.from_dashboard_data(dashboard)

    # Export
    if format == "yaml":
        content = schema.to_yaml()
        ext = ".yaml"
    else:
        content = schema.to_json()
        ext = ".json"

    # Save or print
    if output:
        Path(output).write_text(content)
        console.print(f"✓ Exported to {output}")
    else:
        console.print(content)


@dashboard_cli.command("import")
def import_dashboard(
    file: str,
    project_id: str,
    format: str = "auto",  # auto-detect
):
    """Import dashboard from YAML or JSON."""
    content = Path(file).read_text()

    # Auto-detect
    if format == "auto":
        format = "yaml" if file.endswith(".yaml") or file.endswith(".yml") else "json"

    # Parse
    if format == "yaml":
        schema = DashboardSchema.from_yaml(content)
    else:
        schema = DashboardSchema.from_json(content)

    # Import via API
    result = api_client.post("/dashboards/import", json={
        "content": content,
        "format": format,
        "project_id": project_id,
    })

    console.print(f"✓ Imported dashboard: {result['dashboard_id']}")
```

**Lines**: ~50

---

### Phase 4: Optional File Watcher

**File**: `depictio/api/v1/services/file_watcher.py`

```python
import asyncio
from watchfiles import awatch
from pathlib import Path


async def watch_dashboard_directory(directory: Path):
    """
    Simple async file watcher for YAML/JSON files.

    Supports both formats automatically.
    """
    async for changes in awatch(directory):
        for change_type, path in changes:
            path = Path(path)

            # Skip non-dashboard files
            if path.suffix not in [".yaml", ".yml", ".json"]:
                continue

            try:
                # Load schema based on extension
                if path.suffix in [".yaml", ".yml"]:
                    schema = DashboardSchema.from_yaml_file(path)
                else:
                    schema = DashboardSchema.from_json_file(path)

                # Sync to MongoDB
                await sync_to_mongodb(schema, path)

            except Exception as e:
                logger.error(f"Failed to sync {path}: {e}")


async def sync_to_mongodb(schema: DashboardSchema, filepath: Path):
    """Sync file to MongoDB (update or create)."""
    # Extract dashboard ID from filename or metadata
    # Update existing or create new dashboard
    # Preserve permissions and metadata
    pass
```

**Lines**: ~30 (optional)

---

## Total Implementation

| Component | Lines | Status |
|-----------|-------|--------|
| DashboardSchema model | ~150 | Phase 1 |
| API endpoints (3) | ~70 | Phase 2 |
| CLI commands (2) | ~50 | Phase 3 |
| **Core Total** | **~270** | **Required** |
| File watcher (optional) | ~30 | Phase 4 (optional) |
| **Total with watcher** | **~300** | |

**Comparison**:
- Current YAML system: 3,399 lines
- New unified system: 270-300 lines
- **Reduction: 91-92%**

---

## Migration Strategy

### From Current YAML System

The current YAML files can be migrated automatically:

```python
# Migration script
from depictio.models.yaml_serialization import import_dashboard_from_file
from depictio.models.schemas import DashboardSchema

# Load old YAML (using current complex system)
old_dashboard_dict = import_dashboard_from_file("old_dashboard.yaml")

# Convert to DashboardData
dashboard = DashboardData(**old_dashboard_dict)

# Export to new simple format
schema = DashboardSchema.from_dashboard_data(dashboard)
schema.to_yaml_file("new_dashboard.yaml")
```

The new YAML will be cleaner and simpler (no compact/MVP format variations).

---

## Key Benefits

### 1. Keep YAML's Strengths

- ✅ **Human-editable**: Easy to modify by hand
- ✅ **Git-friendly**: Clear diffs, merge conflicts easy to resolve
- ✅ **Comments**: Document dashboards inline
- ✅ **Readable**: Better than JSON for humans

### 2. Add JSON's Strengths

- ✅ **API-native**: No conversion needed
- ✅ **Programmatic**: Easy to generate/parse in code
- ✅ **MCP-ready**: Direct JSON Schema integration

### 3. Simplify Everything

- ✅ **One format**: Not 3 competing formats
- ✅ **One model**: DashboardSchema for both YAML and JSON
- ✅ **Pydantic validation**: No custom validation system
- ✅ **Clean separation**: Structure vs auth/metadata

### 4. Massive Code Reduction

- Current: 3,399 lines
- New: 270-300 lines
- **Reduction: 91-92%**

---

## Recommendation

**Implement unified system with BOTH YAML and JSON support**

**Why**:
1. ✅ Best of both worlds (YAML for humans, JSON for APIs)
2. ✅ Users choose based on workflow
3. ✅ 91% code reduction
4. ✅ Simple, maintainable
5. ✅ Future-proof (supports both use cases)

**Implementation Order**:
1. Create DashboardSchema model (Phase 1)
2. Add API endpoints with format parameter (Phase 2)
3. Add CLI commands with format parameter (Phase 3)
4. Optional: Add file watcher for auto-sync (Phase 4)

**Default format**: YAML (for human workflows), with JSON always available

---

## Next Steps

1. **Approve approach** - YAML + JSON via DashboardSchema
2. **Implement Phase 1** - Create model with both serialization methods
3. **Implement Phase 2** - Add API endpoints with format selection
4. **Implement Phase 3** - Add CLI with format selection
5. **Optional Phase 4** - Add file watcher if needed

**Ready to proceed?**
