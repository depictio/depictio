import logging

from depictio.api.v1.configs.settings_models import Settings
from depictio.api.v1.utils import get_config, validate_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(filename)s - %(funcName)s - line %(lineno)d - %(message)s")
logger = logging.getLogger("depictio")

settings = validate_config(get_config("depictio/api/v1/configs/config_backend.yaml"), Settings)

API_BASE_URL = f"http://{settings.fastapi.host}:{settings.fastapi.port}"
MONGODB_URL = f"mongodb://{settings.mongodb.host}:{settings.mongodb.port}/"
TOKEN = settings.auth.tmp_token
