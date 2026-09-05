#!/usr/bin/env python3
"""Resolve, inspect and fetch nf-core AWS megatest runs.

Maintainer tool (not shipped with ``depictio-cli``). Every nf-core release runs a
full-scale "megatest" on AWS and publishes its results to the public bucket
``s3://nf-core-awsmegatests/<pipeline>/results-<sha>/`` where ``<sha>`` is the
release's ``tag_sha`` in https://nf-co.re/pipelines.json. Depictio validates
its nf-core templates against those runs, so this module knows how to:

* map a pipeline + version (``latest``, ``2.18.0``, ``v2.18.0``) to its results
  prefix and verify the run is real (many release prefixes are empty or failed
  runs holding only ``pipeline_info/`` plus zero-byte directory markers),
* list what a run contains (anonymous ListObjectsV2, paginated, retried),
* fetch the tables-only subset a template needs, driven by the per-version
  manifest ``depictio/projects/nf-core/<pipeline>/<version>/megatest.yaml``,
  mirroring the megatest key layout below the run root into a local
  ``DATA_ROOT`` directory.

Only the standard library is required. PyYAML is used to read manifests when it
is installed; otherwise a small parser covering the manifest subset takes over.

Usage::

    python scripts/nfcore_megatest.py resolve --pipeline ampliseq --version 2.18.0
    python scripts/nfcore_megatest.py ls --pipeline rnaseq --version latest --top-dirs
    python scripts/nfcore_megatest.py fetch --pipeline ampliseq --version 2.18.0 --dry-run
    python scripts/nfcore_megatest.py fetch --pipeline ampliseq --version 2.18.0 --dest ~/Data/x

Exit codes: 0 ok, 1 error (manifest, I/O), 2 usage, 3 the megatest run could
not be resolved (the fallback table of real runs is printed).
"""

from __future__ import annotations

import argparse
import fnmatch
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, NamedTuple
from xml.etree import ElementTree as ET

_REPO_ROOT = Path(__file__).resolve().parents[1]
NFCORE_PROJECTS_DIR = _REPO_ROOT / "depictio" / "projects" / "nf-core"
MANIFEST_NAME = "megatest.yaml"

# Public bucket holding the AWS "megatest" full-scale test results per release.
MEGATEST_BUCKET = "nf-core-awsmegatests"
MEGATEST_REGION = os.environ.get("NFCORE_MEGATEST_REGION", "eu-west-1")
_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

PIPELINES_JSON_URL = "https://nf-co.re/pipelines.json"
PIPELINES_JSON_ENV = "NFCORE_PIPELINES_JSON"
PIPELINES_JSON_MAX_AGE_S = 6 * 3600

DEFAULT_DEST_ROOT = Path("~/Data/depictio-nfcore")
DEFAULT_MAX_FILE_MB = 500.0
DEFAULT_STATS_LIMIT = 2000
DEFAULT_MIN_DATA_OBJECTS = 5
# A real run publishes many small tables/reports; a failed or truncated sync
# leaves a handful of multi-GB intermediates (BAM, FASTQ, VCF). Objects at or
# below this size count as "small" for the empty-run heuristic.
SMALL_OBJECT_BYTES = 50_000_000

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

# Timestamped nf-core provenance files get a stable local name so templates can
# read ``pipeline_info/params.json`` regardless of when the run happened.
DEFAULT_RENAMES: dict[str, str] = {
    "pipeline_info/params_*.json": "pipeline_info/params.json",
    "pipeline_info/*software*versions*.yml": "pipeline_info/software_versions.yml",
}

