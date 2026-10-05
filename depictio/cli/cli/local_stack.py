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
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

# The major series of the images in docker-compose.yaml (mongo, redis,
# chrislusf/seaweedfs): move them together. Redis and SeaweedFS are pinned to the
# major only: a pin below what an existing local home already runs would
# downgrade it, and Redis cannot load an RDB written by a newer version.
# export-compose pins the SeaweedFS image to the local version, so a hand-over
# never downgrades either.
CONDA_SPECS = ["mongodb 8.0.*", "redis-server 8.*", "seaweedfs 4.*"]
ADMIN_EMAIL = "admin@example.com"
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
)


class LocalStackError(RuntimeError):
    pass


def check_platform_supported() -> None:
    """Linux and macOS, x86_64 or arm64: the platforms conda-forge builds all three
    services for, and the ones where the process-group handling below works."""
    if sys.platform == "win32":
        raise LocalStackError(
            "depictio local is not supported on Windows: conda-forge has no redis-server "
            "build for it and the services are managed as POSIX process groups. "
            "Use WSL2, or the Docker compose stack."
        )


def local_home() -> Path:
    return Path(os.environ.get("DEPICTIO_LOCAL_HOME", "~/.depictio/local")).expanduser()


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

    def bin(self, name: str) -> Path:
        return self.env / "bin" / name

    def ensure_dirs(self) -> None:
        # Owner-only: keys/ holds the token signing keys and cli/ the admin token and
        # S3 secret, which the API writes with the default umask (world-readable).
        for private in (self.home, self.home / "keys", self.home / "cli"):
            private.mkdir(parents=True, exist_ok=True)
            private.chmod(0o700)
        for sub in DATA_DIRS:
            (self.home / sub).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Native binaries (conda-forge via py-rattler)
# ---------------------------------------------------------------------------


def ensure_binaries(paths: Paths, log=print) -> None:
    try:
        from rattler import Platform, VirtualPackage, install, solve
    except ImportError as exc:
        raise LocalStackError(
            "py-rattler is required to fetch MongoDB, Redis and SeaweedFS. "
            'Install the local extra: uv tool install "depictio[local]"'
        ) from exc

    # The platform is part of the marker: a $HOME shared between linux-64 and
    # linux-aarch64 hosts, or a Python switched between Rosetta and native on a
    # Mac, must not reuse binaries built for the other architecture.
    wanted = {"specs": CONDA_SPECS, "platform": str(Platform.current())}
    marker = paths.env / ".depictio-specs.json"
    if marker.exists() and json.loads(marker.read_text()) == wanted:
        return
    if paths.env.exists():
        shutil.rmtree(paths.env)

    async def _install() -> None:
        records = await solve(
            sources=["conda-forge"],
            specs=CONDA_SPECS,
            virtual_packages=VirtualPackage.detect(),
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
    pids: dict[str, int] = field(default_factory=dict)
    # Start time of each process, so a PID reused after a reboot is not taken for ours.
    start_times: dict[str, float | None] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.ports.get('api', DEFAULT_PORTS['api'])}"

    @classmethod
    def load(cls, paths: Paths) -> State | None:
        """The state of the last `up`, or None when nothing is recorded.

        Files written by earlier versions load too: a missing key takes its
        default, and url is derived from the ports rather than read.
        """
        if not paths.state.exists():
            return None
        saved = json.loads(paths.state.read_text())
        known = {f.name for f in fields(cls)}
        state = cls(**{k: v for k, v in saved.items() if k in known})
        state.home = state.home or str(paths.home)
        return state

    def save(self, paths: Paths) -> None:
        # url is written too, for anything reading the file without this class.
        paths.state.write_text(json.dumps({**asdict(self), "url": self.url}, indent=2))


