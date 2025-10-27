# Dashboard Template System Implementation Plan

## Overview
Create a template system for sharing project configurations and dashboards. Templates are stored as exportable YAML/JSON files in the repository, allowing users to instantiate dashboards on new projects with similar data structures.

**Key Design Decisions**:
- Templates stored as YAML files in git repository (`depictio/api/v1/templates/`)
- Dashboard model has `is_template` field to mark template dashboards
- Templates reference data collections by `data_collection_tag` (not ObjectId)
- Templates applied "as-is" (no customization during instantiation)
- Strict schema validation required before instantiation

---

## 1. Database Models (`depictio/models/models/`)

### 1.1 Extend Dashboard Model
**File**: `depictio/models/models/dashboards.py`

Add fields to `DashboardData`:
```python
is_template: bool = False
template_file_path: str | None = None  # Path to template file if created from template
template_source_dashboard_id: PyObjectId | None = None  # Original dashboard if this is a template
```

### 1.2 Create Template Models
**New File**: `depictio/models/models/templates.py`

```python
class TemplateMetadata(BaseModel):
    name: str
    description: str
    author_email: str
    created_at: str
    updated_at: str | None = None
    version: int = 1
    tags: list[str] = []
    screenshot_path: str

class SchemaColumnRequirement(BaseModel):
    name: str
    type: str  # "float64", "int64", "str", etc.
    optional: bool = False

class DataCollectionRequirement(BaseModel):
    dc_tag: str
    dc_type: str  # "table", "jbrowse2", "multiqc"
    required_columns: list[SchemaColumnRequirement]
    description: str

class DashboardTemplate(BaseModel):
    template_metadata: TemplateMetadata
    project_config_template: dict  # Simplified project config
    dashboard_config: dict  # Dashboard structure with tag-based references
    schema_requirements: list[DataCollectionRequirement]
```

---

## 2. Backend API (`depictio/api/v1/`)

### 2.1 Template Endpoints
**New File**: `depictio/api/v1/endpoints/templates_endpoints/routes.py`

**Endpoints**:
- `POST /depictio/api/v1/templates/create` - Create template from dashboard
- `GET /depictio/api/v1/templates/list` - List available templates
- `GET /depictio/api/v1/templates/{template_name}` - Get template details
- `POST /depictio/api/v1/templates/{template_name}/validate` - Validate project against template
- `POST /depictio/api/v1/templates/{template_name}/instantiate` - Create dashboard from template
- `DELETE /depictio/api/v1/templates/{template_name}` - Delete template

### 2.2 Template Utils
**New File**: `depictio/api/v1/endpoints/templates_endpoints/utils.py`

**Functions**:
```python
async def export_dashboard_as_template(
    dashboard_id: str,
    template_name: str,
    description: str,
    tags: list[str],
    user: UserBeanie
) -> dict:
    """Export dashboard and project as template file"""
    # 1. Fetch dashboard document
    # 2. Fetch associated project
    # 3. Extract DC tags from components
    # 4. Query actual DC schemas for validation requirements
    # 5. Replace dc_id/wf_id with dc_tag/wf_name in stored_metadata
    # 6. Generate template structure
    # 7. Write to YAML file
    # 8. Copy screenshot to templates/screenshots/
    # 9. Update dashboard document: is_template=True

async def list_available_templates(project_id: str | None = None) -> list[dict]:
    """List templates, optionally filtered by project compatibility"""
    # 1. Scan depictio/api/v1/templates/ directory
    # 2. Read each template file
    # 3. If project_id provided, validate compatibility
    # 4. Return list with validation status

async def validate_project_for_template(
    project_id: str,
    template: DashboardTemplate
) -> dict:
    """Validate project has compatible data collections and schema"""
    # 1. Fetch project document
    # 2. For each DC requirement in template:
    #    a. Find matching DC by tag
    #    b. Validate DC type
    #    c. Load actual data schema from Delta table
    #    d. Validate required columns exist with correct types
    # 3. Return validation result with errors/warnings/mappings

async def instantiate_template(
    template_name: str,
    project_id: str,
    dashboard_title: str | None,
    user: UserBeanie
) -> dict:
    """Create new dashboard from template"""
    # 1. Read template file
    # 2. Validate project compatibility (strict)
    # 3. Map DC tags → actual DC IDs
    # 4. Map workflow names → actual workflow IDs
    # 5. Create new DashboardData document:
    #    - Replace dc_tag with dc_id in stored_metadata
    #    - Copy stored_layout_data
    #    - Set template_file_path
    #    - Set is_template=False
    # 6. Generate screenshot for new dashboard
    # 7. Return new dashboard ID
```

