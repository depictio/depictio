import os
import yaml
from pydantic import HttpUrl

from depictio.api.v1.configs.custom_logging import logger
from depictio.api.v1.configs.config import settings
from depictio.api.v1.s3 import minios3_external_config

from depictio_models.models.users import (
    UserBeanie,
    TokenBeanie,
    UserBaseCLIConfig,
    CLIConfig,
)
from depictio_models.utils import make_json_serializable


# Helper function to generate agent config
async def generate_agent_config(user: UserBeanie, token: TokenBeanie) -> CLIConfig:
    """
    Generate an agent configuration for a user with the given token.

    Args:
        user: The UserBeanie object
        token: The TokenBeanie object containing token information

    Returns:
        A CLIConfigBeanie object with the agent configuration
    """
    logger.info(f"Generating agent config for user: {user.email}")

    # Create the user CLI config
    user_cli_config = UserBaseCLIConfig(
        id=user.id, email=user.email, is_admin=user.is_admin, token=token
    )

    # Create the complete CLI config
    cli_config = CLIConfig(
        user=user_cli_config,
        base_url=HttpUrl(f"http://{settings.fastapi.host}:{settings.fastapi.port}"),
        s3=minios3_external_config,
    )

    logger.debug(f"Generated CLI config: {cli_config}")
    return cli_config


# Function to export agent config to a YAML file
async def export_agent_config(
    cli_config: CLIConfig, email: str, wipe: bool = False
) -> str:
    """
    Export the agent configuration to a YAML file.

    Args:
        cli_config: The CLIConfigBeanie object to export
        email: User email for filename generation
        wipe: Whether to overwrite existing config files

    Returns:
        Path to the generated config file
    """
    # Make the config serializable by converting Pydantic models and ObjectIds
    serializable_config = make_json_serializable(cli_config.model_dump())
    serializable_config["base_url"] = str(cli_config.base_url)

    # Convert to YAML
    agent_config_yaml = yaml.dump(serializable_config, default_flow_style=False)

    # Create username-based filename
    username = email.split("@")[0]
    config_filename = f"{username}_config.yaml"

    # Check if the file already exists
    config_dir = settings.auth.cli_config_dir
    config_path = f"{config_dir}/{config_filename}"
    # Create the config directory if it doesn't exist
    os.makedirs(config_dir, exist_ok=True)
    
    logger.debug(f"Creating config directory: {config_dir}")
    logger.debug(f"Wipe flag is set to: {wipe}")

    # Check if file exists and respect the wipe flag
    if os.path.exists(config_path) and not wipe:
        logger.warning(f"Config file {config_path} already exists. Use wipe=True to overwrite.")
    else:
        # Log appropriate message based on whether we're overwriting
        if os.path.exists(config_path):
            logger.warning(f"Config file {config_path} already exists. Overwriting.")
        else:
            logger.debug(f"Creating new config file: {config_path}")
        
        # Write the config file
        with open(config_path, "w") as f:
            f.write(agent_config_yaml)
            
        logger.debug(f"Agent config for {email} exported to {config_path}")
    
    return config_path
