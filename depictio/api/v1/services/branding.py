"""Instance branding resolution (issue #397).

Three layers compose what a visitor sees:

- **Deployment defaults** — the ``DEPICTIO_BRANDING_*`` env vars
  (``settings.branding``), baked in by whoever operates the deployment
  (helm values, compose env).
- **Admin overrides** — a singleton document in ``instance_settings``,
  edited live from the /admin Branding panel.
- **Dashboard override** — ``DashboardData.brand_theme``, applied by the
  viewer and the figure render path on top of the two above.

All three are the same ``BrandTheme`` shape (``depictio.models.models.branding``),
so composing them is one right-wins fold and an unset field always means
"inherit from the layer below".

``resolve_effective_brand_theme()`` is what every consumer reads: the
``/utils/public-config`` channel (viewer logo/name/colors) and the figure
render paths (Plotly template colorway) — API and Celery worker alike, both
have DB access. It returns a *resolved* theme, i.e. one where the derived
values (figure colorway, sequential colorscale) are already materialised, so
the SPA never re-derives them and can't drift from the server.

Reads go through a short TTL cache so the per-figure template patch never adds
a Mongo round-trip per render; ``set_brand_theme_overrides`` invalidates it
in-process (other processes catch up within the TTL).
"""

from __future__ import annotations

import time
from typing import Any, Optional

import pymongo

from depictio.api.v1.configs.config import MONGODB_URL, settings
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.branding import (
    HEX_COLOR_RE,
    PALETTE_NAME_RE,
    BrandTheme,
    merge_brand_themes,
    resolve_brand_theme,
)

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


#: Flat field names the pre-BrandTheme admin panel wrote. Read-only support, so
#: a dev instance branded before the rework doesn't silently lose its logo.
_LEGACY_FIELD_MAP = {
    "logo_url": "logo_url",
    "logo_url_dark": "logo_url_dark",
    "app_name": "app_name",
    "primary_color": "primary",
}

# Render-path cache: the effective theme is read for every server-rendered
# figure (template patch), so the singleton read is memoized briefly.
_CACHE_TTL_SECONDS = 30.0
_cache: tuple[float, BrandTheme] | None = None


def _theme_from_doc(doc: dict[str, Any]) -> BrandTheme:
    """Parse a stored overrides document, tolerating the pre-BrandTheme shape."""
    if not doc:
        return BrandTheme()
    if isinstance(doc.get("theme"), dict):
        return BrandTheme(**doc["theme"])

    legacy = {new: doc[old] for old, new in _LEGACY_FIELD_MAP.items() if doc.get(old) is not None}
    if doc.get("colorway"):
        legacy["plots"] = {"colorway": doc["colorway"]}
    return BrandTheme(**legacy) if legacy else BrandTheme()


def get_brand_theme_overrides() -> BrandTheme:
    """The raw admin overrides (an empty theme when none are saved)."""
    return _theme_from_doc(_get_collection().find_one({"_id": _DOC_ID}) or {})


def set_brand_theme_overrides(theme: Optional[BrandTheme]) -> BrandTheme:
    """Replace the admin overrides with ``theme``. Returns the new effective theme.

    An empty theme deletes the document: absence is what "fall back to the
    deployment defaults" looks like.
    """
    payload = (theme or BrandTheme()).model_dump(exclude_none=True)
    if payload:
        _get_collection().replace_one({"_id": _DOC_ID}, {"theme": payload}, upsert=True)
    else:
        _get_collection().delete_one({"_id": _DOC_ID})
    invalidate_branding_cache()
    return get_effective_brand_theme(use_cache=False)


def patch_brand_theme_overrides(patch: dict[str, Any]) -> BrandTheme:
    """Set (or clear, with ``None``) some top-level override fields in place.

    Used by the logo upload endpoints, which write two fields and must not
    clobber a concurrent edit of the rest of the panel.
    """
    unknown = set(patch) - set(BrandTheme.model_fields)
    if unknown:
        raise ValueError(f"Unknown brand theme field(s): {sorted(unknown)}")
    current = get_brand_theme_overrides().model_dump(exclude_none=True)
    for field, value in patch.items():
        if value is None:
            current.pop(field, None)
        else:
            current[field] = value
    return set_brand_theme_overrides(BrandTheme(**current))


def env_brand_theme() -> BrandTheme:
    """The deployment-level (env var) branding."""
    return settings.branding.as_brand_theme()


def get_effective_brand_theme(use_cache: bool = True) -> BrandTheme:
    """Env defaults overridden per-field by the admin document.

    Never raises: an unreachable overrides store degrades to the env defaults
    (cached like a successful read, so a Mongo outage costs one short
    connection attempt per TTL window — not one per render).
    """
    global _cache
    now = time.monotonic()
    if use_cache and _cache and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]

    env = env_brand_theme()
    try:
        effective = merge_brand_themes(env, get_brand_theme_overrides())
    except Exception as exc:
        logger.warning(f"Branding overrides unavailable, using env defaults: {exc}")
        effective = env
    _cache = (now, effective)
    return effective


def resolve_effective_brand_theme(use_cache: bool = True) -> BrandTheme:
    """The effective theme with every derived value materialised.

    This is the wire format: what ``/utils/public-config`` ships to the SPA and
    what the figure render path reads.
    """
    return resolve_brand_theme(get_effective_brand_theme(use_cache=use_cache))


def invalidate_branding_cache() -> None:
    global _cache
    _cache = None


# ── Logo upload validation ────────────────────────────────────────────────────
# Shared by the instance logo endpoints and the per-dashboard logo endpoint:
# PNG/JPEG/WebP only (SVG can carry scripts and is served same-origin), the
# extension pinned by the declared content type, magic bytes checked against it.

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


__all__ = [
    "HEX_COLOR_RE",
    "LOGO_MAX_BYTES",
    "LOGO_TYPES",
    "PALETTE_NAME_RE",
    "env_brand_theme",
    "get_brand_theme_overrides",
    "get_effective_brand_theme",
    "instance_settings_collection",
    "invalidate_branding_cache",
    "resolve_effective_brand_theme",
    "set_brand_theme_overrides",
    "patch_brand_theme_overrides",
    "validate_logo_upload",
]
