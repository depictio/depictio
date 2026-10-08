"""Container-free Depictio stack: the same API, worker and viewer as the Docker
deployment, with MongoDB, Redis and SeaweedFS (the S3 store) run as plain processes.

The native binaries come from conda-forge, installed once into
``<home>/env`` with py-rattler (the library pixi is built on), so nothing has to
be installed by hand and the binaries do not depend on the Linux distribution.
Only configuration differs from the Docker profile: every service is pointed at
127.0.0.1 through the regular ``DEPICTIO_*`` environment variables.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import TextIO

from depictio.cli.cli_logging import logger

# The major series of the images in docker-compose.yaml (mongo, redis,
# chrislusf/seaweedfs): move them together. Redis and SeaweedFS are pinned to the
# major only: a pin below what an existing local home already runs would
# downgrade it, and Redis cannot load an RDB written by a newer version.
# `depictio local export` pins the SeaweedFS image to the local version, so a
# hand-over never downgrades either.
CONDA_SPECS = ["mongodb 8.0.*", "redis-server 8.*", "seaweedfs 4.*"]
ADMIN_EMAIL = "admin@example.com"
# --force replaces the `depictio` and `depictio-cli` commands that `uv tool install
# depictio-cli` (the alias package) installed, which uv would otherwise refuse to do.
INSTALL_LOCAL = 'uv tool install --force "depictio[local]"'
S3_USER = "depictio"
S3_BUCKET = "depictio-bucket"

DEFAULT_PORTS = {"api": 8058, "mongo": 27018, "redis": 6379, "s3": 9000}
# weed mini's internal listeners and their default ports. Not kept across runs: its
# volume server and filer register with the master again at each start.
SEAWEEDFS_PORTS = {
    "master.port": 9333,
    "master.port.grpc": 19333,
    "volume.port": 9340,
    "volume.port.grpc": 19340,
    "filer.port": 8888,
    "filer.port.grpc": 18888,
    "admin.port": 23646,
    "admin.port.grpc": 33646,
    "s3.port.grpc": 18333,
}
# Start order; stopped in reverse.
PROCESS_ORDER = ["mongo", "redis", "s3", "api", "worker"]
# The example projects shipped in the wheel, seeded by --examples, with their Delta
# tables from STATIC_IDS in depictio/api/v1/db_init_reference_datasets.py: copied,
# because importing that module needs the server's settings. A test keeps the two
# in sync.
EXAMPLE_TABLES = {
    "iris": ("646b0f3c1e4a2d7f8e5b8c9c",),
    "penguins": (
        "646b0f3c1e4a2d7f8e5b8c9f",
        "646b0f3c1e4a2d7f8e5b8ca0",
        "646b0f3c1e4a2d7f8e5b8ca1",
    ),
}
EXAMPLES = tuple(EXAMPLE_TABLES)
# The data directories under the local home: created by `up`, deleted by `wipe`,
# which keeps env/ (the downloaded binaries).
DATA_DIRS = (
    "logs",
    "mongo",
    "redis",
    "s3",
    "keys",
    "cli",
    "cache",
    "multiqc_prerender",
    "screenshots",
    "backups",
)
# Written by `up` into the folder it makes a local home: `wipe` deletes nothing,
# and `up` changes the mode of nothing, in a folder without it.
HOME_MARKER = ".depictio-local-home"
# Held by `up` while it starts the server, and by `wipe` and `export` while they stop
# it, so a second command on the home fails fast. Named before those two took it.
UP_LOCK = ".up.lock"


class LocalStackError(RuntimeError):
    pass


class StateUnreadable(LocalStackError):
    """state.json cannot be read: `down` and `wipe` then find the processes another way."""


def check_platform_supported() -> None:
    """Linux and macOS, x86_64 or arm64: the platforms conda-forge builds all three
    services for, and the ones where the process-group handling below works."""
    if sys.platform == "win32":
        raise LocalStackError(
            "depictio local is not supported on Windows: conda-forge has no redis-server "
            "build for it and the services are managed as POSIX process groups. "
            "Use WSL2, or the Docker compose stack."
        )


def local_home_env_is_blank() -> bool:
    """Whether DEPICTIO_LOCAL_HOME is set but empty, which `depictio local` refuses
    rather than take for the current folder."""
    value = os.environ.get("DEPICTIO_LOCAL_HOME")
    return value is not None and not value.strip()


def local_home() -> Path:
    """The local home, absolute: the services start in it, so a relative path would
    be resolved a second time against itself. An empty DEPICTIO_LOCAL_HOME counts
    as unset here; the `depictio local` commands refuse it first."""
    value = os.environ.get("DEPICTIO_LOCAL_HOME", "").strip()
    home = Path(value or "~/.depictio/local").expanduser().resolve()
    logger.debug("Local home: %s (%s)", home, "DEPICTIO_LOCAL_HOME" if value else "default")
    return home


@dataclass
class Paths:
    home: Path

    @property
    def env(self) -> Path:
        return self.home / "env"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def state(self) -> Path:
        return self.home / "state.json"

    @property
    def secrets(self) -> Path:
        return self.home / "secrets.json"

    @property
    def ports(self) -> Path:
        return self.home / "ports.json"

    @property
    def cli_config(self) -> Path:
        return self.home / "cli" / f"{ADMIN_EMAIL.split('@')[0]}_config.yaml"

    @property
    def marker(self) -> Path:
        return self.home / HOME_MARKER

    def bin(self, name: str) -> Path:
        return self.env / "bin" / name

    def ensure_dirs(self) -> None:
        """Create the data directories. Only for a home that claim_home accepted."""
        # Owner-only: keys/ holds the token signing keys and cli/ the admin token and
        # S3 secret, which the API writes with the default umask (world-readable).
        for private in (self.home, self.home / "keys", self.home / "cli"):
            private.mkdir(parents=True, exist_ok=True)
            private.chmod(0o700)
        for sub in DATA_DIRS:
            (self.home / sub).mkdir(parents=True, exist_ok=True)
        logger.debug("Data directories under %s: %s", self.home, ", ".join(DATA_DIRS))

    def has_data(self) -> bool:
        """Whether anything `wipe` deletes is there."""
        return any((self.home / sub).exists() for sub in DATA_DIRS) or any(
            f.exists() for f in (self.state, self.secrets, self.ports)
        )


def is_local_home(home: Path) -> bool:
    """Whether ``home`` is a Depictio local home: it holds the marker `up` writes or,
    made before the marker, what `up` leaves there."""
    if (home / HOME_MARKER).is_file():
        return True
    recorded = any((home / name).is_file() for name in ("state.json", "ports.json"))
    # Every data directory `up` created before the backups one, as after a first
    # run that failed early.
    created = all((home / sub).is_dir() for sub in DATA_DIRS if sub != "backups")
    if created or (
        recorded and all((home / sub).is_dir() for sub in ("keys", "cli", "mongo", "logs"))
    ):
        logger.debug("%s has no %s but the layout of a local home", home, HOME_MARKER)
        return True
    # Wiped before the marker existed: only the downloaded binaries are left.
    try:
        specs = json.loads((home / "env" / ".depictio-specs.json").read_text())
    except (OSError, ValueError):
        return False
    return isinstance(specs, dict) and "specs" in specs


def claim_home(paths: Paths) -> None:
    """Make ``paths.home`` a local home before `up` writes to it: a new or empty
    folder becomes one, a folder holding anything else is refused."""
    home = paths.home
    if home.exists() and not home.is_dir():
        raise LocalStackError(
            f"DEPICTIO_LOCAL_HOME names {home}, which is a file: point it at a folder"
        )
    # Finder drops a .DS_Store into any folder it shows.
    content = [p.name for p in home.iterdir() if p.name != ".DS_Store"] if home.is_dir() else []
    if content and not is_local_home(home):
        raise LocalStackError(
            f"{home} is not empty and is not a Depictio local home (it has no {HOME_MARKER}): "
            "point DEPICTIO_LOCAL_HOME at a new or empty folder"
        )
    home.mkdir(parents=True, exist_ok=True)
    if not paths.marker.exists():
        paths.marker.write_text(
            "A Depictio local home, made by `depictio local up`. "
            "`depictio local wipe` deletes its data.\n"
        )
        logger.debug("Wrote %s", paths.marker)


# ---------------------------------------------------------------------------
# Native binaries (conda-forge via py-rattler)
# ---------------------------------------------------------------------------


def ensure_binaries(paths: Paths, log=print) -> None:
    try:
        from rattler import Platform, VirtualPackage, install, solve
    except ImportError as exc:
        raise LocalStackError(
            "py-rattler is required to fetch MongoDB, Redis and SeaweedFS. "
            f"Install the local extra: {INSTALL_LOCAL}"
        ) from exc

    # The platform is part of the marker: a $HOME shared between linux-64 and
    # linux-aarch64 hosts, or a Python switched between Rosetta and native on a
    # Mac, must not reuse binaries built for the other architecture.
    wanted = {"specs": CONDA_SPECS, "platform": str(Platform.current())}
    marker = paths.env / ".depictio-specs.json"
    if not marker.exists():
        logger.debug("No native binaries recorded in %s: installing %s", marker, wanted)
    else:
        found = json.loads(marker.read_text())
        if found == wanted:
            logger.debug("Native binaries in %s are current: %s", paths.env, wanted)
            return
        logger.debug(
            "Native binaries in %s are %s, wanted %s: reinstalling", paths.env, found, wanted
        )
    if paths.env.exists():
        logger.debug("Deleting %s", paths.env)
        shutil.rmtree(paths.env)

    async def _install() -> None:
        records = await solve(
            sources=["conda-forge"],
            specs=CONDA_SPECS,
            virtual_packages=VirtualPackage.detect(),
        )
        logger.debug(
            "Solved %d packages: %s",
            len(records),
            ", ".join(f"{r.name.normalized} {r.version}" for r in records),
        )
        await install(records=records, target_prefix=str(paths.env), show_progress=False)

    log(
        f"Installing {', '.join(CONDA_SPECS)} for {wanted['platform']} from conda-forge "
        f"into {paths.env} (first run only)"
    )
    start = time.monotonic()
    try:
        asyncio.run(_install())
    except Exception as exc:
        logger.debug("Solving or installing the native binaries failed", exc_info=True)
        # Without the marker, the next run starts the download over.
        raise LocalStackError(
            f"Could not download MongoDB, Redis and SeaweedFS from conda-forge: {exc}. "
            "Check your network or proxy."
        ) from exc
    marker.write_text(json.dumps(wanted))
    log(f"Native services installed in {time.monotonic() - start:.0f}s")


# ---------------------------------------------------------------------------
# State, ports, secrets
# ---------------------------------------------------------------------------


@dataclass
class State:
    """What `up` records in state.json, for `down`, `status` and the next `up`."""

    ports: dict[str, int] = field(default_factory=dict)
    home: str = ""
    examples: str = ""
    # Started on an empty database, so the examples are being seeded; cleared once
    # they are loaded.
    first_run: bool = False
    # Whether the server renders dashboard thumbnails; None in older files.
    screenshots: bool | None = None
    pids: dict[str, int] = field(default_factory=dict)
    # Start time of each process, so a PID reused after a reboot is not taken for ours.
    start_times: dict[str, float | None] = field(default_factory=dict)

    @property
    def api_port(self) -> int:
        return self.ports.get("api", DEFAULT_PORTS["api"])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @classmethod
    def load(cls, paths: Paths) -> State | None:
        """The state of the last `up`, or None when nothing is recorded.

        Files written by earlier versions load too: a missing key takes its
        default, and url is derived from the ports rather than read. Raises
        StateUnreadable for a file that is not one `up` wrote.
        """
        if not paths.state.exists():
            logger.debug("No %s: nothing recorded", paths.state)
            return None
        try:
            saved = _read_json_object(paths.state)
            known = {f.name for f in fields(cls)}
            state = cls(**{k: v for k, v in saved.items() if k in known})
            for name in ("ports", "pids"):
                value = getattr(state, name)
                if not isinstance(value, dict) or not all(
                    isinstance(v, int) for v in value.values()
                ):
                    raise ValueError(f"{name} is not a map of numbers")
            if not isinstance(state.start_times, dict):
                raise ValueError("start_times is not a map")
            if not isinstance(state.examples, str):
                raise ValueError("examples is not text")
        except (OSError, ValueError) as exc:
            raise StateUnreadable(
                f"{paths.state} is unreadable ({_file_error(exc)}). depictio local down "
                "stops the server without it, then depictio local up starts it again"
            ) from exc
        state.home = state.home or str(paths.home)
        logger.debug("Loaded %s: %s", paths.state, state)
        return state

    def save(self, paths: Paths) -> None:
        # url is written too, for anything reading the file without this class.
        write_file_atomic(paths.state, json.dumps({**asdict(self), "url": self.url}, indent=2))
        logger.debug("Saved %s: ports %s, pids %s", paths.state, self.ports, self.pids)


def _file_error(exc: BaseException) -> str:
    """Why a file could not be read, without quoting its content (it may hold secrets)."""
    if isinstance(exc, json.JSONDecodeError):
        return f"not valid JSON: {exc.msg} at line {exc.lineno}"
    if isinstance(exc, UnicodeDecodeError):
        return "not text"
    if isinstance(exc, OSError):
        return exc.strerror or type(exc).__name__
    return str(exc) or type(exc).__name__


def _read_json_object(path: Path) -> dict:
    """The JSON object in ``path``; OSError or ValueError (for _file_error) otherwise."""
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("not a JSON object")
    return value


def write_private_file(path: Path, text: str) -> None:
    """Write ``text`` to ``path``. A new file is created owner-only rather than
    chmod-ed afterwards, so it is never readable by others."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)


