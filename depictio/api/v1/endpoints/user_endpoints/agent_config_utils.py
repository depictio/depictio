import os

import yaml
from pydantic import validate_call

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.cli import CLIConfig, UserBaseCLIConfig
from depictio.models.models.users import TokenBeanie, UserBeanie
from depictio.models.utils import make_json_serializable


@validate_call(validate_return=True)
async def _generate_agent_config(user: UserBeanie, token: TokenBeanie) -> CLIConfig:
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
        id=user.id,  # type: ignore[invalid-argument-type]
        email=user.email,
        is_admin=user.is_admin,
        token=token,  # type: ignore[invalid-argument-type]
    )

    # Create the complete CLI config
    cli_config = CLIConfig(
        user=user_cli_config,
        api_base_url=settings.fastapi.external_url,  # Always use external URL for CLI
        s3_storage=settings.minio,
    )

    logger.debug(f"Generated CLI config for user: {user.email}")
    return cli_config


async def export_agent_config(cli_config: CLIConfig, email: str, wipe: bool = False) -> str:
    """
    Export the agent configuration to a YAML file.

    Args:
        cli_config: The CLIConfigBeanie object to export
        email: User email for filename generation
        wipe: Whether to overwrite existing config files

    Returns:
        Path to the generated config file
    """
    # Make the config serializable
    serializable_config = make_json_serializable(cli_config.model_dump())
    serializable_config["api_base_url"] = str(cli_config.api_base_url)

    # Convert to YAML
    agent_config_yaml = yaml.dump(serializable_config, default_flow_style=False)

    # Create username-based filename
    username = email.split("@")[0]
    config_filename = f"{username}_config.yaml"

    # Check if the file already exists
    config_dir = settings.auth.cli_config_dir
    config_path = f"{config_dir}/{config_filename}"
    os.makedirs(config_dir, exist_ok=True)

    logger.debug(f"Creating config directory: {config_dir}")
    logger.debug(f"Wipe flag is set to: {wipe}")

    # Check if file exists and respect the wipe flag
    if os.path.exists(config_path) and not wipe:
        logger.warning(f"Config file {config_path} already exists. Use wipe=True to overwrite.")
    else:
        if os.path.exists(config_path):
            logger.warning(f"Config file {config_path} already exists. Overwriting.")
        else:
            logger.debug(f"Creating new config file: {config_path}")

        # Write the config file
        with open(config_path, "w") as f:
            f.write(agent_config_yaml)

        logger.debug(f"Agent config for {email} exported to {config_path}")

    return config_path
