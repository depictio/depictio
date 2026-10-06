"""`depictio template ...`: templates you can read, edit and run with `depictio run --template`."""

from pathlib import Path
from typing import Annotated

import typer

from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement

app = typer.Typer(
    help="Project templates: compose one from a results directory.",
    no_args_is_help=True,
)


@app.callback()
def _group() -> None:
    """Project templates: compose one from a results directory."""


@app.command("compose")
def compose(
    data_root: Annotated[Path, typer.Argument(help="Results directory to compose a dashboard for")],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Write the template here, to edit it and run it with `depictio run "
            "--template <dir>`. Default: where `depictio run` keeps composed templates",
        ),
    ] = None,
    include_unknown: Annotated[
        bool,
        typer.Option(
            "--include-unknown",
            help="Also include the tabular files the catalog does not recognise",
        ),
    ] = False,
    include: Annotated[
        list[str] | None,
        typer.Option(
            "--include",
            help="Include the unrecognised files matching this glob (relative to the "
            "directory); repeatable",
        ),
    ] = None,
    project_name: Annotated[
        str | None, typer.Option("--project-name", help="Name of the project to create")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="List everything left out, with the reason")
    ] = False,
):
    """Compose a template from the files the catalog recognises in a results directory.

    Offline: nothing is ingested. Prints what was recognised, the tabs and key
    metrics of the dashboard, what was left out and why, and the tabular files
    nothing recognised with what each could show. This is what `depictio run
    --data-root` does by itself when no bundled template fits the run.
    """
    from depictio.cli.cli.utils.compose import ComposedTemplate, compose_template, print_report
    from depictio.models.models.run_info import read_run_info

    if not data_root.is_dir():
        rich_print_checked_statement(f"{data_root} is not a directory", "error")
        raise typer.Exit(code=1)
    info = read_run_info(data_root)
    result = compose_template(
        data_root,
        out_dir=output,
        include_unknown=include_unknown,
        include=include or (),
        project_name=project_name,
        pipeline_name=info.pipeline_name if info else None,
        pipeline_version=info.pipeline_version if info else None,
        engine=info.engine if info else None,
    )
    print_report(result, verbose=verbose)
    if not isinstance(result, ComposedTemplate):
        rich_print_checked_statement(
            f"Nothing in {data_root} is recognised by the catalog: no template written.",
            "warning",
        )
        raise typer.Exit(code=1)
    rich_print_checked_statement(f"Template written to {result.template_dir}", "success")
    rich_print_checked_statement(
        f"Ingest it: depictio run --template {result.template_dir} --data-root {data_root} "
        f"(or depictio local up --data-root {data_root})",
        "info",
    )
