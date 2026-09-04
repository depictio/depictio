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


def describe_api_target(yaml_config_path: str) -> str:
    """Name the API URL a failed call was aimed at, and the file it came from.

    "Connection refused" on its own sends people restarting a server that is
    already up: the usual cause is a config pointing at a different instance.
    That is the default failure of an automated run, where nobody chose the
    config path and it fell back to ``~/.depictio/CLI.yaml``.

    Never raises. It is only ever called while already reporting another error,
    and a failure to read the config is itself part of the answer.
    """
    try:
        config = load_depictio_config(yaml_config_path=yaml_config_path, quiet=True)
    except Exception as exc:
        logger.debug(f"Could not resolve the API base URL to report it: {exc}")
        return f"an unreadable configuration at {yaml_config_path}"
    return f"{config.api_base_url}, read from {yaml_config_path}"


# CLI config paths considered "default" - only these are overridden by
# DEPICTIO_CLI_CONFIG_PATH, so an explicit --CLI-config-path is never clobbered.
_DEFAULT_CLI_CONFIG_PATHS = ("~/.depictio/cli.yaml", "~/.depictio/CLI.yaml")


def _apply_env_overrides(config: dict) -> dict:
    """Apply environment-variable overrides to a loaded CLI config dict.

    Lets a ``CLI.yaml`` be committed **without secrets** and have the token (and
    optionally the API URL) injected at runtime - the mechanism that makes
    automated triggering (e.g. from a Nextflow pipeline in CI or on a cluster)
    practical, since the head job usually has env vars but no writable home.

    Recognised variables:
      - ``DEPICTIO_CLI_TOKEN``        -> ``user.token.access_token``
      - ``DEPICTIO_CLI_API_BASE_URL`` -> ``api_base_url``

    (``DEPICTIO_CLI_CONFIG_PATH`` is handled in :func:`load_depictio_config`
    since it selects which file to load, before this runs.)
    """
    token = os.environ.get("DEPICTIO_CLI_TOKEN")
    if token:
        user = config.setdefault("user", {})
        if not isinstance(user.get("token"), dict):
            user["token"] = {}
        user["token"]["access_token"] = token

    api_base_url = os.environ.get("DEPICTIO_CLI_API_BASE_URL")
    if api_base_url:
        config["api_base_url"] = api_base_url

    return config


@validate_call(validate_return=True)
def load_depictio_config(
    yaml_config_path: str = "~/.depictio/CLI.yaml", quiet: bool = False
) -> CLIConfig:
    """
    Load the Depictio configuration file.

    ``quiet`` suppresses the "Loading..." line, for callers that re-read an
    already-loaded config only to name a field (the API URL in an error
    message, the viewer URL in the summary). Without it those reads announce a
    second load that never happened, in the middle of reporting a failure.
    """
    try:
        if not quiet:
            rich_print_checked_statement("Loading Depictio configuration...", "loading")
        # DEPICTIO_CLI_CONFIG_PATH overrides the path only when the caller left it
        # at a default - an explicit --CLI-config-path always wins.
        env_path = os.environ.get("DEPICTIO_CLI_CONFIG_PATH")
        from_env = bool(env_path) and yaml_config_path in _DEFAULT_CLI_CONFIG_PATHS
        if from_env:
            yaml_config_path = env_path  # type: ignore[assignment]
        expanded = os.path.expanduser(yaml_config_path)
        # `get_config` signals a missing/unsuitable file with ValueError, not
        # FileNotFoundError, so checking here is what turns a typo into a usable
        # message instead of a traceback. That matters most for an automated
        # trigger, where the path usually arrives from DEPICTIO_CLI_CONFIG_PATH.
        if not os.path.isfile(expanded):
            source = "DEPICTIO_CLI_CONFIG_PATH" if from_env else "--CLI-config-path"
            logger.error(f"Depictio CLI configuration file not found: {expanded} (from {source})")
            rich_print_checked_statement(
                f"Depictio CLI configuration file not found: {expanded} (from {source}). "
                f"Create it, or point {source} at an existing config.",
                "error",
            )
            raise typer.Exit(code=1)
        config = get_config(expanded)
        config = _apply_env_overrides(config)
        config = validate_depictio_cli_config(config)
        return config
    except FileNotFoundError:
        logger.error(
            "Depictio configuration file not found. Please create a new user and generate a token."
        )
        raise typer.Exit(code=1)
