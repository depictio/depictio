"""Cryptographic key management utilities for RSA and other algorithms."""

import os
from pathlib import Path
from typing import Literal, TypeVar, cast

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from pydantic import validate_call

from depictio.api.v1.configs.logging_init import logger

# Type definitions
Algorithm = Literal["RS256", "RS512", "ES256", "SHA256"]
KeyPathStr = str
PrivateKeyT = TypeVar("PrivateKeyT", bound=RSAPrivateKey | ec.EllipticCurvePrivateKey)
PublicKeyT = TypeVar("PublicKeyT", bound=RSAPublicKey | ec.EllipticCurvePublicKey)


class KeyGenerationError(Exception):
    """Custom exception for key generation failures."""


# @validate_call(validate_return=True)
# def _load_or_generate_api_internal_key(
#     keys_dir: Path = Path("./depictio/keys"),
#     algorithm: Algorithm = "RS256",
# ) -> str:
#     """Check if the API internal key is set in the environment.

#     Returns:
#         API internal key if set, otherwise generates a new one
#     """
#     logger.info("Checking for API internal key in environment variables.")
#     key_path = os.path.join(keys_dir, "api_internal_key.pem")
#     logger.info(f"Key path: {key_path}")
#     logger.info(f"Loading or generating API internal key with algorithm: {algorithm}")

#     # Create the directory if it doesn't exist
#     logger.debug(f"Creating directory if it doesn't exist: {os.path.dirname(key_path)}")
#     os.makedirs(os.path.dirname(key_path), exist_ok=True)

#     logger.debug(f"Key path: {key_path}")
#     if os.path.exists(key_path):
#         with open(key_path) as f:
#             key = f.read().strip()
#             logger.debug(f"Loaded API internal key: {key}")
#             return key
#     else:
#         key = _generate_api_internal_key()
#         logger.debug(f"Generated API internal key: {key}")
#         with open(key_path, "w") as f:
#             f.write(key)
#         return key


# @validate_call(validate_return=True)
# def _generate_api_internal_key() -> str:
#     """Generate a consistent API internal key.

#     Returns:
#         Consistently generated API internal key
#     """
#     # Use a combination of environment variables and a salt to generate a consistent key
#     salt = "DEPICTIO_INTERNAL_KEY_SALT"
#     base_key = os.getenv("DEPICTIO_INTERNAL_API_KEY", "")

#     # If no base key exists, generate a persistent key
#     if not base_key:
#         import hashlib

#         # Generate a hash based on a combination of system information
#         system_info = f"{os.getpid()}:{os.getuid()}:{salt}"
#         base_key = hashlib.sha256(system_info.encode()).hexdigest()

#         # Set the environment variable to persist the key
#         os.environ["DEPICTIO_INTERNAL_API_KEY"] = base_key

#     return base_key


@validate_call()
def _ensure_directory_exists(path: str | Path) -> None:
    """Ensure the directory for a file exists.

    Args:
        path: File path whose directory should exist
    """
    if isinstance(path, str):
        path = Path(path)

    # Create parent directory if it doesn't exist
    path.parent.mkdir(parents=True, exist_ok=True)


@validate_call(validate_return=True)
def _resolve_key_paths(
    private_key_path: str | None,
    public_key_path: str | None,
    keys_dir: Path | None,
) -> tuple[str, str]:
    """Resolve key paths based on input parameters.

    Args:
        private_key_path: Optional custom path for private key
        public_key_path: Optional custom path for public key
        keys_dir: Optional directory to store keys

    Returns:
        Tuple of resolved private and public key paths
    """
    # Standardize keys_dir to Path if provided
    if keys_dir:
        keys_dir = Path(keys_dir) if isinstance(keys_dir, str) else keys_dir
        keys_dir.mkdir(parents=True, exist_ok=True)

        # Set default key paths if not provided
        priv_path = private_key_path or str(keys_dir / "private_key.pem")
        pub_path = public_key_path or str(keys_dir / "public_key.pem")
    else:
        if not private_key_path or not public_key_path:
            raise ValueError("Both key paths must be specified if keys_dir is not provided")
        priv_path = private_key_path
        pub_path = public_key_path

    # Ensure directories exist
    _ensure_directory_exists(priv_path)
    _ensure_directory_exists(pub_path)

    return priv_path, pub_path


