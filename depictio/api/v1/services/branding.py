"""Instance branding resolution (issue #397, admin UI follow-up).

Two layers compose the effective branding:

- **Deployment defaults** — the ``DEPICTIO_BRANDING_*`` env vars
  (``settings.branding``), baked in by whoever operates the deployment
  (helm values, compose env).
- **Admin overrides** — a singleton document in ``instance_settings``,
  edited live from the /admin Branding panel. Per-field: an override set to
  ``None``/absent falls back to the env default, so a deployment configured
  by env keeps working until an admin explicitly changes something.

``get_effective_branding()`` is what every consumer reads: the
``/utils/public-config`` channel (viewer logo/name/primary color) and the
figure render paths (mantine template colorway) — API and Celery worker
alike, both have DB access. Reads go through a short TTL cache so the
per-figure template patch never adds a Mongo round-trip per render;
``set_branding_overrides`` invalidates it in-process (other processes catch
up within the TTL).
"""

from __future__ import annotations

import re
import time
from typing import Any

import pymongo

from depictio.api.v1.configs.config import MONGODB_URL, settings
from depictio.api.v1.configs.logging_init import logger

_DOC_ID = "branding"

# Lazily-created handle on the `instance_settings` collection. Deliberately a
# DEDICATED client with a short server-selection timeout rather than the
# shared db.py client (30s): the effective branding is read on the figure
# render path, and a Mongo hiccup must degrade to the env defaults in ~2s,
# not stall every render for half a minute. Tests inject a fake here.
instance_settings_collection: Any = None


def _get_collection() -> Any:
    global instance_settings_collection
    if instance_settings_collection is None:
        client: pymongo.MongoClient = pymongo.MongoClient(
            MONGODB_URL, serverSelectionTimeoutMS=2000, connectTimeoutMS=2000
        )
        instance_settings_collection = client[settings.mongodb.db_name]["instance_settings"]
    return instance_settings_collection


#: Fields an admin can override. Mirrors BrandingConfig (settings_models.py),
#: except colorway is stored as a list here rather than a comma-string.
BRANDING_FIELDS = ("logo_url", "logo_url_dark", "app_name", "primary_color", "colorway")

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
#: Mantine palette name (e.g. "teal") — the other accepted primary_color form.
PALETTE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")

# Render-path cache: get_effective_branding() runs for every server-rendered
# figure (template colorway patch), so the singleton read is memoized briefly.
_CACHE_TTL_SECONDS = 30.0
_cache: tuple[float, dict[str, Any]] | None = None


def get_branding_overrides() -> dict[str, Any]:
    """The raw admin overrides document ({} when none saved yet)."""
    doc = _get_collection().find_one({"_id": _DOC_ID}) or {}
    return {field: doc.get(field) for field in BRANDING_FIELDS if doc.get(field) is not None}


def set_branding_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    """Replace the admin overrides with ``overrides`` (validated fields only).

    ``None`` values are dropped — absence is what "fall back to the env
    default" looks like. Returns the new effective branding.
    """
    doc = {field: overrides[field] for field in BRANDING_FIELDS if overrides.get(field) is not None}
    if doc:
        _get_collection().replace_one({"_id": _DOC_ID}, doc, upsert=True)
    else:
        _get_collection().delete_one({"_id": _DOC_ID})
    invalidate_branding_cache()
    return get_effective_branding()


def update_branding_override(field: str, value: Any) -> dict[str, Any]:
    """Set (or clear, with ``None``) a single override field in place."""
    if field not in BRANDING_FIELDS:
        raise ValueError(f"Unknown branding field: {field}")
    if value is None:
        _get_collection().update_one({"_id": _DOC_ID}, {"$unset": {field: ""}})
    else:
        _get_collection().update_one({"_id": _DOC_ID}, {"$set": {field: value}}, upsert=True)
    invalidate_branding_cache()
    return get_effective_branding()


def env_branding_defaults() -> dict[str, Any]:
    """The deployment-level (env var) branding, colorway already parsed."""
    branding = settings.branding
    return {
        "logo_url": branding.logo_url,
        "logo_url_dark": branding.logo_url_dark,
        "app_name": branding.app_name,
        "primary_color": branding.primary_color,
        "colorway": branding.colorway_list,
    }


def get_effective_branding(use_cache: bool = True) -> dict[str, Any]:
    """Env defaults overridden per-field by the admin document.

    Never raises: an unreachable overrides store degrades to the env defaults
    (cached like a successful read, so a Mongo outage costs one short
    connection attempt per TTL window — not one per render).
    """
    global _cache
    now = time.monotonic()
    if use_cache and _cache and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]

    effective = env_branding_defaults()
    try:
        effective.update(get_branding_overrides())
    except Exception as exc:
        logger.warning(f"Branding overrides unavailable, using env defaults: {exc}")
    _cache = (now, effective)
    return effective


def invalidate_branding_cache() -> None:
    global _cache
    _cache = None


# ── Logo upload validation ────────────────────────────────────────────────────
# Same rules as the per-dashboard logo endpoint: PNG/JPEG/WebP only (SVG can
# carry scripts and is served same-origin), extension pinned by the declared
# content type, magic bytes checked against it.

LOGO_TYPES: dict[str, tuple[str, tuple[bytes, ...]]] = {
    "image/png": (".png", (b"\x89PNG\r\n\x1a\n",)),
    "image/jpeg": (".jpg", (b"\xff\xd8\xff",)),
    "image/webp": (".webp", (b"RIFF",)),
}
LOGO_MAX_BYTES = 2 * 1024 * 1024


def validate_logo_upload(content_type: str | None, content: bytes) -> str:
    """Return the file extension for a valid logo upload, or raise ValueError."""
    spec = LOGO_TYPES.get(content_type or "")
    if not spec:
        raise ValueError("Unsupported image type — use PNG, JPEG or WebP.")
    ext, magic_prefixes = spec
    if len(content) > LOGO_MAX_BYTES:
        raise ValueError("Logo file too large (max 2MB).")
    valid_magic = content.startswith(magic_prefixes)
    if valid_magic and ext == ".webp":
        valid_magic = content[8:12] == b"WEBP"
    if not valid_magic:
        raise ValueError("File content does not match the declared image type.")
    return ext