### 2.3 Template File Operations
**Functions in utils**:
```python
def read_template_file(template_name: str) -> DashboardTemplate:
    """Read template from depictio/api/v1/templates/{name}.yaml"""
    template_path = get_template_directory() / f"{template_name}.yaml"
    with open(template_path, 'r') as f:
        data = yaml.safe_load(f)
    return DashboardTemplate(**data)

def write_template_file(template: DashboardTemplate, template_name: str):
    """Write template to depictio/api/v1/templates/{name}.yaml"""
    template_path = get_template_directory() / f"{template_name}.yaml"
    with open(template_path, 'w') as f:
        yaml.safe_dump(template.model_dump(), f, default_flow_style=False)

def get_template_directory() -> Path:
    """Get templates directory path"""
    return Path(__file__).parent.parent.parent / "templates"

def list_template_files() -> list[str]:
    """List all template files in directory"""
    template_dir = get_template_directory()
    return [f.stem for f in template_dir.glob("*.yaml")]

def get_dc_schema_from_deltatable(dc_id: str) -> dict[str, str]:
    """Load Delta table schema for validation"""
    # Use existing Delta table utilities
    # Return: {"column_name": "polars_dtype_string"}
```

---

## 3. Frontend/Dashboard UI (`depictio/dash/`)

### 3.1 Update Dashboard Creation Modal
**File**: `depictio/dash/layouts/layouts_toolbox.py`

**Changes**:
1. Add tab/section: "Create from Template"
2. Add template gallery with screenshots
3. Add template selection dropdown
4. Show template details (description, requirements)
5. Show validation status (green/red) for current project compatibility

**New Component**:
```python
def template_selection_section(project_id: str) -> dmc.Stack:
    """Template gallery with screenshots and validation"""
    return dmc.Stack([
        dmc.Title("Create from Template", order=3),
        dmc.Text("Select a dashboard template compatible with your project"),
        dmc.Space(h=20),
        # Template cards with screenshots
        dmc.SimpleGrid(
            cols={"base": 1, "sm": 2, "lg": 3},
            spacing="lg",
            children=[
                template_card(template_name, template_data, is_compatible)
                for template_name, template_data, is_compatible in templates
            ]
        ),
    ])

def template_card(name: str, template: dict, validation_result: dict) -> dmc.Card:
    """Individual template card with screenshot and validation status"""
    is_compatible = validation_result["valid"]

    return dmc.Card([
        dmc.CardSection([
            dmc.Image(
                src=template["template_metadata"]["screenshot_path"],
                height=160,
                alt=template["template_metadata"]["name"]
            )
        ]),
        dmc.Stack([
            dmc.Text(template["template_metadata"]["name"], fw=700, size="lg"),
            dmc.Text(template["template_metadata"]["description"], size="sm", c="dimmed"),
            dmc.Group([
                dmc.Badge(
                    "Compatible" if is_compatible else "Incompatible",
                    color="green" if is_compatible else "red",
                    variant="filled"
                ),
                dmc.Badge(f"v{template['template_metadata']['version']}", variant="outline"),
            ]),
            # Show validation errors if incompatible
            *([dmc.Alert(
                title="Validation Errors",
                color="red",
                children=[
                    dmc.List([dmc.ListItem(err) for err in validation_result["errors"]])
                ]
            )] if not is_compatible else []),
            # Action button
            dmc.Button(
                "Use Template",
                id={"type": "use-template-btn", "template_name": name},
                disabled=not is_compatible,
                fullWidth=True,
                color="orange"
            ),
        ], gap="xs"),
    ], withBorder=True, shadow="sm", radius="md", p="lg")
```

### 3.2 Dashboard Management - Export Template
**File**: `depictio/dash/layouts/draggable.py`

**Changes**:
1. Add "Export as Template" button in dashboard header (next to save)
2. Open modal for template metadata input
3. Call API to create template

