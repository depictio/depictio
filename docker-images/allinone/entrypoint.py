#!/usr/bin/env python3
"""Entrypoint of the depictio all-in-one image.

Runs the `depictio local up` stack (MongoDB, Redis, SeaweedFS, the API serving the
built viewer, the Celery worker) in the foreground on the local home mounted at
/data, and stops it in order on SIGTERM / SIGINT / SIGHUP.

It is a thin layer over depictio.cli.cli.local_stack, so a home made by
`depictio local up` (e.g. by the Nextflow module) opens with the exact same
passwords, keys, ports and environment. What it adds is what `local up` cannot do
yet (see README, "Changes to depictio"):

  * foreground supervision as PID 1's child, with ordered shutdown;
  * the native services read from a prefix baked into the image
    (DEPICTIO_SERVICES_PREFIX, default /opt/depictio-services), not <home>/env;
  * the API bound to DEPICTIO_BIND_HOST (0.0.0.0 under Docker, 127.0.0.1 under
    Apptainer, which shares the host network);
  * dropping root to the owner of /data, so files stay the user's.

Usage:  entrypoint.py [serve]          start and supervise the stack (default)
        entrypoint.py health           exit 0 when the API answers /health
        entrypoint.py <cmd> [args...]  exec any other command (e.g. depictio ...)
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
from pathlib import Path

HOME_DIR = Path(os.environ.get("DEPICTIO_LOCAL_HOME") or "/data")
SERVICES_PREFIX = Path(os.environ.get("DEPICTIO_SERVICES_PREFIX") or "/opt/depictio-services")
IN_APPTAINER = any(
    os.environ.get(v) for v in ("APPTAINER_CONTAINER", "SINGULARITY_CONTAINER", "APPTAINER_NAME")
)
# Seconds each tier gets after SIGTERM before SIGKILL. MongoDB gets the most: a
# clean shutdown checkpoints WiredTiger. Keep the sum under `docker stop -t`.
STOP_TIMEOUTS = {"app": 10.0, "store": 15.0, "mongo": 30.0}


def say(msg: str) -> None:
    print(f"[depictio-allinone] {msg}", flush=True)


def die(msg: str, code: int = 1) -> None:
    say(f"ERROR: {msg}")
    sys.exit(code)


# ---------------------------------------------------------------------------
# Identity: run as the owner of /data, with a writable HOME
# ---------------------------------------------------------------------------


def drop_root_to_data_owner() -> None:
    """As root (plain `docker run`), become the owner of the mounted home, as the
    official mongo/postgres images do: the data then stays owned by the user who
    produced it. Set DEPICTIO_ALLOW_ROOT=1 to keep running as root."""
    if os.geteuid() != 0 or os.environ.get("DEPICTIO_ALLOW_ROOT") == "1":
        return
    try:
        st = HOME_DIR.stat()
    except FileNotFoundError:
        return  # no mount: an anonymous folder, created as root below
    if st.st_uid == 0:
        return
    os.setgroups([])
    os.setgid(st.st_gid)
    os.setuid(st.st_uid)
    say(f"Running as uid {st.st_uid}:{st.st_gid}, the owner of {HOME_DIR}")


def ensure_writable_home_env() -> None:
    """An arbitrary uid (`-u`, Apptainer) may have no passwd entry and HOME=/:
    give Python, matplotlib and fontconfig a writable HOME outside the data."""
    home = os.environ.get("HOME", "")
    if home and home != "/" and os.access(home, os.W_OK):
        return
    fallback = Path(f"/tmp/depictio-home-{os.getuid()}")
    fallback.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.environ["HOME"] = str(fallback)
    os.environ.setdefault("XDG_CACHE_HOME", str(fallback / ".cache"))
    os.environ.setdefault("MPLCONFIGDIR", str(fallback / ".config" / "matplotlib"))


def check_home_dir() -> None:
    unusable = (
        f"{HOME_DIR} is not readable and writable by uid {os.getuid()}: mount it read-write "
        "and run as its owner (docker run -u $(id -u):$(id -g) ..., or apptainer run as that user)"
    )
    try:
        if not HOME_DIR.exists():
            return  # created by ensure_dirs (an anonymous folder: nothing kept)
        if not os.access(HOME_DIR, os.R_OK | os.W_OK | os.X_OK):
            die(unusable)
        # The usual mistake: mounting the pipeline's results folder instead of
        # results/depictio.
        marker = ".depictio-local-home"
        if (HOME_DIR / "depictio" / marker).is_file() and not (HOME_DIR / marker).is_file():
            die(f"{HOME_DIR} holds a depictio home in depictio/: mount that folder at {HOME_DIR}")
    except PermissionError:
        die(unusable)


# ---------------------------------------------------------------------------
# Glue over depictio.cli.cli.local_stack
# ---------------------------------------------------------------------------


def bind_host() -> str:
    return os.environ.get("DEPICTIO_BIND_HOST") or ("127.0.0.1" if IN_APPTAINER else "0.0.0.0")


def api_port_wanted() -> int | None:
    """DEPICTIO_PORT if set. Under Docker the port is fixed (8058, what -p publishes);
    under Apptainer, which shares the host's ports, None lets local_stack take the
    previous run's or a free one."""
    value = os.environ.get("DEPICTIO_PORT")
    if value:
        return int(value)
    return None if IN_APPTAINER else 8058


