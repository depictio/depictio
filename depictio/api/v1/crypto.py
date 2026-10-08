"""Symmetric encrypt-at-rest primitive for replayable secrets (Fernet).

Passwords are bcrypt-hashed (one-way). Per-project storage credentials must be
decrypted to be used, so they are sealed with a symmetric key instead. That key
lives next to the JWT keypair, in ``settings.auth.keys_dir`` (environment
``DEPICTIO_AUTH_KEYS_DIR``), for one reason: it is the single directory every
Depictio process already shares. The API encrypts on ``PUT /projects/{id}/storage``
and the Celery worker decrypts inside manifest refresh tasks, so backend and
worker MUST mount the same keys volume. A worker with a keys directory of its
own would mint a second key and every stored secret would be unreadable there
(``StorageSecretUnreadable`` on the read side).

Nothing here touches the filesystem at import time. The API container runs as
a non-root user, and the first call resolves the directory lazily so a
read-only or missing keys directory fails at the first encrypt/decrypt, with a
clear error, rather than at import of an unrelated module.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from depictio.api.v1.configs.logging_init import logger

__all__ = ["InvalidToken", "decrypt_secret", "encrypt_secret", "secrets_key_path"]

_SECRETS_KEY_FILENAME = "secrets_key.bin"
_SECRETS_KEY_LOCKFILE = ".secrets_key_generation.lock"


def _keys_dir() -> Path:
    # Lazy import: ``configs.config`` instantiates Settings and generates the JWT
    # keypair on import. Resolving it per call keeps this module importable in
    # isolation and lets tests repoint ``settings.auth.keys_dir`` at a temp dir.
    from depictio.api.v1.configs.config import settings

    return Path(settings.auth.keys_dir)


def secrets_key_path() -> Path:
    """Where the Fernet key is (or will be) persisted: ``<keys_dir>/secrets_key.bin``."""
    return _keys_dir() / _SECRETS_KEY_FILENAME


def _load_or_generate_secrets_key() -> bytes:
    path = secrets_key_path()
    if path.is_file():
        return path.read_bytes().strip()

    path.parent.mkdir(parents=True, exist_ok=True)
    # Same file-lock pattern as ``key_utils.check_and_generate_keys``: with
    # several API workers, two first-ever encrypts must not each mint a key
    # and have the loser's ciphertexts become unreadable.
    lock_path = path.parent / _SECRETS_KEY_LOCKFILE
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            if path.is_file():
                return path.read_bytes().strip()
            key = Fernet.generate_key()
            path.write_bytes(key)
            try:
                os.chmod(path, 0o600)
            except OSError as exc:
                logger.warning(
                    f"Could not restrict permissions on secrets key {path} to 0600: {exc}. "
                    "The key is readable by other users of this filesystem."
                )
            logger.info(f"Generated secrets key at {path}")
            return key
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret for storage. Returns urlsafe-base64 ciphertext (str)."""
    return Fernet(_load_or_generate_secrets_key()).encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a secret produced by ``encrypt_secret``.

    Raises ``cryptography.fernet.InvalidToken`` if the ciphertext was produced
    with a different key (keys directory rotated or lost, or the calling
    process does not share the keys volume with the process that encrypted).
    """
    return Fernet(_load_or_generate_secrets_key()).decrypt(ciphertext.encode()).decode()