**New Modal**:
```python
def export_template_modal(opened: bool = False) -> dmc.Modal:
    """Modal for exporting dashboard as template"""
    return dmc.Modal(
        id="export-template-modal",
        opened=opened,
        title=dmc.Group([
            DashIconify(icon="mdi:file-export", width=30, color="orange"),
            dmc.Title("Export Dashboard as Template", order=2)
        ]),
        size="lg",
        children=[
            dmc.Stack([
                dmc.TextInput(
                    id="template-name-input",
                    label="Template Name",
                    placeholder="my_analysis_template",
                    description="Unique identifier for the template (alphanumeric, underscores, hyphens)",
                    required=True,
                ),
                dmc.Textarea(
                    id="template-description-input",
                    label="Description",
                    placeholder="Describe what this template does and what data it expects...",
                    required=True,
                    minRows=3,
                ),
                dmc.MultiSelect(
                    id="template-tags-input",
                    label="Tags",
                    placeholder="Add tags (e.g., genomics, qc, visualization)",
                    data=[],
                    searchable=True,
                    creatable=True,
                ),
                dmc.Alert(
                    title="Template Requirements",
                    color="blue",
                    children=[
                        dmc.Text("This will extract schema requirements from your current data collections."),
                        dmc.Text("Screenshot will be automatically captured from the current dashboard view.")
                    ]
                ),
                dmc.Group([
                    dmc.Button("Cancel", id="export-template-cancel-btn", variant="outline"),
                    dmc.Button(
                        "Create Template",
                        id="export-template-create-btn",
                        color="orange",
                        leftSection=DashIconify(icon="mdi:check")
                    ),
                ], justify="flex-end"),
            ], gap="md")
        ]
    )
```

**New Button in Dashboard Header**:
```python
# In draggable.py header section
dmc.Button(
    "Export as Template",
    id="open-export-template-modal-btn",
    variant="subtle",
    color="orange",
    leftSection=DashIconify(icon="mdi:file-export", width=20),
)
```

### 3.3 Template Callbacks
**New File**: `depictio/dash/layouts/callbacks/templates_callbacks.py`

**Callbacks**:
```python
@callback(
    Output("template-list-store", "data"),
    Input("dashboard-projects", "value"),  # Selected project
    State("token-store", "data"),
)
def load_templates_for_project(project_id, token):
    """Load and validate templates when project is selected"""
    if not project_id:
        return []

    response = requests.get(
        f"{API_BASE_URL}/depictio/api/v1/templates/list",
        params={"project_id": project_id},
        headers={"Authorization": f"Bearer {token}"}
    )
    return response.json()


@callback(
    Output("create-dashboard-from-template-store", "data"),
    Input({"type": "use-template-btn", "template_name": ALL}, "n_clicks"),
    State("dashboard-projects", "value"),
    State("token-store", "data"),
    prevent_initial_call=True,
)
def instantiate_template(n_clicks_list, project_id, token):
    """Instantiate template when user clicks 'Use Template' button"""
    if not any(n_clicks_list):
        raise PreventUpdate

    # Get triggered template name
    ctx = callback_context
    template_name = ctx.triggered_id["template_name"]

    response = requests.post(
        f"{API_BASE_URL}/depictio/api/v1/templates/{template_name}/instantiate",
        json={"project_id": project_id, "dashboard_title": None},
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code == 200:
        return response.json()
    else:
        # Show error notification
        return {"error": response.json().get("detail")}


@callback(
    Output("export-template-modal", "opened"),
    Output("export-template-status-store", "data"),
    Input("open-export-template-modal-btn", "n_clicks"),
    Input("export-template-create-btn", "n_clicks"),
    Input("export-template-cancel-btn", "n_clicks"),
    State("template-name-input", "value"),
    State("template-description-input", "value"),
    State("template-tags-input", "value"),
    State("dashboard-id-store", "data"),
    State("token-store", "data"),
    prevent_initial_call=True,
)
def handle_export_template_modal(
    open_clicks, create_clicks, cancel_clicks,
    template_name, description, tags,
    dashboard_id, token
):
    """Handle export template modal interactions"""
    ctx = callback_context
    triggered_id = ctx.triggered_id

    if triggered_id == "open-export-template-modal-btn":
        return True, no_update  # Open modal

    if triggered_id == "export-template-cancel-btn":
        return False, no_update  # Close modal

    if triggered_id == "export-template-create-btn":
        # Validate inputs
        if not template_name or not description:
            return no_update, {"error": "Name and description are required"}

        # Call API to create template
        response = requests.post(
            f"{API_BASE_URL}/depictio/api/v1/templates/create",
            json={
                "dashboard_id": dashboard_id,
                "template_name": template_name,
                "description": description,
                "tags": tags or []
            },
            headers={"Authorization": f"Bearer {token}"}
        )

        if response.status_code == 200:
            return False, {"success": True, "template_name": template_name}
        else:
            return no_update, {"error": response.json().get("detail")}

    raise PreventUpdate
```

---

## 4. CLI Commands (`depictio/cli/`)

### 4.1 New Template Command Group
**New File**: `depictio/cli/commands/template.py`

