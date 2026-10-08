import os
import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape

from depictio.cli.cli.utils.api_calls import (
    api_create_magic_link,
    api_get_project_from_name,
    api_login,
    api_monitoring_ingestion_finish,
    api_monitoring_ingestion_start,
    api_monitoring_ingestion_step,
    api_provision_user,
    api_sync_project_config_to_server,
)
from depictio.cli.cli.utils.common import (
    cli_config_file,
    describe_api_target,
    generate_api_headers,
    get_http_client,
    load_depictio_config,
    report_login_failure,
    say_local_server_running,
)
from depictio.cli.cli.utils.config import validate_project_config_and_check_S3_storage
from depictio.cli.cli.utils.helpers import process_project_helper
from depictio.cli.cli.utils.image_upload import (
    image_collections_to_upload,
    upload_collection_images,
)
from depictio.cli.cli.utils.renamed import note_if_called_as, note_renamed, pick_renamed
from depictio.cli.cli.utils.rich_utils import (
    render_records_table,
    rich_print_checked_statement,
    rich_print_command_usage,
    rich_print_section_separator,
)
from depictio.cli.cli.utils.scan import flat_run_tag_clash, scan_project_files
from depictio.cli.cli.utils.scan_utils import (
    count_data_collection_matches,
    resolve_run_locations,
)
from depictio.cli.cli.utils.server_target import (
    LegacyConfigPathOption,
    ServerOption,
    resolve_server,
)
from depictio.cli.cli.utils.state import lock_path, settle_collections
from depictio.cli.cli.utils.step_reporter import StepReporter
from depictio.cli.cli.utils.watch import ProjectLock, ProjectLockError
from depictio.cli.cli_logging import logger
from depictio.models.s3_utils import S3_storage_checks
from depictio.models.utils import convert_model_to_dict


def _cli_version() -> str | None:
    """Installed CLI version, or ``None`` if it can't be determined.

    Best-effort metadata for the monitoring ledger — never raises.
    """
    try:
        from depictio.cli.cli.utils.telemetry import cli_version

        return cli_version()
    except Exception:
        return None


# CLI options whose *value* is a secret and must never reach the monitoring ledger.
_SENSITIVE_OPTS = {"--provisioning-key"}


def _redacted_command_line() -> str | None:
    """Best-effort reconstruction of the CLI invocation with secrets redacted.

    Renders as ``depictio-cli <args…>`` (argv[0] normalized to the entrypoint
    name) and masks the value of any sensitive option. Never raises.
    """
    try:
        import sys

        out = ["depictio-cli"]
        redact_next = False
        for arg in sys.argv[1:]:
            if redact_next:
                out.append("***")
                redact_next = False
                continue
            key = arg.split("=", 1)[0]
            if key in _SENSITIVE_OPTS:
                out.append(f"{key}=***" if "=" in arg else arg)
                redact_next = "=" not in arg
                continue
            out.append(arg)
        return " ".join(out)
    except Exception:
        return None


def _ingestion_data_collections(project_config, count_files: bool = False) -> list[dict]:
    """Per-DC summary (tag / type / format) + the local scan paths the CLI
    resolved, walked from the validated project config. Best-effort; never raises.

    ``count_files`` walks the run directories to fill ``file_count`` with what a
    scan would match. Off by default: the monitoring ledger is written after the
    scan, which already knows the real counts, so pre-walking for it would be
    both slower and less accurate. The dry run is the one caller with no scan to
    learn from, so it is the one that pays for the walk.
    """
    out: list[dict] = []
    try:
        for wf in getattr(project_config, "workflows", None) or []:
            dl = getattr(wf, "data_location", None)
            locations = [str(x) for x in (getattr(dl, "locations", None) or [])] if dl else []
            data_collections = getattr(wf, "data_collections", None) or []
            # Counted for the whole workflow at once: the counter walks each run
            # directory a single time and tests every pattern against that one
            # listing, as the scanner does.
            file_counts: list[int | None] = [None] * len(data_collections)
            if count_files:
                run_locations = resolve_run_locations(wf).locations
                file_counts = count_data_collection_matches(data_collections, run_locations)
            for dc, file_count in zip(data_collections, file_counts, strict=True):
                cfg = getattr(dc, "config", None)
                scan = getattr(cfg, "scan", None) if cfg else None
                mode = getattr(scan, "mode", None) if scan else None
                params = getattr(scan, "scan_parameters", None) if scan else None
                # Lowercased like the scanner, which compares `scan.mode.lower()`
                # while the model stores whatever spelling the config used.
                normalized_mode = mode.lower() if mode else None
                if normalized_mode == "single":
                    pattern = getattr(params, "filename", None)
                elif normalized_mode == "recursive":
                    rc = getattr(params, "regex_config", None)
                    pattern = getattr(rc, "pattern", None) if rc else None
                elif mode == "url":
                    pattern = getattr(params, "url", None)
                elif mode == "s3_prefix":
                    prefix = getattr(params, "prefix", None)
                    glob = getattr(params, "pattern", None)
                    pattern = f"{prefix}{glob}" if prefix and glob else prefix
                elif mode == "manifest":
                    pattern = getattr(params, "manifest_url", None)
                else:
                    pattern = None
                dcsp = getattr(cfg, "dc_specific_properties", None) if cfg else None
                out.append(
                    {
                        "tag": getattr(dc, "data_collection_tag", None) or "",
                        "type": getattr(cfg, "type", None) if cfg else None,
                        "format": getattr(dcsp, "format", None) if dcsp else None,
                        "scan_mode": mode,
                        "scan_pattern": pattern,
                        "locations": locations,
                        "file_count": file_count,
                    }
                )
    except Exception:
        return out
    return out


def _shorten_scan_pattern(pattern: str | None, locations: list[str]) -> str:
    """Render a scan pattern short enough to survive the preview table.

    A single-file scan's pattern is an absolute path, and in a terminal-width
    table it truncates to the data root every collection shares, hiding the one
    part that identifies the file. Relative to the configured location it stays
    unambiguous and readable.
    """
    if not pattern:
        return "-"
    for location in locations:
        try:
            return str(Path(pattern).relative_to(location))
        except ValueError:
            continue
    return pattern


def _print_dry_run_scan_preview(project_config) -> bool:
    """Show what a real scan would match, per data collection.

    Answering "is --data-root pointing at the right level?" is the whole reason
    to run ``--dry-run``, and it could not: every step was wrapped in
    ``if not dry_run`` and the run then printed "Data scanning completed" all
    the same. The counts come from the scanner's own matcher, so a preview
    cannot promise files the scan would not find.

    Returns whether every data collection would find something, so the caller
    does not follow a warning with a green "completed".
    """
    records = _ingestion_data_collections(project_config, count_files=True)
    if not records:
        rich_print_checked_statement("No data collection found in the project config.", "warning")
        return False

    # Reported before the table: a location that resolved no run at all explains
    # every zero below it, and naming the directory level is what turns "0 files"
    # into a fix.
    for workflow in getattr(project_config, "workflows", None) or []:
        for warning in resolve_run_locations(workflow).warnings:
            rich_print_checked_statement(warning, "warning")

    rows = []
    for record in records:
        file_count = record["file_count"]
        rows.append(
            {
                "data collection": record["tag"],
                "scan mode": record["scan_mode"] or "-",
                "pattern": _shorten_scan_pattern(record["scan_pattern"], record["locations"]),
                # A collection with no scan config (a derived one) has no files
                # to count, which is not the same as counting zero.
                "files": "n/a (no scan)" if file_count is None else str(file_count),
            }
        )
    render_records_table(rows, title="Dry run: files each data collection would match")

    empty = [record["tag"] for record in records if record["file_count"] == 0]
    if empty:
        rich_print_checked_statement(
            f"{len(empty)} data collection(s) would match no file: {', '.join(empty)}. "
            "Check --data-root and the scan patterns before running for real.",
            "warning",
        )
    return not empty


# How long an error exit waits for the server to record the outcome. Short, so
# a Ctrl-C against an unreachable server still returns promptly.
_ERROR_REPORT_TIMEOUT = 5.0


class _TerminatedBySignal(SystemExit):
    """SIGTERM turned into an exception, so the run can report before it exits.

    A ``SystemExit`` so the steps' ``except Exception`` blocks let it through,
    carrying ``128 + signum`` so the process still exits with the status a
    scheduler expects from a terminated job.
    """


class _IngestionRecord:
    """The server-side monitoring record of one ingestion.

    ``run_ingest`` fills it in as it goes (run id once opened, steps, project id)
    and closes it with the final tally at the summary. ``ingestion_record`` closes
    it on every other way out, so an error exit, a Ctrl-C or a SIGTERM no longer
    leaves the run "running" forever.
    """

    def __init__(self) -> None:
        self.run_id: str | None = None
        self.CLI_config = None
        self.project_config = None
        self.project_id: str | None = None
        # Steps only accumulate until the record is opened; ``go_live`` then swaps
        # in a reporter that also sends each one as it starts and ends.
        self.reporter = StepReporter(send=lambda *_: True, run_id=None, enabled=False)
        # Last step entered, so an interruption can name what it cut short.
        self.current_step: str | None = None
        self.closed = False

    @property
    def steps(self) -> list[dict]:
        """Every step recorded so far, in the order each was first seen."""
        return self.reporter.steps

    def start(self, name: str) -> None:
        """Enter a step: it shows as running until it is recorded again, at its end."""
        self.current_step = name
        self.reporter.start(name)

    def go_live(self) -> None:
        """Send each step to the server as it starts and ends, replaying the ones
        recorded before the record was opened. Does nothing without a run id."""
        if not self.run_id:
            return
        CLI_config = self.CLI_config
        previous = self.reporter.steps
        self.reporter = StepReporter(
            send=lambda run_id, step, current: api_monitoring_ingestion_step(
                CLI_config, run_id, step, current
            ),
            run_id=self.run_id,
        )
        self.reporter.replay(previous)

    def close(self, status: str, error: str | None = None, timeout: float = 30.0) -> None:
        """Report the outcome, once. Best-effort: never raises."""
        if self.closed or not self.run_id:
            return
        self.closed = True
        try:
            # A short, bounded wait for the live updates still queued: the finish
            # below carries every step anyway.
            self.reporter.close(timeout=2.0)
            api_monitoring_ingestion_finish(
                CLI_config=self.CLI_config,
                run_id=self.run_id,
                status=status,
                steps=self.steps,
                error=error,
                project_id=self.project_id,
                data_collections=_ingestion_data_collections(self.project_config),
                timeout=timeout,
            )
        except Exception as exc:
            logger.debug(f"Could not close the monitoring ingestion record (non-fatal): {exc}")


def _describe_abnormal_exit(
    exc: BaseException, record: _IngestionRecord
) -> tuple[str, str, dict | None]:
    """Status, error message and optional extra step for a run that never
    reached its summary."""
    if isinstance(exc, (KeyboardInterrupt, typer.Abort, _TerminatedBySignal)):
        cause = "Terminated (SIGTERM)" if isinstance(exc, _TerminatedBySignal) else "Interrupted"
        step = record.current_step
        # A step is recorded as running when it starts and again when it ends, so
        # a current step still running, or never recorded, is the one the
        # interruption cut short.
        recorded = [s for s in record.steps if s.get("name") == step]
        if step and (not recorded or recorded[-1].get("status") == "running"):
            return (
                "interrupted",
                f"{cause} during step '{step}'",
                {"name": step, "status": "interrupted", "detail": cause},
            )
        return "interrupted", cause, None
    if isinstance(exc, (typer.Exit, SystemExit)):
        for s in reversed(record.steps):
            if s.get("status") == "failed":
                return (
                    "failed",
                    f"Step '{s['name']}' failed: {s.get('detail') or 'no detail'}",
                    None,
                )
        code = exc.exit_code if isinstance(exc, typer.Exit) else exc.code
        return "failed", f"Exited with code {code}", None
    return "failed", f"{type(exc).__name__}: {exc}", None


def _raise_on_sigterm() -> Callable[[], None]:
    """Turn SIGTERM into ``_TerminatedBySignal`` until the returned undo runs.

    Schedulers and containers stop a job with SIGTERM, whose default action
    ends Python without unwinding, so the record would stay open. SIGKILL cannot
    be caught; the server's stale-run sweep covers that. Only the main thread
    may install handlers, so elsewhere this does nothing.
    """
    owner_pid = os.getpid()
    try:
        previous = signal.getsignal(signal.SIGTERM)
        restored = previous if previous is not None else signal.SIG_DFL

        def _handler(signum, frame):
            if os.getpid() != owner_pid:
                # A forked worker (the MultiQC parse pool) inherited this
                # handler: die the default way instead of unwinding the run.
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)
                return
            # Restore first, so a second SIGTERM while reporting ends it at once.
            signal.signal(signum, restored)
            raise _TerminatedBySignal(128 + signum)

        signal.signal(signal.SIGTERM, _handler)
    except (ValueError, OSError):
        return lambda: None

    def _restore() -> None:
        try:
            signal.signal(signal.SIGTERM, restored)
        except (ValueError, OSError):
            pass

    return _restore