def write_private_file(path: Path, text: str) -> None:
    """Write ``text`` to ``path``. A new file is created owner-only rather than
    chmod-ed afterwards, so it is never readable by others."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)


def load_secrets(paths: Paths) -> dict:
    if paths.secrets.exists():
        return json.loads(paths.secrets.read_text())
    values = {
        "s3_password": secrets.token_urlsafe(24),
        "admin_password": secrets.token_urlsafe(24),
    }
    write_private_file(paths.secrets, json.dumps(values))
    return values


def port_is_free(port: int) -> bool:
    # On macOS/BSD the bind below succeeds next to a listener on 0.0.0.0 (e.g. a
    # port published by the Docker dev stack), so check for a listener first.
    if tcp_ready(port):
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # Same option the servers set, so a port left in TIME_WAIT by the previous
        # run still counts as free.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def pick_port(preferred: int, taken: set[int]) -> int:
    if preferred not in taken and port_is_free(preferred):
        return preferred
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port not in taken:
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
        return {}
    saved = json.loads(paths.ports.read_text())
    return {k: v for k, v in saved.items() if k in DEFAULT_PORTS and isinstance(v, int)}


def save_ports(paths: Paths, ports: dict[str, int]) -> None:
    paths.ports.write_text(json.dumps(ports, indent=2))


def parse_examples(value: str | None, template: str | None) -> str:
    """--examples as DEPICTIO_SEED_PROJECTS takes it, or 'none'."""
    if value is None:
        return "none" if template else ",".join(EXAMPLES)
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


def server_env(
    paths: Paths, ports: dict[str, int], secret_values: dict, seed: str, screenshots: bool
) -> dict:
    host = "127.0.0.1"
    # Inherited DEPICTIO_* settings target another instance, except the telemetry
    # opt-out (DEPICTIO_TELEMETRY_ENABLED=false), which must reach this one too.
    env = {
        k: v
        for k, v in os.environ.items()
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
        }
    )
    if seed == "none":
        env["DEPICTIO_DISABLE_EXAMPLE_DASHBOARDS"] = "true"
    else:
        env["DEPICTIO_SEED_PROJECTS"] = seed
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
            continue
        recorded, current = state.start_times.get(name), process_start_time(pid)
        # Without a record (older state) or without psutil, only liveness is checked.
        if recorded is None or current is None or abs(current - recorded) < _START_TIME_SLACK:
            live[name] = pid
    return live


def spawn(paths: Paths, name: str, cmd: list[str], env: dict | None = None) -> subprocess.Popen:
    # The child gets its own copy of the log file descriptor, so ours can be closed.
    with open(paths.logs / f"{name}.log", "ab") as log_file:
        return subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            cwd=paths.home,
            start_new_session=True,
        )


def wait_until(check, what: str, timeout: float, proc: subprocess.Popen, log_path: Path) -> None:
    deadline = time.monotonic() + timeout
    hint = f" See {log_path}"
    while time.monotonic() < deadline:
        if check():
            return
        # poll() rather than kill(pid, 0): an unreaped child stays visible as a zombie.
        if proc.poll() is not None:
            if proc.returncode == -signal.SIGILL:
                hint += (
                    " It was killed by an illegal instruction: MongoDB 5+ needs AVX on "
                    "x86_64 and ARMv8.2-A on arm64 (not available on e.g. a Raspberry Pi 4)."
                )
            raise LocalStackError(f"{what} exited during startup.{hint}")
        time.sleep(0.5)
    raise LocalStackError(f"Timed out after {timeout:.0f}s waiting for {what}.{hint}")


def tcp_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


# Loopback checks bypass any proxy set in the environment (common on HPC login
# nodes), which cannot reach this machine's 127.0.0.1.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_ready(url: str) -> bool:
    try:
        with _DIRECT.open(url, timeout=2) as resp:
            return resp.status < 500
    except Exception:
        return False


def api_healthy(port: int) -> bool:
    """Whether the Depictio API answers its health check on ``port``.

    The payload is checked too, so another server answering on that port does not count.
    """
    try:
        with _DIRECT.open(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
            return resp.status == 200 and json.load(resp).get("status") == "healthy"
    except Exception:
        return False


def start_services(
    paths: Paths, ports: dict[str, int], secret_values: dict, env: dict
) -> dict[str, subprocess.Popen]:
    procs: dict[str, subprocess.Popen] = {}
    try:
        _start_services(paths, ports, secret_values, env, procs)
    except BaseException:
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


def _start_services(
    paths: Paths,
    ports: dict[str, int],
    secret_values: dict,
    env: dict,
    procs: dict[str, subprocess.Popen],
) -> None:
    procs["mongo"] = spawn(
        paths,
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
    )
    procs["redis"] = spawn(
        paths,
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
    )
    # Same `weed mini` as the Docker and pixi stacks. Its master, volume and filer
    # talk to each other over HTTP: pin them to loopback and keep them away from any
    # proxy in the environment, or they announce and dial the host's public address.
    s3_env = {k: v for k, v in os.environ.items() if k.lower() not in _PROXY_VARS}
    s3_env.update(
        {
            "NO_PROXY": "127.0.0.1,localhost",
            "AWS_ACCESS_KEY_ID": S3_USER,
            "AWS_SECRET_ACCESS_KEY": secret_values["s3_password"],
            "S3_BUCKET": S3_BUCKET,
        }
    )
    procs["s3"] = spawn(
        paths,
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
        ],
        env=s3_env,
    )

    wait_until(
        lambda: tcp_ready(ports["mongo"]), "MongoDB", 60, procs["mongo"], paths.logs / "mongo.log"
    )
    wait_until(
        lambda: tcp_ready(ports["redis"]), "Redis", 30, procs["redis"], paths.logs / "redis.log"
    )
    wait_until(
        lambda: http_ready(f"http://127.0.0.1:{ports['s3']}/healthz"),
        "SeaweedFS",
        60,
        procs["s3"],
        paths.logs / "s3.log",
    )

    procs["api"] = spawn(
        paths,
        "api",
        [
            sys.executable,
            "-m",
            "uvicorn",
            "depictio.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(ports["api"]),
            "--workers",
            "1",
        ],
        env=env,
    )
    procs["worker"] = spawn(
        paths,
        "worker",
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "depictio.api.celery_worker:celery_app",
            "worker",
            "--loglevel=info",
            *worker_pool_args(),
        ],
        env=env,
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
    paths: Paths, ports: dict[str, int], proc: subprocess.Popen, timeout: float = 300
) -> None:
    wait_until(
        lambda: api_healthy(ports["api"]),
        "the Depictio API",
        timeout,
        proc,
        paths.logs / "api.log",
    )
    # Written by the API when it creates the admin token, before /health answers.
    wait_until(
        paths.cli_config.exists,
        f"the CLI configuration ({paths.cli_config})",
        120,
        proc,
        paths.logs / "api.log",
    )
    sync_cli_config(paths, ports)


def sync_cli_config(paths: Paths, ports: dict[str, int]) -> bool:
    """Point the CLI configuration at this run's API and S3 ports; keep it owner-only.

    The API writes it only when it creates the admin token, on the first run, so
    after a port change it still names the old ports. Returns whether it changed.
    """
    import yaml

    config = yaml.safe_load(paths.cli_config.read_text()) or {}
    s3 = config.setdefault("s3_storage", {})
    url = f"http://127.0.0.1:{ports['api']}"
    changed = config.get("api_base_url") != url or any(
        s3.get(key) != ports["s3"] for key in ("service_port", "external_port")
    )
    if changed:
        config["api_base_url"] = url
        s3["service_port"] = s3["external_port"] = ports["s3"]
        # Replaced in one step, so a CLI reading it meanwhile never sees half a file.
        tmp = paths.cli_config.with_suffix(".tmp")
        write_private_file(tmp, yaml.safe_dump(config, default_flow_style=False, sort_keys=False))
        os.replace(tmp, paths.cli_config)
    paths.cli_config.chmod(0o600)
    return changed


def check_alive(paths: Paths, procs: dict[str, subprocess.Popen]) -> None:
    """Fail when a service died while the API was starting, e.g. a crashed worker."""
    for name, proc in procs.items():
        if proc.poll() is not None:
            raise LocalStackError(
                f"The {name} process exited during startup. See {paths.logs / f'{name}.log'}"
            )


def table_ready(url: str, token: str, dc_id: str) -> bool:
    """Whether the API has a Delta table for the data collection ``dc_id``."""
    request = urllib.request.Request(
        f"{url}/depictio/api/v1/deltatables/specs/{dc_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with _DIRECT.open(request, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def examples_loading(paths: Paths, state: State) -> list[str]:
    """The seeded examples whose Delta tables do not exist yet.

    The API loads them in a background thread once it has started, so /health
    answers first: on a first run they need a few more seconds.
    """
    import yaml

    names = [name for name in state.examples.split(",") if name in EXAMPLE_TABLES]
    if not names:
        return []
    try:
        config = yaml.safe_load(paths.cli_config.read_text())
        token = config["user"]["token"]["access_token"]
    except (OSError, KeyError, TypeError):
        return []
    return [
        name
        for name in names
        if not all(table_ready(state.url, token, dc_id) for dc_id in EXAMPLE_TABLES[name])
    ]


def wait_for_examples(
    paths: Paths, state: State, timeout: float = 120, interval: float = 1.0
) -> list[str]:
    """Wait for the seeded examples to load; returns the ones still missing at the timeout."""
    deadline = time.monotonic() + timeout
    missing = examples_loading(paths, state)
    while missing and time.monotonic() < deadline:
        time.sleep(interval)
        missing = examples_loading(paths, state)
    return missing


def terminate_group(pid: int, timeout: float = 20, alive=None) -> None:
    """Stop the process group ``pid`` leads: SIGTERM, up to ``timeout`` seconds, SIGKILL.

    Every service starts in its own session, so its group also holds what it forked
    (Celery pool processes, Chromium), which signalling ``pid`` alone leaves running.
    """
    alive = alive or (lambda: pid_alive(pid))
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        # Not a group leader: stop the process alone.
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
    deadline = time.monotonic() + timeout
    while alive() and time.monotonic() < deadline:
        time.sleep(0.2)
    # Whatever ignored SIGTERM, or outlived the leader.
    with contextlib.suppress(OSError):
        os.killpg(pid, signal.SIGKILL)
    if alive():
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)


def stop_all(paths: Paths, log=print) -> list[str]:
    """Stop the processes `up` recorded; returns the names of those that were running."""
    live = live_pids(State.load(paths))
    stopped = [name for name in reversed(PROCESS_ORDER) if name in live]
    for name in stopped:
        log(f"Stopping {name} (pid {live[name]})")
        terminate_group(live[name])
    paths.state.unlink(missing_ok=True)
    return stopped


def running_status(paths: Paths) -> dict[str, bool]:
    live = live_pids(State.load(paths))
    return {name: name in live for name in PROCESS_ORDER}


def check_server_installed() -> None:
    missing = [
        mod for mod in ("fastapi", "uvicorn", "celery", "depictio.api") if not _importable(mod)
    ]
    if missing:
        raise LocalStackError(
            "The Depictio server is not installed in this environment "
            f'(missing: {", ".join(missing)}). Install it with: uv tool install "depictio[local]"'
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
    return root is not None and (root / "viewer" / "dist" / "index.html").is_file()


def seed_screenshots(paths: Paths) -> None:
    """Copy the thumbnails shipped for the reference dashboards, once."""
    root = package_root()
    if root is None:
        return
    bundled = root / "api" / "static" / "screenshots"
    target = paths.home / "screenshots"
    for png in bundled.glob("*.png"):
        if not (target / png.name).exists():
            shutil.copy2(png, target / png.name)


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
    return result.returncode == 0


def install_chromium() -> None:
    if subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"]) != 0:
        raise LocalStackError("Could not install Chromium for dashboard thumbnails")


def reset(paths: Paths) -> None:
    """Delete all local data but keep the downloaded binaries."""
    for sub in DATA_DIRS:
        shutil.rmtree(paths.home / sub, ignore_errors=True)
    for f in (paths.state, paths.secrets, paths.ports):
        f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# up: start the stack, ingest a template
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

    Leftovers of an earlier run are stopped first. On any error, Ctrl-C included,
    what this call started is stopped again before the error propagates.
    """
    warn = warn or log
    try:
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
        state = State(ports=ports, home=str(paths.home), examples=seed)
        state.save(paths)
        procs = start_services(paths, ports, secret_values, env)
        state.pids = {name: proc.pid for name, proc in procs.items()}
        state.start_times = {name: process_start_time(proc.pid) for name, proc in procs.items()}
        state.save(paths)
        log(f"Services started (logs in {paths.logs}); waiting for the API")
        wait_for_api(paths, ports, procs["api"])
        check_alive(paths, procs)
    except BaseException:
        stop_all(paths, log=log)
        raise
    return state


def ingest(
    paths: Paths,
    template: str,
    data_root: Path,
    variables: list[str] | None = None,
    project_name: str | None = None,
) -> int:
    """Ingest ``data_root`` into the local server with `depictio run`; returns its exit code."""
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
    return subprocess.call(cmd, env=_ingestion_env())


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
