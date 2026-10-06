import contextlib
import logging
import os
import shlex
import sys
import time
import webbrowser
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.markup import escape
from rich.text import Text

from depictio.cli.cli.local_compose import export_compose
from depictio.cli.cli.local_stack import (
    LocalStackError,
    Paths,
    State,
    api_healthy,
    check_platform_supported,
    check_server_installed,
    examples_status,
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


# Messages are escaped: they quote install commands such as `depictio[local]` and
# paths, which Rich would otherwise read as style tags and drop.
def _info(msg: str) -> None:
    rich_print_checked_statement(escape(msg), "info")


def _warn(msg: str) -> None:
    rich_print_checked_statement(escape(msg), "warning")


def _fail(msg: str) -> NoReturn:
    rich_print_checked_statement(escape(msg), "error")
    raise typer.Exit(code=1)


def _print_rows(rows: list[tuple[str, str]], width: int = 0, value_style: str = "") -> None:
    """Label/value rows with the values aligned, past ``width`` or the longest label."""
    width = max(width, *(len(label) for label, _ in rows))
    for label, value in rows:
        # Text with soft_wrap rather than a Table: long paths and commands stay on one
        # line, so they copy-paste intact.
        row = Text.assemble("  ", (label.ljust(width), "dim"), "  ", (value, value_style))
        console.print(row, soft_wrap=True)


def _can_animate() -> bool:
    """Whether a spinner may draw: stdout is an interactive terminal, and no -v/-vv
    logs are on, which go to stderr through a plain logging handler and would tear
    through the live display."""
    return (
        sys.stdout.isatty()
        and not console.is_dumb_terminal
        and logging.getLogger("depictio-cli").getEffectiveLevel() >= logging.ERROR
    )


class _Elapsed:
    """``message`` and the seconds since it started, redrawn with each spinner frame."""

    def __init__(self, message: str):
        self.message = message
        self.start = time.monotonic()

    def __rich__(self) -> Text:
        return Text.assemble(self.message, (f"  {time.monotonic() - self.start:.0f}s", "dim"))


@contextlib.contextmanager
def _spinner(message: str, *, announce: bool = False) -> Iterator[None]:
    """A spinner with the elapsed time while `up` waits, where _can_animate allows.

    Lines printed meanwhile appear above it. Where it cannot draw, ``announce``
    prints ``message`` as an info line instead.
    """
    if not _can_animate():
        if announce:
            _info(message)
        yield
        return
    with console.status(_Elapsed(message)):
        yield


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


def _moved_to_ingest(
    template: str | None,
    data_root: str | None,
    project_name: str | None,
    variables: list[str] | None,
) -> NoReturn:
    """Exit 2 with the `depictio ingest` command that does what these `up` flags did.

    1.12.0b1 ingested with `up --template --data-root`, so the flags are still
    parsed, to point there rather than fail as unknown options.
    """
    # Placeholders where the old flags were incomplete; given values quoted as typed.
    args = [
        ("--template", shlex.quote(template) if template is not None else "<template>"),
        ("--data-root", shlex.quote(data_root) if data_root is not None else "<dir>"),
    ]
    if project_name is not None:
        args.append(("--project-name", shlex.quote(project_name)))
    args += [("--var", shlex.quote(var)) for var in variables or []]
    command = " ".join(["depictio ingest --server local", *(f"{f} {v}" for f, v in args)])
    rich_print_checked_statement(
        "depictio local up starts the server only: add data with depictio ingest", "error"
    )
    _print_rows(
        [("Start the server", "depictio local up"), ("Add the data", command)], value_style="cyan"
    )
    raise typer.Exit(code=2)


def _check_examples(examples: str | None) -> str:
    """--examples as the server seeds it, rejected before anything starts."""
    try:
        return parse_examples(examples)
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
        if state is not None and all(running_status(paths, state).values()):
            _info(f"Depictio is already running at {state.url}")
            # Applied at startup only.
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
        # No spinner with --screenshots: the Chromium installer draws its own progress.
        spinner = contextlib.nullcontext() if screenshots else _spinner("Starting the local server")
        with spinner:
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
            with _spinner("Loading the examples", announce=True):
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


def _print_summary(paths: Paths, state: State, examples: list[str]) -> None:
    """Where things are, then what to run next, as two blocks of aligned rows."""
    rich_print_checked_statement(f"Depictio is ready: {state.url}/dashboards", "success")
    where = [("Examples", ", ".join(examples))] if examples else []
    where += [("Data", str(paths.home)), ("Logs", str(paths.logs))]
    # --server local reads the CLI configuration this home holds, admin token included.
    next_steps = [
        ("Add data", "depictio ingest --server local --template <template> --data-root <dir>"),
        ("Use the CLI", "depictio <command> --server local"),
        ("Stop", "depictio local down"),
    ]
    width = max(len(label) for label, _ in where + next_steps)
    console.print()
    _print_rows(where, width)
    console.print()
    console.print("  Next steps", style="bold")
    _print_rows(next_steps, width, value_style="cyan")


def _open_dashboards(state: State, announce: bool = False) -> None:
    """Open the dashboards page in a browser, or say how to reach it without a display."""
    url = f"{state.url}/dashboards"
    if _has_display():
        if announce:
            _info(f"Opening {url}")
        webbrowser.open(url)
        return
    api_port = state.ports["api"]
    _info(
        f"No browser here: from your machine, run ssh -L {api_port}:127.0.0.1:{api_port} "
        f"<host>, then open {url}"
    )


@app.command()
def up(
    examples: Annotated[
        str | None,
        typer.Option(
            "--examples",
            help="Example projects to seed on the first run: iris,penguins (the default), "
            "iris, penguins or none",
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
    # Moved to `depictio ingest --server local`: parsed only to say so.
    template: Annotated[str | None, typer.Option("--template", hidden=True)] = None,
    data_root: Annotated[str | None, typer.Option("--data-root", hidden=True)] = None,
    project_name: Annotated[str | None, typer.Option("--project-name", hidden=True)] = None,
    variables: Annotated[list[str] | None, typer.Option("--var", hidden=True)] = None,
):
    """Start MongoDB, Redis, SeaweedFS, the API and the worker on this machine.

    Then add data with: depictio ingest --server local --template <template> --data-root <dir>
    """
    if template is not None or data_root is not None or project_name is not None or variables:
        _moved_to_ingest(template, data_root, project_name, variables)
    seed = _check_examples(examples)
    paths = Paths(local_home())
    paths.ensure_dirs()
    state = _start_or_reuse(paths, port, seed, examples is not None, screenshots)
    present = _wait_for_examples(paths, state, seed.split(",") if examples else [])
    _print_summary(paths, state, present)
    if open_browser:
        _open_dashboards(state)


@app.command("open")
def open_cmd():
    """Open the dashboards page of the running local server in a browser."""
    paths = Paths(local_home())
    state = State.load(paths)
    if state is None or not all(running_status(paths, state).values()):
        _fail("Depictio local is not running. Start it with: depictio local up")
    _open_dashboards(state, announce=True)


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
        _info("Depictio local is not running. Start it with: depictio local up")
        return
    processes = running_status(paths, state)
    # One line per process, its name, state and port in aligned columns.
    width = max(len(name) for name in processes)
    for name, alive in processes.items():
        port = f"port {state.ports[name]}" if name in state.ports else ""
        rich_print_checked_statement(
            f"{name.ljust(width)}  {'running' if alive else 'stopped'}  {port}".rstrip(),
            "success" if alive else "error",
        )
    healthy = api_healthy(state.ports["api"])
    rich_print_checked_statement(
        f"API at {state.url}: {'reachable' if healthy else 'not reachable'}",
        "success" if healthy else "error",
    )
    _print_rows(
        [("Dashboards", f"{state.url}/dashboards"), ("Logs", str(Path(state.home) / "logs"))]
    )


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


@app.command("export")
def export_cmd(
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
        ],
        value_style="cyan",
    )


# The 1.12.0b1 name, which CI still calls.
app.command("export-compose", hidden=True)(export_cmd)
