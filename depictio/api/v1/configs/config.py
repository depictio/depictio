from depictio.api.v1.configs.logging_init import initialize_loggers
from depictio.api.v1.configs.settings_models import Settings
from depictio.api.v1.key_utils import check_and_generate_keys

# Explicitly load environment variables
# load_dotenv(BASE_PATH.parent / ".env", override=False)

# Settings
# Overwrite priority: environment variables (.env) > config file (.yaml) > default values
settings = Settings()

# Initialize all loggers with the verbosity level from settings
initialize_loggers(verbose_level=settings.logging.verbosity_level)

API_BASE_URL = settings.fastapi.internal_url
DASH_BASE_URL = settings.viewer.internal_url


def _build_mongodb_url() -> str:
    cfg = settings.mongodb
    if cfg.username and cfg.password:
        pw = cfg.password.get_secret_value()
        url = f"mongodb://{cfg.username}:{pw}@{cfg.service_name}:{cfg.service_port}"
        params = [f"authSource={cfg.auth_source}"]
        if cfg.replica_set:
            params.append(f"replicaSet={cfg.replica_set}")
        return f"{url}/?{'&'.join(params)}"
    return f"mongodb://{cfg.service_name}:{cfg.service_port}"


MONGODB_URL = _build_mongodb_url()
_KEYS_DIR = settings.auth.keys_dir
# The internal API key is now automatically managed via the computed field
# No manual assignment needed - it checks environment variables and generates/reads from file


# Algorithm used for signing
ALGORITHM = settings.auth.keys_algorithm

# Generate keys only if missing (file-locked to avoid races between workers
# sharing the keys volume). Key rotation is done by deleting the keys dir
# (e.g. the Helm demo wipe-job removes the keys PVC pre-upgrade) — never by
# wiping at import time: with >1 replica each pod would wipe the others' keys
# and end up holding a different in-memory pair, so ~half of all JWTs would
# be rejected with "Signature verification failed".
check_and_generate_keys(keys_dir=_KEYS_DIR, algorithm=ALGORITHM)

# Canonical key file locations — consumers load keys via
# key_utils.get_private_key / get_public_key, which re-read on file change.
PRIVATE_KEY_PATH = _KEYS_DIR / "private_key.pem"
PUBLIC_KEY_PATH = _KEYS_DIR / "public_key.pem"

# Generate/load the internal API key during startup (creates api_internal_key.pem file)
# This ensures the key file exists before other services (frontend, celery) need it
_INTERNAL_API_KEY = settings.auth.internal_api_key
