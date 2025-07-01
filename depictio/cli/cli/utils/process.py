# depictio/cli/cli/utils/process.py

from depictio.cli.cli.utils.rich_utils import (
    rich_print_checked_statement,
)
from depictio.cli.cli_logging import logger
from depictio.models.models.cli import CLIConfig


def process_project_data_collections(
    CLI_config: CLIConfig,
    project_config,
    workflow_name: str | None = None,
    data_collection_tag: str | None = None,
    command_parameters: dict | None = None,
) -> dict:
    """
    Process data collections for a project with optional filtering.

    Args:
        CLI_config: CLI configuration containing API URL and credentials
        project_config: The project configuration object
        workflow_name: Optional workflow name to filter by
        data_collection_tag: Optional data collection tag to filter by
        command_parameters: Command parameters dict

    Returns:
        dict: Results summary
    """
    if command_parameters is None:
        command_parameters = {}

    rich_print_checked_statement(
        f"Processing Project: [italic]'{project_config.name}'[/italic]", "info"
    )

    # Filter workflows if specific workflow_name is provided
    workflows_to_process = project_config.workflows
    if workflow_name:
        workflows_to_process = [w for w in workflows_to_process if w.workflow_tag == workflow_name]
        if not workflows_to_process:
            raise Exception(f"Workflow '{workflow_name}' not found in project")

    total_processed = 0

    for workflow in workflows_to_process:
        rich_print_checked_statement(
            f" ↪ Processing Workflow: [italic]'{workflow.workflow_tag}'[/italic]", "info"
        )

        # Filter data collections if specific data_collection_tag is provided
        data_collections_to_process = workflow.data_collections
        logger.info(
            f"Found {len(data_collections_to_process)} data collections in workflow '{workflow.workflow_tag}'"
        )
        if data_collection_tag:
            data_collections_to_process = [
                dc
                for dc in data_collections_to_process
                if dc.data_collection_tag == data_collection_tag
            ]
            if not data_collections_to_process:
                rich_print_checked_statement(
                    f"Data collection '{data_collection_tag}' not found in workflow '{workflow.workflow_tag}'",
                    "warning",
                )
                continue

        # Process each data collection
        for dc in data_collections_to_process:
            try:
                result = process_single_data_collection(
                    workflow=workflow,
                    data_collection=dc,
                    CLI_config=CLI_config,
                    command_parameters=command_parameters,
                )

                if result["success"]:
                    rich_print_checked_statement(
                        f"  ✓ Data collection [italic]'{dc.data_collection_tag}'[/italic] processed successfully. {result['data']['message']}",
                        "success",
                    )
                    total_processed += 1
                else:
                    rich_print_checked_statement(
                        f"  ✗ Failed to process data collection '{dc.data_collection_tag}': {result.get('message', 'Unknown error')}",
                        "error",
                    )

            except Exception as e:
                rich_print_checked_statement(
                    f"  ✗ Error processing data collection '{dc.data_collection_tag}': {e}",
                    "error",
                )
                logger.error(f"Detailed error for {dc.data_collection_tag}: {e}", exc_info=True)

        rich_print_checked_statement(
            f"Workflow {workflow.workflow_tag} processing completed", "success"
        )

    rich_print_checked_statement(
        f"Processing completed! Total data collections processed: {total_processed}", "success"
    )

    return {"result": "success", "total_processed": total_processed}


def process_single_data_collection(
    workflow,
    data_collection,
    CLI_config: CLIConfig,
    command_parameters: dict | None = None,
) -> dict:
    """
    Process a single data collection using existing helper function.

    Args:
        workflow: The workflow object
        data_collection: The data collection to process
        CLI_config: CLI configuration
        overwrite: Whether to overwrite existing processed data

    Returns:
        dict: Processing result with success status and message
    """
    from depictio.cli.cli.utils.helpers import process_data_collection_helper

    try:
        logger.info(f"Processing data collection: {data_collection.data_collection_tag}")

        # Use existing helper function
        result = process_data_collection_helper(
            CLI_config=CLI_config,
            wf=workflow,
            dc_id=str(data_collection.id),
            command_parameters=command_parameters or {},
            mode="process",
        )

        return {
            "success": True,
            "message": f"Data collection {data_collection.data_collection_tag} processed successfully",
            "data": result,
        }

    except Exception as e:
        logger.error(f"Error processing data collection {data_collection.data_collection_tag}: {e}")
        return {
            "success": False,
            "message": str(e),
        }


# Legacy function for backwards compatibility
def process_project_helper_legacy(
    CLI_config,
    project_config,
    mode: str,
    workflow_name: str | None = None,
    data_collection_tag: str | None = None,
    command_parameters: dict | None = None,
):
    """
    Legacy helper function - kept for backwards compatibility.
    Use the individual functions directly for new code.
    """
    logger.warning("Using legacy process_project_helper_legacy function.")

    if mode == "process":
        return process_project_data_collections(
            CLI_config=CLI_config,
            project_config=project_config,
            workflow_name=workflow_name,
            data_collection_tag=data_collection_tag,
            command_parameters=command_parameters,
        )
    else:
        raise ValueError(f"Invalid mode: {mode}. This function only supports 'process' mode.")
