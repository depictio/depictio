"""The hardware profile a set of measurements was taken under.

A latency figure without the machine and the container limits it was taken on is
not a result — it cannot be compared to anything, including a later run of the
same harness. Every row the runner emits carries a ``profile_label``, and the
full profile is written once per run so the report can stamp it.

Everything here is read-only and cheap: ``sysctl``/``sw_vers`` for the host, and
a plain YAML *file read* for the Colima VM (deliberately not ``colima``/``docker``
commands). Per-service limits come from the same ``BENCH_*`` variables
``docker-compose.bench.yaml`` reads, so the profile records what the stack was
actually booted with rather than a hand-typed claim — as long as the benchmark
process is launched with the same variables exported.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

COLIMA_CONFIG = Path.home() / ".colima" / "default" / "colima.yaml"
# Repo-root compose override — read (never executed) to learn whether the backend
# is in dev mode, which silently caps uvicorn at one worker.
COMPOSE_OVERRIDE = Path(__file__).resolve().parent.parent / "docker-compose.override.yaml"

# Reported key -> environment variable read by docker-compose.bench.yaml, and
# the default that file falls back to.
_SERVICE_LIMITS: tuple[tuple[str, str, str], ...] = (
    ("api_cpus", "BENCH_API_CPUS", "4"),
    ("api_workers", "BENCH_API_WORKERS", "4"),
    ("celery_cpus", "BENCH_CELERY_CPUS", "4"),
    ("celery_workers", "BENCH_CELERY_WORKERS", "4"),
    ("mongo_cpus", "BENCH_MONGO_CPUS", "2"),
)


def _sysctl(key: str) -> str:
    try:
        out = subprocess.run(
            ["sysctl", "-n", key], capture_output=True, text=True, timeout=5, check=False
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _host() -> dict[str, Any]:
    mem_raw = _sysctl("hw.memsize")
    try:
        mem_gb = round(int(mem_raw) / 1024**3, 1) if mem_raw else None
    except ValueError:
        mem_gb = None
    try:
        os_version = subprocess.run(
            ["sw_vers", "-productVersion"], capture_output=True, text=True, timeout=5, check=False
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        os_version = ""
    return {
        "model": _sysctl("hw.model"),
        "chip": _sysctl("machdep.cpu.brand_string"),
        "cpus": _sysctl("hw.ncpu"),
        "memory_gb": mem_gb,
        "os_version": os_version,
    }


def _colima(config_path: Path = COLIMA_CONFIG) -> dict[str, Any]:
    """vCPU / RAM / disk of the VM the containers run in.

    Read from Colima's own config file rather than by shelling out, so this
    works the same whether or not the VM is running and stays inert.
    """
    if not config_path.exists():
        return {}
    try:
        import yaml

        raw = yaml.safe_load(config_path.read_text()) or {}
    except Exception:
        return {}
    return {
        "vcpu": raw.get("cpu"),
        "memory_gb": raw.get("memory"),
        "disk_gb": raw.get("disk"),
        "vm_type": raw.get("vmType"),
    }


def _dev_mode(override_path: Path = COMPOSE_OVERRIDE) -> bool:
    """Whether the backend is booted with ``DEPICTIO_DEV_MODE=true``.

    This decides how many uvicorn workers actually exist:
    ``docker-images/run_fastapi.sh`` runs ``uvicorn --reload`` with a **single**
    worker in dev mode and ignores ``DEPICTIO_FASTAPI_WORKERS`` entirely. A
    profile that repeats the requested worker count would describe a stack that
    isn't running — and the difference is exactly what decides whether N
    concurrent renders share their memory across processes or pile into one.
    """
    if not override_path.exists():
        return False
    text = override_path.read_text()
    return "DEPICTIO_DEV_MODE=true" in text or 'DEPICTIO_DEV_MODE: "true"' in text


def collect_profile(label: str) -> dict[str, Any]:
    """Build the profile dict for this run.

    Per-service limits come from the environment — the same ``BENCH_*`` variables
    ``docker-compose.bench.yaml`` reads — falling back to that file's defaults.
    Export them for the benchmark process as well as for compose, or the profile
    records the defaults rather than what the stack is running under.
    """
    limits = {key: str(os.environ.get(env) or default) for key, env, default in _SERVICE_LIMITS}
    dev_mode = _dev_mode()
    if dev_mode:
        # What was asked for is kept, but the effective count is what the numbers
        # were measured under.
        limits["api_workers_requested"] = limits["api_workers"]
        limits["api_workers"] = "1"
    return {
        "label": label,
        "host": _host(),
        "vm": _colima(),
        "service_limits": limits,
        "dev_mode": dev_mode,
    }


def write_profile(output_root: str | Path, profile: dict[str, Any]) -> Path:
    """Persist the profile next to the results. Returns the written path."""
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "hardware_profile.json"
    path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return path


def read_profile(output_root: str | Path) -> dict[str, Any]:
    """Read back a written profile; ``{}`` if the run predates profile stamping."""
    path = Path(output_root) / "hardware_profile.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def describe(profile: dict[str, Any]) -> list[str]:
    """Markdown lines describing a profile — shared by report and blog snippet."""
    if not profile:
        return ["_No hardware profile recorded for this run._"]
    host = profile.get("host") or {}
    vm = profile.get("vm") or {}
    limits = profile.get("service_limits") or {}
    # Dev mode runs uvicorn --reload with one worker whatever
    # DEPICTIO_FASTAPI_WORKERS says, so N concurrent renders share one process's
    # memory instead of N. Saying so is part of the measurement.
    workers_note = ""
    if profile.get("dev_mode"):
        requested = limits.get("api_workers_requested")
        workers_note = (
            f" — dev mode: uvicorn --reload, single worker"
            f"{f' ({requested} requested, ignored)' if requested else ''}"
        )
    return [
        f"- **Profile**: `{profile.get('label', 'unlabelled')}`",
        f"- **Host**: {host.get('model', '?')} — {host.get('chip', '?')}, "
        f"{host.get('cpus', '?')} CPU, {host.get('memory_gb', '?')} GB RAM, "
        f"macOS {host.get('os_version', '?')}",
        f"- **VM (Colima {vm.get('vm_type', '?')})**: {vm.get('vcpu', '?')} vCPU, "
        f"{vm.get('memory_gb', '?')} GB RAM, {vm.get('disk_gb', '?')} GB disk",
        f"- **Container limits**: API {limits.get('api_cpus', '?')} CPU / "
        f"{limits.get('api_workers', '?')} worker(s){workers_note} · Celery "
        f"{limits.get('celery_cpus', '?')} CPU / {limits.get('celery_workers', '?')} workers · "
        f"Mongo {limits.get('mongo_cpus', '?')} CPU",
    ]