@contextmanager
def ingestion_record(trap_sigterm: bool = True) -> Iterator[_IngestionRecord]:
    """A run's monitoring record, closed however the block exits.

    Around the whole run rather than a try/finally inside it: every step exits on
    its own with ``typer.Exit``, and a Ctrl-C or SIGTERM can land anywhere. The
    exception is always re-raised unchanged, so the exit code is what it would
    have been without monitoring. ``trap_sigterm`` turns SIGTERM into an exception
    for the block; ``watch`` turns it off, as its own handler lets the cycle in
    progress finish.
    """
    record = _IngestionRecord()
    restore_sigterm = _raise_on_sigterm() if trap_sigterm else (lambda: None)
    try:
        yield record
    except BaseException as exc:
        if record.run_id and not record.closed:
            try:
                status, error, step = _describe_abnormal_exit(exc, record)
                if step:
                    record.reporter.record(step["name"], step["status"], step["detail"])
                record.close(status, error, timeout=_ERROR_REPORT_TIMEOUT)
            except Exception as report_exc:
                logger.debug(f"Could not report the run's exit (non-fatal): {report_exc}")
        raise
    finally:
        restore_sigterm()


def _write_provisioned_cli_config(base_raw_config: dict, provision: dict) -> str:
    """Write a temporary CLI config that runs the pipeline as the provisioned user.

    Takes the operator's *raw* CLI config dict (as read from YAML) and swaps in
    only the provisioned user's identity and run token — ``api_base_url`` and
    ``s3_storage`` are preserved verbatim, so the real S3 secret (a SecretStr on
    the parsed model, which would be masked by ``model_dump``) is kept intact.
    Pointing the rest of the run at this file makes every step (sync, scan,
    process, dashboard import) own its resources as that user, with no changes
    to downstream code. The file holds a token, so it is created 0600 and
    removed on process exit.
    """
    import atexit
    import os
    import tempfile

    import yaml

    tok = provision["token"]
    temp_cfg = dict(base_raw_config)  # shallow copy; only `user` is replaced
    temp_cfg["user"] = {
        "id": provision["user_id"],
        "email": provision["email"],
        "is_admin": provision["is_admin"],
        "token": {
            "user_id": provision["user_id"],
            "access_token": tok["access_token"],
            "refresh_token": tok["refresh_token"],
            "token_type": tok["token_type"],
            "token_lifetime": tok["token_lifetime"],
            "expire_datetime": tok["expire_datetime"],
            "refresh_expire_datetime": tok["refresh_expire_datetime"],
            "name": tok["name"],
        },
    }

    fd, path = tempfile.mkstemp(prefix="depictio-cli-provisioned-", suffix=".yaml")
    with os.fdopen(fd, "w") as fh:
        yaml.safe_dump(temp_cfg, fh)
    os.chmod(path, 0o600)
    atexit.register(lambda: os.path.exists(path) and os.unlink(path))
    return path


def _server_run_locations(remote_project: dict) -> dict[str, tuple[list[str], list[str]]]:
    """Each workflow's run locations on the server, and those --attach-run added, by tag."""
    by_tag: dict[str, tuple[list[str], list[str]]] = {}
    for wf_doc in remote_project.get("workflows", []) or []:
        wf_tag = wf_doc.get("workflow_tag")
        if wf_tag:
            data_location = wf_doc.get("data_location") or {}
            # Fresh lists, so the remote entries are never aliased into the model.
            by_tag[wf_tag] = (
                list(data_location.get("locations") or []),
                list(data_location.get("attached_locations") or []),
            )
    return by_tag


def _distinct_locations(*groups: list[str]) -> list[str]:
    """The locations in order, each directory once. Compared by real path, so a data
    root reached through a symlink is the run it points to, not a second one."""
    seen: set[str] = set()
    distinct: list[str] = []
    for group in groups:
        for location in group:
            real = os.path.realpath(location)
            if real not in seen:
                seen.add(real)
                distinct.append(location)
    return distinct


def merge_run_locations(project_config, remote_project: dict) -> dict:
    """Add this run's locations to those the server holds, in place, and record them
    as attached.

    ``data_location.locations`` is a list and the scan treats each entry as its own
    run (``structure: flat``) or walks it for run subdirectories
    (``sequencing-runs``), so the locations are the project's runs. A configuration
    resolved from one data root lists that root only: an attach keeps every
    location the server holds, and puts this run's after them.

    ``attached_locations`` records them, so that a refresh keeps them (see
    :func:`refresh_run_locations`). A location the project already has is recorded
    too: attaching it again is how a run attached before the record existed is
    kept by the next refresh.

    Returns ``{"added": {workflow_tag: [locations]}, "recorded": {workflow_tag:
    [locations]}}``: the locations new to the project, and those newly recorded
    as attached.
    """
    server = _server_run_locations(remote_project)
    added: dict[str, list[str]] = {}
    recorded: dict[str, list[str]] = {}
    for wf in project_config.workflows:
        known, attached = server.get(wf.workflow_tag, ([], []))
        ours = _distinct_locations(wf.data_location.locations)
        known_real = {os.path.realpath(loc) for loc in known}
        added[wf.workflow_tag] = [loc for loc in ours if os.path.realpath(loc) not in known_real]
        wf.data_location.locations = known + added[wf.workflow_tag]

        # Under the name the locations list it by, which is the server's for a run
        # it already holds through another path.
        listed: dict[str, str] = {}
        for loc in wf.data_location.locations:
            listed.setdefault(os.path.realpath(loc), loc)
        attached_real = {os.path.realpath(loc) for loc in attached}
        recorded[wf.workflow_tag] = [
            listed[os.path.realpath(loc)]
            for loc in ours
            if os.path.realpath(loc) not in attached_real
        ]
        wf.data_location.attached_locations = attached + recorded[wf.workflow_tag]

    return {"added": added, "recorded": recorded}


def refresh_run_locations(project_config, remote_project: dict, drop_missing: bool = False) -> dict:
    """Set the run locations of a refresh, in place: this configuration's, then those
    added with --attach-run.

    Any other location the server holds is dropped, so the rescan removes its runs:
    a results directory that moved replaces the old one instead of being ingested
    next to it, and a location taken out of a project file goes away. A project
    ingested before attached runs were recorded has no record, so its extra
    locations are dropped too.

    An attached location that is not a directory on this host is reported as
    missing. The rescan would remove its runs, so the caller stops unless
    ``drop_missing``, which takes it out of the locations and of the record.

    Returns ``{"attached": {workflow_tag: [locations]}, "dropped": {workflow_tag:
    [locations]}, "missing": {workflow_tag: [locations]}}``: the attached locations
    kept besides this configuration's, the server's locations left out, and the
    attached locations not on disk.
    """
    server = _server_run_locations(remote_project)
    report: dict[str, dict[str, list[str]]] = {"attached": {}, "dropped": {}, "missing": {}}
    for wf in project_config.workflows:
        tag = wf.workflow_tag
        known, attached = server.get(tag, ([], []))
        requested = _distinct_locations(wf.data_location.locations)
        requested_real = {os.path.realpath(loc) for loc in requested}
        missing = [
            loc
            for loc in _distinct_locations(attached)
            if os.path.realpath(loc) not in requested_real and not os.path.isdir(loc)
        ]
        missing_real = {os.path.realpath(loc) for loc in missing}
        if drop_missing:
            attached = [loc for loc in attached if os.path.realpath(loc) not in missing_real]

        wf.data_location.locations = _distinct_locations(requested, attached)
        wf.data_location.attached_locations = attached
        kept_real = {os.path.realpath(loc) for loc in wf.data_location.locations}
        report["attached"][tag] = [
            loc for loc in wf.data_location.locations if os.path.realpath(loc) not in requested_real
        ]
        report["dropped"][tag] = [
            loc for loc in known if os.path.realpath(loc) not in kept_real | missing_real
        ]
        report["missing"][tag] = missing
    return report


def attach_run_to_project(project_config, remote_project: dict) -> dict:
    """Fold this run into an existing project, in place, and report what changed.

    Appending this run's directory to the locations is all it takes to add a run
    (see :func:`merge_run_locations`), which also records it as attached so that a
    refresh keeps it. The scan is incremental, so the runs already registered are
    skipped.

    Two things are deliberately preserved from the server:

    * the existing locations, so attaching never drops a run already ingested;
    * the ``scan.mode: single`` bindings. Such a collection points at ONE absolute
      path, substituted from whichever ``DATA_ROOT`` the template was resolved
      against, which here is the *new* run. Pushing that as-is would re-point the
      collection, and the next scan deletes files whose location no longer matches
      the config (the stale-file cleanup in ``scan_files_for_data_collection``), so
      the original run's samplesheet/metadata/tree would be dropped.

    Returns ``{"added": {workflow_tag: [locations]}, "recorded": {workflow_tag:
    [locations]}, "kept_single": [dc_tags]}``.
    """
    remote_single: dict[tuple[str, str], str] = {}
    for wf_doc in remote_project.get("workflows", []) or []:
        wf_tag = wf_doc.get("workflow_tag")
        if not wf_tag:
            continue
        for dc_doc in wf_doc.get("data_collections", []) or []:
            scan_doc = (dc_doc.get("config") or {}).get("scan") or {}
            if str(scan_doc.get("mode", "")).lower() != "single":
                continue
            filename = (scan_doc.get("scan_parameters") or {}).get("filename")
            dc_tag = dc_doc.get("data_collection_tag")
            if filename and dc_tag:
                remote_single[(wf_tag, dc_tag)] = filename

    merge = merge_run_locations(project_config, remote_project)

    kept_single: list[str] = []
    for wf in project_config.workflows:
        for dc in wf.data_collections:
            if not (dc.config.scan and dc.config.scan.mode.lower() == "single"):
                continue
            previous = remote_single.get((wf.workflow_tag, dc.data_collection_tag))
            if previous and previous != dc.config.scan.scan_parameters.filename:
                dc.config.scan.scan_parameters.filename = previous
                kept_single.append(dc.data_collection_tag)

    return {**merge, "kept_single": kept_single}


def _stop_on_missing_locations(report: dict) -> None:
    """End a refresh that would remove the runs of attached locations not on this host.

    Checked before the sync, so nothing has been changed yet: dropping them is for
    --drop-missing-runs to ask for, as a location that is only unmounted here, or
    reached under another path on another host, would otherwise lose its runs.
    """
    for wf_tag, missing in report["missing"].items():
        for location in missing:
            rich_print_checked_statement(
                f"Workflow '{escape(wf_tag)}': run location {escape(location)}, added with "
                f"--attach-run, is not on this host.",
                "error",
            )
    rich_print_checked_statement(
        "A refresh would remove the runs and files of the location(s) above, so it stops "
        "here and nothing was changed. Run it where they are reachable, or pass "
        "--drop-missing-runs to remove those runs from the project.",
        "error",
    )
    raise typer.Exit(code=1)


def _stop_on_run_tag_clash(project_config) -> None:
    """End the command when two flat locations of a workflow would share a run name.

    Checked once the locations are final, before the sync records them (the scan
    would refuse them only after the project was updated) and before the runs they
    add or keep are announced.
    """
    for wf in project_config.workflows:
        clash = flat_run_tag_clash(wf.data_location)
        if clash:
            rich_print_checked_statement(
                f"Workflow '{escape(str(wf.workflow_tag))}': {escape(clash)}", "error"
            )
            raise typer.Exit(code=1)


def _report_run_locations(project_config, report: dict) -> None:
    """Say, for a refresh, which runs the project keeps and which it loses."""
    for wf_tag, missing in report["missing"].items():
        for location in missing:
            rich_print_checked_statement(
                f"Workflow '{escape(wf_tag)}': run location {escape(location)} is not on "
                f"this host. --drop-missing-runs is given, so this refresh removes its runs "
                f"and files from the project and rebuilds the tables without them.",
                "warning",
            )
    for wf_tag, dropped in report["dropped"].items():
        for location in dropped:
            rich_print_checked_statement(
                f"Workflow '{escape(wf_tag)}': run location {escape(location)} is not in this "
                f"configuration and was not added with --attach-run, so this refresh removes "
                f"its runs and files from the project.",
                "warning",
            )
    total = sum(len(wf.data_location.locations) for wf in project_config.workflows)
    attached = sum(len(locations) for locations in report["attached"].values())
    rich_print_checked_statement(
        f"The project keeps {total} run location(s): "
        + (
            f"{total - attached} from this configuration, {attached} added with --attach-run"
            if attached
            else "those of this configuration"
        ),
        "info",
    )


def _stop_without_project(continue_on_error: bool) -> None:
    """End the run after the step that should have produced the project configuration.

    Every later step reads it, so ``--continue-on-error`` cannot carry on: it used to
    try, and each step failed on the missing configuration before a traceback.
    """
    if continue_on_error:
        rich_print_checked_statement(
            "Stopping despite --continue-on-error: every later step needs the project "
            "configuration.",
            "error",
        )
    raise typer.Exit(code=1)


