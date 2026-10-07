import atexit
import contextlib
import os
from collections.abc import Iterator
from datetime import datetime
from urllib.parse import urlparse

import httpx
import typer
import yaml
from pydantic import ValidationError, validate_call
from rich.markup import escape

from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement
from depictio.cli.cli.utils.server_target import (
    DEFAULT_TARGET_CLI_CONFIG,
    ConfigFile,
    default_server,
    is_local_cli_config,
    running_local_url,
)
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
    # The URL and the user only: the configuration holds the access token, and
    # verbose logs of a pipeline run are archived.
    logger.info(
        f"Depictio CLI configuration validated: {config.api_base_url}, user {config.user.email}"
    )
    return config


def describe_api_target(yaml_config_path: str) -> str:
    """Name the API URL a failed call was aimed at, and the file it came from.

    "Connection refused" on its own sends people restarting a server that is
    already up: the usual cause is a config pointing at a different instance.
    That is the default failure of an automated run, where nobody passed
    --server and it fell back to ``~/.depictio/CLI.yaml``. For the local server,
    the usual cause is that it is stopped, and this says so.

    Never raises, and prints nothing. It is only ever called while already
    reporting another error, and a failure to read the config is itself part of
    the answer.
    """
    # The file actually read: DEPICTIO_CLI_CONFIG_PATH or the local server may stand in
    # for the default.
    config_file = cli_config_file(yaml_config_path)
    shown = display_path(config_file)
    if os.path.isdir(config_file):
        return f"a directory at {shown}, not a configuration file"
    if not os.path.isfile(config_file):
        return f"a missing configuration at {shown}"
    try:
        config, source = _read_cli_config(yaml_config_path)
    except Exception as exc:
        logger.debug(f"Could not resolve the API base URL to report it: {exc}")
        return f"an unreadable configuration at {shown}"
    # The variable wins over the file: naming the file would send people to fix the
    # wrong one.
    origin = _URL_FROM_ENV if source.startswith(_URL_FROM_ENV) else f"read from {shown}"
    hint = local_server_hint(config_file)
    return f"{config.api_base_url}, {origin}" + (f" ({hint})" if hint else "")


def report_unreachable(yaml_config_path: str, exc: Exception) -> None:
    """Say that the server did not answer, and which one: see describe_api_target. Then
    a local server that runs besides it, if any."""
    rich_print_checked_statement(f"Cannot reach the Depictio server: {exc}", "error")
    rich_print_checked_statement(f"Tried {describe_api_target(yaml_config_path)}", "info")
    say_local_server_running(yaml_config_path)


def report_login_failure(
    yaml_config_path: str, login: dict, failed: str = "Authentication failed"
) -> None:
    """Say why api_login returned success False, after ``failed``, then the server tried.

    The token is blamed only when the server refused it: a 401 or a 403, or a 200 whose
    verdict is no. Any other answer, a viewer host's 404 or a proxy's 502, is not the
    token's fault, and a new token would not fix it.
    """
    status = login.get("status_code", 200)
    if status in (200, 401, 403):
        reason = "the server rejected this configuration's token, which is invalid or expired"
    else:
        reason = f"the server answered HTTP {status}"
    rich_print_checked_statement(f"{failed}: {reason}", "error")
    rich_print_checked_statement(f"Tried {describe_api_target(yaml_config_path)}", "info")


def local_server_hint(yaml_config_path: str) -> str | None:
    """How to start the local server, when ``yaml_config_path`` is its configuration and
    it is stopped: a bare "Connection refused" does not say that. None otherwise."""
    try:
        if not is_local_cli_config(cli_config_file(yaml_config_path)):
            return None
        from depictio.cli.cli.local_stack import Paths, local_home, running_status

        if running_status(Paths(local_home())).get("api"):
            return None
    except Exception as exc:
        # Only ever a hint added to another error: it must not replace that error.
        logger.debug(f"Could not tell whether the local server runs: {exc}")
        return None
    return "the local server is not running: start it with `depictio local up`"


