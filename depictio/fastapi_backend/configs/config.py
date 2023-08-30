from pydantic import BaseModel, ValidationError, validator
import yaml

from depictio.fastapi_backend.configs.models import (
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
from depictio.fastapi_backend.utils import get_config, validate_config, validate_all_workflows

config = validate_config(get_config("depictio/fastapi_backend/configs/config.yaml"), RootConfig)

validated_config = validate_all_workflows(config)
# print(validated_config)

settings = validate_config(
    get_config("depictio/fastapi_backend/configs/config_backend.yaml"), Settings
)
