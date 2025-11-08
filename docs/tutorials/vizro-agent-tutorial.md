# Building a Vizro Expert Claude Agent

## Table of Contents
1. [Introduction](#introduction)
2. [Architecture Overview](#architecture-overview)
3. [Prerequisites](#prerequisites)
4. [Setting Up the Environment](#setting-up-the-environment)
5. [Core Components](#core-components)
6. [MCP Integration](#mcp-integration)
7. [Advanced Prompt Engineering](#advanced-prompt-engineering)
8. [Agent Capabilities](#agent-capabilities)
9. [Error Handling and Debugging](#error-handling-and-debugging)
10. [Best Practices](#best-practices)
11. [Example Use Cases](#example-use-cases)

---

## Introduction

This tutorial guides you through building an advanced Claude agent that serves as an expert in **Vizro** - McKinsey's open-source dashboard development framework. The agent will be capable of:

- **Creating**: Generate Vizro dashboards from natural language descriptions
- **Debugging**: Identify and fix issues in existing Vizro code
- **Teaching**: Explain Vizro concepts and guide users through development
- **Optimizing**: Suggest improvements and best practices

### What is Vizro?

Vizro is a Python toolkit that combines:
- **Rapid prototyping** (like Streamlit)
- **Production-ready customization** (like Dash)
- **Built-in design best practices** (opinionated defaults)

**Key Features:**
- Declarative configuration (Python/YAML/JSON)
- Plotly-based visualizations
- Pydantic model validation
- Built-in themes and layouts
- Multi-page navigation
- Interactive filters and parameters

### What is Vizro-MCP?

Vizro-MCP is a Model Context Protocol server that provides:
- Sample data information
- Model JSON schema retrieval
- Dashboard configuration validation
- Chart code validation
- PyCafe link generation for live testing

---

## Architecture Overview

### High-Level Design

```
┌─────────────────────────────────────────────────────────┐
│                   Claude Agent Core                      │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   Knowledge  │  │   Prompt     │  │  Validation  │ │
│  │     Base     │  │  Templates   │  │   Helpers    │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │            MCP Integration Layer                  │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │   Vizro-MCP Server   │
              │                      │
              │  • get_sample_data   │
              │  • get_model_schema  │
              │  • validate_config   │
              │  • validate_chart    │
              │  • analyze_data      │
              └──────────────────────┘
```

### Component Responsibilities

1. **Knowledge Base**: Structured Vizro patterns, common issues, best practices
2. **Prompt Templates**: Task-specific prompts for different agent modes
3. **Validation Helpers**: Schema checking, configuration validation
4. **MCP Integration**: Client wrapper for vizro-mcp tools

---

## Prerequisites

### Required Knowledge

- Advanced Python programming
- Understanding of Vizro framework (models, components, controls)
- Familiarity with Plotly/Dash
- Experience with MCP (Model Context Protocol)
- Pydantic models and validation

### Required Software

```bash
# Python 3.9+
python --version

# uv (recommended package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Vizro and vizro-mcp
uv pip install vizro
uvx vizro-mcp

# Claude Desktop (for MCP integration)
# Download from: https://claude.ai/download
```

---

## Setting Up the Environment

### Step 1: Install Dependencies

Create a `requirements.txt` for the agent project:

```txt
vizro>=0.1.47
pydantic>=2.0
requests>=2.31
anthropic>=0.21.0
```

Install:
```bash
uv pip install -r requirements.txt
```

### Step 2: Configure Vizro-MCP Server

Edit your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "vizro": {
      "command": "uvx",
      "args": ["vizro-mcp"]
    }
  }
}
```

Restart Claude Desktop to load the MCP server.

### Step 3: Verify MCP Connection

In Claude Desktop, check that vizro-mcp tools are available:
- `get_vizro_chart_or_dashboard_plan`
- `get_model_json_schema`
- `get_sample_data_info`
- `load_and_analyze_data`
- `validate_dashboard_config`
- `validate_chart_code`

---

## Core Components

### 1. Knowledge Base (`vizro_knowledge_base.py`)

The knowledge base contains:
- **Model schemas**: All Vizro models with parameters
- **Component patterns**: Common component configurations
- **Common issues**: Error patterns and solutions
- **Best practices**: Recommended approaches
- **Data type mappings**: Column types → selector types

**Structure:**

```python
"""
Comprehensive Vizro knowledge base for the Claude agent.
"""

from typing import Dict, List, Any
from dataclasses import dataclass

@dataclass
class VizroModel:
    """Represents a Vizro model with its schema."""
    name: str
    description: str
    required_fields: List[str]
    optional_fields: Dict[str, Any]
    examples: List[Dict[str, Any]]

@dataclass
class CommonIssue:
    """Represents a common Vizro issue with solution."""
    pattern: str
    description: str
    solution: str
    code_example: str

class VizroKnowledgeBase:
    """Central repository of Vizro knowledge."""

    # Model definitions
    MODELS: Dict[str, VizroModel] = {...}

    # Component patterns
    COMPONENT_PATTERNS: Dict[str, Dict] = {...}

    # Common issues
    COMMON_ISSUES: List[CommonIssue] = {...}

    # Best practices
    BEST_PRACTICES: Dict[str, List[str]] = {...}

    # Data type mappings
    DATA_TYPE_SELECTOR_MAP: Dict[str, str] = {
        "categorical": "Dropdown",
        "numerical": "RangeSlider",
        "temporal": "DatePicker",
        "boolean": "Switch"
    }
```

### 2. Prompt Templates (`prompt_templates.py`)

Specialized prompts for different agent modes:

```python
"""
Prompt templates for Vizro agent tasks.
"""

class VizroPromptTemplates:
    """Collection of prompt templates for different agent modes."""

    DASHBOARD_CREATION = """
You are a Vizro expert helping to create a dashboard from natural language.

User Request: {user_request}

Data Information:
{data_info}

Instructions:
1. Analyze the data structure and user requirements
2. Determine appropriate components (Graph, Table, AgGrid, Card)
3. Select suitable visualizations based on data types
4. Configure filters and parameters for interactivity
5. Design layout (Grid or Flex)
6. Generate valid Vizro configuration

Use vizro-mcp tools:
- get_sample_data_info() for data understanding
- get_model_json_schema() for model validation
- validate_dashboard_config() to verify configuration

Output format: {output_format}
"""

    DEBUGGING = """
You are a Vizro debugging expert analyzing code issues.

Code to Debug:
{code}

Error Message:
{error}

Instructions:
1. Identify the root cause of the error
2. Check for common issues:
   - Invalid model parameters
   - Incorrect data references
   - Missing required fields
   - Type mismatches
3. Suggest specific fixes with code examples
4. Explain why the error occurred

Common Vizro Issues:
{common_issues}
"""

    CODE_OPTIMIZATION = """
You are a Vizro optimization expert improving dashboard code.

Current Code:
{code}

Focus Areas:
{focus_areas}

Instructions:
1. Analyze code for performance bottlenecks
2. Check adherence to best practices
3. Identify optimization opportunities:
   - Data loading efficiency
   - Caching strategies
   - Component selection
   - Layout optimization
4. Suggest improvements with rationale

Best Practices:
{best_practices}
"""

    TEACHING = """
You are a Vizro educator explaining concepts clearly.

Topic: {topic}
User Level: Advanced

Instructions:
1. Provide comprehensive explanation of the concept
2. Include code examples demonstrating usage
3. Explain why/when to use this approach
4. Contrast with alternative approaches
5. Share advanced tips and edge cases

Reference Documentation:
{reference_docs}
"""
```

### 3. Validation Helpers (`validation_helpers.py`)

Configuration and schema validation utilities:

```python
"""
Validation helpers for Vizro configurations.
"""

from typing import Dict, Any, List, Tuple
import json
from pydantic import ValidationError

class VizroValidator:
    """Validates Vizro configurations against schemas."""

    def __init__(self, mcp_client):
        self.mcp_client = mcp_client
        self._schema_cache = {}

    async def get_model_schema(self, model_name: str) -> Dict[str, Any]:
        """Retrieve JSON schema for a Vizro model."""
        if model_name in self._schema_cache:
            return self._schema_cache[model_name]

        schema = await self.mcp_client.call_tool(
            "get_model_json_schema",
            {"model_name": model_name}
        )
        self._schema_cache[model_name] = schema
        return schema

    async def validate_dashboard_config(
        self,
        config: Dict[str, Any],
        data_infos: List[Dict],
        custom_charts: List[Dict]
    ) -> Tuple[bool, str, Dict]:
        """
        Validate a complete dashboard configuration.

        Returns:
            (is_valid, message, details)
        """
        result = await self.mcp_client.call_tool(
            "validate_dashboard_config",
            {
                "dashboard_config": config,
                "data_infos": data_infos,
                "custom_charts": custom_charts,
                "auto_open": False
            }
        )

        is_valid = result.get("status") == "success"
        message = result.get("message", "")
        details = result.get("data", {})

        return is_valid, message, details

    async def validate_chart_code(
        self,
        chart_config: Dict[str, Any],
        data_info: Dict[str, Any]
    ) -> Tuple[bool, str, Dict]:
        """
        Validate custom chart code.

        Returns:
            (is_valid, message, details)
        """
        result = await self.mcp_client.call_tool(
            "validate_chart_code",
            {
                "chart_config": chart_config,
                "data_info": data_info,
                "auto_open": False
            }
        )

        is_valid = result.get("status") == "success"
        message = result.get("message", "")
        details = result.get("data", {})

        return is_valid, message, details

    def check_required_fields(
        self,
        config: Dict[str, Any],
        model_name: str
    ) -> List[str]:
        """Check for missing required fields."""
        schema = self.get_model_schema(model_name)
        required = schema.get("required", [])
        missing = [field for field in required if field not in config]
        return missing

    def validate_field_types(
        self,
        config: Dict[str, Any],
        schema: Dict[str, Any]
    ) -> List[str]:
        """Validate field types against schema."""
        errors = []
        properties = schema.get("properties", {})

        for field, value in config.items():
            if field not in properties:
                errors.append(f"Unknown field: {field}")
                continue

            expected_type = properties[field].get("type")
            actual_type = type(value).__name__

            # Type checking logic
            # ... (detailed implementation)

        return errors
```

### 4. MCP Integration (`mcp_integration.py`)

Client wrapper for vizro-mcp server:

```python
"""
MCP client wrapper for vizro-mcp server integration.
"""

import asyncio
from typing import Dict, Any, List, Optional
import json

class VizroMCPClient:
    """Client for interacting with vizro-mcp server."""

    def __init__(self):
        self.server_name = "vizro"
        self.available_tools = [
            "get_vizro_chart_or_dashboard_plan",
            "get_model_json_schema",
            "get_sample_data_info",
            "load_and_analyze_data",
            "validate_dashboard_config",
            "validate_chart_code"
        ]

    async def call_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Call a vizro-mcp tool.

        Args:
            tool_name: Name of the tool to call
            parameters: Tool parameters

        Returns:
            Tool result as dictionary
        """
        if tool_name not in self.available_tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        # In actual implementation, this would call the MCP server
        # For now, we'll use a placeholder that shows the structure

        # Example: Claude Code would execute this via MCP
        # result = await mcp_call(f"mcp__vizro-mcp__{tool_name}", parameters)

        # Placeholder response
        return {"status": "success", "data": {}}

    async def get_sample_data_info(
        self,
        data_name: str
    ) -> Dict[str, Any]:
        """Get information about sample datasets."""
        return await self.call_tool(
            "get_sample_data_info",
            {"data_name": data_name}
        )

    async def load_and_analyze_data(
        self,
        path_or_url: str
    ) -> Dict[str, Any]:
        """Load and analyze a data file."""
        return await self.call_tool(
            "load_and_analyze_data",
            {"path_or_url": path_or_url}
        )

    async def get_dashboard_plan(
        self,
        user_plan: str,
        user_host: str = "ide",
        advanced_mode: bool = False
    ) -> str:
        """Get instructions for creating a dashboard."""
        result = await self.call_tool(
            "get_vizro_chart_or_dashboard_plan",
            {
                "user_plan": user_plan,
                "user_host": user_host,
                "advanced_mode": advanced_mode
            }
        )
        return result.get("data", {}).get("instructions", "")

    async def validate_dashboard(
        self,
        config: Dict[str, Any],
        data_infos: List[Dict],
        custom_charts: List[Dict],
        auto_open: bool = False
    ) -> Dict[str, Any]:
        """Validate a complete dashboard configuration."""
        return await self.call_tool(
            "validate_dashboard_config",
            {
                "dashboard_config": config,
                "data_infos": data_infos,
                "custom_charts": custom_charts,
                "auto_open": auto_open
            }
        )
```

---

## MCP Integration

### Understanding MCP Communication

The Model Context Protocol enables Claude to communicate with external tools. For Vizro, this means:

1. **Claude sends request** → MCP server
2. **MCP server executes** → Vizro validation/analysis
3. **MCP server returns** → Results to Claude
4. **Claude interprets** → Provides response to user

### Available Vizro-MCP Tools

#### 1. `get_vizro_chart_or_dashboard_plan`

**Purpose**: Get instructions for creating Vizro artifacts

**Parameters:**
- `user_plan`: "chart" or "dashboard"
- `user_host`: "generic_host" or "ide"
- `advanced_mode`: Boolean (for custom CSS/components)

**Usage:**
```python
instructions = await mcp_client.call_tool(
    "get_vizro_chart_or_dashboard_plan",
    {
        "user_plan": "dashboard",
        "user_host": "ide",
        "advanced_mode": False
    }
)
```

#### 2. `get_model_json_schema`

**Purpose**: Retrieve JSON schema for validation

**Parameters:**
- `model_name`: Name of Vizro model (e.g., "Dashboard", "Page", "Graph")

**Usage:**
```python
schema = await mcp_client.call_tool(
    "get_model_json_schema",
    {"model_name": "Dashboard"}
)
```

#### 3. `get_sample_data_info`

**Purpose**: Get information about sample datasets

**Parameters:**
- `data_name`: "iris", "tips", "stocks", or "gapminder"

**Usage:**
```python
data_info = await mcp_client.call_tool(
    "get_sample_data_info",
    {"data_name": "iris"}
)
```

#### 4. `load_and_analyze_data`

**Purpose**: Analyze user data files

**Parameters:**
- `path_or_url`: Absolute path or URL to data file

**Supported formats:** CSV, JSON, HTML, Excel, ODS, Parquet

**Usage:**
```python
analysis = await mcp_client.call_tool(
    "load_and_analyze_data",
    {"path_or_url": "/absolute/path/to/data.csv"}
)
```

#### 5. `validate_dashboard_config`

**Purpose**: Validate complete dashboard configuration

**Parameters:**
- `dashboard_config`: Dashboard config dict/JSON
- `data_infos`: List of data metadata
- `custom_charts`: List of custom chart configs
- `auto_open`: Boolean (open PyCafe link)

**Returns:** Python code and PyCafe link (if valid)

**Usage:**
```python
result = await mcp_client.call_tool(
    "validate_dashboard_config",
    {
        "dashboard_config": {...},
        "data_infos": [...],
        "custom_charts": [...],
        "auto_open": False
    }
)
```

#### 6. `validate_chart_code`

**Purpose**: Validate custom chart code

**Parameters:**
- `chart_config`: ChartPlan object with code
- `data_info`: Dataset metadata
- `auto_open`: Boolean (open PyCafe link)

**Returns:** Python code and PyCafe link (if valid)

---

## Advanced Prompt Engineering

### Strategy 1: Task-Specific System Prompts

Create specialized prompts for each agent mode:

```python
SYSTEM_PROMPTS = {
    "creation": """
You are a Vizro expert specializing in dashboard creation. Your role is to:

1. ANALYZE user requirements and data structure
2. RECOMMEND appropriate Vizro components and configurations
3. GENERATE valid, production-ready dashboard configurations
4. VALIDATE configurations using vizro-mcp tools
5. EXPLAIN design decisions and best practices

Always use vizro-mcp tools:
- get_sample_data_info() or load_and_analyze_data() to understand data
- get_model_json_schema() to ensure valid configurations
- validate_dashboard_config() before presenting final code

Follow Vizro best practices:
- Use Graph for charts, AgGrid for tables
- Auto-detect selector types from data
- Apply Grid layout for structured pages
- Include filters for interactivity
""",

    "debugging": """
You are a Vizro debugging specialist. Your role is to:

1. IDENTIFY root causes of errors in Vizro code
2. RECOGNIZE common patterns and anti-patterns
3. PROVIDE specific, actionable fixes
4. EXPLAIN why errors occurred and how to prevent them

Common error categories:
- Invalid model parameters
- Type mismatches
- Missing required fields
- Incorrect data references
- Callback conflicts

Always:
- Validate fixes against schemas using get_model_json_schema()
- Test fixes with validate_dashboard_config()
- Provide working code examples
""",

    "optimization": """
You are a Vizro performance and code quality expert. Your role is to:

1. ANALYZE code for performance bottlenecks
2. IDENTIFY deviations from best practices
3. RECOMMEND specific optimizations
4. QUANTIFY expected improvements

Focus areas:
- Data loading efficiency (caching, pre-filtering)
- Component selection (AgGrid vs Table)
- Layout optimization (Grid vs Flex)
- Callback performance
- Production readiness

Best practices:
{best_practices}
""",

    "teaching": """
You are a Vizro educator. Your role is to:

1. EXPLAIN concepts clearly with examples
2. DEMONSTRATE usage patterns
3. CONTRAST different approaches with pros/cons
4. SHARE advanced tips and edge cases

Teaching approach:
- Start with concept overview
- Show simple example
- Progress to advanced usage
- Highlight common mistakes
- Reference official docs

Always provide:
- Executable code examples
- Explanation of parameters
- When/why to use this approach
"""
}
```

### Strategy 2: Chain-of-Thought for Complex Tasks

For dashboard creation:

```
1. Data Analysis Phase
   → Use load_and_analyze_data() or get_sample_data_info()
   → Identify: columns, types, ranges, categorical values
   → Determine: suitable visualizations, filters, parameters

2. Planning Phase
   → Map data types to components
   → Select visualization types
   → Design page layout
   → Plan interactivity (filters, parameters, actions)

3. Configuration Generation Phase
   → Start with Page model
   → Add components (Graph, Table, Card)
   → Configure controls (Filter, Parameter)
   → Set layout (Grid or Flex)
   → Create Dashboard model

4. Validation Phase
   → Check required fields using get_model_json_schema()
   → Validate full config with validate_dashboard_config()
   → Review PyCafe link for live preview

5. Refinement Phase
   → Explain design decisions
   → Suggest optimizations
   → Provide usage instructions
```

### Strategy 3: Few-Shot Learning with Examples

Include examples in prompts:

```python
EXAMPLE_DASHBOARD = """
Example 1: Simple Scatter Plot Dashboard

User Request: "Create a dashboard with a scatter plot of sepal_length vs petal_width, colored by species"

Data: Iris dataset (150 rows, 5 columns)

Generated Configuration:
```python
import vizro.models as vm
import vizro.plotly.express as px

df = px.data.iris()

dashboard = vm.Dashboard(
    pages=[
        vm.Page(
            title="Iris Analysis",
            components=[
                vm.Graph(
                    figure=px.scatter(
                        df,
                        x="sepal_length",
                        y="petal_width",
                        color="species"
                    )
                )
            ],
            controls=[
                vm.Filter(column="species")
            ]
        )
    ]
)
```

Validation Result: ✓ Valid
PyCafe Link: https://py.cafe/...
"""
```

### Strategy 4: Error Recovery Patterns

```python
ERROR_RECOVERY_PROMPT = """
When validation fails:

1. PARSE the error message carefully
2. IDENTIFY the specific issue:
   - Missing required field → Add with default value
   - Invalid type → Convert to correct type
   - Unknown field → Remove or rename
   - Schema violation → Adjust to match schema

3. APPLY fix and RE-VALIDATE
4. If still failing → Try alternative approach
5. EXPLAIN what was wrong and what was fixed

Example:
Error: "Field 'components' is required for Page model"
Fix: Add components=[] to Page configuration
Explanation: Page model requires at least an empty components list
"""
```

---

## Agent Capabilities

### Capability 1: Dashboard Creation from Natural Language

**Process Flow:**

```python
async def create_dashboard(user_request: str, data_source: str):
    """Create dashboard from natural language."""

    # 1. Analyze data
    if data_source in ["iris", "tips", "stocks", "gapminder"]:
        data_info = await mcp_client.get_sample_data_info(data_source)
    else:
        data_info = await mcp_client.load_and_analyze_data(data_source)

    # 2. Get creation instructions
    instructions = await mcp_client.get_dashboard_plan(
        user_plan="dashboard",
        user_host="ide",
        advanced_mode=False
    )

    # 3. Generate configuration based on request + data
    config = generate_config(user_request, data_info, instructions)

    # 4. Validate configuration
    is_valid, message, details = await validator.validate_dashboard_config(
        config=config,
        data_infos=[data_info],
        custom_charts=[]
    )

    # 5. Return result with code and link
    if is_valid:
        return {
            "success": True,
            "code": details.get("python_code"),
            "pycafe_link": details.get("pycafe_link"),
            "message": message
        }
    else:
        # Attempt to fix and retry
        fixed_config = apply_fixes(config, message)
        return await create_dashboard_retry(fixed_config, data_info)
```

**Example Interaction:**

```
User: "Create a dashboard showing sales trends over time with filters for region and product"

Agent:
1. Analyzes data structure (datetime, numerical, categorical columns)
2. Selects appropriate components:
   - vm.Graph with px.line for time series
   - vm.Filter for region (Dropdown)
   - vm.Filter for product (Dropdown)
3. Generates configuration
4. Validates with vizro-mcp
5. Returns working code + PyCafe link
```

### Capability 2: Debugging Existing Code

**Process Flow:**

```python
async def debug_vizro_code(code: str, error_message: str):
    """Debug Vizro code and provide fixes."""

    # 1. Parse code to extract configuration
    config = parse_vizro_code(code)

    # 2. Identify error category
    error_type = classify_error(error_message)

    # 3. Match against common issues
    known_issue = knowledge_base.find_matching_issue(error_message)

    if known_issue:
        # Apply known solution
        fixed_code = apply_solution(code, known_issue.solution)
    else:
        # Analyze and fix
        # Check for missing fields
        missing = validator.check_required_fields(config, "Dashboard")

        # Check for type mismatches
        type_errors = validator.validate_field_types(config, schema)

        # Generate fixes
        fixed_code = generate_fixes(code, missing, type_errors)

    # 4. Validate fix
    is_valid, message, details = await validator.validate_dashboard_config(
        config=parse_vizro_code(fixed_code),
        data_infos=[...],
        custom_charts=[]
    )

    # 5. Return explanation + fixed code
    return {
        "issue": explain_issue(error_message),
        "fix": fixed_code,
        "explanation": explain_fix(error_message, fixed_code),
        "validated": is_valid
    }
```

**Example Interaction:**

```
User: "I'm getting an error: 'components' field required"

Code:
```python
page = vm.Page(title="My Page")
```

Agent Response:
Issue: The Page model requires a 'components' field (list of visual elements)

Fix:
```python
page = vm.Page(
    title="My Page",
    components=[]  # Add at least empty list
)
```

Explanation: Vizro's Page model has 'components' as a required field. Even if you plan to add components later, you must provide at least an empty list during initialization.

Best Practice: Always include components when creating a Page:
```python
page = vm.Page(
    title="My Page",
    components=[
        vm.Graph(figure=px.scatter(...)),
        vm.Table(figure=...)
    ]
)
```
```

### Capability 3: Code Optimization

**Focus Areas:**

1. **Data Loading Efficiency**
   - Recommend caching strategies
   - Suggest pre-filtering for large datasets
   - Identify opportunities for parametrized loading

2. **Component Selection**
   - Replace Table with AgGrid for better performance
   - Use Figure for custom components instead of hacks
   - Optimize layout choice (Grid vs Flex)

3. **Best Practices Compliance**
   - Check for hardcoded data (should use data_manager)
   - Verify filter/parameter targeting
   - Ensure proper action chaining

**Example Optimization:**

```python
# BEFORE (suboptimal)
@data_manager.add_data("sales")
def load_sales():
    df = pd.read_csv("large_file.csv")  # No caching
    return df

page = vm.Page(
    components=[
        vm.Table(  # Slower than AgGrid
            figure=dash_data_table(data_frame="sales")
        )
    ]
)

# AFTER (optimized)
from flask_caching import Cache
cache = Cache(config={"CACHE_TYPE": "SimpleCache"})

@data_manager.add_data("sales")
@cache.memoize(timeout=300)  # Cache for 5 minutes
def load_sales():
    df = pd.read_csv("large_file.csv")
    return df

page = vm.Page(
    components=[
        vm.AgGrid(  # Faster, more features
            figure=dash_ag_grid(
                data_frame="sales",
                columnDefs=[...]
            )
        )
    ]
)
```

### Capability 4: Teaching and Explanation

**Teaching Modes:**

1. **Concept Explanation**
   - Clear definition with context
   - Visual examples
   - Common use cases

2. **Code Walkthrough**
   - Line-by-line explanation
   - Parameter descriptions
   - Alternative approaches

3. **Best Practices**
   - Why this approach is recommended
   - When to use vs alternatives
   - Common pitfalls to avoid

**Example Teaching Session:**

```
User: "Explain how Filters work in Vizro"

Agent Response:

# Vizro Filters: Comprehensive Guide

## What are Filters?

Filters in Vizro enable users to subset data displayed in components. They automatically detect the appropriate selector (Dropdown, RangeSlider, DatePicker) based on column data type.

## Basic Usage

```python
vm.Filter(column="species")
```

This creates a filter that:
1. Detects "species" is categorical
2. Creates a multi-select Dropdown
3. Applies to ALL components on the page

## Advanced Configuration

### Target Specific Components
```python
vm.Filter(
    column="species",
    targets=["scatter_plot", "histogram"]  # Only these components
)
```

### Custom Selector
```python
vm.Filter(
    column="species",
    selector=vm.RadioItems(  # Single-select instead of multi
        options=["setosa", "versicolor", "virginica"]
    )
)
```

## Auto-Detection Rules

| Data Type | Auto-Selected Selector |
|-----------|------------------------|
| Categorical | Dropdown (multi-select) |
| Numerical | RangeSlider |
| Temporal | DatePicker |
| Boolean | Switch |

## Filters vs Parameters

**Use Filter when:**
- Subsetting data (removing rows)
- Working with DataFrame columns
- Want auto-detection

**Use Parameter when:**
- Changing function arguments
- Modifying chart properties (colors, axes)
- Need explicit control

## Common Patterns

### Multi-Filter Dashboard
```python
page = vm.Page(
    components=[...],
    controls=[
        vm.Filter(column="category"),
        vm.Filter(column="date_range"),
        vm.Filter(column="value", selector=vm.RangeSlider())
    ]
)
```

### Cross-Filtering
```python
# Click on chart → update filter → affect other charts
vm.Graph(
    id="source",
    figure=px.scatter(...),
    actions=[va.set_control(control="category_filter", value="selected")]
)
```

## Best Practices

✅ DO:
- Let Vizro auto-detect selectors when possible
- Use meaningful column names (displayed in UI)
- Place related filters together

❌ DON'T:
- Filter on ID columns (not user-friendly)
- Create too many filters (overwhelming)
- Use filters for non-data modifications (use Parameters)

## Advanced: Dynamic Filter Options

```python
@data_manager.add_data("filtered_data")
def load_data(region="All"):
    if region == "All":
        return df
    return df[df["region"] == region]
```

Now the filter affects what data is loaded!
```
```

---

## Error Handling and Debugging

### Common Error Patterns

#### 1. Missing Required Fields

**Error:**
```
ValidationError: 1 validation error for Page
components
  field required (type=value_error.missing)
```

**Solution:**
```python
# WRONG
page = vm.Page(title="My Page")

# CORRECT
page = vm.Page(title="My Page", components=[])
```

#### 2. Invalid Model Type

**Error:**
```
ValidationError: value is not a valid dict (type=type_error.dict)
```

**Solution:**
```python
# WRONG
vm.Graph(figure="my_chart")  # String instead of Figure object

# CORRECT
vm.Graph(figure=px.scatter(...))  # Proper Figure object
```

#### 3. Incorrect Data Reference

**Error:**
```
KeyError: 'my_data' not found in data_manager
```

**Solution:**
```python
# Register data first
data_manager["my_data"] = df

# Then reference
vm.Graph(figure=px.scatter(data_frame="my_data", ...))
```

#### 4. Target Component Not Found

**Error:**
```
ValueError: Target 'nonexistent_id' not found
```

**Solution:**
```python
# Ensure component has matching id
vm.Graph(id="scatter_plot", ...)

# Then target it
vm.Filter(column="species", targets=["scatter_plot"])
```

### Debugging Workflow

```python
async def debug_with_agent(code: str, error: str):
    """Comprehensive debugging workflow."""

    # Step 1: Classify error
    error_category = classify_error(error)

    # Step 2: Check against known issues
    known_solution = knowledge_base.get_solution(error_category)

    # Step 3: If not known, analyze code structure
    if not known_solution:
        config = parse_code(code)

        # Validate against schemas
        errors = []
        for model_type in ["Dashboard", "Page", "Graph"]:
            schema = await mcp_client.call_tool(
                "get_model_json_schema",
                {"model_name": model_type}
            )
            model_errors = validator.validate_field_types(config, schema)
            errors.extend(model_errors)

    # Step 4: Generate fix
    fixed_code = apply_fixes(code, known_solution or errors)

    # Step 5: Validate fix
    result = await validator.validate_dashboard_config(
        config=parse_code(fixed_code),
        data_infos=[...],
        custom_charts=[]
    )

    # Step 6: Return explanation
    return {
        "error_type": error_category,
        "explanation": explain_error(error),
        "fixed_code": fixed_code,
        "validation_result": result,
        "prevention_tips": get_prevention_tips(error_category)
    }
```

---

## Best Practices

### 1. Configuration Generation

✅ **DO:**
- Always validate configurations before presenting
- Use vizro-mcp tools for schema checking
- Provide PyCafe links for live testing
- Explain design decisions
- Include comments in generated code

❌ **DON'T:**
- Generate invalid configurations
- Skip validation step
- Assume configuration is correct
- Provide code without explanation

### 2. Data Handling

✅ **DO:**
- Use `load_and_analyze_data()` for user files
- Check column types and ranges
- Recommend appropriate visualizations
- Suggest caching for large datasets

❌ **DON'T:**
- Assume data structure without checking
- Skip data analysis step
- Recommend unsuitable visualizations

### 3. Error Messages

✅ **DO:**
- Explain root cause clearly
- Provide specific, actionable fixes
- Include code examples
- Explain why error occurred
- Suggest prevention strategies

❌ **DON'T:**
- Just paste the error message
- Provide vague suggestions
- Skip explanation of why
- Ignore error prevention

### 4. Teaching

✅ **DO:**
- Start with clear concept explanation
- Progress from simple to advanced
- Provide executable examples
- Explain when/why to use
- Contrast with alternatives

❌ **DON'T:**
- Assume prior knowledge
- Skip foundational concepts
- Provide only code without explanation
- Ignore edge cases

---

## Example Use Cases

### Use Case 1: Creating Multi-Page Dashboard

**User Request:**
"Create a dashboard with two pages: Overview (showing summary statistics) and Details (showing data table and charts)"

**Agent Process:**

```python
# 1. Analyze requirements
requirements = {
    "pages": 2,
    "page1": "Overview with summary stats",
    "page2": "Details with table and charts",
    "navigation": "needed for multi-page"
}

# 2. Get data info
data_info = await mcp_client.get_sample_data_info("iris")

# 3. Generate configuration
config = {
    "pages": [
        {
            "title": "Overview",
            "components": [
                {
                    "type": "card",
                    "text": "# Summary Statistics\n\n**Total Records**: 150\n**Species**: 3"
                },
                {
                    "type": "graph",
                    "figure": {
                        "_target_": "box",
                        "data_frame": "iris",
                        "x": "species",
                        "y": "sepal_length"
                    }
                }
            ]
        },
        {
            "title": "Details",
            "components": [
                {
                    "type": "ag_grid",
                    "figure": {
                        "_target_": "dash_ag_grid",
                        "data_frame": "iris"
                    }
                },
                {
                    "type": "graph",
                    "figure": {
                        "_target_": "scatter",
                        "data_frame": "iris",
                        "x": "sepal_length",
                        "y": "petal_width",
                        "color": "species"
                    }
                }
            ],
            "controls": [
                {"type": "filter", "column": "species"}
            ]
        }
    ]
}

# 4. Validate
result = await mcp_client.validate_dashboard(
    config=config,
    data_infos=[data_info],
    custom_charts=[],
    auto_open=False
)

# 5. Present result
return {
    "code": result["python_code"],
    "pycafe_link": result["pycafe_link"],
    "explanation": """
Created a two-page dashboard:

**Overview Page:**
- Card with summary statistics
- Box plot showing distribution by species

**Details Page:**
- AgGrid table with full dataset
- Scatter plot with species filter

**Navigation:**
- Automatic accordion navigation added
- Users can switch between pages

**Try it:** [PyCafe Link]
"""
}
```

### Use Case 2: Debugging Callback Conflict

**User Report:**
"I'm getting a callback error when I add a second graph"

**Code:**
```python
page = vm.Page(
    components=[
        vm.Graph(id="graph1", figure=px.scatter(...)),
        vm.Graph(id="graph1", figure=px.line(...))  # Duplicate ID!
    ]
)
```

**Agent Response:**

```
Error Identified: Duplicate Component IDs

Issue:
Both Graph components have the same id="graph1". In Dash (which Vizro is built on), every component must have a unique ID to enable callbacks.

Root Cause:
When Vizro creates callbacks for interactivity, it uses component IDs as targets. Duplicate IDs cause callback conflicts because Dash doesn't know which component to update.

Fix:
```python
page = vm.Page(
    components=[
        vm.Graph(id="scatter_plot", figure=px.scatter(...)),
        vm.Graph(id="line_chart", figure=px.line(...))
    ]
)
```

Explanation:
- Changed IDs to "scatter_plot" and "line_chart"
- Now each component has unique identifier
- Callbacks can target specific components

Prevention:
✅ Use descriptive, unique IDs for all components
✅ Follow naming convention: {component_type}_{description}
✅ If ID not specified, Vizro auto-generates unique IDs

Best Practice:
```python
# Explicit IDs for components you'll reference
vm.Graph(id="main_scatter", ...)

# Omit ID for components without interactions
vm.Card(text="Static text")  # Auto-generated ID
```
```

### Use Case 3: Optimizing Performance

**User Request:**
"My dashboard is slow to load with 100k rows"

**Agent Analysis:**

```python
# Analyze current implementation
current_code = """
@data_manager.add_data("large_data")
def load_data():
    return pd.read_csv("100k_rows.csv")  # No caching!

page = vm.Page(
    components=[
        vm.Table(  # Slow for large data
            figure=dash_data_table(data_frame="large_data")
        ),
        vm.Graph(figure=px.scatter(data_frame="large_data", ...))
    ]
)
"""

# Identify bottlenecks
issues = [
    "No caching → re-reads CSV on every page load",
    "Using Table → slower than AgGrid for large datasets",
    "Loading all 100k rows → should pre-filter",
    "No pagination → trying to display all rows at once"
]

# Generate optimized version
optimized_code = """
from flask_caching import Cache

# Configure cache
cache = Cache(config={"CACHE_TYPE": "SimpleCache"})

# Add caching to data loading
@data_manager.add_data("large_data")
@cache.memoize(timeout=600)  # Cache for 10 minutes
def load_data(category=None):
    df = pd.read_csv("100k_rows.csv")

    # Pre-filter if parameter provided
    if category:
        df = df[df["category"] == category]

    return df

page = vm.Page(
    components=[
        vm.AgGrid(  # Much faster than Table
            figure=dash_ag_grid(
                data_frame="large_data",
                defaultColDef={"filter": True},
                pagination=True,  # Enable pagination
                paginationPageSize=50  # Show 50 rows per page
            )
        ),
        vm.Graph(
            figure=px.scatter(
                data_frame="large_data",
                x="x",
                y="y",
                # Sample data for visualization
                render_mode="webgl"  # Faster rendering
            )
        )
    ],
    controls=[
        # Add parameter to enable pre-filtering
        vm.Parameter(
            targets=["large_data.category"],
            selector=vm.Dropdown(
                options=["A", "B", "C"],
                value="A"  # Default loads only category A
            )
        )
    ]
)
"""

# Calculate improvements
improvements = {
    "caching": "10x faster on repeat visits",
    "agrid": "5x faster rendering vs Table",
    "pagination": "Only loads 50 rows at a time",
    "pre_filtering": "Reduces data by ~67% (if 3 categories)",
    "webgl": "2x faster chart rendering"
}

return {
    "issues": issues,
    "optimized_code": optimized_code,
    "improvements": improvements,
    "explanation": """
Applied 5 key optimizations:

1. **Caching** (10x faster)
   - Added @cache.memoize decorator
   - CSV read once, cached for 10 minutes
   - Repeat visits instant

2. **AgGrid Instead of Table** (5x faster)
   - Better performance with large datasets
   - Built-in filtering and sorting
   - Virtual scrolling

3. **Pagination** (Essential)
   - Only renders 50 rows at a time
   - User can navigate pages
   - Drastically reduces initial load

4. **Pre-filtering** (67% reduction)
   - Added category parameter
   - Only loads relevant data
   - User selects category from dropdown

5. **WebGL Rendering** (2x faster)
   - Uses GPU for chart rendering
   - Essential for large scatter plots
   - Much smoother interactions

Expected Result:
- Initial load: 2-3 seconds (was 20+ seconds)
- Repeat visits: <500ms (was 20+ seconds)
- Smooth interactions throughout
"""
}
```

---

## Conclusion

This tutorial has covered building an advanced Claude agent for Vizro expertise. Key takeaways:

1. **Architecture**: Modular design with knowledge base, prompts, validation, and MCP integration
2. **MCP Integration**: Leverage vizro-mcp tools for validation and schema access
3. **Capabilities**: Creation, debugging, optimization, and teaching
4. **Best Practices**: Always validate, explain decisions, provide examples

### Next Steps

1. Implement the core components
2. Build example scenarios
3. Test with real dashboards
4. Iterate based on feedback
5. Extend knowledge base with new patterns

### Resources

- **Vizro Docs**: https://vizro.readthedocs.io
- **Vizro-MCP**: https://github.com/mckinsey/vizro
- **MCP Protocol**: https://modelcontextprotocol.io
- **Claude Code**: https://docs.claude.com/claude-code

---

**Happy Building! 🚀**
