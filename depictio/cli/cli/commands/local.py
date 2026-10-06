import json
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
    examples_status,
    ingest,
    local_home,
    parse_examples,
    requested_examples,
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


def _check_up_flags(
    template: str | None,
    data_root: Path | None,
    examples: str | None,
    refresh: bool,
    composing: bool = False,
) -> str:
    """Reject flags that do not go together, before anything starts; returns the seed."""
    if data_root is None:
        if template is not None:
            _fail("--template needs --data-root, the directory to ingest")
        if refresh:
            _fail("--refresh needs --data-root, the directory to ingest again")
        if composing:
            _fail("--compose, --include-unknown and --include need --data-root")
    elif template is not None and composing:
        _fail("--compose, --include-unknown and --include build the template: drop --template")
    elif not data_root.is_dir():
        _fail(f"--data-root {data_root} is not a directory")
    try:
        return parse_examples(examples, data_root is not None)
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


def _wait_for_examples(paths: Paths, state: State, asked: list[str]) -> list[str]:
    """Hold `ready` until the examples are loaded, so their dashboards show data.

    The API loads them in the background, and on a first run stopping it in the
    meantime would leave them half loaded. ``asked`` are the examples --examples
    named. Returns the examples this home has.
    """
    try:
        status = examples_status(paths, state)
        if "loading" in status.values():
            _info("Loading the examples")
            status = wait_for_examples(paths, state)
    except KeyboardInterrupt:
        _warn(
            "Interrupted: the server keeps running and finishes loading the examples "
            "(depictio local down to stop)"
        )
        raise typer.Exit(code=130)
    absent = [name for name, s in status.items() if s == "absent"]
    if unseeded := [name for name in absent if name in asked]:
        _warn(
            f"This local home has no {' or '.join(unseeded)} example: examples are added "
            "on its first run only"
        )
    missing = [name for name, s in status.items() if s == "loading"]
    if missing:
        plural = len(missing) > 1
        _warn(
            f"The {' and '.join(missing)} example{'s' if plural else ''} did not finish "
            "loading, so the dashboards show no data. depictio local wipe, then depictio "
            f"local up, reloads {'them' if plural else 'it'} (details in {paths.logs / 'api.log'})"
        )
    return [name for name in requested_examples(state) if name not in absent]


def _read_result(path: Path) -> dict | None:
    """What `depictio run --result-json` wrote, or None (an older CLI, an early failure)."""
    try:
        result = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return result if isinstance(result, dict) else None


def _ingest(
    paths: Paths,
    template: str | None,
    data_root: Path,
    variables: list[str] | None,
    project_name: str | None,
    refresh: bool,
    compose: bool = False,
    include_unknown: bool = False,
    include: list[str] | None = None,
) -> dict | None:
    """Ingest with `depictio run`; on failure the server keeps running.

    Returns what `run` reported, to open the dashboard it made. Ingesting a
    directory a second time is not a failure: `run` changes nothing and names the
    existing project, which is then what gets opened.
    """
    how = (
        f"with template {template}"
        if template
        else "(template composed from the catalog)"
        if compose
        else "(template picked from the run, or composed from the catalog)"
    )
    _info(f"{'Re-ingesting' if refresh else 'Ingesting'} {data_root} {how}")
    result_file = paths.last_ingestion
    result_file.unlink(missing_ok=True)
    try:
        code = ingest(
            paths,
            template,
            data_root,
            variables,
            project_name,
            refresh,
            result_file,
            compose=compose,
            include_unknown=include_unknown,
            include=include,
        )
    except KeyboardInterrupt:
        _warn("Ingestion interrupted; the server is still running (depictio local down to stop)")
        raise typer.Exit(code=130)
    result = _read_result(result_file)
    if code == 2 and result and result.get("status") == "exists":
        project = result.get("project") or {}
        name = project.get("name") or "a project"
        locations = {Path(location).resolve() for location in project.get("locations") or []}
        if locations and data_root.resolve() not in locations:
            # Same project name (a template names its project), another run: --refresh
            # would replace that project's data with this directory's.
            _fail(
                f"A project named {name} already exists, for another directory: pass "
                f"--project-name to ingest {data_root} as a project of its own"
            )
        _info(
            f"{data_root} is already ingested, as {name}: showing it. "
            "--refresh ingests it again and resets its dashboards to the template's"
        )
        return result
    if code != 0:
        _fail("Ingestion failed; the server is still running (depictio local down to stop)")
    return result