def local_server_running_instead(
    yaml_config_path: str, api_base_url: str | None = None
) -> str | None:
    """The URL of the local server when it runs and ``yaml_config_path`` reaches another
    server, for a hint that names it. None otherwise.

    ``api_base_url`` is the URL that configuration resolved to, read here when not
    given: a configuration copied from the local server's reaches it already. Only
    ever a hint added to other output, so it never raises.
    """
    try:
        if is_local_cli_config(cli_config_file(yaml_config_path)):
            return None
        local_url = running_local_url()
        if local_url is None:
            return None
        if api_base_url is None:
            api_base_url = str(_read_cli_config(yaml_config_path)[0].api_base_url)
        if _same_loopback_server(api_base_url, local_url):
            return None
    except Exception as exc:
        logger.debug(f"Could not tell whether a local server runs besides the target: {exc}")
        return None
    return local_url


def say_local_server_running(yaml_config_path: str, option: str = "--server") -> None:
    """After the "Tried ..." line of a server that failed: the local server, when it runs
    and is another one. For the commands that print that line themselves, too."""
    local_url = local_server_running_instead(yaml_config_path)
    if local_url:
        rich_print_checked_statement(
            f"A local server is running at {local_url}: add {option} local to use it", "info"
        )


class CLIConfigError(ValueError):
    """A CLI configuration that cannot be used. The message names the file and the fix."""


# CLI config paths considered "default": only these are resolved by default_server
# (DEPICTIO_CLI_CONFIG_PATH, the local server), so an explicit --server is never clobbered.
_DEFAULT_CLI_CONFIG_PATHS = ("~/.depictio/cli.yaml", "~/.depictio/CLI.yaml")

# What load_depictio_config already announced in this process: a command reloads its
# configuration at several steps (login, then each step), and once is enough.
_announced: set[str] = set()

# Off for migrate's target, see env_overrides_ignored.
_env_overrides_enabled = True

# Where _read_cli_config says a URL came from when DEPICTIO_CLI_API_BASE_URL set it.
_URL_FROM_ENV = "from DEPICTIO_CLI_API_BASE_URL"


@contextlib.contextmanager
def env_overrides_ignored() -> Iterator[None]:
    """Load configurations as written, without DEPICTIO_CLI_TOKEN and DEPICTIO_CLI_API_BASE_URL.

    For migrate's target. Those variables stand in for the one server a command
    talks to, the source, like DEPICTIO_CLI_CONFIG_PATH does: applied to the target
    too, they would point both at the same server.
    """
    global _env_overrides_enabled
    previous, _env_overrides_enabled = _env_overrides_enabled, False
    try:
        yield
    finally:
        _env_overrides_enabled = previous


def _config_file(yaml_config_path: str) -> ConfigFile:
    """The file a load of ``yaml_config_path`` reads, expanded, and how it was chosen."""
    if yaml_config_path in _DEFAULT_CLI_CONFIG_PATHS:
        return default_server(yaml_config_path)
    return ConfigFile(os.path.expanduser(yaml_config_path))


def cli_config_file(yaml_config_path: str = "~/.depictio/CLI.yaml") -> str:
    """The file load_depictio_config reads for ``yaml_config_path``, the default resolved.

    For a command that can do without a server, and so must know whether one is
    configured before loading anything.
    """
    return _config_file(yaml_config_path).path


def display_path(path: str) -> str:
    """``path`` as printed: the home directory as ``~``, like the commands take it."""
    home = os.path.expanduser("~")
    return "~" + path[len(home) :] if path.startswith(home + os.sep) else path


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


def _origin(yaml_config_path: str, from_env: bool, option: str) -> tuple[str, str]:
    """Where a configuration file came from, and how to point the command at another."""
    if from_env:
        return (
            "from DEPICTIO_CLI_CONFIG_PATH",
            "point DEPICTIO_CLI_CONFIG_PATH at an existing config",
        )
    if yaml_config_path in (*_DEFAULT_CLI_CONFIG_PATHS, DEFAULT_TARGET_CLI_CONFIG):
        # Nobody chose this file, so naming the option as its source would mislead.
        where = "the default" if option == "--server" else f"the default for {option}"
        return where, f"pass {option}: 'local' or an existing config"
    return f"from {option}", f"point {option} at an existing config"


