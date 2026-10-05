import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape

from depictio.cli.cli.local_stack import (
    COMPOSE_URL,
    LocalStackError,
    Paths,
    api_healthy,
    check_alive,
    check_platform_supported,
    check_server_installed,
    chromium_installed,
    ensure_binaries,
    export_compose,
    install_chromium,
    load_ports,
    load_secrets,
    load_state,
    local_home,
    parse_examples,
    pick_ports,
    process_start_time,
    reset,
    running_status,
    save_ports,
    save_state,
    seed_screenshots,
    server_env,
    start_services,
    stop_all,
    viewer_built,
    wait_for_api,
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


def _fail(msg: str) -> None:
    rich_print_checked_statement(msg, "error")
    raise typer.Exit(code=1)


def _absolutize_path_var(var: str) -> str:
    """`run` resolves relative variables against --data-root; users type them from cwd."""
    key, sep, value = var.partition("=")
    if sep and value and not Path(value).is_absolute() and Path(value).exists():
        return f"{key}={Path(value).resolve()}"
    return var


def _ingestion_env() -> dict[str, str]:
    """The environment of the `depictio run` child, without DEPICTIO_CLI_* overrides.

    DEPICTIO_CLI_TOKEN and DEPICTIO_CLI_API_BASE_URL, set for another instance,
    would win over the local server's CLI configuration.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("DEPICTIO_CLI_")}


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


def _print_summary(paths: Paths, state: dict, template: str | None, data_root: Path | None) -> None:
    rich_print_checked_statement(f"Depictio is ready: {state['url']}/dashboards", "success")
    rows = []
    if state.get("examples"):
        rows.append(("Examples", state["examples"].replace(",", ", ")))
    if template and data_root is not None:
        rows.append(("Ingested", f"{data_root.resolve()} ({template})"))
    rows += [
        ("Data", f"{paths.home} (logs in {paths.logs})"),
        ("Add data", "depictio local up --template <template> --data-root <dir>"),
        ("CLI on this server", f"export DEPICTIO_CLI_CONFIG_PATH={paths.cli_config}"),
        ("Stop", "depictio local down"),
    ]
    for label, value in rows:
        # soft_wrap: long paths stay on one line, so commands copy-paste intact.
        console.print(f"  [bold]{label}:[/bold] {escape(value)}", soft_wrap=True, highlight=False)


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
    if (template is None) != (data_root is None):
        _fail("--template and --data-root go together")
    if data_root is not None and not data_root.is_dir():
        _fail(f"--data-root {data_root} is not a directory")
    try:
        seed = parse_examples(examples, template)
    except LocalStackError as exc:
        _fail(str(exc))

    paths = Paths(local_home())
    paths.ensure_dirs()
    # Set once services may have been started, so a failure stops them, but a
    # failed check never takes down a server that was already running.
    starting = False
    try:
        check_platform_supported()
        check_server_installed()
        if not viewer_built():
            _warn(
                "The viewer bundle (depictio/viewer/dist) is not built: the API will run but "
                "dashboards will not render. Build it with: cd depictio/viewer && pnpm run build"
            )

        state = load_state(paths)
        if all(running_status(paths).values()):
            _info(f"Depictio is already running at {state['url']}")
            # Applied at startup only; ingestion with --template still goes ahead.
            ignored = [
                ("--port", port is not None and port != state["ports"]["api"]),
                ("--examples", examples is not None),
                ("--screenshots" if screenshots else "--no-screenshots", screenshots is not None),
            ]
            for flag, given in ignored:
                if given:
                    _warn(
                        f"{flag} is ignored: the server is already running "
                        "(depictio local down first)"
                    )
        else:
            starting = True
            stop_all(paths, log=_info)
            ensure_binaries(paths, log=_info)
            seed_screenshots(paths)
            saved_ports = load_ports(paths)
            ports = pick_ports(port, saved_ports)
            if port is None and saved_ports.get("api", ports["api"]) != ports["api"]:
                _warn(
                    f"Port {saved_ports['api']} is now used by another program: "
                    f"Depictio moves to port {ports['api']}"
                )
            save_ports(paths, ports)
            if screenshots and not chromium_installed():
                _info("Installing Chromium for dashboard thumbnails")
                install_chromium()
            secret_values = load_secrets(paths)
            env = server_env(paths, ports, secret_values, seed, bool(screenshots))
            url = f"http://127.0.0.1:{ports['api']}"
            state = {
                "pids": {},
                "ports": ports,
                "url": url,
                "home": str(paths.home),
                "examples": seed,
            }
            save_state(paths, state)
            procs = start_services(paths, ports, secret_values, env)
            state["pids"] = {name: proc.pid for name, proc in procs.items()}
            state["start_times"] = {
                name: process_start_time(proc.pid) for name, proc in procs.items()
            }
            save_state(paths, state)
            _info(f"Services started (logs in {paths.logs}); waiting for the API")
            wait_for_api(paths, ports, procs["api"])
            check_alive(paths, procs)
    except LocalStackError as exc:
        if starting:
            stop_all(paths, log=_info)
        _fail(str(exc))
    except KeyboardInterrupt:
        if starting:
            stop_all(paths, log=_info)
        _warn(
            "Interrupted: services started by this run are stopped" if starting else "Interrupted"
        )
        raise typer.Exit(code=130)

    if template and data_root is not None:
        cmd = [
            sys.executable,
            "-m",
            "depictio.cli",
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
        try:
            code = subprocess.call(cmd, env=_ingestion_env())
        except KeyboardInterrupt:
            _warn(
                "Ingestion interrupted; the server is still running (depictio local down to stop)"
            )
            raise typer.Exit(code=130)
        if code != 0:
            _fail("Ingestion failed; the server is still running (depictio local down to stop)")

    _print_summary(paths, state, template, data_root)
    if open_browser:
        if _has_display():
            webbrowser.open(f"{state['url']}/dashboards")
        else:
            api_port = state["ports"]["api"]
            _info(
                f"No browser here: from your machine, run ssh -L {api_port}:127.0.0.1:{api_port} "
                f"<host>, then open {state['url']}/dashboards"
            )


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
    state = load_state(paths)
    if not state:
        _info("Depictio local is not running.")
        return
    ports = state["ports"]
    for name, alive in running_status(paths).items():
        where = f" (port {ports[name]})" if name in ports else ""
        rich_print_checked_statement(
            f"{name}{where}: {'running' if alive else 'stopped'}", "success" if alive else "error"
        )
    healthy = api_healthy(ports["api"])
    rich_print_checked_statement(
        f"API at {state['url']}: {'reachable' if healthy else 'not reachable'}",
        "success" if healthy else "error",
    )
    _info(f"Logs: {Path(state['home']) / 'logs'}")


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
    """Copy the local server's data into a directory Docker Compose runs as is."""
    paths = Paths(local_home())
    out = out.resolve()
    try:
        compose_copied = export_compose(paths, out, log=_info)
    except LocalStackError as e:
        _fail(str(e))
    rich_print_checked_statement(f"Exported to {out}", "success")
    _info(f"cd {out}")
    if not compose_copied:
        _info(f"curl -LO {COMPOSE_URL}")
    _info("docker compose up -d   # then http://localhost:5080")