def write_file_atomic(path: Path, text: str, mode: int | None = None) -> None:
    """Write ``text`` to ``path`` through a file renamed over it, so a reader, or an
    interrupted write, never leaves half a file. ``mode`` defaults to the file's
    current one, else the umask's."""
    if mode is None:
        with contextlib.suppress(FileNotFoundError):
            mode = path.stat().st_mode & 0o777
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if mode is None else mode)
    try:
        with os.fdopen(fd, "w") as fh:
            if mode is not None:
                # Exact, whatever the umask.
                os.fchmod(fh.fileno(), mode)
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def load_secrets(paths: Paths, create: bool = True) -> dict:
    """The passwords this home was created with, generated on its first run."""
    # The file name only: its content is never logged.
    if paths.secrets.exists():
        logger.debug("Reading the passwords from %s", paths.secrets)
        try:
            values = _read_json_object(paths.secrets)
            missing = [k for k in ("s3_password", "admin_password") if not values.get(k)]
            if missing:
                raise ValueError(f"no {' or '.join(missing)}")
        except (OSError, ValueError) as exc:
            raise LocalStackError(
                f"{paths.secrets} is unreadable ({_file_error(exc)}). It holds the passwords "
                "this local home was created with: restore it from a copy, or start over "
                "with depictio local wipe, which deletes the data"
            ) from exc
        return values
    if not create:
        raise LocalStackError(
            f"{paths.secrets} is missing: it holds the passwords this local home was created with"
        )
    values = {
        "s3_password": secrets.token_urlsafe(24),
        "admin_password": secrets.token_urlsafe(24),
    }
    write_file_atomic(paths.secrets, json.dumps(values), mode=0o600)
    logger.debug("Generated new passwords in %s", paths.secrets)
    return values


def port_is_free(port: int) -> bool:
    # On macOS/BSD the bind below succeeds next to a listener on 0.0.0.0 (e.g. a
    # port published by the Docker dev stack), so check for a listener first.
    if tcp_ready(port):
        logger.debug("Port %d: another program is listening on it", port)
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # Same option the servers set, so a port left in TIME_WAIT by the previous
        # run still counts as free.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as exc:
            logger.debug("Port %d: cannot bind it (%s)", port, _probe_error(exc))
            return False
    return True


def pick_port(preferred: int, taken: set[int]) -> int:
    if preferred in taken:
        logger.debug("Port %d already goes to another service of this run", preferred)
    elif port_is_free(preferred):
        return preferred
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port not in taken:
            logger.debug("Port %d is not available: using %d instead", preferred, port)
            return port


def pick_ports(api_port: int | None, saved: dict[str, int] | None = None) -> dict[str, int]:
    """Ports for this run: --port, else the previous run's, else the defaults.

    Reusing the previous ports keeps the URL stable. One that another program has
    taken since is replaced by a free one, so `up` never stops on it.
    """
    preferred = {**DEFAULT_PORTS, **(saved or {})}
    ports: dict[str, int] = {}
    for name in DEFAULT_PORTS:
        if name == "api" and api_port:
            if not port_is_free(api_port):
                raise LocalStackError(f"Port {api_port} is already in use: choose another --port")
            ports[name] = api_port
        else:
            ports[name] = pick_port(preferred[name], set(ports.values()))
    logger.info("Ports for this run: %s", ports)
    return ports


def seaweedfs_port_flags(taken: set[int]) -> list[str]:
    """`weed mini` flags for its internal ports, each one free now and not in `taken`.

    Left to itself, weed mini moves off a taken default port, but next to a second
    weed mini (another local home, a dev stack) that search races with its own
    binds and stops it at startup.
    """
    taken = set(taken)
    flags = []
    for flag, preferred in SEAWEEDFS_PORTS.items():
        port = pick_port(preferred, taken)
        taken.add(port)
        flags.append(f"-{flag}={port}")
    return flags


