"""Pinned Pyodide assets for the optional Python runtime add-on (RFC §13.6).

Everything a bundle's Python-in-WASM runtime needs is pinned in ``pin.json``
(Pyodide 314.0.7, CPython 3.14.2): the core files and the lock by sha256, the
packages by the lock's own sha256, and two pure-Python wheels from PyPI
(plotly 6.9.0 — the server's version — and RestrictedPython 8.4) by theirs.

The files are not in the wheel (tens of MB). The producer downloads them once,
verifies every hash, and caches them under ``DEPICTIO_PYODIDE_CACHE``
(``~/.cache/depictio/pyodide/<version>`` by default). An air-gapped instance
points ``DEPICTIO_PYODIDE_DIR`` at a directory holding the same file names; it
is then read only, never written. A view of the bundle makes zero requests: the
runtime decodes the inlined assets and serves them to Pyodide from memory.

``estimate_bytes`` sizes the add-on from ``pin.json`` alone, so the preflight
and the export modal can state the cost before anything is downloaded.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import os
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PIN_PATH = Path(__file__).with_name("pin.json")
CACHE_ENV = "DEPICTIO_PYODIDE_CACHE"
DIR_ENV = "DEPICTIO_PYODIDE_DIR"

#: What each Python job needs, beyond the core. ``code_figure`` runs the
#: server's code executor (polars frame, plotly, RestrictedPython); the others
#: run the server's own compute functions over a polars frame.
FEATURE_PACKAGES: dict[str, tuple[str, ...]] = {
    "base": ("numpy", "polars"),
    # The server's code executor builds its write guard from pandas types at
    # import time, so pandas comes with every code figure.
    "code_figure": ("narwhals", "packaging", "pandas"),
    "group_compare": ("scipy",),
    "embedding": (),
    "embedding_tsne": ("scikit-learn",),
}
FEATURE_EXTRAS: dict[str, tuple[str, ...]] = {"code_figure": ("plotly", "restrictedpython")}


class PyodideAssetError(RuntimeError):
    """A pinned asset could not be obtained or did not match its hash."""


def pin() -> dict[str, Any]:
    return json.loads(PIN_PATH.read_text())


def version() -> str:
    return str(pin()["version"])


def _lock_packages() -> dict[str, Any]:
    return json.loads(_read("pyodide-lock.json", pin()["lock"]["sha256"]))["packages"]


def closure(names: set[str] | list[str] | tuple[str, ...]) -> list[str]:
    """Package names plus their dependencies, dependencies first (from pin.json)."""
    packages = pin()["packages"]
    # Dependencies from the lock are needed only to order; pin.json carries the
    # closures of every package it lists, so resolve against the lock lazily.
    deps: dict[str, list[str]] = {
        "pandas": ["numpy", "python-dateutil", "pytz"],
        "python-dateutil": ["six"],
        "scipy": ["numpy"],
        "scikit-learn": ["scipy", "joblib", "threadpoolctl"],
    }
    out: list[str] = []

    def add(name: str) -> None:
        if name in out:
            return
        for dep in deps.get(name, []):
            add(dep)
        if name not in packages:
            raise PyodideAssetError(f"package {name!r} is not pinned in {PIN_PATH.name}")
        out.append(name)

    for name in names:
        add(name)
    return out


def features_packages(features: set[str]) -> tuple[list[str], list[str]]:
    """``(packages, extras)`` for a set of job features."""
    wanted: list[str] = list(FEATURE_PACKAGES["base"])
    extras: list[str] = []
    for feature in sorted(features):
        wanted.extend(FEATURE_PACKAGES.get(feature, ()))
        for extra in FEATURE_EXTRAS.get(feature, ()):
            if extra not in extras:
                extras.append(extra)
    return closure(wanted), extras


def estimate_bytes(features: set[str]) -> int:
    """HTML bytes the add-on adds for these features (base64 of what is inlined)."""
    p = pin()
    packages, extras = features_packages(features)
    return (
        sum(int(v["embedded_bytes"]) for v in p["core"].values())
        + sum(int(p["packages"][n]["embedded_bytes"]) for n in packages)
        + sum(int(p["extras"][n]["embedded_bytes"]) for n in extras)
        + 64 * 1024  # pruned lock, bootstrap modules, glue
    )


# --- fetching -------------------------------------------------------------------


def _cache_dir() -> Path:
    override = os.environ.get(CACHE_ENV)
    base = Path(override) if override else Path.home() / ".cache" / "depictio" / "pyodide"
    return base / version()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(name: str, sha256: str, url: str | None = None) -> bytes:
    """One pinned file: from DEPICTIO_PYODIDE_DIR, the cache, or the network."""
    fixed = os.environ.get(DIR_ENV)
    candidates = [Path(fixed) / name] if fixed else []
    cached = _cache_dir() / name
    candidates.append(cached)
    for path in candidates:
        if path.is_file():
            data = path.read_bytes()
            if _sha(data) == sha256:
                return data
            if fixed and path.parent == Path(fixed):
                raise PyodideAssetError(f"{path} does not match its pinned sha256")
    if fixed:
        raise PyodideAssetError(f"{name} is not in {DIR_ENV}={fixed}")
    source = url or pin()["base_url"] + name
    try:
        with urllib.request.urlopen(source, timeout=120) as resp:  # noqa: S310 - pinned https URL
            data = resp.read()
    except Exception as exc:
        raise PyodideAssetError(f"could not download {source}: {exc}") from exc
    if _sha(data) != sha256:
        raise PyodideAssetError(f"{source} does not match its pinned sha256")
    cached.parent.mkdir(parents=True, exist_ok=True)
    tmp = cached.with_suffix(cached.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(cached)
    return data


def _stripped_plotly(raw: bytes, strip: list[str]) -> bytes:
    """The plotly wheel without what a bundle never reads (its own plotly.js, the
    Jupyter widget bundle and lab extension, the sample datasets, matplotlylib):
    9.9 MB → 3.9 MB, deflate level 9, extracted into site-packages as is."""
    src = zipfile.ZipFile(io.BytesIO(raw))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        for info in src.infolist():
            name = info.filename
            if name.startswith(tuple(strip)) or name.endswith(".dist-info/RECORD"):
                continue
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            # A bare ZipInfo is ZIP_STORED whatever the archive's default is.
            entry.compress_type = zipfile.ZIP_DEFLATED
            out.writestr(entry, src.read(info), compresslevel=9)
    return buf.getvalue()


@dataclass
class AssetFile:
    name: str
    data: bytes
    gzip: bool = False

    def embedded(self) -> str:
        payload = gzip.compress(self.data, compresslevel=9, mtime=0) if self.gzip else self.data
        return base64.b64encode(payload).decode("ascii")


@dataclass
class PyodideAssets:
    """Everything one bundle inlines, verified."""

    version: str
    packages: list[str]
    extras: list[str]
    files: list[AssetFile] = field(default_factory=list)
    lock: dict[str, Any] = field(default_factory=dict)


def load_assets(features: set[str]) -> PyodideAssets:
    """Fetch (or read from the cache) and verify every file the features need."""
    packages, extras = features_packages(features)
    return load_assets_named(packages + extras)


def load_assets_named(names: list[str]) -> PyodideAssets:
    """:func:`load_assets` for an explicit list (``RuntimeAddon.packages``)."""
    p = pin()
    packages = closure([n for n in names if n in p["packages"]])
    extras = [n for n in names if n in p["extras"]]
    files = [
        AssetFile(name, _read(name, meta["sha256"]), bool(meta["gzip"]))
        for name, meta in p["core"].items()
    ]
    lock_all = _lock_packages()
    for name in packages:
        meta = p["packages"][name]
        files.append(AssetFile(meta["file_name"], _read(meta["file_name"], meta["sha256"])))
    for name in extras:
        meta = p["extras"][name]
        file_name = meta["url"].rsplit("/", 1)[-1]
        data = _read(file_name, meta["sha256"], meta["url"])
        if meta.get("strip"):
            data = _stripped_plotly(data, list(meta["strip"]))
        files.append(AssetFile(f"{name}.zip", data))
    lock = json.loads(_read("pyodide-lock.json", p["lock"]["sha256"]))
    lock["packages"] = {n: lock_all[n] for n in packages}
    return PyodideAssets(
        version=p["version"], packages=packages, extras=extras, files=files, lock=lock
    )
