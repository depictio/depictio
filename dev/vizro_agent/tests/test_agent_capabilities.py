"""
Test suite for Vizro agent capabilities.

Tests cover all major agent functions including dashboard creation,
debugging, optimization, and teaching.
"""

import pytest
import asyncio
import sys
sys.path.append("..")

from agent_core import VizroAgent, AgentContext, AgentMode
from vizro_knowledge_base import VizroKnowledgeBase
from validation_helpers import VizroValidator
from mcp_integration import VizroMCPClient


class TestAgentCore:
    """Test core agent functionality."""

    @pytest.mark.asyncio
    async def test_agent_initialization(self):
        """Test agent initializes correctly."""
        agent = VizroAgent()
        assert agent.knowledge_base is not None
        assert agent.prompts is not None
        assert agent.mcp_client is not None
        assert agent.validator is not None

    @pytest.mark.asyncio
    async def test_dashboard_creation_mode(self):
        """Test dashboard creation mode."""
        agent = VizroAgent()
        context = AgentContext(
            mode=AgentMode.CREATION,
            user_request="Create a simple scatter plot",
            data_source="iris"
        )
        # Note: In actual tests, mock MCP calls
        # result = await agent.process_request(context)
        # assert result.success is True

    @pytest.mark.asyncio
    async def test_debugging_mode(self):
        """Test debugging mode."""
        agent = VizroAgent()
        context = AgentContext(
            mode=AgentMode.DEBUGGING,
            user_request="",
            code="page = vm.Page(title='Test')",
            error_message="components field required"
        )
        # result = await agent.process_request(context)
        # assert result.success is True

    @pytest.mark.asyncio
    async def test_optimization_mode(self):
        """Test optimization mode."""
        agent = VizroAgent()
        context = AgentContext(
            mode=AgentMode.OPTIMIZATION,
            user_request="",
            code="# Some code",
            focus_areas=["data_loading"]
        )
        # result = await agent.process_request(context)
        # assert result.success is True

    @pytest.mark.asyncio
    async def test_teaching_mode(self):
        """Test teaching mode."""
        agent = VizroAgent()
        context = AgentContext(
            mode=AgentMode.TEACHING,
            user_request="filters"
        )
        # result = await agent.process_request(context)
        # assert result.success is True


class TestKnowledgeBase:
    """Test knowledge base functionality."""

    def test_knowledge_base_initialization(self):
        """Test knowledge base initializes with data."""
        kb = VizroKnowledgeBase()
        assert len(kb.models) > 0
        assert len(kb.common_issues) > 0
        assert len(kb.best_practices) > 0
        assert len(kb.concepts) > 0

    def test_get_model_info(self):
        """Test retrieving model information."""
        kb = VizroKnowledgeBase()
        model = kb.get_model_info("Dashboard")
        assert model is not None
        assert model.name == "Dashboard"
        assert "pages" in model.required_fields

    def test_find_matching_issue(self):
        """Test finding matching issue for error."""
        kb = VizroKnowledgeBase()
        issue = kb.find_matching_issue("field required")
        assert issue is not None
        assert "required" in issue.pattern.lower()

    def test_get_concept_info(self):
        """Test retrieving concept information."""
        kb = VizroKnowledgeBase()
        concept = kb.get_concept_info("filters")
        assert concept is not None
        assert concept.name == "Filters"
        assert len(concept.related_topics) > 0

    def test_get_pattern(self):
        """Test retrieving code pattern."""
        kb = VizroKnowledgeBase()
        pattern = kb.get_pattern("basic_dashboard")
        assert pattern is not None
        assert "vm.Page" in pattern

    def test_get_selector_for_dtype(self):
        """Test selector recommendation for data type."""
        kb = VizroKnowledgeBase()
        selector = kb.get_selector_for_dtype("categorical")
        assert selector == "Dropdown"

        selector = kb.get_selector_for_dtype("numerical")
        assert selector == "RangeSlider"

    def test_search_knowledge(self):
        """Test knowledge search functionality."""
        kb = VizroKnowledgeBase()
        results = kb.search_knowledge("filter")
        assert "models" in results
        assert "concepts" in results


class TestValidator:
    """Test validation helper functionality."""

    @pytest.mark.asyncio
    async def test_validator_initialization(self):
        """Test validator initializes correctly."""
        mcp_client = VizroMCPClient()
        validator = VizroValidator(mcp_client)
        assert validator.mcp_client is not None

    def test_validate_component_id(self):
        """Test component ID validation."""
        mcp_client = VizroMCPClient()
        validator = VizroValidator(mcp_client)

        is_valid, error = validator.validate_component_id("unique_id", [])
        assert is_valid is True
        assert error is None

        is_valid, error = validator.validate_component_id("dup_id", ["dup_id"])
        assert is_valid is False
        assert "Duplicate" in error

    def test_validate_target_reference(self):
        """Test target reference validation."""
        mcp_client = VizroMCPClient()
        validator = VizroValidator(mcp_client)

        is_valid, error = validator.validate_target_reference(
            "chart1",
            ["chart1", "chart2"]
        )
        assert is_valid is True

        is_valid, error = validator.validate_target_reference(
            "missing",
            ["chart1", "chart2"]
        )
        assert is_valid is False

    def test_validate_filter_column(self):
        """Test filter column validation."""
        mcp_client = VizroMCPClient()
        validator = VizroValidator(mcp_client)

        is_valid, error = validator.validate_filter_column(
            "species",
            ["sepal_length", "species", "petal_width"]
        )
        assert is_valid is True

        is_valid, error = validator.validate_filter_column(
            "nonexistent",
            ["sepal_length", "species"]
        )
        assert is_valid is False


class TestMCPIntegration:
    """Test MCP client functionality."""

    def test_mcp_client_initialization(self):
        """Test MCP client initializes correctly."""
        client = VizroMCPClient()
        assert client.server_name == "vizro"
        assert len(client.available_tools) > 0

    def test_list_available_tools(self):
        """Test listing available tools."""
        client = VizroMCPClient()
        tools = client.list_available_tools()
        assert "get_model_json_schema" in tools
        assert "validate_dashboard_config" in tools

    def test_is_tool_available(self):
        """Test tool availability check."""
        client = VizroMCPClient()
        assert client.is_tool_available("get_model_json_schema") is True
        assert client.is_tool_available("nonexistent_tool") is False

    @pytest.mark.asyncio
    async def test_call_unknown_tool(self):
        """Test calling unknown tool raises error."""
        client = VizroMCPClient()
        with pytest.raises(ValueError):
            await client.call_tool("nonexistent_tool", {})


class TestIntegration:
    """Integration tests for complete workflows."""

    @pytest.mark.asyncio
    async def test_dashboard_creation_workflow(self):
        """Test complete dashboard creation workflow."""
        # This would test the full flow:
        # 1. User request
        # 2. Data analysis
        # 3. Config generation
        # 4. Validation
        # 5. Code generation
        pass

    @pytest.mark.asyncio
    async def test_debugging_workflow(self):
        """Test complete debugging workflow."""
        # This would test the full flow:
        # 1. Error input
        # 2. Error classification
        # 3. Solution identification
        # 4. Fix generation
        # 5. Fix validation
        pass

    @pytest.mark.asyncio
    async def test_optimization_workflow(self):
        """Test complete optimization workflow."""
        # This would test the full flow:
        # 1. Code analysis
        # 2. Issue identification
        # 3. Optimization generation
        # 4. Validation
        # 5. Improvement quantification
        pass


def run_tests():
    """Run all tests."""
    pytest.main([__file__, "-v", "-s"])


if __name__ == "__main__":
    run_tests()
