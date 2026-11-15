"""Object-store files shipped inside a serverless bundle (protein kinds).

``molecule_3d``, ``ramachandran`` and ``pae_matrix`` read a structure (PDB /
mmCIF) or a PAE matrix from an ``indexed_file`` data collection at render time,
through presigned object-store URLs. A bundle has no object store, so the
producer reads those files at export, from the collection's own storage, and
ships their bytes in ``inline_blobs`` under a stated cap. The runtime answers
the renderer's manifest read (``GET /files/indexed/{dc_id}``) from
``BundleManifest.objects`` with ``blob:`` URLs over the bytes, so the renderer's
download path (gunzip by magic bytes, per-object cache) runs unchanged.

Producer-agnostic on purpose: producer B (CLI-only install) reads files from
``{data_dir}/{workflow_tag}/{dc_tag}/``; producer A (``collect_objects_a`` in
``producer_a``) from Mongo + S3. Nothing here imports the API package.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from depictio.models.models.serverless import BundledObject, ObjectCollection

#: Kinds whose renderer reads object files, and the config key bases naming
#: their ``indexed_file`` collections (``<base>_dc_id`` / ``<base>_dc_tag``).
OBJECT_KINDS: dict[str, tuple[str, ...]] = {
    "molecule_3d": ("structure",),
    "ramachandran": ("structure",),
    "pae_matrix": ("pae",),
}

#: Kinds that draw with 3Dmol.js (the conditional ``3dmol`` runtime add-on).
THREE_DMOL_KINDS = frozenset({"molecule_3d"})

#: Per-bundle budget for shipped objects, raw bytes before gzip. 24 MB keeps a
#: protein bundle travelling (base64 inflates by a third) while covering a few
#: hundred AlphaFold models of ordinary length; a PAE matrix is n² values, so a
#: 1500-residue one is ~10 MB of text before gzip.
OBJECTS_MAX_MB_ENV = "DEPICTIO_STATIC_OBJECTS_MAX_MB"
OBJECTS_MAX_MB_DEFAULT = 24
#: A single object past this is never shipped, whatever budget is left.
OBJECT_MAX_MB_ENV = "DEPICTIO_STATIC_OBJECT_MAX_MB"
OBJECT_MAX_MB_DEFAULT = 8
#: Resolver answers frozen per resolve-mode tile (one model per entity).
RESOLVE_MAX_ENTITIES = 12

_GZIP_MAGIC = b"\x1f\x8b"


def _env_mb(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


def objects_cap_bytes() -> int:
    """The per-bundle object budget in force (``DEPICTIO_STATIC_OBJECTS_MAX_MB``)."""
    return _env_mb(OBJECTS_MAX_MB_ENV, OBJECTS_MAX_MB_DEFAULT) * 1024 * 1024


def object_cap_bytes() -> int:
    """The per-object ceiling (``DEPICTIO_STATIC_OBJECT_MAX_MB``)."""
    return _env_mb(OBJECT_MAX_MB_ENV, OBJECT_MAX_MB_DEFAULT) * 1024 * 1024


def cap_sentence() -> str:
    """The cap as the tier table states it."""
    return (
        f"objects are shipped up to {objects_cap_bytes() // (1024 * 1024)} MB per bundle and "
        f"{object_cap_bytes() // (1024 * 1024)} MB per file ({OBJECTS_MAX_MB_ENV} / "
        f"{OBJECT_MAX_MB_ENV})"
    )


def object_kind(comp: dict[str, Any]) -> str:
    return str(comp.get("viz_kind") or (comp.get("config") or {}).get("viz_kind") or "")


def resolve_mode(comp: dict[str, Any]) -> bool:
    """True when a structure tile asks the structure resolver (no file collection)."""
    config = comp.get("config") or {}
    return object_kind(comp) in ("molecule_3d", "ramachandran") and (
        config.get("structure_source") == "resolve"
    )


def object_dc_refs(comp: dict[str, Any]) -> list[tuple[str, str]]:
    """``[(base, dc_id)]`` of the indexed_file collections a component reads."""
    if comp.get("component_type") != "advanced_viz":
        return []
    bases = OBJECT_KINDS.get(object_kind(comp), ())
    if resolve_mode(comp):
        bases = tuple(b for b in bases if b != "structure")
    config = comp.get("config") or {}
    out: list[tuple[str, str]] = []
    for base in bases:
        dc_id = config.get(f"{base}_dc_id")
        if dc_id:
            out.append((base, str(dc_id)))
    return out


def object_dc_tags(comp: dict[str, Any]) -> list[tuple[str, str]]:
    """``[(base, dc_tag)]`` — producer B's spelling of :func:`object_dc_refs`."""
    if comp.get("component_type") != "advanced_viz":
        return []
    bases = OBJECT_KINDS.get(object_kind(comp), ())
    if resolve_mode(comp):
        bases = tuple(b for b in bases if b != "structure")
    config = comp.get("config") or {}
    return [(b, str(config[f"{b}_dc_tag"])) for b in bases if config.get(f"{b}_dc_tag")]


