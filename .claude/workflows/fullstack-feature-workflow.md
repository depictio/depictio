# Full-Stack Feature Development: Frontend + Backend

A practical guide for developing features that span both FastAPI backend and Dash frontend.

---

## Example Feature: Dashboard Export System

Let's build a feature that allows users to export dashboards as PDF/PNG/JSON.

**Requirements:**
- Backend: API endpoint to generate exports, storage handling
- Frontend: Export button, format selector, progress indicator
- Integration: Async job processing, status polling

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FULL-STACK FEATURE FLOW                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   FRONTEND (Dash)                         BACKEND (FastAPI)                  │
│   ──────────────────                      ─────────────────                  │
│                                                                              │
│   ┌─────────────────┐                     ┌─────────────────┐               │
│   │  Export Button  │────── POST ────────▶│  /api/exports   │               │
│   │  (DMC 2.0+)     │      (create)       │  Create job     │               │
│   └─────────────────┘                     └────────┬────────┘               │
│                                                    │                         │
│   ┌─────────────────┐                     ┌────────▼────────┐               │
│   │ Progress Modal  │◀───── GET ─────────│  /api/exports/  │               │
│   │ (polling)       │      (status)       │  {id}/status    │               │
│   └─────────────────┘                     └────────┬────────┘               │
│                                                    │                         │
│   ┌─────────────────┐                     ┌────────▼────────┐               │
│   │ Download Link   │◀───── GET ─────────│  /api/exports/  │               │
│   │                 │      (file)         │  {id}/download  │               │
│   └─────────────────┘                     └─────────────────┘               │
│                                                                              │
│                              ┌─────────────────┐                             │
│                              │    MongoDB      │                             │
│                              │  Export jobs    │                             │
│                              └─────────────────┘                             │
│                                      │                                       │
│                              ┌───────▼───────┐                               │
│                              │  S3 / MinIO   │                               │
│                              │ Export files  │                               │
│                              └───────────────┘                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Planning

### 1.1 Explore Current Architecture

```bash
claude

# Understand dashboard structure
/arch dash
"Show me how dashboards are currently structured and rendered"

# Check existing export patterns
/arch api
"Are there any existing file export or download endpoints?"

# Database state
/db query dashboards
```

### 1.2 Define the Data Contract

```
YOU: "Let's define the API contract for the export feature.
     I need endpoints for: creating export, checking status, downloading.
     What should the request/response look like?"
```

**Claude suggests:**

```yaml
# API Contract

POST /api/v1/exports
  Request:
    dashboard_id: str
    format: "pdf" | "png" | "json"
    options:
      include_data: bool
      quality: "low" | "medium" | "high"
  Response:
    export_id: str
    status: "pending"
    created_at: datetime

GET /api/v1/exports/{export_id}/status
  Response:
    export_id: str
    status: "pending" | "processing" | "completed" | "failed"
    progress: int (0-100)
    error: str | null

GET /api/v1/exports/{export_id}/download
  Response: File stream
```

### 1.3 Create Task Plan

```
YOU: "Create a task plan for this feature covering both backend and frontend"
```

**Claude creates TodoWrite tasks:**

```
Backend Tasks:
□ Create ExportJob model
□ Create export request/response schemas
□ Implement POST /exports endpoint
□ Implement GET /exports/{id}/status endpoint
□ Implement GET /exports/{id}/download endpoint
□ Add export generation logic (PDF/PNG/JSON)
□ Write API tests

Frontend Tasks:
□ Create ExportButton component
□ Create ExportModal with format selector
□ Create ProgressIndicator component
□ Add polling callback for status
□ Add download trigger callback
□ Ensure theme compatibility
□ Write component tests

Integration:
□ End-to-end testing
□ Error handling across stack
```

---

## Phase 2: Backend Implementation (API Agent)

### 2.1 Create the Model

```bash
/model ExportJob
```

```
YOU: "Create the ExportJob model with status tracking, file location,
     and proper relationships to dashboard and user"
```

**Claude creates** `depictio/models/models/exports.py`:

