# Dashboard JSON Schema Analysis & Minimal Implementation

**Date**: 2026-01-29
**Goal**: Create minimal JSON-based dashboard serialization with Pydantic validation
**Approach**: Lightweight schema excluding auth/metadata, bi-directional sync option

---

## Executive Summary

**Problem**: `DashboardData` model contains 30+ fields mixing dashboard structure with runtime metadata and authorization data.

**Solution**: Create `DashboardSchema` - a minimal Pydantic model with only essential dashboard structure (9 core fields).

**Benefits**:
- ✅ **Clean separation**: Structure vs metadata/auth
- ✅ **Portable**: Export/import without exposing permissions
- ✅ **Validation**: Pydantic + JSON Schema for API/CLI
- ✅ **Simple**: ~50 lines vs DashboardData's complexity

---

## DashboardData Field Analysis

### Current Model (30+ fields)

```python
class DashboardData(MongoModel):
    # ============ ESSENTIAL (Dashboard Structure) ============
    stored_metadata: list = []          # ✅ Component configurations
    stored_layout_data: list = []       # ✅ Grid layout positions
    title: str                           # ✅ Dashboard name
    subtitle: str = ""                   # ✅ Description

    # ============ OPTIONAL (Visual/Organization) ============
    icon: str = "mdi:view-dashboard"    # ⚠️  UI decoration
    icon_color: str = "orange"          # ⚠️  UI decoration
    icon_variant: str = "filled"        # ⚠️  UI decoration
    notes_content: str = ""             # ⚠️  Documentation

    # ============ METADATA (Runtime/System) ============
    dashboard_id: PyObjectId            # ❌ Auto-generated (MongoDB)
    version: int = 1                    # ❌ System versioning
    project_id: PyObjectId              # ❌ Context-specific
    last_saved_ts: str = ""             # ❌ Runtime metadata

    # ============ AUTHORIZATION (Security) ============
    permissions: Permission             # ❌ NOT for export
    is_public: bool = False             # ❌ NOT for export

    # ============ RUNTIME STATE (Temporary) ============
    tmp_children_data: list | None = [] # ❌ Temporary UI state
    stored_children_data: list = []     # ❌ Cached/computed data
    stored_edit_dashboard_mode_button: list = []  # ❌ UI state
    stored_add_button: dict = {"count": 0}  # ❌ UI state
    buttons_data: dict = {...}          # ❌ UI state

    # ============ ADVANCED FEATURES ============
    workflow_system: str = "none"       # ⚠️  Optional feature
    left_panel_layout_data: list = []   # ⚠️  Dual-panel feature
    right_panel_layout_data: list = []  # ⚠️  Dual-panel feature
    is_main_tab: bool = True            # ⚠️  Tab system
    parent_dashboard_id: Optional[PyObjectId] = None  # ⚠️  Tab system
    tab_order: int = 0                  # ⚠️  Tab system
```

### Field Categories

| Category | Count | Include in Export? | Reason |
|----------|-------|-------------------|---------|
| **Essential Structure** | 4 | ✅ YES | Core dashboard content |
| **Optional Visual** | 4 | ⚠️  OPTIONAL | Nice to have, not critical |
| **System Metadata** | 4 | ❌ NO | Auto-generated/context-specific |
| **Authorization** | 2 | ❌ NO | Security sensitive |
| **Runtime State** | 5 | ❌ NO | Temporary UI state |
| **Advanced Features** | 6 | ⚠️  OPTIONAL | Feature-specific |

---

## Minimal DashboardSchema Design

### Core Principles

1. **Structure Only**: Dashboard components and layout
2. **No Auth**: Permissions handled separately
3. **No IDs**: Generated on import
4. **Portable**: Works across projects/instances
5. **Validatable**: Pydantic + JSON Schema

### DashboardSchema Model