def unknown_filter_error(
    project_config, workflow_name: str | None, data_collection_tag: str | None
) -> str | None:
    """Why ``--workflow-name`` / ``--data-collection-tag`` select nothing, or ``None``.

    Both match the way the scan and the processing filter: the workflow by its tag,
    the collection by its tag within the selected workflows.
    """
    workflows = list(project_config.workflows)
    if workflow_name:
        known = [wf.workflow_tag for wf in workflows]
        workflows = [wf for wf in workflows if wf.workflow_tag == workflow_name]
        if not workflows:
            return (
                f"--workflow-name '{workflow_name}' matches no workflow of this project. "
                f"Known: {', '.join(known) or 'none'}"
            )
    if data_collection_tag:
        known = [dc.data_collection_tag for wf in workflows for dc in wf.data_collections]
        if data_collection_tag not in known:
            where = f"workflow '{workflow_name}'" if workflow_name else "this project"
            return (
                f"--data-collection-tag '{data_collection_tag}' matches no data collection "
                f"of {where}. Known: {', '.join(known) or 'none'}"
            )
    return None


def _drop_pinned_ids(config: dict) -> None:
    """Drop the ids a project file pins, in place, so a renamed copy is a project of its own.

    Kept, they would make it the same project under another name: the sync finds a
    project by id before name, and a data collection's id names its Delta table.
    The server's ids still come back by name through ``merge_existing_ids`` when the
    renamed project already exists. Links that point at a pinned collection id point
    at its tag instead, which the validation resolves once ids are assigned.
    """
    tag_by_id: dict[str, str] = {}
    collections = list(config.get("data_collections") or [])
    for wf in config.get("workflows") or []:
        wf.pop("id", None)
        wf.pop("_id", None)
        collections.extend(wf.get("data_collections") or [])
    for dc in collections:
        # Both keys, as a file may carry both: a kept `_id` would give the renamed
        # copy the original's id, and with it the original's Delta table.
        for dc_id in (dc.pop("id", None), dc.pop("_id", None)):
            if dc_id and dc.get("data_collection_tag"):
                tag_by_id[str(dc_id)] = dc["data_collection_tag"]
    for join in config.get("joins") or []:
        join.pop("id", None)
    for link in config.get("links") or []:
        link.pop("id", None)
        for side in ("source", "target"):
            tag = tag_by_id.get(str(link.get(f"{side}_dc_id")))
            if tag:
                link.pop(f"{side}_dc_id")
                link[f"{side}_dc_tag"] = link.get(f"{side}_dc_tag") or tag
    config.pop("id", None)
    config.pop("_id", None)


def load_project_file(path: str, project_name: str | None = None) -> dict:
    """The project file as the dict validation takes, renamed when ``project_name`` is given."""
    from depictio.models.utils import get_config

    config = get_config(path)
    config["yaml_config_path"] = os.path.abspath(path)
    if project_name and project_name != config.get("name"):
        config["name"] = project_name
        _drop_pinned_ids(config)
    return config


def _bound_project_file(path: str, project_name: str | None, bind: list[str]) -> dict:
    """The project file as ``load_project_file`` reads it, with each ``--bind`` applied."""
    config = load_project_file(path, project_name)
    if not bind:
        return config
    from depictio.cli.cli.utils.bindings import BindingError, apply_bindings

    try:
        for note in apply_bindings(config, list(bind)):
            rich_print_checked_statement(f"Bound {note}", "info")
    except BindingError as exc:
        rich_print_checked_statement(str(exc), "error")
        raise typer.Exit(code=1)
    return config


def validate_project_locally(config: dict):
    """The configuration as a ``Project``, checked without a server.

    For a dry run: no owner to add and no ids to merge, but a missing file, a
    location that is not there or an invalid field fails as it would for real.
    """
    import copy

    from pydantic import ValidationError

    from depictio.models.models.projects import Project
    from depictio.models.utils import substitute_env_vars

    config = copy.deepcopy(config)
    config["permissions"] = {"owners": [], "editors": [], "viewers": []}
    try:
        return Project(**substitute_env_vars(config))
    except ValidationError as exc:
        from depictio.cli.cli.utils.config import describe_invalid_config

        # One line per problem, as a real run reports it, not pydantic's dump.
        raise ValueError(
            f"Project configuration validation failed:\n{describe_invalid_config(exc)}"
        ) from exc


# The panels of `ingest --help` past the essentials, which stay in the default one.
PROJECT_PANEL = "Project and runs"
DASHBOARDS_PANEL = "Dashboards"
STEPS_PANEL = "Scope and steps"
AUTOMATION_PANEL = "Automation"
DEBUG_PANEL = "Performance and debugging"

# The steps --skip takes, each with the flag that skipped it before.
SKIP_STEPS = {
    "server-check": "--skip-server-check",
    "s3-check": "--skip-s3-check",
    "sync": "--skip-sync",
    "scan": "--skip-scan",
    "process": "--skip-process",
    "join": "--skip-join",
    "dashboards": "--skip-dashboard-import",
}

# What step 8 did to each dashboard, as the server reports it.
DASHBOARD_STATUSES = ("created", "kept", "replaced")


def parse_skip(values: list[str] | None) -> list[str]:
    """The steps --skip names, comma-separated, repeated or both.

    An unknown step is a usage error that lists the known ones: ignored, a typo
    would run the very step it was meant to skip.
    """
    steps: list[str] = []
    for value in values or []:
        for step in (part.strip().lower() for part in value.split(",")):
            if not step:
                continue
            if step not in SKIP_STEPS:
                raise typer.BadParameter(f"unknown step '{step}'. Steps: {', '.join(SKIP_STEPS)}")
            if step not in steps:
                steps.append(step)
    return steps


# The Delta write strategies step 6 knows. There is deliberately no append mode:
# a run is always rebuilt by re-parsing its files.
WRITE_MODES = ("overwrite", "replace-runs")


@dataclass(frozen=True)
class IngestOptions:
    """What ``run_ingest`` runs: ``ingest``'s options once its usage checks passed,
    the former names folded in, and what ``watch`` sets for each of its cycles."""

    data_root: str | None = None
    # The CLI configuration file, already resolved from --server.
    CLI_config_path: str | None = None
    template: str | None = None
    project_config_path: str = ""
    project_name: str | None = None
    # A data manifest (URL or local file) filling a manifest-driven template.
    manifest: str | None = None
    # TAG=LOCATION overrides of a data collection's scan, applied after resolution.
    bind: tuple[str, ...] = ()
    var: tuple[str, ...] = ()
    update_config: bool = False
    dry_run: bool = False
    attach_run: bool = False
    drop_missing_runs: bool = False
    provenance_file: tuple[str, ...] = ()
    dashboard: tuple[str, ...] = ()
    dashboard_name: str | None = None
    reset_dashboards: bool = False
    workflow_name: str | None = None
    data_collection_tag: str | None = None
    # The steps to skip, named as --skip names them (SKIP_STEPS).
    skip: frozenset[str] = frozenset()
    continue_on_error: bool = False
    pipeline_id: str | None = None
    triggered_by: str = "manual"
    user: str | None = None
    provisioning_key: str | None = None
    streaming: bool = False
    preview_recipes: bool = False
    rich_tables: bool = False
    overwrite: bool = False
    rescan_folders: bool = False
    sync_files: bool = False
    sync_changed: bool = False
    legacy_scan_depth: bool = False
    state_cache: bool = True
    concurrency: int = 4
    upload_chunk_size: int = 1000
    write_mode: str = "overwrite"
    incremental_write: bool = False
    skip_unchanged: bool = False
    repartition: bool = False
    async_upsert: bool = False
    # Not options of `ingest`: `watch` sets them for each cycle.
    command: str = "ingest"
    trigger: str = "manual"
    trigger_reason: str | None = None
    # The scan and the processing report what they would change and write nothing.
    # Unlike dry_run, which stops before the server is contacted at all.
    scan_dry_run: bool = False
    # Given the monitoring run id once the record is opened (None if it was not).
    on_run_opened: Callable[[str | None], None] | None = None
    # The per-project lock, taken once the project is validated and before the
    # first write, then left held for the caller to release: `ingest` holds it for
    # its one run, `watch` from its first cycle to its exit. None takes no lock.
    project_lock: ProjectLock | None = None


@dataclass(frozen=True)
class IngestOutcome:
    """How far an ingestion that ran to its summary got."""

    success_count: int
    total_steps: int

    @property
    def ok(self) -> bool:
        """Whether every step completed (or was skipped as asked)."""
        return self.success_count == self.total_steps


