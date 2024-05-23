import logging

from depictio.api.v1.configs.settings_models import Settings
from depictio.api.v1.utils import get_config, validate_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(filename)s - %(funcName)s - line %(lineno)d - %(message)s")
logger = logging.getLogger("depictio")

# Settings
# Overwrite priority: environment variables (.env) > config file (.yaml) > default values
settings = validate_config(get_config("depictio/api/v1/configs/config_backend.yaml"), Settings)

API_BASE_URL = f"http://{settings.fastapi.service_name}:{settings.fastapi.port}"
MONGODB_URL = f"mongodb://{settings.mongodb.service_name}:{settings.mongodb.port}/"
TOKEN = settings.auth.tmp_token


# Load your private key from the settings
PRIVATE_KEY = settings.auth.private_key.encode() if settings.auth.private_key else None
# Load your public key from the settings
PUBLIC_KEY = settings.auth.public_key.encode() if settings.auth.public_key else None

ALGORITHM = "RS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 360 * 3600

if not PRIVATE_KEY or not PUBLIC_KEY:
    logger.error("Private or public key not found in environment variables.")
else:
    logger.info("Private and public keys successfully loaded.")