```python
import typer
from rich.console import Console
from rich.table import Table
import requests
from pathlib import Path

app = typer.Typer(help="Manage dashboard templates")
console = Console()


@app.command()
def create(
    project_config_path: str = typer.Option(..., help="Path to project YAML config"),
    dashboard_id: str = typer.Option(..., help="Dashboard ID to export as template"),
    template_name: str = typer.Option(..., help="Template name (unique identifier)"),
    description: str = typer.Option(..., help="Template description"),
    tags: list[str] = typer.Option([], help="Tags for categorization"),
    cli_config_path: str = typer.Option("~/.depictio/CLI.yaml", help="Path to CLI config"),
):
    """Create template from existing project and dashboard"""
    console.print(f"[bold cyan]Creating template '{template_name}' from dashboard {dashboard_id}[/bold cyan]")

    # Load CLI config for API access
    cli_config = load_cli_config(cli_config_path)

    # Call API
    response = requests.post(
        f"{cli_config.api_base_url}/depictio/api/v1/templates/create",
        json={
            "dashboard_id": dashboard_id,
            "template_name": template_name,
            "description": description,
            "tags": tags
        },
        headers={"Authorization": f"Bearer {cli_config.token}"}
    )

    if response.status_code == 200:
        result = response.json()
        console.print(f"[bold green]✓[/bold green] Template created successfully")
        console.print(f"  File: {result['template_file_path']}")
        console.print(f"  Screenshot: {result['screenshot_path']}")
    else:
        console.print(f"[bold red]✗[/bold red] Failed to create template: {response.text}", style="red")
        raise typer.Exit(1)


@app.command()
def list_templates(
    project_config_path: str = typer.Option(None, help="Filter by project compatibility"),
    cli_config_path: str = typer.Option("~/.depictio/CLI.yaml", help="Path to CLI config"),
):
    """List available templates, optionally filtered by project compatibility"""
    cli_config = load_cli_config(cli_config_path)

    # Determine project_id if config provided
    project_id = None
    if project_config_path:
        project_id = get_project_id_from_config(project_config_path, cli_config)

    # Call API
    params = {"project_id": project_id} if project_id else {}
    response = requests.get(
        f"{cli_config.api_base_url}/depictio/api/v1/templates/list",
        params=params,
        headers={"Authorization": f"Bearer {cli_config.token}"}
    )

    if response.status_code == 200:
        templates = response.json()

        # Create table
        table = Table(title="Available Dashboard Templates")
        table.add_column("Name", style="cyan")
        table.add_column("Description", style="white")
        table.add_column("Version", style="yellow")
        table.add_column("Tags", style="magenta")
        if project_id:
            table.add_column("Compatible", style="green")

        for t in templates:
            row = [
                t["template_metadata"]["name"],
                t["template_metadata"]["description"][:50] + "...",
                f"v{t['template_metadata']['version']}",
                ", ".join(t["template_metadata"]["tags"][:3]),
            ]
            if project_id:
                row.append("✓" if t.get("validation", {}).get("valid") else "✗")
            table.add_row(*row)

        console.print(table)
    else:
        console.print(f"[bold red]Failed to list templates: {response.text}[/bold red]")
        raise typer.Exit(1)


@app.command()
def apply(
    template_name: str = typer.Option(..., help="Template name to apply"),
    project_config_path: str = typer.Option(..., help="Path to project YAML config"),
    dashboard_title: str = typer.Option(None, help="Override dashboard title"),
    cli_config_path: str = typer.Option("~/.depictio/CLI.yaml", help="Path to CLI config"),
):
    """Apply template to create new dashboard for project"""
    console.print(f"[bold cyan]Applying template '{template_name}' to project[/bold cyan]")

    cli_config = load_cli_config(cli_config_path)
    project_id = get_project_id_from_config(project_config_path, cli_config)

    # Call API
    response = requests.post(
        f"{cli_config.api_base_url}/depictio/api/v1/templates/{template_name}/instantiate",
        json={
            "project_id": project_id,
            "dashboard_title": dashboard_title
        },
        headers={"Authorization": f"Bearer {cli_config.token}"}
    )

    if response.status_code == 200:
        result = response.json()
        console.print(f"[bold green]✓[/bold green] Dashboard created from template")
        console.print(f"  Dashboard ID: {result['dashboard_id']}")
        console.print(f"  Title: {result['title']}")
        console.print(f"  URL: {cli_config.api_base_url}/dashboards/{result['dashboard_id']}")
    else:
        console.print(f"[bold red]✗[/bold red] Failed to apply template: {response.text}", style="red")
        raise typer.Exit(1)


@app.command()
def validate(
    template_name: str = typer.Option(..., help="Template name to validate against"),
    project_config_path: str = typer.Option(..., help="Path to project YAML config"),
    cli_config_path: str = typer.Option("~/.depictio/CLI.yaml", help="Path to CLI config"),
):
    """Validate project against template requirements"""
    console.print(f"[bold cyan]Validating project against template '{template_name}'[/bold cyan]")

    cli_config = load_cli_config(cli_config_path)
    project_id = get_project_id_from_config(project_config_path, cli_config)

    # Call API
    response = requests.post(
        f"{cli_config.api_base_url}/depictio/api/v1/templates/{template_name}/validate",
        json={"project_id": project_id},
        headers={"Authorization": f"Bearer {cli_config.token}"}
    )

    if response.status_code == 200:
        result = response.json()

        if result["valid"]:
            console.print("[bold green]✓ Project is compatible with template[/bold green]")
        else:
            console.print("[bold red]✗ Project is NOT compatible with template[/bold red]")

        # Show errors
        if result.get("errors"):
            console.print("\n[bold red]Errors:[/bold red]")
            for err in result["errors"]:
                console.print(f"  • {err}", style="red")

        # Show warnings
        if result.get("warnings"):
            console.print("\n[bold yellow]Warnings:[/bold yellow]")
            for warn in result["warnings"]:
                console.print(f"  • {warn}", style="yellow")

        # Show mappings if valid
        if result["valid"] and result.get("mappings"):
            console.print("\n[bold green]Data Collection Mappings:[/bold green]")
            for dc_tag, mapping in result["mappings"].items():
                console.print(f"  {dc_tag} → DC ID: {mapping['dc_id']}, WF ID: {mapping['wf_id']}")
    else:
        console.print(f"[bold red]Validation failed: {response.text}[/bold red]")
        raise typer.Exit(1)
```

