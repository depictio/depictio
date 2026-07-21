"""``depictio project-builder <dir>`` — launch the local, service-free Project Builder.

Opens a browser UI on localhost served by a standalone uvicorn app (no Mongo/
Redis/Celery/S3). Point at a folder → associate file(s) to Data Collections
(scan glob/regex inferred by config-by-example) → write a ``depictio_project.yaml``
you feed to ``depictio run``. Dashboards are authored later in the editor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer


def register_project_builder_command(app: typer.Typer) -> None:
    def project_builder(
        directory: Annotated[
            str,
            typer.Argument(help="Folder to author from (root of the file tree)"),
        ] = ".",
        host: Annotated[
            str, typer.Option("--host", help="Host to bind the Project Builder server to")
        ] = "127.0.0.1",
        port: Annotated[
            int, typer.Option("--port", help="Port to serve the Project Builder on")
        ] = 8129,
        no_open: Annotated[
            bool, typer.Option("--no-open", help="Do not open a browser tab")
        ] = False,
    ) -> None:
        """Launch the local Depictio Project Builder on a run directory."""
        from depictio.project_builder.server import run_project_builder

        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            typer.echo(f"Not a directory: {root}")
            raise typer.Exit(code=1)

        typer.echo(f"  Depictio Project Builder — authoring from {root}")
        typer.echo(f"  Serving at http://{host}:{port}/  (Ctrl-C to stop)")
        try:
            run_project_builder(root, host=host, port=port, open_browser=not no_open)
        except KeyboardInterrupt:
            typer.echo("\n  stopped.")

    # Primary command name, plus a hidden `studio` alias for backwards compatibility.
    app.command("project-builder")(project_builder)
    app.command("studio", hidden=True)(project_builder)
