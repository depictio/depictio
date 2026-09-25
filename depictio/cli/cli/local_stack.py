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


class LocalStackError(RuntimeError):
    pass


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
    def cli_config(self) -> Path:
        return self.home / "cli" / f"{ADMIN_EMAIL.split('@')[0]}_config.yaml"

    def bin(self, name: str) -> Path:
        if sys.platform == "win32":
            return self.env / "Library" / "bin" / f"{name}.exe"
        return self.env / "bin" / name

    def ensure_dirs(self) -> None:
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
    marker = _env_marker(paths)
    if marker.exists() and json.loads(marker.read_text()) == CONDA_SPECS:
        return
    try:
        from rattler import VirtualPackage, install, solve
    except ImportError as exc:
        raise LocalStackError(
            "py-rattler is required to fetch MongoDB, Redis and SeaweedFS. "
            "Install the local extra: uvx --python 3.12 --from 'depictio[local]' depictio local up"
        ) from exc

    async def _install() -> None:
        records = await solve(
            sources=["conda-forge"],
            specs=CONDA_SPECS,
            virtual_packages=VirtualPackage.detect(),
        )
        await install(records=records, target_prefix=str(paths.env), show_progress=False)

    log(f"Installing {', '.join(CONDA_SPECS)} from conda-forge into {paths.env} (first run only)")
    start = time.monotonic()
    asyncio.run(_install())
    marker.write_text(json.dumps(CONDA_SPECS))
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
    paths.secrets.write_text(json.dumps(values))
    paths.secrets.chmod(0o600)
    return values


def port_is_free(port: int) -> bool:
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


def pick_ports(api_port: int | None) -> dict[str, int]:
    ports: dict[str, int] = {}
    for name, preferred in DEFAULT_PORTS.items():
        if name == "api" and api_port:
            if not port_is_free(api_port):
                raise LocalStackError(f"Port {api_port} is already in use")
            ports[name] = api_port
        else:
            ports[name] = pick_port(preferred, set(ports.values()))
    return ports


# ---------------------------------------------------------------------------
# Environment shared by the API and the worker
# ---------------------------------------------------------------------------


def server_env(
    paths: Paths, ports: dict[str, int], secret_values: dict, seed: str, screenshots: bool
) -> dict:
    host = "127.0.0.1"
    env = {k: v for k, v in os.environ.items() if not k.startswith("DEPICTIO_")}
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
    elif seed != "all":
        env["DEPICTIO_SEED_PROJECTS"] = seed
    return env


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


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


def http_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status < 500
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


def _stop_child(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()


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
            "--concurrency=2",
            "--max-tasks-per-child=50",
        ],
        env=env,
    )


def wait_for_api(
    paths: Paths, ports: dict[str, int], proc: subprocess.Popen, timeout: float = 300
) -> None:
    wait_until(
        lambda: http_ready(f"http://127.0.0.1:{ports['api']}/health"),
        "the Depictio API",
        timeout,
        proc,
        paths.logs / "api.log",
    )
    wait_until(
        paths.cli_config.exists,
        f"the CLI configuration ({paths.cli_config})",
        120,
        proc,
        paths.logs / "api.log",
    )


def stop_pid(pid: int, timeout: float = 20) -> None:
    if not pid_alive(pid):
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return
        time.sleep(0.2)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


def stop_all(paths: Paths, log=print) -> None:
    state = load_state(paths)
    pids = state.get("pids", {})
    for name in reversed(PROCESS_ORDER):
        pid = pids.get(name)
        if pid_alive(pid):
            log(f"Stopping {name} (pid {pid})")
            stop_pid(pid)
    if paths.state.exists():
        paths.state.unlink()


def running_status(paths: Paths) -> dict[str, bool]:
    pids = load_state(paths).get("pids", {})
    return {name: pid_alive(pids.get(name)) for name in PROCESS_ORDER}


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
    for f in (paths.state, paths.secrets):
        if f.exists():
            f.unlink()
