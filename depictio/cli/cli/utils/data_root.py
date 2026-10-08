"""One object per data root, whether it is a directory or an ``s3://`` prefix.

Template resolution, scanning and the recipe layer all ask the same handful of
questions of a data root: does this relative path exist, which files match this
glob, which files match this scan regex, what are the run directories, what is
the absolute location of this entry, give me its bytes. Locally those are
``pathlib`` calls. Remotely each one would be its own S3 round trip, so
:class:`S3DataRoot` answers all of them from a single paginated listing taken
once at construction and held in memory.

The two implementations are kept deliberately interchangeable: a caller written
against :class:`DataRoot` must not have to know which one it holds. Where that
could not be achieved the difference is called out in the method's docstring.

The S3 primitives (:func:`list_s3_objects` and the read target it lists
with) live here rather than in ``scan.py`` so the dependency runs one way only:
``scan.py -> data_root.py``. How an ``s3://`` location is read is not decided
here: :func:`depictio.api.v1.remote_fetch.s3_read_target` decides it, the same
way for the preview, the API, the worker and the CLI.
"""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Protocol

from depictio.api.v1 import remote_fetch
from depictio.api.v1.configs.settings_models import local_data_policy
from depictio.cli.cli.utils.scan_utils import regex_match
from depictio.cli.cli_logging import logger
from depictio.models.local_access import LocalPathRefused
from depictio.models.s3_access import (
    S3AccessFailed,
    S3Target,
    client_error_code,
    ensure_region,
    iter_object_pages,
)

# Ceiling on the number of keys a single :class:`S3DataRoot` listing pages
# through. Matches ``ScanS3Prefix.max_files``' own ``le=100_000`` ceiling, so a
# root can never cost more than one full scan's worth of listing.
DEFAULT_MAX_KEYS = 100_000


@dataclass(frozen=True)
class RemoteObject:
    """One object out of an S3 listing, in the shape every caller needs it."""

    key: str
    """Full object key, prefix included."""

    relative: str
    """``key`` with the root's prefix stripped and no leading ``/``."""

    url: str
    """``s3://bucket/key``."""

    size: int
    """Object size in bytes, ``-1`` when the listing did not report one."""

    etag: str
    """ETag with the quotes S3 wraps it in stripped off."""

    last_modified: datetime | None


# ── S3 listing primitives ────────────────────────────────────────────────────


def _s3_read_target(url: str, CLI_config) -> S3Target:
    """How ``url`` is read for ``CLI_config``, moved to its bucket's own region.

    The decision is :func:`depictio.api.v1.remote_fetch.s3_read_target`'s, made
    from configuration alone: a location the configuration does not allow
    raises ``S3AccessRefused`` before any request names its bucket, so a bucket
    typed by a user never becomes an existence or region oracle. Only an
    accepted bucket is then asked for its region (object-store does not follow
    S3's cross-region redirect).
    """
    return ensure_region(remote_fetch.s3_read_target(url, CLI_config))


def s3_read_client(url: str, CLI_config):
    """boto3 client for reading ``url``: the target :func:`_s3_read_target` resolves."""
    return remote_fetch.s3_read_client(url, CLI_config)


def split_s3_prefix(prefix: str) -> tuple[str, str]:
    """``(bucket, key_prefix)`` out of an ``s3://`` prefix.

    Raises ``ValueError`` on anything that is not an ``s3://`` URL, or on one
    with no bucket, so a malformed configuration surfaces as a scan failure
    rather than an empty listing.
    """
    if not prefix.lower().startswith("s3://"):
        raise ValueError(f"s3_prefix scan needs an s3:// prefix, got '{prefix}'")

    without_scheme = prefix[len("s3://") :]
    bucket, _, key_prefix = without_scheme.partition("/")
    if not bucket:
        raise ValueError(f"s3_prefix '{prefix}' has no bucket")
    return bucket, key_prefix


def _list_objects(
    target: S3Target, key_prefix: str, max_keys: int
) -> tuple[list[RemoteObject], bool]:
    """Every object under ``key_prefix`` in ``target``'s bucket, up to ``max_keys`` keys.

    A prefix that holds nothing lists as empty, even on gateways that answer it
    with a 404; any other failure raises ``S3AccessFailed``.
    """
    objects: list[RemoteObject] = []
    examined = 0
    truncated = False
    for page in iter_object_pages(target, key_prefix):
        for obj in page.get("Contents", []):
            examined += 1
            key = obj["Key"]
            if key.endswith("/"):
                continue
            relative = key[len(key_prefix) :].lstrip("/") if key_prefix else key
            objects.append(
                RemoteObject(
                    key=key,
                    relative=relative,
                    url=f"s3://{target.bucket}/{key}",
                    size=obj.get("Size", -1),
                    etag=(obj.get("ETag") or "").strip('"'),
                    last_modified=obj.get("LastModified"),
                )
            )
        # ``IsTruncated`` is set on every list_objects_v2 page; a listing that
        # ends exactly at the budget is complete and must not report truncation.
        if examined >= max_keys and page.get("IsTruncated", True):
            truncated = True
            break

    return objects, truncated