def load_ports(paths: Paths) -> dict[str, int]:
    """The ports of the previous run, kept across `down` (unlike state.json)."""
    if not paths.ports.exists():
        logger.debug("No %s: preferring the default ports %s", paths.ports, DEFAULT_PORTS)
        return {}
    try:
        saved = _read_json_object(paths.ports)
    except (OSError, ValueError) as exc:
        raise LocalStackError(
            f"{paths.ports} is unreadable ({_file_error(exc)}). Delete it: depictio local up "
            "then picks the default ports again"
        ) from exc
    ports = {k: v for k, v in saved.items() if k in DEFAULT_PORTS and isinstance(v, int)}
    logger.debug("Previous run's ports, from %s: %s", paths.ports, ports)
    return ports


def save_ports(paths: Paths, ports: dict[str, int]) -> None:
    write_file_atomic(paths.ports, json.dumps(ports, indent=2))
    logger.debug("Saved %s: %s", paths.ports, ports)


def parse_examples(value: str | None) -> str:
    """--examples as DEPICTIO_SEED_PROJECTS takes it, or 'none'; every example by default."""
    if value is None:
        return ",".join(EXAMPLES)
    names = [name.strip().lower() for name in value.split(",") if name.strip()]
    if names == ["none"]:
        return "none"
    if not names or not set(names) <= set(EXAMPLES):
        raise LocalStackError(
            f"--examples {value!r} is not valid: use iris, penguins, iris,penguins or none"
        )
    return ",".join(dict.fromkeys(names))


# ---------------------------------------------------------------------------
# Environment shared by the API and the worker
# ---------------------------------------------------------------------------


def inherited_env() -> dict[str, str]:
    """This process's environment for the services, without its AWS_* settings.

    The local S3 store is the server's own, with its credentials in DEPICTIO_S3_*: a
    session token, profile, region or endpoint from the user's shell makes boto3 and
    deltalake sign for, or look up, another account.
    """
    dropped = sorted(k for k in os.environ if k.startswith("AWS_"))
    if dropped:
        # Names only: these hold credentials.
        _debug_on_change("aws", f"Not passed to the local services: {', '.join(dropped)}")
    return {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}


def server_env(
    paths: Paths, ports: dict[str, int], secret_values: dict, seed: str, screenshots: bool
) -> dict:
    host = "127.0.0.1"
    # Inherited DEPICTIO_* settings target another instance, except the telemetry
    # opt-out (DEPICTIO_TELEMETRY_ENABLED=false), which must reach this one too.
    env = {
        k: v
        for k, v in inherited_env().items()
        if not k.startswith("DEPICTIO_") or k.startswith("DEPICTIO_TELEMETRY_")
    }
    env.update(
        {
            "DEPICTIO_CONTEXT": "server",
            "DEPICTIO_DEV_MODE": "false",
            "DEPICTIO_AUTH_SINGLE_USER_MODE": "true",
            "DEPICTIO_AUTH_KEYS_DIR": str(paths.home / "keys"),
            "DEPICTIO_KEYS_DIR": str(paths.home / "keys"),
            "DEPICTIO_AUTH_CLI_CONFIG_DIR": str(paths.home / "cli"),
            "DEPICTIO_BOOTSTRAP_ADMIN_EMAIL": ADMIN_EMAIL,
            "DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD": secret_values["admin_password"],
            "DEPICTIO_MONGODB_SERVICE_NAME": host,
            "DEPICTIO_MONGODB_SERVICE_PORT": str(ports["mongo"]),
            "DEPICTIO_MONGODB_EXTERNAL_PORT": str(ports["mongo"]),
            "DEPICTIO_S3_SERVICE_NAME": host,
            "DEPICTIO_S3_SERVICE_PORT": str(ports["s3"]),
            "DEPICTIO_S3_EXTERNAL_HOST": host,
            "DEPICTIO_S3_EXTERNAL_PORT": str(ports["s3"]),
            "DEPICTIO_S3_ROOT_USER": S3_USER,
            "DEPICTIO_S3_ROOT_PASSWORD": secret_values["s3_password"],
            "DEPICTIO_S3_BUCKET": S3_BUCKET,
            "DEPICTIO_CACHE_REDIS_HOST": host,
            "DEPICTIO_CACHE_REDIS_PORT": str(ports["redis"]),
            "DEPICTIO_CELERY_BROKER_HOST": host,
            "DEPICTIO_CELERY_BROKER_PORT": str(ports["redis"]),
            "DEPICTIO_CELERY_RESULT_BACKEND_HOST": host,
            "DEPICTIO_CELERY_RESULT_BACKEND_PORT": str(ports["redis"]),
            "DEPICTIO_EVENTS_REDIS_HOST": host,
            "DEPICTIO_EVENTS_REDIS_PORT": str(ports["redis"]),
            "DEPICTIO_FASTAPI_HOST": host,
            "DEPICTIO_FASTAPI_SERVICE_NAME": host,
            "DEPICTIO_FASTAPI_SERVICE_PORT": str(ports["api"]),
            "DEPICTIO_FASTAPI_EXTERNAL_HOST": host,
            "DEPICTIO_FASTAPI_EXTERNAL_PORT": str(ports["api"]),
            # The built viewer is served by FastAPI itself, on the API port.
            "DEPICTIO_VIEWER_SERVICE_NAME": host,
            "DEPICTIO_VIEWER_SERVICE_PORT": str(ports["api"]),
            "DEPICTIO_VIEWER_EXTERNAL_HOST": host,
            "DEPICTIO_VIEWER_EXTERNAL_PORT": str(ports["api"]),
            "DEPICTIO_S3_CACHE_DIR": str(paths.home / "cache" / "s3_files"),
            "DEPICTIO_DELTA_CACHE_DIR": str(paths.home / "cache" / "delta_cache"),
            "DEPICTIO_MULTIQC_PRERENDER_DIR": str(paths.home / "multiqc_prerender"),
            "DEPICTIO_TELEMETRY_DEPLOYMENT_KIND": "local",
            "DEPICTIO_PERFORMANCE_SCREENSHOTS_ENABLED": str(screenshots).lower(),
            # Startup prunes thumbnails of dashboards absent from the database, so they
            # must not live inside the installed package.
            "DEPICTIO_PERFORMANCE_SCREENSHOTS_DIR": str(paths.home / "screenshots"),
            # Backups go to <base dir>/backups, by default inside the installed package,
            # where every local home would share them and `wipe` would miss them.
            "DEPICTIO_BACKUP_BASE_DIR": str(paths.home),
        }
    )
    if seed == "none":
        env["DEPICTIO_DISABLE_EXAMPLE_DASHBOARDS"] = "true"
    else:
        env["DEPICTIO_SEED_PROJECTS"] = seed
    return bypass_proxy_for_loopback(env)


