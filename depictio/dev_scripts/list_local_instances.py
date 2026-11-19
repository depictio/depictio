"""List the Docker-free `depictio local` instances found on this machine.

Each instance keeps its own home (`~/.depictio/local`, `~/.depictio/local-<name>`, ...)
with a `state.json` that records the pid and port of every service it started. This
script reads those files, checks which pids are still alive and whether the API answers,
so stale homes and port clashes between instances are visible at a glance.

Standard library only: run it with any Python 3, no install needed.

    python depictio/dev_scripts/list_local_instances.py
    python depictio/dev_scripts/list_local_instances.py --all --no-probe
    python depictio/dev_scripts/list_local_instances.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path.home() / ".depictio"
HOME_PREFIX = "local"


@dataclass
class Instance:
    name: str
    home: Path
    url: str
    ports: dict[str, int]
    pids: dict[str, int]
    alive: dict[str, bool]
    api_ok: bool | None  # None when the probe was skipped

    @property
    def status(self) -> str:
        if self.alive and all(self.alive.values()):
            return "running"
        if any(self.alive.values()):
            return "partial"
        return "stopped"


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def api_responds(port: int, timeout: float) -> bool:
    url = f"http://127.0.0.1:{port}/depictio/api/v1/utils/status"
    try:
        with urllib.request.urlopen(url, timeout=timeout):  # noqa: S310
            return True
    except urllib.error.HTTPError:
        # Any HTTP answer means the API process is serving.
        return True
    except (urllib.error.URLError, OSError):
        return False


def is_home(path: Path) -> bool:
    return path.is_dir() and (path.name == HOME_PREFIX or path.name.startswith(f"{HOME_PREFIX}-"))


def find_homes(root: Path) -> list[Path]:
    homes = [p for p in sorted(root.iterdir()) if is_home(p)] if root.is_dir() else []
    extra = os.environ.get("DEPICTIO_LOCAL_HOME")
    if extra and Path(extra).expanduser() not in homes:
        homes.append(Path(extra).expanduser())
    return homes


def load_instance(home: Path, probe: bool, timeout: float) -> Instance | None:
    state_file = home / "state.json"
    if not state_file.is_file():
        return None
    try:
        state = json.loads(state_file.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    pids = {k: int(v) for k, v in state.get("pids", {}).items()}
    ports = {k: int(v) for k, v in state.get("ports", {}).items()}
    alive = {k: pid_alive(v) for k, v in pids.items()}
    api_port = ports.get("api")
    api_ok = api_responds(api_port, timeout) if probe and api_port and alive.get("api") else None
    return Instance(
        name=home.name,
        home=home,
        url=state.get("url", f"http://127.0.0.1:{api_port}" if api_port else ""),
        ports=ports,
        pids=pids,
        alive=alive,
        api_ok=api_ok,
    )


def port_clashes(instances: list[Instance]) -> dict[int, list[str]]:
    """Ports declared by several instances that are running (or partly) at once."""
    owners: dict[int, list[str]] = {}
    for inst in instances:
        if inst.status == "stopped":
            continue
        for port in inst.ports.values():
            owners.setdefault(port, []).append(inst.name)
    return {port: names for port, names in owners.items() if len(names) > 1}


def render_table(instances: list[Instance]) -> str:
    rows = [("INSTANCE", "STATUS", "API", "URL", "PORTS (api/mongo/redis/s3)", "SERVICES UP")]
    for inst in instances:
        api = {True: "ok", False: "no answer", None: "-"}[inst.api_ok]
        ports = "/".join(str(inst.ports.get(s, "-")) for s in ("api", "mongo", "redis", "s3"))
        up = f"{sum(inst.alive.values())}/{len(inst.alive)}"
        rows.append((inst.name, inst.status, api, inst.url, ports, up))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"folder holding the homes (default {DEFAULT_ROOT})",
    )
    parser.add_argument("--all", action="store_true", help="also list stopped instances")
    parser.add_argument("--no-probe", action="store_true", help="do not call the API")
    parser.add_argument("--timeout", type=float, default=1.0, help="API probe timeout in seconds")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    instances = [
        inst
        for home in find_homes(args.root.expanduser())
        if (inst := load_instance(home, not args.no_probe, args.timeout))
    ]
    shown = instances if args.all else [i for i in instances if i.status != "stopped"]
    clashes = port_clashes(instances)

    if args.json:
        payload = [
            {
                "name": i.name,
                "home": str(i.home),
                "status": i.status,
                "url": i.url,
                "ports": i.ports,
                "pids": i.pids,
                "api_ok": i.api_ok,
            }
            for i in shown
        ]
        print(json.dumps({"instances": payload, "port_clashes": clashes}, indent=2))
        return 0

    if not shown:
        hidden = len(instances) - len(shown)
        print(
            f"No running local instance under {args.root}."
            + (f" {hidden} stopped (use --all)." if hidden else "")
        )
        return 0
    print(render_table(shown))
    for port, names in sorted(clashes.items()):
        print(f"\nwarning: port {port} is declared by {', '.join(names)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
