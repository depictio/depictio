"""Recognition + config-by-example for picked files (middle column).

Two jobs:

1. **Recognize** — is a picked file a known tool output? Wraps
   ``match_run_dir`` (``depictio.models.components.advanced_viz.catalog``) over
   the studio root and returns the matching tool + its ``renders_as`` + the
   ``find`` glob that produced the match, so the designer can offer the catalog's
   existing visus in one click.

2. **Config-by-example** — for an *unknown* file (or a set of picked files),
   anti-unify the example path(s) into a ``**``-aware glob, count the files it
   matches under the root, and sniff the format. This is what turns "I picked
   ``star/S1/quant.tsv`` and ``star/S2/quant.tsv``" into a recursive scan over
   ``star/*/quant.tsv``.
"""

from __future__ import annotations

from fnmatch import translate as _glob_to_regex
from pathlib import Path, PurePosixPath
from typing import Any

from depictio.authoring.paths import StudioPathError, rel_to_root, safe_resolve

# Cap the number of matched files we open to compare schemas — a scan glob can
# match thousands of files; the studio only needs enough to spot disagreement.
MAX_SCHEMA_CHECK = 100


def _wildcard_token(names: list[str]) -> str:
    """Collapse a set of sibling path segments into one glob token.

    Identical names → the literal name. Differing names → common prefix + ``*`` +
    common suffix (e.g. ``["S1.quant", "S2.quant"] → "S*.quant"``), which keeps
    the extension while wildcarding only the varying middle.
    """
    uniq = list(dict.fromkeys(names))
    if len(uniq) == 1:
        return uniq[0]

    def common_prefix(items: list[str]) -> str:
        first = items[0]
        for i, ch in enumerate(first):
            if any(len(s) <= i or s[i] != ch for s in items):
                return first[:i]
        return first

    prefix = common_prefix(uniq)
    suffix = common_prefix([s[::-1] for s in uniq])[::-1]
    # Avoid overlap when prefix+suffix would exceed the shortest name.
    if len(prefix) + len(suffix) > min(len(s) for s in uniq):
        suffix = ""
    return f"{prefix}*{suffix}"


def config_by_example(root: Path, rel_paths: list[str]) -> dict[str, Any]:
    """Anti-unify example paths → a glob + the files it matches under ``root``."""
    root = Path(root).resolve()
    if not rel_paths:
        raise ValueError("config_by_example needs at least one example path")

    parts = [PurePosixPath(p).parts for p in rel_paths]
    lengths = {len(p) for p in parts}

    if len(rel_paths) == 1:
        # A single example can't reveal what varies — generalise to any depth.
        base = PurePosixPath(rel_paths[0]).name
        path_glob = f"**/{base}"
    elif len(lengths) == 1:
        # Same depth → per-segment anti-unification.
        segments = [_wildcard_token(list(col)) for col in zip(*parts)]
        path_glob = "/".join(segments)
    else:
        # Mixed depths → wildcard the directory prefix, keep a filename token.
        names = [PurePosixPath(p).name for p in rel_paths]
        path_glob = f"**/{_wildcard_token(names)}"

    matched = sorted(rel_to_root(root, p) for p in root.glob(path_glob) if p.is_file())
    return {"path_glob": path_glob, "matched": matched, "match_count": len(matched)}


def glob_to_pattern(glob: str) -> str:
    """Regex for the *filename* component of a scan glob.

    Mirrors what a recursive ``Scan`` matches at ingestion (the basename of each
    candidate file against ``regex_config.pattern``), so the regex the studio
    shows is byte-for-byte what ``export_project`` writes.
    """
    return _glob_to_regex(PurePosixPath(glob).name)


def _schema_diff(reference: dict[str, str], other: dict[str, str]) -> str:
    """Human-readable summary of how ``other`` differs from ``reference`` (or "")."""
    missing = [c for c in reference if c not in other]
    extra = [c for c in other if c not in reference]
    dtype_diffs = [
        f"{c} {reference[c]}≠{other[c]}"
        for c in reference
        if c in other and reference[c] != other[c]
    ]
    parts: list[str] = []
    if missing:
        parts.append(f"missing {', '.join(missing)}")
    if extra:
        parts.append(f"extra {', '.join(extra)}")
    if dtype_diffs:
        parts.append("dtype " + "; ".join(dtype_diffs))
    return "; ".join(parts)


def _matched_under(
    walk_root: Path,
    root: Path,
    compiled: Any,
    max_depth: int | None,
    ignore: list[str] | None,
) -> list[str]:
    """Files under ``walk_root`` whose basename matches, within depth/ignore limits.

    Depth/ignore are measured from ``walk_root``; results are reported relative to
    ``root``. The ``walk_root in parents`` check also rejects symlink escapes.
    """
    return [
        rel_to_root(root, p)
        for p in walk_root.rglob("*")
        if p.is_file()
        and walk_root in p.resolve().parents
        and compiled.match(p.name)
        and _within_scan_limits(rel_to_root(walk_root, p), max_depth, ignore)
    ]


def _within_scan_limits(rel: str, max_depth: int | None, ignore: list[str] | None) -> bool:
    """Recursive ``max_depth`` / ``ignore`` check on a root-relative POSIX path.

    Kept in lockstep with ``depictio.cli.cli.utils.scan_utils.passes_scan_limits``
    (which the actual ingestion uses); duplicated here only to keep the studio
    backend free of a CLI import.
    """
    if ignore and any(token and token in rel for token in ignore):
        return False
    if max_depth is not None:
        parent = PurePosixPath(rel).parent
        depth = 0 if str(parent) == "." else len(parent.parts)
        if depth > max_depth:
            return False
    return True


