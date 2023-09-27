from pydantic import BaseModel, ValidationError, validator
import yaml

from depictio.api.v1.configs.models import (
    RootConfig,
    Settings,
    # WorkflowConfig,
    # FileConfig,
    # File,
    # DataCollection,
    # DataCollectionConfig,
    # Workflow,
    # Collections,
    # Config,
)
from depictio.api.v1.utils import get_config, validate_config, validate_all_workflows

config = validate_config(get_config("depictio/api/v1/configs/config.yaml"), RootConfig)

validated_config = validate_all_workflows(config)
# print(validated_config)

settings = validate_config(
    get_config("depictio/api/v1/configs/config_backend.yaml"), Settings
)
