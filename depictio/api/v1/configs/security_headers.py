"""The baseline security headers every API response carries.

Lives apart from ``depictio.api.main`` so a route can build a variant of the
policy without importing the app module that imports the routers.

A third copy of the policy is the nginx ``add_header`` line in
``docker-images/nginx.conf.template`` (the viewer container). Both are asserted
to agree in ``depictio/tests/api/v1/test_security_headers.py``.
"""

from __future__ import annotations

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    # CSP: the React SPA bundle requires its own assets only; ag-grid / Mantine
    # ship CSS-in-JS so 'unsafe-inline' is required for style-src. WebSockets to
    # the same origin are needed for the realtime events stream.
    #
    # 'unsafe-eval' is required for WebGL: Plotly draws `scattergl` / `scatter3d`
    # through regl, which compiles each draw command at runtime via the Function
    # constructor (`Function.apply(null, ...)` in the vendor-plotly chunk).
    # Without it every gl trace throws EvalError at first draw, so Volcano,
    # Manhattan, DotPlot, QQ, Lollipop and Embedding render nothing. The Vite
    # dev server only appears to work because it sends no CSP at all.
    # 'wasm-unsafe-eval' covers the Pyodide runtime behind figure Code Mode.
    #
    # connect-src also has to name the basemap CDNs, because maplibre fetches a
    # map's style, glyphs, sprite and vector tiles with fetch/XHR rather than as
    # images — `img-src https:` does not cover them. Without these a map
    # component renders its legend over blank white and logs "Style is not done
    # loading". The three styles Depictio offers (see MAP_STYLES in
    # depictio/models/components/constants.py) resolve to:
    #   carto-positron / carto-darkmatter → basemaps.cartocdn.com (style.json),
    #     which in turn points at tiles.basemaps.cartocdn.com (glyphs, sprite,
    #     TileJSON) and tiles-{a,b,c,d}.basemaps.cartocdn.com (the .mvt tiles)
    #   open-street-map → tile.openstreetmap.org
    # The bare apex is listed separately: a `*.` wildcard does not match it.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' ws: wss: "
        "https://basemaps.cartocdn.com https://*.basemaps.cartocdn.com "
        "https://tile.openstreetmap.org; "
        "frame-ancestors 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}


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
