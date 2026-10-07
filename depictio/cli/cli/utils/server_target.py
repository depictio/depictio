"""The server a command talks to.

Every command that reaches a Depictio server takes ``--server``: ``local`` for the
server `depictio local up` runs, or the path to a CLI configuration file. Without it,
load_depictio_config reads $DEPICTIO_CLI_CONFIG_PATH, else ~/.depictio/CLI.yaml.
`depictio migrate` names its second server with ``--to-server``, which takes the same
values.
"""

from __future__ import annotations

from typing import Annotated

import typer

DEFAULT_CLI_CONFIG = "~/.depictio/CLI.yaml"
# migrate's target before --to-server existed, kept so its invocations reach the same server.
DEFAULT_TARGET_CLI_CONFIG = "~/.depictio/CLI_remote.yaml"
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


def _resolve(
    value: str | None, legacy_path: str | None, *, option: str, legacy_option: str, default: str
) -> str:
    if value and legacy_path:
        raise typer.BadParameter(f"give {option} or {legacy_option}, not both", param_hint=option)
    if legacy_path and not value:
        from depictio.cli.cli.utils.renamed import note_renamed

        note_renamed(legacy_option, option)
    chosen = value or legacy_path
    if chosen is None:
        # Left at the default, so DEPICTIO_CLI_CONFIG_PATH still applies to --server.
        return default
    if chosen == LOCAL:
        from depictio.cli.cli.local_stack import Paths, local_home

        path = Paths(local_home()).cli_config
        if not path.is_file():
            raise typer.BadParameter(
                f"no local server configuration at {path}: start one with `depictio local up`",
                param_hint=option,
            )
        return str(path)
    return chosen
