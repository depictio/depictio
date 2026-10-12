"""Lightweight, RO-Crate-flavoured workflow metadata extraction from a repo URL.

The Project Builder runs locally, so given a public repository URL it best-effort fetches a
few small files and merges what it finds — ``name``, ``engine``, ``version``,
``catalog`` (fed into the project.yaml) plus ``description`` / ``author`` /
``license`` / ``homepage`` (shown to the user, not stored) — to pre-fill the
workflow editor. Everything is optional: a fetch failure just yields whatever was
gathered (manual entry always works). Sources, in priority order:

1. **RO-Crate** — ``ro-crate-metadata.json`` at the repo root (the "RO-Crate like"
   part): the root data entity's name/version/description/license/author + a
   workflow entity's ``programmingLanguage`` → engine.
2. **Nextflow** — ``nextflow.config`` ``manifest {}`` block (name/version/
   description/author/homePage).
3. **GitHub API** — repo name/description/homepage/license as a last resort.

Parsing is split from fetching so the parsers stay unit-testable without a network.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

_TIMEOUT = 6

# Workflow engines depictio actually supports (those with brand logos/handling)
# plus python; used to normalise an extracted engine name onto a known value.
# Anything else falls through lower-cased rather than being dropped.
KNOWN_ENGINES = ["nextflow", "snakemake", "galaxy", "python"]


def _github_owner_repo(url: str) -> tuple[str | None, str | None]:
    """(owner, repo) for a github.com URL, else (None, None)."""
    parsed = urlparse(url)
    if "github.com" not in parsed.netloc:
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
    """Extract manifest fields from a Nextflow ``manifest {}`` block. Engine=nextflow."""
    out: dict[str, Any] = {"engine": "nextflow"}
    block_match = re.search(r"manifest\s*\{(.*?)\}", text, re.DOTALL)
    block = block_match.group(1) if block_match else text
    for key, field in (
        ("name", "name"),
        ("version", "version"),
        ("description", "description"),
        ("author", "author"),
        ("homePage", "homepage"),
    ):
        m = re.search(rf"\b{key}\s*=\s*['\"]([^'\"]*)['\"]", block)
        if m and m.group(1):
            out[field] = m.group(1).strip()
    return out


def _http_get(url: str) -> str | None:
    """Best-effort GET returning decoded text, or None on any failure."""
    import urllib.request

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "depictio-project-builder"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 — http(s) only
            if getattr(resp, "status", 200) != 200:
                return None
            return resp.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 — offline / 404 / bad host all fall back to manual entry
        return None


_MAX_LOGO_BYTES = 1_000_000


def _http_get_data_uri(url: str, mime: str = "image/png") -> str | None:
    """Best-effort GET of a small image, returned as a ``data:`` URI (or None).

    Inlining keeps the fetched logo self-contained in the single-file Project Builder and
    avoids the browser making its own cross-origin request."""
    import base64
    import urllib.request

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "depictio-project-builder"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 — http(s) only
            if getattr(resp, "status", 200) != 200:
                return None
            data = resp.read(_MAX_LOGO_BYTES + 1)
            if not data or len(data) > _MAX_LOGO_BYTES:
                return None
            return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    except Exception:  # noqa: BLE001 — best-effort; a missing logo just isn't shown
        return None


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


def fetch_workflow_metadata(url: str) -> dict[str, Any]:
    """Best-effort workflow metadata from a repository URL.

    Returns ``{repository_url, name?, engine?, version?, catalog?, description?,
    author?, license?, homepage?, sources: [...]}``. Never raises on network
    problems — ``sources`` is empty when nothing was found.
    """
    url = (url or "").strip()
    if not url:
        raise ValueError("repository url is required")
    if not re.match(r"^(https?|git)://", url):
        raise ValueError("repository url must start with http(s):// or git://")

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
        crate = _http_get(f"{raw_base}/ro-crate-metadata.json")
        if crate:
            try:
                meta = parse_ro_crate(json.loads(crate))
                if meta:
                    _merge(result, meta)
                    sources.append("ro-crate")
            except (json.JSONDecodeError, ValueError):
                pass

        if any(k not in result for k in ("name", "version", "description", "author", "homepage")):
            config = _http_get(f"{raw_base}/nextflow.config")
            if config:
                _merge(result, parse_nextflow_config(config))
                sources.append("nextflow.config")

    if owner and repo and any(k not in result for k in ("name", "description", "homepage")):
        api = _http_get(f"https://api.github.com/repos/{owner}/{repo}")
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
        light = _http_get_data_uri(f"{raw_base}/docs/images/nf-core-{repo}_logo_light.png")
        dark = _http_get_data_uri(f"{raw_base}/docs/images/nf-core-{repo}_logo_dark.png")
        if light or dark:
            result["logo"] = light or dark
            result["logo_dark"] = dark or light
            sources.append("logo")

    # Descriptions can arrive as raw HTML/Markdown (nf-core's RO-Crate carries the
    # whole README) — reduce to a short plain-text summary for display.
    if result.get("description"):
        result["description"] = _clean_description(result["description"])

    result["sources"] = sources
    return result