def scan_preview(
    root: Path,
    glob: str,
    regex: str | None = None,
    max_depth: int | None = None,
    ignore: list[str] | None = None,
    subroot: str | None = None,
    structure: str = "flat",
    runs_regex: str | None = None,
) -> dict[str, Any]:
    """Preview what a scan will ingest: files, regex, and schema agreement.

    Mirrors the CLI scanner exactly. At ingestion ``scan_single_file`` matches each
    file's *basename* against ``regex_config.pattern`` over the workflow's
    ``data_location``, then the recursive ``max_depth`` / ``ignore`` limits drop
    files — so the preview does the same or it would mis-report the ingested set.
    ``regex`` overrides the glob-derived pattern (the user can hand-edit it).
    ``subroot`` scopes the walk to a workflow's ``data_location`` folder (relative
    to ``root``). ``structure`` mirrors ``WorkflowDataLocation.structure``: ``flat``
    walks the folder as one tree; ``sequencing-runs`` scans each immediate
    ``runs_regex``-matching subdirectory as its own run (``max_depth`` counted from
    the run dir), exactly like ``scan.py``.

    Returns ``{glob, regex, matched, match_count, schema, consistent, mismatches,
    truncated}``. ``schema`` is the reference (first matched file) column→dtype map;
    ``mismatches`` lists files whose schema diverges from it. Non-blocking — a
    divergent scan is surfaced, not rejected.
    """
    import re

    from depictio.authoring import preview as preview_mod

    root = Path(root).resolve()
    glob = (glob or "").strip()
    if not glob:
        raise ValueError("scan_preview needs a non-empty glob")
    if glob.startswith("/") or ".." in PurePosixPath(glob).parts:
        raise StudioPathError(f"glob escapes studio root: {glob!r}")

    # A workflow's data_location folder scopes the walk (safe_resolve rejects escapes).
    base = safe_resolve(root, subroot) if subroot else root

    pattern = (regex or "").strip() or glob_to_pattern(glob)
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid scan regex: {exc}") from exc

    if structure == "sequencing-runs":
        # Each immediate subdir matching runs_regex is a run scanned on its own,
        # exactly like scan.py (max_depth/ignore measured from the run dir).
        try:
            run_pat = re.compile(runs_regex or "run_*")
        except re.error as exc:
            raise ValueError(f"invalid runs_regex: {exc}") from exc
        run_dirs = (
            [c for c in sorted(base.iterdir()) if c.is_dir() and run_pat.match(c.name)]
            if base.is_dir()
            else []
        )
        matched = sorted(
            rel
            for run_dir in run_dirs
            for rel in _matched_under(run_dir, root, compiled, max_depth, ignore)
        )
    else:
        matched = sorted(_matched_under(base, root, compiled, max_depth, ignore))

    checked = matched[:MAX_SCHEMA_CHECK]
    truncated = len(matched) > MAX_SCHEMA_CHECK
    mismatches: list[dict[str, str]] = []
    consistent = True
    reference: dict[str, str] | None = None
    for rel in checked:
        try:
            file_schema = preview_mod.schema_of(root, rel)
        except Exception as exc:  # noqa: BLE001 — an unreadable match is a mismatch
            consistent = False
            mismatches.append({"path": rel, "issue": f"could not read: {exc}"})
            continue
        if reference is None:
            reference = file_schema
            continue
        issue = _schema_diff(reference, file_schema)
        if issue:
            consistent = False
            mismatches.append({"path": rel, "issue": issue})

    return {
        "glob": glob,
        "regex": pattern,
        "matched": matched,
        "match_count": len(matched),
        "schema": reference or {},
        "consistent": consistent,
        "mismatches": mismatches,
        "truncated": truncated,
    }


def _render_to_dict(render: Any) -> dict[str, Any]:
    return render.model_dump(exclude_none=True, exclude_defaults=True)


def recognize(root: Path, rel: str, extra_examples: list[str] | None = None) -> dict[str, Any]:
    """Recognize a picked file and compute its config-by-example scan.

    ``extra_examples`` lets the caller pass sibling picks so the generated glob
    generalises across them (e.g. one DC covering many samples).
    """
    from depictio.models.components.advanced_viz.catalog import match_run_dir

    root = Path(root).resolve()
    path = safe_resolve(root, rel)
    rel_norm = rel_to_root(root, path)

    matches = match_run_dir(root)
    recognized: list[dict[str, Any]] = []
    for m in matches:
        if m.path != rel_norm:
            continue
        recognized.append(
            {
                "tool_id": m.tool_id,
                "output_id": m.output_id,
                "renders": m.renders,
                "mode": m.mode,
            }
        )

    result: dict[str, Any] = {
        "path": rel_norm,
        "recognized": bool(recognized),
        "matches": recognized,
        "config_by_example": config_by_example(root, [rel_norm, *(extra_examples or [])]),
    }

    # If recognized, attach the full renders_as of the first matching catalog
    # output so the designer can offer them as one-click "existing visus".
    if recognized:
        result["catalog_renders"] = _catalog_renders(recognized[0]["output_id"])
    return result


def _catalog_renders(output_id: str) -> list[dict[str, Any]]:
    from depictio.models.components.advanced_viz.catalog import load_catalog_entries

    for entry in load_catalog_entries():
        for output in entry.outputs:
            if output.id == output_id:
                return [_render_to_dict(r) for r in output.renders_as]
    return []
