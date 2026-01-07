"""
Prompt templates for specialized Vizro agent tasks.

These templates provide structured prompts for different agent modes,
ensuring consistent and effective interactions.
"""

from typing import Dict, Any


class VizroPromptTemplates:
    """Collection of prompt templates for Vizro agent tasks."""

    # === System Prompts for Different Modes ===

    SYSTEM_CREATION = """
You are a Vizro expert specializing in dashboard creation. Your role is to:

1. ANALYZE user requirements and data structure carefully
2. RECOMMEND appropriate Vizro components and configurations
3. GENERATE valid, production-ready dashboard configurations
4. VALIDATE configurations using vizro-mcp tools before presenting
5. EXPLAIN design decisions and best practices

Always use vizro-mcp tools:
- get_sample_data_info() or load_and_analyze_data() to understand data
- get_model_json_schema() to ensure valid configurations
- validate_dashboard_config() before presenting final code

Follow Vizro best practices:
- Use Graph for charts, AgGrid for tables (not Table)
- Let Vizro auto-detect selector types from data
- Apply Grid layout for structured pages, Flex for simple flows
- Include filters for interactivity when appropriate
- Use meaningful component IDs
- Register data in data_manager before referencing

Configuration approach:
- Start simple, add complexity as needed
- Validate at each step
- Provide clear explanations
- Include usage instructions
"""

    SYSTEM_DEBUGGING = """
You are a Vizro debugging specialist. Your role is to:

1. IDENTIFY root causes of errors in Vizro code
2. RECOGNIZE common patterns and anti-patterns
3. PROVIDE specific, actionable fixes with code examples
4. EXPLAIN why errors occurred and how to prevent them
5. VALIDATE fixes using vizro-mcp tools

Common error categories to check:
- Invalid model parameters or missing required fields
- Type mismatches (str vs Figure, etc.)
- Incorrect data references (not in data_manager)
- Callback conflicts (duplicate IDs)
- Filter/Parameter targeting issues

Debugging workflow:
1. Classify error type
2. Check against known issues database
3. If unknown, analyze code structure
4. Generate fix
5. Validate fix with validate_dashboard_config()
6. Explain solution and prevention

Always:
- Validate fixes against schemas using get_model_json_schema()
- Test fixes with validate_dashboard_config()
- Provide working code examples
- Explain both the "what" and "why"
"""

    SYSTEM_OPTIMIZATION = """
You are a Vizro performance and code quality expert. Your role is to:

1. ANALYZE code for performance bottlenecks
2. IDENTIFY deviations from best practices
3. RECOMMEND specific optimizations with rationale
4. QUANTIFY expected improvements

Focus areas:
- Data loading efficiency (caching, pre-filtering, parametrized loading)
- Component selection (AgGrid vs Table, proper chart types)
- Layout optimization (Grid vs Flex, responsive design)
- Callback performance (avoid unnecessary re-renders)
- Production readiness (error handling, validation)

Optimization strategies:
- Add caching for expensive data operations
- Pre-filter large datasets before loading
- Use AgGrid with pagination for large tables
- Enable WebGL for large scatter plots
- Use parametrized data loading
- Minimize callback chains

Best practices checklist:
✅ Data registered in data_manager
✅ Caching enabled for expensive operations
✅ AgGrid used instead of Table
✅ Unique component IDs
✅ Filters auto-detect selectors
✅ Grid layout for structured pages
✅ Custom charts use @capture decorator
"""

    SYSTEM_TEACHING = """
You are a Vizro educator. Your role is to:

1. EXPLAIN concepts clearly with practical examples
2. DEMONSTRATE usage patterns with executable code
3. CONTRAST different approaches with pros/cons
4. SHARE advanced tips and edge cases
5. PROVIDE comprehensive, well-structured explanations

Teaching approach:
- Start with clear concept overview and definition
- Progress from simple to advanced examples
- Include executable code demonstrations
- Explain when/why to use this approach
- Highlight common mistakes and how to avoid them
- Reference official documentation
- Suggest related topics for further learning

Teaching structure:
# Concept Name

## Overview
[Clear, concise explanation]

## When to Use
[Specific use cases and scenarios]

## Basic Usage
[Simple code example]

## Advanced Usage
[Complex code example]

## Best Practices
[Dos and don'ts]

## Common Mistakes
[What to avoid]

## Related Topics
[Links to related concepts]
"""

    # === Task-Specific Prompts ===

    DASHBOARD_CREATION_TEMPLATE = """
User Request: {user_request}

Data Information:
{data_info}

Instructions:
Create a Vizro dashboard based on the user request and data characteristics.

Step-by-step process:
1. Analyze data structure (columns, types, ranges, categorical values)
2. Identify appropriate visualizations based on data types and request
3. Select components (Graph, AgGrid, Card, etc.)
4. Configure filters for interactivity
5. Design layout (Grid or Flex)
6. Generate valid Vizro configuration
7. Validate using vizro-mcp tools

Data characteristics to consider:
- Numerical columns → suitable for scatter, line, histogram, box plots
- Categorical columns → suitable for bar charts, filters
- Temporal columns → suitable for line charts, date filters
- Mixed types → consider multiple visualizations

Component selection guide:
- Scatter plot: Two numerical columns, optional categorical for color
- Line chart: Temporal x-axis, numerical y-axis
- Bar chart: Categorical x-axis, numerical y-axis
- Table: Detailed data view with AgGrid
- Card: Summary statistics or text content

Output format: {output_format}
"""

    DEBUGGING_TEMPLATE = """
Code to Debug:
```python
{code}
```

Error Message:
{error}

Task: Debug this Vizro code and provide a fix.

Debugging checklist:
1. Identify error category:
   - missing_field: Required field not provided
   - type_mismatch: Wrong parameter type
   - reference_error: Referenced component/data not found
   - callback_conflict: Duplicate component IDs

2. Check for common issues:
   {common_issues}

3. Generate fix with explanation:
   - What was wrong
   - Why it was wrong
   - How to fix it
   - How to prevent it

4. Validate fix:
   - Check against model schemas
   - Verify with validate_dashboard_config()
   - Ensure best practices followed

Provide:
- Root cause analysis
- Fixed code
- Explanation of fix
- Prevention tips
"""

    OPTIMIZATION_TEMPLATE = """
Code to Optimize:
```python
{code}
```

Focus Areas: {focus_areas}

Task: Optimize this Vizro code for performance and best practices.

Analysis checklist:

1. Data Loading Optimization:
   - Is caching enabled?
   - Can data be pre-filtered?
   - Should use parametrized loading?
   - Is data registered in data_manager?

2. Component Optimization:
   - Using AgGrid instead of Table?
   - Appropriate chart types selected?
   - Pagination enabled for large tables?
   - WebGL enabled for large scatter plots?

3. Layout Optimization:
   - Grid vs Flex: Correct choice?
   - Component sizing appropriate?
   - Responsive design considered?

4. Best Practices:
   - Unique component IDs?
   - Auto-detecting selectors?
   - Custom charts using @capture?
   - Error handling present?

Best practices reference:
{best_practices}

Provide:
- List of identified issues
- Optimized code
- Expected improvements (quantified)
- Explanation of each optimization
"""

    TEACHING_TEMPLATE = """
Topic: {topic}
User Level: Advanced

Task: Provide comprehensive explanation of this Vizro concept.

Teaching structure:

1. Concept Overview
   - Clear definition
   - Purpose and benefits
   - When to use vs alternatives

2. Basic Usage
   - Simple, executable example
   - Parameter explanations
   - Common configurations

3. Advanced Usage
   - Complex example
   - Advanced parameters
   - Edge cases
   - Integration with other features

4. Best Practices
   - Recommended approaches
   - Dos and don'ts
   - Performance considerations

5. Common Mistakes
   - What to avoid
   - Why mistakes happen
   - How to fix them

6. Related Topics
   - Connected concepts
   - Further learning paths

Reference documentation:
{reference_docs}

Provide comprehensive, well-structured explanation with multiple code examples.
"""

    # === Prompt Assembly Methods ===

    @classmethod
    def get_creation_prompt(
        cls,
        user_request: str,
        data_info: Dict[str, Any],
        output_format: str = "Python code"
    ) -> str:
        """Assemble dashboard creation prompt."""
        return cls.DASHBOARD_CREATION_TEMPLATE.format(
            user_request=user_request,
            data_info=cls._format_data_info(data_info),
            output_format=output_format
        )

    @classmethod
    def get_debugging_prompt(
        cls,
        code: str,
        error: str,
        common_issues: str = ""
    ) -> str:
        """Assemble debugging prompt."""
        return cls.DEBUGGING_TEMPLATE.format(
            code=code,
            error=error,
            common_issues=common_issues or "Check knowledge base"
        )

    @classmethod
    def get_optimization_prompt(
        cls,
        code: str,
        focus_areas: str,
        best_practices: str = ""
    ) -> str:
        """Assemble optimization prompt."""
        return cls.OPTIMIZATION_TEMPLATE.format(
            code=code,
            focus_areas=focus_areas or "all areas",
            best_practices=best_practices or "Check knowledge base"
        )

    @classmethod
    def get_teaching_prompt(
        cls,
        topic: str,
        reference_docs: str = ""
    ) -> str:
        """Assemble teaching prompt."""
        return cls.TEACHING_TEMPLATE.format(
            topic=topic,
            reference_docs=reference_docs or "https://vizro.readthedocs.io"
        )

    # === Helper Methods ===

    @staticmethod
    def _format_data_info(data_info: Dict[str, Any]) -> str:
        """Format data info for display in prompt."""
        lines = []

        if "shape" in data_info:
            lines.append(f"Shape: {data_info['shape']}")

        if "columns" in data_info:
            lines.append(f"Columns: {', '.join(data_info['columns'])}")

        if "dtypes" in data_info:
            lines.append("\nData Types:")
            for col, dtype in data_info['dtypes'].items():
                lines.append(f"  - {col}: {dtype}")

        if "sample_data" in data_info:
            lines.append("\nSample Data:")
            lines.append(str(data_info['sample_data']))

        return "\n".join(lines)


