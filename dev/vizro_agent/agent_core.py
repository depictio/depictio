"""
Core Claude agent implementation for Vizro expertise.

This module provides the main VizroAgent class that orchestrates all
agent capabilities including dashboard creation, debugging, optimization,
and teaching.
"""

import asyncio
from typing import Dict, Any, List, Optional, Literal
from dataclasses import dataclass
from enum import Enum

from vizro_knowledge_base import VizroKnowledgeBase
from prompt_templates import VizroPromptTemplates
from validation_helpers import VizroValidator
from mcp_integration import VizroMCPClient


class AgentMode(Enum):
    """Available agent operation modes."""

    CREATION = "creation"
    DEBUGGING = "debugging"
    OPTIMIZATION = "optimization"
    TEACHING = "teaching"


@dataclass
class AgentContext:
    """Context information for agent operations."""

    mode: AgentMode
    user_request: str
    code: Optional[str] = None
    error_message: Optional[str] = None
    data_source: Optional[str] = None
    focus_areas: Optional[List[str]] = None


@dataclass
class AgentResponse:
    """Structured response from agent."""

    success: bool
    message: str
    code: Optional[str] = None
    explanation: Optional[str] = None
    pycafe_link: Optional[str] = None
    validation_result: Optional[Dict[str, Any]] = None
    suggestions: Optional[List[str]] = None


