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
from dataclasses import dataclass
from pathlib import Path

CONDA_SPECS = ["mongodb 8.0.*", "redis-server", "seaweedfs"]
ADMIN_EMAIL = "admin@example.com"
S3_USER = "depictio"
S3_BUCKET = "depictio-bucket"

DEFAULT_PORTS = {"api": 8058, "mongo": 27018, "redis": 6379, "s3": 9000}
# Start order; stopped in reverse.
PROCESS_ORDER = ["mongo", "redis", "s3", "api", "worker"]
# The example projects shipped in the wheel, seeded by --examples.
EXAMPLES = ("iris", "penguins")


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
        for sub in (
            "logs",
            "mongo",
            "redis",
            "s3",
            "keys",
            "cli",
            "cache",
            "multiqc_prerender",
            "screenshots",
        ):
            (self.home / sub).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Native binaries (conda-forge via py-rattler)
# ---------------------------------------------------------------------------


def _env_marker(paths: Paths) -> Path:
    return paths.env / ".depictio-specs.json"


def ensure_binaries(paths: Paths, log=print) -> None:
    try:
        from rattler import Platform, VirtualPackage, install, solve
    except ImportError as exc:
        raise LocalStackError(
            "py-rattler is required to fetch MongoDB, Redis and SeaweedFS. "
            "Install the local extra: uvx --python 3.12 --from 'depictio[local]' depictio local up"
        ) from exc

    # The platform is part of the marker: a $HOME shared between linux-64 and
    # linux-aarch64 hosts, or a Python switched between Rosetta and native on a
    # Mac, must not reuse binaries built for the other architecture.
    wanted = {"specs": CONDA_SPECS, "platform": str(Platform.current())}
    marker = _env_marker(paths)
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


_PROXY_VARS = {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}


def load_state(paths: Paths) -> dict:
    if not paths.state.exists():
        return {}
    return json.loads(paths.state.read_text())


def save_state(paths: Paths, state: dict) -> None:
    paths.state.write_text(json.dumps(state, indent=2))


def load_secrets(paths: Paths) -> dict:
    if paths.secrets.exists():
        return json.loads(paths.secrets.read_text())
    values = {
        "s3_password": secrets.token_urlsafe(24),
        "admin_password": secrets.token_urlsafe(24),
    }
    # Created owner-only rather than chmod-ed afterwards, so it is never readable by others.
    fd = os.open(paths.secrets, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(values))
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
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


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
    except (OSError, ProcessLookupError):
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


def live_pids(state: dict) -> dict[str, int]:
    """The recorded PIDs that still belong to the processes `up` started.

    state.json survives a reboot, after which a PID can name an unrelated process:
    one whose start time differs from the recorded one counts as gone.
    """
    start_times = state.get("start_times", {})
    live: dict[str, int] = {}
    for name, pid in state.get("pids", {}).items():
        if not pid_alive(pid):
            continue
        recorded, current = start_times.get(name), process_start_time(pid)
        # Without a record (older state) or without psutil, only liveness is checked.
        if recorded is None or current is None or abs(current - recorded) < _START_TIME_SLACK:
            live[name] = pid
    return live


def spawn(paths: Paths, name: str, cmd: list[str], env: dict | None = None) -> subprocess.Popen:
    log_file = open(paths.logs / f"{name}.log", "ab")  # noqa: SIM115 - handed to the child
    proc = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        cwd=paths.home,
        start_new_session=True,
    )
    log_file.close()
    return proc