def list_s3_objects(
    prefix: str, CLI_config, max_keys: int = DEFAULT_MAX_KEYS
) -> tuple[list[RemoteObject], bool]:
    """Full recursive listing under an ``s3://`` prefix.

    Returns ``(objects, truncated)``. ``truncated`` is True when the walk
    stopped because ``max_keys`` keys had been examined and the listing was not
    finished: a page already fetched is always scanned in full, so the budget is
    only checked between pages, and a listing that ends exactly on the budget is
    complete rather than truncated.

    Console-created "folders" - zero-byte keys ending in ``/`` - are never data
    and are skipped, but they do count against the budget since S3 charges for
    listing them either way.

    Raises ``ValueError`` on a malformed prefix, ``S3AccessRefused`` when the
    configuration does not allow reading it and ``S3AccessFailed`` when the
    listing itself fails. An absent prefix is an empty listing.
    """
    _bucket, key_prefix = split_s3_prefix(prefix)
    return _list_objects(_s3_read_target(prefix, CLI_config), key_prefix, max_keys)


# ── glob translation ─────────────────────────────────────────────────────────


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a ``Path.glob`` pattern into a regex over a relative path.

    ``**/`` spans directories, ``*`` and ``?`` stop at ``/``, character classes
    pass through and everything else is escaped. This is what lets an in-memory
    S3 listing answer ``glob`` the way ``Path.glob`` answers it on disk.

    Deliberately *not* the fnmatch dialect ``scan.list_s3_prefix`` matches its
    own ``pattern`` with, where ``*`` spans ``/`` as well. Both are right for
    their caller: a recipe's ``glob_pattern`` is written against a directory
    tree and must mean on S3 what it means on disk, while an ``s3_prefix``
    scan's pattern is the remote twin of a *recursive* walk, so ``*.csv`` there
    is meant to reach into sub-prefixes. Merging them would break one of the
    two, so they stay separate.
    """
    out: list[str] = []
    index = 0
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if char == "*":
            if pattern.startswith("**/", index):
                # Zero or more directories, so "**/*.csv" also matches the root.
                out.append("(?:.*/)?")
                index += 3
            elif pattern.startswith("**", index):
                out.append(".*")
                index += 2
            else:
                out.append("[^/]*")
                index += 1
            continue
        if char == "?":
            out.append("[^/]")
            index += 1
            continue
        if char == "[":
            close = index + 1
            if close < length and pattern[close] in "!^":
                close += 1
            if close < length and pattern[close] == "]":
                close += 1
            while close < length and pattern[close] != "]":
                close += 1
            if close >= length:
                # Unclosed class: the "[" was meant literally.
                out.append(re.escape("["))
                index += 1
                continue
            body = pattern[index + 1 : close]
            if body.startswith("!"):
                body = "^" + body[1:]
            out.append(f"[{body}]")
            index = close + 1
            continue
        out.append(re.escape(char))
        index += 1
    return re.compile("".join(out))


def _normalize_relative(rel: str) -> str:
    """A root-relative path in the one spelling the implementations agree on."""
    return rel.strip("/")


# ── the protocol ─────────────────────────────────────────────────────────────


class DataRoot(Protocol):
    """Everything the CLI needs to ask of a data root, local or remote."""

    location: str
    """The root exactly as the caller gave it."""

    name: str
    """Last path segment; used as the project-name suffix."""

    is_remote: bool

    truncated: bool
    """Whether the root's view of the location is partial (a capped listing)."""

    def exists(self, rel: str) -> bool:
        """Whether ``rel`` names a file or a directory under the root."""
        ...

    def glob(self, pattern: str) -> list[str]:
        """``Path.glob`` semantics, as sorted root-relative POSIX paths."""
        ...

    def match(self, regex: str, within: str = "") -> list[str]:
        """Scan-matcher: files under ``within`` matching ``regex``, root-relative."""
        ...

    def runs(self, runs_regex: str) -> list[str]:
        """Sorted first-level directory names matching ``runs_regex``."""
        ...

    def scoped(self, sub: str) -> DataRoot:
        """The same root narrowed to the sub-directory ``sub``.

        A ``sequencing-runs`` layout runs the same recipe once per run, so this
        must never cost a second listing: an implementation answers from what
        it already holds.
        """
        ...

    def url(self, rel: str) -> str:
        """Absolute location of ``rel``: a filesystem path or an ``s3://`` URL."""
        ...

    def relative_of(self, location: str) -> str | None:
        """``location`` as a root-relative path, or None when it is not under the root."""
        ...

    def read_bytes(self, rel: str) -> bytes:
        """Contents of ``rel``; ``FileNotFoundError`` when it is absent."""
        ...

    def size(self, rel: str) -> int | None:
        """Size of the file ``rel`` in bytes, or None when it is unknown or absent."""
        ...

    def storage_options(self) -> dict | None:
        """Polars storage options for reading this root, or None when local."""
        ...


