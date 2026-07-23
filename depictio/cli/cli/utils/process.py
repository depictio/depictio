# depictio/cli/cli/utils/process.py

import os

from depictio.cli.cli.utils.rich_utils import (
    rich_print_checked_statement,
)
from depictio.cli.cli_logging import logger
from depictio.models.models.cli import CLIConfig

# Upper bound on the DC pool. Each worker holds a full dataset in memory during
# its collect/write, so the cap is about RAM, not CPU: 4 concurrent 1 GB
# aggregations is already ~8 GB of peak RSS on the default (non-streaming) path.
_MAX_DC_WORKERS = 4


def data_collection_workers(n_data_collections: int) -> int:
    """How many data collections to ingest concurrently (1 = sequential).

    Opt-in via ``DEPICTIO_INGEST_DC_WORKERS`` (new features default off). The
    result is clamped to the number of DCs and to :data:`_MAX_DC_WORKERS`, so an
    over-large value degrades to the cap rather than spawning a thread per DC.
    """
    raw = os.getenv("DEPICTIO_INGEST_DC_WORKERS", "").strip()
    if not raw:
        return 1
    try:
        requested = int(raw)
    except ValueError:
        logger.warning(f"Invalid DEPICTIO_INGEST_DC_WORKERS={raw!r}; ingesting sequentially.")
        return 1
    return max(1, min(requested, _MAX_DC_WORKERS, n_data_collections))


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
    rich_print_checked_statement(
        f"Processing Project: [italic]'{project_config.name}'[/italic]", "info"
    )

    # Cross-DC links live on the project, but the columns they match on are
    # needed down in the per-DC write (to cluster the Delta table on the key it
    # will be filtered by). Resolve them once here and carry them alongside the
    # other run-level options rather than re-deriving them per DC. Rebuilt, not
    # mutated in place, so a caller's dict is left alone (and ``None`` becomes
    # the empty defaults the rest of this function already assumed).
    from depictio.cli.cli.utils.deltatables import link_columns_by_dc

    command_parameters = {
        **(command_parameters or {}),
        "link_columns_by_dc": link_columns_by_dc(project_config),
    }

    # Filter workflows if specific workflow_name is provided
    workflows_to_process = project_config.workflows
    if workflow_name:
        workflows_to_process = [w for w in workflows_to_process if w.workflow_tag == workflow_name]
        if not workflows_to_process:
            raise Exception(f"Workflow '{workflow_name}' not found in project")

    total_processed = 0
    failed_tags: list[str] = []
    skipped_optional: list[str] = []

    for workflow in workflows_to_process:
        rich_print_checked_statement(
            f" ↪ Processing Workflow: [italic]'{workflow.workflow_tag}'[/italic]", "info"
        )

        # Filter data collections if specific data_collection_tag is provided
        data_collections_to_process = workflow.data_collections

        # Note: Image DCs are now processed like Table DCs (they have delta tables)
        # No special skipping needed

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

        # Ingest the data collections, then report. Reporting is deliberately a
        # second, sequential pass over the original order: with a worker pool the
        # completion order is arbitrary, and interleaving rich output from several
        # threads would scramble the console. Splitting the two keeps the printed
        # summary byte-identical to the sequential path.
        outcomes = _ingest_data_collections(
            workflow=workflow,
            data_collections=data_collections_to_process,
            CLI_config=CLI_config,
            command_parameters=command_parameters,
        )

        for dc, result, error in outcomes:
            try:
                if error is not None:
                    raise error

                if result["success"]:
                    rich_print_checked_statement(
                        f"  ✓ Data collection [italic]'{dc.data_collection_tag}'[/italic] processed successfully. {result['data']['message']}",
                        "success",
                    )
                    total_processed += 1
                elif getattr(dc, "optional", False):
                    # Optional DCs whose inputs are absent (missing dc_ref / source
                    # file) are skipped, not failed: e.g. seed-only advanced-viz
                    # canonical DCs that depend on intermediate DCs not produced by
                    # a plain CLI ingestion. They stay populated from committed seeds.
                    rich_print_checked_statement(
                        f"  ⊘ Skipped optional data collection '{dc.data_collection_tag}': {result.get('message', 'inputs unavailable')}",
                        "warning",
                    )
                    skipped_optional.append(dc.data_collection_tag)
                else:
                    rich_print_checked_statement(
                        f"  ✗ Failed to process data collection '{dc.data_collection_tag}': {result.get('message', 'Unknown error')}",
                        "error",
                    )
                    failed_tags.append(dc.data_collection_tag)

            except Exception as e:
                if getattr(dc, "optional", False):
                    rich_print_checked_statement(
                        f"  ⊘ Skipped optional data collection '{dc.data_collection_tag}': {e}",
                        "warning",
                    )
                    logger.info(f"Optional DC {dc.data_collection_tag} skipped: {e}")
                    skipped_optional.append(dc.data_collection_tag)
                    continue
                rich_print_checked_statement(
                    f"  ✗ Error processing data collection '{dc.data_collection_tag}': {e}",
                    "error",
                )
                logger.error(f"Detailed error for {dc.data_collection_tag}: {e}", exc_info=True)
                failed_tags.append(dc.data_collection_tag)

        rich_print_checked_statement(
            f"Workflow {workflow.workflow_tag} processing completed", "success"
        )

    skipped_note = (
        f" ({len(skipped_optional)} optional skipped: {', '.join(skipped_optional)})"
        if skipped_optional
        else ""
    )
    if failed_tags:
        rich_print_checked_statement(
            f"Processing completed with failures: {total_processed} processed, "
            f"{len(failed_tags)} failed ({', '.join(failed_tags)}){skipped_note}",
            "warning",
        )
    else:
        rich_print_checked_statement(
            f"Processing completed! Total data collections processed: "
            f"{total_processed}{skipped_note}",
            "success",
        )

    return {
        "result": "partial" if failed_tags else "success",
        "total_processed": total_processed,
        "total_failed": len(failed_tags),
        "failed_tags": failed_tags,
        "skipped_optional": skipped_optional,
    }


