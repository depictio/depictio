import atexit
import os
from datetime import datetime

import httpx
import typer
from pydantic import validate_call

from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement
from depictio.cli.cli_logging import logger
from depictio.models.models.cli import CLIConfig
from depictio.models.utils import get_config

# Process-wide pooled HTTP client. A single CLI invocation (scan/process/sync)
# fires many sequential requests to the same API host; reusing one client keeps
# the TCP/TLS connection alive across them instead of paying a fresh handshake
# per call. Per-request timeouts/headers are still passed at each call site.
_http_client: httpx.Client | None = None


def get_http_client() -> httpx.Client:
    """Return the shared, lazily-created :class:`httpx.Client`."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client()
        atexit.register(_http_client.close)
    return _http_client


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
    return config


# CLI config paths considered "default" — only these are overridden by
# DEPICTIO_CLI_CONFIG_PATH so an explicit --CLI-config-path is never clobbered.
_DEFAULT_CLI_CONFIG_PATHS = ("~/.depictio/cli.yaml", "~/.depictio/CLI.yaml")


def _apply_env_overrides(config: dict) -> dict:
    """Apply environment-variable overrides to a loaded CLI config dict.

    Lets a ``CLI.yaml`` be committed **without secrets** and have the token (and
    optionally the API URL) injected at runtime — the mechanism that makes
    automated triggering (e.g. from a Nextflow pipeline in CI/cluster) practical.

    Recognised variables:
      - ``DEPICTIO_CLI_TOKEN``        → ``user.token.access_token``
      - ``DEPICTIO_CLI_API_BASE_URL`` → ``api_base_url``

    (``DEPICTIO_CLI_CONFIG_PATH`` is handled in :func:`load_depictio_config`
    since it selects the file to load before this runs.)
    """
    token = os.environ.get("DEPICTIO_CLI_TOKEN")
    if token:
        user = config.setdefault("user", {})
        user.setdefault("token", {})["access_token"] = token

    api_base_url = os.environ.get("DEPICTIO_CLI_API_BASE_URL")
    if api_base_url:
        config["api_base_url"] = api_base_url

    return config


@validate_call(validate_return=True)
def load_depictio_config(yaml_config_path: str = "~/.depictio/cli.yaml") -> CLIConfig:
    """
    Load the Depictio configuration file.
    """
    try:
        rich_print_checked_statement("Loading Depictio configuration...", "loading")
        # DEPICTIO_CLI_CONFIG_PATH overrides the path only when the caller left it
        # at a default — an explicit --CLI-config-path always wins.
        env_path = os.environ.get("DEPICTIO_CLI_CONFIG_PATH")
        if env_path and yaml_config_path in _DEFAULT_CLI_CONFIG_PATHS:
            yaml_config_path = env_path
        config = get_config(os.path.expanduser(yaml_config_path))
        config = _apply_env_overrides(config)
        config = validate_depictio_cli_config(config)
        return config
    except FileNotFoundError:
        logger.error(
            "Depictio configuration file not found. Please create a new user and generate a token."
        )
        raise typer.Exit(code=1)