@validate_call(config={"arbitrary_types_allowed": True})  # type: ignore[invalid-argument-type]
def _generate_rsa_private_key(key_size: int = 2048) -> RSAPrivateKey:
    """Generate an RSA private key with the specified key size.

    Args:
        key_size: Size of the RSA key in bits (default: 2048)

    Returns:
        RSA private key object
    """
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
        backend=default_backend(),
    )


@validate_call(config={"arbitrary_types_allowed": True})  # type: ignore[invalid-argument-type]
def _save_private_key(private_key: PrivateKeyT, path: str) -> None:
    """Save private key to file.

    Args:
        private_key: Private key object to save
        path: Path where the key should be saved
    """
    with open(path, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )


@validate_call(config={"arbitrary_types_allowed": True})  # type: ignore[invalid-argument-type]
def _save_public_key(public_key: PublicKeyT, path: str) -> None:
    """Save public key to file.

    Args:
        public_key: Public key object to save
        path: Path where the key should be saved
    """
    with open(path, "wb") as f:
        f.write(
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )


def generate_keys(
    private_key_path: str | None = None,
    public_key_path: str | None = None,
    keys_dir: Path | None = None,
    algorithm: Algorithm | None = None,
    wipe: bool = False,
) -> tuple[str, str]:
    """Generate a new key pair with the specified algorithm.

    Args:
        private_key_path: Optional custom path for private key
        public_key_path: Optional custom path for public key
        keys_dir: Optional directory to store keys
        algorithm: Algorithm to use for key generation
        wipe: Whether to wipe existing keys

    Returns:
        Tuple of (private_key_path, public_key_path)

    Raises:
        ValueError: If the algorithm is unsupported
        NotImplementedError: If the algorithm is not yet implemented
        KeyGenerationError: If key generation fails for any other reason
    """
    if not algorithm:
        algorithm = "RS256"  # Default algorithm

    logger.debug(f"Generating keys with algorithm: {algorithm}")
    logger.debug(f"Keys directory: {keys_dir}")
    logger.debug(f"Private key path: {private_key_path}")
    logger.debug(f"Public key path: {public_key_path}")
    logger.debug(f"Wipe existing keys: {wipe}")

    if wipe:
        logger.warning("Wiping existing keys as requested.")
        # Remove existing keys if wipe is True
        if private_key_path and os.path.exists(private_key_path):
            os.remove(private_key_path)
            logger.warning(f"Removed existing private key at {private_key_path}")
        if public_key_path and os.path.exists(public_key_path):
            os.remove(public_key_path)
            logger.warning(f"Removed existing public key at {public_key_path}")

    try:
        private_key_path, public_key_path = _resolve_key_paths(
            private_key_path, public_key_path, keys_dir
        )

        if algorithm == "RS256":
            private_key = _generate_rsa_private_key(key_size=2048)
            public_key = private_key.public_key()
        elif algorithm == "RS512":
            private_key = _generate_rsa_private_key(key_size=4096)
            public_key = private_key.public_key()
        elif algorithm == "ES256":
            # Placeholder for ECDSA key generation
            raise NotImplementedError("ES256 algorithm is not implemented yet.")
        elif algorithm == "SHA256":
            # Placeholder for SHA256 key generation
            raise NotImplementedError("SHA256 algorithm is not implemented yet.")
        else:
            raise ValueError(f"Unsupported algorithm: {algorithm}")

        # Save keys
        _save_private_key(private_key, private_key_path)
        _save_public_key(public_key, public_key_path)

        logger.info(
            f"Generated new {algorithm} key pair at {private_key_path} and {public_key_path}"
        )
        return private_key_path, public_key_path

    except (ValueError, NotImplementedError):
        # Re-raise explicit errors
        raise
    except Exception as e:
        logger.error(f"Failed to generate keys: {e}")
        raise KeyGenerationError(f"Failed to generate keys: {e}") from e


