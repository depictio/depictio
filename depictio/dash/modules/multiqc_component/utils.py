from typing import Any

import dash_mantine_components as dmc
import httpx

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.modules.multiqc_component.models import (
    MultiQCDashboardComponent,
)


def build_multiqc(**kwargs: Any) -> dmc.Paper:
    """
    Build MultiQC component for dashboard display using Pydantic models.

    Args:
        **kwargs: Component metadata including:
            - index: Component ID
            - workflow_id/wf_id: Workflow ID
            - data_collection_id/dc_id: Data collection ID
            - selected_module: Selected MultiQC module
            - selected_plot: Selected plot
            - selected_dataset: Selected dataset
            - s3_locations: S3 data locations
            - metadata: MultiQC metadata
            - access_token: Authentication token
            - theme: UI theme

    Returns:
        Dash component for MultiQC visualization
    """
    from depictio.dash.modules.multiqc_component.frontend import design_multiqc_from_model

    logger.info(f"Building MultiQC component with kwargs keys: {list(kwargs.keys())}")

    try:
        # Create MultiQC component from stored metadata using Pydantic model
        multiqc_component = MultiQCDashboardComponent.from_stored_metadata(kwargs)
        logger.info(f"Created MultiQC component model: {multiqc_component.index}")
        logger.info(
            f"Component state: module={multiqc_component.state.selected_module}, "
            f"plot={multiqc_component.state.selected_plot}"
        )

        # Create the Dash component using the model
        dash_component = design_multiqc_from_model(multiqc_component)
        return dash_component

    except Exception as e:
        logger.error(f"Error building MultiQC component with models: {e}")
        # Fallback to legacy method if model creation fails
        return _build_multiqc_legacy(**kwargs)


def _build_multiqc_legacy(**kwargs: Any) -> dmc.Paper:
    """
    Legacy fallback method for building MultiQC components.

    Args:
        **kwargs: Component metadata in legacy format

    Returns:
        Dash component for MultiQC visualization
    """
    from depictio.dash.modules.multiqc_component.frontend import design_multiqc

    logger.info("Using legacy MultiQC component build method")

    # Extract basic parameters
    component_id = kwargs.get("index", "multiqc-component")
    workflow_id = kwargs.get("workflow_id") or kwargs.get("wf_id")
    data_collection_id = kwargs.get("data_collection_id") or kwargs.get("dc_id")
    local_data = kwargs.get("local_data") or kwargs.get("access_token")

    # Convert ObjectId to string if needed
    if isinstance(workflow_id, dict) and "$oid" in workflow_id:
        workflow_id = workflow_id["$oid"]
    if isinstance(data_collection_id, dict) and "$oid" in data_collection_id:
        data_collection_id = data_collection_id["$oid"]

    return design_multiqc(
        id=component_id,
        workflow_id=str(workflow_id) if workflow_id else None,
        data_collection_id=str(data_collection_id) if data_collection_id else None,
        local_data=local_data,
        **kwargs,  # Pass through any additional state
    )


def get_multiqc_reports_for_data_collection(data_collection_id: str, token: str) -> list:
    """
    Retrieve MultiQC reports for a specific data collection.

    Args:
        data_collection_id: The ID of the data collection
        token: Authentication token

    Returns:
        List of MultiQC reports
    """
    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/multiqc/reports/data-collection/{data_collection_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

        if response.status_code == 200:
            data = response.json()
            reports = data.get("reports", [])
            logger.info(
                f"Retrieved {len(reports)} MultiQC reports for data collection {data_collection_id}"
            )
            return reports
        else:
            logger.warning(
                f"Failed to retrieve MultiQC reports: {response.status_code} - {response.text}"
            )
            return []

    except Exception as e:
        logger.error(f"Error retrieving MultiQC reports: {str(e)}")
        return []


def get_multiqc_report_metadata(report_id: str, token: str) -> dict:
    """
    Get metadata for a specific MultiQC report.

    Args:
        report_id: The ID of the MultiQC report
        token: Authentication token

    Returns:
        Dictionary containing report metadata
    """
    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/multiqc/reports/{report_id}/metadata",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

        if response.status_code == 200:
            metadata = response.json()
            logger.info(f"Retrieved metadata for MultiQC report {report_id}")
            return metadata
        else:
            logger.warning(
                f"Failed to retrieve MultiQC report metadata: {response.status_code} - {response.text}"
            )
            return {}

    except Exception as e:
        logger.error(f"Error retrieving MultiQC report metadata: {str(e)}")
        return {}


def check_multiqc_data_availability(data_collection_id: str, token: str) -> dict:
    """
    Check if MultiQC data is available for a data collection.

    Args:
        data_collection_id: The ID of the data collection
        token: Authentication token

    Returns:
        Dictionary with availability status and details
    """
    try:
        # Check for MultiQC reports
        reports = get_multiqc_reports_for_data_collection(data_collection_id, token)

        # Get data collection info to verify it's a MultiQC type
        dc_response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/{data_collection_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

        dc_info = {}
        if dc_response.status_code == 200:
            dc_info = dc_response.json()

        dc_type = dc_info.get("config", {}).get("type", "").lower()

        return {
            "available": len(reports) > 0,
            "report_count": len(reports),
            "is_multiqc_type": dc_type == "multiqc",
            "data_collection_info": dc_info,
            "reports": reports,
        }

    except Exception as e:
        logger.error(f"Error checking MultiQC data availability: {str(e)}")
        return {
            "available": False,
            "report_count": 0,
            "is_multiqc_type": False,
            "error": str(e),
        }


def format_multiqc_summary(reports: list, metadata: dict | None = None) -> dict:
    """
    Format MultiQC data for display in the component.

    Args:
        reports: List of MultiQC reports
        metadata: Optional metadata dictionary

    Returns:
        Formatted summary information
    """
    if not reports:
        return {
            "total_reports": 0,
            "total_samples": 0,
            "modules": [],
            "summary": "No MultiQC reports available",
        }

    try:
        # Extract information from reports and metadata
        total_reports = len(reports)

        # Get sample and module information from metadata if available
        if metadata:
            samples = metadata.get("samples", [])
            modules = metadata.get("modules", [])
            plots = metadata.get("plots", {})
        else:
            # Try to extract from first report if metadata not provided
            first_report = reports[0]
            report_metadata = first_report.get("metadata", {})
            samples = report_metadata.get("samples", [])
            modules = report_metadata.get("modules", [])
            plots = report_metadata.get("plots", {})

        total_samples = len(samples)

        # Create summary text
        summary_parts = [f"{total_reports} report{'s' if total_reports != 1 else ''}"]
        if total_samples > 0:
            summary_parts.append(f"{total_samples} sample{'s' if total_samples != 1 else ''}")
        if modules:
            summary_parts.append(f"{len(modules)} module{'s' if len(modules) != 1 else ''}")

        summary = " • ".join(summary_parts)

        return {
            "total_reports": total_reports,
            "total_samples": total_samples,
            "modules": modules,
            "plots": plots,
            "samples": samples,
            "summary": summary,
        }

    except Exception as e:
        logger.error(f"Error formatting MultiQC summary: {str(e)}")
        return {
            "total_reports": len(reports),
            "total_samples": 0,
            "modules": [],
            "summary": f"Error formatting summary: {str(e)}",
        }
