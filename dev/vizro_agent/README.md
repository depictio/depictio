# Vizro Expert Claude Agent

A comprehensive Claude agent for Vizro dashboard development, debugging, optimization, and teaching.

## Overview

This agent provides expert assistance with McKinsey's Vizro dashboard framework through four specialized modes:

- **Creation**: Generate dashboards from natural language descriptions
- **Debugging**: Identify and fix issues in Vizro code
- **Optimization**: Improve performance and code quality
- **Teaching**: Explain concepts with examples and best practices

## Quick Start

### Prerequisites

```bash
# Python 3.9+
python --version

# Install dependencies
pip install vizro pydantic anthropic

# Install vizro-mcp
uvx vizro-mcp
```

### Configure MCP Server

Edit your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

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

Restart Claude Desktop to load the server.

### Basic Usage

```python
import asyncio
from agent_core import VizroAgent, AgentContext, AgentMode

async def main():
    agent = VizroAgent()

    # Create a dashboard
    context = AgentContext(
        mode=AgentMode.CREATION,
        user_request="Create a scatter plot dashboard with filters",
        data_source="iris"
    )

    result = await agent.process_request(context)
    print(result.code)
    print(result.pycafe_link)

asyncio.run(main())
```

## Architecture

```
vizro_agent/
├── agent_core.py              # Main agent implementation
├── vizro_knowledge_base.py    # Vizro patterns and schemas
├── prompt_templates.py        # Specialized prompts
├── validation_helpers.py      # Configuration validation
├── mcp_integration.py         # MCP client wrapper
├── examples/                  # Usage examples
│   ├── dashboard_creation.py
│   ├── debugging_session.py
│   └── code_optimization.py
└── tests/                     # Test suite
    └── test_agent_capabilities.py
```

## Core Components

### Agent Core (`agent_core.py`)

Main agent orchestration with four modes:

```python
from agent_core import create_dashboard_from_text, debug_vizro_code

# Create dashboard
result = await create_dashboard_from_text(
    "Show sales trends over time",
    "sales_data.csv"
)

# Debug code
result = await debug_vizro_code(
    code="page = vm.Page(title='Test')",
    error="components field required"
)
```

### Knowledge Base (`vizro_knowledge_base.py`)

Structured Vizro knowledge including:
- Model schemas and parameters
- Common issues and solutions
- Best practices
- Code patterns
- Teaching materials

```python
from vizro_knowledge_base import VizroKnowledgeBase

kb = VizroKnowledgeBase()

# Find solution for error
issue = kb.find_matching_issue("field required")
print(issue.solution)

# Get concept explanation
concept = kb.get_concept_info("filters")
print(concept.description)

# Get code pattern
pattern = kb.get_pattern("basic_dashboard")
```

### MCP Integration (`mcp_integration.py`)

Client wrapper for vizro-mcp server:

```python
from mcp_integration import VizroMCPClient

client = VizroMCPClient()

# Get sample data info
data_info = await client.get_sample_data_info("iris")

# Validate dashboard
result = await client.validate_dashboard(
    config=dashboard_config,
    data_infos=[data_info],
    custom_charts=[]
)
```

### Validation Helpers (`validation_helpers.py`)

Configuration validation utilities:

```python
from validation_helpers import VizroValidator

validator = VizroValidator(mcp_client)

# Check required fields
missing = await validator.check_required_fields(config, "Page")

# Validate full configuration
is_valid, message, details = await validator.validate_dashboard_config(
    config, data_infos, custom_charts
)
```

## Examples

### Dashboard Creation

```python
from agent_core import VizroAgent, AgentContext, AgentMode

agent = VizroAgent()

context = AgentContext(
    mode=AgentMode.CREATION,
    user_request="""
    Create a dashboard with:
    - Scatter plot of sepal length vs width
    - Bar chart of average petal length by species
    - Data table
    - Species filter
    """,
    data_source="iris"
)

result = await agent.process_request(context)
print(f"PyCafe Link: {result.pycafe_link}")
```

### Debugging

```python
from agent_core import debug_vizro_code

buggy_code = """
page = vm.Page(title="My Page")
"""

error = "ValidationError: components field required"

result = await debug_vizro_code(buggy_code, error)
print(f"Fixed Code:\n{result.code}")
print(f"Explanation:\n{result.explanation}")
```

### Optimization

```python
from agent_core import optimize_vizro_dashboard

unoptimized = """
@data_manager.add_data("sales")
def load_data():
    return pd.read_csv("large_file.csv")  # No caching
"""

result = await optimize_vizro_dashboard(
    unoptimized,
    focus_areas=["data_loading"]
)
print(f"Optimized:\n{result.code}")
print(f"Improvements: {result.suggestions}")
```

### Teaching

```python
from agent_core import learn_vizro_concept

result = await learn_vizro_concept("filters")
print(result.explanation)
print(f"Examples:\n{result.code}")
```

## Running Examples

```bash
# Dashboard creation examples
cd examples
python dashboard_creation.py

# Debugging examples
python debugging_session.py

# Optimization examples
python code_optimization.py
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test class
pytest tests/test_agent_capabilities.py::TestAgentCore -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html
```

## Agent Capabilities

