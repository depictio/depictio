"""``depictio studio <dir>`` — launch the local, service-free authoring studio.

Opens a browser UI on localhost served by a standalone uvicorn app (no Mongo/
Redis/Celery/S3). Pick file(s) → preview → design a viz → export a
``project.yaml`` + ``dashboard.yaml`` you can feed to ``depictio run`` /
``depictio dashboard import``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer


def register_studio_command(app: typer.Typer) -> None:
    @app.command("studio")
    def studio(
        directory: Annotated[
            str,
            typer.Argument(help="Run directory to author from (root of the file tree)"),
        ] = ".",
        host: Annotated[
            str, typer.Option("--host", help="Host to bind the studio server to")
        ] = "127.0.0.1",
        port: Annotated[int, typer.Option("--port", help="Port to serve the studio on")] = 8129,
        no_open: Annotated[
            bool, typer.Option("--no-open", help="Do not open a browser tab")
        ] = False,
    ) -> None:
        """Launch the local Depictio Studio on a run directory."""
        from depictio.authoring.server import run_studio

        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            typer.echo(f"Not a directory: {root}")
            raise typer.Exit(code=1)

        typer.echo(f"  Depictio Studio — authoring from {root}")
        typer.echo(f"  Serving at http://{host}:{port}/  (Ctrl-C to stop)")
        try:
            run_studio(root, host=host, port=port, open_browser=not no_open)
        except KeyboardInterrupt:
            typer.echo("\n  stopped.")
