"""Profile pictures: storage, normalisation and the identity-provider hook.

A user has at most one picture, kept in the ``user_avatars`` collection as
``{_id: <user id>, data_b64, content_type, width, height, source, provider,
provider_url, updated_at}``. ``source`` says where it came from:

- ``"upload"``: the user chose it in Account settings. It always wins.
- ``"provider"``: an identity provider supplied it at login (``provider`` names
  which one, ``provider_url`` remembers the URL it was fetched from).

Why every picture is re-encoded
-------------------------------
Nothing uploaded, or downloaded from a provider, is ever stored or served as
received. `normalize_image` decodes it, applies the EXIF orientation, crops it
to a centred square, resizes it to ``AVATAR_SIZE`` pixels and encodes it again
as WebP (PNG when WebP is unavailable). The re-encode is the security boundary:
a polyglot file, a script smuggled into SVG or metadata, a decompression bomb
or a GPS-tagged photo all stop at the decoder, and what is served is bytes this
module produced.

The bytes are stored base64-encoded, like the ``branding_assets`` logos, so the
document is plain JSON: the backup endpoint serialises with ``default=str``,
which would turn raw BSON ``Binary`` into an unrestorable ``repr``.

Plugging in an identity provider
--------------------------------
`set_provider_avatar` is the one entry point. A provider integration calls it
once the user is resolved, after authentication has succeeded::

    # OIDC / OAuth: the userinfo `picture` claim is a URL.
    await set_provider_avatar(user.id, provider="oidc", url=claims.get("picture"))

    # SAML / LDAP: `jpegPhoto` or `thumbnailPhoto` arrive as bytes.
    await set_provider_avatar(user.id, provider="saml", raw=photo_bytes)

It never raises and returns whether a new picture was stored, so a login can
call it without a try/except and never fails because of a photo. Precedence:

- A picture the user uploaded is never replaced by a provider's.
- A URL equal to the stored ``provider_url`` is not downloaded again.
- When the user removes an uploaded picture the document is deleted, so the
  next provider login may supply one again. Removing a provider picture works
  the same way: it comes back at the next login, which is how the provider
  stays the source of truth until the user uploads their own.

The Google OAuth callback is the first caller (``google_oauth_routes.py``).
"""

from __future__ import annotations

import asyncio
import base64
import io
from typing import Any, Literal, Optional
from urllib.parse import urlsplit

import httpx
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import user_avatars_collection
from depictio.models.timestamps import utc_now_naive

#: Edge of the stored square, in pixels. Large enough for the biggest avatar
#: the UI draws (the Account section's, ~96 px) at 2x density.
AVATAR_SIZE = 256

#: Largest input accepted, uploaded or downloaded.
MAX_INPUT_BYTES = 5 * 1024 * 1024

#: Decoded pixel budget, checked from the header before any pixel is decoded.
#: Pillow's own limit only warns past ~89 MP; a 5 MB file can still declare a
#: huge canvas, so refuse earlier (and without touching Pillow's global limit).
MAX_INPUT_PIXELS = 40_000_000

#: Raster formats accepted for decoding. Pillow knows many more (EPS and PDF
#: among them, which can reach out to external tools); none is wanted here.
ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP", "GIF")

#: Longest edge kept while processing, before the final square crop. Large enough
#: for any crop to AVATAR_SIZE, small enough that the later copies are cheap.
WORKING_EDGE = 1024

#: A provider's picture is fetched at most this long, so a slow host cannot hold
#: a login open.
PROVIDER_FETCH_TIMEOUT_S = 5.0

AvatarSource = Literal["upload", "provider"]


class AvatarError(ValueError):
    """The input is not a picture we accept. ``status`` is the HTTP code to use."""

    def __init__(self, message: str, status: int = 415):
        super().__init__(message)
        self.status = status


class AvatarTooLarge(AvatarError):
    def __init__(self) -> None:
        super().__init__(f"Picture is larger than {MAX_INPUT_BYTES // (1024 * 1024)} MB.", 413)


# ── Normalisation ────────────────────────────────────────────────────────────


