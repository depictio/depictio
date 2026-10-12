"""Workflow metadata from a repository URL, to pre-fill the builder's workflow editor.

Best effort, and GitHub only: a few small files at fixed URLs built from the
``github.com/<owner>/<repo>`` the user pasted, never the URL itself, so the
server never fetches an address a user chose. Sources, in priority order:

1. **RO-Crate**: ``ro-crate-metadata.json`` at the repository root (name,
   version, description, license, author, and the workflow's language as engine);
2. **Nextflow**: the ``manifest {}`` block of ``nextflow.config``, read by the
   parser run-info detection uses (``models.models.nextflow.parse_manifest_block``);
3. **GitHub API**: the repository's name, description, homepage and license.

nf-core pipelines also get their logo, inlined as a ``data:`` URI. Fetching is
injected: on the server every request goes through the remote-fetch gateway
(``remote_fetch.fetch_validated_*``: host policy, redirects, size cap), from
the CLI through its direct counterparts. Any failure only means fewer fields.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from depictio.models.models.nextflow import parse_manifest_block

TextGetter = Callable[[str], str]
BytesGetter = Callable[[str], bytes]

# Workflow engines depictio actually supports (those with brand logos/handling)
# plus python; used to normalise an extracted engine name onto a known value.
# Anything else falls through lower-cased rather than being dropped.
KNOWN_ENGINES = ["nextflow", "snakemake", "galaxy", "python"]
# "r" is matched whole: as a substring it would claim "nextflow" or "galaxy".
_WHOLE_WORD_ENGINES = ["r"]


def _github_owner_repo(url: str) -> tuple[str | None, str | None]:
    """(owner, repo) for a github.com URL, else (None, None)."""
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in ("github.com", "www.github.com"):
        return None, None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None, None
    return parts[0], parts[1].removesuffix(".git")


def _normalise_engine(name: str | None) -> str | None:
    if not name:
        return None
    low = name.strip().lower()
    for known in KNOWN_ENGINES:
        if known in low:
            return known
    for known in _WHOLE_WORD_ENGINES:
        if re.search(rf"\b{known}\b", low):
            return known
    return low or None


def _resolve_names(value: Any, by_id: dict[str, Any]) -> str | None:
    """Resolve an RO-Crate value that may be a string, an @id ref, or a list of
    either, into a comma-joined display string (e.g. authors, license)."""
    items = value if isinstance(value, list) else [value]
    names: list[str] = []
    for item in items:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            resolved = by_id.get(item.get("@id"), item)
            names.append(str(resolved.get("name") or item.get("@id") or "").strip())
    names = [n for n in names if n]
    return ", ".join(names) or None


def parse_ro_crate(data: dict[str, Any]) -> dict[str, Any]:
    """Extract name / version / description / license / author / engine from RO-Crate."""
    graph = data.get("@graph")
    if not isinstance(graph, list):
        return {}
    by_id = {e.get("@id"): e for e in graph if isinstance(e, dict)}

    # The metadata descriptor points at the root data entity via `about`.
    descriptor = by_id.get("ro-crate-metadata.json") or by_id.get("ro-crate-metadata.jsonld")
    root = None
    about = descriptor.get("about") if isinstance(descriptor, dict) else None
    if isinstance(about, dict):
        root = by_id.get(about.get("@id"))
    root = root or by_id.get("./")

    out: dict[str, Any] = {}
    if isinstance(root, dict):
        for key, field in (
            ("name", "name"),
            ("version", "version"),
            ("description", "description"),
        ):
            if root.get(key):
                out[field] = str(root[key]).strip()
        license_name = _resolve_names(root.get("license"), by_id)
        if license_name:
            out["license"] = license_name
        author_name = _resolve_names(root.get("author"), by_id)
        if author_name:
            out["author"] = author_name

    # Engine: the programmingLanguage of a workflow / source-code entity.
    for entity in graph:
        if not isinstance(entity, dict):
            continue
        types = entity.get("@type")
        types = types if isinstance(types, list) else [types]
        if not any(
            "ComputationalWorkflow" in str(t) or "SoftwareSourceCode" in str(t) for t in types
        ):
            continue
        lang = entity.get("programmingLanguage")
        if isinstance(lang, dict):
            lang = by_id.get(lang.get("@id"), lang).get("name") or lang.get("@id")
        engine = _normalise_engine(lang if isinstance(lang, str) else None)
        if engine:
            out.setdefault("engine", engine)
            break
    return out


def parse_nextflow_config(text: str) -> dict[str, Any]:
    """The ``manifest {}`` fields of a ``nextflow.config``; the engine is Nextflow."""
    return {"engine": "nextflow", **parse_manifest_block(text)}


_MAX_TEXT_BYTES = 512 * 1024
_MAX_LOGO_BYTES = 1_000_000


def default_getters() -> tuple[TextGetter, BytesGetter]:
    """The gateway on a server, the direct reads from the CLI (``depictio project-builder``)."""
    from depictio.api.v1 import remote_fetch

    if remote_fetch.is_server_context():
        return (
            lambda url: remote_fetch.fetch_validated_text(url, max_bytes=_MAX_TEXT_BYTES),
            lambda url: remote_fetch.fetch_validated_bytes(url, max_bytes=_MAX_LOGO_BYTES),
        )
    return (
        remote_fetch.direct_fetch_text,
        lambda url: remote_fetch.direct_fetch_bytes(url, max_bytes=_MAX_LOGO_BYTES),
    )


class _Fetcher:
    """Best-effort reads: None on any failure, and whether the gateway refused one."""

    def __init__(self, get_text: TextGetter, get_bytes: BytesGetter):
        self._get_text = get_text
        self._get_bytes = get_bytes
        self.blocked = False

    def _failed(self, url: str, exc: Exception) -> None:
        from depictio.api.v1.remote_fetch import RemoteFetchFailed, RemoteURLRejected

        if isinstance(exc, RemoteURLRejected) and not isinstance(exc, RemoteFetchFailed):
            self.blocked = True

    def text(self, url: str) -> str | None:
        try:
            return self._get_text(url)
        except Exception as exc:  # noqa: BLE001 - offline, 404, refused: fewer fields
            self._failed(url, exc)
            return None

    def data_uri(self, url: str, mime: str = "image/png") -> str | None:
        try:
            data = self._get_bytes(url)
        except Exception as exc:  # noqa: BLE001 - a missing logo just is not shown
            self._failed(url, exc)
            return None
        if not data or len(data) > _MAX_LOGO_BYTES:
            return None
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """Fill only keys ``dst`` doesn't already have (earlier sources win)."""
    for key, value in src.items():
        if value and not dst.get(key):
            dst[key] = value