```python
from datetime import datetime
from enum import Enum
from typing import Optional

from beanie import Document
from pydantic import Field

from depictio.models.models.base import DepictioBaseModel, PyObjectId


class ExportFormat(str, Enum):
    PDF = "pdf"
    PNG = "png"
    JSON = "json"


class ExportStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportOptions(DepictioBaseModel):
    """Export configuration options."""
    include_data: bool = False
    quality: str = "medium"  # low, medium, high


class ExportJob(DepictioBaseModel):
    """Export job tracking model."""
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    dashboard_id: PyObjectId
    user_id: PyObjectId
    format: ExportFormat
    options: ExportOptions = Field(default_factory=ExportOptions)
    status: ExportStatus = ExportStatus.PENDING
    progress: int = Field(default=0, ge=0, le=100)
    file_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class ExportJobBeanie(Document, ExportJob):
    """MongoDB document for export jobs."""

    class Settings:
        name = "export_jobs"
        indexes = [
            "dashboard_id",
            "user_id",
            "status",
        ]
```

**Hook runs automatically:** ✓ Formatting check passed

### 2.2 Create API Endpoints

```bash
/api-endpoint exports CRUD with status and download
```

**Claude creates** `depictio/api/v1/endpoints/exports_endpoints/routes.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import StreamingResponse

from depictio.api.v1.endpoints.user_endpoints.core_functions import get_current_user
from depictio.models.models.users import UserBeanie
from depictio.models.models.exports import (
    ExportJobBeanie,
    ExportFormat,
    ExportStatus,
    ExportOptions,
)

router = APIRouter()


# === Request/Response Schemas ===

class CreateExportRequest(BaseModel):
    dashboard_id: str
    format: ExportFormat
    options: ExportOptions = Field(default_factory=ExportOptions)


class ExportResponse(BaseModel):
    export_id: str
    status: ExportStatus
    progress: int
    created_at: datetime
    error_message: Optional[str] = None


# === Endpoints ===

@router.post("/", response_model=ExportResponse, status_code=status.HTTP_201_CREATED)
async def create_export(
    request: CreateExportRequest,
    background_tasks: BackgroundTasks,
    current_user: UserBeanie = Depends(get_current_user),
) -> ExportResponse:
    """Create a new dashboard export job."""
    # Verify dashboard access
    dashboard = await DashboardBeanie.get(request.dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    if not await user_can_access_dashboard(current_user, dashboard):
        raise HTTPException(status_code=403, detail="Access denied")

    # Create export job
    export_job = ExportJobBeanie(
        dashboard_id=dashboard.id,
        user_id=current_user.id,
        format=request.format,
        options=request.options,
    )
    await export_job.insert()

    # Queue background processing
    background_tasks.add_task(process_export, export_job.id)

    return ExportResponse(
        export_id=str(export_job.id),
        status=export_job.status,
        progress=export_job.progress,
        created_at=export_job.created_at,
    )


@router.get("/{export_id}/status", response_model=ExportResponse)
async def get_export_status(
    export_id: str,
    current_user: UserBeanie = Depends(get_current_user),
) -> ExportResponse:
    """Get export job status."""
    export_job = await ExportJobBeanie.get(export_id)
    if not export_job:
        raise HTTPException(status_code=404, detail="Export not found")

    if export_job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return ExportResponse(
        export_id=str(export_job.id),
        status=export_job.status,
        progress=export_job.progress,
        created_at=export_job.created_at,
        error_message=export_job.error_message,
    )


@router.get("/{export_id}/download")
async def download_export(
    export_id: str,
    current_user: UserBeanie = Depends(get_current_user),
) -> StreamingResponse:
    """Download completed export file."""
    export_job = await ExportJobBeanie.get(export_id)
    if not export_job:
        raise HTTPException(status_code=404, detail="Export not found")

    if export_job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if export_job.status != ExportStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Export not ready")

    # Stream file from S3
    file_stream = await get_file_stream(export_job.file_path)

    return StreamingResponse(
        file_stream,
        media_type=get_media_type(export_job.format),
        headers={
            "Content-Disposition": f"attachment; filename=dashboard.{export_job.format}"
        }
    )
```

