from depictio.api.v1.configs.logging_init import initialize_loggers
from depictio.api.v1.configs.settings_models import Settings
from depictio.api.v1.key_utils import (
    check_and_generate_keys,
    generate_keys,
    load_private_key,
    load_public_key,
)

# Explicitly load environment variables
# load_dotenv(BASE_PATH.parent / ".env", override=False)

# Settings
# Overwrite priority: environment variables (.env) > config file (.yaml) > default values
settings = Settings()

# Initialize all loggers with the verbosity level from settings
initialize_loggers(verbose_level=settings.logging.verbosity_level)

API_BASE_URL = settings.fastapi.internal_url
DASH_BASE_URL = settings.dash.internal_url
MONGODB_URL = f"mongodb://{settings.mongodb.service_name}:{settings.mongodb.service_port}"
_KEYS_DIR = settings.auth.keys_dir
# The internal API key is now automatically managed via the computed field
# No manual assignment needed - it checks environment variables and generates/reads from file


# Algorithm used for signing
ALGORITHM = settings.auth.keys_algorithm

# Lazy-loaded settings and paths
_KEYS_DIR = settings.auth.keys_dir
DEFAULT_PRIVATE_KEY_PATH = None
DEFAULT_PUBLIC_KEY_PATH = None

# Use check_and_generate_keys to avoid race conditions between workers
# Only use generate_keys with wipe when explicitly requested
if bool(settings.mongodb.wipe):
    # When wiping, we need to regenerate keys
    generate_keys(
        private_key_path=DEFAULT_PRIVATE_KEY_PATH,
        public_key_path=DEFAULT_PUBLIC_KEY_PATH,
        keys_dir=_KEYS_DIR,
        algorithm=ALGORITHM,
        wipe=True,
    )
else:
    # Normal case: only generate if keys don't exist (prevents race condition)
    check_and_generate_keys(
        private_key_path=DEFAULT_PRIVATE_KEY_PATH,
        public_key_path=DEFAULT_PUBLIC_KEY_PATH,
        keys_dir=_KEYS_DIR,
        algorithm=ALGORITHM,
    )

PRIVATE_KEY = load_private_key(
    settings.auth.keys_dir / "private_key.pem"
)  # Load private key from file
PUBLIC_KEY = load_public_key(settings.auth.keys_dir / "public_key.pem")  # Load public key from file

# Generate/load the internal API key during startup (creates api_internal_key.pem file)
# This ensures the key file exists before other services (frontend, celery) need it
_INTERNAL_API_KEY = settings.auth.internal_api_key
