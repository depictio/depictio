"""Merge one catalog-site export into the depictio-catalog site tree.

The contract is ``docs/design/catalog-site.md``. The tree holds one directory per
published slot (``latest/`` for ``main``, ``v<version>/`` per release, every one
kept) and what they share:

- ``assets/``: every slot's content-hashed bundle chunks, stored once (a file whose
  name carries no hash, such as ``assets/genomes/hg38.genes.json``, stays in its slot);
- ``objects/<sha256>.json``: every output's ``{fixturePreview, data}``, stored once
  per content (an output that did not change between releases is one file);
- ``modules/<tool_id>.json``: a module's version history across the slots;
- ``releases.json``: per slot, its version, publication date and what changed;
- ``versions.json`` (with ``stable``, the newest non-beta release), ``stable/``
  and ``index.html``, redirects to that release (``latest/`` before any).

The export is copied into its slot, then every slot is normalised: ``data/outputs/``
moves to ``objects/`` (each output entry gets a ``dataRef``), ``assets/`` moves to the
shared ``assets/`` (the slot keeps ``assets.json``, its file list, and its
``index.html`` loads ``../assets/``). Normalising is idempotent and also converts a
slot published in the earlier format (outputs and assets inside the slot). Objects and
assets no slot references any more are then dropped, except those of the ``latest/``
this run replaced, listed in ``latest/assets.previous.json`` and ``latest/objects.previous.json``
and kept for one more deploy so a tab opened before it can still load its chunks and data.

The publisher is not atomic: it edits the tree in place, so a failure after it started can
leave the tree half-updated. It checks what it can before deleting anything and computes
``modules/`` and ``releases.json`` first, but a host that publishes in place should run it
on a copy and swap the copy in.

Usage::

    python scripts/publish_catalog_site.py --site DIR --export DIR --slot v1.22.0
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LATEST = "latest"
_RELEASE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-b(\d+))?$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ASSET_REF = re.compile(r"""(\b(?:src|href)=)(["'])\./assets/([^"']*)""")
# Vite names a chunk <name>-<content hash>.<ext>; only such a file can be shared between slots.
_HASHED = re.compile(r"-[A-Za-z0-9_-]{8,}\.[a-z0-9]+$")

STABLE = "stable"


def redirect_html(target: str) -> str:
    """A page that sends its reader to ``target``, keeping the URL hash
    (``#tool=``, ``#output=``), so a ``stable/`` deep link lands in the release."""
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Depictio Tools Catalog</title>
<link rel="canonical" href="{target}">
<script>location.replace({target!r} + location.search + location.hash)</script>
<noscript><meta http-equiv="refresh" content="0; url={target}"></noscript>
<a href="{target}">Depictio Tools Catalog</a>
"""


# ---------------------------------------------------------------------------
# Slots and versions
# ---------------------------------------------------------------------------


def release_key(name: str) -> tuple[int, int, int, int]:
    """Sort key of a release slot; a beta sorts before its release."""
    m = _RELEASE.fullmatch(name)
    if m is None:
        raise ValueError(f"not a release slot: {name!r}")
    major, minor, patch, beta = m.groups()
    return (int(major), int(minor), int(patch), int(beta) if beta else 1_000_000)


def releases(site: Path) -> list[str]:
    """Release slots present in the site, newest first."""
    names = [p.name for p in site.iterdir() if p.is_dir() and _RELEASE.fullmatch(p.name)]
    return sorted(names, key=release_key, reverse=True)


def slots(site: Path) -> list[str]:
    """Every slot present: ``latest`` first, then the releases newest first."""
    return ([LATEST] if (site / LATEST).is_dir() else []) + releases(site)


def _semver(version: str) -> tuple[int, int, int]:
    nums = [int(n) for n in re.findall(r"\d+", version)[:3]]
    return tuple(nums + [0] * (3 - len(nums)))  # type: ignore[return-value]


def bump_between(lower: str, higher: str) -> str:
    """The semver step from ``lower`` to ``higher``; ``"downgrade"`` if it goes down."""
    a, b = _semver(lower), _semver(higher)
    if a > b:
        return "downgrade"
    if a[0] != b[0]:
        return "major"
    return "minor" if a[1] != b[1] else "patch"


# ---------------------------------------------------------------------------
# JSON and file helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text())


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")) + "\n")


def _move_shared(src: Path, dest: Path) -> None:
    """Move ``src`` to ``dest``; content-named, so an existing ``dest`` is the same file."""
    if dest.exists():
        if not filecmp.cmp(src, dest, shallow=False):
            raise SystemExit(f"{dest.name} exists with other content: refusing to overwrite it")
        src.unlink()
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))


def _is_hashed(name: str) -> bool:
    return _HASHED.search(Path(name).name) is not None


def _tool_version(tool: dict[str, Any]) -> str | None:
    """The module version of an index entry; None when the export predates versions."""
    version = tool.get("version")
    return str(version) if version else None


def _prune_empty(directory: Path) -> None:
    """Remove ``directory`` and its sub-directories that hold nothing."""
    if not directory.is_dir():
        return
    for sub in sorted((p for p in directory.rglob("*") if p.is_dir()), reverse=True):
        if not any(sub.iterdir()):
            sub.rmdir()
    if not any(directory.iterdir()):
        directory.rmdir()


def _tools(index: dict[str, Any]) -> list[dict[str, Any]]:
    return list(index.get("tools") or [])


def _outputs(tool: dict[str, Any]) -> list[dict[str, Any]]:
    return list(tool.get("outputs") or [])


def _output_id(entry: dict[str, Any]) -> str:
    return str((entry.get("output") or {}).get("id") or "")


# ---------------------------------------------------------------------------
# Normalising a slot (also converts the earlier format)
# ---------------------------------------------------------------------------


def normalize_slot(site: Path, slot: str) -> None:
    """Bring ``site/slot`` to the shared layout. Idempotent.

    - ``data/outputs/<id>.json`` -> ``objects/<sha256>.json``, ``dataRef`` on the entry;
    - ``assets/*`` -> the shared ``assets/``, listed in the slot's ``assets.json``;
    - ``index.html`` loads ``../assets/`` instead of ``./assets/``.
    """
    root = site / slot
    index_path = root / "data" / "index.json"
    index = _read_json(index_path)
    if index is None:
        raise SystemExit(f"{root} has no data/index.json: not a catalog slot")

    outputs_dir = root / "data" / "outputs"
    changed = False
    for tool in _tools(index):
        for entry in _outputs(tool):
            if not entry.get("ok") or entry.get("dataRef"):
                continue
            oid = _output_id(entry)
            file = outputs_dir / f"{oid}.json"
            if not _SAFE_NAME.fullmatch(oid) or not file.is_file():
                continue
            ref = hashlib.sha256(file.read_bytes()).hexdigest()
            _move_shared(file, site / "objects" / f"{ref}.json")
            entry["dataRef"] = ref
            changed = True
    if changed:
        _write_json(index_path, index)
    if outputs_dir.exists():
        shutil.rmtree(outputs_dir)

    assets_dir = root / "assets"
    if assets_dir.is_dir():
        moved = sorted(
            p.relative_to(assets_dir).as_posix()
            for p in assets_dir.rglob("*")
            if p.is_file() and _is_hashed(p.name)
        )
        for name in moved:
            _move_shared(assets_dir / name, site / "assets" / name)
        if moved:
            # A slot normalised before keeps its list: the files moved then are gone from here.
            names = sorted(set(_read_json(root / "assets.json", [])) | set(moved))
            _write_json(root / "assets.json", names)
        _prune_empty(assets_dir)

    html_path = root / "index.html"
    if html_path.is_file():
        html = html_path.read_text()
        # Only a shared (hashed) file moved; any other stays relative to the slot.
        rewritten = _ASSET_REF.sub(
            lambda m: m.group(0)
            if not _is_hashed(m.group(3))
            else f"{m.group(1)}{m.group(2)}../assets/{m.group(3)}",
            html,
        )
        if rewritten != html:
            html_path.write_text(rewritten)


# ---------------------------------------------------------------------------
# What the site is made of: references, history
# ---------------------------------------------------------------------------


def _slot_refs(site: Path, slot: str) -> set[str]:
    """The object refs the slot's own index points at."""
    refs: set[str] = set()
    for tool in _tools(_read_json(site / slot / "data" / "index.json", {})):
        for entry in _outputs(tool):
            ref = entry.get("dataRef")
            if isinstance(ref, str) and _SHA256.fullmatch(ref):
                refs.add(ref)
    return refs


def _name_list(path: Path) -> list[str]:
    return [n for n in _read_json(path, []) if isinstance(n, str)]


def _referenced(site: Path, names: list[str]) -> tuple[set[str], set[str]]:
    """(object refs, asset files) that some slot still needs, grace lists included."""
    objects: set[str] = set()
    assets: set[str] = set()
    for slot in names:
        objects |= _slot_refs(site, slot)
        objects.update(
            r for r in _name_list(site / slot / "objects.previous.json") if _SHA256.fullmatch(r)
        )
        for file in ("assets.json", "assets.previous.json"):
            assets.update(_name_list(site / slot / file))
    return objects, assets


def _check_tree(site: Path, names: list[str]) -> None:
    """Refuse, before anything is deleted, a tree that points at files it does not have.

    Dropping the unreferenced files of a tree that is already missing some would only
    make it worse. The grace lists are not required to exist: they name what may be left.
    """
    missing: list[str] = []
    for slot in names:
        for ref in sorted(_slot_refs(site, slot)):
            if not (site / "objects" / f"{ref}.json").is_file():
                missing.append(f"{slot}: objects/{ref}.json")
        for name in _name_list(site / slot / "assets.json"):
            parts = Path(name).parts
            if Path(name).is_absolute() or ".." in parts or not parts:
                raise SystemExit(f"{slot}/assets.json names {name!r}, outside assets/")
            if not (site / "assets" / name).is_file():
                missing.append(f"{slot}: assets/{name}")
    if missing:
        shown = "; ".join(missing[:10]) + (f" (+{len(missing) - 10} more)" if len(missing) > 10 else "")
        raise SystemExit(f"the site tree is missing files its slots need, nothing deleted: {shown}")


def _drop_unreferenced(directory: Path, keep: set[str], suffix: str = "") -> list[str]:
    """Delete the files of ``directory`` not named in ``keep``; return what went."""
    removed: list[str] = []
    if not directory.is_dir():
        return removed
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        name = path.relative_to(directory).as_posix()
        if (name[: -len(suffix)] if suffix else name) not in keep:
            path.unlink()
            removed.append(name)
    for sub in sorted((p for p in directory.rglob("*") if p.is_dir()), reverse=True):
        if not any(sub.iterdir()):
            sub.rmdir()
    return removed


def _reduced_render(render: dict[str, Any]) -> dict[str, Any]:
    reduced = {
        k: render[k] for k in ("index", "component_type", "_yaml", "kind", "_variant") if k in render
    }
    # The module revision this render last changed in (`renders_as[].version`), which
    # the index carries as `_version`; absent when the render does not say.
    if render.get("_version"):
        reduced["version"] = str(render["_version"])
    return reduced


def _reduced_output(entry: dict[str, Any]) -> dict[str, Any]:
    info = entry.get("output") or {}
    reduced: dict[str, Any] = {"id": _output_id(entry), "name": info.get("name")}
    # The module revision this output last changed in (the output's `version`).
    if info.get("output_version"):
        reduced["version"] = str(info["output_version"])
    reduced["renders"] = [_reduced_render(r) for r in entry.get("renders") or []]
    return reduced


def _changelog_entries(tool: dict[str, Any]) -> list[dict[str, Any]]:
    """The module's `changelog` from an index entry: the tool's own, else (an index
    exported between the two) the first output's copy of it."""
    log = tool.get("changelog")
    if not isinstance(log, list):
        outs = _outputs(tool)
        log = ((outs[0].get("output") or {}).get("changelog") if outs else None) or []
    return [e for e in log if isinstance(e, dict) and e.get("version")]


def build_modules(site: Path, names: list[str]) -> dict[str, dict[str, Any]]:
    """Per tool id, its version history over ``names`` (``latest`` first, then newest release)."""
    modules: dict[str, dict[str, Any]] = {}
    for slot in names:
        for tool in _tools(_read_json(site / slot / "data" / "index.json", {})):
            tid = str(tool.get("id") or "")
            if not _SAFE_NAME.fullmatch(tid):
                raise SystemExit(f"tool id {tid!r} cannot name a file of the catalog site")
            module = modules.setdefault(
                tid, {"id": tid, "name": tool.get("name") or tid, "_versions": {}, "_log": {}}
            )
            # A changelog is cumulative: the newest slot that has an entry for a
            # version gives its text, whichever slot shipped that version.
            for e in _changelog_entries(tool):
                module["_log"].setdefault(str(e["version"]), e)
            version = _tool_version(tool)
            if version is None:
                continue  # an export that predates module versions: unknown, not 1.0.0
            known = module["_versions"].get(version)
            if known is None:
                # The first slot seen is the most recent one shipping this version.
                module["_versions"][version] = {
                    "version": version,
                    "releases": [slot],
                    "outputs": [_reduced_output(e) for e in _outputs(tool)],
                }
            else:
                known["releases"].append(slot)

    result: dict[str, dict[str, Any]] = {}
    for tid, module in modules.items():
        if not module["_versions"]:
            continue  # no slot knows a version of this module: no history to show
        ordered = sorted(module["_versions"].values(), key=lambda v: _semver(v["version"]), reverse=True)
        history = []
        for i, v in enumerate(ordered):
            lower = ordered[i + 1]["version"] if i + 1 < len(ordered) else None
            item: dict[str, Any] = {
                "version": v["version"],
                "bump": bump_between(lower, v["version"]) if lower else None,
                "releases": v["releases"],
            }
            log = module["_log"].get(v["version"])
            if log is not None:
                if log.get("date"):
                    item["date"] = str(log["date"])
                item["changelog"] = [str(c) for c in log.get("changes") or []]
            item["outputs"] = v["outputs"]
            history.append(item)
        result[tid] = {"id": tid, "name": module["name"], "versions": history}
    return result


def _snapshot(site: Path, slot: str) -> tuple[str, dict[str, str | None], set[str]]:
    index = _read_json(site / slot / "data" / "index.json", {})
    tools = {str(t.get("id")): _tool_version(t) for t in _tools(index)}
    outputs = {_output_id(e) for t in _tools(index) for e in _outputs(t)}
    return str(index.get("version") or ""), tools, outputs


def build_releases(
    site: Path,
    names: list[str],
    published: dict[str, str],
) -> list[dict[str, Any]]:
    """The ``releases.json`` entries: each slot against the release below it.

    ``latest`` is compared with the newest release; with nothing to compare against
    (the oldest release) ``previous`` is null and every list of ``changes`` is empty.
    """
    result = []
    stable = [n for n in names if n != LATEST]
    for slot in names:
        if slot == LATEST:
            previous = stable[0] if stable else None
        else:
            below = stable[stable.index(slot) + 1 :]
            previous = below[0] if below else None
        version, tools, outputs = _snapshot(site, slot)
        changes: dict[str, Any] = {
            "added": [],
            "removed": [],
            "bumped": [],
            "outputs_added": [],
            "outputs_removed": [],
        }
        if previous is not None:
            _, p_tools, p_outputs = _snapshot(site, previous)
            changes = {
                "added": sorted(set(tools) - set(p_tools)),
                "removed": sorted(set(p_tools) - set(tools)),
                "bumped": [
                    {
                        "id": t,
                        "from": p_tools[t],
                        "to": tools[t],
                        "bump": bump_between(p_tools[t], tools[t]),  # type: ignore[arg-type]
                    }
                    for t in sorted(set(tools) & set(p_tools))
                    # A version unknown on either side compares with nothing.
                    if tools[t] is not None
                    and p_tools[t] is not None
                    and tools[t] != p_tools[t]
                ],
                "outputs_added": sorted(outputs - p_outputs),
                "outputs_removed": sorted(p_outputs - outputs),
            }
        result.append(
            {
                "slot": slot,
                "version": version,
                "published": published[slot],
                "previous": previous,
                "changes": changes,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


def _check_export(export: Path) -> None:
    index = _read_json(export / "data" / "index.json") if (export / "data").is_dir() else None
    if not (export / "index.html").is_file() or index is None:
        raise SystemExit(f"{export} is not a catalog-site export (index.html, data/index.json)")
    for tool in _tools(index):
        for entry in _outputs(tool):
            oid = _output_id(entry)
            if not _SAFE_NAME.fullmatch(oid):
                raise SystemExit(f"{export}: output id {oid!r} cannot name a file of the catalog site")
            if entry.get("ok") and not (export / "data" / "outputs" / f"{oid}.json").is_file():
                raise SystemExit(f"{export}: output {oid!r} is ok but has no data/outputs/{oid}.json")


def publish(site: Path, export: Path, slot: str, now: datetime | None = None) -> dict[str, list[str]]:
    """Copy ``export`` into ``site/slot`` and rebuild everything derived from the slots.

    Returns the ``objects`` and ``assets`` that no slot referenced any more and were deleted.
    """
    if slot != LATEST:
        release_key(slot)  # refuse anything that is not latest or vX.Y.Z[-bN]
    _check_export(export)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")

    site.mkdir(parents=True, exist_ok=True)
    target = site / slot

    # The latest/ about to be replaced: its assets stay one more deploy.
    old_assets: list[str] = []
    old_previous: list[str] = []
    old_objects: list[str] = []
    old_objects_previous: list[str] = []
    if slot == LATEST and (target / "data" / "index.json").is_file():
        normalize_slot(site, LATEST)
        old_assets = _name_list(target / "assets.json")
        old_previous = _name_list(target / "assets.previous.json")
        old_objects = sorted(_slot_refs(site, LATEST))
        old_objects_previous = _name_list(target / "objects.previous.json")

    published: dict[str, str] = {
        r["slot"]: r["published"]
        for r in (_read_json(site / "releases.json", {}) or {}).get("releases", [])
    }

    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(export, target)
    published[slot] = stamp

    for name in slots(site):
        normalize_slot(site, name)
        published.setdefault(name, stamp)

    if slot == LATEST:
        new_assets = _read_json(target / "assets.json", [])
        # Same bundle redeployed: keep the grace list of the one before it.
        grace = old_assets if old_assets != new_assets else old_previous
        if grace:
            _write_json(target / "assets.previous.json", grace)
        new_objects = sorted(_slot_refs(site, LATEST))
        grace_objects = old_objects if old_objects != new_objects else old_objects_previous
        if grace_objects:
            _write_json(target / "objects.previous.json", grace_objects)

    names = slots(site)
    # Everything that can fail is computed or checked before the first deletion.
    modules = build_modules(site, names)
    release_entries = build_releases(site, names, published)
    _check_tree(site, names)

    objects, assets = _referenced(site, names)
    removed = {
        "objects": _drop_unreferenced(site / "objects", objects, ".json"),
        "assets": _drop_unreferenced(site / "assets", assets),
    }

    modules_dir = site / "modules"
    for tid, module in modules.items():
        _write_json(modules_dir / f"{tid}.json", module)
    if modules_dir.is_dir():
        for stale in modules_dir.glob("*.json"):
            if stale.stem not in modules:
                stale.unlink()

    rels = releases(site)
    # A beta tag (vX.Y.Z-bN) is a release slot, never what `stable/` names.
    stable = next((r for r in rels if "-b" not in r), None)
    _write_json(site / "releases.json", {"releases": release_entries})
    _write_json(
        site / "versions.json",
        {
            "latest": LATEST if (site / LATEST).is_dir() else None,
            "stable": stable,
            "versions": rels,
        },
    )
    # `stable/` is the newest release (what the docs link to); the site root
    # opens it too, and falls back to `latest/` before any release exists.
    stable_dir = site / STABLE
    stable_dir.mkdir(exist_ok=True)
    if stable:
        (stable_dir / "index.html").write_text(redirect_html(f"../{stable}/"))
    else:
        (stable_dir / "index.html").write_text(redirect_html(f"../{LATEST}/"))
    (site / "index.html").write_text(redirect_html(f"{stable or LATEST}/"))
    # Pages would otherwise run Jekyll and drop directories starting with "_".
    (site / ".nojekyll").touch()
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, required=True, help="Checkout of the Pages tree")
    parser.add_argument("--export", type=Path, required=True, help="catalog export-site output")
    parser.add_argument("--slot", required=True, help="'latest' or a release tag, e.g. v1.22.0")
    args = parser.parse_args()

    removed = publish(args.site, args.export, args.slot)
    print(
        f"Published {args.slot}; dropped {len(removed['objects'])} unreferenced objects "
        f"and {len(removed['assets'])} assets"
    )


if __name__ == "__main__":
    main()
