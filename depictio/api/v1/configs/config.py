import os

from depictio.api.v1.configs.settings_models import Settings
from depictio.api.v1.utils import get_config, validate_config
from depictio.api.v1.crypto import run_generate_keys
from depictio.api.v1.configs.logging import logger

config_backend_location = os.getenv("DEPICTIO_CONFIG_BACKEND_LOCATION", "depictio/api/v1/configs/config_backend_dockercompose.yaml")
logger.info(f"Using config file: {config_backend_location}")

# Settings
# Overwrite priority: environment variables (.env) > config file (.yaml) > default values
settings = validate_config(get_config(config_backend_location), Settings)

API_BASE_URL = f"http://{settings.fastapi.service_name}:{settings.fastapi.port}"
DASH_BASE_URL = f"http://{settings.dash.service_name}:{settings.dash.port}"
MONGODB_URL = f"mongodb://{settings.mongodb.service_name}:{settings.mongodb.port}/"
# TOKEN = settings.auth.tmp_token
# TOKEN = TOKEN.strip()


# Check if key files exist, generate if they don't
run_generate_keys()


with open("depictio/keys/private_key.pem", "rb") as f:
    PRIVATE_KEY = f.read()
with open("depictio/keys/public_key.pem", "rb") as f:
    PUBLIC_KEY = f.read()
ALGORITHM = "RS256"

logger.info(f"API_BASE_URL: {API_BASE_URL}")
logger.info(f"MONGODB_URL: {MONGODB_URL}")
# logger.info(f"TOKEN: {TOKEN}")
