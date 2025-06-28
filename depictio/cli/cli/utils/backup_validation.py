import json
from datetime import datetime
from typing import Any, Dict, List

from depictio.cli.cli_logging import logger
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.deltatables import DeltaTableAggregated
from depictio.models.models.files import File
from depictio.models.models.projects import Project
from depictio.models.models.users import GroupBeanie, User
from depictio.models.models.workflows import Workflow, WorkflowRun


def validate_backup_file(backup_path: str) -> Dict[str, Any]:
    """
    Validate a backup file against Pydantic models.

    Args:
        backup_path: Path to the backup file to validate

    Returns:
        dict: Validation results including status and details
    """
    try:
        logger.info(f"Starting validation of backup file: {backup_path}")

        # Load backup file
        with open(backup_path, "r") as f:
            backup_data = json.load(f)

        validation_results = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "collections_validated": {},
            "total_documents": 0,
            "valid_documents": 0,
            "invalid_documents": 0,
            "timestamp": datetime.now().isoformat(),
        }

        # Check backup structure
        if "backup_metadata" not in backup_data:
            validation_results["errors"].append("Missing backup_metadata section")
            validation_results["valid"] = False

        if "data" not in backup_data:
            validation_results["errors"].append("Missing data section")
            validation_results["valid"] = False
            return validation_results

        data_section = backup_data["data"]

        # Define collection validators (tokens excluded)
        collection_validators = {
            "users": User,
            "projects": Project,
            "dashboards": DashboardData,
            "data_collections": DataCollection,
            "workflows": Workflow,
            "runs": WorkflowRun,
            "files": File,
            # "tokens": TokenBeanie,  # Excluded to avoid circular dependency
            "deltatables": DeltaTableAggregated,
            "groups": GroupBeanie,
        }

        # Validate each collection
        for collection_name, documents in data_section.items():
            logger.info(f"Validating collection: {collection_name}")

            collection_results = {"total": len(documents), "valid": 0, "invalid": 0, "errors": []}

            # Skip validation for collections without Pydantic models
            if collection_name not in collection_validators:
                validation_results["warnings"].append(
                    f"No Pydantic model available for collection '{collection_name}', skipping validation"
                )
                collection_results["valid"] = len(documents)
                validation_results["collections_validated"][collection_name] = collection_results
                validation_results["total_documents"] += len(documents)
                validation_results["valid_documents"] += len(documents)
                continue

            model_class = collection_validators[collection_name]

            # Validate each document in the collection
            for i, document in enumerate(documents):
                try:
                    # Try to create model instance from document
                    if collection_name == "dashboards":
                        # DashboardData uses from_mongo method
                        _ = model_class.from_mongo(document)
                    else:
                        # Other models use standard Pydantic validation
                        _ = model_class(**document)

                    collection_results["valid"] += 1
                    validation_results["valid_documents"] += 1

                except Exception as e:
                    error_msg = f"Document {i} in {collection_name}: {str(e)}"
                    collection_results["errors"].append(error_msg)
                    collection_results["invalid"] += 1
                    validation_results["invalid_documents"] += 1
                    validation_results["errors"].append(error_msg)

            validation_results["collections_validated"][collection_name] = collection_results
            validation_results["total_documents"] += len(documents)

            logger.info(
                f"Collection {collection_name}: {collection_results['valid']}/{collection_results['total']} valid"
            )

        # Determine overall validation status
        if validation_results["invalid_documents"] > 0:
            validation_results["valid"] = False

        # Add summary to results
        validation_results["summary"] = {
            "collections_count": len(data_section),
            "total_documents": validation_results["total_documents"],
            "valid_documents": validation_results["valid_documents"],
            "invalid_documents": validation_results["invalid_documents"],
            "validation_success_rate": (
                validation_results["valid_documents"] / validation_results["total_documents"] * 100
                if validation_results["total_documents"] > 0
                else 0
            ),
        }

        logger.info(f"Backup validation completed: {validation_results['summary']}")

        return validation_results

    except FileNotFoundError:
        return {
            "valid": False,
            "errors": [f"Backup file not found: {backup_path}"],
            "warnings": [],
            "collections_validated": {},
            "total_documents": 0,
            "valid_documents": 0,
            "invalid_documents": 0,
        }
    except json.JSONDecodeError as e:
        return {
            "valid": False,
            "errors": [f"Invalid JSON format: {str(e)}"],
            "warnings": [],
            "collections_validated": {},
            "total_documents": 0,
            "valid_documents": 0,
            "invalid_documents": 0,
        }
    except Exception as e:
        logger.error(f"Backup validation failed: {str(e)}")
        return {
            "valid": False,
            "errors": [f"Validation failed: {str(e)}"],
            "warnings": [],
            "collections_validated": {},
            "total_documents": 0,
            "valid_documents": 0,
            "invalid_documents": 0,
        }


