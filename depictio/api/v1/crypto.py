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

# ── Symmetric secrets (Fernet) ──────────────────────────────────────────────
# Encrypt-at-rest for replayable credentials (e.g. per-project storage keys).
# Unlike passwords (bcrypt, one-way) these must be decrypted to be used, so
# they get a dedicated symmetric key generated-and-persisted alongside the JWT
# keypair. The key path honours DEPICTIO_KEYS_DIR at call time (not import
# time) so tests can point it at a temp directory.

_SECRETS_KEY_FILENAME = "secrets_key.bin"


def _secrets_key_path() -> Path:
    env_key_dir = os.getenv("DEPICTIO_KEYS_DIR", None)
    base = Path(env_key_dir) if env_key_dir else _KEYS_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / _SECRETS_KEY_FILENAME


def _load_or_generate_secrets_key() -> bytes:
    from cryptography.fernet import Fernet

    path = _secrets_key_path()
    if path.is_file():
        return path.read_bytes().strip()
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret for storage. Returns urlsafe-base64 ciphertext (str)."""
    from cryptography.fernet import Fernet

    return Fernet(_load_or_generate_secrets_key()).encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a secret produced by ``encrypt_secret``.

    Raises ``cryptography.fernet.InvalidToken`` if the ciphertext was produced
    with a different key (e.g. the keys dir was rotated or lost).
    """
    from cryptography.fernet import Fernet

    return Fernet(_load_or_generate_secrets_key()).decrypt(ciphertext.encode()).decode()
