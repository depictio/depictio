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
from collections.abc import Callable
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


def _listed_series(group) -> list[str] | None:
    """The series paths a bioformats2raw container's ``OME`` group lists
    (0.4 ``OME/.zattrs`` ``series``, 0.5 ``OME/zarr.json`` ``ome.series``),
    or None when it lists none and the series are numbered from ``0``."""
    try:
        attrs = dict(group["OME"].attrs) if "OME" in group else {}
    except Exception:
        return None
    ome = attrs.get("ome")
    series = (ome if isinstance(ome, dict) else attrs).get("series")
    if isinstance(series, list) and series and all(isinstance(p, str) and p for p in series):
        return series
    return None


def _validation_error_in(exc: BaseException):
    """The pydantic ValidationError behind ``exc``, if any: a spec violation,
    even when ome-zarr-models re-raised it as a ValueError for a nested group.
    None means something else failed (zarr-python reading an array)."""
    from pydantic import ValidationError

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, ValidationError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


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
            spec_error = _validation_error_in(exc)
            if spec_error is not None:
                # The metadata breaks the spec: a finding, wherever it sits.
                self.issues += [f"{where}{line}" for line in _format_errors(spec_error)]
                return
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
        self.attrs("bioformats2raw", ome)
        listed = _listed_series(group)
        if listed is not None:
            # The OME group names the series: check a spread of them.
            for path in _spread(listed):
                if path in group:
                    self.group(group[path], "image", f"{path}/")
                else:
                    self.issues.append(f"{path}: listed in OME/series but missing")
            return f"bioformats2raw metadata and {min(len(listed), SAMPLED_MEMBERS)} of {len(listed)} series"
        # No list: the series are 0, 1, 2... until one is missing. Counting
        # them all is a read per series, so only the first few.
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


def callback_store(read: Callable[[str], bytes | None]):
    """A read-only zarr store whose every key comes from ``read(key)`` (None:
    no such key).

    The API validates a remote store through this, with its own reader, which
    holds the host allow-list and size caps: zarr's HTTP client would follow
    any URL the metadata leads it to. Not listable, like any store over HTTP;
    each key is read once.
    """
    from zarr.abc.store import (
        OffsetByteRequest,
        RangeByteRequest,
        Store,
        SuffixByteRequest,
    )

    class _CallbackStore(Store):
        supports_writes = False
        supports_deletes = False
        supports_listing = False
        supports_partial_writes = False

        def __init__(self) -> None:
            super().__init__(read_only=True)
            self._seen: dict[str, bytes | None] = {}

        def __eq__(self, other: object) -> bool:
            return self is other

        def _get(self, key: str) -> bytes | None:
            if key not in self._seen:
                self._seen[key] = read(key)
            return self._seen[key]

        async def get(self, key, prototype, byte_range=None):
            data = self._get(key)
            if data is None:
                return None
            if isinstance(byte_range, RangeByteRequest):
                data = data[byte_range.start : byte_range.end]
            elif isinstance(byte_range, OffsetByteRequest):
                data = data[byte_range.offset :]
            elif isinstance(byte_range, SuffixByteRequest):
                data = data[-byte_range.suffix :]
            return prototype.buffer.from_bytes(data)

        async def get_partial_values(self, prototype, key_ranges):
            return [await self.get(key, prototype, rng) for key, rng in key_ranges]

        async def exists(self, key: str) -> bool:
            return self._get(key) is not None

        async def set(self, key, value) -> None:
            raise PermissionError("read-only store")

        async def delete(self, key) -> None:
            raise PermissionError("read-only store")

        async def list(self):
            return
            yield

        async def list_prefix(self, prefix: str):
            return
            yield

        async def list_dir(self, prefix: str):
            return
            yield

    return _CallbackStore()


def validate_ngff_store(store_path, image_path: str | None = None) -> NgffValidation | None:
    """Validate the NGFF metadata of the store at ``store_path`` (a path, or a
    zarr store such as ``callback_store``).

    With ``image_path`` (a SpatialData store), the image element under it is
    validated, since that is what the viewer reads. Never raises: a store that
    cannot even be opened as a zarr group comes back ``ok=False`` with the
    reason as its only issue. None when this install cannot validate
    (``validator_available``): no report rather than a wrong one.
    """
    if not validator_available():
        return None
    import zarr

    validator = _validator_name()
    try:
        if isinstance(store_path, str):
            root = os.path.join(store_path, *image_path.split("/")) if image_path else store_path
            group = zarr.open_group(root, mode="r")
        else:
            group = zarr.open_group(store=store_path, path=image_path or "", mode="r")
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
        first = (_listed_series(group) or ["0"])[0]
        try:
            version = _ome_attributes(dict(group[first].attrs))[1]
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