### 4.2 Update Run Command
**File**: `depictio/cli/commands/run.py`

**Add optional parameter**:
```python
@app.command()
def run(
    # ... existing parameters ...
    template: str = typer.Option(None, help="Apply dashboard template after project creation"),
):
    """Main orchestration command"""
    # ... existing run logic ...

    # After successful project creation and data processing
    if template:
        console.print(f"\n[bold cyan]Applying dashboard template '{template}'...[/bold cyan]")

        response = requests.post(
            f"{cli_config.api_base_url}/depictio/api/v1/templates/{template}/instantiate",
            json={"project_id": project_id, "dashboard_title": None},
            headers={"Authorization": f"Bearer {token}"}
        )

        if response.status_code == 200:
            result = response.json()
            console.print(f"[bold green]✓[/bold green] Dashboard created from template: {result['dashboard_id']}")
        else:
            console.print(f"[bold yellow]⚠[/bold yellow] Template application failed: {response.text}", style="yellow")
```

### 4.3 Register Template Commands
**File**: `depictio/cli/depictio_cli.py`

```python
from depictio.cli.commands import template

# Register template command group
app.add_typer(template.app, name="template")
```

---

## 5. Template File Structure

### 5.1 Directory Structure
```
depictio/api/v1/templates/
├── iris_analysis_dashboard.yaml
├── ampliseq_qc_dashboard.yaml
├── multiqc_report_dashboard.yaml
└── screenshots/
    ├── iris_analysis_dashboard.png
    ├── ampliseq_qc_dashboard.png
    └── multiqc_report_dashboard.png
```

### 5.2 Template File Format
**Example**: `iris_analysis_dashboard.yaml`

```yaml
template_metadata:
  name: "Iris Dataset Analysis Dashboard"
  description: "Interactive visualization dashboard for iris dataset with scatter plots and summary cards"
  author_email: "admin@depictio.com"
  created_at: "2025-10-17 10:00:00"
  version: 1
  tags: ["demo", "visualization", "basic-analytics"]
  screenshot_path: "depictio/api/v1/templates/screenshots/iris_analysis_dashboard.png"

project_config_template:
  # Minimal project structure for reference
  workflows:
    - name: "iris_workflow"
      data_collections:
        - data_collection_tag: "iris_table"

dashboard_config:
  title: "Iris Analysis Dashboard"
  subtitle: "Interactive analysis of iris dataset characteristics"
  icon: "mdi:flower"
  icon_color: "purple"
  workflow_system: "python"

  stored_metadata:
    - index: "fig-scatter-sepal"
      component_type: "figure"
      dc_tag: "iris_table"  # Reference by tag instead of ID
      visu_type: "scatter"
      mode: "ui"
      dict_kwargs:
        x: "sepal.length"
        y: "sepal.width"
        color: "variety"
        title: "Sepal Dimensions by Variety"
        labels:
          "sepal.length": "Sepal Length (cm)"
          "sepal.width": "Sepal Width (cm)"

    - index: "card-mean-sepal-length"
      component_type: "card"
      dc_tag: "iris_table"
      column_name: "sepal.length"
      aggregation: "mean"

    - index: "table-full-data"
      component_type: "table"
      dc_tag: "iris_table"
      columns: ["sepal.length", "sepal.width", "petal.length", "petal.width", "variety"]

  stored_layout_data:
    - i: "box-fig-scatter-sepal"
      x: 0
      y: 0
      w: 8
      h: 6
    - i: "box-card-mean-sepal-length"
      x: 8
      y: 0
      w: 4
      h: 3
    - i: "box-table-full-data"
      x: 0
      y: 6
      w: 12
      h: 6

schema_requirements:
  - dc_tag: "iris_table"
    dc_type: "table"
    description: "Main iris dataset table with sepal/petal measurements and variety classification"
    required_columns:
      - name: "sepal.length"
        type: "float64"
        optional: false
      - name: "sepal.width"
        type: "float64"
        optional: false
      - name: "petal.length"
        type: "float64"
        optional: false
      - name: "petal.width"
        type: "float64"
        optional: false
      - name: "variety"
        type: "str"
        optional: false
```

