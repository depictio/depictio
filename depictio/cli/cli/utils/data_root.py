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

The listing primitives (:func:`s3_read_client`, :func:`list_s3_objects`) live
here rather than in ``scan.py`` so the dependency runs one way only:
``scan.py -> data_root.py``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from depictio.api.v1.remote_fetch import (
    is_public_s3_location,
    public_s3_region,
    public_s3_storage_options,
)
from depictio.cli.cli.utils.scan_utils import regex_match
from depictio.cli.cli_logging import logger

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


def s3_read_client(url: str, CLI_config):
    """boto3 client for *reading* user data buckets (scan mode ``s3_prefix``).

    A location on the administrator's public bucket allowlist gets an unsigned
    client: signing with credentials that have no relationship to someone else's
    open bucket only earns a rejection. The allowlist is configuration, so this
    is decided before the client makes any call.

    Otherwise credential precedence mirrors the read/write split in CLIConfig:
    the per-project ``remote_storage_options`` win, then the instance's own
    ``s3_storage``. Anything still missing is left to boto3's default chain
    (env vars, ~/.aws, IAM role) so real AWS deployments work without ever
    putting keys in a config file.
    """
    import boto3

    if url and is_public_s3_location(url):
        from botocore import UNSIGNED
        from botocore.config import Config

        return boto3.client(
            "s3",
            config=Config(signature_version=UNSIGNED),
            region_name=public_s3_region(urlparse(url).netloc),
        )

    remote = getattr(CLI_config, "remote_storage_options", None) or {}
    # polars storage_options spells the endpoint either way depending on version
    endpoint = remote.get("aws_endpoint_url") or remote.get("endpoint_url")
    key = remote.get("aws_access_key_id")
    secret = remote.get("aws_secret_access_key")
    # ``region`` is what storage_options_for_project (per-project storage
    # config) emits; the other two are the polars/boto3 spellings.
    region = remote.get("aws_region") or remote.get("region_name") or remote.get("region")

    s3_storage = getattr(CLI_config, "s3_storage", None)
    if not key and s3_storage:
        key = s3_storage.aws_access_key_id
        secret = s3_storage.aws_secret_access_key
        endpoint = endpoint or s3_storage.url

    # Passing None lets botocore fall through to its own resolution chain.
    return boto3.client(
        "s3",
        aws_access_key_id=key or None,
        aws_secret_access_key=secret or None,
        endpoint_url=endpoint or None,
        region_name=region or None,
    )


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
    """
    bucket, key_prefix = split_s3_prefix(prefix)

    client = s3_read_client(prefix, CLI_config)
    paginator = client.get_paginator("list_objects_v2")

    objects: list[RemoteObject] = []
    examined = 0
    truncated = False
    for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
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
                    url=f"s3://{bucket}/{key}",
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


# ── glob translation ─────────────────────────────────────────────────────────


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a ``Path.glob`` pattern into a regex over a relative path.

    ``**/`` spans directories, ``*`` and ``?`` stop at ``/``, character classes
    pass through and everything else is escaped. This is what lets an in-memory
    S3 listing answer ``glob`` the way ``Path.glob`` answers it on disk.
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

    def url(self, rel: str) -> str:
        """Absolute location of ``rel``: a filesystem path or an ``s3://`` URL."""
        ...

    def relative_of(self, location: str) -> str | None:
        """``location`` as a root-relative path, or None when it is not under the root."""
        ...

    def read_bytes(self, rel: str) -> bytes:
        """Contents of ``rel``; ``FileNotFoundError`` when it is absent."""
        ...

    def storage_options(self) -> dict | None:
        """Polars storage options for reading this root, or None when local."""
        ...


# ── local ────────────────────────────────────────────────────────────────────


class LocalDataRoot:
    """A data root that is a directory on disk. A thin ``pathlib`` wrapper."""

    is_remote = False

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
        return self._child(rel).exists()

    def glob(self, pattern: str) -> list[str]:
        return sorted(path.relative_to(self._root).as_posix() for path in self._root.glob(pattern))

    def match(self, regex: str, within: str = "") -> list[str]:
        base = self._child(within)
        matched: list[str] = []
        for path in base.rglob("*"):
            if not path.is_file():
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
        return sorted(
            path.name
            for path in self._root.iterdir()
            if path.is_dir() and re.match(runs_regex, path.name)
        )

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
        return path.read_bytes()

    def storage_options(self) -> dict | None:
        return None


# ── remote ───────────────────────────────────────────────────────────────────


