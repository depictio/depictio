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
from functools import lru_cache
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


@lru_cache(maxsize=1)
def validator_available() -> bool:
    """Whether ``ome-zarr-models`` is installed and its models can validate.

    It needs Python 3.12 at the pinned release. An older release imports but
    leaves its models half-built under a newer pydantic, and every store would
    then read as invalid; such an install validates nothing instead.
    """
    try:
        from ome_zarr_models import v04, v05
    except Exception:
        return False
    return all(getattr(m.Image, "__pydantic_complete__", True) for m in (v04, v05))


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


def _models(version: str | None):
    """The ome-zarr-models modules for ``version``."""
    if version is not None and version.startswith("0.5"):
        from ome_zarr_models.v05 import bioformats2raw, hcs, image, image_label, well
    else:
        from ome_zarr_models.v04 import bioformats2raw, hcs, image, image_label, well
    return {
        "image": (image.Image, image.ImageAttrs),
        "plate": (hcs.HCS, hcs.HCSAttrs),
        "well": (well.Well, well.WellAttrs),
        "bioformats2raw": (bioformats2raw.BioFormats2Raw, bioformats2raw.BioFormats2RawAttrs),
        "labels": (image_label.ImageLabel, image_label.ImageLabelAttrs),
    }


#: Wells, fields and bioformats2raw series read past a container's own
#: metadata. ``ome-zarr-models`` walks them all, one after another: thousands
#: of reads on a 384-well plate, minutes over HTTP. A few spread across the
#: container catch a writer's systematic mistakes, which is what this is for.
SAMPLED_MEMBERS = 3


def _spread(items: list, n: int = SAMPLED_MEMBERS) -> list:
    """First, middle and last of ``items`` (all of them when there are few)."""
    if len(items) <= n:
        return list(items)
    picks = sorted({round(i * (len(items) - 1) / (n - 1)) for i in range(n)})
    return [items[i] for i in picks]


def _quiet(call) -> None:
    with warnings.catch_warnings():
        # The models warn on SHOULD-level findings too; those are not errors.
        warnings.simplefilter("ignore")
        call()


class _Check:
    """One store's validation: the issues found, and the groups whose arrays
    zarr-python could not open (checked on their metadata alone)."""

    def __init__(self, version: str | None):
        self.version = version
        self.models = _models(version)
        self.issues: list[str] = []
        self.unread: list[str] = []

    def attrs(self, layout: NgffLayout, ome: dict[str, Any], where: str = "") -> None:
        attrs_cls = self.models[layout][1]
        try:
            _quiet(lambda: attrs_cls.model_validate(ome))
        except Exception as exc:
            self.issues += [f"{where}{line}" for line in _format_errors(exc)]

    def group(self, group, layout: NgffLayout, where: str = "") -> None:
        """The group with its arrays; its metadata alone when zarr-python
        cannot open them (``>u1`` is valid Zarr v2 that zarr-python 3 refuses),
        since that is the reader's limit, not the store's."""
        model = self.models[layout][0]
        try:
            _quiet(lambda: model.from_zarr(group))
            return
        except Exception as exc:
            errors = _format_errors(exc)
        before = len(self.issues)
        ome, _ = _ome_attributes(dict(group.attrs))
        self.attrs(layout, ome, where)
        if len(self.issues) == before:
            # The metadata is fine: what failed was reading the arrays.
            self.unread.append(f"{where or 'root: '}{errors[0]}")

    def plate(self, group, ome: dict[str, Any]) -> str:
        self.attrs("plate", ome)
        wells = (ome.get("plate") or {}).get("wells") or []
        paths = [w["path"] for w in wells if isinstance(w, dict) and isinstance(w.get("path"), str)]
        sample = _spread(paths)
        most_fields = 0
        for path in sample:
            try:
                well = group[path]
            except Exception:
                self.issues.append(f"{path}: listed in the plate but missing")
                continue
            most_fields = max(most_fields, self.well(well, f"{path}/"))
        checked = f"plate metadata and {len(sample)} of {len(paths)} wells"
        if most_fields > SAMPLED_MEMBERS:
            checked += f", {SAMPLED_MEMBERS} of up to {most_fields} fields each"
        return checked

    def well(self, group, where: str) -> int:
        """A well's metadata and a few of its fields; returns its field count."""
        ome, _ = _ome_attributes(dict(group.attrs))
        self.attrs("well", ome, where)
        images = (ome.get("well") or {}).get("images") or []
        paths = [
            i["path"] for i in images if isinstance(i, dict) and isinstance(i.get("path"), str)
        ]
        for path in _spread(paths):
            try:
                field = group[path]
            except Exception:
                self.issues.append(f"{where}{path}: listed in the well but missing")
                continue
            self.group(field, "image", f"{where}{path}/")
        return len(paths)

    def bioformats2raw(self, group, ome: dict[str, Any]) -> str:
        # bioformats2raw lists no series: they are 0, 1, 2... until one is
        # missing. Counting them all is a read per series, so only the first few.
        self.attrs("bioformats2raw", ome)
        series = 0
        while series < SAMPLED_MEMBERS and str(series) in group:
            self.group(group[str(series)], "image", f"{series}/")
            series += 1
        if not series:
            self.issues.append("0: a bioformats2raw container needs its first series at 0/")
        return f"bioformats2raw metadata and the first {series} series"

    def scope(self, checked: str | None) -> str | None:
        if not self.unread:
            return checked
        note = (
            "metadata only: zarr-python could not read the arrays "
            f"({self.unread[0]}{f', +{len(self.unread) - 1} more' if len(self.unread) > 1 else ''})"
        )
        return f"{note}; {checked}" if checked else note


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


def validate_ngff_store(store_path: str, image_path: str | None = None) -> NgffValidation | None:
    """Validate the NGFF metadata of the store at ``store_path``.

    With ``image_path`` (a SpatialData store), the image element under it is
    validated, since that is what the viewer reads. Never raises: a store that
    cannot even be opened as a zarr group comes back ``ok=False`` with the
    reason as its only issue. None when this install cannot validate
    (``validator_available``): no report rather than a wrong one.
    """
    if not validator_available():
        return None
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
    if layout == "bioformats2raw" and version is None:
        # 0.4 puts no version on a bioformats2raw root: its series carry it.
        try:
            version = _ome_attributes(dict(group["0"].attrs))[1]
        except Exception:
            pass
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

    check = _Check(version)
    checked: str | None = None
    if layout == "plate":
        checked = check.plate(group, ome)
    elif layout == "bioformats2raw":
        checked = check.bioformats2raw(group, ome)
    else:
        check.group(group, layout)
    labels: list[str] = []
    if layout == "image":
        labels = _label_names(group, ome)
        for name in labels:
            try:
                label_group = group["labels"][name]
            except Exception:
                check.issues.append(f"labels/{name}: listed in labels/ but missing")
                continue
            _, label_version = _ome_attributes(dict(label_group.attrs))
            label_check = _Check(label_version or version)
            label_check.group(label_group, "labels", f"labels/{name}/")
            check.issues += label_check.issues
            check.unread += label_check.unread

    issues = check.issues
    checked = check.scope(checked)
    if version is None:
        issues.insert(0, "no NGFF version in the metadata")
    return NgffValidation(
        ok=not issues,
        ngff_version=version,
        layout=layout,
        issues=issues[:NGFF_MAX_ISSUES],
        labels=labels,
        validator=validator,
        checked=checked,
    )