def bypass_proxy_for_loopback(env: dict[str, str]) -> dict[str, str]:
    """``env`` with 127.0.0.1 and localhost added to no_proxy and NO_PROXY.

    boto3 and httpx send through a proxy set in the environment, and a usual
    no_proxy=localhost does not cover 127.0.0.1, where every local service listens.
    Both variables get the entries of either: a tool reading only one of them must
    not lose what the other held.
    """
    entries = [
        entry.strip()
        for value in (env.get("no_proxy"), env.get("NO_PROXY"))
        for entry in (value or "").split(",")
        if entry.strip()
    ]
    merged = ",".join(dict.fromkeys([*entries, "127.0.0.1", "localhost"]))
    env["no_proxy"] = env["NO_PROXY"] = merged
    return env


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    # A child of this process (`up` stopping what it just started) stays visible as a
    # zombie until reaped, so reap it here; for any other process this is a no-op.
    with contextlib.suppress(ChildProcessError):
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def process_start_time(pid: int) -> float | None:
    """When ``pid`` started, or None without psutil (a server dependency) or once it is gone."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        return psutil.Process(pid).create_time()
    except psutil.Error:
        return None


# Slack for a recorded start time: psutil derives it from the boot time on Linux,
# which a clock step can shift. A PID reused after a reboot is off by far more.
_START_TIME_SLACK = 5.0


def live_pids(state: State | None) -> dict[str, int]:
    """The recorded PIDs that still belong to the processes `up` started.

    state.json survives a reboot, after which a PID can name an unrelated process:
    one whose start time differs from the recorded one counts as gone.
    """
    if state is None:
        return {}
    live: dict[str, int] = {}
    for name, pid in state.pids.items():
        if not pid_alive(pid):
            logger.debug("%s (pid %d) is not running", name, pid)
            continue
        recorded, current = state.start_times.get(name), process_start_time(pid)
        # Without a record (older state) or without psutil, only liveness is checked.
        if recorded is None or current is None or abs(current - recorded) < _START_TIME_SLACK:
            live[name] = pid
        else:
            logger.debug(
                "%s pid %d now belongs to another process (started at %.0f, not %.0f): left alone",
                name,
                pid,
                current,
                recorded,
            )
    return live


def _describe_env(env: dict[str, str] | None) -> str:
    """What ``env`` changes from this process's environment, by variable NAME only.

    Values are compared, never shown: the server environment holds the passwords.
    """
    if env is None:
        return "this process's environment"
    changed = sorted(k for k, v in env.items() if os.environ.get(k) != v)
    removed = sorted(k for k in os.environ if k not in env)
    text = f"{len(env) - len(changed)} inherited, set: {', '.join(changed) or 'none'}"
    return text + (f", removed: {', '.join(removed)}" if removed else "")


def spawn(paths: Paths, name: str, cmd: list[str], env: dict | None = None) -> subprocess.Popen:
    log_path = paths.logs / f"{name}.log"
    logger.debug("Starting %s: %s", name, shlex.join(cmd))
    logger.debug("Environment of %s: %s", name, _describe_env(env))
    # The child gets its own copy of the log file descriptor, so ours can be closed.
    with open(log_path, "ab") as log_file:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            cwd=paths.home,
            start_new_session=True,
        )
    logger.info("Started %s (pid %d), output in %s", name, proc.pid, log_path)
    return proc


def wait_until(check, what: str, timeout: float, proc: subprocess.Popen, log_path: Path) -> None:
    """Poll ``check`` until it returns True. A check may raise instead of returning
    False: the exception says why the service is not ready, which is logged when it
    changes and named in the timeout error."""
    start = time.monotonic()
    deadline = start + timeout
    hint = f" See {log_path}"
    last_error = None
    logger.debug("Waiting up to %.0fs for %s", timeout, what)
    while time.monotonic() < deadline:
        try:
            ready, error = check(), None
        except Exception as exc:
            ready, error = False, _probe_error(exc)
        if ready:
            logger.info("Waited %.1fs for %s", time.monotonic() - start, what)
            return
        # Once per change, not at every poll.
        if error != last_error:
            logger.debug("Waiting for %s: %s", what, error or "not there yet")
            last_error = error
        # poll() rather than kill(pid, 0): an unreaped child stays visible as a zombie.
        if proc.poll() is not None:
            logger.debug("%s (pid %d) exited with code %s", what, proc.pid, proc.returncode)
            if proc.returncode == -signal.SIGILL:
                hint += (
                    " It was killed by an illegal instruction: MongoDB 5+ needs AVX on "
                    "x86_64 and ARMv8.2-A on arm64 (not available on e.g. a Raspberry Pi 4)."
                )
            # `what` may start lower case ("the Depictio API"); here it opens the sentence.
            raise LocalStackError(f"{what[:1].upper()}{what[1:]} exited during startup.{hint}")
        time.sleep(0.5)
    detail = f" (last error: {last_error})" if last_error else ""
    raise LocalStackError(f"Timed out after {timeout:.0f}s waiting for {what}{detail}.{hint}")


def _probe_error(exc: BaseException) -> str:
    """Why a probe failed, in a few words: 'Connection refused', 'HTTP 401 Unauthorized'."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} {exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        if not isinstance(exc.reason, BaseException):
            return str(exc.reason)
        exc = exc.reason
    # Refused or reset connections, socket timeouts ('timed out').
    if isinstance(exc, OSError):
        return exc.strerror or str(exc) or type(exc).__name__
    if isinstance(exc, LocalStackError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


def _probe_tcp(port: int) -> bool:
    """True once something accepts connections on ``port``; raises OSError otherwise."""
    with socket.create_connection(("127.0.0.1", port), timeout=0.5):
        return True


def tcp_ready(port: int) -> bool:
    try:
        return _probe_tcp(port)
    except OSError:
        return False


# Loopback checks bypass any proxy set in the environment (common on HPC login
# nodes), which cannot reach this machine's 127.0.0.1.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _probe_http(url: str) -> bool:
    """True once ``url`` answers without an error status; raises with the reason otherwise."""
    with _DIRECT.open(url, timeout=2) as resp:
        return resp.status < 500


def _probe_api(port: int) -> bool:
    """True once the Depictio API answers its health check on ``port``; raises with
    the reason otherwise.

    The payload is checked too, so another server answering on that port does not count.
    """
    with _DIRECT.open(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
        payload = json.load(resp)
        status = payload.get("status") if isinstance(payload, dict) else None
        if resp.status != 200 or status != "healthy":
            raise LocalStackError(
                f"/health answered HTTP {resp.status} with status {status!r}, "
                "not a healthy Depictio API"
            )
    return True


def api_healthy(port: int) -> bool:
    """Whether the Depictio API answers its health check on ``port``."""
    try:
        return _probe_api(port)
    except Exception as exc:
        logger.debug("API health check on port %d failed: %s", port, _probe_error(exc))
        return False


def start_services(
    paths: Paths,
    ports: dict[str, int],
    secret_values: dict,
    env: dict,
    record: Callable[[str, subprocess.Popen], None] | None = None,
) -> dict[str, subprocess.Popen]:
    """Start every service; ``record`` is called with each one as soon as it is
    started, so its PID is on disk before the next one starts."""
    procs: dict[str, subprocess.Popen] = {}
    try:
        _start_services(paths, ports, secret_values, env, procs, record)
    except BaseException as exc:
        logger.debug("Startup failed (%s): stopping %s", type(exc).__name__, ", ".join(procs))
        with _signals_ignored():
            for proc in reversed(list(procs.values())):
                _stop_child(proc)
        raise
    return procs


def _stop_child(proc: subprocess.Popen, timeout: float = 20) -> None:
    if proc.poll() is not None:
        return
    # poll() rather than kill(pid, 0): an unreaped child stays visible as a zombie.
    terminate_group(proc.pid, timeout, alive=lambda: proc.poll() is None)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=5)


_PROXY_VARS = {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
# What the API and the worker run, which also tells them apart from other processes.
API_APP = "depictio.api.main:app"
WORKER_APP = "depictio.api.celery_worker:celery_app"
# The native services by the name of their binary under <home>/env/bin.
NATIVE_BINARIES = {"mongod": "mongo", "redis-server": "redis", "weed": "s3"}


def _start_services(
    paths: Paths,
    ports: dict[str, int],
    secret_values: dict,
    env: dict,
    procs: dict[str, subprocess.Popen],
    record: Callable[[str, subprocess.Popen], None] | None = None,
) -> None:
    def start(name: str, cmd: list[str], env: dict) -> None:
        # Held until the process is in procs and its pid on disk, where the cleanup
        # finds it.
        with _signals_held():
            procs[name] = spawn(paths, name, cmd, env=env)
            if record is not None:
                record(name, procs[name])

    base_env = inherited_env()
    start(
        "mongo",
        [
            str(paths.bin("mongod")),
            "--dbpath",
            str(paths.home / "mongo"),
            "--port",
            str(ports["mongo"]),
            "--bind_ip",
            "127.0.0.1",
        ],
        base_env,
    )
    start(
        "redis",
        [
            str(paths.bin("redis-server")),
            "--port",
            str(ports["redis"]),
            "--bind",
            "127.0.0.1",
            "--dir",
            str(paths.home / "redis"),
            "--save",
            "",
        ],
        base_env,
    )
    # Same `weed mini` as the Docker and pixi stacks. Its master, volume and filer
    # talk to each other over HTTP: pin them to loopback and keep them away from any
    # proxy in the environment, or they announce and dial the host's public address.
    s3_env = {k: v for k, v in base_env.items() if k.lower() not in _PROXY_VARS}
    s3_env.update(
        {
            "NO_PROXY": "127.0.0.1,localhost",
            "AWS_ACCESS_KEY_ID": S3_USER,
            "AWS_SECRET_ACCESS_KEY": secret_values["s3_password"],
            "S3_BUCKET": S3_BUCKET,
        }
    )
    start(
        "s3",
        [
            str(paths.bin("weed")),
            "mini",
            f"-dir={paths.home / 's3'}",
            "-ip=127.0.0.1",
            "-ip.bind=127.0.0.1",
            f"-s3.port={ports['s3']}",
            *seaweedfs_port_flags(set(ports.values())),
            "-s3.port.iceberg=0",
            "-s3.port.lance=0",
            "-admin.ui=false",
            "-webdav=false",
            # weed mini reports cluster statistics to seaweedfs.com by default.
            "-master.telemetry=false",
        ],
        s3_env,
    )

    wait_until(
        lambda: _probe_tcp(ports["mongo"]), "MongoDB", 60, procs["mongo"], paths.logs / "mongo.log"
    )
    wait_until(
        lambda: _probe_tcp(ports["redis"]), "Redis", 30, procs["redis"], paths.logs / "redis.log"
    )
    wait_until(
        lambda: _probe_http(f"http://127.0.0.1:{ports['s3']}/healthz"),
        "SeaweedFS",
        60,
        procs["s3"],
        paths.logs / "s3.log",
    )

    start(
        "api",
        [
            sys.executable,
            "-m",
            "uvicorn",
            API_APP,
            "--host",
            "127.0.0.1",
            "--port",
            str(ports["api"]),
            "--workers",
            "1",
        ],
        env,
    )
    start(
        "worker",
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            WORKER_APP,
            "worker",
            "--loglevel=info",
            *worker_pool_args(),
        ],
        env,
    )


def worker_pool_args() -> list[str]:
    """Celery pool for this OS.

    prefork forks without exec, which only Linux tolerates here. On macOS the
    children load libarrow, deltalake and the TLS trust store, all of which call
    into CoreFoundation / SystemConfiguration, and a forked child that does so
    dies with SIGABRT or SIGSEGV; OBJC_DISABLE_INITIALIZE_FORK_SAFETY does not
    prevent it. Threads avoid the fork (the API already runs these tasks in
    threads), at the cost of Celery time limits and max-tasks-per-child.
    """
    if sys.platform.startswith("linux"):
        return ["--pool=prefork", "--concurrency=2", "--max-tasks-per-child=50"]
    return ["--pool=threads", "--concurrency=2"]


def wait_for_api(
    paths: Paths,
    ports: dict[str, int],
    proc: subprocess.Popen,
    timeout: float = 300,
    rebuild_from: dict | None = None,
    warn=print,
) -> None:
    """Wait for the API, then for the CLI configuration it writes.

    ``rebuild_from``: the passwords, on a run after the first one, when the CLI
    configuration is missing. The API writes it only when it creates the admin
    token, so it is then written again through the API rather than waited for.
    """
    wait_until(
        lambda: _probe_api(ports["api"]),
        "the Depictio API",
        timeout,
        proc,
        paths.logs / "api.log",
    )
    if rebuild_from is not None and not paths.cli_config.exists():
        rebuild_cli_config(paths, ports["api"], rebuild_from, warn=warn)
    # Written by the API when it creates the admin token, before /health answers.
    wait_until(
        paths.cli_config.exists,
        f"the CLI configuration ({paths.cli_config})",
        120,
        proc,
        paths.logs / "api.log",
    )
    sync_cli_config(paths, ports)


def read_cli_config(paths: Paths) -> dict:
    """The CLI configuration the API wrote; LocalStackError if it cannot be parsed."""
    import yaml

    try:
        config = yaml.safe_load(paths.cli_config.read_text()) or {}
        if not isinstance(config, dict):
            raise ValueError("not a YAML mapping")
    except (yaml.YAMLError, ValueError) as exc:
        # The exception type only: a parser message quotes the file, admin token included.
        reason = "not valid YAML" if isinstance(exc, yaml.YAMLError) else str(exc)
        raise LocalStackError(
            f"{paths.cli_config} is unreadable ({reason}). Delete it: depictio local up "
            "then writes it again"
        ) from exc
    return config


def _write_cli_config(paths: Paths, config: dict) -> None:
    """Write the CLI configuration owner-only, replaced in one step, so a CLI reading
    it meanwhile never sees half a file."""
    import yaml

    write_file_atomic(
        paths.cli_config,
        yaml.safe_dump(config, default_flow_style=False, sort_keys=False),
        mode=0o600,
    )


def sync_cli_config(paths: Paths, ports: dict[str, int]) -> bool:
    """Point the CLI configuration at this run's API and S3 ports; keep it owner-only.

    The API writes it only when it creates the admin token, on the first run, so
    after a port change it still names the old ports. Returns whether it changed.
    """
    config = read_cli_config(paths)
    s3 = config.setdefault("s3_storage", {})
    url = f"http://127.0.0.1:{ports['api']}"
    changed = config.get("api_base_url") != url or any(
        s3.get(key) != ports["s3"] for key in ("service_port", "external_port")
    )
    # The URL and ports only: the file also holds the admin token and the S3 password.
    logger.debug(
        "CLI configuration %s: API %s, S3 port %s%s",
        paths.cli_config,
        config.get("api_base_url"),
        s3.get("service_port"),
        f"; rewritten for {url} and S3 port {ports['s3']}" if changed else ", up to date",
    )
    if changed:
        config["api_base_url"] = url
        s3["service_port"] = s3["external_port"] = ports["s3"]
        _write_cli_config(paths, config)
    paths.cli_config.chmod(0o600)
    return changed


def _api_call(
    url: str, token: str | None = None, form: dict | None = None, body=None, method: str = "POST"
) -> dict | list:
    """Call the local API; the JSON answer. A POST sends ``form`` (url-encoded) or
    ``body`` (JSON), a GET or DELETE nothing."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif method == "POST":
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with _DIRECT.open(request, timeout=30) as resp:
        return json.load(resp)


def _api_object(answer: dict | list, what: str) -> dict:
    """``answer`` when it is a JSON object, as ``what`` should answer; ValueError otherwise."""
    if not isinstance(answer, dict):
        raise ValueError(f"{what} did not answer a JSON object")
    return answer


# The name rebuild_cli_config gives its token. The first run's token is the API's
# default_token, and the CLI agents page lets the user pick any name.
REBUILT_TOKEN_NAME = re.compile(r"depictio-local-\d{14}")


def rebuild_cli_config(paths: Paths, api_port: int, secret_values: dict, warn=print) -> None:
    """Write the CLI configuration again, through the running API, as the admin.

    The same three calls as the CLI agents page: sign in, create a long-lived token,
    have the API generate the configuration for it. Then the tokens earlier rebuilds
    created are revoked; ``warn`` names those that could not be.
    """
    logger.info("No %s: writing it again through the API", paths.cli_config)
    auth = f"http://127.0.0.1:{api_port}/depictio/api/v1/auth"
    name = f"depictio-local-{time.strftime('%Y%m%d%H%M%S')}"
    try:
        session = _api_object(
            _api_call(
                f"{auth}/login",
                form={"username": ADMIN_EMAIL, "password": secret_values["admin_password"]},
            ),
            "/auth/login",
        )
        token = _api_object(
            _api_call(f"{auth}/me/tokens", token=session["access_token"], body={"name": name}),
            "/auth/me/tokens",
        )
        fields_sent = (
            "user_id",
            "access_token",
            "refresh_token",
            "token_type",
            "token_lifetime",
            "expire_datetime",
            "refresh_expire_datetime",
            "name",
        )
        config = _api_object(
            _api_call(
                f"{auth}/generate_agent_config",
                token=session["access_token"],
                body={key: token.get(key) for key in fields_sent},
            ),
            "/auth/generate_agent_config",
        )
    except (OSError, ValueError, KeyError) as exc:
        raise LocalStackError(
            f"{paths.cli_config} is missing and the API could not write it again "
            f"({_probe_error(exc)}). See {paths.logs / 'api.log'}"
        ) from exc
    _write_cli_config(paths, config)
    logger.info("Wrote %s again", paths.cli_config)
    left = _revoke_rebuilt_tokens(auth, session["access_token"], name, _token_id(token))
    page = f"http://127.0.0.1:{api_port}/cli-agents"
    if left is None:
        warn(f"Could not list the earlier depictio-local tokens, which stay valid: see {page}")
    elif left:
        plural = left > 1
        warn(
            f"{left} earlier depictio-local token{'s' if plural else ''} could not be "
            f"revoked and stay{'' if plural else 's'} valid: delete "
            f"{'them' if plural else 'it'} on {page}"
        )


def _token_id(token: dict) -> str:
    """A token's id: the API answers ``_id``, the CLI agents page also accepts ``id``."""
    return str(token.get("_id") or token.get("id") or "")


def _revoke_rebuilt_tokens(auth: str, session: str, kept_name: str, kept_id: str) -> int | None:
    """Delete the admin's tokens from earlier rebuilds, all but the one just created.

    No configuration holds them any more, yet each stays valid for a year. Only names
    matching REBUILT_TOKEN_NAME are touched. Returns how many could not be deleted,
    None when the list itself failed.
    """
    try:
        tokens = _api_call(
            f"{auth}/list_tokens?token_lifetime=long-lived", token=session, method="GET"
        )
        if not isinstance(tokens, list):
            raise ValueError(f"a {type(tokens).__name__} instead of a list")
    except (OSError, ValueError) as exc:
        logger.debug("Listing the admin's tokens failed: %s", _probe_error(exc))
        return None
    earlier = [
        t
        for t in tokens
        if isinstance(t, dict)
        and REBUILT_TOKEN_NAME.fullmatch(str(t.get("name") or ""))
        and t["name"] != kept_name
        and _token_id(t) != kept_id
    ]
    left = 0
    for t in earlier:
        token_id = _token_id(t)
        try:
            if not token_id:
                raise ValueError("no id in the token list")
            _api_call(
                f"{auth}/me/tokens/{urllib.parse.quote(token_id)}", token=session, method="DELETE"
            )
            logger.debug("Revoked the earlier token %s (%s)", t["name"], token_id)
        except (OSError, ValueError) as exc:
            left += 1
            logger.debug(
                "Revoking the token %s (%s) failed: %s", t["name"], token_id, _probe_error(exc)
            )
    logger.info("Revoked %d of %d earlier depictio-local tokens", len(earlier) - left, len(earlier))
    return left


def check_alive(paths: Paths, procs: dict[str, subprocess.Popen]) -> None:
    """Fail when a service died while the API was starting, e.g. a crashed worker."""
    for name, proc in procs.items():
        if proc.poll() is not None:
            logger.debug("%s (pid %d) exited with code %s", name, proc.pid, proc.returncode)
            raise LocalStackError(
                f"The {name} process exited during startup. See {paths.logs / f'{name}.log'}"
            )


def table_status(url: str, token: str, dc_id: str) -> str:
    """'ready' once the API has a Delta table for the data collection ``dc_id``,
    'absent' if the data collection does not exist, 'unreachable' if the API does
    not answer, 'loading' otherwise."""
    request = urllib.request.Request(
        f"{url}/depictio/api/v1/deltatables/specs/{dc_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with _DIRECT.open(request, timeout=5) as resp:
            status, reason = "ready", f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        status, reason = "loading", _probe_error(exc)
        # The endpoint answers 404 both while the Delta table is being written and
        # when the data collection itself does not exist.
        with contextlib.suppress(OSError):
            if exc.code == 404 and b"Data collection not found" in exc.read():
                status, reason = "absent", f"{reason}, data collection not found"
    except Exception as exc:
        # Refused, reset or timed out: the API, not the example, is the problem.
        status, reason = "unreachable", _probe_error(exc)
    _debug_on_change(f"table {dc_id}", f"Delta table of {dc_id}: {status} ({reason})")
    return status


# The last message _debug_on_change logged for each key.
_last_debug: dict[str, str] = {}


def _debug_on_change(key: str, message: str) -> None:
    """Log ``message`` unless it is what was last logged for ``key``: a poll then
    logs a line when its outcome changes, not at every round."""
    if _last_debug.get(key) != message:
        _last_debug[key] = message
        logger.debug(message)


def requested_examples(state: State) -> list[str]:
    """The examples `up` asked the server to seed."""
    return [name for name in state.examples.split(",") if name in EXAMPLE_TABLES]


def examples_status(paths: Paths, state: State, names: list[str] | None = None) -> dict[str, str]:
    """'ready', 'loading', 'absent' or 'unreachable' for each example in ``names``,
    by default the requested ones; empty if unknown.

    The API loads them in a background thread once it has started, so /health
    answers first: on a first run they need a few more seconds, and their projects
    appear one after the other. They are seeded on the first run of a local home
    only, so later a missing one is one the home was created without, or that was
    deleted since.
    """
    requested = requested_examples(state)
    names = requested if names is None else names
    if not names:
        logger.debug("No examples to check (requested: %r)", state.examples)
        return {}
    try:
        token = read_cli_config(paths)["user"]["token"]["access_token"]
    except (OSError, LocalStackError, KeyError, TypeError) as exc:
        # The exception type only: a message could quote part of the file.
        logger.debug("No admin token in %s (%s)", paths.cli_config, type(exc).__name__)
        return {}
    status = {}
    for name in names:
        # Seeding creates each project in turn, so on a first run one not created yet
        # is still to come.
        not_found = "loading" if state.first_run and name in requested else "absent"
        tables = {table_status(state.url, token, dc_id) for dc_id in EXAMPLE_TABLES[name]}
        tables = {not_found if s == "absent" else s for s in tables}
        order = ("absent", "unreachable", "loading", "ready")
        status[name] = next(s for s in order if s in tables)
    return status


# Worth waiting out: a table being written, or an API too busy to answer for a moment.
_PENDING = ("loading", "unreachable")


def wait_for_examples(
    paths: Paths, state: State, timeout: float = 120, interval: float = 1.0
) -> dict[str, str]:
    """examples_status once no example is pending any more, or at the timeout."""
    start = time.monotonic()
    deadline = start + timeout

    def pending(status: dict[str, str]) -> bool:
        return any(s in _PENDING for s in status.values())

    status = examples_status(paths, state)
    logger.debug("Waiting up to %.0fs for the examples: %s", timeout, status)
    while pending(status) and time.monotonic() < deadline:
        time.sleep(interval)
        previous, status = status, examples_status(paths, state)
        if status != previous:
            logger.debug("Examples after %.0fs: %s", time.monotonic() - start, status)
    if pending(status):
        logger.debug("Gave up on the examples after %.0fs: %s", time.monotonic() - start, status)
    return status


def mark_examples_loaded(paths: Paths, state: State) -> None:
    """Record that the first run's examples are loaded: from then on a missing one
    was deleted, and is not waited for. Left alone if the server was stopped or
    restarted meanwhile."""
    state.first_run = False
    try:
        current = State.load(paths)
    except StateUnreadable:
        return
    if current is None or current.pids != state.pids:
        logger.debug("%s changed meanwhile: first_run left as is", paths.state)
        return
    current.first_run = False
    current.save(paths)


def terminate_group(pid: int, timeout: float = 20, alive=None) -> None:
    """Stop the process group ``pid`` leads: SIGTERM, up to ``timeout`` seconds, SIGKILL.

    Every service starts in its own session, so its group also holds what it forked
    (Celery pool processes, Chromium), which signalling ``pid`` alone leaves running.
    """
    alive = alive or (lambda: pid_alive(pid))
    try:
        os.killpg(pid, signal.SIGTERM)
        logger.debug("Sent SIGTERM to process group %d", pid)
    except OSError as exc:
        # Not a group leader: stop the process alone.
        logger.debug("No process group %d (%s): SIGTERM to the process", pid, _probe_error(exc))
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            logger.debug("pid %d is gone (%s)", pid, _probe_error(exc))
            return
    start = time.monotonic()
    deadline = start + timeout
    while alive() and time.monotonic() < deadline:
        time.sleep(0.2)
    if alive():
        logger.debug("pid %d still running after %.0fs: SIGKILL", pid, timeout)
    else:
        logger.debug("pid %d exited %.1fs after SIGTERM", pid, time.monotonic() - start)
    # Whatever ignored SIGTERM, or outlived the leader.
    with contextlib.suppress(OSError):
        os.killpg(pid, signal.SIGKILL)
        logger.debug("Sent SIGKILL to process group %d, for anything left in it", pid)
    if alive():
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)


def stop_all(paths: Paths, log=print) -> list[str]:
    """Stop the processes `up` recorded; returns the names of those that were running.

    With an unreadable state.json, the processes are found by find_server_processes.
    """
    try:
        live = live_pids(State.load(paths))
    except StateUnreadable:
        log(f"{paths.state} is unreadable: looking for the server's processes instead")
        live = find_server_processes(paths)
    stopped = [name for name in reversed(PROCESS_ORDER) if name in live]
    if not stopped:
        logger.debug("No recorded process is running")
    for name in stopped:
        log(f"Stopping {name} (pid {live[name]})")
        terminate_group(live[name])
    paths.state.unlink(missing_ok=True)
    return stopped


def _service_name(cmdline: list[str]) -> str | None:
    """Which service ``cmdline`` runs, if it is one `up` starts."""
    if not cmdline:
        return None
    # Redis rewrites its title to "redis-server 127.0.0.1:<port>".
    binary = os.path.basename(cmdline[0].split(" ")[0])
    if binary in NATIVE_BINARIES:
        return NATIVE_BINARIES[binary]
    if API_APP in cmdline:
        return "api"
    if WORKER_APP in cmdline:
        return "worker"
    return None


def find_server_processes(paths: Paths) -> dict[str, int]:
    """The services `up` started from this home, found without state.json.

    Each one leads its own session (start_new_session), runs one of the commands
    `up` starts, and works in the home or one of its folders (Redis in redis/).
    """
    try:
        import psutil
    except ImportError as exc:
        raise LocalStackError(
            f"{paths.state} is unreadable, and finding the server's processes without it "
            f"needs psutil. Stop the mongod, redis-server, weed, uvicorn and celery processes "
            f"started from {paths.home}, then delete {paths.state}"
        ) from exc
    home = os.path.realpath(paths.home)
    found: dict[str, int] = {}
    for proc in psutil.process_iter(["pid", "cmdline", "cwd"]):
        pid, cwd = proc.info["pid"], proc.info["cwd"]
        if pid == os.getpid() or not cwd:
            continue
        cwd = os.path.realpath(cwd)
        if home not in (cwd, os.path.dirname(cwd)):
            continue
        name = _service_name(proc.info["cmdline"] or [])
        with contextlib.suppress(OSError):
            if name and os.getpgid(pid) == pid:
                found[name] = pid
    logger.debug("Server processes running from %s: %s", home, found or "none")
    return found


def running_status(paths: Paths, state: State | None = None) -> dict[str, bool]:
    """Whether each process `up` started still runs. ``state``: state.json as the
    caller already loaded it, read here otherwise."""
    live = live_pids(state if state is not None else State.load(paths))
    return {name: name in live for name in PROCESS_ORDER}


def api_responds(port: int, patience: float = 10) -> bool:
    """Whether the API answers its health check within ``patience`` seconds, so a
    moment of load is not taken for a hung API."""
    deadline = time.monotonic() + patience
    while not api_healthy(port):
        if time.monotonic() >= deadline:
            return False
        time.sleep(1)
    return True


def check_server_installed() -> None:
    missing = [
        mod for mod in ("fastapi", "uvicorn", "celery", "depictio.api") if not _importable(mod)
    ]
    if missing:
        raise LocalStackError(
            "The Depictio server is not installed in this environment "
            f"(missing: {', '.join(missing)}). Install it with: {INSTALL_LOCAL}"
        )


def _importable(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


def package_root() -> Path | None:
    """The ``depictio`` package directory: in site-packages, or in a source checkout."""
    spec = importlib.util.find_spec("depictio")
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations)))


