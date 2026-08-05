"""Data Manifest contract — the remote-data entry point.

A manifest is a flat index of remote files: one entry per file, keyed by a
canonical entity/sample ``id`` and a ``type`` whose value is a data collection
tag. See ``docs/design/rfc-remote-data-manifests.md`` for the full contract;
the stability rules that matter here:

- URLs are absolute (``s3://`` or ``https://``; ``http://`` only behind
  ``DEPICTIO_REMOTE_ALLOW_HTTP``).
- The schema is closed — ``extra`` is the only open field.
- ``version`` gates schema evolution.
"""

import csv
import io
import json
import os

from pydantic import BaseModel, ConfigDict, field_validator

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
    """The manifest contract: a versioned, closed list of ``ManifestEntry``."""

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

    def types(self) -> set[str]:
        """Distinct ``type`` values (= data collection tags) in the manifest."""
        return {entry.type for entry in self.entries}

    def entries_for_type(self, dc_tag: str) -> list[ManifestEntry]:
        return [entry for entry in self.entries if entry.type == dc_tag]

    @classmethod
    def from_csv(
        cls,
        text: str,
        source: str | None = None,
        field_map: dict[str, str] | None = None,
    ) -> "DataManifest":
        """Parse a CSV manifest. Required columns: ``id``, ``type``, ``url``.

        ``run`` is optional; any other column is folded into ``extra`` — the
        CSV affordance for the contract's single open field. ``field_map``
        remaps non-canonical column names onto the contract, keyed by
        canonical name (e.g. ``{"id": "sample", "url": "path"}``).
        """
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = [name.strip() for name in (reader.fieldnames or [])]
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
                if key is not None and key.strip() not in known
            }
            entries.append(
                ManifestEntry(
                    id=(row.get(column_of["id"]) or ""),
                    type=(row.get(column_of["type"]) or ""),
                    url=(row.get(column_of["url"]) or ""),
                    run=(row.get(column_of["run"]) or None),
                    extra={k.strip(): v for k, v in extra.items()},
                )
            )
        return cls(entries=entries, source=source)

    @classmethod
    def from_json(
        cls,
        text: str,
        source: str | None = None,
        field_map: dict[str, str] | None = None,
    ) -> "DataManifest":
        """Parse a JSON manifest: either ``{"entries": [...]}`` (with optional
        ``version``) or a bare list of entries. ``field_map`` behaves as in
        ``from_csv`` and applies to each entry object."""
        try:
            payload = json.loads(text)
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