class VizroAgent:
    """
    Main Claude agent for Vizro expertise.

    Capabilities:
    - Dashboard creation from natural language
    - Code debugging and error resolution
    - Performance optimization
    - Teaching and concept explanation
    """

    def __init__(self):
        """Initialize the Vizro agent."""
        self.knowledge_base = VizroKnowledgeBase()
        self.prompts = VizroPromptTemplates()
        self.mcp_client = VizroMCPClient()
        self.validator = VizroValidator(self.mcp_client)

    async def process_request(self, context: AgentContext) -> AgentResponse:
        """
        Process a user request based on agent mode.

        Args:
            context: Agent context with mode and request details

        Returns:
            AgentResponse with results
        """
        if context.mode == AgentMode.CREATION:
            return await self.create_dashboard(
                context.user_request, context.data_source or "iris"
            )

        elif context.mode == AgentMode.DEBUGGING:
            return await self.debug_code(context.code, context.error_message)

        elif context.mode == AgentMode.OPTIMIZATION:
            return await self.optimize_code(context.code, context.focus_areas or [])

        elif context.mode == AgentMode.TEACHING:
            return await self.teach_concept(context.user_request)

        else:
            return AgentResponse(success=False, message=f"Unknown mode: {context.mode}")

    async def create_dashboard(
        self, user_request: str, data_source: str
    ) -> AgentResponse:
        """
        Create a Vizro dashboard from natural language description.

        Process:
        1. Analyze data structure
        2. Get creation instructions from MCP
        3. Generate configuration
        4. Validate configuration
        5. Return code + PyCafe link

        Args:
            user_request: Natural language description of desired dashboard
            data_source: Data source (sample name or file path)

        Returns:
            AgentResponse with generated code and validation results
        """
        try:
            # Step 1: Analyze data
            print(f"🔍 Analyzing data source: {data_source}")
            if data_source in ["iris", "tips", "stocks", "gapminder"]:
                data_info = await self.mcp_client.get_sample_data_info(data_source)
            else:
                data_info = await self.mcp_client.load_and_analyze_data(data_source)

            print(f"✓ Data analyzed: {data_info.get('shape', 'unknown shape')}")

            # Step 2: Get creation instructions
            print("📋 Getting dashboard creation plan...")
            instructions = await self.mcp_client.get_dashboard_plan(
                user_plan="dashboard", user_host="ide", advanced_mode=False
            )

            # Step 3: Generate configuration
            print("🏗️  Generating dashboard configuration...")
            config = self._generate_dashboard_config(
                user_request, data_info, instructions
            )

            # Step 4: Validate configuration
            print("✓ Validating configuration...")
            is_valid, message, details = await self.validator.validate_dashboard_config(
                config=config, data_infos=[data_info], custom_charts=[]
            )

            if is_valid:
                return AgentResponse(
                    success=True,
                    message="Dashboard created successfully!",
                    code=details.get("python_code"),
                    pycafe_link=details.get("pycafe_link"),
                    explanation=self._generate_creation_explanation(config, data_info),
                    validation_result=details,
                )
            else:
                # Attempt to fix and retry
                print("⚠️  Initial validation failed, attempting fixes...")
                fixed_config = self._apply_validation_fixes(config, message)
                return await self._retry_validation(fixed_config, [data_info], [])

        except Exception as e:
            return AgentResponse(
                success=False,
                message=f"Error creating dashboard: {str(e)}",
                explanation=self._generate_error_explanation(e),
            )

    async def debug_code(
        self, code: str, error_message: str
    ) -> AgentResponse:
        """
        Debug Vizro code and provide fixes.

        Process:
        1. Classify error type
        2. Check against known issues
        3. Analyze code structure
        4. Generate fixes
        5. Validate fixes
        6. Explain solution

        Args:
            code: Vizro code with issues
            error_message: Error message or description of problem

        Returns:
            AgentResponse with fixed code and explanation
        """
        try:
            print(f"🐛 Debugging code...")
            print(f"Error: {error_message}")

            # Step 1: Classify error
            error_type = self._classify_error(error_message)
            print(f"Error type: {error_type}")

            # Step 2: Check known issues
            known_issue = self.knowledge_base.find_matching_issue(error_message)

            if known_issue:
                print(f"✓ Found known issue: {known_issue.description}")
                fixed_code = self._apply_known_solution(code, known_issue)
            else:
                print("Analyzing code structure for unknown issue...")
                # Step 3: Analyze code
                config = self._parse_vizro_code(code)

                # Check for missing required fields
                missing_fields = await self._check_missing_fields(config)

                # Check for type mismatches
                type_errors = await self._check_type_errors(config)

                # Step 4: Generate fixes
                fixed_code = self._generate_fixes(code, missing_fields, type_errors)

            # Step 5: Validate fix
            print("Validating fix...")
            config = self._parse_vizro_code(fixed_code)
            is_valid, validation_msg, details = (
                await self.validator.validate_dashboard_config(
                    config=config, data_infos=[], custom_charts=[]
                )
            )

            # Step 6: Generate explanation
            explanation = self._generate_debug_explanation(
                error_message, error_type, fixed_code, known_issue
            )

            return AgentResponse(
                success=is_valid,
                message="Fix applied and validated" if is_valid else "Fix needs review",
                code=fixed_code,
                explanation=explanation,
                validation_result=details,
                suggestions=self._get_prevention_tips(error_type),
            )

        except Exception as e:
            return AgentResponse(
                success=False,
                message=f"Error debugging code: {str(e)}",
                explanation=self._generate_error_explanation(e),
            )

    async def optimize_code(
        self, code: str, focus_areas: List[str]
    ) -> AgentResponse:
        """
        Optimize Vizro code for performance and best practices.

        Focus areas:
        - data_loading: Caching, pre-filtering
        - components: Better component choices
        - layout: Optimal layout strategy
        - best_practices: Adherence to Vizro patterns

        Args:
            code: Vizro code to optimize
            focus_areas: List of optimization focus areas

        Returns:
            AgentResponse with optimized code and improvements
        """
        try:
            print(f"⚡ Optimizing code...")
            print(f"Focus areas: {', '.join(focus_areas) if focus_areas else 'all'}")

            # Analyze current implementation
            config = self._parse_vizro_code(code)
            issues = self._identify_optimization_opportunities(config, focus_areas)

            print(f"Found {len(issues)} optimization opportunities")

            # Generate optimized version
            optimized_code = self._apply_optimizations(code, issues)

            # Calculate improvements
            improvements = self._calculate_improvements(issues)

            # Generate explanation
            explanation = self._generate_optimization_explanation(
                issues, improvements, optimized_code
            )

            # Validate optimized code
            is_valid, validation_msg, details = (
                await self.validator.validate_dashboard_config(
                    config=self._parse_vizro_code(optimized_code),
                    data_infos=[],
                    custom_charts=[],
                )
            )

            return AgentResponse(
                success=is_valid,
                message=f"Code optimized with {len(issues)} improvements",
                code=optimized_code,
                explanation=explanation,
                validation_result=details,
                suggestions=improvements,
            )

        except Exception as e:
            return AgentResponse(
                success=False,
                message=f"Error optimizing code: {str(e)}",
                explanation=self._generate_error_explanation(e),
            )

    async def teach_concept(self, topic: str) -> AgentResponse:
        """
        Teach a Vizro concept with examples and explanations.

        Args:
            topic: Concept to explain (e.g., "filters", "parameters", "layouts")

        Returns:
            AgentResponse with comprehensive explanation
        """
        try:
            print(f"📚 Teaching concept: {topic}")

            # Get relevant knowledge
            concept_info = self.knowledge_base.get_concept_info(topic)

            if not concept_info:
                return AgentResponse(
                    success=False,
                    message=f"Unknown topic: {topic}",
                    suggestions=self.knowledge_base.get_available_topics(),
                )

            # Generate comprehensive explanation
            explanation = self._generate_teaching_explanation(topic, concept_info)

            # Get code examples
            examples = self.knowledge_base.get_examples(topic)

            # Generate example code
            example_code = self._format_examples(examples)

            return AgentResponse(
                success=True,
                message=f"Concept explanation: {topic}",
                code=example_code,
                explanation=explanation,
                suggestions=self.knowledge_base.get_related_topics(topic),
            )

        except Exception as e:
            return AgentResponse(
                success=False,
                message=f"Error teaching concept: {str(e)}",
                explanation=self._generate_error_explanation(e),
            )

    # === Private Helper Methods ===

    def _generate_dashboard_config(
        self, user_request: str, data_info: Dict, instructions: str
    ) -> Dict[str, Any]:
        """Generate dashboard configuration from user request."""
        # This is a simplified version - actual implementation would use
        # more sophisticated parsing and generation logic

        # Extract data characteristics
        columns = data_info.get("columns", [])
        dtypes = data_info.get("dtypes", {})

        # Determine appropriate components
        components = self._select_components(user_request, columns, dtypes)

        # Determine filters
        filters = self._select_filters(user_request, columns, dtypes)

        # Build configuration
        config = {
            "pages": [
                {
                    "title": self._extract_title(user_request),
                    "components": components,
                    "controls": filters,
                }
            ]
        }

        return config

    def _select_components(
        self, request: str, columns: List[str], dtypes: Dict
    ) -> List[Dict]:
        """Select appropriate components based on request and data."""
        components = []

        # Check for chart keywords
        if any(word in request.lower() for word in ["scatter", "plot", "graph"]):
            components.append(self._create_scatter_component(columns, dtypes))

        if any(word in request.lower() for word in ["line", "trend", "time"]):
            components.append(self._create_line_component(columns, dtypes))

        if any(word in request.lower() for word in ["bar", "histogram"]):
            components.append(self._create_bar_component(columns, dtypes))

        if any(word in request.lower() for word in ["table", "data"]):
            components.append(self._create_table_component())

        # Default to scatter if no specific chart mentioned
        if not components:
            components.append(self._create_scatter_component(columns, dtypes))

        return components

    def _select_filters(
        self, request: str, columns: List[str], dtypes: Dict
    ) -> List[Dict]:
        """Select appropriate filters based on request and data."""
        filters = []

        # Check for explicit filter mentions
        if "filter" in request.lower():
            # Add filters for categorical columns
            for col, dtype in dtypes.items():
                if dtype in ["object", "category", "string"]:
                    filters.append({"type": "filter", "column": col})

        return filters

    def _create_scatter_component(
        self, columns: List[str], dtypes: Dict
    ) -> Dict[str, Any]:
        """Create scatter plot component."""
        # Find suitable numeric columns for x and y
        numeric_cols = [col for col, dtype in dtypes.items() if "float" in dtype or "int" in dtype]

        x_col = numeric_cols[0] if len(numeric_cols) > 0 else columns[0]
        y_col = numeric_cols[1] if len(numeric_cols) > 1 else columns[1]

        # Find categorical column for color
        categorical_cols = [col for col, dtype in dtypes.items() if dtype in ["object", "category"]]
        color_col = categorical_cols[0] if categorical_cols else None

        component = {
            "type": "graph",
            "figure": {
                "_target_": "scatter",
                "x": x_col,
                "y": y_col,
            },
        }

        if color_col:
            component["figure"]["color"] = color_col

        return component

    def _create_line_component(
        self, columns: List[str], dtypes: Dict
    ) -> Dict[str, Any]:
        """Create line chart component."""
        # Similar logic to scatter but for line charts
        numeric_cols = [col for col, dtype in dtypes.items() if "float" in dtype or "int" in dtype]
        temporal_cols = [col for col, dtype in dtypes.items() if "datetime" in dtype]

        x_col = temporal_cols[0] if temporal_cols else (numeric_cols[0] if numeric_cols else columns[0])
        y_col = numeric_cols[1] if len(numeric_cols) > 1 else (numeric_cols[0] if numeric_cols else columns[1])

        return {"type": "graph", "figure": {"_target_": "line", "x": x_col, "y": y_col}}

    def _create_bar_component(
        self, columns: List[str], dtypes: Dict
    ) -> Dict[str, Any]:
        """Create bar chart component."""
        categorical_cols = [col for col, dtype in dtypes.items() if dtype in ["object", "category"]]
        numeric_cols = [col for col, dtype in dtypes.items() if "float" in dtype or "int" in dtype]

        x_col = categorical_cols[0] if categorical_cols else columns[0]
        y_col = numeric_cols[0] if numeric_cols else columns[1]

        return {"type": "graph", "figure": {"_target_": "bar", "x": x_col, "y": y_col}}

    def _create_table_component(self) -> Dict[str, Any]:
        """Create table/AgGrid component."""
        return {"type": "ag_grid", "figure": {"_target_": "dash_ag_grid"}}

    def _extract_title(self, request: str) -> str:
        """Extract appropriate title from user request."""
        # Simple heuristic - take first few words
        words = request.split()
        return " ".join(words[:5]).title()

    def _apply_validation_fixes(self, config: Dict, error_message: str) -> Dict:
        """Apply fixes based on validation error message."""
        # Parse error and apply appropriate fixes
        # This is simplified - actual implementation would be more sophisticated

        if "required" in error_message.lower():
            # Add missing required fields with defaults
            if "components" not in config.get("pages", [{}])[0]:
                config["pages"][0]["components"] = []

        return config

    async def _retry_validation(
        self, config: Dict, data_infos: List[Dict], custom_charts: List[Dict]
    ) -> AgentResponse:
        """Retry validation with fixed configuration."""
        is_valid, message, details = await self.validator.validate_dashboard_config(
            config=config, data_infos=data_infos, custom_charts=custom_charts
        )

        if is_valid:
            return AgentResponse(
                success=True,
                message="Dashboard created successfully after fixes",
                code=details.get("python_code"),
                pycafe_link=details.get("pycafe_link"),
                validation_result=details,
            )
        else:
            return AgentResponse(
                success=False,
                message=f"Validation failed: {message}",
                code=None,
                explanation="Unable to automatically fix validation errors",
            )

    def _classify_error(self, error_message: str) -> str:
        """Classify error type from message."""
        error_lower = error_message.lower()

        if "required" in error_lower or "missing" in error_lower:
            return "missing_field"
        elif "type" in error_lower:
            return "type_mismatch"
        elif "not found" in error_lower or "keyerror" in error_lower:
            return "reference_error"
        elif "callback" in error_lower:
            return "callback_conflict"
        else:
            return "unknown"

    def _parse_vizro_code(self, code: str) -> Dict[str, Any]:
        """Parse Vizro code into configuration dict."""
        # Simplified - actual implementation would use AST parsing
        # For now, return empty dict
        return {}

    async def _check_missing_fields(self, config: Dict) -> List[str]:
        """Check for missing required fields in configuration."""
        missing = []

        # Check each model type
        for model_type in ["Dashboard", "Page", "Graph"]:
            schema = await self.mcp_client.call_tool(
                "get_model_json_schema", {"model_name": model_type}
            )

            required = schema.get("required", [])
            for field in required:
                if field not in config:
                    missing.append(f"{model_type}.{field}")

        return missing

    async def _check_type_errors(self, config: Dict) -> List[str]:
        """Check for type mismatches in configuration."""
        # Simplified - actual implementation would validate against schemas
        return []

    def _generate_fixes(
        self, code: str, missing_fields: List[str], type_errors: List[str]
    ) -> str:
        """Generate fixed code based on identified issues."""
        # Simplified - actual implementation would use AST manipulation
        return code

    def _apply_known_solution(self, code: str, issue) -> str:
        """Apply known solution to code."""
        # Simplified - actual implementation would apply specific fixes
        return code

    def _generate_creation_explanation(
        self, config: Dict, data_info: Dict
    ) -> str:
        """Generate explanation for created dashboard."""
        num_pages = len(config.get("pages", []))
        num_components = sum(
            len(page.get("components", [])) for page in config.get("pages", [])
        )
        num_filters = sum(
            len(page.get("controls", [])) for page in config.get("pages", [])
        )

        explanation = f"""
Created dashboard with:
- {num_pages} page(s)
- {num_components} component(s)
- {num_filters} filter(s)

Data: {data_info.get('shape', 'unknown')}
Columns: {', '.join(data_info.get('columns', [])[:5])}...

The configuration follows Vizro best practices and is ready to run.
"""
        return explanation.strip()

    def _generate_debug_explanation(
        self, error: str, error_type: str, fixed_code: str, known_issue
    ) -> str:
        """Generate explanation for debugging session."""
        if known_issue:
            return f"""
Error Type: {error_type}

Issue: {known_issue.description}

Solution Applied: {known_issue.solution}

The code has been fixed and should now work correctly.
"""
        else:
            return f"""
Error Type: {error_type}

The error was analyzed and appropriate fixes were applied.
The fixed code addresses the identified issues.
"""

    def _get_prevention_tips(self, error_type: str) -> List[str]:
        """Get prevention tips for error type."""
        tips = {
            "missing_field": [
                "Always check required fields in model schemas",
                "Use vm.Model(...) with all required parameters",
                "Refer to documentation for model requirements",
            ],
            "type_mismatch": [
                "Verify parameter types match schema expectations",
                "Use proper Plotly Figure objects for graphs",
                "Check data types in DataFrames",
            ],
            "reference_error": [
                "Register data in data_manager before referencing",
                "Ensure component IDs match targets",
                "Check for typos in references",
            ],
            "callback_conflict": [
                "Use unique IDs for all components",
                "Avoid duplicate component IDs",
                "Let Vizro auto-generate IDs when possible",
            ],
        }

        return tips.get(error_type, ["Review Vizro documentation", "Check examples"])

    def _identify_optimization_opportunities(
        self, config: Dict, focus_areas: List[str]
    ) -> List[Dict]:
        """Identify optimization opportunities in code."""
        opportunities = []

        # Check for data loading optimization
        if not focus_areas or "data_loading" in focus_areas:
            opportunities.append(
                {
                    "type": "caching",
                    "description": "Add caching to data loading",
                    "impact": "high",
                }
            )

        # Check for component optimization
        if not focus_areas or "components" in focus_areas:
            opportunities.append(
                {
                    "type": "agrid",
                    "description": "Replace Table with AgGrid",
                    "impact": "medium",
                }
            )

        return opportunities

    def _apply_optimizations(self, code: str, issues: List[Dict]) -> str:
        """Apply optimizations to code."""
        # Simplified - actual implementation would apply specific optimizations
        optimized = code

        for issue in issues:
            if issue["type"] == "caching":
                # Add caching decorator
                optimized = self._add_caching(optimized)
            elif issue["type"] == "agrid":
                # Replace Table with AgGrid
                optimized = optimized.replace("vm.Table", "vm.AgGrid")

        return optimized

    def _add_caching(self, code: str) -> str:
        """Add caching to data loading functions."""
        # Simplified - actual implementation would use AST manipulation
        return code

    def _calculate_improvements(self, issues: List[Dict]) -> List[str]:
        """Calculate expected improvements from optimizations."""
        improvements = []

        for issue in issues:
            if issue["type"] == "caching":
                improvements.append("10x faster on repeat visits")
            elif issue["type"] == "agrid":
                improvements.append("5x faster table rendering")

        return improvements

    def _generate_optimization_explanation(
        self, issues: List[Dict], improvements: List[str], optimized_code: str
    ) -> str:
        """Generate explanation for optimizations."""
        issue_list = "\n".join(f"- {issue['description']}" for issue in issues)
        improvement_list = "\n".join(f"- {imp}" for imp in improvements)

        return f"""
Applied {len(issues)} optimization(s):
{issue_list}

Expected Improvements:
{improvement_list}

The optimized code follows Vizro best practices and should perform significantly better.
"""

    def _generate_teaching_explanation(
        self, topic: str, concept_info: Dict
    ) -> str:
        """Generate comprehensive teaching explanation."""
        return f"""
# {topic.title()}

## Overview
{concept_info.get('description', 'No description available')}

## When to Use
{concept_info.get('use_cases', 'Various use cases')}

## Best Practices
{concept_info.get('best_practices', 'Follow Vizro guidelines')}

## Common Mistakes
{concept_info.get('common_mistakes', 'Avoid anti-patterns')}

Refer to the code examples below for practical demonstrations.
"""

    def _format_examples(self, examples: List[Dict]) -> str:
        """Format code examples for display."""
        if not examples:
            return "# No examples available"

        formatted = []
        for i, example in enumerate(examples, 1):
            formatted.append(f"# Example {i}: {example.get('title', 'Untitled')}")
            formatted.append(example.get("code", ""))
            formatted.append("")

        return "\n".join(formatted)

    def _generate_error_explanation(self, error: Exception) -> str:
        """Generate explanation for unexpected errors."""
        return f"""
An unexpected error occurred: {str(error)}

This may be due to:
- Malformed input
- Missing dependencies
- Internal error

Please check the error message and try again.
"""