def needs_three_dmol(components: Iterable[dict[str, Any]]) -> bool:
    return any(
        c.get("component_type") == "advanced_viz" and object_kind(c) in THREE_DMOL_KINDS
        for c in components
    )


def pack_object(data: bytes) -> tuple[str, str, bool]:
    """``(blob_key, base64, gzipped)`` for one object's bytes.

    Text formats (PDB, mmCIF, PAE JSON/TSV) compress 3-6x, and the renderer's
    loader gunzips whatever starts with the gzip magic, so every object that is
    not already gzipped is stored compressed. The key is content-addressed, so
    two tiles on the same model ship it once.
    """
    gzipped = data[:2] == _GZIP_MAGIC
    stored = data if gzipped else gzip.compress(data, compresslevel=9, mtime=0)
    key = "obj_" + hashlib.sha256(stored).hexdigest()[:24]
    return key, base64.b64encode(stored).decode("ascii"), not gzipped


@dataclass
class ObjectBudget:
    """Running total of shipped object bytes across a bundle."""

    cap: int = field(default_factory=objects_cap_bytes)
    per_object: int = field(default_factory=object_cap_bytes)
    used: int = 0
    seen: set[str] = field(default_factory=set)

    def admits(self, size: int) -> bool:
        return size <= self.per_object and self.used + size <= self.cap


@dataclass(frozen=True)
class ObjectSource:
    """One object a collection holds: ``load()`` returns its bytes."""

    sample: str
    name: str
    size_bytes: int | None
    load: Callable[[], bytes]


def build_collection(
    sources: list[ObjectSource],
    fmt: str,
    budget: ObjectBudget,
    inline_blobs: dict[str, str],
    preferred: Iterable[str] = (),
) -> ObjectCollection:
    """Ship as many of ``sources`` as the budget admits, preferred samples first.

    One object per sample (the renderer reads the first per sample, too). The
    samples the bound table actually names come first, so a cap that bites drops
    files no tile could open on before it drops the ones it would.
    """
    rank = {str(s): i for i, s in enumerate(preferred)}
    by_sample: dict[str, ObjectSource] = {}
    for src in sorted(sources, key=lambda s: (s.sample, s.name)):
        by_sample.setdefault(src.sample, src)
    ordered = sorted(
        by_sample.values(), key=lambda s: (rank.get(s.sample, len(rank)), s.sample, s.name)
    )
    files: list[BundledObject] = []
    dropped: list[str] = []
    for src in ordered:
        if src.size_bytes is not None and not budget.admits(src.size_bytes):
            dropped.append(src.sample)
            continue
        try:
            data = src.load()
        except Exception:
            dropped.append(src.sample)
            continue
        if not budget.admits(len(data)):
            dropped.append(src.sample)
            continue
        key, b64, gz = pack_object(data)
        if key not in budget.seen:
            budget.seen.add(key)
            budget.used += len(data)
            inline_blobs[key] = b64
        files.append(
            BundledObject(
                sample=src.sample, name=src.name, uri=f"inline:{key}", size_bytes=len(data), gzip=gz
            )
        )
    return ObjectCollection(
        format=fmt, files=files, total=len(by_sample), cap_bytes=budget.cap, dropped=dropped
    )


# --- producer B: files on disk ------------------------------------------------

#: Extensions stripped from a file name to get its sample (entity) id, longest
#: first, so ``P12345.pae.json.gz`` is the sample ``P12345``.
_SAMPLE_SUFFIXES = (
    ".pae.json.gz",
    ".pae.tsv.gz",
    ".pae.json",
    ".pae.tsv",
    ".cif.gz",
    ".pdb.gz",
    ".mmcif",
    ".json.gz",
    ".tsv.gz",
    ".cif",
    ".pdb",
    ".ent",
    ".json",
    ".tsv",
    ".gz",
)


def sample_from_name(name: str) -> str:
    low = name.lower()
    for suffix in _SAMPLE_SUFFIXES:
        if low.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def local_sources(directory: Path) -> list[ObjectSource]:
    """Producer B convention: every file of ``{data_dir}/{wf}/{dc_tag}/`` is one object."""
    if not directory.is_dir():
        return []
    out: list[ObjectSource] = []
    for path in sorted(p for p in directory.iterdir() if p.is_file()):
        out.append(
            ObjectSource(
                sample=sample_from_name(path.name),
                name=path.name,
                size_bytes=path.stat().st_size,
                load=path.read_bytes,
            )
        )
    return out


def collection_detail(collection: ObjectCollection) -> str | None:
    """The tier-detail sentence for a collection the cap cut short, else ``None``."""
    if not collection.dropped:
        return None
    shown = ", ".join(collection.dropped[:5])
    more = f" and {len(collection.dropped) - 5} more" if len(collection.dropped) > 5 else ""
    return (
        f"{len(collection.files)} of {collection.total} files shipped; left out: {shown}{more} "
        f"({cap_sentence()})"
    )
