from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.data_collections import DataCollection


def compare_models(workflow_yaml: dict, workflow_db: dict) -> bool:
    """
    Compare the workflow data dictionary with the retrieved workflow JSON.
    """
    logger.info(f"Workflow YAML: {workflow_yaml}")
    logger.info(f"Workflow DB: {workflow_db}")

    # Compare the workflow data dictionary with the retrieved workflow JSON - excluding dynamic fields
    set_checks = []
    # workflow_yaml_only = Workflow(**workflow_yaml)
    workflow_yaml_only = workflow_yaml.copy()  # type: ignore[unresolved-attribute]
    workflow_yaml_only.pop("registration_time", None)
    # workflow_db_only = Workflow(**workflow_db)
    workflow_db_only = workflow_db.copy()  # type: ignore[unresolved-attribute]
    workflow_db_only.pop("registration_time", None)
    set_checks.append(workflow_yaml_only == workflow_db_only)

    # Compare the data collections
    for dc_yaml, dc_db in zip(
        workflow_yaml_only["data_collections"], workflow_db_only["data_collections"]
    ):
        dc_yaml = DataCollection(**dc_yaml)  # type: ignore[missing-argument]
        dc_yaml_only = dc_yaml.dict(exclude={"registration_time"})
        dc_db = DataCollection(**dc_db)  # type: ignore[missing-argument]
        dc_db_only = dc_db.dict(exclude={"registration_time"})
        set_checks.append(dc_yaml_only == dc_db_only)

    # Check if workflow and data collections are the same between the YAML and the DB
    return set(set_checks) == {True}
