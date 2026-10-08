"""Data Manifest contract — the remote-data entry point.

A manifest is a flat index of remote files: one entry per file, keyed by a
canonical entity/sample ``id`` and a ``type`` whose value is a data collection
tag. See ``docs/design/rfc-remote-data-manifests.md`` for the full contract;
the stability rules that matter here:

- URLs are absolute (``s3://`` or ``https://``; ``http://`` only behind
  ``DEPICTIO_REMOTE_ALLOW_HTTP``).
- The schema is closed — ``extra`` is the only open field.
- ``version`` gates schema evolution.
- An entry listed twice (same ``id``, ``type`` and ``url``) is refused.
"""

import csv
import io
import json
import os

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

SUPPORTED_MANIFEST_VERSIONS = ("1",)

_REMOTE_SCHEMES_ALWAYS = ("s3://", "https://")
_REMOTE_SCHEME_HTTP = "http://"


def _http_allowed() -> bool:
    return os.environ.get("DEPICTIO_REMOTE_ALLOW_HTTP", "false").lower() in (
        "true",
        "1",
        "yes",
    )


def is_remote_url(value: str) -> bool:
    """True if ``value`` is a remote location Depictio can ingest from.

    Scheme matching is case-insensitive (RFC 3986). Plain ``http://`` counts
    only when ``DEPICTIO_REMOTE_ALLOW_HTTP`` is set — checked lazily so tests
    and airgapped deployments can opt in per-process.
    """
    lowered = value.lower()
    if lowered.startswith(_REMOTE_SCHEMES_ALWAYS):
        return True
    return lowered.startswith(_REMOTE_SCHEME_HTTP) and _http_allowed()


def validate_remote_url_syntax(value: str) -> str:
    """Syntactic-only URL validation shared by models (no network calls here).

    Reachability, DNS and SSRF checks belong to the API-side fetch gateway
    (``depictio.api.v1.remote_fetch``), not to pydantic validators.
    """
    if not value:
        raise ValueError("URL cannot be empty")
    if not is_remote_url(value):
        allowed = list(_REMOTE_SCHEMES_ALWAYS) + ([_REMOTE_SCHEME_HTTP] if _http_allowed() else [])
        raise ValueError(f"URL scheme not allowed for '{value}'. Allowed schemes: {allowed}")
    return value


class ManifestEntry(BaseModel):
    """One remote file: ``id`` (canonical entity/sample ID), ``type`` (DC tag),
    ``url`` (absolute), optional ``run`` grouping."""

    id: str
    type: str
    url: str
    run: str | None = None
    extra: dict[str, str] = {}

    model_config = ConfigDict(extra="forbid")

    @field_validator("id", "type")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field cannot be empty")
        return v.strip()

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        return validate_remote_url_syntax(v)


