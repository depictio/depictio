import logging
import os

from depictio.api.v1.configs.settings_models import Settings
from depictio.api.v1.utils import get_config, validate_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(filename)s - %(funcName)s - line %(lineno)d - %(message)s")
logger = logging.getLogger("depictio")

config_backend_location = os.getenv("DEPICTIO_CONFIG_BACKEND_LOCATION", "depictio/api/v1/configs/config_backend_dockercompose.yaml")
logger.info(f"Using config file: {config_backend_location}")   

# Settings
# Overwrite priority: environment variables (.env) > config file (.yaml) > default values
settings = validate_config(get_config(config_backend_location), Settings)

API_BASE_URL = f"http://{settings.fastapi.service_name}:{settings.fastapi.port}"
MONGODB_URL = f"mongodb://{settings.mongodb.service_name}:{settings.mongodb.port}/"
TOKEN = settings.auth.tmp_token
TOKEN = TOKEN.strip()

logger.info(f"API_BASE_URL: {API_BASE_URL}")
logger.info(f"MONGODB_URL: {MONGODB_URL}")
logger.info(f"TOKEN: {TOKEN}")