```python
from pydantic import BaseModel, Field, field_validator
from typing import Any


class DashboardSchema(BaseModel):
    """
    Minimal dashboard structure for JSON export/import.

    Excludes:
    - Authorization (permissions, is_public)
    - System metadata (dashboard_id, project_id, version, last_saved_ts)
    - Runtime state (tmp_*, stored_children_data, buttons_data)

    Use Cases:
    - Export dashboard as portable JSON template
    - Import dashboard into different project
    - Version control dashboard structure
    - Programmatic dashboard creation via API/CLI
    """

    # ===== REQUIRED FIELDS =====

    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Dashboard title",
        examples=["Sales Dashboard", "Iris Dataset Analysis"],
    )

    stored_metadata: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Component configurations (cards, figures, tables)",
        examples=[[
            {
                "index": "component-1",
                "type": "card",
                "dc_id": "646b0f3c1e4a2d7f8e5b8c9c",
                "config": {"aggregation_function": "mean", "column_name": "revenue"},
            }
        ]],
    )

    stored_layout_data: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Grid layout positions (react-grid-layout format)",
        examples=[[
            {"i": "box-component-1", "x": 0, "y": 0, "w": 6, "h": 6}
        ]],
    )

    # ===== OPTIONAL FIELDS =====

    subtitle: str = Field(
        default="",
        max_length=500,
        description="Dashboard subtitle/description",
    )

    icon: str = Field(
        default="mdi:view-dashboard",
        description="Material Design Icon identifier",
        examples=["mdi:chart-line", "mdi:table", "mdi:view-dashboard"],
    )

    icon_color: str = Field(
        default="orange",
        description="Icon color",
        examples=["blue", "green", "orange", "#FF5733"],
    )

    icon_variant: str = Field(
        default="filled",
        description="Icon variant",
        examples=["filled", "outlined"],
    )

    notes_content: str = Field(
        default="",
        description="Markdown notes/documentation for this dashboard",
    )

    workflow_system: str = Field(
        default="none",
        description="Workflow system integration",
        examples=["none", "nextflow", "snakemake"],
    )

    # ===== ADVANCED FEATURES (Optional) =====

    left_panel_layout_data: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Left panel grid layout (dual-panel mode)",
    )

    right_panel_layout_data: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Right panel grid layout (dual-panel mode)",
    )

    is_main_tab: bool = Field(
        default=True,
        description="Whether this is a main dashboard or sub-tab",
    )

    tab_order: int = Field(
        default=0,
        ge=0,
        description="Tab order (for multi-tab dashboards)",
    )

    # ===== VALIDATION =====

    @field_validator("stored_metadata")
    @classmethod
    def validate_components(cls, components: list[dict]) -> list[dict]:
        """Validate component structure."""
        for idx, component in enumerate(components):
            # Require index field
            if "index" not in component:
                raise ValueError(f"Component {idx} missing 'index' field")

            # Warn if missing type (but don't fail)
            if "type" not in component:
                import warnings
                warnings.warn(f"Component {component['index']} missing 'type' field")

        return components

    @field_validator("stored_layout_data")
    @classmethod
    def validate_layout(cls, layout: list[dict]) -> list[dict]:
        """Validate layout structure."""
        for idx, item in enumerate(layout):
            # react-grid-layout required fields
            required = ["i", "x", "y", "w", "h"]
            missing = [f for f in required if f not in item]
            if missing:
                raise ValueError(
                    f"Layout item {idx} missing required fields: {missing}"
                )

        return layout

    # ===== CONVENIENCE METHODS =====

    def to_json(self, **kwargs) -> str:
        """Export to JSON string."""
        import json
        return json.dumps(self.model_dump(), indent=2, **kwargs)

    def to_json_file(self, filepath: str | Path) -> Path:
        """Export to JSON file."""
        from pathlib import Path
        filepath = Path(filepath)
        filepath.write_text(self.to_json())
        return filepath

    @classmethod
    def from_json(cls, json_str: str) -> "DashboardSchema":
        """Import from JSON string."""
        import json
        data = json.loads(json_str)
        return cls.model_validate(data)

    @classmethod
    def from_json_file(cls, filepath: str | Path) -> "DashboardSchema":
        """Import from JSON file."""
        from pathlib import Path
        filepath = Path(filepath)
        return cls.from_json(filepath.read_text())

    @classmethod
    def from_dashboard_data(cls, dashboard: "DashboardData") -> "DashboardSchema":
        """
        Convert DashboardData to minimal DashboardSchema.

        Extracts only structure fields, excludes auth/metadata.
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
        Convert DashboardSchema to full DashboardData with auth/metadata.

        Args:
            project_id: Project to associate dashboard with
            user: User creating the dashboard (set as owner)
            dashboard_id: Optional existing dashboard ID (for updates)

        Returns:
            DashboardData ready for MongoDB insertion
        """
        from bson import ObjectId
        from depictio.models.models.users import UserBase, Permission

        # Generate new ID if not provided
        dash_id = ObjectId(dashboard_id) if dashboard_id else ObjectId()

        # Set permissions with user as owner
        permissions = Permission(
            owners=[UserBase(
                id=user.id,
                email=user.email,
                is_admin=user.is_admin,
            )],
            editors=[],
            viewers=[],
        )

        # Create full DashboardData
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

---

## JSON Schema Generation

### Auto-Generated from Pydantic

```python
# Get JSON Schema for API/MCP consumers
schema = DashboardSchema.model_json_schema()