---

## 6. Implementation Workflow

### 6.1 Template Creation Flow
1. User clicks "Export as Template" button on dashboard
2. Modal opens requesting: template name, description, tags
3. Backend validates: project config exists, dashboard is complete, screenshot exists
4. Backend extracts:
   - Project structure (workflows, DC tags)
   - Dashboard components with DC tag references (not IDs)
   - Required columns from actual data collections
   - Column types for validation
5. Generate template file and save to `depictio/api/v1/templates/`
6. Generate/copy screenshot to `screenshots/` subdirectory
7. Update dashboard document: `is_template=True, template_file_path=...`
8. Return success with template file path

### 6.2 Template Application Flow
1. User creating new dashboard, selects "Create from Template" tab
2. Frontend loads templates via API: `GET /templates/list?project_id={id}`
3. API reads all template files, validates each against project:
   - Check if project has DC with matching tag
   - Check if DC type matches
   - Check if DC has required columns with correct types
4. Frontend displays compatible templates (green badge) and incompatible (red badge, disabled)
5. User selects template, clicks "Use Template"
6. API instantiates template:
   - Read template file
   - Find project's workflows and DCs matching template tags
   - Map DC tags → actual DC IDs
   - Map workflow tags → actual workflow IDs
   - Create new `DashboardData` document with:
     - `stored_metadata`: components with mapped IDs
     - `stored_layout_data`: layout from template
     - `template_file_path`: reference to source template
     - `is_template=False` (this is an instance)
7. Generate screenshot for new dashboard
8. Return new dashboard ID
9. Frontend redirects to new dashboard in edit mode

### 6.3 Validation Algorithm
```python
def validate_project_for_template(project: Project, template: DashboardTemplate) -> dict:
    """Returns validation result with details"""
    results = {"valid": True, "errors": [], "warnings": [], "mappings": {}}

    for dc_req in template.schema_requirements:
        # Find matching DC in project by tag
        matching_dc = find_dc_by_tag(project, dc_req.dc_tag)

        if not matching_dc:
            results["valid"] = False
            results["errors"].append(f"Missing data collection: {dc_req.dc_tag}")
            continue

        # Validate DC type
        if matching_dc.config.type != dc_req.dc_type:
            results["valid"] = False
            results["errors"].append(
                f"DC {dc_req.dc_tag} type mismatch: expected {dc_req.dc_type}, got {matching_dc.config.type}"
            )
            continue

        # Load actual data schema from Delta table
        actual_schema = get_dc_schema_from_deltatable(matching_dc.id)

        # Validate required columns
        for col_req in dc_req.required_columns:
            if col_req.name not in actual_schema:
                if not col_req.optional:
                    results["valid"] = False
                    results["errors"].append(
                        f"Missing required column: {dc_req.dc_tag}.{col_req.name}"
                    )
                else:
                    results["warnings"].append(
                        f"Missing optional column: {dc_req.dc_tag}.{col_req.name}"
                    )
                continue

            # Validate column type compatibility
            actual_type = actual_schema[col_req.name]
            if not types_compatible(actual_type, col_req.type):
                results["valid"] = False
                results["errors"].append(
                    f"Column type mismatch: {dc_req.dc_tag}.{col_req.name} expected {col_req.type}, got {actual_type}"
                )

        # Store mapping for later use
        results["mappings"][dc_req.dc_tag] = {
            "dc_id": str(matching_dc.id),
            "wf_id": str(find_workflow_for_dc(project, matching_dc.id).id)
        }

    return results

def types_compatible(actual: str, expected: str) -> bool:
    """Check if Polars data types are compatible"""
    # Exact match
    if actual == expected:
        return True

    # Numeric type compatibility
    numeric_types = ["int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64", "float32", "float64"]
    if actual in numeric_types and expected in numeric_types:
        return True

    # String type compatibility
    string_types = ["str", "utf8", "categorical"]
    if actual in string_types and expected in string_types:
        return True

    return False
```

