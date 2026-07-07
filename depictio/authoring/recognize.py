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

from pathlib import Path, PurePosixPath
from typing import Any

from depictio.authoring.paths import rel_to_root, safe_resolve


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
