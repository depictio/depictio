import os
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

from depictio.api.v1.configs.logging import logger   


# Algorithm used for signing
ALGORITHM = "RS256"

# Key file paths
private_key_path = "depictio/private_key.pem"
public_key_path = "depictio/public_key.pem"

def generate_keys():
    """Generate a new RSA private-public key pair."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    public_key = private_key.public_key()

    # Save the private key
    with open(private_key_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))

    # Save the public key
    with open(public_key_path, "wb") as f:
        f.write(public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ))

    logger.info("Generated new RSA key pair.")

def run_generate_keys():
    # Check if key files exist, generate if they don't
    if not os.path.exists(private_key_path) or not os.path.exists(public_key_path):
        logger.warning("Key files not found. Generating new keys.")
        generate_keys()

def load_private_key(private_key_path=private_key_path):
    """Load the private key from the file."""
    with open(private_key_path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())
    
def load_public_key(public_key_path=public_key_path):
    """Load the public key from the file."""
    with open(public_key_path, "rb") as f:
        return serialization.load_pem_public_key(f.read(), backend=default_backend())