from typing import Optional

from pydantic import validate_call
from typeguard import typechecked

from depictio.cli.cli.utils.deltatables import client_aggregate_data
from depictio.cli.cli.utils.rich_utils import (
    rich_print_checked_statement,
)
from depictio.cli.cli.utils.scan import scan_files_for_data_collection
from depictio.cli.cli_logging import logger
from depictio.models.models.projects import Project, Workflow
from depictio.models.models.users import CLIConfig


@validate_call
def process_data_collection_helper(
    CLI_config: CLIConfig,
    wf: Workflow,
    dc_id: str,
    command_parameters: dict = {},
    mode: str = "scan",
) -> None:
    """_summary_

    Args:
        CLI_config (CLIConfig): _description_
        wf (Workflow): _description_
        dc_id (str): _description_
        rescan_folders (bool, optional): _description_. Defaults to False.
        update_files (bool, optional): _description_. Defaults to False.
    """
    dc = next((dc for dc in wf.data_collections if str(dc.id) == dc_id), None)
    if dc is None:
        raise ValueError(f"Data collection with id {dc_id} not found.")

    print("\n")
    rich_print_checked_statement(
        f"Processing Data Collection: {dc.data_collection_tag} - type {dc.config.type} - metatype {dc.config.metatype}",
        "info",
    )
    logger.info(f"Processing Data collection: {dc.data_collection_tag}")
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
        logger.info("Processing data collection...")
        print("Processing data collection...")
        result = client_aggregate_data(
            data_collection=dc,
            CLI_config=CLI_config,
            command_parameters=command_parameters,
        )
        return result
    logger.info(f"Result: {result}")
    if result["result"] == "success":
        rich_print_checked_statement(
            f"Data Collection {dc.data_collection_tag} processed successfully",
            "success",
        )
    else:
        rich_print_checked_statement(f"Error: {result['message']}", "error")


@typechecked
def process_workflow_helper(
    CLI_config: CLIConfig,
    workflow: Workflow,
    data_collection_tag: Optional[str] = None,
    command_parameters: dict = {},
    mode: str = "scan",
) -> None:
    """
    Process a workflow's data collections, optionally filtering by a specific data collection tag.

    Args:
        cli_config (dict): CLI configuration settings.
        workflow (dict): Workflow configuration containing data collections.
        data_collection_tag (str, optional): Specific data collection tag to process.
                                             If None, all data collections are processed.
        rescan_folders (bool, optional): Reprocess the runs for the data collections.
        update_files (bool, optional): Update the files for the data collections.
    """
    logger.info(f"Processing Workflow: {workflow.name}")
    rich_print_checked_statement(
        f"Processing Workflow: {workflow.workflow_tag}", "info"
    )

    for data_collection in workflow.data_collections:
        # Skip if a specific tag is provided and it doesn't match
        if (
            data_collection_tag
            and data_collection.data_collection_tag.lower()
            != data_collection_tag.lower()
        ):
            logger.info(
                f"Skipping data collection: {data_collection.data_collection_tag}"
            )
            continue

        # Process the matching data collection
        logger.info(
            f"Processing data collection: {data_collection.data_collection_tag}"
        )
        dc_id = str(data_collection.id)
        process_data_collection_helper(
            CLI_config=CLI_config,
            wf=workflow,
            dc_id=dc_id,
            command_parameters=command_parameters,
            mode=mode,
        )


@typechecked
def process_project_helper(
    CLI_config: CLIConfig,
    project_config: Project,
    workflow_name: Optional[str] = None,
    data_collection_tag: Optional[str] = None,
    command_parameters: dict = {},
    mode: str = "scan",
):
    """
    Process workflows within a project, optionally filtering by workflow name.

    Args:
        cli_config (dict): CLI configuration settings.
        project_config (dict): Project configuration containing workflows.
        workflow_name (str, optional): Specific workflow name to process.
                                       If None, all workflows are processed.
        data_collection_tag (str, optional): Specific data collection tag to process.
                                             If None, all data collections are processed.
    """
    logger.info(f"Processing project: {project_config.name}")
    rich_print_checked_statement(f"Processing Project: {project_config.name}", "info")

    # Determine which workflows to process
    workflows = project_config.workflows

    if workflow_name:
        # Filter workflows if specific name requested
        rich_print_checked_statement(
            f"Filtering workflows for name: {workflow_name}", "info"
        )
        workflows = [wf for wf in workflows if wf.name == workflow_name]

        if not workflows:
            logger.error(f"No workflow found with name: {workflow_name}")
            rich_print_checked_statement(
                f"No workflow found with name: {workflow_name}", "error"
            )

    # Process selected workflows
    for workflow in workflows:
        print("\n")
        logger.info(f"Processing workflow: {workflow.workflow_tag}")
        process_workflow_helper(
            CLI_config=CLI_config,
            workflow=workflow,
            data_collection_tag=data_collection_tag,
            command_parameters=command_parameters,
            mode=mode,
        )
        rich_print_checked_statement(
            f"Workflow {workflow.workflow_tag} processed successfully", "success"
        )