def wait_until(
    check, what: str, timeout: float, proc: subprocess.Popen | None = None, log_path=None
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        # poll() rather than kill(pid, 0): an unreaped child stays visible as a zombie.
        if proc is not None and proc.poll() is not None:
            hint = f" See {log_path}" if log_path else ""
            if proc.returncode == -signal.SIGILL:
                hint += (
                    " It was killed by an illegal instruction: MongoDB 5+ needs AVX on "
                    "x86_64 and ARMv8.2-A on arm64 (not available on e.g. a Raspberry Pi 4)."
                )
            raise LocalStackError(f"{what} exited during startup.{hint}")
        time.sleep(0.5)
    hint = f" See {log_path}" if log_path else ""
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
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            yaml.safe_dump(config, fh, default_flow_style=False, sort_keys=False)
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
    live = live_pids(load_state(paths))
    stopped = [name for name in reversed(PROCESS_ORDER) if name in live]
    for name in stopped:
        log(f"Stopping {name} (pid {live[name]})")
        terminate_group(live[name])
    if paths.state.exists():
        paths.state.unlink()
    return stopped


def running_status(paths: Paths) -> dict[str, bool]:
    live = live_pids(load_state(paths))
    return {name: name in live for name in PROCESS_ORDER}


def check_server_installed() -> None:
    missing = [
        mod for mod in ("fastapi", "uvicorn", "celery", "depictio.api") if not _importable(mod)
    ]
    if missing:
        raise LocalStackError(
            "The Depictio server is not installed in this environment "
            f"(missing: {', '.join(missing)}). Use: uvx --python 3.12 --from 'depictio[local]' depictio local up"
        )


def _importable(module: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


def _package_root() -> Path | None:
    import importlib.util

    spec = importlib.util.find_spec("depictio")
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations)))


def viewer_built() -> bool:
    root = _package_root()
    return root is not None and (root / "viewer" / "dist" / "index.html").is_file()


def seed_screenshots(paths: Paths) -> None:
    """Copy the thumbnails shipped for the reference dashboards, once."""
    root = _package_root()
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
    for sub in (
        "mongo",
        "redis",
        "s3",
        "keys",
        "cli",
        "cache",
        "multiqc_prerender",
        "screenshots",
        "logs",
    ):
        shutil.rmtree(paths.home / sub, ignore_errors=True)
    for f in (paths.state, paths.secrets, paths.ports):
        if f.exists():
            f.unlink()


# ---------------------------------------------------------------------------
# Hand-over to Docker Compose
# ---------------------------------------------------------------------------

COMPOSE_URL = "https://raw.githubusercontent.com/depictio/depictio/stable/docker-compose.yaml"
# Data carried over. Redis holds only cache and queue, and thumbnails are re-rendered.
EXPORTED_DIRS = ("mongo", "s3")
KEY_FILES = ("private_key.pem", "public_key.pem", "api_internal_key.pem")


def installed_version(paths: Paths, package: str) -> str:
    """Version of a conda-forge package in ``<home>/env``, read from its conda-meta record."""
    for record in (paths.env / "conda-meta").glob(f"{package}-*.json"):
        meta = json.loads(record.read_text())
        if meta.get("name") == package:
            return meta["version"]
    raise LocalStackError(
        f"{package} is not installed under {paths.env}; run `depictio local up` once"
    )


def compose_override(mongo_version: str, seaweedfs_version: str, user: str | None) -> str:
    """The override that points the stock docker-compose.yaml at the exported data.

    Mongo and SeaweedFS run the exact versions the local server wrote the data
    with. Paths are relative to the export directory, so it can be moved. The key
    files are mounted one by one over the keys volume: the API also writes a lock
    file next to them, which a bind-mounted directory owned by the host user would
    refuse to the image's own user.
    """
    run_as = f'    user: "{user}"\n' if user else ""
    keys = "".join(
        f"      - ./data/keys/{name}:/app/depictio/keys/{name}:ro\n" for name in KEY_FILES
    )
    return (
        "# Generated by `depictio local export-compose`: the Docker stack on the data\n"
        "# of a local server. docker compose reads it next to docker-compose.yaml.\n"
        "services:\n"
        "  mongo:\n"
        f"    image: mongo:{mongo_version}\n"
        f"{run_as}"
        "    volumes:\n"
        "      - ./data/mongo:/data/db\n"
        "  s3:\n"
        f"    image: chrislusf/seaweedfs:{seaweedfs_version}\n"
        f"{run_as}"
        "    volumes:\n"
        "      - ./data/s3:/data\n"
        "  depictio-backend:\n"
        "    volumes:\n"
        f"{keys}"
        "  depictio-celery-worker:\n"
        "    volumes:\n"
        f"{keys}"
    )


