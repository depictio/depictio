"""The baseline security headers every API response carries.

Lives apart from ``depictio.api.main`` so a route can build a variant of the
policy without importing the app module that imports the routers.

A third copy of the policy is the nginx ``add_header`` line in
``docker-images/nginx.conf.template`` (the viewer container). Both are asserted
to agree in ``depictio/tests/api/v1/test_security_headers.py``.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from depictio.api.v1.configs.config import settings

# connect-src before any deployment-specific origin is appended.
#
# connect-src also has to name the basemap CDNs, because maplibre fetches a
# map's style, glyphs, sprite and vector tiles with fetch/XHR rather than as
# images, and `img-src https:` does not cover them. Without these a map
# component renders its legend over blank white and logs "Style is not done
# loading". The three styles Depictio offers (see MAP_STYLES in
# depictio/models/components/constants.py) resolve to:
#   carto-positron / carto-darkmatter → basemaps.cartocdn.com (style.json),
#     which in turn points at tiles.basemaps.cartocdn.com (glyphs, sprite,
#     TileJSON) and tiles-{a,b,c,d}.basemaps.cartocdn.com (the .mvt tiles)
#   open-street-map → tile.openstreetmap.org
# The bare apex is listed separately: a `*.` wildcard does not match it.
_BASE_CONNECT_SRC = (
    "'self' ws: wss: "
    "https://basemaps.cartocdn.com https://*.basemaps.cartocdn.com "
    "https://tile.openstreetmap.org"
)

_DEFAULT_PORTS = {"http": 80, "https": 443}


def url_origin(url: str | None) -> str | None:
    """``scheme://host[:port]`` of ``url``, or ``None`` when it names no host.

    The scheme's default port is dropped, so ``https://s3.example.com:443/``
    and ``https://s3.example.com`` give the same origin. CSP matches a
    host-source without a port on the scheme's default port, so nothing is lost.
    """
    if not url:
        return None
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    # ``hostname`` is lowercased and has userinfo and IPv6 brackets stripped.
    host = parts.hostname
    if not scheme or not host:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    if ":" in host:
        host = f"[{host}]"
    if port is None or port == _DEFAULT_PORTS.get(scheme):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def s3_connect_source(s3_url: str | None, self_url: str | None) -> str | None:
    """The S3 origin ``connect-src`` must name, or ``None`` when 'self' covers it.

    Indexed-file tracks (VCF / BAM / BigWig behind a genome_view tile) are read
    by GenomeSpy straight from storage, through presigned URLs signed against
    ``settings.s3.external_url`` (see ``presign_indexed_file`` in
    ``endpoints/files_endpoints/routes.py``). Those are fetch/XHR range reads,
    so ``connect-src`` governs them; under ``'self'`` alone every read is
    refused and the lane draws empty. ``s3_url`` is that same URL and
    ``self_url`` the origin the page is served from.
    """
    s3_origin = url_origin(s3_url)
    if s3_origin is None or s3_origin == url_origin(self_url):
        return None
    return s3_origin


def content_security_policy(extra_connect_src: Iterable[str] = ()) -> str:
    """The shipped CSP, with ``extra_connect_src`` appended to ``connect-src``.

    The React SPA bundle requires its own assets only; ag-grid / Mantine ship
    CSS-in-JS so 'unsafe-inline' is required for style-src. WebSockets to the
    same origin are needed for the realtime events stream.

    'unsafe-eval' is required for WebGL: Plotly draws `scattergl` / `scatter3d`
    through regl, which compiles each draw command at runtime via the Function
    constructor (`Function.apply(null, ...)` in the vendor-plotly chunk).
    Without it every gl trace throws EvalError at first draw, so Volcano,
    Manhattan, DotPlot, QQ, Lollipop and Embedding render nothing. The Vite
    dev server only appears to work because it sends no CSP at all.
    'wasm-unsafe-eval' covers the Pyodide runtime behind figure Code Mode.

    worker-src: maplibre parses tiles and GeoJSON in Web Workers it starts
    from blob: URLs. Without a worker-src the browser falls back to
    script-src, which has no blob:, so the workers are refused: the style and
    TileJSON load on the main thread, then no tile and no marker ever draws,
    and the map shows its legend over grey.
    """
    connect_src = " ".join((_BASE_CONNECT_SRC, *extra_connect_src))
    return (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; "
        "worker-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data:; "
        f"connect-src {connect_src}; "
        "frame-ancestors 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


def build_security_headers(s3_url: str | None, self_url: str | None) -> dict[str, str]:
    """The baseline headers for a deployment whose browser reaches S3 at ``s3_url``."""
    s3_source = s3_connect_source(s3_url, self_url)
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
        "Content-Security-Policy": content_security_policy([s3_source] if s3_source else []),
    }


# The page this policy guards is served by the API itself (the built SPA), so
# 'self' is the API's browser-facing origin.
SECURITY_HEADERS: dict[str, str] = build_security_headers(
    s3_url=settings.s3.external_url,
    self_url=settings.fastapi.external_url,
)


def csp_with_script_nonce(nonce: str) -> str:
    """The shipped policy with one inline-script nonce added to ``script-src``.

    A response that carries this may run the inline scripts it stamped with the
    same nonce, and nothing else: every other directive is untouched, and the
    nonce is single-use because it is generated per response.

    This exists for the catalog-preview bundle, a `vite-plugin-singlefile` build
    whose entire JS is one inline `<script type="module">`. Under the baseline
    `script-src 'self'` the browser parses that script and refuses to run it, so
    the preview iframe stays blank with a `script-src-elem` violation.
    """
    policy = SECURITY_HEADERS["Content-Security-Policy"]
    return policy.replace("script-src 'self'", f"script-src 'self' 'nonce-{nonce}'", 1)
