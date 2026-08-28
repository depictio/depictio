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

import base64
import time
from pathlib import Path
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
from depictio.version import get_api_version

_DOC_ID = "branding"

# Lazily-created handle on the `instance_settings` collection. Deliberately a
# DEDICATED client with a short server-selection timeout rather than the
# shared db.py client (30s): the effective branding is read on the figure
# render path, and a Mongo hiccup must degrade to the env defaults in ~2s,
# not stall every render for half a minute. Tests inject a fake here.
instance_settings_collection: Any = None

_client: Optional[pymongo.MongoClient] = None


def _get_client() -> pymongo.MongoClient:
    global _client
    if _client is None:
        _client = pymongo.MongoClient(
            MONGODB_URL, serverSelectionTimeoutMS=2000, connectTimeoutMS=2000
        )
    return _client


def _get_collection() -> Any:
    global instance_settings_collection
    if instance_settings_collection is None:
        instance_settings_collection = _get_client()[settings.mongodb.db_name][
            settings.mongodb.collections.instance_settings_collection
        ]
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


# ── Uploaded logo storage ─────────────────────────────────────────────────────
# Logos live in MongoDB, not on the API container's filesystem. A theme document
# only ever holds a URL, and that URL used to point into
# `depictio/api/static/branding/` (or `.../dashboard_logos/`): gitignored, with
# no compose volume and no Helm PVC behind it, so a rebuild or a redeploy left
# the document claiming a logo whose bytes were gone. `validate_logo_upload`
# caps an upload at LOGO_MAX_BYTES, so an asset sits far under Mongo's 16MB
# limit.

#: Same dedicated-client rationale as `instance_settings_collection` above, and
#: the same injection point for tests.
branding_assets_collection: Any = None

_API_PREFIX = f"/depictio/api/{get_api_version()}"

#: Only reached by a document stored without a content type — every upload path
#: goes through `validate_logo_upload`, which admits nothing but the LOGO_TYPES.
_FALLBACK_CONTENT_TYPE = "application/octet-stream"


def _get_assets_collection() -> Any:
    global branding_assets_collection
    if branding_assets_collection is None:
        branding_assets_collection = _get_client()[settings.mongodb.db_name][
            settings.mongodb.collections.branding_assets_collection
        ]
    return branding_assets_collection


def instance_logo_key(variant: str) -> str:
    """Asset key for an instance logo variant (``light`` / ``dark``)."""
    return f"instance-{variant}"


def dashboard_logo_key(dashboard_id: Any) -> str:
    """Asset key for a dashboard's own logo."""
    return f"dashboard-{dashboard_id}"


def logo_asset_url(key: str) -> str:
    """The URL serving ``key``, cache-busted so a replacement shows up at once.

    ``?v=`` mirrors the screenshot thumbnails' `screenshot_ts` idiom: the path
    is stable, so without it a browser keeps the previous logo after an upload.
    """
    if key.startswith("instance-"):
        endpoint = f"utils/branding/logo/{key.removeprefix('instance-')}"
    else:
        endpoint = f"dashboards/logo/{key.removeprefix('dashboard-')}"
    return f"{_API_PREFIX}/{endpoint}?v={int(time.time())}"


#: What the logo endpoints answer with. Safe because `logo_asset_url` mints a
#: fresh ``?v=`` on every upload: the bytes behind a given URL never change.
LOGO_CACHE_CONTROL = "public, max-age=31536000, immutable"


def store_logo_asset(key: str, content: bytes, content_type: str | None) -> str:
    """Store (or replace) a logo's bytes. Returns the URL to put on the theme.

    ``content_type`` is the upload's declared type, already checked against the
    magic bytes by `validate_logo_upload`; it is optional only because
    ``UploadFile.content_type`` is.

    Base64 rather than BSON ``Binary`` so the document is plain JSON: the
    backup endpoint serialises with ``json.dump(..., default=str)``, which
    would turn raw bytes into an unrestorable ``repr``. The ~33% overhead on an
    asset capped at LOGO_MAX_BYTES is worth a brand that survives a restore.
    """
    _get_assets_collection().replace_one(
        {"_id": key},
        {
            "content_type": content_type or _FALLBACK_CONTENT_TYPE,
            "data_b64": base64.b64encode(content).decode("ascii"),
            "updated_at": int(time.time()),
        },
        upsert=True,
    )
    return logo_asset_url(key)


def read_logo_asset(key: str) -> Optional[tuple[bytes, str]]:
    """A stored logo's ``(bytes, content_type)``, or ``None`` when absent."""
    doc = _get_assets_collection().find_one({"_id": key})
    if not doc or not doc.get("data_b64"):
        return None
    return (
        base64.b64decode(doc["data_b64"]),
        doc.get("content_type") or _FALLBACK_CONTENT_TYPE,
    )