# ── local ────────────────────────────────────────────────────────────────────


def _readable(policy, path: Path) -> bool:
    """Whether ``path`` may be read under ``policy``; everything may without one."""
    return policy is None or policy.allows_read(str(path))


class LocalDataRoot:
    """A data root that is a directory on disk. A thin ``pathlib`` wrapper.

    On a server reading its own disk (``depictio local``, see
    ``settings_models.local_data_policy``) every answer is confined: an entry
    whose real path leaves the allowed folders (a symlink, a ``..`` in a
    recipe's glob, a hidden or Depictio-owned folder) does not exist, is not
    listed and is not read. Recipes reach files only through these methods,
    so this is what keeps them in. Without that policy (the CLI, a shared
    server) nothing changes.
    """

    is_remote = False
    # A directory is read as it is at the moment of the question, so a local
    # root never has a partial view of itself.
    truncated = False

    def __init__(self, location: str):
        self.location = location
        self._root = Path(location)
        self.name = self._root.name

    def __repr__(self) -> str:
        return f"LocalDataRoot({self.location!r})"

    def _child(self, rel: str) -> Path:
        rel = _normalize_relative(rel)
        return self._root / rel if rel else self._root

    def exists(self, rel: str) -> bool:
        path = self._child(rel)
        return path.exists() and _readable(local_data_policy(), path)

    def glob(self, pattern: str) -> list[str]:
        policy = local_data_policy()
        return sorted(
            path.relative_to(self._root).as_posix()
            for path in self._root.glob(pattern)
            if _readable(policy, path)
        )

    def match(self, regex: str, within: str = "") -> list[str]:
        policy = local_data_policy()
        base = self._child(within)
        matched: list[str] = []
        for path in base.rglob("*"):
            if not path.is_file() or not _readable(policy, path):
                continue
            # Basename first, then - only when the pattern spells a path - the
            # path relative to ``within``. Same two-shot rule as the local
            # recursive scan, so a DC regex means the same thing either way.
            hit, _ = regex_match(path.name, regex)
            if not hit and "/" in regex:
                hit, _ = regex_match(path.relative_to(base).as_posix(), regex)
            if hit:
                matched.append(path.relative_to(self._root).as_posix())
        return sorted(matched)

    def runs(self, runs_regex: str) -> list[str]:
        if not self._root.is_dir():
            return []
        policy = local_data_policy()
        return sorted(
            path.name
            for path in self._root.iterdir()
            if path.is_dir() and re.match(runs_regex, path.name) and _readable(policy, path)
        )

    def scoped(self, sub: str) -> LocalDataRoot:
        """A sub-directory is just another directory, so it is another root."""
        return LocalDataRoot(self.url(sub)) if _normalize_relative(sub) else self

    def url(self, rel: str) -> str:
        return os.path.abspath(str(self._child(rel)))

    def relative_of(self, location: str) -> str | None:
        """Accepts an absolute filesystem path or a path already relative to the root.

        Resolved on both sides, so a root reached through a symlink (per-run
        isolation trees do that) still recognises its own files.
        """
        if "://" in location:
            return None
        candidate = Path(location)
        if not candidate.is_absolute():
            candidate = self._child(location)
        try:
            relative = candidate.resolve().relative_to(self._root.resolve())
        except ValueError:
            return None
        return "" if str(relative) == "." else relative.as_posix()

    def read_bytes(self, rel: str) -> bytes:
        path = self._child(rel)
        if not path.is_file():
            raise FileNotFoundError(f"No such file under the data root: {path}")
        if not _readable(local_data_policy(), path):
            raise LocalPathRefused(
                f"'{path}' is outside the folders this server may read.", "local_path_outside"
            )
        return path.read_bytes()

    def size(self, rel: str) -> int | None:
        path = self._child(rel)
        return path.stat().st_size if path.is_file() else None

    def storage_options(self) -> dict | None:
        return None


