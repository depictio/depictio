"""``depictio project-builder <dir>``: define a project's data collections from a folder.

For a folder no shipped template recognises, on a machine without a Depictio
server (an HPC login node, a laptop): opens the Project Builder in the
browser, served by a small local server that reads only that folder and needs
no MongoDB, Redis or S3. It writes an ad-hoc template next to the data, which
``depictio ingest <dir> --template <bundle>`` then runs against any server. With
a server at hand (``depictio local up``, or a shared one) the same builder is
under Projects → Create → Advanced project, and creates the project directly.

FastAPI and uvicorn come with ``depictio[builder]`` (or ``[server]``/``[local]``);
nothing here imports them until the command runs.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Annotated

import typer

INSTALL_BUILDER = "uv tool install 'depictio[builder]'  (or: pip install 'depictio[builder]')"


def _missing_server_modules() -> list[str]:
    missing = []
    for module in ("fastapi", "uvicorn"):
        try:
            if importlib.util.find_spec(module) is None:
                missing.append(module)
        except ModuleNotFoundError:
            missing.append(module)
    return missing


def _viewer_dist() -> Path:
    """The viewer bundle to serve, built first on a source checkout when it is
    missing or older than its sources (as ``depictio local up`` does)."""
    from depictio.cli.cli.local_stack import (
        build_viewer,
        package_root,
        viewer_built,
        viewer_outdated,
        viewer_workspace,
    )

    workspace = viewer_workspace()
    if workspace is not None:
        reason = viewer_outdated(workspace)
        if reason is not None:
            log_path = Path.home() / ".depictio" / "builder" / "viewer-build.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            typer.echo(f"  Building the viewer bundle ({reason}); output in {log_path}")
            build_viewer(workspace, log_path)
    root = package_root()
    if root is None or not viewer_built():
        typer.echo(
            "  This installation has no viewer bundle, so the Project Builder cannot be "
            "shown. Reinstall depictio from a release, or build it: "
            "cd depictio/viewer && pnpm run build",
            err=True,
        )
        raise typer.Exit(code=1)
    return root / "viewer" / "dist"


def register_project_builder_command(app: typer.Typer) -> None:
    @app.command("project-builder")
    def project_builder(
        directory: Annotated[
            Path,
            typer.Argument(help="The folder to define data collections from"),
        ] = Path("."),
        out: Annotated[
            Path | None,
            typer.Option(
                "--out",
                help="Folder to write the template bundle to (default: <dir>/.depictio/template, "
                "or ~/.depictio/builder/... when <dir> is read-only)",
            ),
        ] = None,
        host: Annotated[
            str, typer.Option("--host", help="Address to serve on (default: this machine only)")
        ] = "127.0.0.1",
        port: Annotated[int, typer.Option("--port", help="Port to serve on")] = 8129,
        no_open: Annotated[bool, typer.Option("--no-open", help="Do not open a browser")] = False,
    ) -> None:
        """Define a project's data collections from a folder no template fits, in the browser."""
        missing = _missing_server_modules()
        if missing:
            typer.echo(
                f"  The Project Builder needs {', '.join(missing)}, which this installation "
                f"lacks. Install it with: {INSTALL_BUILDER}",
                err=True,
            )
            raise typer.Exit(code=1)

        root = directory.expanduser().resolve()
        if not root.is_dir():
            typer.echo(f"  Not a folder: {root}", err=True)
            raise typer.Exit(code=1)

        viewer_dist = _viewer_dist()
        from depictio.project_builder.standalone import serve

        shown_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        typer.echo(f"  Depictio Project Builder on {root}")
        typer.echo(f"  Open http://{shown_host}:{port}/projects/build  (Ctrl-C to stop)")
        try:
            serve(
                root,
                viewer_dist=viewer_dist,
                host=host,
                port=port,
                out_dir=out.expanduser().resolve() if out else None,
                open_browser=not no_open,
            )
        except KeyboardInterrupt:
            typer.echo("\n  Stopped.")
