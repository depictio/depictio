"""
Validation helpers for Vizro configurations.

Provides utilities for validating dashboard configurations against
Vizro schemas using the vizro-mcp server.
"""

from typing import Dict, Any, List, Tuple, Optional


class VizroValidator:
    """Validates Vizro configurations against schemas."""

    def __init__(self, mcp_client):
        """
        Initialize validator with MCP client.

        Args:
            mcp_client: VizroMCPClient instance for tool calls
        """
        self.mcp_client = mcp_client
        self._schema_cache: Dict[str, Dict] = {}

    async def get_model_schema(self, model_name: str) -> Dict[str, Any]:
        """
        Retrieve JSON schema for a Vizro model.

        Args:
            model_name: Name of the Vizro model (e.g., "Dashboard", "Page")

        Returns:
            JSON schema dictionary
        """
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

        Args:
            config: Dashboard configuration dictionary
            data_infos: List of data metadata objects
            custom_charts: List of custom chart configurations

        Returns:
            Tuple of (is_valid, message, details)
        """
        try:
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

        except Exception as e:
            return False, f"Validation error: {str(e)}", {}

    async def validate_chart_code(
        self,
        chart_config: Dict[str, Any],
        data_info: Dict[str, Any]
    ) -> Tuple[bool, str, Dict]:
        """
        Validate custom chart code.

        Args:
            chart_config: Chart configuration with code
            data_info: Data metadata

        Returns:
            Tuple of (is_valid, message, details)
        """
        try:
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

        except Exception as e:
            return False, f"Chart validation error: {str(e)}", {}

    async def check_required_fields(
        self,
        config: Dict[str, Any],
        model_name: str
    ) -> List[str]:
        """
        Check for missing required fields.

        Args:
            config: Configuration to check
            model_name: Name of Vizro model

        Returns:
            List of missing required field names
        """
        schema = await self.get_model_schema(model_name)
        required = schema.get("required", [])
        missing = [field for field in required if field not in config]
        return missing

    async def validate_field_types(
        self,
        config: Dict[str, Any],
        schema: Dict[str, Any]
    ) -> List[str]:
        """
        Validate field types against schema.

        Args:
            config: Configuration to validate
            schema: JSON schema

        Returns:
            List of type error messages
        """
        errors = []
        properties = schema.get("properties", {})

        for field, value in config.items():
            if field not in properties:
                errors.append(f"Unknown field: {field}")
                continue

            expected_type = properties[field].get("type")
            actual_type = self._get_type_name(value)

            if expected_type and not self._types_match(expected_type, actual_type):
                errors.append(
                    f"Field '{field}': expected {expected_type}, got {actual_type}"
                )

        return errors

    def validate_data_reference(
        self,
        data_name: str,
        registered_data: List[str]
    ) -> bool:
        """
        Check if data is registered in data_manager.

        Args:
            data_name: Name of data to check
            registered_data: List of registered data names

        Returns:
            True if data is registered
        """
        return data_name in registered_data

    def validate_component_id(
        self,
        component_id: str,
        existing_ids: List[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if component ID is unique.

        Args:
            component_id: ID to check
            existing_ids: List of existing IDs

        Returns:
            Tuple of (is_valid, error_message)
        """
        if component_id in existing_ids:
            return False, f"Duplicate component ID: {component_id}"
        return True, None

    def validate_target_reference(
        self,
        target_id: str,
        component_ids: List[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if target component exists.

        Args:
            target_id: Target component ID
            component_ids: List of available component IDs

        Returns:
            Tuple of (is_valid, error_message)
        """
        if target_id not in component_ids:
            return False, f"Target component not found: {target_id}"
        return True, None

    def validate_filter_column(
        self,
        column: str,
        df_columns: List[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if filter column exists in DataFrame.

        Args:
            column: Column name to check
            df_columns: List of DataFrame columns

        Returns:
            Tuple of (is_valid, error_message)
        """
        if column not in df_columns:
            return False, f"Column not found in DataFrame: {column}"
        return True, None

    @staticmethod
    def _get_type_name(value: Any) -> str:
        """Get type name for a value."""
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
        }
        return type_map.get(type(value), str(type(value)))

    @staticmethod
    def _types_match(expected: str, actual: str) -> bool:
        """Check if types match (accounting for JSON schema types)."""
        # Direct match
        if expected == actual:
            return True

        # Number includes integer and float
        if expected == "number" and actual in ["integer", "number"]:
            return True

        # Array and object
        if expected == "array" and actual == "array":
            return True
        if expected == "object" and actual == "object":
            return True

        return False


# === Convenience Functions ===


async def validate_config(
    mcp_client,
    config: Dict[str, Any],
    data_infos: List[Dict] = None,
    custom_charts: List[Dict] = None
) -> Tuple[bool, str, Dict]:
    """
    Convenience function to validate a configuration.

    Example:
        is_valid, message, details = await validate_config(
            mcp_client,
            config={"pages": [...]},
            data_infos=[data_info]
        )
    """
    validator = VizroValidator(mcp_client)
    return await validator.validate_dashboard_config(
        config,
        data_infos or [],
        custom_charts or []
    )


async def check_missing_fields(
    mcp_client,
    config: Dict[str, Any],
    model_name: str
) -> List[str]:
    """
    Check for missing required fields.

    Example:
        missing = await check_missing_fields(
            mcp_client,
            config={"title": "My Page"},
            model_name="Page"
        )
        # Returns: ["components"]
    """
    validator = VizroValidator(mcp_client)
    return await validator.check_required_fields(config, model_name)


if __name__ == "__main__":
    # Example usage
    from mcp_integration import VizroMCPClient
    import asyncio

    async def main():
        client = VizroMCPClient()
        validator = VizroValidator(client)

        # Check required fields
        config = {"title": "My Page"}
        missing = await validator.check_required_fields(config, "Page")
        print(f"Missing fields: {missing}")

    asyncio.run(main())