### 2.3 Run Backend Tests

```bash
/test api
```

```
YOU: "Write tests for the export endpoints"
```

**Claude creates tests** in `depictio/tests/api/v1/endpoints/exports_endpoints/test_routes.py`

### 2.4 Type Check Backend

```bash
/quality
```

```
✓ ruff format: OK
✓ ruff check: OK
✓ ty check depictio/api/: OK
✓ ty check depictio/models/: OK
```

---

## Phase 3: Frontend Implementation (Dash Agent)

### 3.1 Create Export Button Component

```bash
/dash-component export-button
```

```
YOU: "Create an export button with a dropdown for format selection.
     Use DMC 2.0+ components and ensure theme compatibility."
```

**Claude creates** `depictio/dash/modules/export_component/frontend.py`:

```python
import dash_mantine_components as dmc
from dash import html, dcc
from dash_iconify import DashIconify


def render_export_button(dashboard_id: str) -> html.Div:
    """Render export button with format dropdown."""
    return html.Div(
        id="export-button-container",
        children=[
            dcc.Store(id="export-job-store", data=None),
            dmc.Menu(
                [
                    dmc.MenuTarget(
                        dmc.Button(
                            "Export",
                            leftSection=DashIconify(icon="mdi:download"),
                            variant="light",
                            # Theme-aware styling
                            style={
                                "backgroundColor": "var(--app-surface-color, #f8f9fa)",
                                "color": "var(--app-text-color, #000000)",
                            }
                        )
                    ),
                    dmc.MenuDropdown(
                        [
                            dmc.MenuItem(
                                "Export as PDF",
                                id={"type": "export-format", "format": "pdf"},
                                leftSection=DashIconify(icon="mdi:file-pdf-box"),
                            ),
                            dmc.MenuItem(
                                "Export as PNG",
                                id={"type": "export-format", "format": "png"},
                                leftSection=DashIconify(icon="mdi:file-image"),
                            ),
                            dmc.MenuItem(
                                "Export as JSON",
                                id={"type": "export-format", "format": "json"},
                                leftSection=DashIconify(icon="mdi:code-json"),
                            ),
                        ],
                        # Theme-aware dropdown
                        style={
                            "backgroundColor": "var(--app-surface-color, #ffffff)",
                        }
                    ),
                ],
                position="bottom-end",
            ),
        ],
    )
```

### 3.2 Create Progress Modal

```
YOU: "Create a progress modal that shows export status and allows download when complete"
```

**Claude creates** `depictio/dash/modules/export_component/progress_modal.py`:

```python
import dash_mantine_components as dmc
from dash import html
from dash_iconify import DashIconify


def render_export_modal(export_data: dict | None) -> dmc.Modal:
    """Render export progress modal."""
    if not export_data:
        return dmc.Modal(id="export-modal", opened=False, children=[])

    status = export_data.get("status", "pending")
    progress = export_data.get("progress", 0)
    error = export_data.get("error_message")

    # Status-specific content
    if status == "completed":
        content = dmc.Stack([
            dmc.ThemeIcon(
                DashIconify(icon="mdi:check-circle", width=48),
                color="green",
                size="xl",
                variant="light",
            ),
            dmc.Text("Export completed!", fw=500),
            dmc.Button(
                "Download",
                id="download-export-btn",
                leftSection=DashIconify(icon="mdi:download"),
                color="green",
            ),
        ], align="center", gap="md")
    elif status == "failed":
        content = dmc.Stack([
            dmc.ThemeIcon(
                DashIconify(icon="mdi:alert-circle", width=48),
                color="red",
                size="xl",
                variant="light",
            ),
            dmc.Text("Export failed", fw=500, c="red"),
            dmc.Text(error or "Unknown error", size="sm", c="dimmed"),
        ], align="center", gap="md")
    else:
        content = dmc.Stack([
            dmc.Loader(size="lg"),
            dmc.Text(f"Exporting... {progress}%", fw=500),
            dmc.Progress(value=progress, size="lg", w="100%"),
        ], align="center", gap="md")

    return dmc.Modal(
        id="export-modal",
        title="Dashboard Export",
        opened=True,
        centered=True,
        children=[
            dmc.Paper(
                content,
                p="xl",
                # Theme-aware styling
                style={
                    "backgroundColor": "var(--app-surface-color, #ffffff)",
                    "color": "var(--app-text-color, #000000)",
                }
            )
        ],
        styles={
            "modal": {
                "backgroundColor": "var(--app-bg-color, #ffffff)",
            }
        }
    )
```