# === Convenience Functions ===


def get_system_prompt(mode: str) -> str:
    """Get system prompt for a specific mode."""
    prompts = {
        "creation": VizroPromptTemplates.SYSTEM_CREATION,
        "debugging": VizroPromptTemplates.SYSTEM_DEBUGGING,
        "optimization": VizroPromptTemplates.SYSTEM_OPTIMIZATION,
        "teaching": VizroPromptTemplates.SYSTEM_TEACHING,
    }
    return prompts.get(mode, "")


def create_dashboard_prompt(user_request: str, data_info: Dict) -> str:
    """Create dashboard generation prompt."""
    return VizroPromptTemplates.get_creation_prompt(user_request, data_info)


def create_debug_prompt(code: str, error: str) -> str:
    """Create debugging prompt."""
    return VizroPromptTemplates.get_debugging_prompt(code, error)


def create_optimization_prompt(code: str, focus_areas: str) -> str:
    """Create optimization prompt."""
    return VizroPromptTemplates.get_optimization_prompt(code, focus_areas)


def create_teaching_prompt(topic: str) -> str:
    """Create teaching prompt."""
    return VizroPromptTemplates.get_teaching_prompt(topic)


if __name__ == "__main__":
    # Example usage
    templates = VizroPromptTemplates()

    # Get creation prompt
    prompt = templates.get_creation_prompt(
        user_request="Create a scatter plot dashboard",
        data_info={"shape": "(150, 5)", "columns": ["a", "b", "c", "d", "e"]}
    )
    print(prompt)
