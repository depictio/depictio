"""`depictio watch`: `depictio ingest` on a loop, run again whenever the data changes.

Each cycle is one ``run_ingest``, with the project selected exactly as `ingest`
selects it. The watcher (``utils/watch.py``) only decides when a cycle runs.
"""

import os
import socket
from dataclasses import replace
from typing import Annotated

import typer

from depictio.cli.cli.commands.run import (
    WRITE_MODES,
    IngestOptions,
    _cli_version,
    ingestion_record,
    run_ingest,
)
from depictio.cli.cli.utils.api_calls import (
    api_agent_claim_trigger,
    api_agent_deregister,
    api_agent_heartbeat,
)
from depictio.cli.cli.utils.common import get_http_client, load_depictio_config
from depictio.cli.cli.utils.rich_utils import (
    rich_print_checked_statement,
    rich_print_command_usage,
    rich_print_section_separator,
)
from depictio.cli.cli.utils.server_target import (
    LegacyConfigPathOption,
    ServerOption,
    resolve_server,
)
from depictio.cli.cli.utils.watch import (
    ProjectLock,
    ProjectLockError,
    ProjectWatcher,
    WatchConfig,
)
from depictio.cli.cli_logging import logger

WATCH_MODES = ("incremental", "full")
WATCH_BACKENDS = ("auto", "native", "polling", "both")

# Steps no cycle runs. The first cycle reaches the server and S3 as soon as it
# validates the project, which is check enough. Dashboards are `ingest`'s to
# import, run once before watching: a refresh would only re-import those the
# project lacks, which the viewer may have removed on purpose.
_SKIPPED_EVERY_CYCLE = frozenset({"server-check", "s3-check", "dashboards"})


class _Cycles:
    """The watcher's ``run_cycle``: one ``run_ingest`` per call, and what each
    cycle leaves for the next."""

    def __init__(self, base: IngestOptions) -> None:
        self.base = base
        # Set once the loop starts. The first cycle runs before it, to learn the
        # locations to watch.
        self.watcher: ProjectWatcher | None = None
        self.project_config = None
        self.last_run_id: str | None = None
        # Exit code of the last cycle: 0, or the code its failed step exited with.
        self.exit_code = 0
        # Whether the last cycle succeeded, which lets the next leave alone the
        # collections the scan saw no change in.
        self.last_ok = False
        # Whether a cycle has synced the project; the later ones only rescan.
        self.synced = False

    def __call__(self, cycle_mode: str, paths: set[str]) -> bool:
        if paths:
            logger.info(f"Ingesting after {len(paths)} settled change(s).")
        incremental = cycle_mode == "incremental"
        watcher = self.watcher
        options = replace(
            self.base,
            skip=self.base.skip | ({"sync"} if self.synced else set()),
            # A full cycle re-uploads every file, an incremental one only those
            # whose size or modification time moved.
            sync_files=not incremental,
            sync_changed=incremental,
            # Leave untouched collections alone, but only on an incremental cycle
            # whose predecessor succeeded. After any failure, and on every full
            # cycle, everything is rebuilt: that is what makes a table that fell
            # behind (a write that died between the object store and the server,
            # say) catch up on its own instead of staying skipped.
            skip_unchanged=incremental and self.last_ok,
            # The same rule for writing only the changed runs. A failed cycle has
            # already registered the runs it changed, so the next scan finds them
            # unchanged: a write scoped to the runs that moved since would leave
            # them out of the table for good.
            incremental_write=self.base.incremental_write and incremental and self.last_ok,
            # The watcher says why it fired: a settled batch, a poll, or someone
            # pressing "Run now" on its agent card.
            trigger=watcher.trigger_kind if watcher else "watch",
            trigger_reason=(watcher.trigger_reason if watcher else self.base.trigger_reason),
            on_run_opened=self._note_run,
        )
        record = None
        ok = False
        try:
            # Before the loop, SIGTERM closes the record as it does for `ingest`;
            # in it, the watcher's own handler lets the cycle finish instead.
            with ingestion_record(trap_sigterm=watcher is None) as record:
                ok = run_ingest(options, record).ok
            self.exit_code = 0 if ok else 1
        except ProjectLockError:
            # Not a failed cycle: another process owns the project, and the
            # watch command decides what that means.
            raise
        except typer.Exit as exc:
            # A step that failed, and has said why.
            self.exit_code = exc.exit_code or 1
        except Exception as exc:  # noqa: BLE001 - a watcher must outlive one bad cycle
            logger.error(f"Ingestion cycle failed: {exc}")
            self.exit_code = 1
        finally:
            # A refresh adds the runs the server knows to the configuration, so
            # it is read from the record after the cycle, failed or not.
            if record is not None and record.project_config is not None:
                self.project_config = record.project_config
        # A dry run wrote nothing, so it cannot vouch for the next cycle skipping.
        self.last_ok = ok and not self.base.scan_dry_run
        if ok and "sync" not in options.skip:
            self.synced = True
        return ok

    def _note_run(self, run_id: str | None) -> None:
        self.last_run_id = run_id or self.last_run_id
        if self.watcher is not None:
            self.watcher.note_run(run_id)


