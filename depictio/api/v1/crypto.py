import os
from typing import Optional
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

from depictio.api.v1.configs.logging import logger


# Algorithm used for signing
ALGORITHM = "RS256"

# Default key file paths
DEFAULT_PRIVATE_KEY_PATH = "/app/depictio/keys/private_key.pem"
DEFAULT_PUBLIC_KEY_PATH = "/app/depictio/keys/public_key.pem"


def generate_keys(
    private_key_path: Optional[str] = None, public_key_path: Optional[str] = None
):
    """
    Generate a new RSA private-public key pair.

    Args:
        private_key_path: Optional custom path for private key
        public_key_path: Optional custom path for public key
    """
    # Use default paths if not provided
    private_key_path = private_key_path or DEFAULT_PRIVATE_KEY_PATH
    public_key_path = public_key_path or DEFAULT_PUBLIC_KEY_PATH

    # Ensure the directory exists and has the correct permissions
    os.makedirs(os.path.dirname(private_key_path), exist_ok=True)

    try:
        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )
        public_key = private_key.public_key()

        # Save the private key
        with open(private_key_path, "wb") as f:
            f.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

        # Save the public key
        with open(public_key_path, "wb") as f:
            f.write(
                public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )

        logger.info(
            f"Generated new RSA key pair at {private_key_path} and {public_key_path}"
        )
        return private_key_path, public_key_path

    except Exception as e:
        logger.error(f"Failed to generate keys: {e}")
        raise


def run_generate_keys(
    private_key_path: Optional[str] = None, public_key_path: Optional[str] = None
):
    """
    Check if key files exist, generate if they don't.

    Args:
        private_key_path: Optional custom path for private key
        public_key_path: Optional custom path for public key
    """
    # Use default paths if not provided
    private_key_path = private_key_path or DEFAULT_PRIVATE_KEY_PATH
    public_key_path = public_key_path or DEFAULT_PUBLIC_KEY_PATH

    # Check if key files exist, generate if they don't
    if not os.path.exists(private_key_path) or not os.path.exists(public_key_path):
        logger.warning("Key files not found. Generating new keys.")
        generate_keys(private_key_path, public_key_path)

    else:
        logger.info("Key files already exist. No need to generate new keys.")
        logger.info(f"Private key path: {private_key_path}")
        logger.info(f"Public key path: {public_key_path}")


def load_private_key(private_key_path: Optional[str] = None):
    """
    Load the private key from the file.

    Args:
        private_key_path: Optional custom path for private key

    Returns:
        Loaded private key
    """
    # Use default path if not provided
    private_key_path = private_key_path or DEFAULT_PRIVATE_KEY_PATH

    try:
        with open(private_key_path, "rb") as f:
            return serialization.load_pem_private_key(
                f.read(), password=None, backend=default_backend()
            )
    except FileNotFoundError:
        logger.error(f"Private key file not found at {private_key_path}")
        raise
    except Exception as e:
        logger.error(f"Error loading private key: {e}")
        raise


def load_public_key(public_key_path: Optional[str] = None):
    """
    Load the public key from the file.

    Args:
        public_key_path: Optional custom path for public key

    Returns:
        Loaded public key
    """
    # Use default path if not provided
    public_key_path = public_key_path or DEFAULT_PUBLIC_KEY_PATH

    try:
        with open(public_key_path, "rb") as f:
            return serialization.load_pem_public_key(
                f.read(), backend=default_backend()
            )
    except FileNotFoundError:
        logger.error(f"Public key file not found at {public_key_path}")
        raise
    except Exception as e:
        logger.error(f"Error loading public key: {e}")
        raise


def import_keys(
    private_key_content: str,
    public_key_content: str,
    private_key_path: Optional[str] = None,
    public_key_path: Optional[str] = None,
):
    """
    Import keys from provided content.

    Args:
        private_key_content: PEM-formatted private key content
        public_key_content: PEM-formatted public key content
        private_key_path: Optional custom path for private key
        public_key_path: Optional custom path for public key

    Returns:
        Tuple of private and public key paths
    """
    # Use default paths if not provided
    private_key_path = private_key_path or DEFAULT_PRIVATE_KEY_PATH
    public_key_path = public_key_path or DEFAULT_PUBLIC_KEY_PATH

    # Ensure the directory exists
    os.makedirs(os.path.dirname(private_key_path), exist_ok=True)

    # Write private key
    with open(private_key_path, "wb") as f:
        f.write(private_key_content.encode("utf-8"))

    # Write public key
    with open(public_key_path, "wb") as f:
        f.write(public_key_content.encode("utf-8"))

    logger.info(f"Imported keys to {private_key_path} and {public_key_path}")
    return private_key_path, public_key_path
