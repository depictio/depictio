"""
Comprehensive Vizro knowledge base for the Claude agent.

This module contains structured information about Vizro models, patterns,
common issues, best practices, and examples.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class VizroModel:
    """Represents a Vizro model with its schema information."""

    name: str
    description: str
    required_fields: List[str]
    optional_fields: Dict[str, Any]
    examples: List[Dict[str, Any]]
    category: str  # structure, component, control, selector, action


@dataclass
class CommonIssue:
    """Represents a common Vizro issue with solution."""

    pattern: str
    description: str
    solution: str
    code_example: str
    category: str


@dataclass
class BestPractice:
    """Represents a Vizro best practice."""

    category: str
    title: str
    description: str
    example_good: str
    example_bad: str


@dataclass
class ConceptInfo:
    """Information about a Vizro concept for teaching."""

    name: str
    description: str
    use_cases: str
    best_practices: str
    common_mistakes: str
    related_topics: List[str]


class VizroKnowledgeBase:
    """Central repository of Vizro knowledge for the agent."""

    def __init__(self):
        """Initialize the knowledge base with all Vizro information."""
        self._initialize_models()
        self._initialize_common_issues()
        self._initialize_best_practices()
        self._initialize_concepts()
        self._initialize_patterns()

    # === Model Definitions ===

    def _initialize_models(self):
        """Initialize Vizro model definitions."""
        self.models = {
            "Dashboard": VizroModel(
                name="Dashboard",
                description="Top-level container for entire dashboard",
                required_fields=["pages"],
                optional_fields={
                    "title": "str - Dashboard title",
                    "theme": "str - vizro_dark or vizro_light",
                    "navigation": "Navigation - Page navigation config",
                },
                examples=[
                    {
                        "description": "Simple dashboard",
                        "code": """vm.Dashboard(pages=[page1, page2])""",
                    },
                    {
                        "description": "Dashboard with theme",
                        "code": """vm.Dashboard(
    pages=[page1, page2],
    theme="vizro_dark"
)""",
                    },
                ],
                category="structure",
            ),
            "Page": VizroModel(
                name="Page",
                description="Individual dashboard page",
                required_fields=["components"],
                optional_fields={
                    "id": "str - Unique identifier",
                    "title": "str - Page title",
                    "controls": "List[Filter|Parameter] - Interactive controls",
                    "layout": "Layout - Grid or Flex layout",
                },
                examples=[
                    {
                        "description": "Basic page",
                        "code": """vm.Page(
    title="My Page",
    components=[
        vm.Graph(figure=px.scatter(...))
    ]
)""",
                    },
                    {
                        "description": "Page with filters",
                        "code": """vm.Page(
    title="Filtered View",
    components=[vm.Graph(...)],
    controls=[vm.Filter(column="category")]
)""",
                    },
                ],
                category="structure",
            ),
            "Graph": VizroModel(
                name="Graph",
                description="Plotly chart visualization",
                required_fields=["figure"],
                optional_fields={
                    "id": "str - Unique identifier",
                    "actions": "List[Action] - Interactive actions",
                },
                examples=[
                    {
                        "description": "Scatter plot",
                        "code": """vm.Graph(
    figure=px.scatter(
        df, x="col1", y="col2", color="col3"
    )
)""",
                    },
                    {
                        "description": "Custom chart",
                        "code": """@capture("graph")
def custom_chart(data_frame, x, y):
    fig = go.Figure()
    fig.add_trace(go.Scatter(...))
    return fig