class DataManifest(BaseModel):
    """The manifest contract: a versioned, closed list of ``ManifestEntry``.

    The entries are a list, not a set, and an entry repeated with the same
    ``id``, ``type`` and ``url`` is refused rather than deduplicated: each copy
    would become its own File, and the table would hold that file's rows twice.
    """

    version: str = "1"
    entries: list[ManifestEntry] = []
    source: str | None = None  # where the manifest was fetched from (provenance)

    model_config = ConfigDict(extra="forbid")

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if v not in SUPPORTED_MANIFEST_VERSIONS:
            raise ValueError(
                f"Unsupported manifest version '{v}'. Supported: {list(SUPPORTED_MANIFEST_VERSIONS)}"
            )
        return v

    @model_validator(mode="after")
    def reject_repeated_entries(self) -> "DataManifest":
        first_position: dict[tuple[str, str, str], int] = {}
        repeated: list[str] = []
        for position, entry in enumerate(self.entries, start=1):
            key = (entry.id, entry.type, entry.url)
            if key in first_position:
                # Without its query string: a presigned URL's is its signature.
                shown_url = entry.url.split("?", 1)[0]
                repeated.append(
                    f"entries {first_position[key]} and {position} "
                    f"(id={entry.id}, type={entry.type}, url={shown_url})"
                )
            else:
                first_position[key] = position
        if repeated:
            more = f", and {len(repeated) - 3} more" if len(repeated) > 3 else ""
            raise ValueError(
                f"Manifest lists the same file more than once: {'; '.join(repeated[:3])}{more}. "
                "Remove the repeated rows."
            )
        return self

    @classmethod
    def parse(
        cls,
        content: str | bytes,
        source: str | None = None,
        field_map: dict[str, str] | None = None,
    ) -> "DataManifest":
        """Parse a manifest whose format is not known yet: JSON or CSV.

        A ``.json`` ``source`` (query string ignored) is JSON, and so is a
        document that starts with ``{`` or ``[``; anything else is CSV. A UTF-8
        byte order mark is ignored, here and in both parsers.
        """
        text = _as_text(content)
        is_json_source = (source or "").split("?", 1)[0].lower().endswith(".json")
        if is_json_source or text.lstrip().startswith(("{", "[")):
            return cls.from_json(text, source=source, field_map=field_map)
        return cls.from_csv(text, source=source, field_map=field_map)

    def types(self) -> set[str]:
        """Distinct ``type`` values (= data collection tags) in the manifest."""
        return {entry.type for entry in self.entries}

    def entries_for_type(self, dc_tag: str) -> list[ManifestEntry]:
        return [entry for entry in self.entries if entry.type == dc_tag]

    @classmethod
    def from_csv(
        cls,
        text: str | bytes,
        source: str | None = None,
        field_map: dict[str, str] | None = None,
    ) -> "DataManifest":
        """Parse a CSV manifest. Required columns: ``id``, ``type``, ``url``.

        ``run`` is optional; any other column is folded into ``extra`` — the
        CSV affordance for the contract's single open field. ``field_map``
        remaps non-canonical column names onto the contract, keyed by
        canonical name (e.g. ``{"id": "sample", "url": "path"}``). Column
        names and the ``url`` and ``run`` cells are read without surrounding
        spaces, so ``id, type, url`` works as a header.
        """
        reader = csv.DictReader(io.StringIO(_as_text(text)))
        # Rows are keyed by these names, so they are stripped here and not
        # only for the presence check below.
        fieldnames = [name.strip() for name in (reader.fieldnames or [])]
        reader.fieldnames = fieldnames
        column_of = _resolve_field_map(field_map)
        missing = {column_of[k] for k in ("id", "type", "url")} - set(fieldnames)
        if missing:
            raise ValueError(f"Manifest CSV is missing required column(s): {sorted(missing)}")

        known = {column_of[k] for k in ("id", "type", "url", "run")}
        entries: list[ManifestEntry] = []
        for row in reader:
            if not any((value or "").strip() for value in row.values()):
                continue  # tolerate blank lines
            extra = {
                key: (value or "")
                for key, value in row.items()
                if key is not None and key not in known
            }
            entries.append(
                ManifestEntry(
                    id=(row.get(column_of["id"]) or ""),
                    type=(row.get(column_of["type"]) or ""),
                    url=(row.get(column_of["url"]) or "").strip(),
                    run=(row.get(column_of["run"]) or "").strip() or None,
                    extra=extra,
                )
            )
        return cls(entries=entries, source=source)

    @classmethod
    def from_json(
        cls,
        text: str | bytes,
        source: str | None = None,
        field_map: dict[str, str] | None = None,
    ) -> "DataManifest":
        """Parse a JSON manifest: either ``{"entries": [...]}`` (with optional
        ``version``) or a bare list of entries. ``field_map`` behaves as in
        ``from_csv`` and applies to each entry object."""
        try:
            payload = json.loads(_as_text(text))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Manifest is not valid JSON: {exc}")

        def _remap(entry: dict) -> dict:
            if not field_map:
                return entry
            column_of = _resolve_field_map(field_map)
            remapped = {k: v for k, v in entry.items() if k not in column_of.values()}
            for canonical, actual in column_of.items():
                if actual in entry:
                    remapped[canonical] = entry[actual]
            return remapped

        if isinstance(payload, list):
            manifest = cls(
                entries=[ManifestEntry(**_remap(entry)) for entry in payload], source=source
            )
        elif isinstance(payload, dict):
            data: dict[str, object] = dict(payload)
            entries = data.get("entries")
            if field_map and isinstance(entries, list):
                # Non-dict entries pass through untouched so pydantic reports
                # them as validation errors instead of being dropped here.
                data["entries"] = [_remap(e) if isinstance(e, dict) else e for e in entries]
            manifest = cls.model_validate(data)
            manifest.source = source or manifest.source
        else:
            raise ValueError("Manifest JSON must be an object or a list of entries")
        return manifest


def _as_text(content: str | bytes) -> str:
    """A manifest's text, without the UTF-8 byte order mark spreadsheet exports add."""
    if isinstance(content, bytes):
        return content.decode("utf-8-sig")
    return content.removeprefix("﻿")


def _resolve_field_map(field_map: dict[str, str] | None) -> dict[str, str]:
    """Canonical field name -> actual column name, defaulting to identity."""
    resolved = {"id": "id", "type": "type", "url": "url", "run": "run"}
    for canonical, actual in (field_map or {}).items():
        if canonical not in resolved:
            raise ValueError(
                f"Unknown manifest field '{canonical}' in field_map (known: {sorted(resolved)})"
            )
        if actual:
            resolved[canonical] = actual
    return resolved
