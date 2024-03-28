from depictio.api.v1.configs.settings_models import Settings
from depictio.api.v1.utils import get_config, validate_config

settings = validate_config(
    get_config("depictio/api/v1/configs/config_backend.yaml"), Settings
)

import logging
logging.basicConfig(level=logging.INFO)
# Create logger
logger = logging.getLogger(__name__)



API_BASE_URL = f"http://{settings.fastapi.host}:{settings.fastapi.port}"
MONGODB_URL = f"mongodb://{settings.mongodb.host}:{settings.mongodb.port}/"
print("MONGODB_URL: ", MONGODB_URL)
TOKEN = settings.auth.tmp_token