def viewer_built() -> bool:
    root = package_root()
    index = root / "viewer" / "dist" / "index.html" if root is not None else None
    built = index is not None and index.is_file()
    logger.debug("Viewer bundle %s: %s", index, "found" if built else "missing")
    return built


# The files a viewer build reads: modules, styles, the HTML entries, and the fonts and
# images they and public/ bring in.
_BUNDLED = frozenset(
    ".ts .tsx .mts .cts .js .jsx .mjs .cjs .css .json .html .svg .png .jpg .jpeg .gif "
    ".webp .avif .ico .ttf .otf .woff .woff2".split()
)
# What `pnpm run build` in depictio/viewer reads, workspace-relative, with the file
# extensions read there (None: that one file). The viewer and the two workspace
# packages its vite.config.ts aliases to their sources; then what its first step,
# scripts/generate-icon-subset.mjs, scans for icon names (SCAN_FILES and
# SCAN_DATA_DIRS there): the advanced-viz kind registry and the shipped dashboards.
VIEWER_SOURCES: dict[str, frozenset[str] | None] = {
    "pnpm-lock.yaml": None,
    "depictio/viewer": _BUNDLED,
    "packages/depictio-components/src": _BUNDLED,
    "packages/depictio-react-core/src": _BUNDLED,
    "depictio/models/components/advanced_viz/schemas.py": None,
    "depictio/projects": frozenset({".yaml", ".yml", ".json"}),
}
# Not sources: dependencies, build output (dist-* too, for the catalog preview and
# table harness builds), src/generated, which the build writes, and Python caches.
_NOT_VIEWER_SOURCES = {"node_modules", "dist", "generated", "__pycache__"}
VIEWER_BUILD_TIMEOUT = 20 * 60