def _landing(result: dict | None) -> str:
    """The page to open: the ingested dashboard, else its project, else the list."""
    if result:
        dashboards = [d for d in result.get("dashboards") or [] if d.get("id")]
        if dashboards:
            return f"/dashboard/{dashboards[0]['id']}"
        project_id = (result.get("project") or {}).get("id")
        if project_id:
            return f"/projects/{project_id}"
    return "/dashboards"


def _print_summary(
    paths: Paths,
    state: State,
    examples: list[str],
    template: str | None,
    data_root: Path | None,
    result: dict | None,
) -> None:
    rich_print_checked_statement(f"Depictio is ready: {state.url}{_landing(result)}", "success")
    rows = []
    if examples:
        rows.append(("Examples", ", ".join(examples)))
    if data_root is not None:
        used = (result or {}).get("template_id") or template
        rows.append(("Ingested", f"{data_root.resolve()}" + (f" ({used})" if used else "")))
    rows += [
        ("Data", f"{paths.home} (logs in {paths.logs})"),
        ("Add data", "depictio local up --data-root <dir> [--template <template>]"),
        ("CLI on this server", f"export DEPICTIO_CLI_CONFIG_PATH={paths.cli_config}"),
        ("Stop", "depictio local down"),
    ]
    _print_rows(rows)


def _open(state: State, page: str) -> None:
    if _has_display():
        webbrowser.open(f"{state.url}{page}")
        return
    api_port = state.ports["api"]
    _info(
        f"No browser here: from your machine, run ssh -L {api_port}:127.0.0.1:{api_port} "
        f"<host>, then open {state.url}{page}"
    )


@app.command()
def up(
    template: Annotated[
        str | None,
        typer.Option(
            "--template",
            help="Template to ingest --data-root with, e.g. nf-core/rnaseq/latest or the path "
            "to a template.yaml. Default: picked from the run's pipeline_info/",
        ),
    ] = None,
    data_root: Annotated[
        Path | None,
        typer.Option("--data-root", help="Pipeline results directory to ingest"),
    ] = None,
    compose: Annotated[
        bool,
        typer.Option(
            "--compose",
            help="Compose the dashboard from the catalog even when a bundled template fits "
            "(it does by itself when none does)",
        ),
    ] = False,
    include_unknown: Annotated[
        bool,
        typer.Option(
            "--include-unknown",
            help="When composing: also ingest the tabular files the catalog does not recognise",
        ),
    ] = False,
    include: Annotated[
        list[str] | None,
        typer.Option(
            "--include",
            help="When composing: ingest the unrecognised files matching this glob; repeatable",
        ),
    ] = None,
    refresh: Annotated[
        bool,
        typer.Option(
            "--refresh",
            help="Ingest --data-root again when it already was, and reset its dashboards "
            "to the template's (edits made since are lost)",
        ),
    ] = False,
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
        bool,
        typer.Option(
            "--open/--no-open",
            help="Open the ingested dashboard (else the dashboards page) in a browser",
        ),
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
    """Start MongoDB, Redis, SeaweedFS, the API and the worker locally, then ingest --data-root."""
    composing = compose or include_unknown or bool(include)
    seed = _check_up_flags(template, data_root, examples, refresh, composing)
    paths = Paths(local_home())
    paths.ensure_dirs()
    state = _start_or_reuse(paths, port, seed, examples is not None, screenshots)
    present = _wait_for_examples(paths, state, seed.split(",") if examples else [])
    result = None
    if data_root is not None:
        result = _ingest(
            paths,
            template,
            data_root,
            variables,
            project_name,
            refresh,
            compose=compose,
            include_unknown=include_unknown,
            include=include,
        )
    _print_summary(paths, state, present, template, data_root, result)
    if open_browser:
        _open(state, _landing(result))


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