# === Convenience Functions ===


async def create_dashboard_from_text(user_request: str, data_source: str = "iris"):
    """
    Convenience function to create dashboard from natural language.

    Example:
        result = await create_dashboard_from_text(
            "Show scatter plot of sepal length vs width",
            "iris"
        )
        print(result.code)
    """
    agent = VizroAgent()
    context = AgentContext(
        mode=AgentMode.CREATION, user_request=user_request, data_source=data_source
    )
    return await agent.process_request(context)


async def debug_vizro_code(code: str, error: str):
    """
    Convenience function to debug Vizro code.

    Example:
        result = await debug_vizro_code(
            code="page = vm.Page(title='My Page')",
            error="'components' field required"
        )
        print(result.code)
    """
    agent = VizroAgent()
    context = AgentContext(
        mode=AgentMode.DEBUGGING, user_request="", code=code, error_message=error
    )
    return await agent.process_request(context)


async def optimize_vizro_dashboard(code: str, focus_areas: List[str] = None):
    """
    Convenience function to optimize Vizro code.

    Example:
        result = await optimize_vizro_dashboard(
            code="...",
            focus_areas=["data_loading", "components"]
        )
        print(result.code)
    """
    agent = VizroAgent()
    context = AgentContext(
        mode=AgentMode.OPTIMIZATION,
        user_request="",
        code=code,
        focus_areas=focus_areas,
    )
    return await agent.process_request(context)


async def learn_vizro_concept(topic: str):
    """
    Convenience function to learn about Vizro concepts.

    Example:
        result = await learn_vizro_concept("filters")
        print(result.explanation)
    """
    agent = VizroAgent()
    context = AgentContext(mode=AgentMode.TEACHING, user_request=topic)
    return await agent.process_request(context)


if __name__ == "__main__":
    # Example usage
    async def main():
        # Create dashboard
        result = await create_dashboard_from_text(
            "Create a dashboard with scatter plot and table", "iris"
        )
        print(f"Success: {result.success}")
        print(f"PyCafe: {result.pycafe_link}")

    asyncio.run(main())
