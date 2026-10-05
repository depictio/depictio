import os
import shlex
import sys
import webbrowser
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.markup import escape

from depictio.cli.cli.local_compose import export_compose
from depictio.cli.cli.local_stack import (
    LocalStackError,
    Paths,
    State,
    api_healthy,
    check_platform_supported,
    check_server_installed,
    examples_loading,
    ingest,
    local_home,
    parse_examples,
    reset,
    running_status,
    start_stack,
    stop_all,
    viewer_built,
    wait_for_examples,
)
from depictio.cli.cli.utils.rich_utils import console, rich_print_checked_statement

app = typer.Typer(
    help="Run a complete Depictio server on this machine, without Docker.",
    no_args_is_help=True,
)


def _info(msg: str) -> None:
    rich_print_checked_statement(msg, "info")


def _warn(msg: str) -> None:
    rich_print_checked_statement(msg, "warning")


def _fail(msg: str) -> NoReturn:
    rich_print_checked_statement(msg, "error")
    raise typer.Exit(code=1)


def _print_rows(rows: list[tuple[str, str]]) -> None:
    for label, value in rows:
        # soft_wrap: long paths stay on one line, so commands copy-paste intact.
        console.print(f"  [bold]{label}:[/bold] {escape(value)}", soft_wrap=True, highlight=False)


def _has_display() -> bool:
    """Whether a browser opened here shows up on the user's screen.

    Over SSH, or on Linux without a display server, webbrowser falls back to a text
    browser (lynx, w3m) that takes over the terminal.
    """
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


def _check_up_flags(template: str | None, data_root: Path | None, examples: str | None) -> str:
    """Reject flags that do not go together, before anything starts; returns the seed."""
    if (template is None) != (data_root is None):
        _fail("--template and --data-root go together")
    if data_root is not None and not data_root.is_dir():
        _fail(f"--data-root {data_root} is not a directory")
    try:
        return parse_examples(examples, template)
    except LocalStackError as exc:
        _fail(str(exc))


def _start_or_reuse(
    paths: Paths, port: int | None, seed: str, examples_given: bool, screenshots: bool | None
) -> State:
    """The server already running, else a new one; exits 1 on failure and 130 on Ctrl-C.

    A failed check never takes down a server that was already running: only
    start_stack stops services (an earlier run's leftovers, then on error what
    it started).
    """
    starting = False
    try:
        check_platform_supported()
        check_server_installed()
        if not viewer_built():
            _warn(
                "The viewer bundle (depictio/viewer/dist) is not built: the API will run but "
                "dashboards will not render. Build it with: cd depictio/viewer && pnpm run build"
            )
        state = State.load(paths)
        if state is not None and all(running_status(paths).values()):
            _info(f"Depictio is already running at {state.url}")
            # Applied at startup only; ingestion with --template still goes ahead.
            ignored = [
                ("--port", port is not None and port != state.ports["api"]),
                ("--examples", examples_given),
                ("--screenshots" if screenshots else "--no-screenshots", screenshots is not None),
            ]
            for flag, given in ignored:
                if given:
                    _warn(
                        f"{flag} is ignored: the server is already running "
                        "(depictio local down first)"
                    )
            return state
        starting = True
        return start_stack(paths, port, seed, bool(screenshots), log=_info, warn=_warn)
    except LocalStackError as exc:
        _fail(str(exc))
    except KeyboardInterrupt:
        _warn(
            "Interrupted: services started by this run are stopped" if starting else "Interrupted"
        )
        raise typer.Exit(code=130)


def _wait_for_examples(paths: Paths, state: State) -> None:
    """Hold `ready` until the examples are loaded, so their dashboards show data.

    The API loads them in the background, and on a first run stopping it in the
    meantime would leave them half loaded.
    """
    try:
        if not examples_loading(paths, state):
            return
        _info("Loading the examples")
        missing = wait_for_examples(paths, state)
    except KeyboardInterrupt:
        _warn(
            "Interrupted: the server keeps running and finishes loading the examples "
            "(depictio local down to stop)"
        )
        raise typer.Exit(code=130)
    if missing:
        plural = len(missing) > 1
        _warn(
            f"The {' and '.join(missing)} example{'s' if plural else ''} did not finish "
            "loading, so the dashboards show no data. depictio local wipe, then depictio "
            f"local up, reloads {'them' if plural else 'it'} (details in {paths.logs / 'api.log'})"
        )


def _ingest(
    paths: Paths,
    template: str,
    data_root: Path,
    variables: list[str] | None,
    project_name: str | None,
) -> None:
    """Ingest with `depictio run`; on failure the server keeps running."""
    _info(f"Ingesting {data_root} with template {template}")
    try:
        code = ingest(paths, template, data_root, variables, project_name)
    except KeyboardInterrupt:
        _warn("Ingestion interrupted; the server is still running (depictio local down to stop)")
        raise typer.Exit(code=130)
    if code != 0:
        _fail("Ingestion failed; the server is still running (depictio local down to stop)")