# ── remote ───────────────────────────────────────────────────────────────────


class S3DataRoot:
    """A data root that is an ``s3://`` prefix, answered from one listing.

    Every question below is served from the objects listed at construction, so
    a template resolution that asks fifty of them costs one paginated listing
    rather than fifty round trips. The trade is that the view is a snapshot:
    an object written after construction is invisible until a new root is built.

    How the prefix is read is decided once too: the root keeps the
    :class:`~depictio.models.s3_access.S3Target` it resolved, and lists, reads
    and hands polars its options through that target alone.
    """

    is_remote = True

    def __init__(self, location: str, CLI_config=None, max_keys: int = DEFAULT_MAX_KEYS):
        self.location = location

        bucket, key_prefix = split_s3_prefix(location)
        self._bucket = bucket
        # Normalised to a directory-shaped prefix so the root behaves like a
        # directory: without the trailing slash S3 would also hand us the keys
        # of a *sibling* prefix sharing the same leading characters.
        self._prefix = f"{key_prefix.strip('/')}/" if key_prefix.strip("/") else ""
        self.name = self._prefix.strip("/").rsplit("/", 1)[-1] if self._prefix else bucket

        # Refused here (``S3AccessRefused``) when the configuration does not
        # allow the read, before any request goes out.
        self._target = _s3_read_target(f"s3://{bucket}/{self._prefix}", CLI_config)
        objects, truncated = _list_objects(self._target, self._prefix, max_keys)
        if truncated:
            logger.warning(
                f"Listing of '{location}' stopped at {max_keys} keys; the data root's view "
                "of it is partial."
            )
        self._index(objects, truncated)

        self._client_cache = None

    def _index(self, objects: list[RemoteObject], truncated: bool) -> None:
        """Adopt a listing as the set of objects every question is answered from."""
        self.objects = objects
        self.truncated = truncated
        self._files = {obj.relative: obj for obj in objects}
        # S3 has no directories. Synthesising them from the key prefixes is what
        # makes ``exists``, ``glob`` and ``runs`` answer the way they do on
        # disk; without it "input/*" would silently miss a sub-prefix that
        # ``Path.glob`` would have returned.
        self._dirs: set[str] = set()
        for relative in self._files:
            parts = relative.split("/")[:-1]
            for depth in range(1, len(parts) + 1):
                self._dirs.add("/".join(parts[:depth]))

    def __repr__(self) -> str:
        return f"S3DataRoot({self.location!r}, {len(self.objects)} objects)"

    @property
    def _client(self):
        """The read client of the root's target, built on first use and reused."""
        if self._client_cache is None:
            self._client_cache = self._target.client()
        return self._client_cache

    def exists(self, rel: str) -> bool:
        rel = _normalize_relative(rel)
        if not rel:
            return True
        return rel in self._files or rel in self._dirs

    def glob(self, pattern: str) -> list[str]:
        compiled = _glob_to_regex(pattern)
        return sorted(
            candidate for candidate in (*self._files, *self._dirs) if compiled.fullmatch(candidate)
        )

    def match(self, regex: str, within: str = "") -> list[str]:
        within = _normalize_relative(within)
        prefix = f"{within}/" if within else ""
        matched: list[str] = []
        for relative in self._files:
            if prefix and not relative.startswith(prefix):
                continue
            inner = relative[len(prefix) :]
            # Same two-shot rule as the local matcher: basename, then the path
            # relative to ``within`` when the pattern spells a path.
            hit, _ = regex_match(inner.rsplit("/", 1)[-1], regex)
            if not hit and "/" in regex:
                hit, _ = regex_match(inner, regex)
            if hit:
                matched.append(relative)
        return sorted(matched)

    def runs(self, runs_regex: str) -> list[str]:
        return sorted(
            segment
            for segment in self._dirs
            if "/" not in segment and re.match(runs_regex, segment)
        )

    def scoped(self, sub: str) -> S3DataRoot:
        """A view of ``sub`` over the listing this root already holds.

        The objects are here already, so narrowing is a filter, never a second
        ``list_objects_v2`` walk: a 40-run prefix costs one listing, not 41.

        A shallow copy, so the view carries the parent's bucket, read target,
        truncation flag and whatever read client the parent had already built.
        It is a full :class:`S3DataRoot`, ``runs()`` included, because it is one:
        a prefix under a prefix is still a prefix.
        """
        sub = _normalize_relative(sub)
        if not sub:
            return self
        scope = f"{sub}/"
        view = copy.copy(self)
        view.location = self.url(sub)
        view.name = sub.rsplit("/", 1)[-1]
        view._prefix = f"{self._prefix}{scope}"
        view._index(
            [
                replace(obj, relative=obj.relative[len(scope) :])
                for obj in self.objects
                if obj.relative.startswith(scope)
            ],
            self.truncated,
        )
        return view

    def url(self, rel: str) -> str:
        rel = _normalize_relative(rel)
        key = f"{self._prefix}{rel}" if rel else self._prefix.rstrip("/")
        return f"s3://{self._bucket}/{key}" if key else f"s3://{self._bucket}"

    def relative_of(self, location: str) -> str | None:
        """Accepts a full ``s3://bucket/key`` URL or a path already relative to the root."""
        if location.lower().startswith("s3://"):
            without_scheme = location[len("s3://") :]
            bucket, _, key = without_scheme.partition("/")
            if bucket != self._bucket:
                return None
            if self._prefix:
                if key.strip("/") == self._prefix.strip("/"):
                    return ""
                if not key.startswith(self._prefix):
                    return None
                key = key[len(self._prefix) :]
            return _normalize_relative(key)
        if "://" in location or location.startswith("/"):
            return None
        return _normalize_relative(location)

    def read_bytes(self, rel: str) -> bytes:
        rel = _normalize_relative(rel)
        url = self.url(rel)
        if rel not in self._files and not self.truncated:
            # A complete listing is authoritative, so an absent key can be
            # answered without a round trip. A truncated one is not, and falls
            # through to S3 rather than claiming the object does not exist.
            raise FileNotFoundError(f"No such object under the data root: {url}")
        key = f"{self._prefix}{rel}"
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except Exception as exc:
            from botocore.exceptions import ClientError

            if isinstance(exc, ClientError):
                code, status = client_error_code(exc)
                if code == "NoSuchKey" or (status == 404 and code != "NoSuchBucket"):
                    raise FileNotFoundError(f"No such object under the data root: {url}") from exc
            # Coded and sanitized: the API answers with it as it is.
            raise S3AccessFailed.from_exception(exc, self._target.with_key(key)) from exc

    def size(self, rel: str) -> int | None:
        # From the listing: no request per file, and -1 means it reported none.
        obj = self._files.get(_normalize_relative(rel))
        return obj.size if obj is not None and obj.size >= 0 else None

    def storage_options(self) -> dict | None:
        """Options for ``pl.scan_csv(url, storage_options=...)`` against this root.

        The polars spelling of the target the root was listed with, so every
        read of the root signs (or reads unsigned) exactly as its listing did.
        """
        return self._target.polars_options()