vm.Graph(figure=custom_chart(data_frame=df, x="a", y="b"))""",
                    },
                ],
                category="component",
            ),
            "AgGrid": VizroModel(
                name="AgGrid",
                description="AG Grid table component (recommended for tables)",
                required_fields=["figure"],
                optional_fields={
                    "id": "str - Unique identifier",
                    "actions": "List[Action] - Interactive actions",
                },
                examples=[
                    {
                        "description": "Basic table",
                        "code": """vm.AgGrid(
    figure=dash_ag_grid(data_frame=df)
)""",
                    },
                    {
                        "description": "Table with pagination",
                        "code": """vm.AgGrid(
    figure=dash_ag_grid(
        data_frame=df,
        pagination=True,
        paginationPageSize=50
    )
)""",
                    },
                ],
                category="component",
            ),
            "Filter": VizroModel(
                name="Filter",
                description="Data subset selection control",
                required_fields=["column"],
                optional_fields={
                    "targets": "List[str] - Component IDs to filter",
                    "selector": "Selector - Custom selector (auto-detected if omitted)",
                },
                examples=[
                    {
                        "description": "Auto-detected filter",
                        "code": """vm.Filter(column="category")""",
                    },
                    {
                        "description": "Targeted filter",
                        "code": """vm.Filter(
    column="species",
    targets=["graph1", "table1"]
)""",
                    },
                    {
                        "description": "Custom selector",
                        "code": """vm.Filter(
    column="species",
    selector=vm.RadioItems(
        options=["setosa", "versicolor"]
    )
)""",
                    },
                ],
                category="control",
            ),
            "Parameter": VizroModel(
                name="Parameter",
                description="Function argument modification control",
                required_fields=["targets", "selector"],
                optional_fields={},
                examples=[
                    {
                        "description": "Modify chart axis",
                        "code": """vm.Parameter(
    targets=["graph.x", "graph.y"],
    selector=vm.Dropdown(
        options=["col1", "col2", "col3"]
    )
)""",
                    },
                    {
                        "description": "Modify data parameter",
                        "code": """vm.Parameter(
    targets=["filtered_data.category"],
    selector=vm.RadioItems(
        options=["A", "B", "C"]
    )
)""",
                    },
                ],
                category="control",
            ),
        }

    # === Common Issues ===

    def _initialize_common_issues(self):
        """Initialize common Vizro issues and solutions."""
        self.common_issues = [
            CommonIssue(
                pattern="field required|missing",
                description="Missing required field in model",
                solution="Add the required field with appropriate value",
                code_example="""# WRONG
page = vm.Page(title="My Page")

# CORRECT
page = vm.Page(title="My Page", components=[])""",
                category="validation",
            ),
            CommonIssue(
                pattern="duplicate.*id|callback.*conflict",
                description="Duplicate component IDs causing callback conflicts",
                solution="Ensure all component IDs are unique",
                code_example="""# WRONG
vm.Graph(id="chart", ...),
vm.Graph(id="chart", ...)

# CORRECT
vm.Graph(id="scatter_plot", ...),
vm.Graph(id="line_chart", ...)""",
                category="callbacks",
            ),
            CommonIssue(
                pattern="KeyError.*data_manager|not found.*data",
                description="Referenced data not registered in data_manager",
                solution="Register data before referencing",
                code_example="""# Register first
data_manager["my_data"] = df

# Then reference
vm.Graph(figure=px.scatter(data_frame="my_data", ...))""",
                category="data",
            ),
            CommonIssue(
                pattern="type.*error|is not.*valid",
                description="Type mismatch in model parameters",
                solution="Ensure parameter types match schema",
                code_example="""# WRONG
vm.Graph(figure="my_chart")  # String