---

## 7. Additional Considerations

### 7.1 Template Versioning
- Include `version` field in template metadata
- When template is updated, increment version
- Dashboard instances track which version they were created from
- Future: migration tools for upgrading dashboard instances

### 7.2 Multi-DC Templates
- Templates can reference multiple data collections
- Example: AmplliSeq template with `taxonomy_table`, `metadata_table`, `multiqc_data`
- Validation ensures ALL required DCs exist in target project

### 7.3 Joined Data Collections
- If template uses joined DCs, store join configuration in template
- Validation checks if target project can recreate the same join
- Alternative: template specifies pre-joined DC requirement

### 7.4 Interactive Components
- Interactive components (sliders, dropdowns) in templates maintain their configuration
- Default values from template applied to new dashboard
- Users can modify after instantiation via normal editing

### 7.5 Git Version Control
- Templates are in `depictio/api/v1/templates/` (tracked by git)
- Screenshots in `templates/screenshots/` (tracked by git or git-lfs)
- Easy to share templates across teams via git
- Template changes tracked in version control

### 7.6 Permission Model
- Only users with project edit permissions can create templates from their dashboards
- Templates are public (all users can see and use)
- Future: private templates per user/organization

### 7.7 Documentation
- Each template should include comprehensive description
- Document expected data structure in template metadata
- Provide example project config snippet in template

### 7.8 Screenshot Generation
- Reuse existing screenshot system (`screenshot_dash_fixed()`)
- Use component-based composite screenshots (`.react-grid-item` targeting)
- Store screenshots in `templates/screenshots/` directory
- Screenshots serve as preview in template gallery

### 7.9 Component Index Handling
- When instantiating template, preserve component indices from template
- Ensures layout references (`stored_layout_data`) match components (`stored_metadata`)
- Generate new UUIDs only if conflicts exist with existing dashboard components

### 7.10 Workflow Name Resolution
- Templates reference workflows by name (not ID)
- During instantiation, find workflow by name in target project
- If multiple workflows have same name, use first match (or error)
- Consider adding workflow disambiguation in future versions

---

## 8. Testing Strategy

### 8.1 Unit Tests
**New File**: `depictio/tests/test_templates.py`

```python
def test_read_template_file():
    """Test reading template from YAML file"""

def test_write_template_file():
    """Test writing template to YAML file"""

def test_validate_project_compatible():
    """Test validation with compatible project"""

def test_validate_project_incompatible():
    """Test validation with incompatible project (missing columns)"""

def test_dc_tag_to_id_mapping():
    """Test mapping DC tags to actual IDs"""

def test_instantiate_template():
    """Test creating dashboard from template"""

def test_types_compatible():
    """Test type compatibility checker"""
```

### 8.2 Integration Tests
```python
def test_create_template_from_iris_dashboard():
    """Create template from iris demo dashboard"""

def test_apply_template_to_new_project():
    """Apply iris template to a new compatible project"""

def test_template_validation_endpoint():
    """Test template validation API endpoint"""

def test_cli_template_commands():
    """Test CLI template create/list/apply/validate commands"""
```

### 8.3 E2E Tests (Cypress)
```javascript
describe('Template System', () => {
  it('should export dashboard as template', () => {
    // Navigate to iris dashboard
    // Click "Export as Template"
    // Fill in template metadata
    // Verify template file created
  });

  it('should create dashboard from template', () => {
    // Navigate to create dashboard page
    // Select "Create from Template" tab
    // Verify template gallery displays
    // Click "Use Template" on compatible template
    // Verify dashboard created and redirects
  });

  it('should show validation errors for incompatible template', () => {
    // Create project with incompatible schema
    // Open template gallery
    // Verify incompatible templates show red badge
    // Verify error messages displayed
  });
});
```

---

## 9. Implementation Order

### Phase 1: Models & Backend (Week 1)
1. Create template models (`depictio/models/models/templates.py`)
2. Extend dashboard model with template fields
3. Create template utils (file operations, validation)
4. Create template endpoints (create, list, validate, instantiate)
5. Unit tests for validation and mapping logic

### Phase 2: CLI (Week 1)
1. Create template command group
2. Implement create, list, apply, validate commands
3. Update run command with --template parameter
4. Integration tests for CLI commands

### Phase 3: Frontend UI (Week 2)
1. Create export template modal
2. Add "Export as Template" button to dashboard
3. Update dashboard creation modal with template tab
4. Build template gallery component
5. Implement template callbacks (load, validate, instantiate, export)

