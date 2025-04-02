import os
from typing import Optional
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

from depictio.api.v1.configs.logging import logger


def generate_keys(
    private_key_path: Optional[str] = None,
    public_key_path: Optional[str] = None,
    keys_dir: Optional[Path] = None,
    algorithm: Optional[str] = None,
):
    """
    Generate a new RSA private-public key pair.

    Args:
        private_key_path: Optional custom path for private key
        public_key_path: Optional custom path for public key
        keys_dir: Optional directory to store keys
    """
    # Ensure keys directory exists
    if keys_dir:
        keys_dir.mkdir(parents=True, exist_ok=True)
        private_key_path = private_key_path or str(keys_dir / "private_key.pem")
        public_key_path = public_key_path or str(keys_dir / "public_key.pem")

    # Ensure the directory exists and has the correct permissions
    os.makedirs(os.path.dirname(private_key_path), exist_ok=True)

    try:
        if algorithm == "RS256":
            private_key = rsa.generate_private_key(
                public_exponent=65537, key_size=2048, backend=default_backend()
            )
            public_key = private_key.public_key()
        elif algorithm == "RS512":
            private_key = rsa.generate_private_key(
                public_exponent=65537, key_size=4096, backend=default_backend()
            )
        elif algorithm == "ES256":
            # Placeholder for ECDSA key generation
            raise NotImplementedError("ES256 algorithm is not implemented yet.")
        elif algorithm == "SHA256":
            # Placeholder for SHA256 key generation
            raise NotImplementedError("SHA256 algorithm is not implemented yet.")
        else:
            raise ValueError(f"Unsupported algorithm: {algorithm}")

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
    private_key_path: Optional[str] = None,
    public_key_path: Optional[str] = None,
    keys_dir: Optional[Path] = None,
    algorithm: Optional[str] = None,
):
    """
    Check if key files exist, generate if they don't.

    Args:
        private_key_path: Optional custom path for private key
        public_key_path: Optional custom path for public key
        keys_dir: Optional directory to store keys
    """
    # Ensure keys directory exists
    logger.info(f"Setting up keys...")
    logger.info(f"CWD: {os.getcwd()}")
    logger.info(f"Keys dir: {keys_dir}")
    logger.info(f"Private key path: {private_key_path}")
    logger.info(f"Public key path: {public_key_path}")

    # Convert keys_dir to Path if it's a string
    if keys_dir and isinstance(keys_dir, str):
        keys_dir = Path(keys_dir)

    if keys_dir:
        logger.info(f"Creating keys directory: {keys_dir}")

        os.makedirs(keys_dir, exist_ok=True)

        private_key_path = private_key_path or str(keys_dir / "private_key.pem")
        logger.info(f"Private key path set to: {private_key_path}")
        public_key_path = public_key_path or str(keys_dir / "public_key.pem")
        logger.info(f"Public key path set to: {public_key_path}")

    # Check if key files exist, generate if they don't
    if not os.path.exists(private_key_path) or not os.path.exists(public_key_path):
        logger.warning("Key files not found. Generating new keys.")
        generate_keys(private_key_path, public_key_path, keys_dir, algorithm)
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
    keys_dir: Optional[Path] = None,
):
    """
    Import keys from provided content.

    Args:
        private_key_content: PEM-formatted private key content
        public_key_content: PEM-formatted public key content
        private_key_path: Optional custom path for private key
        public_key_path: Optional custom path for public key
        keys_dir: Optional directory to store keys

    Returns:
        Tuple of private and public key paths
    """
    # Ensure keys directory exists
    if keys_dir:
        keys_dir.mkdir(parents=True, exist_ok=True)
        private_key_path = private_key_path or str(keys_dir / "private_key.pem")
        public_key_path = public_key_path or str(keys_dir / "public_key.pem")

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