@validate_call(validate_return=True, config={"arbitrary_types_allowed": True})  # type: ignore[invalid-argument-type]
def check_and_generate_keys(
    private_key_path: str | None = None,
    public_key_path: str | None = None,
    keys_dir: str | Path | None = None,
    algorithm: Algorithm | None = None,
) -> tuple[str, str]:
    """Check if key files exist, generate if they don't.

    Args:
        private_key_path: Optional custom path for private key
        public_key_path: Optional custom path for public key
        keys_dir: Optional directory to store keys
        algorithm: Algorithm to use for key generation if needed

    Returns:
        Tuple of (private_key_path, public_key_path)
    """
    # Convert keys_dir to Path if it's a string
    if keys_dir and isinstance(keys_dir, str):
        keys_dir = Path(keys_dir)

    # Resolve key paths
    private_key_path, public_key_path = _resolve_key_paths(
        private_key_path, public_key_path, keys_dir
    )

    # Check if key files exist, generate if they don't
    if not os.path.exists(private_key_path) or not os.path.exists(public_key_path):
        logger.warning("Key files not found. Generating new keys.")
        return generate_keys(private_key_path, public_key_path, keys_dir, algorithm)  # type: ignore[invalid-argument-type]

    logger.debug("Key files already exist. No need to generate new keys.")
    logger.debug(f"Private key path: {private_key_path}")
    logger.debug(f"Public key path: {public_key_path}")
    return private_key_path, public_key_path


@validate_call(validate_return=True, config={"arbitrary_types_allowed": True})  # type: ignore[invalid-argument-type]
def load_private_key(private_key_path: Path) -> RSAPrivateKey:
    """Load a private key from a file.

    Args:
        private_key_path: Path to the private key file

    Returns:
        Private key object

    Raises:
        FileNotFoundError: If the key file doesn't exist
        Exception: If there's an error loading the key
    """
    try:
        with open(private_key_path, "rb") as f:
            key = serialization.load_pem_private_key(
                f.read(), password=None, backend=default_backend()
            )
            return cast(RSAPrivateKey, key)  # Type casting for mypy
    except FileNotFoundError:
        logger.error(f"Private key file not found at {private_key_path}")
        raise
    except Exception as e:
        logger.error(f"Error loading private key: {e}")
        raise


@validate_call(validate_return=True, config={"arbitrary_types_allowed": True})  # type: ignore[invalid-argument-type]
def load_public_key(public_key_path: Path) -> RSAPublicKey:
    """Load a public key from a file.

    Args:
        public_key_path: Path to the public key file

    Returns:
        Public key object

    Raises:
        FileNotFoundError: If the key file doesn't exist
        Exception: If there's an error loading the key
    """
    try:
        with open(public_key_path, "rb") as f:
            key = serialization.load_pem_public_key(f.read(), backend=default_backend())
            return cast(RSAPublicKey, key)  # Type casting for mypy
    except FileNotFoundError:
        logger.error(f"Public key file not found at {public_key_path}")
        raise
    except Exception as e:
        logger.error(f"Error loading public key: {e}")
        raise


@validate_call(validate_return=True)
def import_keys(
    private_key_content: str,
    public_key_content: str,
    private_key_path: str | None = None,
    public_key_path: str | None = None,
    keys_dir: Path | None = None,
) -> tuple[str, str]:
    """Import keys from provided PEM content.

    Args:
        private_key_content: PEM-formatted private key content
        public_key_content: PEM-formatted public key content
        private_key_path: Optional custom path for private key
        public_key_path: Optional custom path for public key
        keys_dir: Optional directory to store keys

    Returns:
        Tuple of (private_key_path, public_key_path)
    """
    private_key_path, public_key_path = _resolve_key_paths(
        private_key_path, public_key_path, keys_dir
    )

    # Write private key
    with open(private_key_path, "wb") as f:
        f.write(private_key_content.encode("utf-8"))

    # Write public key
    with open(public_key_path, "wb") as f:
        f.write(public_key_content.encode("utf-8"))

    logger.info(f"Imported keys to {private_key_path} and {public_key_path}")
    return private_key_path, public_key_path
