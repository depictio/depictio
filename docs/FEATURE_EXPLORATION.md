# Depictio Feature Exploration: Additional Modes & Interaction Patterns

This document explores potential new features, interaction modes, and architectural improvements for depictio, inspired by analyzing the current architecture and industry best practices.

---

## 1. Declarative Dashboard Configuration (YAML/JSON)

### Current State
Depictio already has:
- Project/Workflow YAML configuration (`initial_project.yaml`)
- Dashboard state stored in JSON (`stored_metadata`, `stored_layout_data`)
- Pydantic models for all components

### Proposed: Full Declarative Dashboard Specification

Create a human-readable, version-controllable dashboard format:

```yaml
# dashboard.yaml
version: "1.0"
title: "Iris Analysis Dashboard"
subtitle: "Exploring the Iris dataset"
icon: "mdi:flower"
theme: "auto"  # auto, light, dark

# Reference to data sources (by tag or ID)
data_sources:
  - workflow: "iris_workflow"
    collection: "iris_table"
    alias: "iris"  # Use this alias in components

# Global filters (optional)
filters:
  - column: "variety"
    type: "multiselect"
    default: ["Setosa", "Versicolor", "Virginica"]

# Layout uses a 48-column grid (current) or named regions
layout:
  type: "grid"  # or "regions" for semantic layout
  columns: 48
  row_height: 50

# Components with positioning
components:
  - id: "scatter-main"
    type: "figure"
    data: "iris"
    position: { x: 0, y: 0, w: 24, h: 16 }
    spec:
      visualization: "scatter"
      x: "sepal.length"
      y: "sepal.width"
      color: "variety"
      size: "petal.length"
      template: "mantine_light"
      marginal_x: "histogram"
      marginal_y: "rug"

  - id: "variety-filter"
    type: "interactive"
    data: "iris"
    position: { x: 24, y: 0, w: 10, h: 6 }
    spec:
      interactive_type: "MultiSelect"
      column: "variety"
      icon: "bx:slider-alt"
      color: "#858585"

  - id: "sepal-length-card"
    type: "card"
    data: "iris"
    position: { x: 34, y: 0, w: 6, h: 6 }
    spec:
      column: "sepal.length"
      aggregation: "average"
      icon: "mdi:leaf"
      icon_color: "#8BC34A"

  - id: "data-table"
    type: "table"
    data: "iris"
    position: { x: 0, y: 16, w: 48, h: 20 }
    spec:
      columns: ["sepal.length", "sepal.width", "petal.length", "petal.width", "variety"]
      pagination: true
      export_csv: true

# Inter-component relationships
interactions:
  - source: "variety-filter"
    targets: ["scatter-main", "data-table", "sepal-length-card"]
    action: "filter"

# Tabs (for multi-page dashboards)
tabs:
  - id: "overview"
    title: "Overview"
    is_main: true
    components: ["scatter-main", "variety-filter", "sepal-length-card"]

  - id: "details"
    title: "Detailed Analysis"
    components: ["data-table"]
```

### Benefits
- **Version Control**: Track dashboard changes in Git
- **Code Review**: Review dashboard changes like code
- **Reusability**: Share dashboard templates across projects
- **CI/CD Integration**: Validate dashboards in pipelines
- **LLM-Friendly**: Easier for AI to generate/modify

### Implementation Strategy
1. Create `DashboardSpec` Pydantic model matching YAML schema
2. Add `/api/v1/dashboards/import` and `/api/v1/dashboards/export` endpoints
3. CLI commands: `depictio dashboard export <id> -o dashboard.yaml`
4. GUI "Export as YAML" button in dashboard settings

---

## 2. MCP Server Integration (Model Context Protocol)

### Why MCP?
MCP enables AI assistants (Claude, Cursor, etc.) to interact with depictio programmatically. This is particularly powerful given depictio's focus on data visualization.

### Proposed MCP Tools

```python
# depictio_mcp/server.py
from mcp.server import Server
from mcp.types import Tool

server = Server("depictio")

@server.tool()
async def list_dashboards(project_id: str | None = None) -> list[dict]:
    """List all dashboards, optionally filtered by project."""
    ...

@server.tool()
async def get_dashboard_schema(dashboard_id: str) -> dict:
    """Get the YAML/JSON schema of a dashboard."""
    ...

@server.tool()
async def create_dashboard(spec: dict) -> dict:
    """Create a new dashboard from a declarative specification."""
    ...

@server.tool()
async def add_component(
    dashboard_id: str,
    component_type: str,  # figure, card, table, interactive
    data_collection: str,
    position: dict,
    spec: dict
) -> dict:
    """Add a component to an existing dashboard."""
    ...

@server.tool()
async def update_component(
    dashboard_id: str,
    component_id: str,
    spec: dict
) -> dict:
    """Update a component's specification."""
    ...

@server.tool()
async def execute_visualization_code(
    data_collection_id: str,
    code: str
) -> dict:
    """Execute Plotly code in sandbox and return figure JSON."""
    ...

@server.tool()
async def list_data_collections(workflow_id: str | None = None) -> list[dict]:
    """List available data collections with schema information."""
    ...

@server.tool()
async def get_data_sample(
    data_collection_id: str,
    limit: int = 100
) -> dict:
    """Get a sample of data from a collection."""
    ...

@server.tool()
async def get_column_stats(
    data_collection_id: str,
    column: str
) -> dict:
    """Get statistics for a specific column."""
    ...
```