# ── dispatch ─────────────────────────────────────────────────────────────────


def data_root_for(location: str, CLI_config=None) -> DataRoot:
    """The :class:`DataRoot` for ``location``, local path or ``s3://`` prefix."""
    if "://" in location:
        scheme = location.split("://", 1)[0].lower()
        if scheme != "s3":
            raise ValueError(
                f"Unsupported data root '{location}': '{scheme}://' cannot be listed. "
                "Supported data roots are a local directory path and an s3:// prefix."
            )
        return S3DataRoot(location, CLI_config)
    return LocalDataRoot(location)


def as_data_root(value: str | Path | DataRoot | None, CLI_config=None) -> DataRoot | None:
    """A :class:`DataRoot` for a user-supplied location, or an existing root.

    ``None`` stays ``None`` (manifest-driven templates have no data root at
    all). A local path is made absolute first, so the root's own ``location``
    is what ``{DATA_ROOT}`` substitutes to; a URL is passed through verbatim,
    since ``Path("s3://b/k").absolute()`` would silently produce
    ``<cwd>/s3:/b/k`` and corrupt every path derived from it.

    Accepting an already-built root is what lets a caller that needs the root
    itself (the data-root preview) hand the same one to ``resolve_template``
    instead of paying for a second S3 listing.
    """
    if value is None:
        return None
    if not isinstance(value, (str, Path)):
        return value
    location = str(value)
    if "://" not in location:
        location = str(Path(location).absolute())
    return data_root_for(location, CLI_config)