### 3.3 Create Callbacks

```
YOU: "Create the callbacks for triggering export, polling status, and downloading"
```

**Claude creates** `depictio/dash/modules/export_component/callbacks/export_callbacks.py`:

```python
from dash import callback, Input, Output, State, ALL, ctx, no_update
from dash.exceptions import PreventUpdate
import httpx

from depictio.dash.api_calls import get_auth_headers, API_BASE_URL


@callback(
    Output("export-job-store", "data"),
    Output("export-modal", "opened"),
    Input({"type": "export-format", "format": ALL}, "n_clicks"),
    State("current-dashboard-id", "data"),
    prevent_initial_call=True,
)
async def trigger_export(n_clicks_list, dashboard_id):
    """Trigger export when format is selected."""
    if not any(n_clicks_list) or not dashboard_id:
        raise PreventUpdate

    # Get which format was clicked
    triggered = ctx.triggered_id
    export_format = triggered["format"]

    # Call API to create export
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{API_BASE_URL}/exports",
            json={
                "dashboard_id": dashboard_id,
                "format": export_format,
                "options": {"include_data": True, "quality": "high"}
            },
            headers=get_auth_headers(),
        )
        response.raise_for_status()
        data = response.json()

    return data, True  # Store data, open modal


@callback(
    Output("export-job-store", "data", allow_duplicate=True),
    Input("export-poll-interval", "n_intervals"),
    State("export-job-store", "data"),
    prevent_initial_call=True,
)
async def poll_export_status(n_intervals, export_data):
    """Poll for export status updates."""
    if not export_data:
        raise PreventUpdate

    status = export_data.get("status")
    if status in ("completed", "failed"):
        raise PreventUpdate  # Stop polling

    export_id = export_data["export_id"]

    # Check status
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_BASE_URL}/exports/{export_id}/status",
            headers=get_auth_headers(),
        )
        response.raise_for_status()
        return response.json()


@callback(
    Output("download-frame", "src"),
    Input("download-export-btn", "n_clicks"),
    State("export-job-store", "data"),
    prevent_initial_call=True,
)
def trigger_download(n_clicks, export_data):
    """Trigger file download when button clicked."""
    if not n_clicks or not export_data:
        raise PreventUpdate

    export_id = export_data["export_id"]
    return f"{API_BASE_URL}/exports/{export_id}/download"
```

### 3.4 Theme Compatibility Check

```
YOU: "Verify this component works in both light and dark themes"
```

**Claude verifies:**
- ✓ All colors use CSS variables
- ✓ No hardcoded hex colors
- ✓ DMC components inherit theme
- ✓ Modal backgrounds theme-aware

### 3.5 Run Frontend Tests

```bash
/test dash
```

---

## Phase 4: Integration & Refinement

### 4.1 Wire Up Frontend to Backend

```
YOU: "Show me how to integrate the export component into the dashboard editor"
```

**Claude shows integration** in `depictio/dash/layouts/dashboard_editor.py`:

```python
from depictio.dash.modules.export_component.frontend import render_export_button
from depictio.dash.modules.export_component.progress_modal import render_export_modal

def render_dashboard_toolbar(dashboard_id: str) -> dmc.Group:
    return dmc.Group([
        # ... other toolbar items ...
        render_export_button(dashboard_id),
        render_export_modal(None),  # Initially hidden
        dcc.Interval(id="export-poll-interval", interval=1000, disabled=True),
        html.Iframe(id="download-frame", style={"display": "none"}),
    ])
```

