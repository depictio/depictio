import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

from depictio.cli.cli.local_stack import (
    LocalStackError,
    Paths,
    check_server_installed,
    chromium_installed,
    ensure_binaries,
    install_chromium,
    load_secrets,
    load_state,
    local_home,
    pick_ports,
    reset,
    running_status,
    save_state,
    seed_screenshots,
    server_env,
    start_services,
    stop_all,
    viewer_built,
    wait_for_api,
)
from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement

app = typer.Typer(
    help="Run a complete Depictio server on this machine, without Docker.",
    no_args_is_help=True,
)


def _info(msg: str) -> None:
    rich_print_checked_statement(msg, "info")


def _fail(msg: str) -> None:
    rich_print_checked_statement(msg, "error")
    raise typer.Exit(code=1)


def _absolutize_path_var(var: str) -> str:
    """`run` resolves relative variables against --data-root; users type them from cwd."""
    key, sep, value = var.partition("=")
    if sep and value and not Path(value).is_absolute() and Path(value).exists():
        return f"{key}={Path(value).resolve()}"
    return var


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
            help="Bundled example projects to seed: comma-separated names, 'all' or 'none'. "
            "Defaults to 'iris,penguins' without --template and 'none' with it.",
        ),
    ] = None,
    port: Annotated[
        int | None, typer.Option("--port", help="API/viewer port (default 8058, or a free one)")
    ] = None,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the dashboards page in a browser")
    ] = True,
    screenshots: Annotated[
        bool | None,
        typer.Option(
            "--screenshots/--no-screenshots",
            help="Dashboard thumbnails via Playwright. --screenshots installs Chromium "
            "(~150 MB) if needed; by default they are on only when Chromium is already there.",
        ),
    ] = None,
):
    """Start MongoDB, Redis, SeaweedFS, the API and the worker locally, then ingest a template."""
    if (template is None) != (data_root is None):
        _fail("--template and --data-root go together")
    if data_root is not None and not data_root.is_dir():
        _fail(f"--data-root {data_root} is not a directory")

    paths = Paths(local_home())
    paths.ensure_dirs()
    try:
        check_server_installed()
        if not viewer_built():
            rich_print_checked_statement(
                "The viewer bundle (depictio/viewer/dist) is not built: the API will run but "
                "dashboards will not render. Build it with: cd depictio/viewer && pnpm run build",
                "warning",
            )

        state = load_state(paths)
        if all(running_status(paths).values()):
            ports = state["ports"]
            _info(f"Depictio is already running at {state['url']}")
        else:
            stop_all(paths, log=_info)
            ensure_binaries(paths, log=_info)
            seed_screenshots(paths)
            ports = pick_ports(port)
            if screenshots and not chromium_installed():
                _info("Installing Chromium for dashboard thumbnails")
                install_chromium()
            thumbnails = chromium_installed() if screenshots is None else screenshots
            seed = examples or ("none" if template else "iris,penguins")
            secret_values = load_secrets(paths)
            env = server_env(paths, ports, secret_values, seed, thumbnails)
            url = f"http://127.0.0.1:{ports['api']}"
            state = {"pids": {}, "ports": ports, "url": url, "home": str(paths.home)}
            save_state(paths, state)
            procs = start_services(paths, ports, secret_values, env)
            state["pids"] = {name: proc.pid for name, proc in procs.items()}
            save_state(paths, state)
            _info(f"Services started (logs in {paths.logs}); waiting for the API")
            wait_for_api(paths, ports, procs["api"])
    except LocalStackError as exc:
        stop_all(paths, log=_info)
        _fail(str(exc))

    url = state["url"]
    if template and data_root is not None:
        cmd = [
            sys.executable,
            "-c",
            "from depictio.cli.depictio_cli import main; main()",
            "run",
            "--template",
            template,
            "--data-root",
            str(data_root.resolve()),
            "--CLI-config-path",
            str(paths.cli_config),
        ]
        if project_name:
            cmd += ["--project-name", project_name]
        for var in variables or []:
            cmd += ["--var", _absolutize_path_var(var)]
        _info(f"Ingesting {data_root} with template {template}")
        if subprocess.call(cmd) != 0:
            _fail("Ingestion failed; the server is still running (depictio local down to stop)")

    dashboards_url = f"{url}/dashboards"
    rich_print_checked_statement(f"Depictio is ready: {dashboards_url}", "success")
    _info(f"CLI config for this instance: {paths.cli_config}")
    if open_browser:
        webbrowser.open(dashboards_url)


@app.command()
def down():
    """Stop every process started by `depictio local up`."""
    paths = Paths(local_home())
    stop_all(paths, log=_info)
    rich_print_checked_statement("Depictio local server stopped", "success")


@app.command()
def status():
    """Show which local processes are running."""
    paths = Paths(local_home())
    state = load_state(paths)
    if not state:
        _info("Depictio local server is not running")
        return
    for name, alive in running_status(paths).items():
        port = state["ports"].get(name, state["ports"]["api"] if name == "worker" else None)
        where = f" (port {port})" if name != "worker" else ""
        rich_print_checked_statement(
            f"{name}{where}: {'running' if alive else 'stopped'}", "success" if alive else "error"
        )
    _info(f"URL: {state['url']}  logs: {Path(state['home']) / 'logs'}")


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