def _ingest_data_collections(
    workflow,
    data_collections: list,
    CLI_config: CLIConfig,
    command_parameters: dict | None,
) -> list[tuple]:
    """Ingest every DC, returning ``(dc, result, error)`` in **input order**.

    Data collections are independent — each scans its own files and writes its
    own delta table — so they can overlap. The work is I/O-bound (S3 upload plus
    API round-trips, which measurably dominate: at 100 MB the upsert alone was
    ~4.3 s of a 7.4 s ingest), and polars releases the GIL for the CPU-bound
    parts, so threads are enough; processes would force the config and clients to
    be pickled for no gain.

    Exceptions are captured rather than raised so one failing DC cannot abandon
    the others mid-flight — the caller re-raises them during its reporting pass,
    preserving the original per-DC error handling.
    """
    workers = data_collection_workers(len(data_collections))

    def run_one(dc):
        try:
            return (
                dc,
                process_single_data_collection(
                    workflow=workflow,
                    data_collection=dc,
                    CLI_config=CLI_config,
                    command_parameters=command_parameters,
                ),
                None,
            )
        except Exception as exc:
            return dc, None, exc

    if workers <= 1:
        return [run_one(dc) for dc in data_collections]

    logger.info(f"Ingesting {len(data_collections)} data collections with {workers} workers")
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=workers) as pool:
        # ``map`` yields in submission order, which is what the reporting pass wants.
        return list(pool.map(run_one, data_collections))


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

        # Check if the processing actually succeeded
        if result.get("result") == "success":
            return {
                "success": True,
                "message": f"Data collection {data_collection.data_collection_tag} processed successfully",
                "data": result,
            }
        else:
            return {
                "success": False,
                "message": f"Failed to process data collection {data_collection.data_collection_tag}: {result.get('message', 'Unknown error')}",
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
