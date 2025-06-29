from typing import Any

from pydantic import validate_call

from depictio.cli.cli.utils.deltatables import client_aggregate_data
from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement
from depictio.cli.cli.utils.scan import scan_files_for_data_collection
from depictio.cli.cli_logging import logger
from depictio.models.models.cli import CLIConfig
from depictio.models.models.projects import Workflow


def process_project_helper(
    CLI_config,
    project_config,
    mode: str,
    workflow_name: str | None = None,
    data_collection_tag: str | None = None,
    command_parameters: dict | None = None,
):
    """
    Helper function to process a project for scanning or processing.

    Args:
        CLI_config: CLI configuration
        project_config: Project configuration object
        mode: Either "scan" or "process"
        workflow_name: Optional workflow name filter
        data_collection_tag: Optional data collection tag filter
        command_parameters: Command parameters dict
    """
    if command_parameters is None:
        command_parameters = {}

    if mode == "scan":
        # Use the new unified scanning function
        from depictio.cli.cli.utils.scan import scan_project_files

        return scan_project_files(
            project_config=project_config,
            CLI_config=CLI_config,
            workflow_name=workflow_name,
            data_collection_tag=data_collection_tag,
            command_parameters=command_parameters,
        )

    elif mode == "process":
        # Keep existing processing logic
        from depictio.cli.cli.utils.process import process_project_data_collections

        return process_project_data_collections(
            CLI_config=CLI_config,
            project_config=project_config,
            workflow_name=workflow_name,
            data_collection_tag=data_collection_tag,
            command_parameters=command_parameters,
        )

    else:
        raise ValueError(f"Invalid mode: {mode}. Must be 'scan' or 'process'")


@validate_call
def process_data_collection_helper(
    CLI_config: CLIConfig,
    wf: Workflow,
    dc_id: str,
    command_parameters: dict[str, Any] = {},
    mode: str = "scan",
) -> dict[str, str] | dict:
    """_summary_

    Args:
        CLI_config (CLIConfig): _description_
        wf (Workflow): _description_
        dc_id (str): _description_
        rescan_folders (bool, optional): _description_. Defaults to False.
        update_files (bool, optional): _description_. Defaults to False.
    """
    task = "Scanning" if mode == "scan" else "Processing"
    dc = next((dc for dc in wf.data_collections if str(dc.id) == dc_id), None)
    if dc is None:
        raise ValueError(f"Data collection with id {dc_id} not found.")

    rich_print_checked_statement(
        f"  ↪ {task} Data Collection: [bold]{dc.data_collection_tag}[/bold] - type {dc.config.type} - metatype {dc.config.metatype}",
        # f"\t\t↪ Processing Data Collection: {dc.data_collection_tag} - type {dc.config.type} - metatype {dc.config.metatype}",
        "info",
    )
    logger.info(f"{task} Data collection: {dc.data_collection_tag}")
    logger.info(f"Mode: {mode}")

    if mode == "scan":
        result = scan_files_for_data_collection(
            workflow=wf,
            data_collection_id=dc_id,
            CLI_config=CLI_config,
            command_parameters=command_parameters,
        )
        return result
    elif mode == "process":
        logger.info("{task} data collection...")
        result = client_aggregate_data(
            data_collection=dc,
            CLI_config=CLI_config,
            command_parameters=command_parameters,
        )
        return result
    else:
        raise ValueError(f"Invalid mode: {mode}. Must be 'scan' or 'process'")
    # logger.info(f"Result: {result}")
    # if result["result"] == "success":
    #     rich_print_checked_statement(
    #         f"Data Collection {dc.data_collection_tag} processed successfully",
    #         "success",
    #     )
    # else:
    #     rich_print_checked_statement(f"Error: {result['message']}", "error")


# def process_workflow_helper(
#     CLI_config: CLIConfig,
#     workflow: Workflow,
#     data_collection_tag: str | None = None,
#     command_parameters: dict = {},
#     mode: str = "scan",
# ) -> None:
#     """
#     Process a workflow's data collections, optionally filtering by a specific data collection tag.

#     Args:
#         cli_config (dict): CLI configuration settings.
#         workflow (dict): Workflow configuration containing data collections.
#         data_collection_tag (str, optional): Specific data collection tag to process.
#                                              If None, all data collections are processed.
#         rescan_folders (bool, optional): Reprocess the runs for the data collections.
#         update_files (bool, optional): Update the files for the data collections.
#     """
#     task = "Scanning" if mode == "scan" else "Processing"
#     logger.info(f"{task} Workflow: {workflow.name}")
#     rich_print_checked_statement(
#         f" ↪ {task} Workflow: [bold]{workflow.workflow_tag}[/bold]", "info"
#     )

#     for data_collection in workflow.data_collections:
#         # Skip if a specific tag is provided and it doesn't match
#         if (
#             data_collection_tag
#             and data_collection.data_collection_tag.lower() != data_collection_tag.lower()
#         ):
#             logger.info(f"Skipping data collection: {data_collection.data_collection_tag}")
#             continue

#         # Process the matching data collection
#         logger.info(f"{task} data collection: {data_collection.data_collection_tag}")
#         dc_id = str(data_collection.id)
#         process_data_collection_helper(
#             CLI_config=CLI_config,
#             wf=workflow,
#             dc_id=dc_id,
#             command_parameters=command_parameters,
#             mode=mode,
#         )


# def process_project_helper(
#     CLI_config: CLIConfig,
#     project_config: Project,
#     workflow_name: str | None = None,
#     data_collection_tag: str | None = None,
#     command_parameters: dict = {},
#     mode: str = "scan",
# ):
#     """
#     Process workflows within a project, optionally filtering by workflow name.

#     Args:
#         cli_config (dict): CLI configuration settings.
#         project_config (dict): Project configuration containing workflows.
#         workflow_name (str, optional): Specific workflow name to process.
#                                        If None, all workflows are processed.
#         data_collection_tag (str, optional): Specific data collection tag to process.
#                                              If None, all data collections are processed.
#     """

#     task = "Scanning" if mode == "scan" else "Processing"
#     logger.info(f"Processing project: {project_config.name}")
#     rich_print_checked_statement(f"{task} Project: [bold]{project_config.name}[/bold]", "info")

#     # Determine which workflows to process
#     workflows = project_config.workflows

#     if workflow_name:
#         # Filter workflows if specific name requested
#         rich_print_checked_statement(f"Filtering workflows for name: {workflow_name}", "info")
#         workflows = [wf for wf in workflows if wf.name == workflow_name]

#         if not workflows:
#             logger.error(f"No workflow found with name: {workflow_name}")
#             rich_print_checked_statement(f"No workflow found with name: {workflow_name}", "error")

#     # Process selected workflows
#     for workflow in workflows:
#         logger.info(f"{task} workflow: {workflow.workflow_tag}")
#         process_workflow_helper(
#             CLI_config=CLI_config,
#             workflow=workflow,
#             data_collection_tag=data_collection_tag,
#             command_parameters=command_parameters,
#             mode=mode,
#         )
#         rich_print_checked_statement(
#             f"Workflow {workflow.workflow_tag} processed successfully", "success"
#         )
