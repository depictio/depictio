import os
from datetime import datetime

import typer
from pydantic import validate_call

from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement
from depictio.cli.cli_logging import logger
from depictio.models.models.cli import CLIConfig
from depictio.models.utils import get_config


@validate_call(validate_return=True)
def generate_api_headers(CLI_config: CLIConfig | dict) -> dict:
    """
    Generate the API headers.
    """
    if not CLI_config:
        raise ValueError("CLI_config is required.")

    if isinstance(CLI_config, CLIConfig):
        cli_config_dict = CLI_config.model_dump()

    elif isinstance(CLI_config, dict):
        cli_config_dict = CLI_config

    elif not isinstance(CLI_config, dict):
        raise TypeError(f"project_config must be a dictionary, got {type(CLI_config)}")

    # Get the token from the CLI configuration
    token = cli_config_dict["user"]["token"]["access_token"]

    return {"Authorization": f"Bearer {token}"}


@validate_call(validate_return=True)
def format_timestamp(timestamp: float) -> str:
    """
    Format the timestamp.
    """
    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(timestamp)


@validate_call(validate_return=True)
def validate_depictio_cli_config(depictio_cli_config: dict) -> CLIConfig:
    """
    Validate the Depictio CLI configuration.
    """
    # Map keys to match CLIConfig model expectations and create CLIConfig explicitly
    config = CLIConfig(
        user=depictio_cli_config["user"],
        api_base_url=depictio_cli_config.get("api_base_url", depictio_cli_config.get("base_url")),
        s3_storage=depictio_cli_config.get("s3_storage", depictio_cli_config.get("s3")),
    )
    logger.info(f"Depictio CLI configuration validated: {config}")
    # config = convert_model_to_dict(config)

    return config


@validate_call(validate_return=True)
def load_depictio_config(yaml_config_path: str = "~/.depictio/cli.yaml") -> CLIConfig:
    """
    Load the Depictio configuration file.
    """
    try:
        rich_print_checked_statement("Loading Depictio configuration...", "loading")
        config = get_config(os.path.expanduser(yaml_config_path))
        config = validate_depictio_cli_config(config)
        return config
    except FileNotFoundError:
        logger.error(
            "Depictio configuration file not found. Please create a new user and generate a token."
        )
        raise typer.Exit(code=1)