# Save for documentation
import json
with open("dashboard_schema.json", "w") as f:
    json.dump(schema, f, indent=2)
```

### Generated Schema (Example)

```json
{
  "$defs": {},
  "properties": {
    "title": {
      "description": "Dashboard title",
      "examples": ["Sales Dashboard", "Iris Dataset Analysis"],
      "maxLength": 200,
      "minLength": 1,
      "title": "Title",
      "type": "string"
    },
    "stored_metadata": {
      "default": [],
      "description": "Component configurations (cards, figures, tables)",
      "items": {"type": "object"},
      "title": "Stored Metadata",
      "type": "array"
    },
    "stored_layout_data": {
      "default": [],
      "description": "Grid layout positions (react-grid-layout format)",
      "items": {"type": "object"},
      "title": "Stored Layout Data",
      "type": "array"
    },
    "subtitle": {
      "default": "",
      "description": "Dashboard subtitle/description",
      "maxLength": 500,
      "title": "Subtitle",
      "type": "string"
    }
  },
  "required": ["title"],
  "title": "DashboardSchema",
  "type": "object"
}
```

---

## File Watcher Analysis

### Current YAML System Complexity

**Pros**:
- ✅ Auto-sync on file changes
- ✅ Bidirectional (file ↔ MongoDB)
- ✅ Debouncing to avoid rapid re-sync

**Cons**:
- ❌ 300+ lines of watcher code
- ❌ Manual thread management
- ❌ Global state tracking
- ❌ Polling fallback complexity
- ❌ Difficult debugging

**Code Stats**:
```
depictio/api/v1/services/yaml_watcher.py: 350 lines
  - WatchdogHandler class
  - PollingWatcher fallback
  - Global _watcher_threads, _watcher_running, _watcher_stop_events
  - Debounce logic with threading.Timer
  - Error handling and logging
```

### Simplified JSON Watcher (If Needed)

**Option 1: Async File Watcher** (Recommended)

Use `watchfiles` (pure Python, async, no threads):

```python
# requirements: watchfiles (already using watchdog, similar)
import asyncio
from watchfiles import awatch
from pathlib import Path


async def watch_dashboard_directory(directory: Path):
    """
    Simple async file watcher for dashboard JSON files.

    Watches for changes and syncs to MongoDB.
    ~30 lines vs 350 lines for YAML system.
    """
    async for changes in awatch(directory, watch_filter=lambda _: True):
        for change_type, path in changes:
            if not path.endswith(".json"):
                continue

            try:
                if change_type in (Change.added, Change.modified):
                    # Load and validate JSON
                    schema = DashboardSchema.from_json_file(path)

                    # Find corresponding dashboard by filename/metadata
                    # Or create new one if doesn't exist
                    await sync_json_to_mongodb(schema, path)

                elif change_type == Change.deleted:
                    # Optional: delete from MongoDB or just ignore
                    pass

            except Exception as e:
                logger.error(f"Failed to sync {path}: {e}")


async def sync_json_to_mongodb(schema: DashboardSchema, filepath: Path):
    """Sync JSON file to MongoDB."""
    # Extract dashboard ID from filename or file content
    # e.g., "sales-dashboard-646b0f3c1e4a2d7f8e5b8c9a.json"

    # Load existing dashboard or create new one
    # Update only structure fields, preserve auth/metadata

    # Save to MongoDB
    pass


# Start watcher on API startup
@app.on_event("startup")
async def start_dashboard_watcher():
    if settings.dashboard_json.watch_enabled:
        asyncio.create_task(
            watch_dashboard_directory(settings.dashboard_json.watch_dir)
        )
```

**Complexity**: ~30-50 lines vs 350+ lines for YAML

---

**Option 2: API-Driven Only** (Simplest)

Skip file watching entirely. Use API endpoints for export/import:

```python
# Export dashboard to JSON file
POST /api/v1/dashboards/export/{dashboard_id}/json?save_to_dir=true

# Import dashboard from JSON file
POST /api/v1/dashboards/import/json/file
Content-Type: multipart/form-data
{file: dashboard.json}

