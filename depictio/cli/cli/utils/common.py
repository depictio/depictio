from datetime import datetime
import os
import typer
from typeguard import typechecked

from depictio.cli.logging import logger
from depictio.models.models.users import CLIConfig


@typechecked
def generate_api_headers(CLI_config: CLIConfig) -> dict:
    """
    Generate the API headers.
    """
    if not CLI_config:
        raise ValueError("CLI_config is required.")

    if isinstance(CLI_config, CLIConfig):
        # logger.debug(f"CLI_config: {CLI_config}")
        # logger.debug(f"Type of CLI_config: {type(CLI_config)}")
        cli_config_dict = CLI_config.model_dump()

    elif isinstance(CLI_config, dict):
        cli_config_dict = CLI_config

    elif not isinstance(CLI_config, dict):
        raise TypeError(f"project_config must be a dictionary, got {type(CLI_config)}")

    # Get the token from the CLI configuration
    token = cli_config_dict["user"]["token"]["access_token"]

    return {"Authorization": f"Bearer {token}"}


@typechecked
def format_timestamp(timestamp: float) -> str:
    """
    Format the timestamp.
    """
    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(timestamp)


@typechecked
def validate_depictio_cli_config(depictio_cli_config: dict) -> CLIConfig:
    """
    Validate the Depictio CLI configuration.
    """
    # Validate the Depictio CLI configuration
    from depictio.models.models.users import CLIConfig

    config = CLIConfig(**depictio_cli_config)
    logger.info(f"Depictio CLI configuration validated: {config}")
    # config = convert_model_to_dict(config)

    return config


@typechecked
def load_depictio_config(yaml_config_path: str = "~/.depictio/cli.yaml") -> CLIConfig:
    """
    Load the Depictio configuration file.
    """
    try:
        from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement
        from depictio.models.utils import get_config

        rich_print_checked_statement("Loading Depictio configuration...", "loading")
        config = get_config(os.path.expanduser(yaml_config_path))
        config = validate_depictio_cli_config(config)
        return config
    except FileNotFoundError:
        logger.error(
            "Depictio configuration file not found. Please create a new user and generate a token."
        )
        raise typer.Exit(code=1)