def _clean_description(text: str, limit: int = 280) -> str:
    """Reduce a possibly-HTML/Markdown description (e.g. an nf-core README, whose
    RO-Crate description is the whole file) to a short plain-text summary."""
    if not text:
        return ""
    s = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)  # HTML comments
    s = re.sub(r"<[^>]+>", " ", s)  # HTML tags
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", s)  # markdown images / badges
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)  # links → keep the text
    s = re.sub(r"[#>*_`~]+", " ", s)  # header / emphasis / code punctuation
    s = re.sub(r"\s+", " ", s).strip()  # collapse whitespace
    if len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


def fetch_workflow_metadata(
    url: str,
    *,
    get_text: TextGetter | None = None,
    get_bytes: BytesGetter | None = None,
) -> dict[str, Any]:
    """Best-effort workflow metadata from a repository URL.

    Returns ``{repository_url, name?, engine?, version?, catalog?, description?,
    author?, license?, homepage?, logo_light?, logo_dark?, sources: [...],
    blocked}``. Never raises on network problems: ``sources`` is empty when
    nothing was found, and ``blocked`` says the server's remote policy refused
    a request (an operator decision, not an outage). Only github.com
    repositories are read.
    """
    if get_text is None or get_bytes is None:
        default_text, default_bytes = default_getters()
        get_text = get_text or default_text
        get_bytes = get_bytes or default_bytes
    fetch = _Fetcher(get_text, get_bytes)
    url = (url or "").strip()
    if not url:
        raise ValueError("repository url is required")
    if not re.match(r"^https?://", url):
        raise ValueError("The repository URL must start with https://.")

    result: dict[str, Any] = {"repository_url": url}
    sources: list[str] = []
    owner, repo = _github_owner_repo(url)

    # nf-core is always a Nextflow workflow published in the nf-core catalog.
    # This inference needs no network, so record it as a source (otherwise an
    # offline nf-core URL would populate fields yet report "nothing found").
    if owner and owner.lower() == "nf-core":
        result["engine"] = "nextflow"
        result["catalog"] = {"name": "nf-core", "url": url}
        sources.append("nf-core")

    raw_base = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD" if owner and repo else None

    if raw_base:
        crate = fetch.text(f"{raw_base}/ro-crate-metadata.json")
        if crate:
            try:
                meta = parse_ro_crate(json.loads(crate))
                if meta:
                    _merge(result, meta)
                    sources.append("ro-crate")
            except (json.JSONDecodeError, ValueError):
                pass

        if any(k not in result for k in ("name", "version", "description", "author", "homepage")):
            config = fetch.text(f"{raw_base}/nextflow.config")
            if config:
                _merge(result, parse_nextflow_config(config))
                sources.append("nextflow.config")

    if owner and repo and any(k not in result for k in ("name", "description", "homepage")):
        api = fetch.text(f"https://api.github.com/repos/{owner}/{repo}")
        if api:
            try:
                gh = json.loads(api)
                gh_meta: dict[str, Any] = {}
                if gh.get("name"):
                    gh_meta["name"] = gh["name"]
                if gh.get("description"):
                    gh_meta["description"] = gh["description"]
                if gh.get("homepage"):
                    gh_meta["homepage"] = gh["homepage"]
                license_info = gh.get("license")
                if isinstance(license_info, dict) and license_info.get("spdx_id"):
                    gh_meta["license"] = license_info["spdx_id"]
                if gh_meta:
                    _merge(result, gh_meta)
                    sources.append("github")
            except (json.JSONDecodeError, ValueError):
                pass

    # nf-core pipelines ship their own logo in the repo assets; fetch both theme
    # variants and inline them so the Project Builder can show the actual pipeline brand.
    if raw_base and owner and owner.lower() == "nf-core" and repo:
        light = fetch.data_uri(f"{raw_base}/docs/images/nf-core-{repo}_logo_light.png")
        dark = fetch.data_uri(f"{raw_base}/docs/images/nf-core-{repo}_logo_dark.png")
        if light or dark:
            result["logo_light"] = light or dark
            result["logo_dark"] = dark or light
            sources.append("logo")

    # Descriptions can arrive as raw HTML/Markdown (nf-core's RO-Crate carries the
    # whole README) — reduce to a short plain-text summary for display.
    if result.get("description"):
        result["description"] = _clean_description(result["description"])

    result["sources"] = sources
    result["blocked"] = fetch.blocked
    return result