def patch_local_stack(ls, host: str) -> None:
    """Two seams `depictio local up` does not expose yet (README: Changes to depictio).

    * Paths.env -> the baked prefix, so nothing is downloaded into the user's data
      (a home from the pipeline may hold an env/ for another platform, or none).
    * the API's `--host 127.0.0.1` -> ``host``. Asserted, so a depictio release
      that changes the command fails loudly instead of silently binding loopback.
    """
    ls.Paths.env = property(lambda self: SERVICES_PREFIX)
    original_spawn = ls.spawn

    def spawn(paths, name, cmd, env=None):
        if name == "api" and host != "127.0.0.1":
            try:
                i = cmd.index("--host")
            except ValueError:
                raise ls.LocalStackError("local_stack's API command has no --host") from None
            if cmd[i + 1] != "127.0.0.1":
                raise ls.LocalStackError(f"unexpected API host {cmd[i + 1]!r} in local_stack")
            cmd = [*cmd[: i + 1], host, *cmd[i + 2 :]]
        if name == "s3":
            cmd = [*cmd, *seaweedfs_socket_flags(cmd)]
        return original_spawn(paths, name, cmd, env=env)

    ls.spawn = spawn


def seaweedfs_socket_flags(cmd: list[str]) -> list[str]:
    """Per-user names for the unix sockets weed puts in /tmp (it ignores TMPDIR).

    Under Apptainer without --contain, /tmp is the node's, shared by its users. A
    /tmp/seaweedfs-s3-9000.sock left by another user's SeaweedFS makes ours die at
    startup ("Failed to remove ... operation not permitted"; reproduced). Only the
    S3 and filer sockets can be named. weed saves these flags in s3/mini.options,
    so the names stay valid for a later `depictio local up` on the host.
    """
    port = next((a.split("=", 1)[1] for a in cmd if a.startswith("-s3.port=")), "9000")
    filer = next((a.split("=", 1)[1] for a in cmd if a.startswith("-filer.port=")), "8888")
    uid = os.getuid()
    return [
        f"-s3.localSocket=/tmp/seaweedfs-u{uid}-s3-{port}.sock",
        f"-filer.localSocket=/tmp/seaweedfs-u{uid}-filer-{filer}.sock",
    ]