def viewer_workspace() -> Path | None:
    """The pnpm workspace depictio runs from, or None when it is installed from a wheel.

    A wheel carries the viewer bundle built. A source checkout (an editable install)
    has to build it: depictio/viewer/dist is not committed.
    """
    root = package_root()
    if root is None or not (root / "viewer" / "src").is_dir():
        return None
    workspace = root.parent
    return workspace if (workspace / "pnpm-workspace.yaml").is_file() else None


def _is_source_folder(name: str) -> bool:
    # Dot folders hold caches and editor state, except the dashboards' .db_seeds.
    return (
        name not in _NOT_VIEWER_SOURCES
        and not name.startswith("dist-")
        and (not name.startswith(".") or name == ".db_seeds")
    )


def _viewer_sources(workspace: Path) -> Iterator[str]:
    """The files the viewer build reads, then the folder holding them: a deleted
    source shows only in its folder's mtime.

    Not depictio/viewer itself: vite writes, then deletes, a copy of its config
    there at each run (`pnpm dev` too).
    """
    viewer = os.path.join(workspace, "depictio", "viewer")
    for name, extensions in VIEWER_SOURCES.items():
        top = os.path.join(workspace, name)
        if extensions is None:
            yield top
            continue
        for folder, dirs, files in os.walk(top):
            dirs[:] = [d for d in dirs if _is_source_folder(d)]
            # Dot files (.DS_Store, editor state) change without the sources.
            for f in files:
                if not f.startswith(".") and os.path.splitext(f)[1] in extensions:
                    yield os.path.join(folder, f)
            if folder != viewer:
                yield folder