### 4.2 Full Quality Check

```bash
/quality

# Output:
# Checking depictio/...
# ✓ ruff format: OK
# ✓ ruff check: OK
# ✓ ty check depictio/models/: OK
# ✓ ty check depictio/api/: OK
# ✓ ty check depictio/dash/: OK
# ✓ pre-commit: OK
```

### 4.3 Code Simplification

```
YOU: "The polling callback is getting complex. Can you simplify it?"
```

**Claude refactors:**

```python
# BEFORE: Complex inline logic
@callback(...)
async def poll_export_status(n_intervals, export_data):
    if not export_data:
        raise PreventUpdate
    status = export_data.get("status")
    if status in ("completed", "failed"):
        raise PreventUpdate
    export_id = export_data["export_id"]
    async with httpx.AsyncClient() as client:
        response = await client.get(...)
        response.raise_for_status()
        return response.json()

# AFTER: Cleaner with helper
async def fetch_export_status(export_id: str) -> dict:
    """Fetch current export status from API."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_BASE_URL}/exports/{export_id}/status",
            headers=get_auth_headers(),
        )
        response.raise_for_status()
        return response.json()


def should_continue_polling(export_data: dict | None) -> bool:
    """Check if we should continue polling for updates."""
    if not export_data:
        return False
    return export_data.get("status") not in ("completed", "failed")


@callback(...)
async def poll_export_status(n_intervals, export_data):
    """Poll for export status updates."""
    if not should_continue_polling(export_data):
        raise PreventUpdate
    return await fetch_export_status(export_data["export_id"])
```

### 4.4 Security Review

```
YOU: "Review the export feature for security issues"
```

**Security Agent checks:**

```
┌─ Security Review: Export Feature ─────────────────────────────┐
│                                                                │
│ ✓ Authentication: All endpoints require current_user          │
│ ✓ Authorization: User can only access own exports             │
│ ✓ Input validation: Pydantic models validate all inputs       │
│ ✓ File access: Downloads restricted to user's exports         │
│                                                                │
│ ⚠ Recommendation: Add rate limiting on POST /exports          │
│   to prevent abuse                                             │
│                                                                │
│ ⚠ Recommendation: Add file size limits in ExportOptions       │
│   to prevent resource exhaustion                               │
└────────────────────────────────────────────────────────────────┘
```

### 4.5 Run Full Test Suite

```bash
/test

# Output:
# ===== test session starts =====
# collected 47 items
#
# depictio/tests/api/v1/endpoints/exports_endpoints/test_routes.py ....
# depictio/tests/models/test_exports.py ...
# depictio/tests/dash/modules/export_component/test_callbacks.py ....
#
# ===== 47 passed in 12.34s =====
```

---

## Phase 5: Ship It

### 5.1 Self Code Review

```bash
/review
```

### 5.2 Automated Code Review

```bash
/code-review

# Output:
# ┌─ Compliance Agent ─────────────────────────────────────────┐
# │ ✓ Follows project patterns                                 │
# │ ✓ Consistent naming conventions                            │
# └────────────────────────────────────────────────────────────┘
#
# ┌─ Bug Detection Agent ──────────────────────────────────────┐
# │ ✓ No obvious bugs                                          │
# │ ℹ Consider: Handle network timeout in polling              │
# └────────────────────────────────────────────────────────────┘
#
# ┌─ Security Agent ───────────────────────────────────────────┐
# │ ✓ Auth checks present                                      │
# │ ✓ No injection vulnerabilities                             │
# └────────────────────────────────────────────────────────────┘
#
# ┌─ Performance Agent ────────────────────────────────────────┐
# │ ✓ Async patterns used correctly                            │
# │ ✓ Background task for heavy processing                     │
# └────────────────────────────────────────────────────────────┘
#
# Overall: APPROVED
```

### 5.3 Commit & Push

