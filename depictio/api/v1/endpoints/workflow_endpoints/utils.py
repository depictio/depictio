
# from depictio.api.v1.endpoints.datacollections_endpoints.models import DataCollection
# from depictio.api.v1.endpoints.workflow_endpoints.models import Workflow
from depictio.api.v1.configs.logging import logger

from depictio_models.models.data_collections import DataCollection
from depictio_models.models.workflows import Workflow

logger.info("Imported utils.py")


def compare_models(workflow_yaml: dict, workflow_db: dict) -> bool:

    """
    Compare the workflow data dictionary with the retrieved workflow JSON.
    """
    logger.info(f"Workflow YAML: {workflow_yaml}")
    logger.info(f"Workflow DB: {workflow_db}")

    # Compare the workflow data dictionary with the retrieved workflow JSON - excluding dynamic fields
    set_checks = []
    # workflow_yaml_only = Workflow(**workflow_yaml)
    workflow_yaml_only = workflow_yaml.dict(exclude={"registration_time"})
    # workflow_db_only = Workflow(**workflow_db)
    workflow_db_only = workflow_db.dict(exclude={"registration_time"})
    set_checks.append(workflow_yaml_only == workflow_db_only)

    # Compare the data collections
    for dc_yaml, dc_db in zip(workflow_yaml_only["data_collections"], workflow_db_only["data_collections"]):
        dc_yaml = DataCollection(**dc_yaml)
        dc_yaml_only = dc_yaml.dict(exclude={"registration_time"})
        dc_db = DataCollection(**dc_db)
        dc_db_only = dc_db.dict(exclude={"registration_time"})
        set_checks.append(dc_yaml_only == dc_db_only)

    # Check if workflow and data collections are the same between the YAML and the DB
    return set(set_checks) == {True}