def warn_on_mongo_series(home: Path) -> None:
    """Data written by MongoDB X.Y must be opened by X.Y (or X.Y+1 after a feature
    compatibility step). The home's own env/ records what wrote it, when present."""
    ours = theirs = None
    for prefix, slot in ((SERVICES_PREFIX, "ours"), (home / "env", "theirs")):
        for record in (prefix / "conda-meta").glob("mongodb-*.json"):
            try:
                meta = json.loads(record.read_text())
            except (OSError, ValueError):
                continue
            if meta.get("name") == "mongodb":
                if slot == "ours":
                    ours = meta["version"]
                else:
                    theirs = meta["version"]
    if ours and theirs and ours.split(".")[:2] != theirs.split(".")[:2]:
        say(
            f"WARNING: this data was written by MongoDB {theirs}, this image runs {ours}. "
            "MongoDB only opens data of its own series (or the previous one): use the image "
            "matching the depictio version the pipeline ran."
        )
    elif ours:
        say(f"MongoDB {ours}" + (f" (data written by {theirs})" if theirs else ""))
    else:
        say(f"WARNING: no readable mongodb record under {SERVICES_PREFIX}/conda-meta")


def serve() -> int:
    drop_root_to_data_owner()
    ensure_writable_home_env()
    check_home_dir()
    os.environ["DEPICTIO_LOCAL_HOME"] = str(HOME_DIR)

    from depictio.cli.cli import local_stack as ls

    host = bind_host()
    patch_local_stack(ls, host)
    paths = ls.Paths(HOME_DIR)
    if not paths.bin("mongod").exists():
        die(f"No mongod under {SERVICES_PREFIX}/bin: set DEPICTIO_SERVICES_PREFIX")

    try:
        fresh = not any((HOME_DIR / "mongo").glob("*"))
        ls.claim_home(paths)
        paths.ensure_dirs()
        # Held for the container's lifetime (`up` holds it during startup only), so
        # a second container or a host `depictio local up/wipe` on it fails fast.
        lock = ls.lock_for_startup(paths, "up")
    except (ls.LocalStackError, OSError) as exc:
        die(str(exc))
    say(f"{'New' if fresh else 'Existing'} depictio home at {HOME_DIR}")
    warn_on_mongo_series(HOME_DIR)

    try:
        seed = ls.parse_examples(os.environ.get("DEPICTIO_EXAMPLES") or "none")
        extra_roots = [r for r in os.environ.get("DEPICTIO_DATA_ROOTS", "").split(",") if r]
        data_roots = ls.local_data_roots(paths, extra_roots)
        ls.seed_screenshots(paths)
        try:
            ports = ls.pick_ports(api_port_wanted(), ls.load_ports(paths))
        except ls.LocalStackError as exc:
            raise ls.LocalStackError(str(exc).replace("--port", "another DEPICTIO_PORT")) from exc
        secret_values = ls.load_secrets(paths)  # generated on a new home
        env = ls.server_env(paths, ports, secret_values, seed, False, data_roots)
        env["DEPICTIO_TELEMETRY_DEPLOYMENT_KIND"] = "docker"
        # The API writes the CLI configuration (admin token) on a new home only; on
        # an existing one a missing file is written again through the API, and an
        # unparsable one is refused before anything starts, as `local up` does.
        rebuild = not fresh and not paths.cli_config.exists()
        if not fresh and not rebuild:
            ls.read_cli_config(paths)
    except ls.LocalStackError as exc:
        die(str(exc))

    state = ls.State(
        ports=ports,
        home=str(HOME_DIR),
        examples=seed,
        first_run=fresh,
        screenshots=False,
        data_roots=data_roots,
    )

    def record(name, proc):
        state.pids[name] = proc.pid
        state.start_times[name] = ls.process_start_time(proc.pid)
        state.save(paths)

    # Flag handlers first: _signals_interrupt restores them when startup ends, so
    # a signal between startup and supervise() cannot kill this process alone and
    # orphan the services.
    # Ctrl-C raises KeyboardInterrupt until the stack is up, as in `local up`.
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _on_signal)
    signal.signal(signal.SIGINT, signal.default_int_handler)

    procs: dict = {}
    say(f"Starting MongoDB, Redis, SeaweedFS, the API and the worker (logs in {paths.logs})")
    try:
        # SIGTERM/SIGHUP raise Interrupted here, so a `docker stop` during startup
        # still stops what was started (start_services cleans up on any error).
        with ls._signals_interrupt():
            procs = ls.start_services(paths, ports, secret_values, env, record=record)
            ls.wait_for_api(
                paths,
                ports,
                procs["api"],
                rebuild_from=secret_values if rebuild else None,
                warn=say,
            )
            ls.check_alive(paths, procs)
            signal.signal(signal.SIGINT, _on_signal)
    except BaseException as exc:  # noqa: BLE001 - includes Interrupted / KeyboardInterrupt
        stop(ls, procs)
        paths.state.unlink(missing_ok=True)
        if isinstance(exc, KeyboardInterrupt):
            say("Interrupted during startup: stopped")
            return 130
        tail_logs(paths)
        die(str(exc) if isinstance(exc, ls.LocalStackError) else repr(exc))

    url_port = os.environ.get("DEPICTIO_PUBLISHED_PORT") or str(ports["api"])
    say(f"Ready: http://localhost:{url_port}/dashboards  (API on {host}:{ports['api']})")
    if IN_APPTAINER and host == "127.0.0.1":
        say(f"From your laptop: ssh -L {ports['api']}:127.0.0.1:{ports['api']} <this node>")
    say("Stop with Ctrl-C" + ("" if IN_APPTAINER else " or `docker stop -t 60 <container>`"))

    return supervise(ls, paths, procs, lock)