# Expected collections that should be backed up
# If a new collection is added to settings, add it here or tests will fail
EXPECTED_BACKUP_COLLECTIONS = [
    "users",
    "projects",
    "dashboards",
    "data_collections",
    "workflows",
    "runs",
    "files",
    # "tokens",  # Excluded to avoid circular dependency in backup/restore
    "deltatables",
    "groups",
]


def check_backup_collections_coverage() -> Dict[str, Any]:
    """
    Simple check to ensure all expected collections have backup coverage.

    If a new collection is added to settings but not to EXPECTED_BACKUP_COLLECTIONS,
    this will detect it and tests should fail.

    Returns:
        dict: Report of collection coverage
    """
    try:
        from depictio.api.v1.configs.config import settings

        # Get all collection names from settings
        collections_in_settings = []
        for attr_name in dir(settings.mongodb.collections):
            if not attr_name.startswith("_"):
                collection_name = getattr(settings.mongodb.collections, attr_name)
                if isinstance(collection_name, str):
                    collections_in_settings.append(collection_name)

        # Define validators (same as in validate_backup_file)
        collection_validators = {
            "users": User,
            "projects": Project,
            "dashboards": DashboardData,
            "data_collections": DataCollection,
            "workflows": Workflow,
            "runs": WorkflowRun,
            "files": File,
            # "tokens": TokenBeanie,  # Excluded to avoid circular dependency
            "deltatables": DeltaTableAggregated,
            "groups": GroupBeanie,
        }

        # Check against expected collections
        expected_set = set(EXPECTED_BACKUP_COLLECTIONS)
        validators_set = set(collection_validators.keys())
        settings_set = set(collections_in_settings)

        # Find issues
        missing_validators = expected_set - validators_set

        # Only consider core collections (filter out utility collections like 'test', 'initialization')
        # Also exclude 'tokens' which is intentionally excluded from backup/restore
        core_collections = {
            col
            for col in collections_in_settings
            if col not in ["test", "initialization", "jbrowse", "tokens"]
        }
        missing_from_expected_core = core_collections - expected_set

        return {
            "valid": len(missing_from_expected_core) == 0 and len(missing_validators) == 0,
            "expected_collections": list(expected_set),
            "collections_with_validators": list(validators_set),
            "collections_in_settings": list(settings_set),
            "missing_from_expected": list(
                missing_from_expected_core
            ),  # New collections not in expected list
            "missing_validators": list(
                missing_validators
            ),  # Expected collections without validators
            "errors": [],
        }

    except ImportError as e:
        return {
            "valid": False,
            "error": f"Could not import settings: {e}",
            "errors": ["Unable to check collection coverage - settings not available"],
        }
    except Exception as e:
        return {
            "valid": False,
            "error": f"Error checking collections: {e}",
            "errors": ["Unable to check collection coverage due to error"],
        }


def validate_backup_metadata(backup_data: Dict[str, Any]) -> List[str]:
    """
    Validate backup metadata structure.

    Args:
        backup_data: The loaded backup data

    Returns:
        List of validation errors
    """
    errors = []

    if "backup_metadata" not in backup_data:
        errors.append("Missing backup_metadata section")
        return errors

    metadata = backup_data["backup_metadata"]
    required_fields = ["timestamp", "created_by", "total_documents", "collections"]

    for field in required_fields:
        if field not in metadata:
            errors.append(f"Missing required metadata field: {field}")

    # Validate timestamp format
    if "timestamp" in metadata:
        try:
            datetime.fromisoformat(metadata["timestamp"])
        except ValueError:
            errors.append("Invalid timestamp format in metadata")

    return errors
