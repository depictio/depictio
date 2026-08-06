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

    headers = {"Authorization": f"Bearer {token}"}

    # Tag every request with the CLI instance identity so the server can
    # distinguish multiple CLIs talking to one instance (admin monitoring).
    import socket

    headers["X-Depictio-CLI-Host"] = socket.gethostname()
    instance_label = cli_config_dict.get("instance_label")
    if instance_label:
        headers["X-Depictio-CLI-Instance"] = str(instance_label)

    # Version rides along on requests the user is already making, so the server
    # can report which CLI versions are in live use without the CLI opening any
    # extra connection — and it keeps working when CLI telemetry is switched off,
    # since this is the operator's own instance receiving it. Unlike the host
    # header above, the version is safe to forward onwards in aggregate.
    try:
        from depictio.cli.cli.utils.telemetry import cli_version

        headers["X-Depictio-CLI-Version"] = cli_version()
    except Exception as exc:  # pragma: no cover - never block a request on this
        logger.debug(f"Could not attach CLI version header: {exc}")

    return headers


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
        # Previously dropped here, so an `instance_label` set in the YAML never
        # reached CLIConfig and the X-Depictio-CLI-Instance header was never sent
        # via this path — the admin monitoring UI showed hostnames only.
        instance_label=depictio_cli_config.get("instance_label"),
    )
    logger.info(f"Depictio CLI configuration validated: {config}")
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
