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
    EXAMPLES,
    HOME_MARKER,
    Interrupted,
    LocalStackError,
    Paths,
    State,
    StateUnreadable,
    api_healthy,
    api_responds,
    build_viewer,
    check_platform_supported,
    check_server_installed,
    claim_home,
    examples_status,
    is_local_home,
    load_secrets,
    local_home,
    local_home_env_is_blank,
    lock_for_startup,
    mark_examples_loaded,
    parse_examples,
    rebuild_cli_config,
    reset,
    running_status,
    start_stack,
    stop_all,
    sync_cli_config,
    viewer_built,
    viewer_outdated,
    viewer_workspace,
    wait_for_examples,
)
from depictio.cli.cli.utils.renamed import note_if_called_as
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


def _join(names: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    return f"{', '.join(names[:-1])} and {names[-1]}" if len(names) > 1 else "".join(names)


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


def _paths() -> Paths:
    """The local home. A set but empty DEPICTIO_LOCAL_HOME is refused rather than
    taken for the current folder, which `wipe` would then empty."""
    if local_home_env_is_blank():
        _fail(
            "DEPICTIO_LOCAL_HOME is set but empty: unset it to use ~/.depictio/local, "
            "or point it at a folder"
        )
    return Paths(local_home())


def _load_state(paths: Paths) -> State | None:
    try:
        return State.load(paths)
    except LocalStackError as exc:
        _fail(str(exc))


def _up_flags(
    examples: str | None,
    template: str | None,
    port: int | None,
    screenshots: bool | None,
    open_browser: bool,
) -> list[str]:
    """The `up` flags given, minus the data ones. In 1.12.0b1, --template without
    --examples seeded no example."""
    flags: list[str] = []
    if examples is not None:
        flags += ["--examples", examples]
    elif template is not None:
        flags += ["--examples", "none"]
    if port is not None:
        flags += ["--port", str(port)]
    if screenshots is not None:
        flags.append("--screenshots" if screenshots else "--no-screenshots")
    if not open_browser:
        flags.append("--no-open")
    return flags


def _moved_to_ingest(
    template: str | None,
    data_root: str | None,
    project_name: str | None,
    variables: list[str] | None,
    up_flags: list[str],
) -> NoReturn:
    """Exit 2 with the `depictio local up` and `depictio ingest` commands that do what
    these `up` flags did.

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
        [
            ("Start the server", shlex.join(["depictio", "local", "up", *up_flags])),
            ("Add the data", command),
        ],
        value_style="cyan",
    )
    raise typer.Exit(code=2)


def _check_examples(value: str | None) -> str | None:
    """--examples, rejected before anything starts, as a usage error (exit 2)."""
    if value is not None:
        try:
            parse_examples(value)
        except LocalStackError as exc:
            raise typer.BadParameter(
                f"use iris, penguins, iris,penguins or none, not {value!r}"
            ) from exc
    return value


def _prepare_home(paths: Paths) -> None:
    """Make the local home ready for `up`: claimed, with its data directories."""
    try:
        claim_home(paths)
        paths.ensure_dirs()
    except LocalStackError as exc:
        _fail(str(exc))
    except OSError as exc:
        _fail(
            f"Cannot set up the local home {paths.home} ({exc.strerror or exc}): point "
            "DEPICTIO_LOCAL_HOME at a folder you can write to"
        )


def _warn_ignored_flags(state: State, port: int | None, screenshots: bool | None) -> None:
    """Name the flags that differ from what the running server was started with:
    they apply at startup only. --examples is covered by _wait_for_examples."""
    ignored = []
    if port is not None and port != state.api_port:
        ignored.append("--port")
    if screenshots is not None and screenshots != state.screenshots:
        ignored.append("--screenshots" if screenshots else "--no-screenshots")
    for flag in ignored:
        _warn(f"{flag} is ignored: the server is already running (depictio local down first)")


def _restore_cli_config(paths: Paths, state: State) -> None:
    """Write a deleted CLI configuration again: the API writes it on the first run only."""
    if paths.cli_config.exists():
        return
    try:
        rebuild_cli_config(paths, state.api_port, load_secrets(paths, create=False), warn=_warn)
        sync_cli_config(paths, state.ports)
    except LocalStackError as exc:
        _warn(str(exc))
        return
    _info(f"Wrote {paths.cli_config} again")


def _prepare_viewer(paths: Paths, running: bool) -> None:
    """Build the viewer bundle when a source checkout's is missing or older than its
    sources; a wheel carries it built.

    The API loads the bundle when it starts, so for a server already ``running`` this
    only says how to pick up a newer one. A failed build does not stop the start.
    """
    workspace = viewer_workspace()
    if workspace is None:
        if not viewer_built():
            _warn(
                "This installation has no viewer bundle, so dashboards will not render: "
                "install depictio[local] from PyPI, whose wheel carries it"
            )
        return
    reason = viewer_outdated(workspace)
    if reason is None:
        return
    if running:
        _warn(
            f"The viewer bundle is out of date ({reason}): depictio local down, then "
            "depictio local up, rebuilds it"
        )
        return
    log_path = paths.logs / "viewer-build.log"
    try:
        with _spinner(f"Building the viewer bundle ({reason})", announce=True):
            build_viewer(workspace, log_path)
    except LocalStackError as exc:
        left = (
            "with the previous bundle"
            if viewer_built()
            else "without a viewer, so dashboards will not render"
        )
        _warn(
            f"{exc}. The server starts {left}; once that is fixed, depictio local down, "
            "then depictio local up, builds it"
        )
        return
    _info(f"Built the viewer bundle (output in {log_path})")


def _start_or_reuse(paths: Paths, port: int | None, seed: str, screenshots: bool | None) -> State:
    """The server already running, else a new one; exits 1 on failure, and 130 on
    Ctrl-C (128 + the signal for SIGTERM and SIGHUP).

    A failed check never takes down a server that was already running: only
    start_stack stops services (an earlier run's leftovers, then on error what
    it started).
    """
    starting = False
    try:
        check_platform_supported()
        check_server_installed()
        try:
            state = State.load(paths)
        except StateUnreadable:
            # start_stack stops what still runs from this home without it, and says so.
            state = None
        running = running_status(paths, state) if state is not None else {}
        if state is not None and all(running.values()):
            if not api_responds(state.api_port):
                _fail(
                    f"Depictio is running but its API at {state.url} is not responding (see "
                    f"{paths.logs / 'api.log'}). Restart it: depictio local down, then "
                    "depictio local up"
                )
            _info(f"Depictio is already running at {state.url}")
            _warn_ignored_flags(state, port, screenshots)
            _prepare_viewer(paths, running=True)
            _restore_cli_config(paths, state)
            return state
        stopped = [name for name, alive in running.items() if not alive]
        if any(running.values()):
            verb = "is" if len(stopped) == 1 else "are"
            _info(f"{_join(stopped)} {verb} not running: restarting the server")
        _prepare_viewer(paths, running=False)
        starting = True
        # No spinner with --screenshots: the Chromium installer draws its own progress.
        spinner = contextlib.nullcontext() if screenshots else _spinner("Starting the local server")
        with spinner:
            return start_stack(paths, port, seed, bool(screenshots), log=_info, warn=_warn)
    except LocalStackError as exc:
        _fail(str(exc))
    except KeyboardInterrupt as exc:
        # After SIGHUP the terminal may be gone: the exit code still tells.
        with contextlib.suppress(OSError):
            _warn(
                "Interrupted: services started by this run are stopped"
                if starting
                else "Interrupted"
            )
        raise typer.Exit(code=128 + exc.signum if isinstance(exc, Interrupted) else 130)


def _wait_for_examples(paths: Paths, state: State, asked: list[str]) -> list[str]:
    """Hold `ready` until the examples are loaded, so their dashboards show data.

    The API loads them in the background, and on a first run stopping it in the
    meantime would leave them half loaded. ``asked`` are the examples --examples
    named. Returns the examples this home has ready, asked for or not.
    """
    try:
        status = examples_status(paths, state)
        if any(s in ("loading", "unreachable") for s in status.values()):
            with _spinner("Loading the examples", announce=True):
                status = wait_for_examples(paths, state)
        if state.first_run and status and all(s == "ready" for s in status.values()):
            mark_examples_loaded(paths, state)
        # The others too: a home keeps the examples of its first run, whatever this
        # run asked for.
        status.update(examples_status(paths, state, [n for n in EXAMPLES if n not in status]))
    except KeyboardInterrupt:
        _warn(
            "Interrupted: the server keeps running and finishes loading the examples "
            "(depictio local down to stop)"
        )
        raise typer.Exit(code=130)

    def named(state_name: str) -> list[str]:
        return [name for name, s in status.items() if s == state_name]

    if unseeded := [name for name in asked if status.get(name) == "absent"]:
        _warn(
            f"This local home has no {' or '.join(unseeded)} example: examples are added "
            "on its first run only"
        )
    if unreachable := named("unreachable"):
        _warn(
            f"The API at {state.url} did not answer while checking the {_join(unreachable)} "
            f"example{'s' if len(unreachable) > 1 else ''} (see {paths.logs / 'api.log'})"
        )
    if missing := named("loading"):
        plural = len(missing) > 1
        _warn(
            f"The {' and '.join(missing)} example{'s' if plural else ''} did not finish "
            "loading, so the dashboards show no data. depictio local wipe, then depictio "
            f"local up, reloads {'them' if plural else 'it'} (details in {paths.logs / 'api.log'})"
        )
    return [name for name in EXAMPLES if status.get(name) == "ready"]


def _print_summary(paths: Paths, state: State, examples: list[str]) -> None:
    """Where things are, then what to run next, as two blocks of aligned rows."""
    rich_print_checked_statement(f"Depictio is ready: {escape(state.url)}/dashboards", "success")
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
    api_port = state.api_port
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
            callback=_check_examples,
        ),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(
            "--port",
            min=1,
            max=65535,
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

    Run from a source checkout, it first builds the viewer when its sources changed
    since the last build (this needs pnpm).

    Then add data with: depictio ingest --server local --template <template> --data-root <dir>
    """
    if template is not None or data_root is not None or project_name is not None or variables:
        flags = _up_flags(examples, template, port, screenshots, open_browser)
        _moved_to_ingest(template, data_root, project_name, variables, flags)
    seed = parse_examples(examples)
    paths = _paths()
    _prepare_home(paths)
    try:
        lock = lock_for_startup(paths)
    except LocalStackError as exc:
        _fail(str(exc))
    except OSError as exc:
        _fail(f"Cannot lock the local home {paths.home} ({exc.strerror or exc})")
    with lock:
        state = _start_or_reuse(paths, port, seed, screenshots)
    present = _wait_for_examples(paths, state, seed.split(",") if examples else [])
    _print_summary(paths, state, present)
    if open_browser:
        _open_dashboards(state)


@app.command("open")
def open_cmd():
    """Open the dashboards page of the running local server in a browser."""
    paths = _paths()
    state = _load_state(paths)
    running = running_status(paths, state) if state is not None else {}
    if state is None or not any(running.values()):
        _fail("Depictio local is not running. Start it with: depictio local up")
    stopped = [name for name, alive in running.items() if not alive]
    partly = f"Depictio local is partly running ({_join(stopped)} stopped): run depictio local up"
    if not api_healthy(state.api_port):
        _fail(
            partly
            if stopped
            else f"The Depictio API at {state.url} is not responding (see "
            f"{paths.logs / 'api.log'}): run depictio local down, then depictio local up"
        )
    if stopped:
        _warn(partly)
    _open_dashboards(state, announce=True)


@app.command()
def down():
    """Stop every process started by `depictio local up`."""
    paths = _paths()
    try:
        stopped = stop_all(paths, log=_info)
    except LocalStackError as exc:
        _fail(str(exc))
    if stopped:
        rich_print_checked_statement("Depictio local server stopped", "success")
    else:
        _info("Depictio local is not running.")


@app.command()
def status():
    """Show which local processes are running and whether the API answers.

    Exits with 0 when every process runs and the API answers, 1 otherwise.
    """
    paths = _paths()
    state = _load_state(paths)
    if state is None:
        _info("Depictio local is not running. Start it with: depictio local up")
        raise typer.Exit(code=1)
    processes = running_status(paths, state)
    # One line per process, its name, state and port in aligned columns.
    width = max(len(name) for name in processes)
    for name, alive in processes.items():
        port = f"port {state.ports[name]}" if name in state.ports else ""
        rich_print_checked_statement(
            f"{name.ljust(width)}  {'running' if alive else 'stopped'}  {port}".rstrip(),
            "success" if alive else "error",
        )
    healthy = api_healthy(state.api_port)
    rich_print_checked_statement(
        f"API at {escape(state.url)} {'is reachable' if healthy else 'is not reachable'}",
        "success" if healthy else "error",
    )
    _print_rows(
        [("Dashboards", f"{state.url}/dashboards"), ("Logs", str(Path(state.home) / "logs"))]
    )
    if not (healthy and all(processes.values())):
        raise typer.Exit(code=1)


@app.command()
def wipe(
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation")] = False,
):
    """Stop the server and delete all local data (downloaded binaries are kept)."""
    paths = _paths()
    if not paths.has_data():
        _info(f"Nothing to delete under {paths.home}")
        return
    if not is_local_home(paths.home):
        _fail(
            f"{paths.home} is not a Depictio local home (it has no {HOME_MARKER}): "
            "nothing deleted. Check DEPICTIO_LOCAL_HOME"
        )
    if not yes and not typer.confirm(f"Delete all Depictio data under {paths.home}?"):
        # Piped answers are not echoed: end the prompt's line.
        typer.echo("Cancelled.")
        return
    try:
        stop_all(paths, log=_info)
    except LocalStackError as exc:
        _fail(str(exc))
    reset(paths)
    rich_print_checked_statement("Local data deleted", "success")


@app.command("export")
def export_cmd(
    ctx: typer.Context,
    out: Annotated[
        Path,
        typer.Option("--out", help="Directory to create for the Docker Compose stack"),
    ] = Path("depictio-docker"),
):
    """Copy the local server's data into a directory Docker Compose runs as is.

    A running local server is stopped first, so the copy is consistent. Formerly
    `export-compose`.
    """
    note_if_called_as(ctx, "local export-compose", "local export")
    paths = _paths()
    out = out.resolve()
    try:
        export_compose(paths, out, log=_info)
    except LocalStackError as exc:
        _fail(str(exc))
    rich_print_checked_statement(f"Exported to {escape(str(out))}", "success")
    _print_rows(
        [
            ("Start it", f"cd {shlex.quote(str(out))} && docker compose up -d"),
            ("Then open", "http://localhost:5080"),
        ],
        value_style="cyan",
    )


# The 1.12.0b1 name, still accepted.
app.command("export-compose", hidden=True)(export_cmd)