### MCP Resources

```python
@server.resource("dashboard://{dashboard_id}")
async def get_dashboard_resource(dashboard_id: str) -> str:
    """Expose dashboard as a resource for context."""
    ...

@server.resource("data://{collection_id}/schema")
async def get_data_schema(collection_id: str) -> str:
    """Expose data collection schema as resource."""
    ...
```

### Usage Example (Claude Desktop)

```
User: "Create a dashboard for the iris dataset with a scatter plot
       showing sepal dimensions colored by variety"

Claude: [Uses depictio MCP tools]
1. list_data_collections() -> finds iris_table
2. get_data_sample("iris_table") -> understands schema
3. create_dashboard({
     title: "Iris Sepal Analysis",
     components: [...]
   })
4. Returns: "Created dashboard: http://localhost:8050/dashboard/abc123"
```

### Implementation Structure

```
depictio/
├── mcp/
│   ├── __init__.py
│   ├── server.py          # MCP server implementation
│   ├── tools/
│   │   ├── dashboards.py  # Dashboard management tools
│   │   ├── data.py        # Data access tools
│   │   └── visualization.py # Viz generation tools
│   └── resources/
│       └── schemas.py     # Resource providers
```

---

## 3. Dual-Mode Interface (Vizro-Style)

### Concept
Allow users to switch between:
1. **GUI Mode**: Current drag-and-drop visual builder
2. **Code Mode**: Python/YAML specification with live preview
3. **Hybrid Mode**: Side-by-side editing

### Python SDK for Programmatic Dashboard Creation

```python
# depictio_sdk/dashboard.py
import depictio as dp

# Create dashboard programmatically
dashboard = dp.Dashboard(
    title="My Analysis",
    project="iris_project"
)

# Add components fluently
dashboard.add_figure(
    data="iris_table",
    visualization="scatter",
    x="sepal.length",
    y="sepal.width",
    color="variety",
    position=dp.Position(x=0, y=0, w=24, h=16)
)

dashboard.add_card(
    data="iris_table",
    column="sepal.length",
    aggregation="mean",
    position=dp.Position(x=24, y=0, w=8, h=6)
)

dashboard.add_filter(
    column="variety",
    type="multiselect",
    targets=["*"]  # Apply to all components
)

# Save to server
dashboard.save()  # Creates/updates on API

# Or export to YAML
dashboard.to_yaml("my_dashboard.yaml")

# Load from YAML
dashboard2 = dp.Dashboard.from_yaml("my_dashboard.yaml")
```

### Jupyter Integration

```python
# In Jupyter notebook
import depictio as dp

# Connect to depictio instance
dp.connect("http://localhost:8050", token="...")

# Create and preview inline
dashboard = dp.Dashboard(title="Notebook Analysis")
dashboard.add_figure(...)

# Render preview in notebook
dashboard.preview()  # IFrame or image

# Publish to server
url = dashboard.publish()
print(f"Dashboard live at: {url}")
```

### CLI Extensions

```bash
# Create from YAML
depictio dashboard create --from dashboard.yaml

# Export existing
depictio dashboard export abc123 --format yaml > dashboard.yaml

# Validate without creating
depictio dashboard validate dashboard.yaml

# Diff two dashboards
depictio dashboard diff abc123 def456

# Clone dashboard
depictio dashboard clone abc123 --name "New Dashboard"
```

---

## 4. Code Execution Alternatives to RestrictedPython

### Current Limitations
- RestrictedPython has edge cases and maintenance concerns
- Limited to specific Python patterns
- No async support
- Debugging can be challenging

### Alternative 1: Pyodide + WASM Sandbox (Recommended)

