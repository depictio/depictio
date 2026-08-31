"""Shared helpers for the component-export showcase.

Keeps the notebook, the exporter script and the external-site generator reading
the same instance config, so none of them hardcode a port or a token.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOWCASE_DIR = Path(__file__).resolve().parent
EXPORT_DIR = SHOWCASE_DIR / "exports"


def instance_env() -> dict[str, str]:
    """Parse `.env.instance`, the per-worktree port allocation."""
    env: dict[str, str] = {}
    path = REPO_ROOT / ".env.instance"
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def api_base() -> str:
    port = os.environ.get("DEPICTIO_API_PORT") or instance_env().get("FASTAPI_PORT", "8058")
    return f"http://localhost:{port}/depictio/api/v1"


def backend_container() -> str:
    project = instance_env().get("COMPOSE_PROJECT_NAME", "depictio")
    return f"{project}-depictio-backend"


def admin_token() -> str:
    """Read the long-lived admin token straight out of the backend container.

    Same recipe scripts/check_deployment.py documents: the CLI config the API
    writes on bootstrap carries `user.token.access_token`.
    """
    if os.environ.get("DEPICTIO_TOKEN"):
        return os.environ["DEPICTIO_TOKEN"]
    cached = SHOWCASE_DIR / ".token"
    if cached.exists():
        token = cached.read_text().strip()
        if token:
            return token
    raw = subprocess.run(
        ["docker", "exec", backend_container(), "cat", "/app/depictio/.depictio/admin_config.yaml"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for line in raw.splitlines():
        if "access_token:" in line:
            token = line.split("access_token:", 1)[1].strip().strip("'\"")
            cached.write_text(token)
            return token
    raise RuntimeError("no access_token in admin_config.yaml")


def request(
    path: str,
    *,
    token: str | None = None,
    params: dict | None = None,
    raw: bool = False,
    timeout: int = 120,
):
    """GET the API. Returns parsed JSON, or (bytes, headers) when raw."""
    url = f"{api_base()}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            if raw:
                return body, dict(resp.headers)
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise ExportError(exc.code, detail, url) from None


class ExportError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        self.status = status
        self.body = body
        self.url = url
        try:
            parsed = json.loads(body)
            detail = parsed.get("detail", parsed)
        except Exception:
            detail = body[:300]
        self.detail = detail
        super().__init__(f"HTTP {status} on {url}: {detail}")


def list_dashboards(token: str, include_child_tabs: bool = False) -> list[dict]:
    """Dashboards visible to this token.

    ``include_child_tabs`` matters here: the showcase embeds components from
    per-topic tabs ("Community & Diversity", the benchmark demos), and the default
    listing returns only main tabs, so without it those dashboards look absent.
    """
    params = {"include_child_tabs": "true"} if include_child_tabs else None
    return request("/dashboards/list", token=token, params=params)


def dashboards_by_title(token: str) -> dict[str, str]:
    """``{title: dashboard_id}`` for this instance.

    The site pages address dashboards by title rather than by ObjectId. A
    dashboard's id is assigned at import and changes whenever the seed is
    re-imported, so an id baked into a page is correct until someone re-seeds and
    then 404s — which is exactly how the versioning page broke. A title is the
    thing the YAML actually pins.

    Reads ``dashboard_id``, *not* ``_id``. A dashboard document carries both and
    they differ; every route — the export API included — looks a dashboard up by
    ``dashboard_id``, so ``_id`` yields URLs that 404 while looking entirely
    plausible.
    """
    return {
        d["title"]: str(d.get("dashboard_id") or d["_id"])
        for d in list_dashboards(token, include_child_tabs=True)
        if d.get("title")
    }


def manifest(dashboard_id: str, token: str | None = None) -> list[dict]:
    return request(f"/export/dashboards/{dashboard_id}/components", token=token)


def export_json(dashboard_id: str, component_id: str, token: str | None = None, theme="light"):
    return request(
        f"/export/dashboards/{dashboard_id}/components/{component_id}",
        token=token,
        params={"format": "json", "theme": theme},
    )


def export_html(
    dashboard_id: str, component_id: str, token: str | None = None, theme="light"
) -> bytes:
    body, _ = request(
        f"/export/dashboards/{dashboard_id}/components/{component_id}",
        token=token,
        params={"format": "html", "theme": theme},
        raw=True,
    )
    return body


def embed_url(dashboard_id: str, component_id: str, theme: str = "light") -> str:
    """The URL you paste into an `<iframe src>`."""
    return (
        f"{api_base()}/export/dashboards/{dashboard_id}/components/{component_id}"
        f"?format=html&theme={theme}"
    )
