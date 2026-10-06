"""The server a command talks to.

Every command that reaches a Depictio server takes ``--server``: ``local`` for the
server `depictio local up` runs, or the path to a CLI configuration file. Without it,
load_depictio_config reads $DEPICTIO_CLI_CONFIG_PATH, else ~/.depictio/CLI.yaml.
"""

from __future__ import annotations

from typing import Annotated

import typer

DEFAULT_CLI_CONFIG = "~/.depictio/CLI.yaml"
LOCAL = "local"

ServerOption = Annotated[
    str | None,
    typer.Option(
        "--server",
        help="Server to use: 'local' for the one `depictio local up` runs, or a CLI "
        "configuration file. Default: $DEPICTIO_CLI_CONFIG_PATH, else ~/.depictio/CLI.yaml",
        show_default=False,
    ),
]

# The option every command took before --server. Still accepted, out of the help.
LegacyConfigPathOption = Annotated[str | None, typer.Option("--CLI-config-path", hidden=True)]


def resolve_server(server: str | None, legacy_path: str | None = None) -> str:
    """The CLI configuration file for ``--server``, or for the legacy option given instead."""
    if server and legacy_path:
        raise typer.BadParameter(
            "give --server or --CLI-config-path, not both", param_hint="--server"
        )
    value = server or legacy_path
    if value is None:
        # Left at the default, so DEPICTIO_CLI_CONFIG_PATH still applies.
        return DEFAULT_CLI_CONFIG
    if value == LOCAL:
        from depictio.cli.cli.local_stack import Paths, local_home

        path = Paths(local_home()).cli_config
        if not path.is_file():
            raise typer.BadParameter(
                f"no local server configuration at {path}: start one with `depictio local up`",
                param_hint="--server",
            )
        return str(path)
    return value
