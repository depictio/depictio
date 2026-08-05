"""The shipped Content-Security-Policy, and the two copies of it.

The policy is declared twice: `SecurityHeadersMiddleware` in
`depictio/api/main.py` (the API container, which also serves the SPA) and an
`add_header` line in `docker-images/nginx.conf.template` (the viewer container).
Whichever one served the response, the browser must see the same rules — a
directive present in only one makes a feature work on one container and fail on
the other, which is the hardest kind of "works on my machine" to pin down.

The map component is the reason this is tested rather than trusted. maplibre
fetches a basemap style, its glyphs, sprite and vector tiles over fetch/XHR, so
`connect-src` governs them and `img-src https:` does not. Under the original
`connect-src 'self' ws: wss:` a map rendered its legend over blank white
everywhere except `vite dev`, which sends no CSP at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from depictio.api.main import _SECURITY_HEADERS
from depictio.models.components.constants import MAP_STYLES

CSP = _SECURITY_HEADERS["Content-Security-Policy"]

NGINX_TEMPLATE = Path(__file__).resolve().parents[4] / "docker-images" / "nginx.conf.template"


def _directive(policy: str, name: str) -> list[str]:
    """The source list of one CSP directive, as tokens."""
    for chunk in policy.split(";"):
        parts = chunk.split()
        if parts and parts[0] == name:
            return parts[1:]
    raise AssertionError(f"CSP has no {name!r} directive: {policy!r}")


class TestBasemapOrigins:
    """`connect-src` has to name every host a basemap style pulls from."""

    @pytest.mark.parametrize(
        "origin",
        [
            # The style document itself.
            "https://basemaps.cartocdn.com",
            # Glyphs, sprite and TileJSON live on tiles.basemaps.cartocdn.com;
            # the .mvt tiles on tiles-{a,b,c,d}.basemaps.cartocdn.com.
            "https://*.basemaps.cartocdn.com",
            # The raster tiles behind the open-street-map style.
            "https://tile.openstreetmap.org",
        ],
    )
    def test_origin_is_allowed(self, origin: str) -> None:
        assert origin in _directive(CSP, "connect-src")

    def test_apex_is_listed_separately_from_the_wildcard(self) -> None:
        """`*.host` does not match `host` in CSP, so both are required."""
        sources = _directive(CSP, "connect-src")
        assert "https://basemaps.cartocdn.com" in sources
        assert "https://*.basemaps.cartocdn.com" in sources

    def test_every_offered_style_has_a_home(self) -> None:
        """A style users can pick must have its host allowed.

        Guards the case where a new entry is added to MAP_STYLES and its CDN is
        never added here — the map would then render blank for that style only.
        """
        hosts = {
            "open-street-map": "https://tile.openstreetmap.org",
            "carto-positron": "https://basemaps.cartocdn.com",
            "carto-darkmatter": "https://basemaps.cartocdn.com",
        }
        assert set(MAP_STYLES) == set(hosts), (
            "MAP_STYLES changed; add the new style's basemap host to the CSP "
            "in depictio/api/main.py and docker-images/nginx.conf.template, "
            "then map it here."
        )
        sources = _directive(CSP, "connect-src")
        for style, host in hosts.items():
            assert host in sources, f"{style} has no allowed origin"


class TestNginxMirrorsTheApi:
    def test_policies_are_identical(self) -> None:
        text = NGINX_TEMPLATE.read_text()
        match = re.search(r'add_header\s+Content-Security-Policy\s+"([^"]+)"\s+always;', text)
        assert match, "no Content-Security-Policy add_header in nginx.conf.template"

        # Compare directive by directive rather than as raw strings: the two are
        # formatted differently (one is a Python implicit concatenation, the
        # other a single nginx line), so whitespace must not decide the verdict.
        def parsed(policy: str) -> dict[str, list[str]]:
            out = {}
            for chunk in policy.split(";"):
                parts = chunk.split()
                if parts:
                    out[parts[0]] = parts[1:]
            return out

        assert parsed(match.group(1)) == parsed(CSP)