_stopping = threading.Event()
_received: list[int] = []


def _on_signal(signum, _frame) -> None:
    if not _received:
        _received.append(signum)
    _stopping.set()


def supervise(ls, paths, procs, lock) -> int:
    code = 0
    while not _stopping.wait(1.0):
        dead = [n for n, p in procs.items() if p.poll() is not None]
        if dead:
            say(f"{', '.join(dead)} exited unexpectedly (see {paths.logs}): stopping")
            code = 1
            break
    if _received:
        say(f"{signal.Signals(_received[0]).name} received: stopping")
    # Ignore further signals, so a second Ctrl-C cannot cut the MongoDB shutdown short.
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, signal.SIG_IGN)
    stop(ls, procs)
    paths.state.unlink(missing_ok=True)
    lock.close()
    say("Stopped")
    return code


def stop(ls, procs: dict) -> None:
    """Worker and API first (they write to the stores), then S3 and Redis, MongoDB
    last. Each tier in parallel; every process group gets SIGTERM, then SIGKILL."""
    tiers = [("app", ["worker", "api"]), ("store", ["s3", "redis"]), ("mongo", ["mongo"])]
    for tier, names in tiers:
        threads = [
            threading.Thread(target=ls._stop_child, args=(procs[n], STOP_TIMEOUTS[tier]))
            for n in names
            if n in procs
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for n in names:
            if n in procs:
                say(f"{n} stopped (exit {procs[n].returncode})")


def tail_logs(paths, lines: int = 15) -> None:
    for name in ("mongo", "redis", "s3", "api", "worker"):
        log = paths.logs / f"{name}.log"
        if log.is_file():
            text = log.read_text(errors="replace").splitlines()[-lines:]
            say(f"--- last lines of {log} ---")
            print("\n".join(text), flush=True)


def health() -> int:
    """For HEALTHCHECK: the API port from state.json, else DEPICTIO_PORT / 8058."""
    import urllib.request

    port = api_port_wanted() or 8058
    try:
        port = json.loads((HOME_DIR / "state.json").read_text())["ports"]["api"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            ok = resp.status == 200 and json.load(resp).get("status") == "healthy"
    except Exception:  # noqa: BLE001
        ok = False
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    cmd = argv[1:] or ["serve"]
    if cmd == ["serve"]:
        return serve()
    if cmd == ["health"]:
        return health()
    os.execvp(cmd[0], cmd)
    return 127


if __name__ == "__main__":
    sys.exit(main(sys.argv))
