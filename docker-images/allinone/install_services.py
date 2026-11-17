"""Build step: install MongoDB, Redis and SeaweedFS from conda-forge into a prefix,
exactly as `depictio local up` does into <home>/env (ensure_binaries), then prune.

The specs are read from depictio/cli/cli/local_stack.py (CONDA_SPECS) so the image
and `depictio local up` of the same depictio version run the same series: MongoDB
only opens data of its own series. Override with SERVICES_SPECS="mongodb 8.0.23 ...;".

    python install_services.py <local_stack.py> <prefix> [--solve-only]
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

# Not needed to serve a home: mongos (150 MB), the Redis modules (190 MB; redis-server
# loads none without a config asking for them), benchmarks, headers, docs.
PRUNE = [
    "bin/mongos",
    "bin/redis-benchmark",
    "bin/redis-check-aof",
    "bin/redis-check-rdb",
    "bin/redis-sentinel",
    "lib/redis",
    "include",
    "share/man",
    "share/doc",
    "lib/cmake",
    "lib/pkgconfig",
]


def conda_specs(local_stack: Path) -> list[str]:
    override = os.environ.get("SERVICES_SPECS", "").strip()
    if override:
        return [s.strip() for s in override.split(";") if s.strip()]
    tree = ast.parse(local_stack.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "CONDA_SPECS" for t in node.targets
        ):
            return list(ast.literal_eval(node.value))
    raise SystemExit(f"No CONDA_SPECS in {local_stack}")


def main() -> None:
    from rattler import Platform, VirtualPackage, install, solve

    local_stack, prefix = Path(sys.argv[1]), Path(sys.argv[2])
    specs = conda_specs(local_stack)
    platform = str(Platform.current())
    print(f"Solving {specs} for {platform}", flush=True)

    async def run() -> None:
        records = await solve(
            sources=["conda-forge"], specs=specs, virtual_packages=VirtualPackage.detect()
        )
        for r in records:
            if r.name.normalized in ("mongodb", "redis-server", "seaweedfs"):
                print(f"  {r.name.normalized} {r.version}", flush=True)
        if "--solve-only" in sys.argv:
            return
        await install(records=records, target_prefix=str(prefix), show_progress=False)

    asyncio.run(run())
    if "--solve-only" in sys.argv:
        return
    # The marker ensure_binaries writes, so the prefix reads like a local home's env/.
    (prefix / ".depictio-specs.json").write_text(json.dumps({"specs": specs, "platform": platform}))
    for rel in PRUNE:
        path = prefix / rel
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
    # rattler writes conda-meta/*.json owner-only; the entrypoint (any uid) reads the
    # mongodb record to compare it with the series that wrote the data.
    for root, dirs, files in os.walk(prefix):
        for name in dirs + files:
            p = Path(root, name)
            if not p.is_symlink():
                mode = p.stat().st_mode
                p.chmod(mode | 0o444 | (0o111 if mode & 0o100 or p.is_dir() else 0))
    for binary in ("mongod", "redis-server", "weed"):
        if not (prefix / "bin" / binary).is_file():
            raise SystemExit(f"{binary} missing from {prefix}/bin")


if __name__ == "__main__":
    main()