def viewer_outdated(workspace: Path) -> str | None:
    """Why the viewer bundle of ``workspace`` needs building, None when it is up to date:
    it was never built, or a source changed since (an edit, a deletion, a pull, a
    branch switch)."""
    index = workspace / "depictio" / "viewer" / "dist" / "index.html"
    try:
        built_at = index.stat().st_mtime
    except OSError:
        return "not built yet"
    # Run by every `up`, over about a thousand paths: plain strings and os.stat rather
    # than Path objects.
    for source in _viewer_sources(workspace):
        try:
            info = os.stat(source)
        except OSError:
            continue
        if info.st_mtime > built_at:
            logger.debug("Viewer bundle %s is older than %s", index, source)
            name = os.path.relpath(source, workspace)
            if stat.S_ISDIR(info.st_mode):
                return f"a file in {name} was added or deleted since the last build"
            return f"{name} changed since the last build"
    logger.debug("Viewer bundle %s is up to date", index)
    return None


def build_viewer(workspace: Path, log_path: Path) -> None:
    """Build the viewer bundle of ``workspace`` as a release does: `pnpm install`, then
    `pnpm run build` in depictio/viewer. Their output goes to ``log_path``.

    Raises LocalStackError when pnpm is missing, or a step fails or takes too long.
    On Ctrl-C, SIGTERM or SIGHUP, pnpm and what it runs are stopped before
    KeyboardInterrupt (Interrupted for the two signals) propagates.
    """
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise LocalStackError(
            "pnpm is not installed, so the viewer cannot be built. Install Node.js 20 or "
            "later, run corepack enable pnpm, then depictio local up again"
        )
    # As in publish-pypi.yaml: no sourcemaps, and room for the plotly chunk.
    env = {
        **os.environ,
        "VITE_NO_SOURCEMAP": "true",
        "NODE_OPTIONS": " ".join(
            filter(None, (os.environ.get("NODE_OPTIONS"), "--max-old-space-size=4096"))
        ),
    }
    steps = [
        ([pnpm, "install", "--frozen-lockfile"], workspace),
        ([pnpm, "run", "build"], workspace / "depictio" / "viewer"),
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # The signals of a closed terminal or a `kill` would otherwise end this process
    # and leave pnpm's session running.
    with _signals_interrupt(), open(log_path, "w", encoding="utf-8") as log:
        for cmd, cwd in steps:
            step = shlex.join(["pnpm", *cmd[1:]])
            logger.debug("Building the viewer: %s in %s, output in %s", step, cwd, log_path)
            log.write(f"$ {step}  (in {cwd})\n")
            log.flush()
            proc = None
            try:
                # Its own session, as the services: stopping it stops what pnpm runs
                # (node, vite) too.
                with _signals_held():
                    proc = subprocess.Popen(
                        cmd,
                        cwd=cwd,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                code = proc.wait(timeout=VIEWER_BUILD_TIMEOUT)
            except BaseException as exc:
                # Ctrl-C does not reach another session: stop it here, whatever the cause.
                if proc is not None:
                    with _signals_ignored():
                        terminate_group(proc.pid, timeout=5, alive=lambda p=proc: p.poll() is None)
                        with contextlib.suppress(subprocess.TimeoutExpired):
                            proc.wait(timeout=5)
                if isinstance(exc, subprocess.TimeoutExpired):
                    raise LocalStackError(
                        f"{step} did not finish in {VIEWER_BUILD_TIMEOUT // 60} minutes "
                        f"(see {log_path})"
                    ) from exc
                raise
            if code != 0:
                raise LocalStackError(f"{step} failed (exit {code}, see {log_path})")


def seed_screenshots(paths: Paths) -> None:
    """Copy the thumbnails shipped for the reference dashboards, once."""
    root = package_root()
    if root is None:
        return
    bundled = root / "api" / "static" / "screenshots"
    target = paths.home / "screenshots"
    copied = 0
    for png in bundled.glob("*.png"):
        if not (target / png.name).exists():
            shutil.copy2(png, target / png.name)
            copied += 1
    logger.debug("Copied %d bundled thumbnails from %s to %s", copied, bundled, target)


def chromium_installed() -> bool:
    """Whether Playwright can launch its bundled Chromium (used for thumbnails)."""
    probe = (
        "import pathlib, sys\n"
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    sys.exit(0 if pathlib.Path(p.chromium.executable_path).exists() else 1)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, timeout=60, check=False
    )
    error = result.stderr.decode(errors="replace").strip().splitlines()
    logger.debug(
        "Chromium probe exited with code %d%s", result.returncode, f": {error[-1]}" if error else ""
    )
    return result.returncode == 0


def install_chromium() -> None:
    cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    logger.debug("Running %s", shlex.join(cmd))
    if subprocess.call(cmd) != 0:
        raise LocalStackError("Could not install Chromium for dashboard thumbnails")


def reset(paths: Paths) -> None:
    """Delete all local data but keep the downloaded binaries. Only for a home
    is_local_home accepts."""
    for sub in DATA_DIRS:
        logger.debug("Deleting %s", paths.home / sub)
        shutil.rmtree(paths.home / sub, ignore_errors=True)
    for f in (paths.state, paths.secrets, paths.ports):
        logger.debug("Deleting %s", f)
        f.unlink(missing_ok=True)
    logger.debug("Kept the native binaries in %s and %s", paths.env, paths.marker)


# The commands that take the lock below.
_LOCKING_COMMANDS = ("up", "wipe", "export")


def lock_for_startup(paths: Paths, command: str = "up") -> TextIO:
    """The lock on the home that `up` holds while it starts the server, and `wipe` and
    `export` while they stop it and delete or copy its data. A second command on the
    home fails fast rather than wait: it would start a second MongoDB on the same
    data, or delete the folders a starting server writes to. Closing the returned
    file releases it."""
    try:
        import fcntl  # POSIX only, as is the process handling above
    except ImportError as exc:
        raise LocalStackError(
            "depictio local needs POSIX file locks, which this platform does not have: "
            "use WSL2, or the Docker compose stack"
        ) from exc
    cannot_lock = f"Cannot lock the local home {paths.home}"
    try:
        handle = open(paths.home / UP_LOCK, "a")
    except OSError as exc:
        raise LocalStackError(f"{cannot_lock} ({exc.strerror or exc})") from exc
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise LocalStackError(_lock_busy(paths, command)) from exc
    except OSError as exc:
        handle.close()
        raise LocalStackError(f"{cannot_lock} ({exc.strerror or exc})") from exc
    except BaseException:
        handle.close()
        raise
    # Who holds it, for the message of a command that cannot have it.
    with contextlib.suppress(OSError):
        handle.truncate(0)
        handle.write(command)
        handle.flush()
    return handle


def _lock_busy(paths: Paths, command: str) -> str:
    """Why ``command`` cannot have the home's lock: the command holding it, as it
    wrote it in the lock file. Before `wipe` and `export` took the lock, only `up`
    did, and wrote nothing."""
    holder = ""
    with contextlib.suppress(OSError, UnicodeDecodeError):
        holder = (paths.home / UP_LOCK).read_text().strip()
    if holder not in _LOCKING_COMMANDS:
        holder = "up"
    if holder == "up" and command == "up":
        return f"Another `depictio local up` is already starting this home ({paths.home})"
    if holder == "up":
        return (
            f"A `depictio local up` is starting this home ({paths.home}): wait for it, "
            "or stop it, then try again"
        )
    return (
        f"`depictio local {holder}` is using this home ({paths.home}): wait for it to "
        "finish, then try again"
    )


class Interrupted(KeyboardInterrupt):
    """SIGTERM or SIGHUP (a closed terminal) during startup, handled as Ctrl-C is."""

    def __init__(self, signum: int):
        super().__init__(signal.Signals(signum).name)
        self.signum = signum


class _InterruptState:
    """The signal _signals_interrupt received, and whether _signals_held holds it."""

    def __init__(self) -> None:
        self.received: list[int] = []
        self.holding = False


# Set while _signals_interrupt is active (main thread only).
_interrupts: _InterruptState | None = None


@contextlib.contextmanager
def _signals_interrupt() -> Iterator[None]:
    """Raise Interrupted on SIGTERM and SIGHUP, as Ctrl-C raises KeyboardInterrupt, so
    the startup stops what it started. A second signal is ignored, so it cannot cut
    that cleanup short. The previous handlers are restored on exit."""
    global _interrupts
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    state = _InterruptState()

    def handler(signum, _frame):
        name = signal.Signals(signum).name
        if state.received:
            logger.debug("Ignored %s: already stopping", name)
            return
        state.received.append(signum)
        if state.holding:
            logger.debug("%s held until the process being started is recorded", name)
            return
        raise Interrupted(signum)

    signums = [getattr(signal, name) for name in ("SIGTERM", "SIGHUP") if hasattr(signal, name)]
    previous = {signum: signal.signal(signum, handler) for signum in signums}
    outer, _interrupts = _interrupts, state
    try:
        yield
    finally:
        _interrupts = outer
        for signum, old in previous.items():
            signal.signal(signum, old)


@contextlib.contextmanager
def _signals_held() -> Iterator[None]:
    """Hold the Interrupted of a SIGTERM or SIGHUP until the end of the block.

    Raised inside subprocess.Popen, after its fork, it would leave the new process
    running with no caller knowing its pid. Held, it is raised once the block has
    recorded that process, so the cleanup stops it.
    """
    state = _interrupts
    if state is None or state.holding or state.received:
        yield
        return
    state.holding = True
    try:
        yield
    finally:
        state.holding = False
    if state.received:
        raise Interrupted(state.received[0])


@contextlib.contextmanager
def _signals_ignored() -> Iterator[None]:
    """Ignore Ctrl-C, SIGTERM and SIGHUP while a failed or interrupted startup stops
    what it started: a second Ctrl-C would cut that short and leave services running.
    The previous handlers are restored on exit."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    names = ("SIGINT", "SIGTERM", "SIGHUP")
    previous = {}
    try:
        for signum in [getattr(signal, name) for name in names if hasattr(signal, name)]:
            previous[signum] = signal.signal(signum, signal.SIG_IGN)
        yield
    finally:
        for signum, old in previous.items():
            signal.signal(signum, old)


def _quiet_on_error(log):
    """``log``, minus the errors of a terminal that has gone (after SIGHUP), which
    would otherwise stop the cleanup halfway."""

    def quiet(msg: str) -> None:
        with contextlib.suppress(OSError):
            log(msg)

    return quiet


# ---------------------------------------------------------------------------
# up: start the stack
# ---------------------------------------------------------------------------


def start_stack(
    paths: Paths,
    port: int | None,
    seed: str,
    screenshots: bool,
    log=print,
    warn=None,
) -> State:
    """Start every service and wait until the API answers; returns what was recorded.

    Leftovers of an earlier run are stopped first. On any error, Ctrl-C, SIGTERM
    and SIGHUP included, what this call started is stopped again before the error
    propagates, with those signals ignored meanwhile. Each PID is saved as soon as
    its process starts.
    """
    warn = warn or log
    with _signals_interrupt():
        try:
            return _start_stack(paths, port, seed, screenshots, log, warn)
        except BaseException as exc:
            logger.debug("Startup failed (%s): stopping what this run started", type(exc).__name__)
            with _signals_ignored():
                stop_all(paths, log=_quiet_on_error(log))
            raise


def _start_stack(paths: Paths, port: int | None, seed: str, screenshots: bool, log, warn) -> State:
    stop_all(paths, log=log)
    ensure_binaries(paths, log=log)
    seed_screenshots(paths)
    saved_ports = load_ports(paths)
    ports = pick_ports(port, saved_ports)
    if port is None and saved_ports.get("api", ports["api"]) != ports["api"]:
        warn(
            f"Port {saved_ports['api']} is now used by another program: "
            f"Depictio moves to port {ports['api']}"
        )
    save_ports(paths, ports)
    if screenshots and not chromium_installed():
        log("Installing Chromium for dashboard thumbnails")
        install_chromium()
    secret_values = load_secrets(paths)
    env = server_env(paths, ports, secret_values, seed, screenshots)
    state = State(
        ports=ports,
        home=str(paths.home),
        examples=seed,
        first_run=not any((paths.home / "mongo").glob("*")),
        screenshots=screenshots,
    )
    logger.debug(
        "Examples to seed: %s; first run (empty database): %s; thumbnails: %s",
        seed,
        state.first_run,
        screenshots,
    )
    # The API writes the CLI configuration on the first run only: checked before
    # anything starts, and a missing one is written again once the API answers.
    rebuild = not state.first_run and not paths.cli_config.exists()
    if rebuild:
        log(f"{paths.cli_config} is missing: it is written again once the API answers")
    elif not state.first_run:
        read_cli_config(paths)
    state.save(paths)

    def record(name: str, proc: subprocess.Popen) -> None:
        state.pids[name] = proc.pid
        state.start_times[name] = process_start_time(proc.pid)
        state.save(paths)

    procs = start_services(paths, ports, secret_values, env, record=record)
    state.pids = {name: proc.pid for name, proc in procs.items()}
    state.start_times = {name: process_start_time(proc.pid) for name, proc in procs.items()}
    state.save(paths)
    log(f"Services started (logs in {paths.logs}); waiting for the API")
    wait_for_api(
        paths, ports, procs["api"], rebuild_from=secret_values if rebuild else None, warn=warn
    )
    check_alive(paths, procs)
    return state