# CORRECT
vm.Graph(figure=px.scatter(...))  # Figure object""",
                category="validation",
            ),
            CommonIssue(
                pattern="target.*not found|unknown.*component",
                description="Filter/Parameter targeting non-existent component",
                solution="Ensure target IDs match component IDs",
                code_example="""# Component with ID
vm.Graph(id="scatter_plot", ...)

# Filter targeting it
vm.Filter(column="species", targets=["scatter_plot"])""",
                category="references",
            ),
            CommonIssue(
                pattern="column.*not found|KeyError.*column",
                description="Filter referencing non-existent column",
                solution="Verify column name exists in DataFrame",
                code_example="""# Check DataFrame columns first
print(df.columns)

# Then use correct column name
vm.Filter(column="actual_column_name")""",
                category="data",
            ),
            CommonIssue(
                pattern="figure.*must be.*function",
                description="Using raw data instead of chart function",
                solution="Use Plotly Express or custom chart function",
                code_example="""# WRONG
vm.Graph(figure=df)

# CORRECT
vm.Graph(figure=px.scatter(df, x="x", y="y"))""",
                category="components",
            ),
            CommonIssue(
                pattern="capture.*decorator|not captured",
                description="Custom function not decorated with @capture",
                solution="Add @capture decorator with appropriate mode",
                code_example="""# Add decorator
@capture("graph")
def custom_chart(data_frame, x, y):
    return go.Figure(...)

# Use in Graph
vm.Graph(figure=custom_chart(data_frame=df, x="a", y="b"))""",
                category="customization",
            ),
        ]

    # === Best Practices ===

    def _initialize_best_practices(self):
        """Initialize Vizro best practices."""
        self.best_practices = {
            "data_loading": [
                BestPractice(
                    category="data_loading",
                    title="Use caching for expensive data operations",
                    description="Add caching to data loading functions to improve performance",
                    example_good="""from flask_caching import Cache
cache = Cache(config={"CACHE_TYPE": "SimpleCache"})

@data_manager.add_data("large_data")
@cache.memoize(timeout=600)
def load_data():
    return pd.read_csv("large_file.csv")""",
                    example_bad="""@data_manager.add_data("large_data")
def load_data():
    return pd.read_csv("large_file.csv")  # No caching""",
                ),
                BestPractice(
                    category="data_loading",
                    title="Pre-filter large datasets",
                    description="Filter data before loading to reduce memory usage",
                    example_good="""@data_manager.add_data("filtered_data")
def load_data(category="A"):
    df = pd.read_csv("data.csv")
    return df[df["category"] == category]""",
                    example_bad="""@data_manager.add_data("all_data")
def load_data():
    return pd.read_csv("large_file.csv")  # Loads everything""",
                ),
            ],
            "components": [
                BestPractice(
                    category="components",
                    title="Use AgGrid instead of Table",
                    description="AgGrid provides better performance and features",
                    example_good="""vm.AgGrid(
    figure=dash_ag_grid(
        data_frame=df,
        pagination=True
    )
)""",
                    example_bad="""vm.Table(
    figure=dash_data_table(data_frame=df)
)""",
                ),
                BestPractice(
                    category="components",
                    title="Use meaningful component IDs",
                    description="Descriptive IDs improve code maintainability",
                    example_good="""vm.Graph(id="sales_scatter_plot", ...)
vm.Graph(id="revenue_line_chart", ...)""",
                    example_bad="""vm.Graph(id="g1", ...)
vm.Graph(id="g2", ...)""",
                ),
            ],
            "filters": [
                BestPractice(
                    category="filters",
                    title="Let Vizro auto-detect selectors",
                    description="Auto-detection chooses appropriate selector types",
                    example_good="""vm.Filter(column="category")  # Auto-detects Dropdown""",
                    example_bad="""vm.Filter(
    column="category",
    selector=vm.Dropdown(...)  # Manual when not needed
)""",
                ),
                BestPractice(
                    category="filters",
                    title="Target filters only when necessary",
                    description="By default, filters apply to all components",
                    example_good="""# Applies to all components
vm.Filter(column="species")""",
                    example_bad="""# Unnecessary targeting
vm.Filter(
    column="species",
    targets=["graph1", "graph2", "table1"]
)""",
                ),
            ],
            "layout": [
                BestPractice(
                    category="layout",
                    title="Use Grid for structured layouts",
                    description="Grid provides precise control over component placement",
                    example_good="""vm.Layout(
    grid=[
        [0, 1],  # Row 1
        [2, 2],  # Row 2
    ]
)""",
                    example_bad="""# Using Flex when Grid is more appropriate
vm.Flex(direction="row")""",
                ),
            ],
            "customization": [
                BestPractice(
                    category="customization",
                    title="Use @capture decorator for custom charts",
                    description="Decorated functions integrate seamlessly with Vizro",
                    example_good="""@capture("graph")
def custom_chart(data_frame, x, y):
    fig = go.Figure()
    # Custom logic
    return fig""",
                    example_bad="""def custom_chart(x, y):  # No decorator, no data_frame
    fig = go.Figure()
    return fig""",
                ),
            ],
        }

    # === Concepts ===

    def _initialize_concepts(self):
        """Initialize Vizro concept information for teaching."""
        self.concepts = {
            "filters": ConceptInfo(
                name="Filters",
                description="Filters enable users to subset data displayed in components. They automatically detect the appropriate selector based on column data type.",
                use_cases="""
Use filters when you need to:
- Allow users to filter data by categories
- Enable date range selection
- Provide numerical range filtering
- Create interactive data exploration experiences
""",
                best_practices="""
- Let Vizro auto-detect selector types
- Use meaningful column names (visible in UI)
- Group related filters together
- Target specific components only when needed
""",
                common_mistakes="""
- Filtering on ID columns (not user-friendly)
- Creating too many filters (overwhelming)
- Using filters for non-data modifications (use Parameters)
- Forgetting to register data in data_manager
""",
                related_topics=["parameters", "selectors", "actions"],
            ),
            "parameters": ConceptInfo(
                name="Parameters",
                description="Parameters modify function arguments, enabling users to change chart properties, data loading parameters, and other configuration options.",
                use_cases="""
Use parameters when you need to:
- Switch chart axes dynamically
- Modify chart colors or properties
- Change data loading parameters
- Toggle between different data views
""",
                best_practices="""
- Use dot notation for targeting (component.field)
- Provide clear selector options
- Use RadioItems for single-select
- Use Dropdown for multi-option selection
""",
                common_mistakes="""
- Using parameters for data filtering (use Filters)
- Incorrect target paths
- Missing selector configuration
- Not matching selector options to function parameters
""",
                related_topics=["filters", "selectors", "dynamic_data"],
            ),
            "layouts": ConceptInfo(
                name="Layouts",
                description="Layouts control how components are arranged on a page. Vizro supports Grid (explicit positioning) and Flex (flow-based) layouts.",
                use_cases="""
Use Grid when:
- You need precise control over positioning
- Creating dashboard-style layouts
- Components should align in rows/columns

Use Flex when:
- Components should flow naturally
- Responsive behavior is important
- Simpler layout requirements
""",
                best_practices="""
- Use Grid for complex dashboards
- Use Flex for simple linear layouts
- Set minimum sizes for components
- Test layouts at different screen sizes
""",
                common_mistakes="""
- Using Flex when Grid is more appropriate
- Not setting minimum dimensions
- Overcomplicated grid structures
- Forgetting responsive design considerations
""",
                related_topics=["pages", "containers", "responsive_design"],
            ),
            "custom_charts": ConceptInfo(
                name="Custom Charts",
                description="Custom charts extend Vizro with custom Plotly visualizations using the @capture decorator.",
                use_cases="""
Create custom charts when:
- Standard Plotly Express charts don't meet needs
- Requiring complex data transformations
- Building reusable chart templates
- Implementing custom interactivity
""",
                best_practices="""
- Use @capture("graph") decorator
- Accept data_frame as first argument
- Return plotly.graph_objects.Figure
- Perform all data manipulation within function
- Document parameters clearly
""",
                common_mistakes="""
- Forgetting @capture decorator
- Not accepting data_frame parameter
- Returning wrong type (not Figure)
- Modifying global state
- Hardcoding data instead of using data_frame
""",
                related_topics=["components", "plotly", "data_manager"],
            ),
            "data_manager": ConceptInfo(
                name="Data Manager",
                description="The data_manager handles both static and dynamic data for Vizro dashboards.",
                use_cases="""
Use static data for:
- Fixed datasets that don't change
- Sample/demo data
- Configuration data

Use dynamic data for:
- Database queries
- API calls
- Time-based data
- User-specific data
""",
                best_practices="""
- Register data before referencing
- Use caching for expensive operations
- Pre-filter large datasets
- Use parametrized data for flexibility
- Choose meaningful data names
""",
                common_mistakes="""
- Not registering data before use
- Loading too much data at once
- No caching for expensive operations
- Inconsistent DataFrame schemas in dynamic data
- Forgetting error handling in data functions
""",
                related_topics=["caching", "performance", "parameters"],
            ),
        }

    # === Patterns ===

    def _initialize_patterns(self):
        """Initialize common Vizro patterns."""
        self.patterns = {
            "basic_dashboard": """
import vizro.plotly.express as px
from vizro import Vizro
import vizro.models as vm

df = px.data.iris()

page = vm.Page(
    title="Iris Analysis",
    components=[
        vm.Graph(figure=px.scatter(df, x="sepal_length", y="petal_width", color="species")),
    ],
    controls=[vm.Filter(column="species")],
)

dashboard = vm.Dashboard(pages=[page])
Vizro().build(dashboard).run()
""",
            "multi_page_dashboard": """
page1 = vm.Page(
    title="Overview",
    components=[
        vm.Card(text="# Dashboard Overview"),
        vm.Graph(figure=px.bar(...)),
    ],
)

page2 = vm.Page(
    title="Details",
    components=[
        vm.AgGrid(figure=dash_ag_grid(data_frame=df)),
        vm.Graph(figure=px.scatter(...)),
    ],
    controls=[vm.Filter(column="category")],
)

dashboard = vm.Dashboard(
    pages=[page1, page2],
    navigation=vm.Navigation(
        nav_selector=vm.NavBar(
            items=[
                vm.NavLink(label="Summary", pages=["Overview"], icon="Home"),
                vm.NavLink(label="Data", pages=["Details"], icon="Table"),
            ]
        )
    ),
)
""",
            "custom_chart": """
from vizro.models.types import capture
import plotly.graph_objects as go

@capture("graph")
def custom_heatmap(data_frame, x, y, z):
    # Data manipulation
    pivot = data_frame.pivot_table(values=z, index=y, columns=x)

    # Create figure
    fig = go.Figure()
    fig.add_trace(
        go.Heatmap(
            x=pivot.columns,
            y=pivot.index,
            z=pivot.values,
            colorscale="Viridis",
        )
    )
    fig.update_layout(title="Custom Heatmap")

    return fig

# Use in dashboard
vm.Graph(figure=custom_heatmap(data_frame=df, x="col1", y="col2", z="col3"))
""",
            "cached_data": """
from flask_caching import Cache
from vizro.managers import data_manager

cache = Cache(config={"CACHE_TYPE": "SimpleCache"})

@data_manager.add_data("cached_data")
@cache.memoize(timeout=600)
def load_data():
    # Expensive operation
    df = pd.read_csv("large_file.csv")
    return df
""",
            "parametrized_data": """
@data_manager.add_data("filtered_data")
def load_data(region="All", year=2023):
    df = pd.read_csv("data.csv")

    if region != "All":
        df = df[df["region"] == region]

    df = df[df["year"] == year]

    return df

# Control with parameters
page = vm.Page(
    components=[vm.Graph(figure=px.line(data_frame="filtered_data", ...))],
    controls=[
        vm.Parameter(
            targets=["filtered_data.region"],
            selector=vm.Dropdown(options=["All", "North", "South"]),
        ),
        vm.Parameter(
            targets=["filtered_data.year"],
            selector=vm.Slider(min=2020, max=2025, value=2023),
        ),
    ],
)
""",
            "cross_filtering": """
import vizro.actions as va

page = vm.Page(
    components=[
        vm.Graph(
            id="source_chart",
            figure=px.scatter(df, x="x", y="y", color="category"),
            actions=[
                va.set_control(
                    control="category_filter",
                    value="category"  # Use clicked data
                )
            ],
        ),
        vm.Graph(id="target_chart", figure=px.histogram(df, x="value")),
    ],
    controls=[
        vm.Filter(
            id="category_filter",
            column="category",
            targets=["target_chart"],  # Only affects target
        )
    ],
)
""",
        }

    # === Data Type Mappings ===

    DATA_TYPE_SELECTOR_MAP = {
        "categorical": "Dropdown",
        "object": "Dropdown",
        "string": "Dropdown",
        "category": "Dropdown",
        "numerical": "RangeSlider",
        "int": "RangeSlider",
        "float": "RangeSlider",
        "temporal": "DatePicker",
        "datetime": "DatePicker",
        "date": "DatePicker",
        "boolean": "Switch",
        "bool": "Switch",
    }

    # === Query Methods ===

    def get_model_info(self, model_name: str) -> Optional[VizroModel]:
        """Get information about a specific Vizro model."""
        return self.models.get(model_name)

    def get_models_by_category(self, category: str) -> List[VizroModel]:
        """Get all models in a specific category."""
        return [m for m in self.models.values() if m.category == category]

    def find_matching_issue(self, error_message: str) -> Optional[CommonIssue]:
        """Find a common issue matching the error message."""
        import re

        error_lower = error_message.lower()

        for issue in self.common_issues:
            if re.search(issue.pattern.lower(), error_lower):
                return issue

        return None

    def get_best_practices(self, category: Optional[str] = None) -> List[BestPractice]:
        """Get best practices, optionally filtered by category."""
        if category:
            return self.best_practices.get(category, [])
        else:
            # Return all best practices
            all_practices = []
            for practices_list in self.best_practices.values():
                all_practices.extend(practices_list)
            return all_practices

    def get_concept_info(self, topic: str) -> Optional[ConceptInfo]:
        """Get information about a concept for teaching."""
        return self.concepts.get(topic.lower())

    def get_available_topics(self) -> List[str]:
        """Get list of available teaching topics."""
        return list(self.concepts.keys())

    def get_related_topics(self, topic: str) -> List[str]:
        """Get related topics for a given topic."""
        concept = self.concepts.get(topic.lower())
        return concept.related_topics if concept else []

    def get_pattern(self, pattern_name: str) -> Optional[str]:
        """Get code pattern by name."""
        return self.patterns.get(pattern_name)

    def get_all_patterns(self) -> Dict[str, str]:
        """Get all available patterns."""
        return self.patterns

    def get_selector_for_dtype(self, dtype: str) -> str:
        """Get recommended selector type for a data type."""
        return self.DATA_TYPE_SELECTOR_MAP.get(dtype.lower(), "Dropdown")

    def get_examples(self, topic: str) -> List[Dict[str, Any]]:
        """Get code examples for a topic."""
        # Check if it's a model
        model = self.models.get(topic)
        if model:
            return model.examples

        # Check if it's a pattern
        pattern = self.patterns.get(topic)
        if pattern:
            return [{"title": topic, "code": pattern}]

        return []

    def search_knowledge(self, query: str) -> Dict[str, List[str]]:
        """Search across all knowledge for a query."""
        results = {"models": [], "issues": [], "practices": [], "concepts": []}

        query_lower = query.lower()

        # Search models
        for model_name, model in self.models.items():
            if query_lower in model_name.lower() or query_lower in model.description.lower():
                results["models"].append(model_name)

        # Search issues
        for issue in self.common_issues:
            if query_lower in issue.description.lower():
                results["issues"].append(issue.description)

        # Search best practices
        for practices_list in self.best_practices.values():
            for practice in practices_list:
                if query_lower in practice.title.lower():
                    results["practices"].append(practice.title)

        # Search concepts
        for concept_name, concept in self.concepts.items():
            if query_lower in concept_name or query_lower in concept.description.lower():
                results["concepts"].append(concept_name)

        return results


# === Convenience Functions ===


def get_vizro_models() -> Dict[str, VizroModel]:
    """Get all Vizro model definitions."""
    kb = VizroKnowledgeBase()
    return kb.models


def find_solution_for_error(error_message: str) -> Optional[CommonIssue]:
    """Find solution for a given error message."""
    kb = VizroKnowledgeBase()
    return kb.find_matching_issue(error_message)


def get_teaching_material(topic: str) -> Optional[ConceptInfo]:
    """Get teaching material for a topic."""
    kb = VizroKnowledgeBase()
    return kb.get_concept_info(topic)


if __name__ == "__main__":
    # Example usage
    kb = VizroKnowledgeBase()

    # Find issue solution
    issue = kb.find_matching_issue("field required")
    if issue:
        print(f"Solution: {issue.solution}")

    # Get concept info
    concept = kb.get_concept_info("filters")
    if concept:
        print(f"\n{concept.name}: {concept.description}")

    # Get pattern
    pattern = kb.get_pattern("basic_dashboard")
    print(f"\nPattern:\n{pattern}")