def normalize_image(raw: bytes) -> tuple[bytes, str, int, int]:
    """Decode ``raw`` and return ``(bytes, content_type, width, height)``.

    The result is a square ``AVATAR_SIZE`` image with no metadata. Raises
    `AvatarTooLarge` over ``MAX_INPUT_BYTES`` and `AvatarError` for anything
    that does not decode as a picture (an SVG or a PDF included: only the raster
    formats in ``ALLOWED_FORMATS`` are accepted).
    """
    if len(raw) > MAX_INPUT_BYTES:
        raise AvatarTooLarge()
    if not raw:
        raise AvatarError("The file is empty.")

    # Imported here: Pillow ships with the [server] extra, and a bare CLI
    # install that never serves avatars should not need it to import this module.
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(raw), formats=ALLOWED_FORMATS) as probe:
            if probe.width * probe.height > MAX_INPUT_PIXELS:
                raise AvatarError("The image dimensions are too large.", 413)
            # verify() checks the file's structure without decoding the pixels;
            # it leaves the image unusable, hence the second open below.
            probe.verify()
        with Image.open(io.BytesIO(raw), formats=ALLOWED_FORMATS) as image:
            # Decode a JPEG at a reduced scale where the codec can, then shrink
            # before anything else copies the pixels. The EXIF tags stay on this
            # same Image object, so the orientation below still applies.
            if image.format == "JPEG":
                image.draft("RGB", (WORKING_EDGE, WORKING_EDGE))
            image.load()
            image.thumbnail((WORKING_EDGE, WORKING_EDGE))
            # EXIF orientation first: a phone photo is stored rotated and tagged.
            oriented = ImageOps.exif_transpose(image)
            # An animated GIF/WebP opens on its first frame, which is the picture.
            has_alpha = oriented.mode in ("RGBA", "LA", "PA") or "transparency" in oriented.info
            rgb = oriented.convert("RGBA" if has_alpha else "RGB")
            # Centre-crop to a square and resize in one step.
            fitted = ImageOps.fit(rgb, (AVATAR_SIZE, AVATAR_SIZE), method=Image.Resampling.LANCZOS)
    except AvatarError:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        SyntaxError,  # what Pillow's PNG/other verifiers raise on corruption
        OSError,
        ValueError,
        TypeError,
        EOFError,
    ) as exc:
        raise AvatarError("The file is not a valid image.") from exc

    # Saving a fresh Image drops EXIF, ICC and XMP: nothing is passed through.
    out = io.BytesIO()
    try:
        fitted.save(out, format="WEBP", quality=85, method=4)
        content_type = "image/webp"
    except (KeyError, OSError, ValueError):
        out = io.BytesIO()
        fitted.save(out, format="PNG", optimize=True)
        content_type = "image/png"
    return out.getvalue(), content_type, fitted.width, fitted.height


# ── Storage ──────────────────────────────────────────────────────────────────


def _as_object_id(user_id: Any) -> ObjectId:
    return user_id if isinstance(user_id, ObjectId) else ObjectId(str(user_id))


def get_avatar(user_id: Any) -> Optional[dict]:
    """The stored document for ``user_id``, bytes included, or ``None``."""
    return user_avatars_collection.find_one({"_id": _as_object_id(user_id)})


def get_avatar_meta(user_id: Any) -> Optional[dict]:
    """Like `get_avatar` without the bytes: what the current-user payload needs."""
    return user_avatars_collection.find_one({"_id": _as_object_id(user_id)}, {"data_b64": 0})


def avatar_bytes(doc: dict) -> bytes:
    """The decoded image bytes of a stored document."""
    return base64.b64decode(doc["data_b64"])


def avatar_updated_at_iso(doc: Optional[dict]) -> Optional[str]:
    """The picture's timestamp as naive-UTC ISO (no offset), or ``None``.

    The SPA uses it as the cache key for the picture: it changes on every
    replacement and the browser appends ``Z`` itself like for any API stamp.
    """
    stamp = doc.get("updated_at") if doc else None
    return stamp.isoformat() if stamp else None