def compose_env(secret_values: dict, version: str | None) -> str:
    lines = [
        "# Generated by `depictio local export-compose`: the local server's credentials.",
        "DEPICTIO_AUTH_SINGLE_USER_MODE=true",
        f"DEPICTIO_S3_ROOT_USER={S3_USER}",
        f"DEPICTIO_S3_ROOT_PASSWORD={secret_values['s3_password']}",
        f"DEPICTIO_S3_BUCKET={S3_BUCKET}",
        f"DEPICTIO_BOOTSTRAP_ADMIN_EMAIL={ADMIN_EMAIL}",
        f"DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD={secret_values['admin_password']}",
    ]
    if version:
        lines.append(f"DEPICTIO_VERSION={version}")
    return "\n".join(lines) + "\n"


def release_version() -> str | None:
    """The installed depictio version when it names a published image, else None.

    Read from the package metadata: the CLI-only package (depictio-cli) does not
    ship depictio.version, and both packages carry the same version number.
    """
    import re
    from importlib.metadata import PackageNotFoundError, version

    for dist in ("depictio", "depictio-cli"):
        try:
            found = version(dist)
        except PackageNotFoundError:
            continue
        return found if re.fullmatch(r"\d+\.\d+\.\d+", found) else None
    return None


def _rebind_seaweedfs(options: Path) -> None:
    """Open the copied SeaweedFS to the Compose network.

    ``weed mini`` saves its flags in ``mini.options`` and reloads them, so the copy
    would keep listening on the container's loopback only. ``ip`` stays: the
    master's raft state is keyed on it, and every SeaweedFS component shares the
    one container.
    """
    if not options.is_file():
        return
    pinned = {"ip.bind": "0.0.0.0", "s3.port": "9000"}
    lines = [
        line
        for line in options.read_text().splitlines()
        if line.partition("=")[0].strip() not in pinned
    ]
    options.write_text("\n".join([*lines, *(f"{k}={v}" for k, v in pinned.items())]) + "\n")


def export_compose(paths: Paths, out: Path, log=print) -> bool:
    """Copy the local server's data into ``out`` with what Docker Compose needs to run it.

    The data is copied, not shared: MongoDB must never run twice on one data
    directory, and the local server stays usable. Returns whether a
    docker-compose.yaml was copied next to the export (from a source checkout).
    """
    if any(running_status(paths).values()):
        raise LocalStackError(
            "The local server is running: stop it with `depictio local down` first"
        )
    if not any((paths.home / "mongo").glob("*")):
        raise LocalStackError(f"No local server data under {paths.home}")
    if out.exists() and any(out.iterdir()):
        raise LocalStackError(f"{out} is not empty")
    secret_values = load_secrets(paths)
    override = compose_override(
        installed_version(paths, "mongodb"),
        installed_version(paths, "seaweedfs"),
        # Bind-mounted data stays owned by the host user, so the database and
        # the object store run as that user rather than the images' own.
        f"{os.getuid()}:{os.getgid()}" if sys.platform == "linux" else None,
    )

    data = out / "data"
    for sub in EXPORTED_DIRS:
        log(f"Copying {sub} data")
        shutil.copytree(paths.home / sub, data / sub)
    _rebind_seaweedfs(data / "s3" / "mini.options")
    (data / "keys").mkdir(parents=True)
    for name in KEY_FILES:
        shutil.copy2(paths.home / "keys" / name, data / "keys" / name)

    (out / "docker-compose.override.yaml").write_text(override)
    fd = os.open(out / ".env", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(compose_env(secret_values, release_version()))

    root = _package_root()
    compose = root.parent / "docker-compose.yaml" if root is not None else None
    if compose is not None and compose.is_file():
        shutil.copy2(compose, out / "docker-compose.yaml")
        return True
    return False