### Phase 4: Testing & Polish (Week 2)
1. Complete unit tests for all new functions
2. Integration tests for workflows
3. E2E tests for UI
4. Create initial templates (iris, ampliseq examples)
5. Performance optimization

### Phase 5: Documentation (Week 3)
1. Update depictio-docs:
   - User guide for creating templates
   - User guide for applying templates
   - Template file format reference
   - CLI commands documentation
2. Update Obsidian notes:
   - Technical architecture of template system
   - Schema validation implementation details
   - Performance considerations
   - Future enhancement ideas

---

## 10. Files to Create/Modify

### New Files (10 files)
1. `depictio/models/models/templates.py` - Template data models
2. `depictio/api/v1/endpoints/templates_endpoints/__init__.py` - Package init
3. `depictio/api/v1/endpoints/templates_endpoints/routes.py` - API endpoints
4. `depictio/api/v1/endpoints/templates_endpoints/utils.py` - Template utilities
5. `depictio/cli/commands/template.py` - CLI commands
6. `depictio/dash/layouts/callbacks/templates_callbacks.py` - Dash callbacks
7. `depictio/tests/test_templates.py` - Unit tests
8. `depictio/api/v1/templates/iris_analysis_dashboard.yaml` - Example template
9. `depictio/api/v1/templates/ampliseq_qc_dashboard.yaml` - Example template
10. `depictio/api/v1/templates/screenshots/.gitkeep` - Screenshot directory

### Modified Files (6 files)
1. `depictio/models/models/dashboards.py` - Add template fields to DashboardData
2. `depictio/dash/layouts/layouts_toolbox.py` - Add template selection tab
3. `depictio/dash/layouts/draggable.py` - Add export template button & modal
4. `depictio/cli/depictio_cli.py` - Register template command group
5. `depictio/cli/commands/run.py` - Add --template parameter
6. `depictio/api/main.py` - Register template router

### Template Directory Structure (Git-tracked)
```
depictio/api/v1/templates/
├── README.md (documentation for template format)
├── iris_analysis_dashboard.yaml
├── ampliseq_qc_dashboard.yaml
└── screenshots/
    ├── iris_analysis_dashboard.png
    └── ampliseq_qc_dashboard.png
```

---

## 11. Success Criteria

### Functional Requirements
- [ ] Users can export existing dashboards as templates
- [ ] Templates stored as YAML files in git repository
- [ ] Templates include schema validation requirements
- [ ] Templates reference data collections by tag (not ID)
- [ ] API validates projects against template requirements
- [ ] Users can create dashboards from templates via UI
- [ ] Users can create dashboards from templates via CLI
- [ ] Template gallery shows screenshots and validation status
- [ ] Only compatible templates can be instantiated

### Technical Requirements
- [ ] All new code passes type checking (ty check)
- [ ] All new code passes linting (ruff check)
- [ ] All new code formatted (ruff format)
- [ ] Unit test coverage >80% for new code
- [ ] Integration tests for complete workflows
- [ ] E2E tests for UI interactions
- [ ] Performance: template validation <1 second
- [ ] Performance: template instantiation <5 seconds

### Documentation Requirements
- [ ] User guide for creating templates
- [ ] User guide for applying templates
- [ ] Template file format reference
- [ ] CLI commands documented
- [ ] API endpoints documented (OpenAPI)
- [ ] Obsidian notes updated with technical details

---

## 12. Future Enhancements

### Phase 2 Features (Future)
1. **Template Marketplace**: Public registry of community templates
2. **Template Versioning**: Upgrade dashboard instances when template updates
3. **Private Templates**: User/organization-specific templates
4. **Template Customization**: Partial instantiation, parameter overrides
5. **Template Dependencies**: Templates that depend on other templates
6. **Template Testing**: Automated tests for template compatibility
7. **Template Import/Export**: Share templates across Depictio instances
8. **Template Analytics**: Track template usage and popularity
9. **Template Recommendations**: Suggest templates based on project schema
10. **Visual Template Builder**: GUI for creating templates without code

### Advanced Features (Future)
1. **Multi-Project Templates**: Templates that span multiple projects
2. **Workflow Templates**: Templates for entire analysis workflows
3. **Component Library**: Reusable component templates
4. **Template Inheritance**: Templates that extend other templates
5. **Schema Evolution**: Handle schema changes in template instances
6. **Template Diff**: Visual diff between template versions
7. **Template Preview**: Live preview before instantiation
8. **Template Rollback**: Revert dashboard to previous template version

---

This comprehensive plan provides a solid foundation for implementing the dashboard template system with clear phases, technical details, and success criteria.