def _has_configured_credentials(CLI_config) -> bool:
    """Whether reads through ``CLI_config`` are aimed somewhere it controls.

    Explicit per-project or instance configuration counts, and so does an
    ambient AWS credential in the environment (env keys, a named profile, ECS
    or IRSA), since boto3's own chain will pick those up. A plain EC2 instance
    profile cannot be detected without a metadata call and so does not count:
    such a deployment allowlists the bucket or configures credentials.
    """
    remote = getattr(CLI_config, "remote_storage_options", None) or {}
    if (
        remote.get("aws_access_key_id")
        or remote.get("aws_endpoint_url")
        or remote.get("endpoint_url")
    ):
        return True
    if getattr(CLI_config, "s3_storage", None):
        return True
    return any(
        os.environ.get(name)
        for name in (
            "AWS_ACCESS_KEY_ID",
            "AWS_PROFILE",
            "AWS_ROLE_ARN",
            "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        )
    )


class S3DataRoot:
    """A data root that is an ``s3://`` prefix, answered from one listing.

    Every question below is served from the objects listed at construction, so
    a template resolution that asks fifty of them costs one paginated listing
    rather than fifty round trips. The trade is that the view is a snapshot:
    an object written after construction is invisible until a new root is built.
    """

    is_remote = True

    def __init__(self, location: str, CLI_config=None, max_keys: int = DEFAULT_MAX_KEYS):
        self.location = location
        self._cli_config = CLI_config

        bucket, key_prefix = split_s3_prefix(location)
        self._bucket = bucket
        # Normalised to a directory-shaped prefix so the root behaves like a
        # directory: without the trailing slash S3 would also hand us the keys
        # of a *sibling* prefix sharing the same leading characters.
        self._prefix = f"{key_prefix.strip('/')}/" if key_prefix.strip("/") else ""
        self.name = self._prefix.strip("/").rsplit("/", 1)[-1] if self._prefix else bucket

        if not is_public_s3_location(location) and not _has_configured_credentials(CLI_config):
            # Decided from configuration alone, before any network call: an
            # anonymous read of a user-supplied bucket would turn the bucket
            # name into an existence-and-region oracle through the error it
            # returns.
            raise ValueError(
                f"Refusing to read '{location}': it is not on the public bucket allowlist "
                "(DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS) and no S3 credentials are configured "
                "for it. Add the bucket to DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS, or configure "
                "credentials for the project or the instance."
            )

        self.objects, self.truncated = list_s3_objects(
            f"s3://{bucket}/{self._prefix}", CLI_config, max_keys=max_keys
        )
        if self.truncated:
            logger.warning(
                f"Listing of '{location}' stopped at {max_keys} keys; the data root's view "
                "of it is partial."
            )

        self._files = {obj.relative: obj for obj in self.objects}
        # S3 has no directories. Synthesising them from the key prefixes is what
        # makes ``exists``, ``glob`` and ``runs`` answer the way they do on
        # disk; without it "input/*" would silently miss a sub-prefix that
        # ``Path.glob`` would have returned.
        self._dirs: set[str] = set()
        for relative in self._files:
            parts = relative.split("/")[:-1]
            for depth in range(1, len(parts) + 1):
                self._dirs.add("/".join(parts[:depth]))

        self._client_cache = None

    def __repr__(self) -> str:
        return f"S3DataRoot({self.location!r}, {len(self.objects)} objects)"

    @property
    def _client(self):
        """The listing client, built on first use and reused for every read."""
        if self._client_cache is None:
            self._client_cache = s3_read_client(self.location, self._cli_config)
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
        response = self._client.get_object(Bucket=self._bucket, Key=f"{self._prefix}{rel}")
        return response["Body"].read()

    def storage_options(self) -> dict | None:
        """Options for ``pl.scan_csv(url, storage_options=...)`` against this root.

        Same precedence the ``url`` scan mode uses: an allowlisted public prefix
        is read unsigned, otherwise the per-project credentials win over the
        instance's own. Decided once here rather than re-derived per read.
        """
        public = public_s3_storage_options(self.location)
        if public:
            return public

        remote = getattr(self._cli_config, "remote_storage_options", None)
        if remote:
            return dict(remote)

        s3_storage = getattr(self._cli_config, "s3_storage", None)
        if s3_storage:
            from depictio.models.s3_utils import turn_S3_config_into_polars_storage_options

            return turn_S3_config_into_polars_storage_options(s3_storage).model_dump()
        return None


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
