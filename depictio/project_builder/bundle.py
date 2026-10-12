"""Write an ad-hoc template where ``depictio ingest --template`` can read it."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
from pathlib import Path
from typing import Any

from depictio.cli.cli.utils.compose import slug
from depictio.project_builder.assemble import template_yaml
from depictio.project_builder.errors import BuilderRefused

BUNDLE_FILE = "template.yaml"


def default_bundle_dir(data_root: Path, name: str) -> Path:
    """``<data root>/.depictio/template``, or a folder under ``~/.depictio/builder``
    when the data root is not writable (a shared, read-only results folder)."""
    inside = data_root / ".depictio" / "template"
    probe = inside if inside.exists() else data_root
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if os.access(probe, os.W_OK):
        return inside
    digest = hashlib.sha256(str(data_root.resolve()).encode()).hexdigest()[:8]
    return Path.home() / ".depictio" / "builder" / f"{slug(name, 40)}-{digest}"


def ingest_command(data_root: str, bundle: Path) -> str:
    """The command to copy and run: quoted, so a folder name never splits or runs."""
    return f"depictio ingest {shlex.quote(data_root)} --template {shlex.quote(str(bundle))}"


def watch_command(data_root: str, bundle: Path) -> str:
    """The command that keeps a project fed as files land: re-ingests on change."""
    return f"depictio watch {shlex.quote(data_root)} --template {shlex.quote(str(bundle))}"


def write_bundle(
    template: dict[str, Any], out_dir: Path, *, data_root: str, overwrite: bool = False
) -> dict[str, Any]:
    """Write ``template`` to ``<out_dir>/template.yaml``.

    An existing bundle is a 409 ``bundle_exists`` unless ``overwrite``, which
    keeps the previous one next to it as ``template.yaml.bak``.
    """
    path = out_dir / BUNDLE_FILE
    if path.exists() and not overwrite:
        raise BuilderRefused(
            409, f"{path} already exists. Overwrite it to replace it.", "bundle_exists"
        )
    text = template_yaml(template)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copyfile(path, path.with_name(BUNDLE_FILE + ".bak"))
        path.write_text(text)
    except OSError as exc:
        raise BuilderRefused(
            500, f"Could not write {path}: {exc.strerror or exc}", "bundle_unwritable"
        ) from exc
    return {
        "path": str(path),
        "yaml": text,
        "ingest_command": ingest_command(data_root, path),
        "watch_command": watch_command(data_root, path),
    }


MAX_MANIFEST_BYTES = 2 * 1024 * 1024


def write_manifest(
    name: str, tsv: str, out_dir: Path, *, data_root: Path, overwrite: bool = False
) -> dict[str, Any]:
    """Write a generated track manifest as ``<out_dir>/<name>.tsv``.

    Only when ``out_dir`` lies inside the data root: the manifest is then a
    file of the root, and its uris (relative to the root) resolve as written.
    """
    if not re.search(r"[A-Za-z0-9]", name):
        raise BuilderRefused(422, "The manifest needs a name.", "manifest_name_invalid")
    stem = slug(name.removesuffix(".tsv"), 64)
    if len(tsv.encode()) > MAX_MANIFEST_BYTES:
        raise BuilderRefused(422, "The manifest is larger than 2 MB.", "manifest_too_large")
    root = data_root.resolve()
    try:
        relative_dir = out_dir.resolve().relative_to(root)
    except ValueError:
        raise BuilderRefused(
            409,
            f"The template folder {out_dir} is outside {root}: download the manifest and "
            "place it in the folder instead.",
            "manifest_outside_root",
        ) from None
    path = out_dir / f"{stem}.tsv"
    if path.exists() and not overwrite:
        raise BuilderRefused(
            409, f"{path} already exists. Overwrite it to replace it.", "manifest_exists"
        )
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(tsv)
    except OSError as exc:
        raise BuilderRefused(
            500, f"Could not write {path}: {exc.strerror or exc}", "manifest_unwritable"
        ) from exc
    return {"path": (relative_dir / path.name).as_posix()}