### 1. Dashboard Creation

**Features:**
- Natural language to Vizro config
- Automatic data analysis
- Component selection based on data types
- Filter and parameter configuration
- Layout optimization
- Validation and PyCafe link generation

**Example:**
```
User: "Create a time series dashboard with date filters"

Agent:
1. Analyzes data structure
2. Identifies temporal columns
3. Selects line chart visualization
4. Configures date filter
5. Validates configuration
6. Returns code + PyCafe link
```

### 2. Debugging

**Features:**
- Error classification
- Root cause analysis
- Known issue matching
- Fix generation
- Validation of fixes
- Prevention tips

**Common Issues Handled:**
- Missing required fields
- Type mismatches
- Reference errors (data, components)
- Callback conflicts (duplicate IDs)
- Column not found
- Target component not found

### 3. Optimization

**Features:**
- Performance bottleneck identification
- Best practice enforcement
- Code quality improvements
- Quantified improvement estimates

**Focus Areas:**
- Data loading (caching, pre-filtering)
- Component selection (AgGrid vs Table)
- Layout optimization
- Callback performance
- Production readiness

### 4. Teaching

**Features:**
- Concept explanations
- Code examples
- Best practices
- Common mistakes
- Related topics

**Topics Covered:**
- Filters, Parameters
- Layouts (Grid, Flex)
- Custom charts
- Data manager
- Actions
- Navigation

## Advanced Usage

### Custom MCP Integration

```python
from mcp_integration import VizroMCPClient

class CustomMCPClient(VizroMCPClient):
    async def call_tool(self, tool_name, parameters):
        # Custom MCP communication logic
        result = await your_mcp_call(tool_name, parameters)
        return result

# Use custom client
agent = VizroAgent()
agent.mcp_client = CustomMCPClient()
```

### Extending Knowledge Base

```python
from vizro_knowledge_base import VizroKnowledgeBase, CommonIssue

class CustomKnowledgeBase(VizroKnowledgeBase):
    def __init__(self):
        super().__init__()

        # Add custom issues
        self.common_issues.append(
            CommonIssue(
                pattern="custom error pattern",
                description="Custom error description",
                solution="Custom solution",
                code_example="# Example code",
                category="custom"
            )
        )

# Use custom knowledge base
agent = VizroAgent()
agent.knowledge_base = CustomKnowledgeBase()
```

### Custom Prompts

```python
from prompt_templates import VizroPromptTemplates

class CustomPrompts(VizroPromptTemplates):
    SYSTEM_CREATION = """
    Custom system prompt for dashboard creation...
    """

# Use custom prompts
agent = VizroAgent()
agent.prompts = CustomPrompts()
```

## Best Practices

### For Dashboard Creation

✅ **DO:**
- Always validate configurations
- Use vizro-mcp tools
- Provide PyCafe links
- Explain design decisions

❌ **DON'T:**
- Skip validation step
- Generate invalid configurations
- Assume data structure

### For Debugging

✅ **DO:**
- Classify error types
- Check known issues first
- Validate fixes
- Explain root causes

❌ **DON'T:**
- Provide vague solutions
- Skip validation
- Ignore prevention tips

### For Optimization

✅ **DO:**
- Identify specific bottlenecks
- Quantify improvements
- Follow best practices
- Validate optimized code

❌ **DON'T:**
- Apply unnecessary optimizations
- Break functionality
- Skip testing

## Troubleshooting

### MCP Server Not Connected

```bash
# Check MCP configuration
cat ~/Library/Application\ Support/Claude/claude_desktop_config.json

# Verify vizro-mcp is installed
uvx vizro-mcp --version

# Restart Claude Desktop
```

### Import Errors

```bash
# Ensure all dependencies installed
pip install vizro pydantic anthropic

# Check Python path
python -c "import vizro; print(vizro.__version__)"
```

### Validation Fails

```python
# Check MCP tools are available
client = VizroMCPClient()
print(client.list_available_tools())

# Verify configuration format
print(json.dumps(config, indent=2))
```

## Resources

### Documentation

- **Vizro Docs**: https://vizro.readthedocs.io
- **Vizro-MCP**: https://github.com/mckinsey/vizro
- **MCP Protocol**: https://modelcontextprotocol.io
- **Tutorial**: See `docs/tutorials/vizro-agent-tutorial.md`

### Examples

- Dashboard creation: `examples/dashboard_creation.py`
- Debugging: `examples/debugging_session.py`
- Optimization: `examples/code_optimization.py`

### Community

- **GitHub Issues**: Report bugs and request features
- **Plotly Forum**: Community support
- **Documentation**: Comprehensive guides and references

## Contributing

Contributions welcome! Areas for enhancement:

1. **Knowledge Base**: Add more patterns and issues
2. **Validation**: Improve error detection
3. **Optimization**: Add more optimization strategies
4. **Testing**: Expand test coverage
5. **Examples**: More real-world scenarios

## License

This project follows the Depictio project license.

## Acknowledgments

- **Vizro**: McKinsey's excellent dashboard framework
- **Anthropic**: Claude and Model Context Protocol
- **Community**: Vizro users and contributors

---

**Built with ❤️ for the Vizro community**