# Sync all dashboards in project to directory
POST /api/v1/dashboards/export-all?project_id={id}&format=json
```

**Benefits**:
- ✅ No file watching complexity
- ✅ Explicit user control
- ✅ Works in containerized environments
- ✅ No background threads/tasks
- ✅ Easier debugging

**Workflow**:
```bash
# User workflow (CLI or API)
1. Export: depictio dashboard export --dashboard-id 123 --format json
2. Edit JSON file locally
3. Import: depictio dashboard import --file dashboard.json
```

---

**Option 3: Git-Based Sync** (Advanced)

Monitor git commits/pushes, sync on repository changes:

```python
# On git push to dashboards/ directory:
# 1. CI/CD webhook triggers API endpoint
# 2. API syncs changed JSON files to MongoDB

POST /api/v1/dashboards/sync-from-git
{
  "repository": "org/repo",
  "branch": "main",
  "changed_files": ["dashboards/sales.json"]
}
```

**Use Case**: GitOps workflows, Infrastructure as Code

---

## Recommendation Matrix

| Approach | Complexity | Auto-Sync | Use Case |
|----------|-----------|-----------|----------|
| **API-Driven Only** | ⭐ Simplest | ❌ No | Most users |
| **Async File Watcher** | ⭐⭐ Simple | ✅ Yes | Power users |
| **Git-Based Sync** | ⭐⭐⭐ Complex | ✅ Yes | Enterprise/GitOps |

### My Recommendation

**Start with API-Driven Only** (Option 2):

**Reasons**:
1. ✅ **98% simpler** than current YAML watcher
2. ✅ **Explicit control** - users trigger export/import
3. ✅ **Works everywhere** - containers, cloud, local
4. ✅ **Easy debugging** - no background tasks
5. ✅ **Matches JSON philosophy** - simple, direct

**Add Async Watcher Later** if users request it:
- ~30 lines of code (vs 350+ for YAML)
- Optional feature (disabled by default)
- Single async task (no threading complexity)

---

## Implementation Plan

### Phase 1: Core Models & Validation (This PR)

**Files to Create**:
```
depictio/models/schemas/
├── __init__.py
└── dashboard_schema.py           # DashboardSchema model (~150 lines)
```

**Tasks**:
- ✅ Create `DashboardSchema` Pydantic model
- ✅ Add validation methods
- ✅ Add conversion methods (to/from DashboardData)
- ✅ Generate JSON Schema
- ✅ Add unit tests

**Estimated Lines**: ~200 lines (model + tests)

---

### Phase 2: API Endpoints (This PR)

**Files to Modify**:
```
depictio/api/v1/endpoints/dashboards_endpoints/
└── routes.py                      # Add JSON endpoints
```

**New Endpoints**:
```python
# Export dashboard as JSON
GET /api/v1/dashboards/{dashboard_id}/export/json
  → Returns DashboardSchema JSON

# Import dashboard from JSON
POST /api/v1/dashboards/import/json
  → Accepts DashboardSchema JSON
  → Creates DashboardData with auth

# Get JSON Schema
GET /api/v1/dashboards/schema
  → Returns JSON Schema for validation

# Validate JSON without importing
POST /api/v1/dashboards/validate/json
  → Validates DashboardSchema JSON
  → Returns validation errors
```

**Estimated Lines**: ~150 lines

---

### Phase 3: CLI Commands (This PR)

**Files to Modify**:
```
depictio/cli/commands/
└── dashboards.py                  # Add JSON export/import commands
```

**New Commands**:
```bash
# Export dashboard to JSON
depictio dashboard export \
  --dashboard-id 646b0f3c1e4a2d7f8e5b8c9a \
  --format json \
  --output sales-dashboard.json

# Import dashboard from JSON
depictio dashboard import \
  --file sales-dashboard.json \
  --project-id 646b0f3c1e4a2d7f8e5b8c9a

# Validate JSON file
depictio dashboard validate \
  --file sales-dashboard.json

# Export all dashboards in project
depictio dashboard export-all \
  --project-id 646b0f3c1e4a2d7f8e5b8c9a \
  --format json \
  --output-dir ./dashboards/
```

**Estimated Lines**: ~100 lines

---

### Phase 4: Optional File Watcher (Future PR)

**Decision Point**: Only implement if users request it

**If Needed**:
```
depictio/api/v1/services/
└── json_watcher.py                # Async file watcher (~30 lines)
```

**Configuration**:
```python
class DashboardJSONConfig(BaseSettings):
    enabled: bool = True
    watch_enabled: bool = False     # Disabled by default
    watch_dir: Path = Path("dashboards/json")
    auto_export_on_save: bool = False