def _summarise(exc: ValidationError) -> str:
    """The first few problems pydantic found, one line each joined, without its URLs."""
    problems = [
        f"{'.'.join(str(part) for part in err['loc']) or 'top level'}: {err['msg']}"
        for err in exc.errors()[:3]
    ]
    return "; ".join(problems)


def _read_cli_config(yaml_config_path: str, option: str = "--server") -> tuple[CLIConfig, str]:
    """The configuration a load of ``yaml_config_path`` reads, and where its URL came from.

    Prints nothing. Raises CLIConfigError, whose message names the file, what is
    wrong with it and, for a missing one, the option that chose it: ``option`` is
    the one that resolved ``yaml_config_path``.
    """
    # DEPICTIO_CLI_CONFIG_PATH and the local server stand in for the path only when the
    # caller left it at a default: an explicit --server always wins.
    chosen = _config_file(yaml_config_path)
    expanded = chosen.path
    shown = display_path(expanded)
    local = is_local_cli_config(expanded)
    # `get_config` signals a missing/unsuitable file with ValueError, so checking
    # here is what turns a typo into a usable message. That matters most for an
    # automated trigger, where the path usually arrives from DEPICTIO_CLI_CONFIG_PATH.
    if not os.path.isfile(expanded):
        if chosen.local_fallback:
            # Nothing named, nothing configured: both ways out, not just the local one.
            raise CLIConfigError(
                "No server configured: start a local one with `depictio local up`, or "
                f"point {option} at a CLI configuration file, downloaded from the CLI "
                f"agents page of a Depictio instance (saved as {yaml_config_path}, it "
                f"needs no {option})."
            )
        where, fix = _origin(yaml_config_path, chosen.from_env, option)
        if local:
            raise CLIConfigError(
                f"No local server configuration at {shown} ({where}): "
                "start one with `depictio local up`."
            )
        if os.path.isdir(expanded):
            raise CLIConfigError(
                f"{shown} is a directory, not a Depictio CLI configuration file ({where}). "
                f"Name the YAML file in it, or {fix}."
            )
        raise CLIConfigError(
            f"Depictio CLI configuration file not found: {shown} ({where}). Create it, or {fix}."
        )
    try:
        raw = get_config(expanded)
    except yaml.YAMLError as exc:
        raise CLIConfigError(f"{shown} is not valid YAML: {exc}") from exc
    except (OSError, ValueError) as exc:
        raise CLIConfigError(f"Cannot read the Depictio CLI configuration {shown}: {exc}") from exc

    # The local server's configuration is complete as `depictio local up` wrote it.
    # The variables are what the Nextflow docs tell people to export for their
    # remote server: applied here, `--server local` would reach that one instead.
    url_from_env = False
    if _env_overrides_enabled and not local:
        url_from_env = bool(os.environ.get("DEPICTIO_CLI_API_BASE_URL"))
        raw = _apply_env_overrides(raw)
    if not isinstance(raw.get("user"), dict):
        raise CLIConfigError(
            f"{shown} has no 'user' key: it is not a Depictio CLI configuration, "
            "or an incomplete one."
        )
    try:
        config = validate_depictio_cli_config(raw)
    except ValidationError as exc:
        raise CLIConfigError(
            f"{shown} is not a valid Depictio CLI configuration: {_summarise(exc)}"
        ) from exc
    source = f"configuration {shown}"
    if url_from_env:
        source = f"{_URL_FROM_ENV}, {source}"
    elif chosen.local_fallback:
        # Said, so that a command meant for a remote server shows why it is not there.
        source = f"local server, as no {yaml_config_path} exists; {source}"
    return config, source


def read_depictio_config(yaml_config_path: str = "~/.depictio/CLI.yaml") -> CLIConfig:
    """load_depictio_config without a word: a configuration it cannot use raises
    CLIConfigError, naming the file, instead of ending the command.

    For a command that can do without a server, and so must not fail on a default
    configuration it cannot use.
    """
    return _read_cli_config(yaml_config_path)[0]


