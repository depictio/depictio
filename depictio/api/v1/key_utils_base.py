"""Base cryptographic key management utilities without logger dependencies."""

import os
import secrets
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
        # Secret key material: create with owner-only permissions (0600).
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(key)
        return key


@validate_call(validate_return=True)
def _generate_api_internal_key() -> str:
    """Generate a cryptographically random API internal key.

    Returns:
        Random 256-bit hex key, persisted via the shared keys volume
    """
    base_key = os.getenv("DEPICTIO_INTERNAL_API_KEY", "")

    if not base_key:
        base_key = secrets.token_hex(32)
        os.environ["DEPICTIO_INTERNAL_API_KEY"] = base_key

    return base_key