def _print_summary(
    paths: Paths, state: State, template: str | None, data_root: Path | None
) -> None:
    rich_print_checked_statement(f"Depictio is ready: {state.url}/dashboards", "success")
    rows = []
    if state.examples:
        rows.append(("Examples", state.examples.replace(",", ", ")))
    if template and data_root is not None:
        rows.append(("Ingested", f"{data_root.resolve()} ({template})"))
    rows += [
        ("Data", f"{paths.home} (logs in {paths.logs})"),
        ("Add data", "depictio local up --template <template> --data-root <dir>"),
        ("CLI on this server", f"export DEPICTIO_CLI_CONFIG_PATH={paths.cli_config}"),
        ("Stop", "depictio local down"),
    ]
    _print_rows(rows)


def _open_dashboards(state: State) -> None:
    if _has_display():
        webbrowser.open(f"{state.url}/dashboards")
        return
    api_port = state.ports["api"]
    _info(
        f"No browser here: from your machine, run ssh -L {api_port}:127.0.0.1:{api_port} "
        f"<host>, then open {state.url}/dashboards"
    )


@app.command()
def up(
    template: Annotated[
        str | None,
        typer.Option("--template", help="Template to ingest, e.g. nf-core/rnaseq/latest"),
    ] = None,
    data_root: Annotated[
        Path | None,
        typer.Option("--data-root", help="Pipeline results directory to ingest with --template"),
    ] = None,
    project_name: Annotated[
        str | None, typer.Option("--project-name", help="Name of the ingested project")
    ] = None,
    variables: Annotated[
        list[str] | None,
        typer.Option(
            "--var",
            help="Template variable KEY=VALUE, passed to `depictio run` (repeatable), "
            "e.g. --var SAMPLESHEET_FILE=samplesheet.csv",
        ),
    ] = None,
    examples: Annotated[
        str | None,
        typer.Option(
            "--examples",
            help="Example projects to seed: iris, penguins, iris,penguins or none. "
            "Defaults to iris,penguins without --template and none with it.",
        ),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(
            "--port",
            help="API/viewer port, kept for later runs (default: the previous one, "
            "else 8058 or a free one)",
        ),
    ] = None,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the dashboards page in a browser")
    ] = True,
    screenshots: Annotated[
        bool | None,
        typer.Option(
            "--screenshots/--no-screenshots",
            help="Dashboard thumbnails via Playwright; installs Chromium (~150 MB) if "
            "needed. Off by default.",
        ),
    ] = None,
):
    """Start MongoDB, Redis, SeaweedFS, the API and the worker locally, then ingest a template."""
    seed = _check_up_flags(template, data_root, examples)
    paths = Paths(local_home())
    paths.ensure_dirs()
    state = _start_or_reuse(paths, port, seed, examples is not None, screenshots)
    _wait_for_examples(paths, state)
    if template and data_root is not None:
        _ingest(paths, template, data_root, variables, project_name)
    _print_summary(paths, state, template, data_root)
    if open_browser:
        _open_dashboards(state)


@app.command()
def down():
    """Stop every process started by `depictio local up`."""
    paths = Paths(local_home())
    if stop_all(paths, log=_info):
        rich_print_checked_statement("Depictio local server stopped", "success")
    else:
        _info("Depictio local is not running.")


@app.command()
def status():
    """Show which local processes are running and whether the API answers."""
    paths = Paths(local_home())
    state = State.load(paths)
    if state is None:
        _info("Depictio local is not running.")
        return
    for name, alive in running_status(paths).items():
        where = f" (port {state.ports[name]})" if name in state.ports else ""
        rich_print_checked_statement(
            f"{name}{where}: {'running' if alive else 'stopped'}", "success" if alive else "error"
        )
    healthy = api_healthy(state.ports["api"])
    rich_print_checked_statement(
        f"API at {state.url}: {'reachable' if healthy else 'not reachable'}",
        "success" if healthy else "error",
    )
    _info(f"Logs: {Path(state.home) / 'logs'}")


@app.command()
def wipe(
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation")] = False,
):
    """Stop the server and delete all local data (downloaded binaries are kept)."""
    paths = Paths(local_home())
    if not yes and not typer.confirm(f"Delete all Depictio data under {paths.home}?"):
        raise typer.Exit()
    stop_all(paths, log=_info)
    reset(paths)
    rich_print_checked_statement("Local data deleted", "success")


@app.command("export-compose")
def export_compose_cmd(
    out: Annotated[
        Path,
        typer.Option("--out", help="Directory to create for the Docker Compose stack"),
    ] = Path("depictio-docker"),
):
    """Copy the local server's data into a directory Docker Compose runs as is.

    A running local server is stopped first, so the copy is consistent.
    """
    paths = Paths(local_home())
    out = out.resolve()
    try:
        export_compose(paths, out, log=_info)
    except LocalStackError as exc:
        _fail(str(exc))
    rich_print_checked_statement(f"Exported to {out}", "success")
    _print_rows(
        [
            ("Start it", f"cd {shlex.quote(str(out))} && docker compose up -d"),
            ("Then open", "http://localhost:5080"),
        ]
    )