# Where the local server and the services `depictio local up` starts listen.
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
# Every name a URL may give this machine: the above, and IPv6's.
_LOOPBACK_NAMES = (*_LOOPBACK_HOSTS, "::1")
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def _bypass_proxy_for_loopback(api_base_url: str) -> None:
    """Keep requests to a server on this machine away from a proxy set in the environment.

    httpx and boto3 send through HTTP(S)_PROXY, and a usual no_proxy=localhost does
    not cover 127.0.0.1, where the local server listens: the proxy cannot reach this
    machine's loopback, so every call would fail. Set before the first request,
    since an HTTP client reads these variables when it is created.
    """
    host = urlparse(api_base_url).hostname
    if host not in _LOOPBACK_NAMES:
        return
    if not any(os.environ.get(var) for var in _PROXY_VARS):
        return
    # Both spellings, merged: a client reads one or the other, so neither may lose an
    # entry the other holds.
    loopback = (*_LOOPBACK_HOSTS, "::1") if host == "::1" else _LOOPBACK_HOSTS
    entries = [
        entry.strip()
        for var in ("no_proxy", "NO_PROXY")
        for entry in os.environ.get(var, "").split(",")
        if entry.strip()
    ]
    merged = ",".join(dict.fromkeys([*entries, *loopback]))
    if os.environ.get("no_proxy") != merged or os.environ.get("NO_PROXY") != merged:
        os.environ["no_proxy"] = os.environ["NO_PROXY"] = merged


def _same_loopback_server(url: str, other: str) -> bool:
    """Whether two URLs reach the same port of this machine, however they name it."""
    first, second = urlparse(url), urlparse(other)
    return (
        first.hostname in _LOOPBACK_NAMES
        and second.hostname in _LOOPBACK_NAMES
        and first.port == second.port
    )


def _warn_local_server_running(yaml_config_path: str, api_base_url: str, option: str) -> None:
    """After the Server line of a default: the local server, when it runs besides it.

    A default only: a server named with --server is the one meant, whatever it is.
    Once per command, like that line.
    """
    local_url = local_server_running_instead(yaml_config_path, api_base_url)
    if not local_url:
        return
    warning = f"A local server is running too ({local_url}): add {option} local to use it"
    if warning not in _announced:
        _announced.add(warning)
        rich_print_checked_statement(warning, "warning")


@validate_call(validate_return=True)
def load_depictio_config(
    yaml_config_path: str = "~/.depictio/CLI.yaml",
    quiet: bool = False,
    option: str = "--server",
    label: str | None = None,
    local_hint: bool = True,
) -> CLIConfig:
    """
    Load the Depictio configuration file.

    Unless ``quiet``, it announces the server the command will talk to, and from
    which file: the wrong server is the usual reason a command fails. ``quiet`` is
    for callers that re-read an already-loaded config only to name a field (the API
    URL in an error message, the viewer URL in the summary).

    ``option`` is the option that named ``yaml_config_path``, so that a missing file
    is blamed on the one the user typed. ``label`` replaces "Server" in the
    announcement, for a command that talks to two servers, and always prints.
    When no server was named and the local server runs besides the default one,
    a warning after the announcement says how to use it, unless ``local_hint`` is
    False: for migrate, when its other server is the local one.

    A configuration it cannot use is reported as such, naming the file, and ends
    the command with exit code 1.
    """
    try:
        config, source = _read_cli_config(yaml_config_path, option)
    except CLIConfigError as exc:
        logger.debug(f"Unusable Depictio CLI configuration: {exc}")
        # Paths, YAML and pydantic errors can hold brackets Rich would read as markup.
        rich_print_checked_statement(escape(str(exc)), "error")
        raise typer.Exit(code=1) from exc
    _bypass_proxy_for_loopback(str(config.api_base_url))
    target = f"{config.api_base_url} ({source})"
    if not quiet and (label or target not in _announced):
        _announced.add(target)
        rich_print_checked_statement(f"{label or 'Server'}: {target}", "info")
        # An unexpanded default spelling: no server was named, see _config_file.
        if local_hint and yaml_config_path in _DEFAULT_CLI_CONFIG_PATHS:
            _warn_local_server_running(yaml_config_path, str(config.api_base_url), option)
    return config