```python
# depictio/dash/modules/figure_component/pyodide_executor.py
import asyncio
from pyodide_sandbox import PythonSandbox

class PyodideCodeExecutor:
    """
    Execute Python code in a WebAssembly sandbox.

    Benefits:
    - True isolation (WASM memory sandbox)
    - Full Python support (no AST restrictions)
    - Can run pandas, numpy, plotly in WASM
    - Timeout support built-in
    - No system access possible
    """

    def __init__(self):
        self.sandbox = PythonSandbox(
            packages=["pandas", "numpy", "plotly"],
            memory_limit_mb=256,
            timeout_seconds=30
        )

    async def execute(self, code: str, data: dict) -> dict:
        """Execute code in isolated WASM environment."""
        result = await self.sandbox.run(
            code=code,
            globals={"df": data, "px": "plotly.express", "go": "plotly.graph_objects"},
            expected_output="fig"
        )
        return result.to_dict()
```

**Pros:**
- True isolation via WASM sandbox
- No Python version/compatibility issues
- Runs on server-side via Deno or Node.js
- Already used by LangChain for code execution

**Cons:**
- Additional dependency (Deno runtime)
- Slightly higher latency
- Package availability limited to pyodide-compatible

### Alternative 2: Docker-based Sandbox

```python
# depictio/dash/modules/figure_component/docker_executor.py
import docker
import tempfile
import json

class DockerCodeExecutor:
    """
    Execute code in ephemeral Docker containers.

    Benefits:
    - Maximum isolation
    - Full Python environment
    - Any package available
    - Resource limits enforced
    """

    def __init__(self):
        self.client = docker.from_env()
        self.image = "depictio/code-sandbox:latest"

    async def execute(self, code: str, data_path: str) -> dict:
        container = self.client.containers.run(
            self.image,
            command=["python", "/code/execute.py"],
            volumes={
                data_path: {"bind": "/data", "mode": "ro"},
            },
            mem_limit="256m",
            cpu_period=100000,
            cpu_quota=50000,  # 50% CPU
            network_disabled=True,
            read_only=True,
            remove=True,
            detach=False,
            timeout=30
        )
        return json.loads(container.decode())
```

### Alternative 3: Expression Language (No Python)

Instead of Python code, offer a domain-specific expression language:

```yaml
# Custom expression language for transformations
transform:
  - groupby: ["variety"]
    aggregate:
      sepal_mean: { column: "sepal.length", func: "mean" }
      count: { column: "*", func: "count" }
  - filter: "sepal_mean > 5"
  - sort: { by: "sepal_mean", ascending: false }

figure:
  type: "bar"
  x: "variety"
  y: "sepal_mean"
  color: "variety"
```

This compiles to Polars expressions server-side:

```python
def compile_expression(spec: dict, df: pl.DataFrame) -> pl.DataFrame:
    for step in spec.get("transform", []):
        if "groupby" in step:
            aggs = [compile_agg(a) for a in step["aggregate"].items()]
            df = df.group_by(step["groupby"]).agg(aggs)
        elif "filter" in step:
            df = df.filter(compile_filter(step["filter"]))
        elif "sort" in step:
            df = df.sort(step["sort"]["by"], descending=not step["sort"]["ascending"])
    return df
```

**Pros:**
- No security concerns (no code execution)
- Easier to validate and optimize
- Can generate UI from expressions
- Portable (works in browser too)

**Cons:**
- Less flexible than Python
- Learning curve for power users
- Can't do everything Python can

### Recommended Hybrid Approach

```python
# Three execution modes
class FigureExecutor:
    def __init__(self):
        self.expression_compiler = ExpressionCompiler()  # For simple cases
        self.restricted_python = SimpleCodeExecutor()     # Current, for backward compat
        self.pyodide_sandbox = PyodideSandbox()          # For advanced code mode

    def execute(self, mode: str, spec: dict, df: pl.DataFrame):
        match mode:
            case "expression":
                # Safe expression language
                return self.expression_compiler.compile_and_run(spec, df)
            case "restricted":
                # Current RestrictedPython (backward compat)
                return self.restricted_python.execute_code(spec["code"], df)
            case "sandbox":
                # Full Python in WASM sandbox
                return self.pyodide_sandbox.execute(spec["code"], df)
```

---

## 5. Template & Component Library

### Reusable Dashboard Templates

```yaml
# templates/genomics_qc.yaml
metadata:
  name: "Genomics QC Dashboard"
  description: "Standard QC metrics for sequencing data"
  author: "depictio-team"
  tags: ["genomics", "qc", "sequencing"]
  required_columns:
    - name: "sample_id"
      type: "string"
    - name: "total_reads"
      type: "integer"
    - name: "mapping_rate"
      type: "float"

parameters:
  - name: "mapping_threshold"
    type: "float"
    default: 0.8
    description: "Minimum acceptable mapping rate"

components:
  - id: "read-distribution"
    type: "figure"
    spec:
      visualization: "histogram"
      x: "total_reads"
      color: "sample_id"

  - id: "mapping-rate-card"
    type: "card"
    spec:
      column: "mapping_rate"
      aggregation: "mean"
      threshold: "${mapping_threshold}"
      conditional_color:
        - condition: ">= ${mapping_threshold}"
          color: "green"
        - condition: "< ${mapping_threshold}"
          color: "red"
```

