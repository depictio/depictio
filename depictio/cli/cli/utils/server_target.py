"""The server a command talks to.

Every command that reaches a Depictio server takes ``--server``: ``local`` for the
server `depictio local up` runs, or the path to a CLI configuration file. Without it,
load_depictio_config reads $DEPICTIO_CLI_CONFIG_PATH, else ~/.depictio/CLI.yaml.
`depictio migrate` names its second server with ``--to-server``, which takes the same
values.
"""

from __future__ import annotations

import os
from typing import Annotated

import typer

DEFAULT_CLI_CONFIG = "~/.depictio/CLI.yaml"
# migrate's target before --to-server existed, kept so its invocations reach the same server.
DEFAULT_TARGET_CLI_CONFIG = "~/.depictio/CLI_remote.yaml"
LOCAL = "local"

SERVER_HELP = (
    "Server to use: 'local' for the one `depictio local up` runs, or a CLI "
    "configuration file. Default: $DEPICTIO_CLI_CONFIG_PATH, else ~/.depictio/CLI.yaml."
)


def _server_option(former: str):
    """--server, its help naming the option a command took before it."""
    return Annotated[
        str | None,
        typer.Option("--server", help=f"{SERVER_HELP} Formerly {former}.", show_default=False),
    ]


ServerOption = _server_option("`--CLI-config-path`")
# The dashboard commands took -c/--config, not --CLI-config-path.
DashboardServerOption = _server_option("`-c/--config`")

# The option every command took before --server. Still accepted, out of the help.
LegacyConfigPathOption = Annotated[str | None, typer.Option("--CLI-config-path", hidden=True)]


def resolve_server(
    server: str | None,
    legacy_path: str | None = None,
    legacy_option: str = "--CLI-config-path",
) -> str:
    """The CLI configuration file for ``--server``, or for the legacy option given instead."""
    return _resolve(
        server,
        legacy_path,
        option="--server",
        legacy_option=legacy_option,
        default=DEFAULT_CLI_CONFIG,
    )


def resolve_target_server(to_server: str | None, legacy_path: str | None = None) -> str:
    """The CLI configuration file for migrate's ``--to-server``, or its ``--target-config``."""
    return _resolve(
        to_server,
        legacy_path,
        option="--to-server",
        legacy_option="--target-config",
        default=DEFAULT_TARGET_CLI_CONFIG,
    )


def is_local(value: str) -> bool:
    """Whether ``value`` names the local server. In any case: nobody means a file called LOCAL."""
    return value.strip().lower() == LOCAL


def local_cli_config() -> str:
    """The CLI configuration `depictio local up` writes.

    It may not exist yet. load_depictio_config says how to create it, and only when a
    command reads it, so `--server local --offline` works without a local server.
    """
    from depictio.cli.cli.local_stack import Paths, local_home

    return str(Paths(local_home()).cli_config)


def is_local_cli_config(path: str) -> bool:
    """Whether ``path`` is the local server's configuration, however it was named."""
    return os.path.realpath(os.path.expanduser(path)) == os.path.realpath(local_cli_config())


def _resolve(
    value: str | None, legacy_path: str | None, *, option: str, legacy_option: str, default: str
) -> str:
    # An empty value would otherwise mean the default without a word, and slip past
    # the "not both" check below.
    for given, name in ((value, option), (legacy_path, legacy_option)):
        if given is not None and not given.strip():
            raise typer.BadParameter(
                "is empty: give 'local' or a CLI configuration file", param_hint=name
            )
    if value and legacy_path:
        raise typer.BadParameter(f"give {option} or {legacy_option}, not both", param_hint=option)
    if legacy_path and not value:
        from depictio.cli.cli.utils.renamed import note_renamed

        note_renamed(legacy_option, option)
    chosen = value or legacy_path
    if chosen is None:
        # Left at the default, so DEPICTIO_CLI_CONFIG_PATH still applies to --server.
        return default
    if is_local(chosen):
        return local_cli_config()
    # Expanded, so a default file named on purpose is not taken for the unexpanded
    # default, which DEPICTIO_CLI_CONFIG_PATH replaces.
    return os.path.expanduser(chosen)
