"""OME-NGFF metadata validation of a bioimage store, reported and never blocking.

``deltatables.validate_ome_zarr_store`` keeps the hard checks the viewer needs
to open a store at all (a root group, a non-empty ``multiscales`` or a layout
it can walk). This module goes further with ``ome-zarr-models``, the
pydantic models of the NGFF spec (0.4 and 0.5): axes order and types,
coordinate transformations, plate and well structure, label images. Whatever it
finds is stored on the store's File and shown by the tile, so a store written
slightly off-spec still opens, and the reader learns why another tool might
refuse it.
"""

from __future__ import annotations

import os
import warnings
from importlib import metadata
from typing import Any

from depictio.models.models.data_collections_types.bioimage import (
    NGFF_MAX_ISSUES,
    NgffLayout,
    NgffValidation,
)

#: Spec versions ``ome-zarr-models`` has schemas for.
_SPEC_VERSIONS = ("0.4", "0.5")

#: Root attribute naming each layout, in the order a root is checked.
_LAYOUT_KEYS: tuple[tuple[str, NgffLayout], ...] = (
    ("multiscales", "image"),
    ("plate", "plate"),
    ("well", "well"),
    ("bioformats2raw.layout", "bioformats2raw"),
    ("image-label", "labels"),
)


def _validator_name() -> str | None:
    try:
        return f"ome-zarr-models {metadata.version('ome-zarr-models')}"
    except metadata.PackageNotFoundError:
        return None


def _ome_attributes(attrs: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """The NGFF attributes of a group and their version.

    NGFF 0.5 keeps them under ``ome`` with a single ``version``; 0.4 puts them
    at the root, with the version inside ``multiscales[0]`` (or ``plate`` /
    ``well``).
    """
    ome = attrs.get("ome")
    if isinstance(ome, dict):
        version = ome.get("version")
        return ome, str(version) if version is not None else None
    for key in ("multiscales", "plate", "well"):
        block = attrs.get(key)
        if isinstance(block, list) and block and isinstance(block[0], dict):
            block = block[0]
        if isinstance(block, dict) and block.get("version") is not None:
            return attrs, str(block["version"])
    return attrs, None


def _layout_of(ome: dict[str, Any]) -> NgffLayout:
    for key, layout in _LAYOUT_KEYS:
        if key in ome:
            return layout
    return "unknown"


def _location(loc: tuple) -> str:
    """A pydantic error location as a metadata path, without the union branches.

    A field typed as a union reports one error per branch it tried, under
    ``tuple[...]`` and class-name segments; the reader only needs the path in
    the metadata (``multiscales/0/coordinateTransformations/0/type``).
    """
    parts = [
        str(part)
        for part in loc
        if part != "__root__"
        and not (isinstance(part, str) and ("[" in part or part[:1].isupper()))
    ]
    return "/".join(parts)


def _format_errors(exc: Exception) -> list[str]:
    """``<location>: <message>`` lines for a pydantic error, else its text.

    The first message per location is kept, so a union field reads as one line.
    """
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            seen: dict[str, str] = {}
            for err in errors():
                loc = _location(tuple(err.get("loc", ())))
                seen.setdefault(loc, str(err.get("msg", "")).strip())
            if seen:
                return [f"{loc}: {msg}" if loc else msg for loc, msg in seen.items()]
        except Exception:  # pragma: no cover - a malformed error list
            pass
    text = str(exc).strip().splitlines()
    return [text[0] if text else type(exc).__name__]


def _model_for(layout: NgffLayout, version: str | None):
    """The ome-zarr-models class that validates ``layout`` at ``version``."""
    if version is not None and version.startswith("0.5"):
        from ome_zarr_models import v05 as models
    else:
        from ome_zarr_models import v04 as models
    return {
        "image": models.Image,
        "plate": models.HCS,
        "well": models.Well,
        "bioformats2raw": models.BioFormats2Raw,
        "labels": models.ImageLabel,
    }.get(layout)


def _validate_group(group, layout: NgffLayout, version: str | None, where: str) -> list[str]:
    model = _model_for(layout, version)
    if model is None:
        return []
    try:
        with warnings.catch_warnings():
            # The models warn on SHOULD-level findings too; those are not errors.
            warnings.simplefilter("ignore")
            model.from_zarr(group)
    except Exception as exc:
        return [f"{where}{line}" for line in _format_errors(exc)]
    return []


def _label_names(group, ome: dict[str, Any]) -> list[str]:
    """Names of an image's label images: ``labels/`` lists them in its attributes."""
    try:
        labels_group = group["labels"]
    except Exception:
        return []
    attrs = dict(getattr(labels_group, "attrs", {}) or {})
    block = attrs.get("ome", attrs)
    names = block.get("labels") if isinstance(block, dict) else None
    if isinstance(names, list) and all(isinstance(n, str) for n in names):
        return names
    return []


def validate_ngff_store(store_path: str, image_path: str | None = None) -> NgffValidation:
    """Validate the NGFF metadata of the store at ``store_path``.

    With ``image_path`` (a SpatialData store), the image element under it is
    validated, since that is what the viewer reads. Never raises: a store that
    cannot even be opened as a zarr group comes back ``ok=False`` with the
    reason as its only issue.
    """
    import zarr

    root = os.path.join(store_path, *image_path.split("/")) if image_path else store_path
    validator = _validator_name()
    try:
        group = zarr.open_group(root, mode="r")
        attrs = dict(group.attrs)
    except Exception as exc:
        return NgffValidation(
            ok=False,
            issues=[f"not a zarr group: {_format_errors(exc)[0]}"],
            validator=validator,
        )

    ome, version = _ome_attributes(attrs)
    layout = _layout_of(ome)
    if layout == "unknown":
        return NgffValidation(
            ok=False,
            ngff_version=version,
            issues=[
                "no NGFF metadata at the store root (multiscales, plate, well, "
                "bioformats2raw.layout or image-label)"
            ],
            validator=validator,
        )

    if version is not None and version not in _SPEC_VERSIONS:
        # A pre-release or tool-specific version (SpatialData writes
        # ``0.5-dev-spatialdata``): no released schema can judge it.
        return NgffValidation(
            ok=False,
            ngff_version=version,
            layout=layout,
            issues=[
                f"NGFF version {version!r} is not a released spec version "
                f"({', '.join(_SPEC_VERSIONS)}); other viewers may refuse it"
            ],
            labels=_label_names(group, ome) if layout == "image" else [],
            validator=validator,
        )

    issues = _validate_group(group, layout, version, "")
    labels: list[str] = []
    if layout == "image":
        labels = _label_names(group, ome)
        for name in labels:
            try:
                label_group = group["labels"][name]
            except Exception:
                issues.append(f"labels/{name}: listed in labels/ but missing")
                continue
            _, label_version = _ome_attributes(dict(label_group.attrs))
            issues += _validate_group(
                label_group, "labels", label_version or version, f"labels/{name}/"
            )

    if version is None:
        issues.insert(0, "no NGFF version in the metadata")
    return NgffValidation(
        ok=not issues,
        ngff_version=version,
        layout=layout,
        issues=issues[:NGFF_MAX_ISSUES],
        labels=labels,
        validator=validator,
    )