### Component Presets

```python
# depictio/dash/component_presets.py
FIGURE_PRESETS = {
    "correlation_matrix": {
        "visualization": "heatmap",
        "auto_columns": "numeric",
        "aggregation": "correlation",
        "color_scale": "RdBu",
        "template": "mantine_light"
    },
    "time_series": {
        "visualization": "line",
        "x_type": "temporal",
        "auto_x": "first_datetime",
        "template": "mantine_light"
    },
    "distribution_overview": {
        "visualization": "box",
        "auto_y": "all_numeric",
        "facet_col": "variable",
        "template": "mantine_light"
    }
}
```

---

## 6. Real-time Collaboration Features

### WebSocket-based Live Updates

```python
# depictio/api/v1/endpoints/realtime/routes.py
from fastapi import WebSocket

@router.websocket("/ws/dashboard/{dashboard_id}")
async def dashboard_websocket(websocket: WebSocket, dashboard_id: str):
    await manager.connect(websocket, dashboard_id)
    try:
        while True:
            data = await websocket.receive_json()
            # Broadcast changes to all connected clients
            await manager.broadcast(
                dashboard_id,
                {
                    "type": data["type"],
                    "component_id": data.get("component_id"),
                    "changes": data.get("changes"),
                    "user": current_user.email
                },
                exclude=websocket
            )
    except WebSocketDisconnect:
        manager.disconnect(websocket, dashboard_id)
```

### Presence Awareness

```typescript
// Frontend: Show who's viewing/editing
interface UserPresence {
  userId: string;
  email: string;
  cursor?: { x: number; y: number };
  editing?: string;  // component ID being edited
  lastSeen: Date;
}
```

---

## 7. Notebook-Style Analysis Mode

### Concept
Add a "notebook" view to dashboards for exploratory analysis:

```yaml
# Notebook cells embedded in dashboard
notebook_cells:
  - id: "cell-1"
    type: "markdown"
    content: |
      ## Data Exploration
      Let's analyze the relationship between sepal and petal dimensions.

  - id: "cell-2"
    type: "code"
    code: |
      # Quick correlation analysis
      correlations = df.select(pl.corr("sepal.length", "petal.length"))
      print(f"Correlation: {correlations[0, 0]:.3f}")
    output: "Correlation: 0.872"

  - id: "cell-3"
    type: "figure"
    # References a component from the dashboard
    component_ref: "scatter-main"
```

---

## 8. API-First Dashboard Creation

### OpenAPI-based Dashboard Generation

```python
# Generate dashboard from API schema
@router.post("/generate_from_api")
async def generate_dashboard_from_api(
    openapi_url: str,
    endpoint: str,
    auth_config: dict | None = None
):
    """
    Automatically generate a dashboard from an API endpoint.

    1. Fetch OpenAPI schema
    2. Identify response schema
    3. Generate appropriate visualizations
    4. Create dashboard with auto-refresh
    """
    schema = await fetch_openapi_schema(openapi_url)
    response_schema = extract_response_schema(schema, endpoint)
    dashboard_spec = generate_dashboard_spec(response_schema)
    return await create_dashboard(dashboard_spec)
```

---

## Implementation Priority

### Phase 1: Foundation (High Impact, Moderate Effort)
1. **YAML Dashboard Export/Import** - Enable version control
2. **Python SDK** - Programmatic dashboard creation
3. **CLI Extensions** - Developer workflow improvements

### Phase 2: AI Integration (High Impact, High Effort)
4. **MCP Server** - AI assistant integration
5. **Pyodide Sandbox** - Secure code execution alternative

### Phase 3: Collaboration (Medium Impact, High Effort)
6. **Template Library** - Reusable dashboard patterns
7. **Real-time Collaboration** - Multi-user editing

### Phase 4: Advanced Features (Future)
8. **Notebook Mode** - Embedded analysis
9. **Expression Language** - No-code transformations
10. **API-First Generation** - Auto-dashboard from APIs

---

## Sources & References

- [Vizro by McKinsey](https://github.com/mckinsey/vizro) - Low-code dashboard toolkit
- [Vizro MCP Integration](https://www.marktechpost.com/2025/08/18/creating-dashboards-using-vizro-mcp-vizro-is-an-open-source-python-toolkit-by-mckinsey/)
- [LangChain Sandbox](https://github.com/langchain-ai/langchain-sandbox) - Pyodide + Deno sandbox
- [Pyodide](https://pyodide.org/) - Python in WebAssembly
- [Simon Willison on Pyodide Sandbox](https://til.simonwillison.net/deno/pyodide-sandbox)
- [sandboxed-python PyPI](https://pypi.org/project/sandboxed-python/)
