import os
from depictio.api.v1.configs.settings_models import Settings
from depictio.api.v1.key_utils import (
    load_private_key,
    load_public_key,
)
from depictio.api.v1.configs.custom_logging import logger


# Settings
# Overwrite priority: environment variables (.env) > config file (.yaml) > default values
settings = Settings()
logger.info(f"Settings: {settings}")
API_BASE_URL = f"http://{settings.fastapi.service_name}:{settings.fastapi.port}"
DASH_BASE_URL = f"http://{settings.dash.service_name}:{settings.dash.port}"
MONGODB_URL = f"mongodb://{settings.mongodb.service_name}:{settings.mongodb.port}/"
_KEYS_DIR = settings.auth.keys_dir
# Use the shared internal API key from settings
FASTAPI_INTERNAL_API_KEY = os.getenv("DEPICTIO_INTERNAL_API_KEY", settings.fastapi.internal_api_key)
ALGORITHM = settings.auth.keys_algorithm


PRIVATE_KEY = load_private_key(
    settings.auth.keys_dir + "/private_key.pem"
)  # Load private key from file
PUBLIC_KEY = load_public_key(
    settings.auth.keys_dir + "/public_key.pem"
)  # Load public key from file

logger.info(f"Private key value: {PRIVATE_KEY}")
logger.info(f"Public key value: {PUBLIC_KEY}")