def run_ingest(opts: IngestOptions, ingestion: _IngestionRecord) -> IngestOutcome:
    """Run the ingestion steps, from validation to dashboards, recording them on
    ``ingestion``.

    A step that fails stops the run with ``typer.Exit`` unless
    ``opts.continue_on_error``; a run that reaches its summary returns how many
    steps completed. ``ingest`` runs it once, ``watch`` once per cycle.
    """
    data_root = opts.data_root
    CLI_config_path = opts.CLI_config_path
    template = opts.template
    project_config_path = opts.project_config_path
    project_name = opts.project_name
    manifest = opts.manifest
    bind = list(opts.bind)
    var = list(opts.var)
    update_config = opts.update_config
    dry_run = opts.dry_run
    attach_run = opts.attach_run
    drop_missing_runs = opts.drop_missing_runs
    provenance_file = list(opts.provenance_file) or None
    dashboard = list(opts.dashboard) or None
    dashboard_name = opts.dashboard_name
    reset_dashboards = opts.reset_dashboards
    workflow_name = opts.workflow_name
    data_collection_tag = opts.data_collection_tag
    continue_on_error = opts.continue_on_error
    pipeline_id = opts.pipeline_id
    triggered_by = opts.triggered_by
    user = opts.user
    provisioning_key = opts.provisioning_key
    streaming = opts.streaming
    preview_recipes = opts.preview_recipes
    rich_tables = opts.rich_tables
    overwrite = opts.overwrite
    rescan_folders = opts.rescan_folders
    sync_files = opts.sync_files
    sync_changed = opts.sync_changed
    legacy_scan_depth = opts.legacy_scan_depth
    state_cache = opts.state_cache
    concurrency = opts.concurrency
    upload_chunk_size = opts.upload_chunk_size
    write_mode = opts.write_mode
    incremental_write = opts.incremental_write
    skip_unchanged = opts.skip_unchanged
    repartition = opts.repartition
    async_upsert = opts.async_upsert
    command = opts.command
    trigger = opts.trigger
    trigger_reason = opts.trigger_reason
    scan_dry_run = opts.scan_dry_run
    on_run_opened = opts.on_run_opened
    skip_server_check = "server-check" in opts.skip
    skip_s3_check = "s3-check" in opts.skip
    skip_sync = "sync" in opts.skip
    skip_scan = "scan" in opts.skip
    skip_process = "process" in opts.skip
    skip_join = "join" in opts.skip
    skip_dashboard_import = "dashboards" in opts.skip

    # A data root that is not there is an argument mistake, and it is worth
    # saying so before anything else happens. This used to live inside the
    # template branch, so the identical mistake made with
    # --project-config-path instead surfaced three steps later as a raw
    # pydantic validation error naming a file, a line and a function: it
    # read like an internal crash rather than a typo. Same cause, same
    # message, whichever way the project was described.
    if data_root and not Path(data_root).is_dir():
        rich_print_checked_statement(
            f"DATA_DIR does not exist or is not a directory: {escape(data_root)}",
            "error",
        )
        raise typer.Exit(code=1)
    # The same for the other paths: a dashboard file used to be read at step 8
    # only, after every table had been written.
    for option, paths in (
        ("--project-config-path", [project_config_path] if project_config_path else []),
        ("--dashboard", dashboard or []),
    ):
        for path in paths:
            if not Path(path).is_file():
                rich_print_checked_statement(
                    f"{option} does not exist or is not a file: {escape(path)}", "error"
                )
                raise typer.Exit(code=1)

    # Step 0-: resolve a bundled template from the pipeline identity. The
    # trigger forwards what its engine reported and lets the CLI decide the
    # mode; an explicit --template / --project-config-path always wins.
    if pipeline_id and not template and not project_config_path:
        from depictio.cli.cli.utils.templates import locate_template

        try:
            locate_template(pipeline_id)
        except FileNotFoundError:
            rich_print_checked_statement(
                f"No bundled depictio template matches pipeline "
                f"'{escape(pipeline_id)}'. Provide --project-config-path with a depictio "
                f"project YAML for this pipeline (or --template for a known one).",
                "error",
            )
            raise typer.Exit(code=1)
        template = pipeline_id
        rich_print_checked_statement(
            f"Resolved pipeline '{escape(pipeline_id)}' to a bundled template.",
            "success",
        )

    # Read the run's own provenance whenever there is a directory to look at,
    # deliberately independent of how the template was chosen. The dominant
    # trigger path forwards --pipeline-id, which already resolved a
    # template above, but the engine version and the tool list exist nowhere
    # except the run directory. Gating this on "no template yet" left every
    # pipeline-triggered project with empty provenance.
    detected_info = None
    if data_root and Path(data_root).is_dir():
        from depictio.models.models.run_info import read_run_info

        detected_info = read_run_info(data_root)
        if detected_info is not None:
            version = f" {detected_info.pipeline_version}" if detected_info.pipeline_version else ""
            rich_print_checked_statement(
                f"Detected {detected_info.pipeline_name or 'an unidentified pipeline'}"
                f"{version} ({detected_info.engine or 'unknown engine'}, "
                f"{len(detected_info.tools_executed)} tool(s))",
                "info",
            )

    # Step 0-: nothing was specified at all, so let the run directory pick the
    # template too. This is the fallback for a pipeline whose manifest the
    # trigger could not forward (an older Nextflow, a hand-run CLI, a
    # non-Nextflow engine).
    if detected_info is not None and not template and not project_config_path:
        from depictio.cli.cli.utils.templates import select_template_for_run

        detected_template = select_template_for_run(detected_info)
        if detected_template:
            template = detected_template
            rich_print_checked_statement(f"Auto-selected template: {escape(template)}", "success")

    # Whichever path chose the template, say so when the run is another major
    # release of the pipeline: the import then prunes what the run lacks
    # without a word on why a tab is gone.
    if detected_info is not None and template:
        from depictio.cli.cli.utils.templates import major_release_gap

        template_release = major_release_gap(detected_info, template)
        if template_release:
            rich_print_checked_statement(
                f"{escape(str(detected_info.pipeline_name))} "
                f"{escape(str(detected_info.pipeline_version))} is not the major release "
                f"the template was built for ({template_release}). Outputs move between "
                "major releases: data collections that find no files are skipped, and "
                "the tabs built on them are dropped.",
                "warning",
            )

    # Validate template/project-config-path mutual exclusivity
    if template and project_config_path:
        rich_print_checked_statement(
            "--template and --project-config-path are mutually exclusive. Use one or the other.",
            "error",
        )
        raise typer.Exit(code=1)

    if manifest and not template:
        rich_print_checked_statement(
            "--manifest needs --template, the template the manifest fills: depictio "
            "ingest --template <id> --manifest <url>.",
            "error",
        )
        raise typer.Exit(code=1)

    if manifest and data_root:
        rich_print_checked_statement(
            "Give DATA_DIR or --manifest, not both: a manifest lists the files itself.",
            "error",
        )
        raise typer.Exit(code=1)

    # --bind gives each data collection its location itself, so it stands in for
    # DATA_DIR / --manifest.
    if template and not data_root and not manifest and not bind:
        rich_print_checked_statement(
            "--template needs DATA_DIR, the results to ingest (or --manifest, or --bind): "
            "depictio ingest <results dir> --template <id>.",
            "error",
        )
        raise typer.Exit(code=1)

    # Without either there is no project to ingest into. It used to run steps 1
    # and 2 first, then fail at step 3 on an empty file name.
    if not template and not project_config_path:
        undetected = " No bundled template matches what DATA_DIR holds." if data_root else ""
        rich_print_checked_statement(
            "Say which project to ingest: depictio ingest <results dir> --template <id> "
            "for a pipeline Depictio ships a template for (detected from the results "
            f"when it can be), or --project-config-path <project.yaml>.{undetected}",
            "error",
        )
        raise typer.Exit(code=2)

    if dry_run:
        rich_print_checked_statement(
            "DRY RUN MODE - No actual operations will be performed", "info"
        )

    # `--overwrite` normally implies a full re-scan. In attach mode that would be
    # wrong: the point is to add ONE run, and the scan is already incremental
    # (a known run_tag is skipped). We still need overwrite for the *process*
    # step, because write_delta_table refuses to rewrite an existing table
    # without it, and the rebuild must include the runs already ingested.
    # Its dashboards are imported as on any refresh: the ones the project has
    # are kept as they are, so only those it lacks are added.
    if attach_run:
        update_config = True
        overwrite = True
    # A reset re-imports dashboards over those of a project that exists, which
    # only the refresh path reaches: without it, the sync stops on that project.
    if reset_dashboards:
        update_config = True
    # Refreshing a project in place rewrites the tables it already has, which
    # write_delta_table refuses to replace without overwrite (its dashboards are
    # kept, unless --reset-dashboards).
    # --update-config alone used to update the configuration, then fail every data
    # collection on its existing table; the Nextflow hook always passed both.
    # And --overwrite alone used to rewrite nothing: the sync stopped on the
    # existing project, so the two are one behaviour under two names.
    if update_config or overwrite:
        update_config = overwrite = True
    # --sync-changed re-uploads what moved, so it needs every run walked
    # again too: without it, a registered run is skipped unread.
    if sync_files or sync_changed or (overwrite and not attach_run):
        rescan_folders = True

    if user and not provisioning_key:
        rich_print_checked_statement(
            "--user requires --provisioning-key "
            "(or the DEPICTIO_AUTH_PROVISIONING_API_KEY environment variable).",
            "error",
        )
        raise typer.Exit(code=1)

    # Track whether we're in template mode
    is_template_mode = template is not None
    template_resolved_config: dict | None = None
    # Only the template branch fills these; a --dashboard import outside it
    # substitutes nothing, since a hand-written dashboard names its data
    # collections directly instead of going through template variables.
    template_variables: dict[str, str] = {}
    template_dashboard_paths: list[Path] = []
    # (title, id, created/kept/replaced) per imported dashboard, for the
    # summary. Step 8 already prints them, but that scrolls past; the summary is
    # where someone reading a finished pipeline log looks for somewhere to click,
    # and for what a refresh did to the dashboards edited in the viewer.
    imported_dashboards: list[tuple[str, str, str]] = []
    # --dashboard is honoured whether or not a template is in play. It used
    # to be read only inside the template branch, so a pipeline Depictio
    # ships no template for could ask for a dashboard and be silently
    # ignored: the run reported 7/7 success and produced a project nobody
    # could look at.
    if dashboard:
        template_dashboard_paths = [Path(p).resolve() for p in dashboard]
    # First dashboard imported for the provisioned user — target of the
    # passwordless login link emitted at the end of the run.
    provisioned_dashboard_id: str | None = None

    # Bound by step 0 in template mode; the summary names the resolved id.
    template_metadata = None

    success_count = 0
    total_steps = 8 if (is_template_mode or template_dashboard_paths) else 7
    # --attach-run adds step 3b (folding the run into the existing project).
    if attach_run and not dry_run:
        total_steps += 1
    # What the scan found, handed to the process step. Empty when the scan
    # was skipped, which correctly reads as "no information" downstream.
    scan_signal: dict = {}

    # ``ingestion`` is the server-side monitoring record of this run
    # (best-effort). The caller's ``ingestion_record`` owns it, so every exit
    # path reports how the run ended; this fills in the run id, project and
    # steps as it goes. Its ``project_id`` is the server-side id, resolved once
    # available (post-sync) and patched onto the record at finish. Steps are
    # recorded from the very start, so the phases that ran before the record
    # is opened (server/S3/validate) are still reported. Best-effort:
    # recording must never affect the ingestion itself.

    def _rec(name: str, status: str, detail: str | None = None, **extra) -> None:
        ingestion.reporter.record(name, status, detail, **extra)

    def _step_done(done: str, would: str) -> None:
        """The line a step ends on: what it did, or in a dry run what it would do."""
        if dry_run:
            rich_print_checked_statement(would, "info")
        else:
            rich_print_checked_statement(done, "success")

    # Step 0a (provisioning only): create-or-get the user and switch the run
    # to act as them by pointing CLI_config_path at a temporary per-user
    # config. Everything downstream then owns its resources as that user.
    if user and not dry_run:
        rich_print_section_separator("Provisioning user account")
        try:
            from depictio.models.utils import get_config

            base_config = load_depictio_config(yaml_config_path=CLI_config_path)
            # The file the load above read, DEPICTIO_CLI_CONFIG_PATH included.
            base_raw_config = get_config(cli_config_file(CLI_config_path))
            provision = api_provision_user(str(base_config.api_base_url), user, provisioning_key)
            CLI_config_path = _write_provisioned_cli_config(base_raw_config, provision)
            action = "Created account for" if provision.get("created") else "Reusing account"
            rich_print_checked_statement(
                f"{action} {provision['email']}: running the pipeline as this user",
                "success",
            )
            _rec("provisioning", "success", f"{action} {provision.get('email')}")
        except typer.Exit:
            _rec("provisioning", "failed", "the CLI configuration could not be read")
            raise
        except Exception as e:
            rich_print_checked_statement(f"User provisioning failed: {escape(str(e))}", "error")
            _rec("provisioning", "failed", str(e))
            raise typer.Exit(code=1)

    # Step 0 (template only): Resolve template and validate data
    if is_template_mode:
        rich_print_section_separator("Step 0: Resolving project template")
        try:
            from depictio.cli.cli.utils.templates import resolve_template

            # Parse --var KEY=VALUE pairs into extra_vars dict
            extra_vars: dict[str, str] = {}
            for v in var:
                if "=" not in v:
                    rich_print_checked_statement(
                        f"--var must be KEY=VALUE format, got: {escape(repr(v))}", "error"
                    )
                    raise typer.Exit(code=1)
                k, val = v.split("=", 1)
                extra_vars[k.strip()] = val.strip()

            # Manifest mode: MANIFEST_URL is just a template variable. A
            # local manifest path is resolved to absolute so the config
            # stays valid from any working directory.
            if manifest:
                from depictio.models.models.manifest import is_remote_url

                if not is_remote_url(manifest):
                    manifest_path = Path(manifest).resolve()
                    if not manifest_path.is_file():
                        rich_print_checked_statement(
                            f"--manifest file does not exist: {manifest}", "error"
                        )
                        raise typer.Exit(code=1)
                    manifest = str(manifest_path)
                extra_vars.setdefault("MANIFEST_URL", manifest)

            # Resolve template
            (
                resolved_config,
                template_metadata,
                template_origin,
                default_dashboard_paths,
                template_variables,
            ) = resolve_template(
                template_id=template,  # type: ignore[arg-type]
                data_root=data_root,  # type: ignore[arg-type]
                project_name=project_name,
                extra_vars=extra_vars or None,
                provenance_files=provenance_file,
                # --bind can make a declared variable irrelevant by replacing
                # the scan block that used it; assert_no_unbound_vars below
                # still fails when it turns out to be genuinely needed.
                allow_missing_vars=bool(bind),
            )

            rich_print_checked_statement(
                f"Template '{template_metadata.template_id}' loaded successfully",
                "success",
            )
            _rec(
                "template_resolve",
                "success",
                f"template '{template_metadata.template_id}' loaded",
            )

            # Stamp the run's own provenance onto each workflow config when we
            # read it from the run directory. It lives on the run-scoped
            # WorkflowConfig so one workflow can aggregate runs produced by
            # different pipeline versions without them conflicting.
            if detected_info is not None:
                provenance = {
                    "engine_name": detected_info.engine,
                    "pipeline_version": detected_info.pipeline_version,
                    "nextflow_version": (
                        detected_info.engine_version if detected_info.engine == "nextflow" else None
                    ),
                    "tools_executed": sorted(detected_info.tools_executed),
                }
                provenance = {k: v for k, v in provenance.items() if v}
                for wf in resolved_config.get("workflows", []):
                    wf.setdefault("config", {}).update(provenance)

            template_resolved_config = resolved_config

            # --bind overrides the template author's scan choice per DC.
            # Applied after resolution so it wins over {DATA_ROOT} / {MANIFEST_URL}
            # substitution rather than being overwritten by it.
            if bind:
                from depictio.cli.cli.utils.bindings import (
                    BindingError,
                    apply_bindings,
                    assert_no_unbound_vars,
                )

                try:
                    for note in apply_bindings(template_resolved_config, list(bind)):
                        rich_print_checked_statement(f"Bound {note}", "info")
                    assert_no_unbound_vars(template_resolved_config)
                except BindingError as exc:
                    rich_print_checked_statement(str(exc), "error")
                    raise typer.Exit(code=1)

            # Resolve dashboard paths: CLI --dashboard overrides template defaults
            if dashboard:
                rich_print_checked_statement(
                    f"Using {len(template_dashboard_paths)} dashboard(s) from --dashboard override",
                    "info",
                )
            else:
                template_dashboard_paths = default_dashboard_paths
                if template_dashboard_paths:
                    rich_print_checked_statement(
                        f"Template provides {len(template_dashboard_paths)} default dashboard(s)",
                        "info",
                    )

            if dry_run:
                # A summary, not the full config. Printed, not logged: at the
                # default log level the heading used to be followed by nothing.
                rich_print_checked_statement("Resolved template configuration:", "info")
                for line in (
                    f"Project: {resolved_config.get('name')}",
                    f"Template: {template_origin.template_id} "
                    f"(template version {template_origin.template_version})",
                    f"Data root: {template_origin.data_root}",
                    *(
                        f"Workflow '{w.get('name')}': "
                        f"{len(w.get('data_collections', []))} data collection(s): "
                        + ", ".join(
                            str(dc.get("data_collection_tag"))
                            for dc in w.get("data_collections", [])
                        )
                        for w in resolved_config.get("workflows", [])
                    ),
                ):
                    rich_print_checked_statement(f"  {escape(line)}", "info")

        except typer.Exit:
            raise
        except Exception as e:
            rich_print_checked_statement(f"Template resolution failed: {escape(str(e))}", "error")
            _rec("template_resolve", "failed", str(e))
            _stop_without_project(continue_on_error)

    # Step 1: Check server accessibility
    if skip_server_check:
        rich_print_checked_statement("Skipping server accessibility check", "info")
        success_count += 1
        _rec("server_check", "skipped")
    elif dry_run:
        rich_print_section_separator(f"Step 1/{total_steps}: Checking server accessibility")
        # Read, not contacted: it names the server, and a configuration that
        # is not there fails here as it would for real.
        load_depictio_config(yaml_config_path=CLI_config_path)
        rich_print_checked_statement("Would check that this server answers", "info")
        success_count += 1
    else:
        rich_print_section_separator(f"Step 1/{total_steps}: Checking server accessibility")
        try:
            login = api_login(CLI_config_path)
        except typer.Exit:
            # Already reported, by the configuration load. `typer.Exit`
            # subclasses RuntimeError, so the handler below used to catch it
            # and print a failure with an empty reason.
            _rec("server_check", "failed", "the CLI configuration could not be read")
            raise
        except Exception as e:
            # Name the endpoint and the file it came from; see
            # describe_api_target for why that matters here in particular.
            target = describe_api_target(CLI_config_path)
            rich_print_checked_statement(
                f"Server accessibility check failed: {escape(str(e))}", "error"
            )
            rich_print_checked_statement(f"Tried {escape(target)}", "info")
            say_local_server_running(CLI_config_path)
            _rec("server_check", "failed", f"{e} (tried {target})")
            if not continue_on_error:
                raise typer.Exit(code=1)
        else:
            # api_login reports a refused login by RETURNING {"success": False},
            # not by raising. Unchecked, an expired token was followed by "check
            # passed", and the run died at step 3 on an error that said nothing
            # about authentication. Only a refusal blames the token: a viewer
            # host's 404 or a proxy's 502 is not its fault.
            if login.get("success"):
                rich_print_checked_statement("Server accessibility check passed", "success")
                success_count += 1
                _rec("server_check", "success", "server reachable")
            else:
                report_login_failure(CLI_config_path, login, "Server accessibility check failed")
                say_local_server_running(CLI_config_path)
                _rec(
                    "server_check",
                    "failed",
                    f"login refused (HTTP {login.get('status_code', 200)})",
                )
                if not continue_on_error:
                    raise typer.Exit(code=1)

    # Step 2: Check S3 storage
    if skip_s3_check:
        rich_print_checked_statement("Skipping S3 storage check", "info")
        success_count += 1
        _rec("s3_check", "skipped")
    elif dry_run:
        rich_print_section_separator(f"Step 2/{total_steps}: Checking S3 storage configuration")
        rich_print_checked_statement("Would check the S3 storage configuration", "info")
        success_count += 1
    else:
        rich_print_section_separator(f"Step 2/{total_steps}: Checking S3 storage configuration")
        try:
            CLI_config = load_depictio_config(yaml_config_path=CLI_config_path)
            S3_storage_checks(CLI_config.s3_storage)
            rich_print_checked_statement("S3 storage configuration check passed", "success")
            success_count += 1
            _rec("s3_check", "success", "S3 storage reachable")
        except typer.Exit:
            _rec("s3_check", "failed", "the CLI configuration could not be read")
            raise
        except Exception as e:
            rich_print_checked_statement(f"S3 storage check failed: {escape(str(e))}", "error")
            _rec("s3_check", "failed", str(e))
            if not continue_on_error:
                raise typer.Exit(code=1)

    # Stays None when validation fails under --continue-on-error: the later steps
    # check it, so the failure is not reported again as a broken scan.
    project_config = None

    # Step 3: Validate project configuration
    rich_print_section_separator(f"Step 3/{total_steps}: Validating project configuration")
    try:
        if dry_run:
            # Locally only, as a dry run contacts no server; a missing or
            # invalid file used to pass here and fail the real run.
            project_config = validate_project_locally(
                template_resolved_config
                if is_template_mode and template_resolved_config is not None
                else _bound_project_file(project_config_path, project_name, bind)
            )
            rich_print_checked_statement(
                "Project configuration is valid (checked locally; a dry run does not "
                "contact the server)",
                "success",
            )
        else:
            if is_template_mode and template_resolved_config is not None:
                # Template mode: use resolved config dict
                from depictio.cli.cli.utils.config import validate_template_project_config

                CLI_config, validation_response = validate_template_project_config(
                    CLI_config_path=CLI_config_path,
                    resolved_config=template_resolved_config,
                )
            elif project_name or bind:
                # --project applies to a project file too. It renames the
                # project before the server is asked for its ids: renamed
                # afterwards, the configuration would carry the ids of the
                # project the file names, and the sync would update that one.
                # --bind patches the same dict in memory, since the file on disk
                # must stay untouched. The dict path of the template mode merges
                # them by the new name.
                from depictio.cli.cli.utils.config import validate_template_project_config

                CLI_config, validation_response = validate_template_project_config(
                    CLI_config_path=CLI_config_path,
                    resolved_config=_bound_project_file(project_config_path, project_name, bind),
                )
            else:
                # Standard mode: load from YAML file
                CLI_config, validation_response = validate_project_config_and_check_S3_storage(
                    CLI_config_path=CLI_config_path,
                    project_config_path=project_config_path,
                )
            if not validation_response["success"]:
                raise Exception("Project configuration validation failed")
            project_config = validation_response["project_config"]
            rich_print_checked_statement("Project configuration validation passed", "success")
        success_count += 1
        _rec("validate_config", "success", "config valid")
    except typer.Exit:
        _rec("validate_config", "failed", "project configuration could not be validated")
        raise
    except Exception as e:
        rich_print_checked_statement(escape(str(e)), "error")
        _rec("validate_config", "failed", str(e))
        _stop_without_project(continue_on_error)
    # On the record from here, not only once it is opened: `watch` takes the
    # locations to watch from it, after the refresh below has added the runs the
    # server knows, and a dry-run cycle opens no record.
    ingestion.project_config = project_config

    # --workflow-name and --data-collection-tag select what the scan and the
    # processing touch. Checked before anything is written: an unknown tag used
    # to be a warning, and every collection was then processed anyway.
    filter_error = unknown_filter_error(project_config, workflow_name, data_collection_tag)
    if filter_error:
        rich_print_checked_statement(escape(filter_error), "error")
        raise typer.Exit(code=1)

    # One ingestion per project at a time, from here to the caller's release:
    # everything above only read, and the first write is close below. A second
    # watcher, or an `ingest` racing a watcher's cycle, would interleave writes
    # to the same runs and Delta tables. Neither dry run writes, so neither locks.
    if opts.project_lock is not None and project_config is not None:
        if not dry_run and not scan_dry_run:
            try:
                opts.project_lock.acquire(
                    lock_path(str(CLI_config.api_base_url), str(project_config.id))
                )
            except ProjectLockError as exc:
                rich_print_checked_statement(escape(str(exc)), "error")
                raise

    # A refresh keeps the runs of this configuration's locations and of those
    # added with --attach-run, and the full rescan removes any other. Settled
    # here, before the sync, so a refresh that has to stop changes nothing.
    if update_config and not attach_run and not dry_run:
        remote = api_get_project_from_name(str(project_config.name), CLI_config)
        if remote.status_code == 200:
            run_locations = refresh_run_locations(
                project_config, remote.json(), drop_missing=drop_missing_runs
            )
            if not drop_missing_runs and any(run_locations["missing"].values()):
                _stop_on_missing_locations(run_locations)
            _stop_on_run_tag_clash(project_config)
            _report_run_locations(project_config, run_locations)

    # Step 3b (--attach-run): fold the run into an EXISTING project instead of
    # creating a new one. `data_location.locations` is a list and the scan treats
    # each entry as its own run (structure: flat) or walks it for run subdirs
    # (sequencing-runs), so appending this run's directory is all it takes. The
    # validation above already ran merge_existing_ids(), which copies the server's
    # workflow / data-collection ids onto this config by tag, so the runs and files
    # already ingested stay attached to the same collections.
    if attach_run and not dry_run:
        rich_print_section_separator("Step 3b: Attaching run to existing project")
        try:
            remote = api_get_project_from_name(str(project_config.name), CLI_config)
            if remote.status_code != 200:
                rich_print_checked_statement(
                    f"--attach-run: no project named '{escape(str(project_config.name))}' "
                    f"on this server (HTTP {remote.status_code}). Ingest once without "
                    f"--attach-run to create it, or pass --project to target another "
                    f"project.",
                    "error",
                )
                _rec("attach_run", "failed", "target project not found")
                raise typer.Exit(code=2)

            report = attach_run_to_project(project_config, remote.json())
            _stop_on_run_tag_clash(project_config)
            added_locations = {tag: locs for tag, locs in report["added"].items() if locs}
            for wf_tag, new_locations in added_locations.items():
                rich_print_checked_statement(
                    f"Workflow '{escape(wf_tag)}': +{len(new_locations)} run location(s) -> "
                    f"{escape(', '.join(new_locations))}",
                    "success",
                )
            if not added_locations:
                rich_print_checked_statement(
                    "--attach-run: this data location is already one of the project's "
                    "runs, so no run is added. Its tables are rebuilt from the runs it "
                    "already has."
                    + (
                        " It is now recorded as attached, so a refresh keeps it."
                        if any(report["recorded"].values())
                        else ""
                    ),
                    "info",
                )
            if report["kept_single"]:
                rich_print_checked_statement(
                    f"{len(report['kept_single'])} single-file data collection(s) keep "
                    f"the file they were first ingested from, and do not pick up this "
                    f"run's copy: {escape(', '.join(report['kept_single']))}",
                    "warning",
                )

            success_count += 1
            _rec("attach_run", "success", f"{len(project_config.workflows)} workflow(s)")
        except typer.Exit:
            raise
        except Exception as e:
            rich_print_checked_statement(f"--attach-run failed: {escape(str(e))}", "error")
            _rec("attach_run", "failed", str(e))
            raise typer.Exit(code=1)

    # The locations of a first ingest or a dry run, which no step above checked.
    _stop_on_run_tag_clash(project_config)

    # Open the monitoring ingestion record now that CLI_config is validated.
    # Best-effort: a monitoring outage must never affect the ingestion.
    if not dry_run and not scan_dry_run:
        try:
            _proj = locals().get("project_config")
            ingestion.CLI_config = CLI_config
            ingestion.project_config = _proj
            ingestion.run_id = api_monitoring_ingestion_start(
                CLI_config=CLI_config,
                command=command,
                project_name=getattr(_proj, "name", None),
                cli_version=_cli_version(),
                command_line=_redacted_command_line(),
                cli_config_path=str(CLI_config_path) if CLI_config_path else None,
                project_config_path=str(project_config_path) or None,
                data_root=str(data_root) if data_root else None,
                # "manual" for `ingest`, a person typing a command; `watch`
                # says what started its cycle.
                trigger=trigger,
                trigger_reason=trigger_reason,
            )
        except Exception:
            ingestion.run_id = None
        # Steps are sent as they start and end from now on, the ones recorded
        # before the record existed included, so the server sees the whole run.
        ingestion.go_live()
        if on_run_opened is not None:
            on_run_opened(ingestion.run_id)

    # Step 4: Sync project configuration to server
    if not skip_sync:
        rich_print_section_separator(
            f"Step 4/{total_steps}: Syncing project configuration to server"
        )
        ingestion.start("sync_project")
        try:
            if dry_run:
                rich_print_checked_statement(
                    f"Would create project '{escape(str(project_config.name))}' on the "
                    f"server{', or refresh it in place' if update_config else ''}",
                    "info",
                )
            else:
                project_config_dict = convert_model_to_dict(project_config)
                # Stamped here rather than at validation because this is the
                # single funnel every mode goes through: new project, update
                # and attach alike. Re-ingesting overwrites it on purpose, so
                # the report always describes how the data currently on the
                # project got there.
                project_config_dict["triggered_by"] = triggered_by
                # Provisioned (per-user) runs must stay private: templates
                # often ship `is_public: true` for showcase visibility, but
                # that would expose one user's project to everyone on the
                # instance — defeating the per-user separation --user is for.
                if user:
                    project_config_dict["is_public"] = False
                sync_verdict = api_sync_project_config_to_server(
                    CLI_config=CLI_config,
                    ProjectConfig=project_config_dict,
                    update=update_config,
                )
                # The project is already on the server and no update was asked
                # for: nothing can be ingested, so say so plainly and stop with
                # a distinct exit code instead of pretending the run succeeded.
                if sync_verdict.get("action") == "exists":
                    # A project file names no run directory of its own: what an
                    # attach adds is the locations it lists.
                    new_run = (
                        escape(data_root)
                        if data_root
                        else "the data locations this configuration lists"
                    )
                    rich_print_checked_statement(
                        f"Project '{escape(str(project_config.name))}' already exists on "
                        f"this server. Ingest again with --update-config to refresh it in "
                        f"place, or with --attach-run to add {new_run} as an additional run "
                        f"of that project.",
                        "error",
                    )
                    _rec("sync_project", "failed", "project exists, no --update-config")
                    raise typer.Exit(code=2)
                rich_print_checked_statement("Project configuration sync completed", "success")

            # Resolve tag-based link IDs now that the server has assigned real DC
            # IDs. A project file renamed with --project has its links
            # turned into tags too (see load_project_file).
            if (is_template_mode or project_name) and not dry_run:
                try:
                    from depictio.cli.cli.utils.api_calls import (
                        api_get_project_from_id,
                        api_update_project,
                    )

                    # Use name lookup first, fall back to ID-based fetch
                    remote = api_get_project_from_name(str(project_config.name), CLI_config)
                    if remote.status_code != 200:
                        # Name lookup may fail with special chars; try by scanning
                        # the project list or use the project_config's id if available
                        pid = getattr(project_config, "id", None)
                        if pid:
                            remote = api_get_project_from_id(pid, CLI_config)
                    if remote.status_code == 200:
                        proj_data = remote.json()
                        ingestion.project_id = (
                            str(proj_data.get("_id") or proj_data.get("id") or "")
                            or ingestion.project_id
                        )
                        tag_to_id: dict[str, str] = {}
                        for wf in proj_data.get("workflows", []):
                            for dc in wf.get("data_collections", []):
                                tag = dc.get("data_collection_tag")
                                dc_id = dc.get("_id")
                                if tag and dc_id:
                                    tag_to_id[tag] = str(dc_id)

                        links_updated = False
                        for link in proj_data.get("links", []):
                            for field, tag_field in [
                                ("source_dc_id", "source_dc_tag"),
                                ("target_dc_id", "target_dc_tag"),
                            ]:
                                tag = link.get(tag_field)
                                if (
                                    tag
                                    and tag in tag_to_id
                                    and str(link.get(field, "")).startswith("tag:")
                                ):
                                    link[field] = tag_to_id[tag]
                                    links_updated = True

                        if links_updated:
                            resp = api_update_project(proj_data, CLI_config)
                            rich_print_checked_statement(
                                f"Resolved link tags to DC IDs ({resp.status_code})", "success"
                            )
                        else:
                            rich_print_checked_statement(
                                "Links already have DC IDs (no tag: placeholders)", "info"
                            )
                except Exception as e:
                    logger.warning(f"Link tag resolution failed (non-blocking): {e}")

            success_count += 1
            _rec("sync_project", "success", "project synced")
        except typer.Exit:
            # Deliberate, already-reported exit (e.g. the "exists" verdict
            # above). `typer.Exit` subclasses RuntimeError, so without this
            # it would be caught below and re-reported as an empty failure.
            raise
        except Exception as e:
            rich_print_checked_statement(
                f"Project configuration sync failed: {escape(str(e))}", "error"
            )
            _rec("sync_project", "failed", str(e))
            if not continue_on_error:
                raise typer.Exit(code=1)
    else:
        rich_print_checked_statement("Skipping project configuration sync", "info")
        success_count += 1
        _rec("sync_project", "skipped")

    # What a dry run says steps 5 and 6 would touch.
    selected = [
        f"{kind} '{escape(value)}'"
        for kind, value in (
            ("workflow", workflow_name),
            ("data collection", data_collection_tag),
        )
        if value
    ]
    scope = f" ({', '.join(selected)} only)" if selected else ""

    # Step 5: Scan data files
    if not skip_scan:
        rich_print_section_separator(f"Step 5/{total_steps}: Scanning data files")
        ingestion.start("scan")
        try:
            if project_config is None:
                raise Exception("no validated project configuration, see the validation step above")
            if not dry_run:
                # Get remote project configuration to compare hashes
                remote_project_config = api_get_project_from_name(
                    str(project_config.name), CLI_config
                )

                if remote_project_config.status_code == 200:
                    # Compare hashes
                    remote_json = remote_project_config.json()
                    local_hash = project_config.hash
                    remote_hash = remote_json.get("hash", None)
                    ingestion.project_id = (
                        str(remote_json.get("_id") or remote_json.get("id") or "")
                        or ingestion.project_id
                    )
                    logger.info(f"Local & Remote hashes: {local_hash} & {remote_hash}")

                    if local_hash == remote_hash:
                        command_parameters = {
                            "rescan_folders": rescan_folders,
                            "sync_files": sync_files,
                            "sync_changed": sync_changed,
                            "legacy_scan_depth": legacy_scan_depth,
                            "dry_run": scan_dry_run,
                            "state_cache": state_cache,
                            "concurrency": concurrency,
                            "upload_chunk_size": upload_chunk_size,
                            "rich_tables": rich_tables,
                        }

                        # Use the unified scanning function
                        result = scan_project_files(
                            project_config=project_config,
                            CLI_config=CLI_config,
                            workflow_name=workflow_name,
                            data_collection_tag=data_collection_tag,
                            command_parameters=command_parameters,
                        )

                        if result["result"] != "success":
                            raise Exception("Data scanning failed")

                        # Which collections and runs moved. The process step
                        # below uses it to scope writes and, only when asked,
                        # to leave untouched collections alone.
                        scan_signal = result

                    else:
                        raise Exception("Local and remote project configurations do not match")
                else:
                    raise Exception("Failed to fetch remote project configuration")

            if dry_run:
                # The preview warns by itself when something would match nothing;
                # the line below is an info, not a green "completed".
                _print_dry_run_scan_preview(project_config)
            _step_done("Data scanning completed", f"Would scan the data files{scope}")
            success_count += 1
            _rec("scan", "success", "data files scanned")
        except Exception as e:
            rich_print_checked_statement(f"Data scanning failed: {escape(str(e))}", "error")
            _rec("scan", "failed", str(e))
            if not continue_on_error:
                raise typer.Exit(code=1)
    else:
        rich_print_checked_statement("Skipping data scanning", "info")
        success_count += 1
        _rec("scan", "skipped")

    # Step 6: Process data collections
    if not skip_process:
        rich_print_section_separator(f"Step 6/{total_steps}: Processing data collections")
        ingestion.start("process")
        image_uploads: list[dict] = []
        try:
            if not dry_run:
                # Get remote project configuration again for processing
                remote_project_config = api_get_project_from_name(
                    str(project_config.name), CLI_config
                )

                if remote_project_config.status_code == 200:
                    # Compare hashes
                    local_hash = project_config.hash
                    remote_hash = remote_project_config.json().get("hash", None)

                    if local_hash == remote_hash:
                        command_parameters = {
                            "overwrite": overwrite,
                            "write_mode": write_mode,
                            "rich_tables": rich_tables,
                            "preview_recipes": preview_recipes,
                            "streaming": streaming,
                            "project_id": str(project_config.id),
                            "ingestion_run_id": ingestion.run_id,
                            "trigger": trigger,
                            "async_upsert": async_upsert,
                            "repartition": repartition,
                            "scan_signal": scan_signal,
                            "incremental_write": incremental_write,
                            # Off for `ingest`: running it again is how someone
                            # rebuilds a project that drifted, so it must not
                            # quietly decide to do nothing.
                            "skip_unchanged": skip_unchanged,
                            "dry_run": scan_dry_run,
                        }

                        process_result = process_project_helper(
                            CLI_config=CLI_config,
                            project_config=project_config,
                            mode="process",
                            workflow_name=workflow_name,
                            data_collection_tag=data_collection_tag,
                            command_parameters=command_parameters,
                        )
                        # The scan marked every collection it registered files for
                        # as unsettled; those whose table is now written are not.
                        # A failed one keeps the mark, so the next scan cannot
                        # vouch for it and it is rebuilt in full.
                        if state_cache and not scan_dry_run and process_result:
                            settle_collections(
                                str(CLI_config.api_base_url),
                                str(project_config.id),
                                process_result.get("settled_dc_ids") or [],
                                project_hash=project_config.hash,
                            )
                        # Surface per-DC processing failures: a data collection
                        # that fails to process must not be reported as overall
                        # success (otherwise CI/automation can't detect it).
                        if process_result and process_result.get("total_failed", 0) > 0:
                            raise Exception(
                                f"{process_result['total_failed']} data collection(s) "
                                f"failed to process: "
                                f"{', '.join(process_result.get('failed_tags', []))}"
                            )
                        # After the tables, which say which images they reference.
                        # A refresh replaces the images too: one changed on disk
                        # under the same name used to be skipped as stored. A
                        # collection whose table was left as it was keeps its
                        # images as they are, and a dry run uploads none.
                        unchanged = set((process_result or {}).get("skipped_unchanged") or [])
                        for dc in image_collections_to_upload(
                            project_config,
                            workflow_name=workflow_name,
                            data_collection_tag=data_collection_tag,
                        ):
                            if scan_dry_run or dc.data_collection_tag in unchanged:
                                continue
                            image_uploads.append(
                                upload_collection_images(dc, CLI_config, overwrite=overwrite)
                            )
                    else:
                        raise Exception("Local and remote project configurations do not match")
                else:
                    raise Exception("Failed to fetch remote project configuration")

            _step_done("Data processing completed", f"Would process the data collections{scope}")
            success_count += 1
            _proc = locals().get("process_result") or {}
            _n_ok = _proc.get("total_processed")
            _rec(
                "process",
                "success",
                f"{_n_ok} data collection(s) processed"
                if _n_ok is not None
                else "data collections processed",
            )
            if image_uploads:
                _rec(
                    "images",
                    "success",
                    f"{sum(u['uploaded'] for u in image_uploads)} uploaded / "
                    f"{sum(u.get('replaced', 0) for u in image_uploads)} replaced / "
                    f"{sum(u['skipped'] for u in image_uploads)} already stored",
                )
        except Exception as e:
            rich_print_checked_statement(f"Data processing failed: {escape(str(e))}", "error")
            _rec("process", "failed", str(e))
            if not continue_on_error:
                raise typer.Exit(code=1)
    else:
        rich_print_checked_statement("Skipping data processing", "info")
        success_count += 1
        _rec("process", "skipped")

    # Step 7: Execute table joins
    if not skip_join:
        rich_print_section_separator(f"Step 7/{total_steps}: Executing table joins")
        ingestion.start("joins")
        try:
            if not dry_run and not scan_dry_run:
                # Check if project has joins defined
                if hasattr(project_config, "joins") and project_config.joins:
                    from depictio.cli.cli.utils.joins import process_project_joins

                    command_parameters = {
                        "overwrite": overwrite,
                        "rich_tables": rich_tables,
                    }

                    join_result = process_project_joins(
                        project=project_config,
                        CLI_config=CLI_config,
                        join_name=None,  # Process all joins
                        preview_only=False,
                        overwrite=overwrite,
                        auto_process_dependencies=True,
                    )

                    # Show summary
                    if join_result.get("processed"):
                        rich_print_checked_statement(
                            f"Processed {len(join_result['processed'])} join(s)", "success"
                        )
                    # "partial" is a failed join too: it used to be reported as
                    # a completed step, and the run exited 0.
                    if join_result.get("result") != "success":
                        failed_joins = [
                            str(err.get("join")) for err in join_result.get("errors") or []
                        ]
                        raise Exception(
                            f"{len(failed_joins)} join(s) failed: {', '.join(failed_joins)}"
                            if failed_joins
                            else join_result.get("message") or "no detail"
                        )
                    rich_print_checked_statement("Join execution completed", "success")
                else:
                    rich_print_checked_statement("No joins defined in project config", "info")
            elif project_config.joins:
                rich_print_checked_statement(
                    f"Would run {len(project_config.joins)} table join(s)", "info"
                )
            else:
                rich_print_checked_statement("No joins defined in project config", "info")

            success_count += 1
            _join = locals().get("join_result") or {}
            _n_join = len(_join.get("processed") or [])
            _n_join_err = len(_join.get("errors") or [])
            _rec(
                "joins",
                "success",
                f"{_n_join} processed / {_n_join_err} failed" if _join else "no joins defined",
            )
        except Exception as e:
            rich_print_checked_statement(f"Join execution failed: {escape(str(e))}", "error")
            _rec("joins", "failed", str(e))
            if not continue_on_error:
                raise typer.Exit(code=1)
    else:
        rich_print_checked_statement("Skipping join execution", "info")
        success_count += 1
        _rec("joins", "skipped")

    # Step 8: Import dashboards (from the template, or from --dashboard)
    if not skip_dashboard_import and template_dashboard_paths:
        rich_print_section_separator(f"Step {total_steps}/{total_steps}: Importing dashboards")
        ingestion.start("dashboard_import")
        if reset_dashboards:
            rich_print_checked_statement(
                "--reset-dashboards: each dashboard is imported over the one the project "
                "has, so the layout and components edited in the viewer are lost. The "
                "titles are kept.",
                "warning",
            )
        try:
            if not dry_run:
                from depictio.cli.cli.utils.templates import (
                    dashboard_outcome,
                    import_dashboards_from_template,
                )

                headers = generate_api_headers(CLI_config)
                api_url = str(CLI_config.api_base_url)

                # Resolve the project ID from the server
                project_id: str | None = None
                remote_project = api_get_project_from_name(str(project_config.name), CLI_config)
                if remote_project.status_code == 200:
                    remote_project_data = remote_project.json()
                    project_id = remote_project_data.get("_id") or remote_project_data.get("id")
                    ingestion.project_id = str(project_id or "") or ingestion.project_id

                results = import_dashboards_from_template(
                    dashboard_paths=template_dashboard_paths,
                    api_url=api_url,
                    headers=headers,
                    project_id=project_id,
                    reset=reset_dashboards,
                    variables=template_variables,
                    dashboard_name=dashboard_name,
                    # What each dashboard's source key is built from, so a
                    # refresh finds the dashboards this ingest made last time.
                    template_id=(
                        template_metadata.template_id if template_metadata is not None else None
                    ),
                    base_dir=Path(project_config_path).parent if project_config_path else None,
                )

                imported, failed = [], []
                for r in results:
                    (imported if r["success"] else failed).append(r)

                if user and imported and provisioned_dashboard_id is None:
                    provisioned_dashboard_id = imported[0].get("dashboard_id")

                for r in imported:
                    if r.get("dashboard_id"):
                        imported_dashboards.append(
                            (
                                str(r.get("title") or "dashboard"),
                                str(r["dashboard_id"]),
                                dashboard_outcome(r),
                            )
                        )
                    rich_print_checked_statement(
                        f"Dashboard {dashboard_outcome(r)}: "
                        f"{escape(str(r.get('title', 'unknown')))}",
                        "success",
                    )
                    if r.get("dash_url"):
                        rich_print_checked_statement(
                            f"  View at: {r['dash_url']}/dashboard/{r.get('dashboard_id')}",
                            "info",
                        )

                if any(r["status"] == "kept" for r in imported):
                    rich_print_checked_statement(
                        "Dashboards the project already had are kept as they are, edits "
                        "made in the viewer included; --reset-dashboards replaces them.",
                        "info",
                    )

                for r in failed:
                    rich_print_checked_statement(
                        f"Dashboard failed: {escape(Path(r['path']).name)} - "
                        f"{escape(str(r.get('error', 'unknown')))}",
                        "error",
                    )

                # Every dashboard was attempted already, so this only decides
                # the step's outcome: under --continue-on-error a failed
                # import used to be counted as a completed step, exit 0.
                if failed:
                    raise Exception(f"{len(failed)} dashboard(s) failed to import")

            if reset_dashboards:
                existing = " over those the project has"
            elif update_config:
                existing = ", keeping those the project already has"
            else:
                existing = ""
            _step_done(
                "Dashboard import completed",
                f"Would import {len(template_dashboard_paths)} dashboard(s){existing}",
            )
            success_count += 1
            # `imported` is only bound in the non-dry-run branch above, and a
            # failed import raised there, so none failed here.
            _imp = locals().get("imported") or []
            _counts = [f"{sum(r.get('status') == s for r in _imp)} {s}" for s in DASHBOARD_STATUSES]
            _rec("dashboard_import", "success", " / ".join(_counts) + " / 0 failed")
        except Exception as e:
            rich_print_checked_statement(f"Dashboard import failed: {escape(str(e))}", "error")
            _rec("dashboard_import", "failed", str(e))
            if not continue_on_error:
                raise typer.Exit(code=1)
    # The step is counted whenever a template or --dashboard is in play (see
    # total_steps), so every way past it counts it too. A --dashboard skipped
    # outside template mode used to count nothing: every step worked, and the
    # run still exited 1.
    elif skip_dashboard_import and (is_template_mode or template_dashboard_paths):
        rich_print_checked_statement("Skipping dashboard import (--skip dashboards)", "info")
        success_count += 1
        _rec("dashboard_import", "skipped")
    elif is_template_mode:
        rich_print_checked_statement("No dashboards defined in template", "info")
        success_count += 1
        _rec("dashboard_import", "skipped", "no dashboards in template")

    # Passwordless login link for the provisioned user. Minted now (not at
    # provisioning time) so the short-lived ticket's clock starts when the
    # link is handed out, not when a long pipeline began.
    if user and not dry_run and provisioned_dashboard_id:
        rich_print_section_separator("Passwordless login link")
        try:
            magic_config = load_depictio_config(yaml_config_path=CLI_config_path)
            magic = api_create_magic_link(magic_config)
            login_url = f"{magic['login_url']}&next=/dashboard/{provisioned_dashboard_id}"
            rich_print_checked_statement(f"One-time login link for {user}:", "info")
            rich_print_checked_statement(login_url, "success")
        except Exception as e:
            rich_print_checked_statement(f"Could not create login link: {e}", "warning")

    # Final summary
    rich_print_section_separator("Ingestion summary")

    # Where to go and look at what just happened. The ingestion is otherwise
    # a wall of green ticks that never says where the result landed, which
    # matters most for the pipeline trigger: nobody is watching that
    # terminal, they read it afterwards and need a link to click.
    viewer_url = None
    try:
        if dry_run:
            raise RuntimeError("a dry run does not contact the server")
        import httpx as _httpx

        # Re-read rather than reuse: CLI_config is only bound inside the
        # step that loaded it, and the summary runs even when that step was
        # skipped or failed.
        _base = load_depictio_config(yaml_config_path=CLI_config_path, quiet=True).api_base_url
        _status = _httpx.get(f"{_base}/depictio/api/v1/utils/status", timeout=5)
        if _status.status_code == 200:
            viewer_url = (_status.json().get("viewer_url") or "").rstrip("/") or None
    except Exception as e:
        # Best effort by design: a missing link must never fail a run that
        # otherwise worked, and an older server simply does not report it.
        logger.debug(f"Could not resolve the viewer URL: {e}")
    if viewer_url and ingestion.project_id:
        rich_print_checked_statement(
            f"Project: {viewer_url}/projects/{ingestion.project_id}", "info"
        )
    for dashboard_title, dashboard_id, dashboard_status in imported_dashboards:
        link = f": {viewer_url}/dashboard/{dashboard_id}" if viewer_url else ""
        rich_print_checked_statement(
            f"Dashboard '{escape(dashboard_title)}' {dashboard_status}{link}", "info"
        )

    if template_metadata is not None:
        # Resolved id, not the raw --template arg: "nf-core/ampliseq/latest"
        # would otherwise print unresolved, hiding which version actually ran.
        rich_print_checked_statement(
            f"Template used: {escape(str(template_metadata.template_id))}", "info"
        )
    if dry_run:
        rich_print_checked_statement(
            f"Dry run complete ({success_count}/{total_steps} steps): the configuration "
            f"is valid, and nothing was changed.",
            "success",
        )
    elif success_count == total_steps:
        rich_print_checked_statement(
            f"Ingestion completed successfully! ({success_count}/{total_steps} steps)",
            "success",
        )
    else:
        failed_steps = [s["name"] for s in ingestion.steps if s.get("status") == "failed"]
        rich_print_checked_statement(
            f"Ingestion completed with some issues ({success_count}/{total_steps} steps"
            + (f"; failed: {', '.join(failed_steps)}" if failed_steps else "")
            + ")",
            "warning",
        )

    # Close the monitoring ingestion record (best-effort; a no-op when it
    # was never opened). Sends the per-phase step ledger recorded by ``_rec``
    # throughout the run. The overall status rides on ``status`` (shown as
    # the header badge in the admin UI), so no separate summary row is needed.
    ingestion.close("success" if success_count == total_steps else "partial")

    return IngestOutcome(success_count=success_count, total_steps=total_steps)