```

**Estimated Lines**: ~50 lines (watcher + config)

---

## Total Implementation Size

| Component | Lines of Code | Status |
|-----------|---------------|--------|
| DashboardSchema model | ~150 | Phase 1 |
| Unit tests | ~50 | Phase 1 |
| API endpoints (4) | ~150 | Phase 2 |
| CLI commands (4) | ~100 | Phase 3 |
| **Total (Core)** | **~450 lines** | **This PR** |
| File watcher (optional) | ~50 | Future (if needed) |
| **Total (with watcher)** | **~500 lines** | |

**Comparison**:
- Current YAML system: **3,399 lines**
- New JSON system: **450-500 lines**
- **Reduction: 85-87%**

---

## Example Usage

### API Usage

```python
import requests

# 1. Export dashboard
response = requests.get(
    "http://localhost:8058/api/v1/dashboards/646b0f3c1e4a2d7f8e5b8c9a/export/json",
    headers={"Authorization": f"Bearer {token}"}
)
dashboard_json = response.json()

# 2. Modify locally
dashboard_json["title"] = "Updated Sales Dashboard"
dashboard_json["stored_metadata"][0]["config"]["column_name"] = "new_revenue"

# 3. Validate
response = requests.post(
    "http://localhost:8058/api/v1/dashboards/validate/json",
    json=dashboard_json,
    headers={"Authorization": f"Bearer {token}"}
)
assert response.json()["valid"] == True

# 4. Import to different project
response = requests.post(
    "http://localhost:8058/api/v1/dashboards/import/json",
    json={
        "schema": dashboard_json,
        "project_id": "new-project-id"
    },
    headers={"Authorization": f"Bearer {token}"}
)
new_dashboard_id = response.json()["dashboard_id"]
```

### CLI Usage

```bash
# Export
depictio dashboard export \
  --dashboard-id 646b0f3c1e4a2d7f8e5b8c9a \
  --format json \
  --output sales.json

# Edit JSON file
vim sales.json

# Validate
depictio dashboard validate --file sales.json

# Import
depictio dashboard import \
  --file sales.json \
  --project-id new-project-id
```

### Programmatic Usage (Python)

```python
from depictio.models.schemas import DashboardSchema

# Create dashboard programmatically
schema = DashboardSchema(
    title="Programmatic Dashboard",
    subtitle="Created via Python API",
    stored_metadata=[
        {
            "index": "card-1",
            "type": "card",
            "dc_id": "646b0f3c1e4a2d7f8e5b8c9c",
            "config": {
                "aggregation_function": "sum",
                "column_name": "revenue",
            },
        },
    ],
    stored_layout_data=[
        {"i": "box-card-1", "x": 0, "y": 0, "w": 6, "h": 6},
    ],
)

# Validate
schema.model_validate(schema.model_dump())  # Raises ValidationError if invalid

# Export to JSON
schema.to_json_file("my_dashboard.json")

# Import from JSON
loaded = DashboardSchema.from_json_file("my_dashboard.json")
```

---

## Summary & Recommendations

### What to Build

**Core (This PR)**:
1. ✅ `DashboardSchema` Pydantic model (minimal structure)
2. ✅ JSON export/import API endpoints (4 endpoints)
3. ✅ JSON export/import CLI commands (4 commands)
4. ✅ JSON Schema generation for validation

**Total**: ~450 lines (85% reduction from YAML's 3,399 lines)

### What NOT to Build (Yet)

❌ **File Watcher** - Wait for user demand
  - If needed later: ~30 lines using async `watchfiles`
  - Current approach (API-driven) is simpler and sufficient

### File Watcher Decision

**My Strong Recommendation: API-Driven Only** (No Watcher)

**Reasons**:
1. **Simplicity**: No background tasks, no threading, no state management
2. **Control**: User explicitly exports/imports when needed
3. **Portability**: Works in all environments (containers, serverless, etc.)
4. **Debugging**: Clear request/response flow
5. **Matches Philosophy**: JSON is simpler than YAML - keep it simple

**Alternative**: If you really want auto-sync:
- Use async `watchfiles` library (~30 lines)
- Disable by default
- Mark as experimental feature

**Best of Both Worlds**: Add file watcher as **optional plugin** in separate PR after core is stable.

---

## Next Steps

1. **Review this analysis** - Confirm approach
2. **Implement Phase 1** - Create `DashboardSchema` model
3. **Implement Phase 2** - Add API endpoints
4. **Implement Phase 3** - Add CLI commands
5. **Test & Document** - Examples and migration guide
6. **Future**: Evaluate watcher need based on user feedback

**Decision Required**:
- ✅ Proceed with API-driven approach (no watcher)?
- ⚠️  Or implement minimal async watcher from start?

Your call!
