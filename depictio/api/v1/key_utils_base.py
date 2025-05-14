"""Base cryptographic key management utilities without logger dependencies."""

import hashlib
import os
from pathlib import Path
from typing import Literal

from pydantic import validate_call

# Type definitions
Algorithm = Literal["RS256", "RS512", "ES256", "SHA256"]


@validate_call(validate_return=True)
def _load_or_generate_api_internal_key(
    keys_dir: Path = Path("./depictio/keys"),
    algorithm: Algorithm = "RS256",
) -> str:
    """Check if the API internal key is set in the environment.

    Returns:
        API internal key if set, otherwise generates a new one
    """
    key_path = os.path.join(keys_dir, "api_internal_key.pem")

    # Create the directory if it doesn't exist
    os.makedirs(os.path.dirname(key_path), exist_ok=True)

    if os.path.exists(key_path):
        with open(key_path) as f:
            key = f.read().strip()
            return key
    else:
        key = _generate_api_internal_key()
        with open(key_path, "w") as f:
            f.write(key)
        return key


@validate_call(validate_return=True)
def _generate_api_internal_key() -> str:
    """Generate a consistent API internal key.

    Returns:
        Consistently generated API internal key
    """
    # Use a combination of environment variables and a salt to generate a consistent key
    salt = "DEPICTIO_INTERNAL_KEY_SALT"
    base_key = os.getenv("DEPICTIO_INTERNAL_API_KEY", "")

    # If no base key exists, generate a persistent key
    if not base_key:
        # Generate a hash based on a combination of system information
        system_info = f"{os.getpid()}:{os.getuid()}:{salt}"
        base_key = hashlib.sha256(system_info.encode()).hexdigest()

        # Set the environment variable to persist the key
        os.environ["DEPICTIO_INTERNAL_API_KEY"] = base_key

    return base_key
