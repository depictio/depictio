from depictio.models.models.data_collections import DataCollection


def compare_models(workflow_yaml: dict, workflow_db: dict) -> bool:
    """
    Compare two workflow dictionaries for equality, excluding dynamic fields.

    Args:
        workflow_yaml: Workflow dictionary from YAML configuration
        workflow_db: Workflow dictionary from database

    Returns:
        True if workflows are equivalent, False otherwise
    """
    set_checks = []

    workflow_yaml_only = workflow_yaml.copy()
    workflow_yaml_only.pop("registration_time", None)
    workflow_db_only = workflow_db.copy()
    workflow_db_only.pop("registration_time", None)
    set_checks.append(workflow_yaml_only == workflow_db_only)

    for dc_yaml, dc_db in zip(
        workflow_yaml_only["data_collections"], workflow_db_only["data_collections"]
    ):
        dc_yaml = DataCollection(**dc_yaml)
        dc_yaml_only = dc_yaml.model_dump(exclude={"registration_time"})
        dc_db = DataCollection(**dc_db)
        dc_db_only = dc_db.model_dump(exclude={"registration_time"})
        set_checks.append(dc_yaml_only == dc_db_only)

    return set(set_checks) == {True}