def _project_data_roots(project_config) -> list[str]:
    """Existing, distinct data locations across every workflow of a project."""
    roots: list[str] = []
    for workflow in project_config.workflows:
        for location in workflow.data_location.locations or []:
            if not os.path.isdir(location):
                logger.warning(f"Skipping non-existent data location: {location}")
            elif location not in roots:
                roots.append(location)
    return roots


def watch(
    data_dir: Annotated[
        str | None,
        typer.Argument(
            metavar="DATA_DIR",
            help="Directory of the pipeline results to watch. Without --template or "
            "--project-config-path, the template is detected from it, as `ingest` does.",
            show_default=False,
        ),
    ] = None,
    server: ServerOption = None,
    CLI_config_path: LegacyConfigPathOption = None,
    template: Annotated[
        str | None,
        typer.Option(
            "--template",
            help="Template to build the project from, as for `ingest`. Default: detected "
            "from DATA_DIR. Not with --project-config-path.",
        ),
    ] = None,
    project_config_path: Annotated[
        str,
        typer.Option(
            "--project-config-path",
            help="Project YAML, for a pipeline Depictio ships no template for. Not with "
            "--template.",
        ),
    ] = "",
    project: Annotated[
        str | None,
        typer.Option(
            "--project",
            help="Project name. Replaces the name the template gives, or the `name` in "
            "the --project-config-path file.",
        ),
    ] = None,
    var: Annotated[
        list[str],
        typer.Option("--var", help="Extra template variable as KEY=VALUE. Repeatable."),
    ] = [],
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="incremental: re-upload only the files that changed. full: re-upload "
            "and rewrite everything on every cycle.",
        ),
    ] = "incremental",
    backend: Annotated[
        str,
        typer.Option(
            "--backend",
            help="auto (detect), native (filesystem events only), polling (periodic "
            "re-walk), or both. auto selects polling on network filesystems, where "
            "native events do not see writes made from another host.",
        ),
    ] = "auto",
    debounce: Annotated[
        float,
        typer.Option("--debounce", help="Seconds of quiet before a cycle is triggered"),
    ] = 30.0,
    settle: Annotated[
        float,
        typer.Option(
            "--settle",
            help="Seconds a file must hold the same size and mtime before it is ingested",
        ),
    ] = 5.0,
    interval: Annotated[
        float,
        typer.Option(
            "--interval",
            help="Seconds between polling walks (also the backstop for lost events)",
        ),
    ] = 300.0,
    max_delay: Annotated[
        float,
        typer.Option(
            "--max-delay",
            help="Ceiling on debouncing, so a tree written continuously still gets ingested",
        ),
    ] = 300.0,
    full_every: Annotated[
        int | None,
        typer.Option("--full-every", min=1, help="Run a full cycle every N incremental ones"),
    ] = None,
    once: Annotated[
        bool, typer.Option("--once", help="Run a single cycle and exit with its status")
    ] = False,
    max_runs: Annotated[
        int | None,
        typer.Option("--max-runs", min=1, help="Stop after this many cycles, the first included"),
    ] = None,
    write_mode: Annotated[
        str,
        typer.Option(
            "--write-mode",
            help="How each cycle writes a table, as for `ingest`: overwrite or replace-runs",
        ),
    ] = "overwrite",
    incremental_write: Annotated[
        bool,
        typer.Option(
            "--incremental-write",
            help="With --write-mode replace-runs, rewrite only the runs that changed "
            "instead of rebuilding the whole table.",
        ),
    ] = False,
    drop_missing_runs: Annotated[
        bool,
        typer.Option(
            "--drop-missing-runs",
            help="Remove the runs of a location added with `ingest --attach-run` that is "
            "not on this host. Without it, such a project stops the first cycle.",
        ),
    ] = False,
    concurrency: Annotated[
        int,
        typer.Option("--concurrency", min=1, help="Parallel HTTP requests during each cycle"),
    ] = 4,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Report each cycle's changes without writing to the server",
        ),
    ] = False,
):
    """
    Ingest pipeline results, then again whenever they change: `ingest` on a loop.

    The first cycle runs at once and refreshes the project as `ingest
    --update-config` does; the later ones rescan and rewrite what moved. Runs until
    interrupted: SIGINT or SIGTERM finish the cycle in progress and then exit
    cleanly, so it is safe to run under systemd or as a container command.

    One watcher or ingestion per project at a time: the first cycle takes the
    project's lock before it writes anything, and the watch holds it until it
    exits. A second one stops at once and names the lock file.

    Example, rewriting only the runs that changed:
      depictio watch results/ --write-mode replace-runs --incremental-write
    """
    for value, allowed, option in (
        (mode, WATCH_MODES, "--mode"),
        (backend, WATCH_BACKENDS, "--backend"),
        (write_mode, WRITE_MODES, "--write-mode"),
    ):
        if value not in allowed:
            raise typer.BadParameter(
                f"'{value}' is not one of {', '.join(allowed)}", param_hint=option
            )

    rich_print_command_usage("watch")
    CLI_config_path = resolve_server(server, CLI_config_path)
    # Size the shared connection pool before the first request: it is created
    # lazily and honours this only on the first call.
    get_http_client(concurrency=concurrency)

    if mode == "incremental" and write_mode == "overwrite":
        # Worth saying plainly: with the default write mode, a collection whose
        # files moved has its whole table rewritten. Collections that did not move
        # are left alone regardless.
        rich_print_checked_statement(
            "Incremental watching with --write-mode overwrite rewrites a changed "
            "collection's entire table. Use --write-mode replace-runs --incremental-write "
            "to rewrite only the runs that changed.",
            "warning",
        )
    if incremental_write and write_mode != "replace-runs":
        rich_print_checked_statement(
            "--incremental-write only applies to --write-mode replace-runs; ignoring it.",
            "warning",
        )
        incremental_write = False

    # Held from the first cycle to the end of the watch. The first cycle takes it
    # once it has validated the project, before its first write; the later ones
    # find it held. A dry run writes nothing and never takes it.
    lock = ProjectLock()
    cycles = _Cycles(
        IngestOptions(
            data_root=data_dir,
            CLI_config_path=CLI_config_path,
            template=template,
            project_config_path=project_config_path,
            project_name=project,
            var=tuple(var),
            # Every cycle refreshes the project in place: its tables exist from
            # the first cycle on, and only a refresh may rewrite them.
            update_config=True,
            drop_missing_runs=drop_missing_runs,
            # A dry run never syncs the project either: that writes to the server.
            skip=_SKIPPED_EVERY_CYCLE | ({"sync"} if dry_run else set()),
            state_cache=True,
            concurrency=concurrency,
            write_mode=write_mode,
            incremental_write=incremental_write,
            triggered_by="watch",
            command="watch",
            trigger="watch",
            trigger_reason="single --once pass" if once else "watcher started",
            scan_dry_run=dry_run,
            project_lock=lock,
        )
    )

    # One lock scope over the first cycle and the loop: released when the watch
    # ends, however it ends.
    with lock:
        # The first cycle, at once: it brings the project up to date with whatever
        # changed while nothing watched, and validates the configuration that says
        # which locations to watch.
        try:
            first_ok = cycles(mode, set())
        except ProjectLockError as exc:
            # Already said by the cycle, which names the lock file and its holder.
            raise typer.Exit(code=exc.exit_code) from exc
        project_config = cycles.project_config
        if project_config is None:
            rich_print_checked_statement(
                "The first cycle stopped before the project configuration was validated: "
                "nothing to watch.",
                "error",
            )
            raise typer.Exit(code=cycles.exit_code or 1)
        if once or max_runs == 1:
            raise typer.Exit(code=0 if first_ok else cycles.exit_code or 1)

        # After that cycle's refresh, which adds the runs the server knows.
        roots = _project_data_roots(project_config)
        if not roots:
            rich_print_checked_statement(
                "No existing data locations to watch in this project.", "error"
            )
            raise typer.Exit(code=1)

        config = WatchConfig(
            mode=mode,  # type: ignore[arg-type]
            backend=backend,  # type: ignore[arg-type]
            debounce_seconds=debounce,
            settle_seconds=settle,
            poll_interval_seconds=interval,
            max_delay_seconds=max_delay,
            full_every=full_every,
            # The first cycle already ran.
            max_runs=max_runs - 1 if max_runs is not None else None,
        )
        CLI_config = load_depictio_config(yaml_config_path=CLI_config_path, quiet=True)
        watcher = ProjectWatcher(roots=roots, config=config, run_cycle=cycles)
        cycles.watcher = watcher
        watcher.note_run(cycles.last_run_id)
        watcher.install_signal_handlers()

        # Register with the server so the watcher is visible in the admin UI, and
        # keep reporting as its state changes. Entirely best-effort: a server that
        # does not support agents (or is simply down) must not stop the watching.
        agent_id = f"{socket.gethostname()}:{os.getpid()}:{project_config.id}"
        agents_supported = True
        commands_supported = True

        def report_status(status: str, extra: dict) -> None:
            nonlocal agents_supported
            if not agents_supported:
                return
            payload = {
                "agent_id": agent_id,
                "kind": "watcher",
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "cli_version": _cli_version(),
                "project_id": str(project_config.id),
                "project_name": project_config.name,
                "mode": mode,
                "backend": watcher.backend,
                "watching": roots,
                "status": status,
                # The first cycle ran before the watcher counts its own.
                "runs_total": int(extra.get("runs_total", 0)) + 1,
            }
            # Both rendered on the agent card. Sent only when set, so a watcher that
            # has not run a cycle yet leaves them null rather than clearing them.
            if extra.get("last_run_id"):
                payload["last_run_id"] = extra["last_run_id"]
            if extra.get("last_trigger_at"):
                payload["last_trigger_at"] = extra["last_trigger_at"].isoformat()
            if not api_agent_heartbeat(CLI_config, payload):
                logger.info("Server has no CLI-agent registry; skipping further heartbeats.")
                agents_supported = False

        def poll_command() -> bool:
            """Whether the agent card's "Run now" has been pressed since the last poll."""
            nonlocal commands_supported
            if not agents_supported or not commands_supported:
                return False
            requested = api_agent_claim_trigger(CLI_config, agent_id)
            if requested is None:
                logger.info("Server does not support UI-triggered runs; not polling for them.")
                commands_supported = False
                return False
            return requested

        watcher.on_status = report_status
        watcher.on_poll_command = poll_command
        report_status("idle", {})

        rich_print_section_separator(
            f"Watching {len(roots)} location(s), {watcher.backend} backend"
        )
        for root in roots:
            rich_print_checked_statement(f"  {root}", "info")

        try:
            exit_code = watcher.run()
        except KeyboardInterrupt:
            rich_print_checked_statement("Interrupted.", "warning")
            exit_code = 130
        finally:
            if agents_supported:
                api_agent_deregister(CLI_config, agent_id)

        raise typer.Exit(code=exit_code)


def register_watch_command(app: typer.Typer) -> None:
    """Register ``watch`` at the top level, next to ``ingest``, which it repeats."""
    app.command(name="watch")(watch)