def delete_logo_asset(key: str) -> None:
    """Drop a stored logo. Used when the thing it belonged to is deleted."""
    _get_assets_collection().delete_one({"_id": key})


def content_type_for_extension(ext: str) -> Optional[str]:
    """Reverse of `LOGO_TYPES`, for importing files written before the rework."""
    for content_type, (known_ext, _) in LOGO_TYPES.items():
        if known_ext == ext.lower():
            return content_type
    return None


# ── Migration off the filesystem ──────────────────────────────────────────────

#: Where uploads landed before the bytes moved into MongoDB. Kept as a read
#: source only. Derived from ``__file__`` so the path holds both in Docker
#: (/app/depictio/...) and in a local run.
_LEGACY_STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
_LEGACY_INSTANCE_URL_PREFIX = "/static/branding/"
_LEGACY_DASHBOARD_URL_PREFIX = "/static/dashboard_logos/"


def _import_legacy_file(key: str, path: Path) -> Optional[str]:
    """Import one on-disk logo, returning its new URL (``None`` if unusable)."""
    content_type = content_type_for_extension(path.suffix)
    if content_type is None:
        logger.warning(f"Skipping legacy logo with unsupported extension: {path.name}")
        return None
    return store_logo_asset(key, path.read_bytes(), content_type)


def _migrate_instance_logos() -> int:
    """Import the instance's own logo files. Returns how many moved."""
    overrides = get_brand_theme_overrides()
    migrated = 0
    for variant, field in (("light", "logo_url"), ("dark", "logo_url_dark")):
        current = getattr(overrides, field, None)
        if not current or not current.startswith(_LEGACY_INSTANCE_URL_PREFIX):
            continue
        matches = sorted(_LEGACY_STATIC_DIR.glob(f"branding/logo_{variant}.*"))
        if not matches:
            logger.warning(
                f"Instance {variant} logo points at {current} but the file is gone; "
                "the brand keeps its other settings and the logo needs re-uploading."
            )
            continue
        new_url = _import_legacy_file(instance_logo_key(variant), matches[0])
        if new_url:
            patch_brand_theme_overrides({field: new_url})
            migrated += 1
    return migrated


def _migrate_dashboard_logos() -> int:
    """Import per-dashboard logo files. Returns how many moved."""
    from depictio.api.v1.db import dashboards_collection

    migrated = 0
    for doc in dashboards_collection.find(
        {"brand_theme.logo_url": {"$regex": f"^{_LEGACY_DASHBOARD_URL_PREFIX}"}},
        {"dashboard_id": 1, "brand_theme": 1},
    ):
        dashboard_id = doc["dashboard_id"]
        matches = sorted(_LEGACY_STATIC_DIR.glob(f"dashboard_logos/{dashboard_id}.*"))
        if not matches:
            continue
        new_url = _import_legacy_file(dashboard_logo_key(dashboard_id), matches[0])
        if new_url:
            dashboards_collection.update_one(
                {"dashboard_id": dashboard_id},
                {"$set": {"brand_theme.logo_url": new_url}},
            )
            migrated += 1
    return migrated


def migrate_legacy_logo_files() -> int:
    """Move logos left on the container filesystem into MongoDB.

    Picks up the documents still holding a ``/static/...`` URL from before the
    move described above, and rewrites them to the new endpoints.

    Runs on every boot and is a no-op once the directories are empty, which is
    the steady state after the first migrated start. Never raises, and the two
    halves are independent: a deployment must still come up if a logo cannot be
    moved, and a dashboard that trips over something must not cost the instance
    its own logo.
    """
    migrated = 0
    for step, migrate in (
        ("instance", _migrate_instance_logos),
        ("dashboard", _migrate_dashboard_logos),
    ):
        try:
            migrated += migrate()
        except Exception as exc:
            logger.warning(f"Migration of {step} logos to MongoDB skipped: {exc}")

    if migrated:
        logger.info(f"Migrated {migrated} uploaded logo(s) from the filesystem into MongoDB")
    return migrated


__all__ = [
    "HEX_COLOR_RE",
    "LOGO_CACHE_CONTROL",
    "LOGO_MAX_BYTES",
    "LOGO_TYPES",
    "PALETTE_NAME_RE",
    "branding_assets_collection",
    "content_type_for_extension",
    "dashboard_logo_key",
    "delete_logo_asset",
    "instance_logo_key",
    "logo_asset_url",
    "migrate_legacy_logo_files",
    "read_logo_asset",
    "store_logo_asset",
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