def register_run_command(app: typer.Typer):
    """Register ``ingest`` and, out of the help, ``run``: its former name, which
    Nextflow hooks installed from older releases, CI and scripts still call."""

    def ingest(
        ctx: typer.Context,
        data_dir: Annotated[
            str | None,
            typer.Argument(
                metavar="DATA_DIR",
                help="Directory of the pipeline results to ingest. Without --template or "
                "--project-config-path, the template is detected from it. Formerly "
                "`--data-root`.",
                show_default=False,
            ),
        ] = None,
        # The essentials stay in the default panel, with --help.
        server: ServerOption = None,
        CLI_config_path: LegacyConfigPathOption = None,
        template: Annotated[
            str | None,
            typer.Option(
                "--template",
                help="Template to build the project from, e.g. nf-core/ampliseq/2.16.0, or "
                "nf-core/ampliseq/latest for the newest shipped version. Default: detected "
                "from DATA_DIR. Not with --project-config-path.",
            ),
        ] = None,
        manifest: Annotated[
            str | None,
            typer.Option(
                "--manifest",
                help="A data manifest, as an https:// URL or a local file, listing the files "
                "to ingest as {id, type, url[, run]} entries. In place of DATA_DIR, for a "
                "manifest-driven template such as generic/manifest-tables/1 (it sets the "
                "template's MANIFEST_URL variable).",
                rich_help_panel=PROJECT_PANEL,
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
        update_config: Annotated[
            bool,
            typer.Option(
                "--update-config",
                help="Refresh a project that exists: its configuration, and its tables with "
                "every run rescanned. Its runs become those of DATA_DIR (or of the project "
                "file's locations) and those added with --attach-run; the runs of any other "
                "location are removed. Its dashboards are kept as they are, edits made in "
                "the viewer included; the template's dashboards it lacks are added. A "
                "project not on the server yet is created.",
            ),
        ] = False,
        var: Annotated[
            list[str],
            typer.Option(
                "--var",
                help=(
                    "Extra template variable as KEY=VALUE. Repeatable. "
                    "Example: --var SAMPLESHEET_FILE=/path/to/samplesheet.csv "
                    "--var METADATA_FILE=/path/to/metadata.tsv"
                ),
            ),
        ] = [],
        dry_run: Annotated[
            bool,
            typer.Option(
                "--dry-run",
                help="Validate the project configuration locally and list the steps that "
                "would run, without contacting the server",
            ),
        ] = False,
        project: Annotated[
            str | None,
            typer.Option(
                "--project",
                help="Project name. Replaces the name the template gives, or the `name` in "
                "the --project-config-path file. --attach-run and --update-config find the "
                "project by it. Formerly `--project-name`.",
                rich_help_panel=PROJECT_PANEL,
            ),
        ] = None,
        attach_run: Annotated[
            bool,
            typer.Option(
                "--attach-run",
                help="Add DATA_DIR to an EXISTING project as one more run, instead of "
                "creating a project. The run is recorded as attached, so a later "
                "--update-config keeps it. The project is found by --project, else by the "
                "template's own name. Implies --update-config, dashboards included. The "
                "tables of file-based collections are rebuilt from all runs; collections a "
                "recipe computes still read the project's first run only.",
                rich_help_panel=PROJECT_PANEL,
            ),
        ] = False,
        drop_missing_runs: Annotated[
            bool,
            typer.Option(
                "--drop-missing-runs",
                help="On a refresh, remove the runs of a location added with --attach-run "
                "that is not on this host. Without it, such a refresh stops before "
                "changing anything.",
                rich_help_panel=PROJECT_PANEL,
            ),
        ] = False,
        provenance_file: Annotated[
            list[str] | None,
            typer.Option(
                "--provenance-file",
                help=(
                    "Extra provenance/recap file (json, yaml, or 2-column tsv of "
                    "key/value) whose entries are listed in the project's run-"
                    "provenance report under 'User provided'. Repeatable."
                ),
                rich_help_panel=PROJECT_PANEL,
            ),
        ] = None,
        bind: Annotated[
            list[str],
            typer.Option(
                "--bind",
                help=(
                    "Point one data collection at where its data actually is, as "
                    "TAG=LOCATION. Repeatable. The scan mode is inferred from the "
                    "location: a local directory or glob scans locally, a local file "
                    "is a single file, https:// is a remote file, an s3:// prefix or "
                    "glob is listed remotely. Example: "
                    "--bind samples=s3://my-bucket/run42/*.samples.csv"
                ),
                rich_help_panel=PROJECT_PANEL,
            ),
        ] = [],
        dashboard: Annotated[
            list[str] | None,
            typer.Option(
                "--dashboard",
                help="Dashboard YAML file to import instead of the template's own. Repeatable.",
                rich_help_panel=DASHBOARDS_PANEL,
            ),
        ] = None,
        dashboard_name: Annotated[
            str | None,
            typer.Option(
                "--dashboard-name",
                help="Title of the main dashboard. Without it, a new dashboard takes the "
                "title in its YAML and a refresh keeps the current one, even if renamed in "
                "the viewer. With it, a refresh renames the existing main dashboard and "
                "leaves its contents as they are. Child tabs keep their titles and stay "
                "attached.",
                rich_help_panel=DASHBOARDS_PANEL,
            ),
        ] = None,
        reset_dashboards: Annotated[
            bool,
            typer.Option(
                "--reset-dashboards",
                help="Import the template's dashboards (or --dashboard's) over the ones "
                "the project has: the layout and components edited in the viewer are lost, "
                "the titles are kept. Implies --update-config, as only a project that "
                "exists has dashboards to reset.",
                rich_help_panel=DASHBOARDS_PANEL,
            ),
        ] = False,
        workflow_name: Annotated[
            str | None,
            typer.Option(
                "--workflow-name",
                help="Scan and process only this workflow (its tag)",
                rich_help_panel=STEPS_PANEL,
            ),
        ] = None,
        data_collection_tag: Annotated[
            str | None,
            typer.Option(
                "--data-collection-tag",
                help="Scan and process only this data collection",
                rich_help_panel=STEPS_PANEL,
            ),
        ] = None,
        skip: Annotated[
            list[str] | None,
            typer.Option(
                "--skip",
                metavar="STEP",
                callback=parse_skip,
                help=f"Steps to skip, comma-separated or repeated: {', '.join(SKIP_STEPS)}. "
                "Skipping process skips the image upload too. Formerly the "
                "`--skip-<step>` flags.",
                rich_help_panel=STEPS_PANEL,
            ),
        ] = None,
        continue_on_error: Annotated[
            bool,
            typer.Option(
                "--continue-on-error",
                help="Continue execution even if a step fails",
                rich_help_panel=STEPS_PANEL,
            ),
        ] = False,
        pipeline_id: Annotated[
            str | None,
            typer.Option(
                "--pipeline-id",
                help=(
                    "The pipeline that produced the data, as '<name>/<version>' (e.g. "
                    "'nf-core/ampliseq/2.16.0'). Without --template or --project-config-path, "
                    "the bundled template that matches it is used; otherwise it is ignored. "
                    "Pipeline triggers fill it in, from a Nextflow pipeline's "
                    "workflow.manifest for instance."
                ),
                rich_help_panel=AUTOMATION_PANEL,
            ),
        ] = None,
        triggered_by: Annotated[
            str,
            typer.Option(
                "--triggered-by",
                help=(
                    "What invoked this ingestion, recorded on the project and shown in its "
                    "ingestion report. Defaults to 'manual'; a pipeline's completion trigger "
                    "passes its engine (e.g. 'nextflow') so an automated project is "
                    "distinguishable from one someone ingested by hand."
                ),
                rich_help_panel=AUTOMATION_PANEL,
            ),
        ] = "manual",
        user: Annotated[
            str | None,
            typer.Option(
                "--user",
                help=(
                    "Provision (create-or-get) this user's account and run the pipeline as "
                    "them, then emit a passwordless login link to their dashboard. "
                    "Requires --provisioning-key."
                ),
                rich_help_panel=AUTOMATION_PANEL,
            ),
        ] = None,
        provisioning_key: Annotated[
            str | None,
            typer.Option(
                "--provisioning-key",
                help=(
                    "Shared provisioning secret used with --user "
                    "(or set DEPICTIO_AUTH_PROVISIONING_API_KEY)."
                ),
                envvar="DEPICTIO_AUTH_PROVISIONING_API_KEY",
                rich_help_panel=AUTOMATION_PANEL,
            ),
        ] = None,
        sync_changed: Annotated[
            bool,
            typer.Option(
                "--sync-changed",
                help="Re-upload only the files whose size or modification time moved since "
                "the last scan. Narrower than --update-config, which re-uploads every file.",
                rich_help_panel=STEPS_PANEL,
            ),
        ] = False,
        write_mode: Annotated[
            str,
            typer.Option(
                "--write-mode",
                help="How step 6 writes a table. overwrite: rewrite it whole. replace-runs: "
                "partition it by run and rewrite only the runs in this batch, leaving the "
                "others untouched.",
                rich_help_panel=STEPS_PANEL,
            ),
        ] = "overwrite",
        incremental_write: Annotated[
            bool,
            typer.Option(
                "--incremental-write",
                help="With --write-mode replace-runs, rewrite only the runs that changed "
                "instead of rebuilding the whole table. Falls back to a full rebuild "
                "whenever that cannot be done safely (run removed, table not partitioned "
                "by run, column type changed).",
                rich_help_panel=STEPS_PANEL,
            ),
        ] = False,
        skip_unchanged: Annotated[
            bool,
            typer.Option(
                "--skip-unchanged",
                help="Leave a data collection's table untouched when the scan found no new, "
                "changed or removed file for it. Off by default, so that ingesting again "
                "always rebuilds a project that drifted.",
                rich_help_panel=STEPS_PANEL,
            ),
        ] = False,
        repartition: Annotated[
            bool,
            typer.Option(
                "--repartition",
                help="Let --write-mode replace-runs partition by run a table that is not "
                "yet. This rewrites every row, so it is never done implicitly, and never "
                "by the watcher.",
                rich_help_panel=STEPS_PANEL,
            ),
        ] = False,
        streaming: Annotated[
            bool,
            typer.Option(
                "--streaming",
                help=(
                    "Stream the Delta write instead of materialising the whole table in "
                    "memory (lower peak RSS on large ingests). Experimental; falls back "
                    "to the standard write on any failure."
                ),
                rich_help_panel=DEBUG_PANEL,
            ),
        ] = False,
        concurrency: Annotated[
            int,
            typer.Option(
                "--concurrency",
                min=1,
                help="Parallel HTTP requests for file uploads and cleanup deletes",
                rich_help_panel=DEBUG_PANEL,
            ),
        ] = 4,
        upload_chunk_size: Annotated[
            int,
            typer.Option(
                "--upload-chunk-size",
                min=1,
                help="Files per /files/upsert_batch request",
                rich_help_panel=DEBUG_PANEL,
            ),
        ] = 1000,
        state_cache: Annotated[
            bool,
            typer.Option(
                "--state-cache/--no-state-cache",
                help="Skip the runs whose file tree is unchanged since the last successful "
                "scan, from a local cache. Only applies when rescanning.",
                rich_help_panel=DEBUG_PANEL,
            ),
        ] = True,
        async_upsert: Annotated[
            bool,
            typer.Option(
                "--async-upsert",
                help="Ask the server to profile each written table in the background, and "
                "poll until it finishes, instead of holding one long request open. A server "
                "without offloading enabled ignores it and answers inline.",
                rich_help_panel=DEBUG_PANEL,
            ),
        ] = False,
        preview_recipes: Annotated[
            bool,
            typer.Option(
                "--preview-recipes",
                help="Show recipe input sources and transformed output before writing to "
                "Delta Lake",
                rich_help_panel=DEBUG_PANEL,
            ),
        ] = False,
        rich_tables: Annotated[
            bool,
            typer.Option(
                "--rich-tables",
                help="Show detailed summary of the workflow execution",
                rich_help_panel=DEBUG_PANEL,
            ),
        ] = False,
        # Out of the help, for the scripts, CI jobs and Nextflow hooks that call them.
        # The former names of DATA_DIR and --project.
        data_root: Annotated[str | None, typer.Option("--data-root", hidden=True)] = None,
        project_name: Annotated[str | None, typer.Option("--project-name", hidden=True)] = None,
        # What --skip <step> replaced.
        skip_server_check: Annotated[
            bool, typer.Option("--skip-server-check", hidden=True)
        ] = False,
        skip_s3_check: Annotated[bool, typer.Option("--skip-s3-check", hidden=True)] = False,
        skip_sync: Annotated[bool, typer.Option("--skip-sync", hidden=True)] = False,
        skip_scan: Annotated[bool, typer.Option("--skip-scan", hidden=True)] = False,
        skip_process: Annotated[bool, typer.Option("--skip-process", hidden=True)] = False,
        skip_join: Annotated[bool, typer.Option("--skip-join", hidden=True)] = False,
        skip_dashboard_import: Annotated[
            bool, typer.Option("--skip-dashboard-import", hidden=True)
        ] = False,
        # --update-config under another name, and two parts of what it does.
        overwrite: Annotated[bool, typer.Option("--overwrite", hidden=True)] = False,
        rescan_folders: Annotated[bool, typer.Option("--rescan-folders", hidden=True)] = False,
        sync_files: Annotated[bool, typer.Option("--sync-files", hidden=True)] = False,
        # Releases before 1.2.2 ignored each collection's scan max_depth/ignore.
        # A deprecated escape hatch, to be removed.
        legacy_scan_depth: Annotated[
            bool, typer.Option("--legacy-scan-depth", hidden=True)
        ] = False,
    ):
        """
        Ingest pipeline results into a Depictio server, from validation to dashboards.
        Formerly `run`.

        Runs these steps in order:
          1. Check that the server answers
          2. Check the S3 storage configuration
          3. Validate the project configuration (or resolve the template)
          4. Sync the project configuration to the server
          5. Scan the data files
          6. Process the data collections, uploading images where local_images_path is set
          7. Run the table joins the project configuration defines
          8. Import the dashboards the project lacks (from the template, or from --dashboard)

        Example, the template detected from the results directory:
          depictio ingest results/

        Refreshed after a new run, the dashboards kept as edited in the viewer:
          depictio ingest results/ --update-config

        A manifest-driven template, the files listed in a manifest instead of a directory:
          depictio ingest --template generic/manifest-tables/1 --manifest https://data.example.org/run42/manifest.json
        """
        note_if_called_as(ctx, "run", "ingest")
        # Usage errors first, before anything is printed.
        data_root = pick_renamed(
            data_dir, data_root, "DATA_DIR", "--data-root", described_as="the DATA_DIR argument"
        )
        project_name = pick_renamed(project, project_name, "--project", "--project-name")
        skipped = set(skip or [])
        for step, given in (
            ("server-check", skip_server_check),
            ("s3-check", skip_s3_check),
            ("sync", skip_sync),
            ("scan", skip_scan),
            ("process", skip_process),
            ("join", skip_join),
            ("dashboards", skip_dashboard_import),
        ):
            if given:
                note_renamed(SKIP_STEPS[step], f"--skip {step}")
                skipped.add(step)
        if reset_dashboards and "dashboards" in skipped:
            raise typer.BadParameter(
                "give --reset-dashboards or --skip dashboards, not both",
                param_hint="--reset-dashboards",
            )
        # A project file brings no dashboards of its own: the reset would reset
        # nothing, and still refresh the whole project.
        if reset_dashboards and project_config_path and not dashboard and not template:
            raise typer.BadParameter(
                "needs dashboards to reset, and a project file has none: pass --dashboard, "
                "or use --template",
                param_hint="--reset-dashboards",
            )
        if write_mode not in WRITE_MODES:
            raise typer.BadParameter(
                f"'{write_mode}' is not one of {', '.join(WRITE_MODES)}",
                param_hint="--write-mode",
            )
        # An attach scans incrementally, so it removes no run: the option would do nothing.
        if drop_missing_runs and attach_run:
            raise typer.BadParameter(
                "give --drop-missing-runs or --attach-run, not both: an attach removes no run",
                param_hint="--drop-missing-runs",
            )

        rich_print_command_usage("ingest")
        CLI_config_path = resolve_server(server, CLI_config_path)
        # Size the shared connection pool before the first request: it is created
        # lazily and honours this only on the first call.
        get_http_client(concurrency=concurrency)

        options = IngestOptions(
            data_root=data_root,
            CLI_config_path=CLI_config_path,
            template=template,
            project_config_path=project_config_path,
            project_name=project_name,
            manifest=manifest,
            bind=tuple(bind or ()),
            var=tuple(var),
            update_config=update_config,
            dry_run=dry_run,
            attach_run=attach_run,
            drop_missing_runs=drop_missing_runs,
            provenance_file=tuple(provenance_file or ()),
            dashboard=tuple(dashboard or ()),
            dashboard_name=dashboard_name,
            reset_dashboards=reset_dashboards,
            workflow_name=workflow_name,
            data_collection_tag=data_collection_tag,
            skip=frozenset(skipped),
            continue_on_error=continue_on_error,
            pipeline_id=pipeline_id,
            triggered_by=triggered_by,
            user=user,
            provisioning_key=provisioning_key,
            streaming=streaming,
            preview_recipes=preview_recipes,
            rich_tables=rich_tables,
            overwrite=overwrite,
            rescan_folders=rescan_folders,
            sync_files=sync_files,
            sync_changed=sync_changed,
            legacy_scan_depth=legacy_scan_depth,
            state_cache=state_cache,
            concurrency=concurrency,
            upload_chunk_size=upload_chunk_size,
            write_mode=write_mode,
            incremental_write=incremental_write,
            skip_unchanged=skip_unchanged,
            repartition=repartition,
            async_upsert=async_upsert,
        )
        try:
            with ProjectLock() as lock, ingestion_record() as record:
                outcome = run_ingest(replace(options, project_lock=lock), record)
        except ProjectLockError as exc:
            # Already said by run_ingest, which names the lock file and its holder.
            raise typer.Exit(code=exc.exit_code) from exc

        # A run that did not complete every step is a failure for automation
        # purposes: exit non-zero so CI can detect it (even under
        # --continue-on-error, which only suppresses the early aborts).
        if not outcome.ok:
            raise typer.Exit(code=1)

    app.command("ingest")(ingest)
    # Same command, same options: only its place in the help is gone, and it says
    # what it is called now. Its own help, as ingest's docstring says "Formerly
    # `run`", which read oddly under `run --help`.
    app.command(
        "run",
        hidden=True,
        help="Ingest pipeline results into a Depictio server. Old name of `ingest`, kept "
        "for compatibility: same options, same behaviour. See `depictio ingest --help`.",
    )(ingest)
