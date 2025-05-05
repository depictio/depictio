import os
from pathlib import Path

# from depictio.api.v1.configs.config import settings


# Determine base path for keys
def _get_base_keys_dir():
    """
    Determine the base directory for storing keys.
    Prioritizes environment variable, then falls back to project-relative paths.
    """
    # Check environment variable first
    env_key_dir = os.getenv("DEPICTIO_KEYS_DIR", None)
    if env_key_dir:
        return Path(env_key_dir)

    # Fallback to project-relative path
    # This works in local dev, pytest, and can be mounted in containers
    return Path(__file__).parent.parent.parent.parent.parent / "keys"


# Ensure keys directory exists
_KEYS_DIR = _get_base_keys_dir()
_KEYS_DIR.mkdir(parents=True, exist_ok=True)

# Default key file paths
DEFAULT_PRIVATE_KEY_PATH = str(_KEYS_DIR / "private_key.pem")
DEFAULT_PUBLIC_KEY_PATH = str(_KEYS_DIR / "public_key.pem")