```bash
/commit

# Claude suggests:
# ┌─────────────────────────────────────────────────────────────┐
# │ feat(exports): add dashboard export system                  │
# │                                                             │
# │ Backend:                                                    │
# │ - Add ExportJob model with status tracking                  │
# │ - Implement export CRUD endpoints                           │
# │ - Add background processing for PDF/PNG/JSON generation     │
# │                                                             │
# │ Frontend:                                                   │
# │ - Add ExportButton component with format dropdown           │
# │ - Add ProgressModal with status polling                     │
# │ - Implement download trigger callback                       │
# │                                                             │
# │ Both:                                                       │
# │ - Full test coverage                                        │
# │ - Theme-compatible UI (light/dark)                          │
# └─────────────────────────────────────────────────────────────┘
# Proceed? [Y/n]
```

### 5.4 Create PR

```bash
/commit-push-pr

# OR manually:
git push -u origin feat/dashboard-export

gh pr create --title "feat: add dashboard export system" --body "$(cat <<'EOF'
## Summary
Add ability to export dashboards as PDF, PNG, or JSON files.

## Changes
### Backend
- New `ExportJob` model for tracking export jobs
- CRUD endpoints at `/api/v1/exports`
- Background processing with status updates

### Frontend
- Export button with format dropdown (DMC 2.0+)
- Progress modal with polling
- Theme-compatible (light/dark mode)

## Test Plan
- [x] Unit tests for API endpoints
- [x] Unit tests for model validation
- [x] Component tests for callbacks
- [ ] Manual testing of full flow
- [ ] Theme compatibility verification

## Screenshots
[Add screenshots of export UI in light/dark mode]
EOF
)"
```

---

## Full-Stack Coordination Cheat Sheet

```
┌─────────────────────────────────────────────────────────────────┐
│            FULL-STACK FEATURE DEVELOPMENT                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. PLAN TOGETHER                                                │
│     /arch                    Understand both sides               │
│     Define API contract      Request/Response shapes             │
│     Create shared types      Keep frontend/backend in sync       │
│                                                                  │
│  2. BUILD BACKEND FIRST                                          │
│     /model                   Create data models                  │
│     /api-endpoint            Create endpoints                    │
│     /test api                Verify backend works                │
│                                                                  │
│  3. BUILD FRONTEND                                               │
│     /dash-component          Create UI components                │
│     Wire up callbacks        Connect to API                      │
│     Theme check              Light + dark mode                   │
│     /test dash               Verify frontend works               │
│                                                                  │
│  4. INTEGRATE & REFINE                                           │
│     End-to-end test          Full flow works                     │
│     /quality                 Code quality                        │
│     Simplify                 Clean up complex code               │
│     Security review          Check both layers                   │
│                                                                  │
│  5. SHIP                                                         │
│     /code-review             Automated review                    │
│     /commit                  AI commit message                   │
│     /commit-push-pr          Full workflow                       │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  AGENT USAGE:                                                    │
│  • API Agent      → Models, endpoints, backend logic             │
│  • Dash Agent     → Components, callbacks, theme                 │
│  • Testing Agent  → Tests for both layers                        │
│  • Security Agent → Auth, validation across stack                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Common Full-Stack Patterns

### Pattern: Status Polling
```
Frontend                    Backend
   │                           │
   ├── POST /resource ────────▶│ Create job, return ID
   │                           │
   ├── GET /resource/{id} ────▶│ Return status
   │◀─────── {status: ...} ────┤
   │                           │
   │  (repeat until done)      │
   │                           │
   ├── GET /resource/{id}/file▶│ Return file
   │◀─────── file stream ──────┤
```

### Pattern: Shared Types
```python
# Backend: depictio/models/models/exports.py
class ExportFormat(str, Enum):
    PDF = "pdf"
    PNG = "png"
    JSON = "json"

# Frontend: Use same values in dropdown
dmc.MenuItem("PDF", id={"type": "export", "format": "pdf"})
```

### Pattern: Error Handling
```python
# Backend: Return structured errors
raise HTTPException(
    status_code=400,
    detail={"code": "EXPORT_FAILED", "message": "Dashboard too large"}
)

# Frontend: Display error in modal
if export_data.get("error_message"):
    show_error_toast(export_data["error_message"])
```