_RESULTS_DIR_RE = re.compile(r"^results-([0-9a-f]{40})$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class MegatestError(RuntimeError):
    """A megatest run could not be resolved.

    ``reason`` is the one-line diagnosis; ``fallback`` (may be empty) is the
    table of real runs the caller can pick from instead. ``str(exc)`` carries
    both so a bare ``print(exc)`` is already actionable.
    """

    def __init__(self, reason: str, fallback: str = "") -> None:
        self.reason = reason
        self.fallback = fallback
        super().__init__(reason + (f"\n\n{fallback}" if fallback else ""))


def _log(message: str) -> None:
    print(message, file=sys.stderr)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _urlopen(req: urllib.request.Request, timeout: float):
    """Indirection so tests can stub the network without touching urllib."""
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310


def _retry_after_seconds(headers: Any) -> float | None:
    value = headers.get("Retry-After") if headers is not None else None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # HTTP-date form: fall back to exponential backoff


def http_get(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 60,
    retries: int = 6,
    backoff: float = 1.0,
    max_backoff: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    """GET ``url`` with retries and return the raw body.

    Retries 429 and 5xx responses (honouring ``Retry-After``), connection
    errors, timeouts and truncated bodies with exponential backoff. The
    megatest bucket answers 503 SlowDown intermittently, so every request in
    this module goes through here. Other HTTP errors (403, 404) raise at once.
    """
    request_headers = {"User-Agent": "depictio-nfcore-megatest"}
    request_headers.update(headers or {})
    attempt = 0
    while True:
        req = urllib.request.Request(url, headers=request_headers)
        try:
            with _urlopen(req, timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_STATUSES or attempt >= retries:
                raise
            delay = _retry_after_seconds(exc.headers)
        except (urllib.error.URLError, http.client.IncompleteRead, TimeoutError, ConnectionError):
            if attempt >= retries:
                raise
            delay = None
        attempt += 1
        if delay is None:
            delay = min(max_backoff, backoff * 2 ** (attempt - 1))
        sleep(delay)


def s3_url(key: str, region: str = MEGATEST_REGION) -> str:
    """HTTPS URL of one object; commas, spaces and other reserved chars are quoted."""
    return f"https://{MEGATEST_BUCKET}.s3.{region}.amazonaws.com/" + urllib.parse.quote(
        key, safe="/"
    )


# ---------------------------------------------------------------------------
# nf-core release index (pipelines.json)
# ---------------------------------------------------------------------------
def default_index_cache_path() -> Path:
    return Path.home() / ".cache" / "depictio-nfcore" / "pipelines.json"


def load_pipelines_index(
    path: str | Path | None = None,
    *,
    cache_path: str | Path | None = None,
    max_age_s: float = PIPELINES_JSON_MAX_AGE_S,
    url: str = PIPELINES_JSON_URL,
) -> dict[str, Any]:
    """Load nf-co.re's ``pipelines.json``.

    Precedence: explicit ``path`` > ``$NFCORE_PIPELINES_JSON`` > a cache younger
    than ``max_age_s`` (default 6 h, under ``~/.cache/depictio-nfcore/``) >
    download (which refreshes the cache). A stale cache is used, with a
    warning, when the download fails.
    """
    explicit = path or os.environ.get(PIPELINES_JSON_ENV)
    if explicit:
        return json.loads(Path(explicit).expanduser().read_text(encoding="utf-8"))

    cache = Path(cache_path).expanduser() if cache_path else default_index_cache_path()
    if cache.is_file() and time.time() - cache.stat().st_mtime < max_age_s:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            pass  # corrupt cache: re-download below

    try:
        raw = http_get(url)
        index = json.loads(raw)
    except (OSError, ValueError) as exc:
        if cache.is_file():
            _log(f"! could not refresh {url} ({exc}); using stale cache {cache}")
            return json.loads(cache.read_text(encoding="utf-8"))
        raise
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        part = cache.with_name(cache.name + ".part")
        part.write_bytes(raw)
        os.replace(part, cache)
    except OSError:
        pass  # a read-only home must not break the lookup
    return index


def _workflow(index: dict[str, Any], pipeline: str) -> dict[str, Any]:
    for workflow in index.get("remote_workflows", []):
        if workflow.get("name") == pipeline:
            return workflow
    raise MegatestError(f"nf-core/{pipeline} is not in the nf-core pipelines index")


def normalize_version(version: str) -> str:
    """``v2.18.0`` -> ``2.18.0`` (a leading ``v`` is only stripped before a digit)."""
    return re.sub(r"^v(?=\d)", "", str(version).strip())


def _version_key(tag: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", tag))


def releases_for(index: dict[str, Any], pipeline: str) -> list[dict[str, Any]]:
    """Published releases of ``pipeline`` (``dev`` excluded), highest version first."""
    releases = [
        release
        for release in _workflow(index, pipeline).get("releases", [])
        if release.get("tag_name") and release["tag_name"] != "dev" and release.get("tag_sha")
    ]
    return sorted(
        releases,
        key=lambda r: (_version_key(r["tag_name"]), r.get("published_at", "")),
        reverse=True,
    )


def release_for_version(
    index: dict[str, Any], pipeline: str, version: str | None = "latest"
) -> dict[str, Any]:
    """The release dict (``tag_name``, ``tag_sha``, ``published_at``) for ``version``.

    ``version`` may be ``latest``/``None`` (highest published version), ``2.18.0``
    or ``v2.18.0``.
    """
    releases = releases_for(index, pipeline)
    if not releases:
        raise MegatestError(f"nf-core/{pipeline} has no published release in the index")
    if version in (None, "", "latest"):
        return releases[0]
    wanted = normalize_version(version)
    for release in releases:
        if normalize_version(release["tag_name"]) == wanted:
            return release
    known = ", ".join(r["tag_name"] for r in releases[:12])
    raise MegatestError(f"nf-core/{pipeline} has no release {version!r} (known: {known})")


def _release_by_sha(index: dict[str, Any] | None, pipeline: str, sha: str) -> dict[str, Any] | None:
    """The release published under ``sha`` (``None`` when unknown or no index)."""
    if index is None:
        return None
    try:
        releases = releases_for(index, pipeline)
    except MegatestError:
        return None  # pipeline (or its releases) unknown to the index
    return next((r for r in releases if r["tag_sha"] == sha), None)


def sha_to_tag(index: dict[str, Any] | None, pipeline: str, sha: str) -> str | None:
    """Release tag whose ``tag_sha`` is ``sha`` (``None`` when unknown or no index)."""
    release = _release_by_sha(index, pipeline, sha)
    return release["tag_name"] if release else None


def _release_published_at(index: dict[str, Any] | None, pipeline: str, sha: str) -> str:
    release = _release_by_sha(index, pipeline, sha)
    return (release.get("published_at") or "") if release else ""


# ---------------------------------------------------------------------------
# Megatest results listing (anonymous S3 REST)
# ---------------------------------------------------------------------------
class S3Object(NamedTuple):
    key: str  # relative to the listed prefix
    size: int
    last_modified: str


class Listing(NamedTuple):
    objects: list[S3Object]
    truncated: bool  # the caller's ``limit`` cut the walk short


def _s3_list(
    prefix: str,
    region: str = MEGATEST_REGION,
    delimiter: str | None = None,
    continuation_token: str | None = None,
    max_keys: int | None = None,
) -> ET.Element:
    """One anonymous ListObjectsV2 call against the megatest bucket -> XML root."""
    params: dict[str, str] = {"list-type": "2", "prefix": prefix}
    if delimiter:
        params["delimiter"] = delimiter
    if continuation_token:
        params["continuation-token"] = continuation_token
    if max_keys is not None:
        params["max-keys"] = str(max_keys)
    url = f"https://{MEGATEST_BUCKET}.s3.{region}.amazonaws.com/?" + urllib.parse.urlencode(params)
    return ET.fromstring(http_get(url))


def _parse_contents(root: ET.Element, prefix: str) -> list[S3Object]:
    objects: list[S3Object] = []
    for contents in root.findall(f"{_S3_NS}Contents"):
        key = contents.findtext(f"{_S3_NS}Key") or ""
        if not key:
            continue
        size_text = contents.findtext(f"{_S3_NS}Size") or "0"
        objects.append(
            S3Object(
                key[len(prefix) :],
                int(size_text),
                contents.findtext(f"{_S3_NS}LastModified") or "",
            )
        )
    return objects


def list_s3_objects(
    prefix: str, region: str = MEGATEST_REGION, limit: int | None = None
) -> Listing:
    """All objects under ``prefix`` (paginated), optionally capped at ``limit`` keys."""
    objects: list[S3Object] = []
    token: str | None = None
    while True:
        max_keys: int | None = None
        if limit is not None:
            remaining = limit - len(objects)
            if remaining <= 0:
                return Listing(objects, True)
            max_keys = min(1000, remaining)
        root = _s3_list(prefix, region=region, continuation_token=token, max_keys=max_keys)
        objects.extend(_parse_contents(root, prefix))
        truncated = root.findtext(f"{_S3_NS}IsTruncated", "false") == "true"
        token = root.findtext(f"{_S3_NS}NextContinuationToken")
        if not truncated or not token:
            return Listing(objects, False)
        # More pages exist: loop back, where a reached ``limit`` ends the walk.


def list_objects(
    prefix: str, region: str = MEGATEST_REGION, limit: int | None = None
) -> list[tuple[str, int]]:
    """All objects under ``prefix`` as ``(key_relative_to_prefix, size)`` (paginated)."""
    return [(obj.key, obj.size) for obj in list_s3_objects(prefix, region, limit).objects]


def list_keys(prefix: str, region: str = MEGATEST_REGION) -> list[str]:
    """All object keys under ``prefix``, returned relative to it (paginated)."""
    return [key for key, _ in list_objects(prefix, region)]


def download_object(
    prefix: str,
    rel_key: str,
    dest: Path,
    region: str = MEGATEST_REGION,
    size: int | None = None,
) -> bool:
    """Download one megatest object (``prefix`` + ``rel_key``) to ``dest``.

    Writes to ``dest.part`` first and renames atomically, so an interrupted
    download never leaves a truncated file behind. When ``size`` is given and
    ``dest`` already has exactly that size the download is skipped. Returns
    True when bytes were written, False when the existing file was kept.
    """
    dest = Path(dest)
    if size is not None and dest.is_file() and dest.stat().st_size == size:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(http_get(s3_url(prefix + rel_key, region), timeout=300))
    os.replace(part, dest)
    return True


# ---------------------------------------------------------------------------
# Run discovery
# ---------------------------------------------------------------------------
def list_result_prefixes(pipeline: str, region: str = MEGATEST_REGION) -> list[str]:
    """``<pipeline>/results-<40 hex>/`` prefixes; ``results-dev`` and ``results-test-*`` are skipped."""
    root = _s3_list(f"{pipeline}/", region=region, delimiter="/")
    prefixes: list[str] = []
    for common in root.findall(f"{_S3_NS}CommonPrefixes/{_S3_NS}Prefix"):
        name = (common.text or "").rstrip("/").rsplit("/", 1)[-1]
        if _RESULTS_DIR_RE.match(name):
            prefixes.append(f"{pipeline}/{name}/")
    return prefixes


def is_data_object(obj: S3Object) -> bool:
    """A real output file: non-empty, not a directory marker, not Nextflow provenance."""
    if obj.size <= 0 or obj.key.endswith("/"):
        return False
    return not (obj.key.startswith("pipeline_info/") or "/pipeline_info/" in obj.key)


@dataclass
class RunStats:
    prefix: str
    n_objects: int = 0
    n_data_objects: int = 0
    n_small_data_objects: int = 0  # data objects <= SMALL_OBJECT_BYTES
    data_bytes: int = 0
    newest_last_modified: str = ""
    has_multiqc_parquet: bool = False
    multiqc_parquet_keys: list[str] = field(default_factory=list)
    top_dirs: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def data_mb(self) -> float:
        return self.data_bytes / 1_000_000


def run_stats(
    prefix: str, region: str = MEGATEST_REGION, limit: int | None = DEFAULT_STATS_LIMIT
) -> RunStats:
    """Summarise a results prefix from (at most ``limit`` keys of) its listing."""
    listing = list_s3_objects(prefix, region, limit)
    stats = RunStats(prefix=prefix, n_objects=len(listing.objects), truncated=listing.truncated)
    tops: set[str] = set()
    for obj in listing.objects:
        if "/" in obj.key:
            tops.add(obj.key.split("/", 1)[0])
        if obj.last_modified > stats.newest_last_modified:
            stats.newest_last_modified = obj.last_modified
        if not is_data_object(obj):
            continue
        stats.n_data_objects += 1
        stats.data_bytes += obj.size
        if obj.size <= SMALL_OBJECT_BYTES:
            stats.n_small_data_objects += 1
        if obj.key.endswith("multiqc.parquet"):
            stats.has_multiqc_parquet = True
            stats.multiqc_parquet_keys.append(obj.key)
    stats.top_dirs = sorted(tops)
    return stats


def is_empty_run(stats: RunStats, min_data_objects: int = DEFAULT_MIN_DATA_OBJECTS) -> bool:
    """True for failed, aborted or truncated megatests.

    Such prefixes hold ``pipeline_info/`` plus zero-byte directory markers, or a
    few multi-GB intermediates that a partial sync left behind (methylseq 4.2.0:
    five BAM/txt.gz files, 37 GB, no report). A run counts as real when it has
    at least ``min_data_objects`` data objects AND at least that many small
    ones (<= ``SMALL_OBJECT_BYTES``), because every complete nf-core run
    publishes many small tables and reports.
    """
    return stats.n_data_objects < min_data_objects or stats.n_small_data_objects < min_data_objects


def _normalize_run_root(run_root: str | None) -> str:
    root = (run_root or "").strip().strip("/")
    return f"{root}/" if root else ""


def _normalize_sha(results_hash: str) -> str:
    return results_hash.strip().removeprefix("results-").rstrip("/").lower()


@dataclass
class ResolvedRun:
    pipeline: str
    results_sha: str
    prefix: str  # ``<pipeline>/results-<sha>/``
    tag: str | None  # release tag when the sha is a known ``tag_sha``
    run_root: str = ""  # ``""`` or ``sub/dir/`` below ``prefix`` that is the DATA_ROOT
    stats: RunStats | None = None

    @property
    def root_prefix(self) -> str:
        return self.prefix + self.run_root

    @property
    def s3_uri(self) -> str:
        return f"s3://{MEGATEST_BUCKET}/{self.prefix}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["root_prefix"] = self.root_prefix
        data["s3_uri"] = self.s3_uri
        return data


class PrefixSurvey(NamedTuple):
    prefix: str
    sha: str
    tag: str | None
    stats: RunStats


def survey_prefixes(
    pipeline: str,
    index: dict[str, Any] | None = None,
    region: str = MEGATEST_REGION,
    max_prefixes: int = 8,
    limit: int = 1000,
) -> list[PrefixSurvey]:
    """Stats for the newest ``max_prefixes`` results prefixes of ``pipeline``.

    Prefixes whose sha is a known release are surveyed newest-release first
    (unknown shas last); the result is ordered by the newest object seen.
    """
    prefixes = list_result_prefixes(pipeline, region)

    def sha_of(prefix: str) -> str:
        return prefix.rstrip("/").rsplit("results-", 1)[-1]

    prefixes.sort(key=lambda p: _release_published_at(index, pipeline, sha_of(p)), reverse=True)
    rows: list[PrefixSurvey] = []
    for prefix in prefixes[:max_prefixes]:
        sha = sha_of(prefix)
        rows.append(
            PrefixSurvey(
                prefix, sha, sha_to_tag(index, pipeline, sha), run_stats(prefix, region, limit)
            )
        )
    rows.sort(key=lambda r: r.stats.newest_last_modified, reverse=True)
    return rows


def format_survey(rows: Sequence[PrefixSurvey]) -> str:
    """Render a survey as a plain-text table (prefix, tag, data objects, MB, parquet)."""
    if not rows:
        return "(no results-<sha> prefixes found)"
    lines = [f"{'prefix':<74} {'tag':<10} {'data objs':>9} {'small':>6} {'MB':>9}  parquet"]
    for row in rows:
        stats = row.stats
        more = "+" if stats.truncated else ""
        parquet = "yes" if stats.has_multiqc_parquet else ("?" if stats.truncated else "no")
        lines.append(
            f"{row.prefix:<74} {row.tag or '?':<10} "
            f"{str(stats.n_data_objects) + more:>9} {stats.n_small_data_objects:>6} "
            f"{stats.data_mb:>9.1f}  {parquet}"
        )
    return "\n".join(lines)


def fallback_table(
    pipeline: str,
    index: dict[str, Any] | None = None,
    region: str = MEGATEST_REGION,
    max_prefixes: int = 8,
) -> str:
    """The table of real runs shown when a requested run is empty or missing."""
    rows = survey_prefixes(pipeline, index, region, max_prefixes)
    if not rows:
        return f"No results-<sha> prefixes under s3://{MEGATEST_BUCKET}/{pipeline}/."
    header = f"Newest megatest runs for nf-core/{pipeline} (pick one with --results-hash):"
    return header + "\n" + format_survey(rows)


def _safe_fallback(pipeline: str, index: dict[str, Any] | None, region: str) -> str:
    try:
        return fallback_table(pipeline, index, region)
    except (OSError, ET.ParseError, MegatestError) as exc:
        return f"(fallback table unavailable: {exc})"


def _try_load_index() -> dict[str, Any] | None:
    try:
        return load_pipelines_index()
    except (OSError, ValueError) as exc:
        _log(f"! nf-core pipelines index unavailable: {exc}")
        return None


def resolve_run(
    pipeline: str,
    version: str | None = None,
    results_hash: str | None = None,
    run_root: str = "",
    index: dict[str, Any] | None = None,
    region: str = MEGATEST_REGION,
    min_data_objects: int = DEFAULT_MIN_DATA_OBJECTS,
    stats_limit: int | None = DEFAULT_STATS_LIMIT,
) -> ResolvedRun:
    """Resolve and verify the megatest run of ``pipeline`` at ``version``.

    An explicit ``results_hash`` wins over the version lookup. The prefix must
    exist and hold at least ``min_data_objects`` real output files outside
    ``pipeline_info/``; when it does not, ``MegatestError`` is raised with the
    fallback table of the newest real runs embedded in its message. A non-empty
    ``run_root`` (e.g. rnaseq ``aligner_star_salmon/``) must exist below the prefix.
    """
    run_root = _normalize_run_root(run_root)
    if results_hash:
        sha = _normalize_sha(results_hash)
        if index is None:
            index = _try_load_index()
        tag = sha_to_tag(index, pipeline, sha)
    else:
        if index is None:
            index = load_pipelines_index()
        release = release_for_version(index, pipeline, version)
        sha, tag = release["tag_sha"], release["tag_name"]

    prefix = f"{pipeline}/results-{sha}/"
    stats = run_stats(prefix, region, stats_limit)
    label = f"nf-core/{pipeline} {tag or sha[:12]}"
    if stats.n_objects == 0:
        raise MegatestError(
            f"{label}: no megatest run at s3://{MEGATEST_BUCKET}/{prefix}",
            _safe_fallback(pipeline, index, region),
        )
    if is_empty_run(stats, min_data_objects):
        raise MegatestError(
            f"{label}: megatest run s3://{MEGATEST_BUCKET}/{prefix} is empty, failed or truncated "
            f"({stats.n_data_objects} data object(s) outside pipeline_info/, "
            f"{stats.n_small_data_objects} of them under {SMALL_OBJECT_BYTES // 1_000_000} MB, "
            f"in {stats.n_objects} keys; need {min_data_objects} of each)",
            _safe_fallback(pipeline, index, region),
        )
    if run_root:
        first_dir = run_root.split("/", 1)[0]
        present = first_dir in stats.top_dirs
        if not present and stats.truncated:
            probe = _s3_list(prefix + run_root, region=region, max_keys=1)
            present = probe.find(f"{_S3_NS}Contents") is not None
        if not present:
            raise MegatestError(
                f"{label}: run_root {run_root!r} not found under s3://{MEGATEST_BUCKET}/{prefix} "
                f"(top-level dirs: {', '.join(stats.top_dirs) or 'none'})"
            )
    return ResolvedRun(pipeline, sha, prefix, tag, run_root, stats)


def newest_nonempty_run(
    pipeline: str,
    index: dict[str, Any] | None = None,
    region: str = MEGATEST_REGION,
    run_root: str = "",
    max_prefixes: int = 8,
    min_data_objects: int = DEFAULT_MIN_DATA_OBJECTS,
) -> ResolvedRun | None:
    """The newest real run of ``pipeline`` (used to degrade when a pinned run is empty)."""
    for row in survey_prefixes(pipeline, index, region, max_prefixes):
        if not is_empty_run(row.stats, min_data_objects):
            return ResolvedRun(
                pipeline, row.sha, row.prefix, row.tag, _normalize_run_root(run_root), row.stats
            )
    return None


# ---------------------------------------------------------------------------
# Manifest (megatest.yaml)
# ---------------------------------------------------------------------------
class _SimpleYaml:
    """Parser for the flat YAML subset manifests use (PyYAML fallback).

    Supported: ``key: scalar``, nested mappings, lists of scalars (``- item``),
    literal block scalars (``key: |`` / ``|-``), ``[]``/``{}``, quoted strings,
    ``null``/``~``/``true``/``false`` and ``#`` comments. Numbers stay strings:
    manifests quote every value that must be text, and the shipped-manifest
    test asserts this parser agrees with PyYAML.
    """

    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()
        self.i = 0

    @staticmethod
    def _indent(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def _skip_blank(self) -> None:
        while self.i < len(self.lines):
            stripped = self.lines[self.i].strip()
            if stripped and not stripped.startswith("#"):
                return
            self.i += 1

    def parse(self) -> Any:
        self._skip_blank()
        if self.i >= len(self.lines):
            return {}
        return self._parse_block(self._indent(self.lines[self.i]))

    def _parse_block(self, indent: int) -> Any:
        self._skip_blank()
        if self.i >= len(self.lines):
            return None
        if self.lines[self.i].lstrip().startswith("- "):
            return self._parse_list(indent)
        return self._parse_mapping(indent)

    def _parse_list(self, indent: int) -> list[Any]:
        items: list[Any] = []
        while True:
            self._skip_blank()
            if self.i >= len(self.lines):
                break
            line = self.lines[self.i]
            if self._indent(line) != indent or not line.lstrip().startswith("- "):
                break
            self.i += 1
            items.append(self._scalar(line.lstrip()[2:]))
        return items

    def _parse_mapping(self, indent: int) -> dict[str, Any]:
        out: dict[str, Any] = {}
        while True:
            self._skip_blank()
            if self.i >= len(self.lines):
                break
            line = self.lines[self.i]
            level = self._indent(line)
            if level < indent:
                break
            if level > indent:
                raise ValueError(f"line {self.i + 1}: unexpected indentation")
            key, sep, rest = line.strip().partition(":")
            if not sep or not key or key.startswith("- "):
                raise ValueError(f"line {self.i + 1}: expected 'key: value'")
            key = self._scalar(key)
            rest = rest.strip()
            self.i += 1
            if rest in ("|", "|-"):
                out[key] = self._block_scalar(indent, keep_final_newline=rest == "|")
            elif rest == "":
                self._skip_blank()
                if self.i < len(self.lines):
                    nxt = self.lines[self.i]
                    if self._indent(nxt) > indent:
                        out[key] = self._parse_block(self._indent(nxt))
                        continue
                    if self._indent(nxt) == indent and nxt.lstrip().startswith("- "):
                        out[key] = self._parse_list(indent)
                        continue
                out[key] = None
            else:
                out[key] = self._scalar(rest)
        return out

    def _block_scalar(self, indent: int, keep_final_newline: bool) -> str:
        body: list[str] = []
        block_indent: int | None = None
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if not line.strip():
                body.append("")
                self.i += 1
                continue
            level = self._indent(line)
            if level <= indent:
                break
            if block_indent is None:
                block_indent = level
            body.append(line[block_indent:])
            self.i += 1
        while body and body[-1] == "":
            body.pop()
        text = "\n".join(body)
        return text + "\n" if keep_final_newline and text else text

    @staticmethod
    def _scalar(raw: str) -> Any:
        value = raw.strip()
        if value[:1] in ('"', "'"):
            quote = value[0]
            end = value.find(quote, 1)
            if end == -1:
                raise ValueError(f"unterminated quoted string: {raw!r}")
            return value[1:end]
        value = value.split(" #", 1)[0].rstrip()
        if value in ("", "~", "null", "Null", "NULL"):
            return None
        if value in ("true", "True", "TRUE"):
            return True
        if value in ("false", "False", "FALSE"):
            return False
        if value == "[]":
            return []
        if value == "{}":
            return {}
        return value


def parse_yaml(text: str) -> Any:
    """``yaml.safe_load`` when PyYAML is installed, else the manifest-subset parser."""
    try:
        import yaml
    except ImportError:
        return _SimpleYaml(text).parse()
    return yaml.safe_load(text)


@dataclass
class Manifest:
    """``megatest.yaml``: which megatest run a template was validated against and what to fetch.

    ``keys`` and ``prefix_keys`` are exact keys or fnmatch globs; ``keys`` are
    relative to ``run_root`` (the local DATA_ROOT mirrors them), ``prefix_keys``
    to the results prefix itself (files outside the run root, e.g.
    ``pipeline_info/`` when the run root is nested). ``renames`` extend
    ``DEFAULT_RENAMES``.
    """

    pipeline: str
    version: str
    results_sha: str | None = None
    run_root: str = ""
    multiqc: dict[str, Any] = field(default_factory=dict)
    keys: list[str] = field(default_factory=list)
    prefix_keys: list[str] = field(default_factory=list)
    renames: dict[str, str] = field(default_factory=dict)
    post_fetch_help: str = ""
    path: Path | None = None

    @property
    def effective_renames(self) -> dict[str, str]:
        return {**DEFAULT_RENAMES, **self.renames}


_MANIFEST_FIELDS = {
    "pipeline",
    "version",
    "results_sha",
    "run_root",
    "multiqc",
    "keys",
    "prefix_keys",
    "renames",
    "post_fetch_help",
}
_MULTIQC_FIELDS = {"version", "parquet", "reprocess"}


def manifest_path(pipeline: str, version: str, projects_dir: Path = NFCORE_PROJECTS_DIR) -> Path:
    return projects_dir / pipeline / version / MANIFEST_NAME


def is_relative_key(key: str) -> bool:
    """Relative, forward-slash, no ``..`` segments, no drive/backslash tricks."""
    if not key or key.startswith("/") or "\\" in key or ":" in key.split("/", 1)[0]:
        return False
    return ".." not in key.split("/")


def _require_str_list(value: Any, name: str, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ValueError(f"{where}: '{name}' must be a list of non-empty strings")
    for item in value:
        if not is_relative_key(item):
            raise ValueError(f"{where}: '{name}' entry {item!r} must be a relative path")
    return list(value)


def manifest_from_dict(data: Any, path: Path | None = None) -> Manifest:
    """Validate a parsed manifest mapping (raises ``ValueError`` with the field named)."""
    where = str(path) if path else "manifest"
    if not isinstance(data, dict):
        raise ValueError(f"{where}: top level must be a mapping")
    unknown = set(data) - _MANIFEST_FIELDS
    if unknown:
        raise ValueError(f"{where}: unknown field(s) {sorted(unknown)}")
    for name in ("pipeline", "version"):
        if not isinstance(data.get(name), str) or not data[name].strip():
            raise ValueError(f"{where}: '{name}' is required and must be a quoted string")

    sha = data.get("results_sha")
    if sha is not None and (not isinstance(sha, str) or not _SHA_RE.match(sha)):
        raise ValueError(f"{where}: 'results_sha' must be a 40-char lowercase hex sha or null")

    run_root = data.get("run_root") or ""
    if not isinstance(run_root, str) or (run_root and not is_relative_key(run_root.rstrip("/"))):
        raise ValueError(f"{where}: 'run_root' must be a relative directory (or empty)")

    multiqc = data.get("multiqc") or {}
    if not isinstance(multiqc, dict) or set(multiqc) - _MULTIQC_FIELDS:
        raise ValueError(
            f"{where}: 'multiqc' must be a mapping with keys {sorted(_MULTIQC_FIELDS)}"
        )
    mq_version = multiqc.get("version")
    if mq_version is not None and not isinstance(mq_version, str):
        raise ValueError(f"{where}: 'multiqc.version' must be a quoted string or null")
    parquet = multiqc.get("parquet")
    if parquet is not None and (not isinstance(parquet, str) or not is_relative_key(parquet)):
        raise ValueError(f"{where}: 'multiqc.parquet' must be a relative path or null")
    if not isinstance(multiqc.get("reprocess", False), bool):
        raise ValueError(f"{where}: 'multiqc.reprocess' must be true or false")
    multiqc = {
        "version": mq_version,
        "parquet": parquet,
        "reprocess": bool(multiqc.get("reprocess", False)),
    }

    renames_raw = data.get("renames") or {}
    if not isinstance(renames_raw, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and is_relative_key(v)
        for k, v in renames_raw.items()
    ):
        raise ValueError(f"{where}: 'renames' must map key globs to relative paths")

    help_text = data.get("post_fetch_help") or ""
    if not isinstance(help_text, str):
        raise ValueError(f"{where}: 'post_fetch_help' must be a string")

    return Manifest(
        pipeline=data["pipeline"].strip(),
        version=data["version"].strip(),
        results_sha=sha,
        run_root=_normalize_run_root(run_root),
        multiqc=multiqc,
        keys=_require_str_list(data.get("keys"), "keys", where),
        prefix_keys=_require_str_list(data.get("prefix_keys"), "prefix_keys", where),
        renames=dict(renames_raw),
        post_fetch_help=help_text,
        path=path,
    )


def load_manifest(path: str | Path) -> Manifest:
    path = Path(path)
    try:
        data = parse_yaml(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{path}: not valid manifest YAML ({exc})") from exc
    return manifest_from_dict(data, path)


def has_glob(pattern: str) -> bool:
    return any(ch in pattern for ch in "*?[")


def expand_keys(
    patterns: Iterable[str], objects: Iterable[S3Object]
) -> tuple[list[S3Object], list[str]]:
    """Resolve manifest patterns against a listing.

    Exact keys pass through when present; globs expand with ``fnmatch`` (note
    ``*`` crosses ``/``). Directory markers never match. Returns the matched
    objects in pattern order (deduplicated) and the patterns that matched nothing.
    """
    files = [obj for obj in objects if not obj.key.endswith("/")]
    by_key = {obj.key: obj for obj in files}
    seen: set[str] = set()
    matched: list[S3Object] = []
    unmatched: list[str] = []
    for pattern in patterns:
        if has_glob(pattern):
            hits = [obj for obj in files if fnmatch.fnmatchcase(obj.key, pattern)]
        else:
            hits = [by_key[pattern]] if pattern in by_key else []
        if not hits:
            unmatched.append(pattern)
            continue
        for obj in hits:
            if obj.key not in seen:
                seen.add(obj.key)
                matched.append(obj)
    return matched, unmatched


def rename_target(key: str, renames: dict[str, str] | None = None) -> str:
    """Local relative path for ``key`` (first matching rename glob wins, else unchanged)."""
    for pattern, target in (DEFAULT_RENAMES if renames is None else renames).items():
        if fnmatch.fnmatchcase(key, pattern):
            return target
    return key


def apply_renames(
    objects: Iterable[S3Object], renames: dict[str, str] | None = None
) -> list[tuple[S3Object, str]]:
    """Pair each object with its local path; sources sharing a target keep the newest only.

    "Newest" is by S3 ``LastModified`` then by key, so of two timestamped
    ``params_*.json`` files the later one becomes ``pipeline_info/params.json``.
    """
    targets = [(obj, rename_target(obj.key, renames)) for obj in objects]
    newest: dict[str, S3Object] = {}
    for obj, target in targets:
        current = newest.get(target)
        if current is None or (obj.last_modified, obj.key) > (current.last_modified, current.key):
            newest[target] = obj
    return [(obj, target) for obj, target in targets if newest[target] is obj]


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------
@dataclass
class FetchFile:
    key: str  # relative to the results prefix
    dest: Path
    size: int
    action: str  # planned | downloaded | kept | too-large


@dataclass
class FetchSummary:
    dest: Path
    prefix: str
    run_root: str
    files: list[FetchFile]
    unmatched: list[str]
    dry_run: bool

    def count(self, action: str) -> int:
        return sum(1 for f in self.files if f.action == action)

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files if f.action != "too-large")


def _strip_root(objects: Iterable[S3Object], run_root: str) -> list[S3Object]:
    if not run_root:
        return list(objects)
    return [
        S3Object(obj.key[len(run_root) :], obj.size, obj.last_modified)
        for obj in objects
        if obj.key.startswith(run_root)
    ]


def fetch_run(
    run: ResolvedRun,
    dest: Path,
    keys: Sequence[str],
    prefix_keys: Sequence[str] = (),
    renames: dict[str, str] | None = None,
    *,
    dry_run: bool = False,
    max_file_mb: float = DEFAULT_MAX_FILE_MB,
    region: str = MEGATEST_REGION,
) -> FetchSummary:
    """Mirror the manifest subset of ``run`` into ``dest``.

    ``keys`` are matched below ``run.run_root`` and land at ``dest/<renamed key>``;
    ``prefix_keys`` are matched at the prefix root and land at ``dest/<renamed key>``
    too. Existing files of identical size are kept, objects above ``max_file_mb``
    are reported and skipped, and ``dry_run`` plans without touching the disk.
    """
    dest = Path(dest).expanduser()
    renames = {**DEFAULT_RENAMES, **(renames or {})}
    root_listing = list_s3_objects(run.root_prefix, region).objects
    matched, unmatched = expand_keys(keys, root_listing)
    plan: list[tuple[S3Object, str]] = [
        (S3Object(run.run_root + obj.key, obj.size, obj.last_modified), target)
        for obj, target in apply_renames(matched, renames)
    ]
    if prefix_keys:
        full_listing = list_s3_objects(run.prefix, region).objects if run.run_root else root_listing
        extra, extra_unmatched = expand_keys(prefix_keys, full_listing)
        plan.extend(apply_renames(extra, renames))
        unmatched.extend(extra_unmatched)

    files: list[FetchFile] = []
    seen_targets: set[str] = set()
    limit_bytes = max_file_mb * 1_000_000
    for obj, target in plan:
        if target in seen_targets:
            continue
        # The manifest strings are validated on load, but this target can also come
        # straight from a bucket listing (rename_target passes unmatched keys through).
        # Path joining silently discards dest when the right operand is absolute, so an
        # absolute or dot-dot key would escape the destination instead of erroring.
        if not is_relative_key(target):
            raise MegatestError(
                f"refusing to write {target!r}: object keys must stay below the destination"
            )
        seen_targets.add(target)
        local = dest / target
        if obj.size > limit_bytes:
            action = "too-large"
        elif dry_run:
            action = "planned"
        elif download_object(run.prefix, obj.key, local, region, size=obj.size):
            action = "downloaded"
        else:
            action = "kept"
        files.append(FetchFile(obj.key, local, obj.size, action))
    return FetchSummary(dest, run.prefix, run.run_root, files, unmatched, dry_run)


def default_dest(pipeline: str, version: str) -> Path:
    return DEFAULT_DEST_ROOT.expanduser() / pipeline / version / "megatest"


def _human_size(n_bytes: int) -> str:
    if n_bytes < 1000:
        return f"{n_bytes} B"
    value = n_bytes / 1000
    for unit in ("KB", "MB"):
        if value < 1000:
            return f"{value:.1f} {unit}"
        value /= 1000
    return f"{value:.1f} GB"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
_ACTION_MARKERS = {"planned": "plan", "downloaded": "get ", "kept": "keep", "too-large": "SKIP"}


def _index_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    if getattr(args, "index", None):
        return load_pipelines_index(args.index)
    return None


def _prefix_for(
    pipeline: str,
    version: str | None,
    results_hash: str | None,
    index: dict[str, Any] | None,
) -> tuple[str, str | None]:
    """Unverified ``(prefix, tag)`` for ``ls`` (which may inspect empty runs)."""
    if results_hash:
        sha = _normalize_sha(results_hash)
        return f"{pipeline}/results-{sha}/", sha_to_tag(index, pipeline, sha)
    index = index if index is not None else load_pipelines_index()
    release = release_for_version(index, pipeline, version)
    return f"{pipeline}/results-{release['tag_sha']}/", release["tag_name"]


def _print_resolved(run: ResolvedRun) -> None:
    stats = run.stats
    print(f"prefix     {run.prefix}")
    print(f"s3         {run.s3_uri}")
    print(f"tag        {run.tag or '? (sha is not a release tag_sha)'}")
    print(f"sha        {run.results_sha}")
    print(f"run_root   {run.run_root or '(prefix root)'}")
    if stats is not None:
        more = " (listing capped, counts are lower bounds)" if stats.truncated else ""
        print(f"objects    {stats.n_objects}{more}")
        print(
            f"data       {stats.n_data_objects} files ({stats.n_small_data_objects} under "
            f"{SMALL_OBJECT_BYTES // 1_000_000} MB), {stats.data_mb:.1f} MB"
        )
        print(f"newest     {stats.newest_last_modified or '?'}")
        parquet = (
            ", ".join(stats.multiqc_parquet_keys) if stats.has_multiqc_parquet else "none seen"
        )
        print(f"multiqc    {parquet}")
        print(f"top dirs   {', '.join(stats.top_dirs) or '(flat)'}")


def cmd_resolve(args: argparse.Namespace) -> int:
    index = _index_from_args(args)
    run = resolve_run(
        args.pipeline,
        version=args.version,
        results_hash=args.results_hash,
        run_root=args.run_root or "",
        index=index,
        min_data_objects=args.min_data_objects,
    )
    if args.json:
        print(json.dumps(run.to_dict(), indent=2))
    else:
        _print_resolved(run)
    return 0


def cmd_ls(args: argparse.Namespace) -> int:
    index = _index_from_args(args)
    prefix, tag = _prefix_for(args.pipeline, args.version, args.results_hash, index)
    sub = _normalize_run_root(args.prefix)
    _log(f"-> listing s3://{MEGATEST_BUCKET}/{prefix}{sub}  (tag {tag or '?'})")
    objects = [
        obj
        for obj in list_s3_objects(prefix + sub, limit=args.limit).objects
        if not obj.key.endswith("/")
    ]
    if args.ext:
        # Accept both "--ext tsv csv" and "--ext tsv,csv". An extension is never
        # allowed to contain a comma, so the comma-joined form can only ever be a
        # caller writing the list the other way, and left alone it matches nothing
        # and reports the run as empty instead of saying the filter was malformed.
        raw = [piece for value in args.ext for piece in value.split(",") if piece]
        exts = tuple(e if e.startswith(".") else f".{e}" for e in raw)
        objects = [obj for obj in objects if obj.key.endswith(exts)]
    if args.grep:
        pattern = re.compile(args.grep)
        objects = [obj for obj in objects if pattern.search(obj.key)]
    if args.top_dirs:
        totals: dict[str, tuple[int, int]] = {}
        for obj in objects:
            top = obj.key.split("/", 1)[0] if "/" in obj.key else "."
            n, size = totals.get(top, (0, 0))
            totals[top] = (n + 1, size + obj.size)
        print(f"{'dir':<40} {'files':>7} {'size':>10}")
        for top, (n, size) in sorted(totals.items(), key=lambda kv: kv[1][1], reverse=True):
            print(f"{top + '/':<40} {n:>7} {_human_size(size):>10}")
        return 0
    for obj in objects:
        print(f"{_human_size(obj.size):>10}  {obj.key}" if args.sizes else obj.key)
    _log(f"-> {len(objects)} object(s), {_human_size(sum(o.size for o in objects))}")
    return 0


def _load_fetch_manifest(args: argparse.Namespace) -> Manifest | None:
    if args.manifest:
        return load_manifest(args.manifest)
    if args.version and args.version != "latest":
        default = manifest_path(args.pipeline, args.version)
        if default.is_file():
            return load_manifest(default)
    return None


def _print_fetch_summary(summary: FetchSummary) -> None:
    """One line per file, the unmatched manifest patterns on stderr, then the totals."""
    for entry in summary.files:
        rel = entry.dest.relative_to(summary.dest)
        print(f"  {_ACTION_MARKERS[entry.action]}  {_human_size(entry.size):>10}  {rel}")
    for pattern in summary.unmatched:
        _log(f"! no object matches manifest pattern {pattern!r}")
    print(
        f"\n{len(summary.files)} file(s), {_human_size(summary.total_bytes)}"
        f" (downloaded {summary.count('downloaded')}, kept {summary.count('kept')},"
        f" planned {summary.count('planned')}, too large {summary.count('too-large')})"
    )


def cmd_fetch(args: argparse.Namespace) -> int:
    manifest = _load_fetch_manifest(args)
    if manifest is None and not args.key:
        raise ValueError(
            f"no manifest for {args.pipeline} {args.version or '?'} "
            f"(expected {manifest_path(args.pipeline, args.version or '<version>')}); "
            "pass --manifest FILE or --key KEY ..."
        )
    version = args.version or (manifest.version if manifest else None)
    if not version:
        raise ValueError("--version is required without a manifest")
    if manifest and manifest.pipeline != args.pipeline:
        raise ValueError(f"manifest is for {manifest.pipeline}, not {args.pipeline}")

    index = _index_from_args(args)
    results_hash = args.results_hash or (manifest.results_sha if manifest else None)
    run_root = (
        args.run_root if args.run_root is not None else (manifest.run_root if manifest else "")
    )
    run = resolve_run(
        args.pipeline, version=version, results_hash=results_hash, run_root=run_root, index=index
    )
    if results_hash and version != "latest":
        try:
            release = release_for_version(index or load_pipelines_index(), args.pipeline, version)
        except (MegatestError, OSError, ValueError):
            release = None
        if release and release["tag_sha"] != run.results_sha:
            _log(
                f"! pinned results-{run.results_sha[:12]} is release {run.tag or '?'}, "
                f"not the {version} release sha ({release['tag_sha'][:12]}); keeping the pin"
            )

    keys = list(args.key) if args.key else manifest.keys  # type: ignore[union-attr]
    prefix_keys = [] if args.key else (manifest.prefix_keys if manifest else [])
    renames = manifest.renames if manifest else {}
    dest = Path(args.dest).expanduser() if args.dest else default_dest(args.pipeline, version)

    _log(f"-> {run.s3_uri}  (tag {run.tag or '?'}, run_root {run.run_root or '(prefix root)'})")
    _log(f"-> {'planning' if args.dry_run else 'fetching'} into {dest}")
    summary = fetch_run(
        run,
        dest,
        keys,
        prefix_keys,
        renames,
        dry_run=args.dry_run,
        max_file_mb=args.max_file_mb,
    )
    _print_fetch_summary(summary)
    if manifest and manifest.post_fetch_help and not args.dry_run:
        print("\n" + manifest.post_fetch_help.replace("{dest}", str(dest)).rstrip())
    return 0


def _add_common(parser: argparse.ArgumentParser, *, version_default: str | None) -> None:
    parser.add_argument("--pipeline", required=True, help="nf-core pipeline name, e.g. ampliseq")
    parser.add_argument(
        "--version",
        default=version_default,
        help="release tag (2.18.0, v2.18.0 or latest); ignored when --results-hash is given",
    )
    parser.add_argument("--results-hash", help="pin an exact results-<sha> instead of the release")
    parser.add_argument(
        "--index", help=f"local pipelines.json (default: ${PIPELINES_JSON_ENV}, cache, download)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_resolve = sub.add_parser(
        "resolve", help="Map pipeline + version to a verified results prefix"
    )
    _add_common(p_resolve, version_default="latest")
    p_resolve.add_argument("--run-root", help="sub-directory of the prefix that is the DATA_ROOT")
    p_resolve.add_argument(
        "--min-data-objects",
        type=int,
        default=DEFAULT_MIN_DATA_OBJECTS,
        help=f"fewer real files than this = empty run (default {DEFAULT_MIN_DATA_OBJECTS})",
    )
    p_resolve.add_argument("--json", action="store_true", help="machine-readable output")
    p_resolve.set_defaults(func=cmd_resolve)

    p_ls = sub.add_parser("ls", help="List objects of a megatest run")
    _add_common(p_ls, version_default="latest")
    p_ls.add_argument("--prefix", default="", help="list only below this sub-directory")
    p_ls.add_argument(
        "--ext",
        nargs="*",
        help="keep only these extensions, space or comma separated (tsv csv parquet)",
    )
    p_ls.add_argument("--grep", help="keep only keys matching this regex")
    p_ls.add_argument("--top-dirs", action="store_true", help="aggregate per top-level directory")
    p_ls.add_argument("--sizes", action="store_true", help="print sizes next to keys")
    p_ls.add_argument("--limit", type=int, help="stop after this many keys")
    p_ls.set_defaults(func=cmd_ls)

    p_fetch = sub.add_parser("fetch", help="Download the manifest subset of a megatest run")
    _add_common(p_fetch, version_default=None)
    p_fetch.add_argument("--manifest", help="megatest.yaml to use (default: the template's)")
    p_fetch.add_argument(
        "--dest",
        help=f"target directory (default {DEFAULT_DEST_ROOT}/<pipeline>/<version>/megatest)",
    )
    p_fetch.add_argument("--key", action="append", help="fetch only these keys/globs (repeatable)")
    p_fetch.add_argument("--run-root", help="override the manifest run_root")
    p_fetch.add_argument("--dry-run", action="store_true", help="plan only, write nothing")
    p_fetch.add_argument(
        "--max-file-mb",
        type=float,
        default=DEFAULT_MAX_FILE_MB,
        help=f"skip objects larger than this (default {DEFAULT_MAX_FILE_MB:g})",
    )
    p_fetch.set_defaults(func=cmd_fetch)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except MegatestError as exc:
        _log(f"error: {exc.reason}")
        if exc.fallback:
            _log("")
            _log(exc.fallback)
        return 3
    except (ValueError, OSError, ET.ParseError) as exc:
        _log(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
