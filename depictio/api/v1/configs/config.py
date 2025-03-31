import os
from typing import Optional

from depictio.api.v1.configs.settings_models import Settings
from depictio.api.v1.crypto import (
    run_generate_keys, 
    load_private_key, 
    load_public_key, 
    import_keys
)
from depictio_models.utils import get_config, validate_model_config

config_backend_location = os.getenv(
    "DEPICTIO_CONFIG_BACKEND_LOCATION",
    "depictio/api/v1/configs/config_backend_dockercompose.yaml",
)

# Settings
# Overwrite priority: environment variables (.env) > config file (.yaml) > default values
settings = validate_model_config(get_config(config_backend_location), Settings)

API_BASE_URL = f"http://{settings.fastapi.service_name}:{settings.fastapi.port}"
DASH_BASE_URL = f"http://{settings.dash.service_name}:{settings.dash.port}"
MONGODB_URL = f"mongodb://{settings.mongodb.service_name}:{settings.mongodb.port}/"
ALGORITHM = "RS256"

def setup_keys(
    private_key_path: Optional[str] = None, 
    public_key_path: Optional[str] = None,
    private_key_content: Optional[str] = None,
    public_key_content: Optional[str] = None
):
    """
    Set up keys for the application with multiple options.
    
    Args:
        private_key_path: Optional custom path for private key
        public_key_path: Optional custom path for public key
        private_key_content: Optional PEM-formatted private key content
        public_key_content: Optional PEM-formatted public key content
    
    Returns:
        Tuple of (private_key, public_key)
    """
    # If both content and path are provided for a key, content takes precedence
    if private_key_content:
        # Import keys from content
        private_key_path, public_key_path = import_keys(
            private_key_content, 
            public_key_content or '', 
            private_key_path, 
            public_key_path
        )
    else:
        # Generate or use existing keys
        run_generate_keys(private_key_path, public_key_path)
    
    # Load and return keys
    private_key = load_private_key(private_key_path)
    public_key = load_public_key(public_key_path)
    
    return private_key, public_key

# Set up keys with default behavior
PRIVATE_KEY, PUBLIC_KEY = setup_keys()
