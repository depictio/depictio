"""
MCP client wrapper for vizro-mcp server integration.

Provides a Python client for interacting with the vizro-mcp server
through the Model Context Protocol.
"""

import asyncio
from typing import Dict, Any, List, Optional


class VizroMCPClient:
    """Client for interacting with vizro-mcp server."""

    def __init__(self):
        """Initialize the MCP client for Vizro."""
        self.server_name = "vizro"
        self.available_tools = [
            "get_vizro_chart_or_dashboard_plan",
            "get_model_json_schema",
            "get_sample_data_info",
            "load_and_analyze_data",
            "validate_dashboard_config",
            "validate_chart_code",
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

        Raises:
            ValueError: If tool_name is not available
        """
        if tool_name not in self.available_tools:
            raise ValueError(
                f"Unknown tool: {tool_name}. "
                f"Available tools: {', '.join(self.available_tools)}"
            )

        # Note: In actual Claude Code usage, this would be executed via MCP
        # The implementation here is a placeholder showing the structure

        # When used within Claude Code, this would call:
        # result = await mcp_call(f"mcp__vizro-mcp__{tool_name}", parameters)

        # For standalone usage, you would need to implement actual MCP protocol
        # communication here (e.g., using stdio or HTTP transport)

        print(f"[MCP Call] {tool_name}({parameters})")

        # Placeholder response structure
        return {
            "status": "success",
            "data": {},
            "message": f"Placeholder response from {tool_name}"
        }

    async def get_sample_data_info(
        self,
        data_name: str
    ) -> Dict[str, Any]:
        """
        Get information about sample datasets.

        Args:
            data_name: Name of sample dataset (iris, tips, stocks, gapminder)

        Returns:
            Data information dictionary with columns, dtypes, shape, etc.
        """
        return await self.call_tool(
            "get_sample_data_info",
            {"data_name": data_name}
        )

    async def load_and_analyze_data(
        self,
        path_or_url: str
    ) -> Dict[str, Any]:
        """
        Load and analyze a data file.

        Supports: CSV, JSON, HTML, Excel, ODS, Parquet

        Args:
            path_or_url: Absolute path or URL to data file

        Returns:
            Analysis results with columns, dtypes, shape, sample data
        """
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
        """
        Get instructions for creating a dashboard or chart.

        Args:
            user_plan: "chart" or "dashboard"
            user_host: "generic_host" or "ide"
            advanced_mode: Enable for custom CSS/components

        Returns:
            Instructions string
        """
        result = await self.call_tool(
            "get_vizro_chart_or_dashboard_plan",
            {
                "user_plan": user_plan,
                "user_host": user_host,
                "advanced_mode": advanced_mode
            }
        )
        return result.get("data", {}).get("instructions", "")

    async def get_model_schema(
        self,
        model_name: str
    ) -> Dict[str, Any]:
        """
        Get JSON schema for a Vizro model.

        Args:
            model_name: Name of model (Dashboard, Page, Graph, etc.)

        Returns:
            JSON schema dictionary
        """
        return await self.call_tool(
            "get_model_json_schema",
            {"model_name": model_name}
        )

    async def validate_dashboard(
        self,
        config: Dict[str, Any],
        data_infos: List[Dict],
        custom_charts: List[Dict],
        auto_open: bool = False
    ) -> Dict[str, Any]:
        """
        Validate a complete dashboard configuration.

        Args:
            config: Dashboard configuration dict
            data_infos: List of data metadata objects
            custom_charts: List of custom chart configs
            auto_open: Whether to open PyCafe link in browser

        Returns:
            Validation result with python_code and pycafe_link if valid
        """
        return await self.call_tool(
            "validate_dashboard_config",
            {
                "dashboard_config": config,
                "data_infos": data_infos,
                "custom_charts": custom_charts,
                "auto_open": auto_open
            }
        )

    async def validate_chart(
        self,
        chart_config: Dict[str, Any],
        data_info: Dict[str, Any],
        auto_open: bool = False
    ) -> Dict[str, Any]:
        """
        Validate custom chart code.

        Args:
            chart_config: ChartPlan object with code
            data_info: Dataset metadata
            auto_open: Whether to open PyCafe link

        Returns:
            Validation result with python_code and pycafe_link if valid
        """
        return await self.call_tool(
            "validate_chart_code",
            {
                "chart_config": chart_config,
                "data_info": data_info,
                "auto_open": auto_open
            }
        )

    def list_available_tools(self) -> List[str]:
        """Get list of available vizro-mcp tools."""
        return self.available_tools.copy()

    def is_tool_available(self, tool_name: str) -> bool:
        """Check if a tool is available."""
        return tool_name in self.available_tools


# === Convenience Functions ===


async def get_data_info(data_source: str) -> Dict[str, Any]:
    """
    Get data information (sample or file).

    Example:
        data_info = await get_data_info("iris")
        data_info = await get_data_info("/path/to/data.csv")
    """
    client = VizroMCPClient()

    if data_source in ["iris", "tips", "stocks", "gapminder"]:
        return await client.get_sample_data_info(data_source)
    else:
        return await client.load_and_analyze_data(data_source)


async def validate_config(
    config: Dict[str, Any],
    data_infos: List[Dict] = None,
    custom_charts: List[Dict] = None
) -> Dict[str, Any]:
    """
    Validate a dashboard configuration.

    Example:
        result = await validate_config(
            config={"pages": [...]},
            data_infos=[data_info]
        )
        if result["status"] == "success":
            print(result["data"]["pycafe_link"])
    """
    client = VizroMCPClient()
    return await client.validate_dashboard(
        config,
        data_infos or [],
        custom_charts or [],
        auto_open=False
    )


async def get_schema(model_name: str) -> Dict[str, Any]:
    """
    Get JSON schema for a Vizro model.

    Example:
        schema = await get_schema("Page")
        required_fields = schema.get("required", [])
    """
    client = VizroMCPClient()
    return await client.get_model_schema(model_name)


if __name__ == "__main__":
    # Example usage
    async def main():
        client = VizroMCPClient()

        # List available tools
        print("Available tools:")
        for tool in client.list_available_tools():
            print(f"  - {tool}")

        # Get sample data info
        print("\nGetting iris data info...")
        data_info = await client.get_sample_data_info("iris")
        print(f"Data info: {data_info}")

        # Get model schema
        print("\nGetting Page model schema...")
        schema = await client.get_model_schema("Page")
        print(f"Required fields: {schema.get('required', [])}")

        # Validate dashboard config
        print("\nValidating dashboard config...")
        config = {
            "pages": [{
                "title": "Test Page",
                "components": []
            }]
        }
        result = await client.validate_dashboard(
            config,
            [data_info],
            [],
            auto_open=False
        )
        print(f"Validation result: {result.get('status')}")

    asyncio.run(main())