def _store(
    user_id: Any,
    image: tuple[bytes, str, int, int],
    *,
    source: AvatarSource,
    provider: Optional[str] = None,
    provider_url: Optional[str] = None,
) -> Optional[dict]:
    """Write the user's picture. A provider write never replaces an upload.

    An upload is unconditional. A provider write only matches a document that is
    not an upload; when one exists the upsert's insert collides on ``_id`` and
    ``None`` comes back, which is how a provider picture that was downloaded while
    the user uploaded their own loses the race.
    """
    data, content_type, width, height = image
    doc = {
        "data_b64": base64.b64encode(data).decode("ascii"),
        "content_type": content_type,
        "width": width,
        "height": height,
        "source": source,
        "provider": provider,
        "provider_url": provider_url,
        "updated_at": utc_now_naive(),
    }
    query: dict[str, Any] = {"_id": _as_object_id(user_id)}
    if source == "provider":
        query["source"] = {"$ne": "upload"}
    try:
        user_avatars_collection.replace_one(query, doc, upsert=True)
    except DuplicateKeyError:
        return None
    return doc


def set_uploaded_avatar(user_id: Any, raw: bytes) -> dict:
    """Normalise ``raw`` and store it as the user's own picture.

    Raises `AvatarError` (`AvatarTooLarge` included) when it is not an
    acceptable picture; nothing is stored then.
    """
    doc = _store(user_id, normalize_image(raw), source="upload")
    assert doc is not None  # an upload write is unconditional
    return doc


def delete_avatar(user_id: Any) -> bool:
    """Remove the user's picture. True when there was one.

    Removing an uploaded picture lets the next provider login supply one again.
    """
    result = user_avatars_collection.delete_one({"_id": _as_object_id(user_id)})
    return result.deleted_count > 0


# ── Identity-provider hook ───────────────────────────────────────────────────


async def _download(url: str) -> bytes:
    """Fetch ``url`` over https, refusing more than ``MAX_INPUT_BYTES``.

    Redirects are not followed: a provider's picture URL is a direct link, and
    following one would let a hostile ``picture`` claim bounce the server to an
    internal address.

    There is no private-address check, so ``url`` must come from the identity
    provider (Google's ``picture`` claim), never from user input. Add one before
    wiring a provider whose claims the user controls.
    """
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise AvatarError("Provider picture URLs must be https.")

    chunks: list[bytes] = []
    total = 0
    async with httpx.AsyncClient(
        timeout=PROVIDER_FETCH_TIMEOUT_S, follow_redirects=False
    ) as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise AvatarError(f"Provider picture returned HTTP {response.status_code}.")
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_INPUT_BYTES:
                    raise AvatarTooLarge()
                chunks.append(chunk)
    return b"".join(chunks)


async def set_provider_avatar(
    user_id: Any,
    *,
    provider: str,
    url: Optional[str] = None,
    raw: Optional[bytes] = None,
) -> bool:
    """Store a picture an identity provider supplied. True when one was stored.

    Pass ``url`` (OIDC ``picture``) or ``raw`` bytes (SAML ``jpegPhoto``). See
    the module docstring for the precedence rules. ``url`` must come from the
    identity provider, never from user input (see `_download`). Never raises: a picture must
    not be able to break a login, so every failure is logged and answered with
    False.
    """
    try:
        if not url and not raw:
            return False

        existing = get_avatar_meta(user_id)
        if existing and existing.get("source") == "upload":
            return False
        if (
            url
            and existing
            and existing.get("provider") == provider
            and existing.get("provider_url") == url
        ):
            return False

        payload = raw if raw else await _download(url or "")
        # Decode and write off the event loop: both are blocking, and the decode
        # is CPU-bound.
        stored = await asyncio.to_thread(
            lambda: _store(
                user_id,
                normalize_image(payload),
                source="provider",
                provider=provider,
                provider_url=url,
            )
        )
        if stored is None:
            logger.debug(f"A picture was uploaded for {user_id} meanwhile; keeping it")
            return False
        return True
    except Exception as exc:  # noqa: BLE001 - a picture must never fail a login
        logger.warning(f"Could not store the {provider} profile picture for {user_id}: {exc}")
        return False
