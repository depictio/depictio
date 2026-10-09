"""The shipped Content-Security-Policy, and the two copies of it.

The policy is declared twice: `content_security_policy` in
`depictio/api/v1/configs/security_headers.py` (the API container, which also
serves the SPA) and an
`add_header` line in `docker-images/nginx.conf.template` (the viewer container).
Whichever one served the response, the browser must see the same rules — a
directive present in only one makes a feature work on one container and fail on
the other, which is the hardest kind of "works on my machine" to pin down.

The map component is the reason this is tested rather than trusted. maplibre
fetches a basemap style, its glyphs, sprite and vector tiles over fetch/XHR, so
`connect-src` governs them and `img-src https:` does not. Under the original
`connect-src 'self' ws: wss:` a map rendered its legend over blank white
everywhere except `vite dev`, which sends no CSP at all.

genome_view file tracks fail the same way: GenomeSpy range-reads VCF / BAM /
BigWig straight from S3 through presigned URLs, so `connect-src` must also name
the S3 origin those URLs point at whenever it is not the page's own. The API
derives it from its settings; nginx takes it from `DEPICTIO_CSP_S3_ORIGIN`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from depictio.api.main import _SECURITY_HEADERS
from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.security_headers import (
    build_security_headers,
    content_security_policy,
    csp_with_script_nonce,
    s3_connect_source,
    url_origin,
)
from depictio.models.components.constants import MAP_STYLES

CSP = _SECURITY_HEADERS["Content-Security-Policy"]

DOCKER_IMAGES = Path(__file__).resolve().parents[4] / "docker-images"
NGINX_TEMPLATE = DOCKER_IMAGES / "nginx.conf.template"
VIEWER_DOCKERFILE = DOCKER_IMAGES / "Dockerfile.viewer"

#: The envsubst placeholder nginx fills with the S3 origin.
S3_PLACEHOLDER = "${DEPICTIO_CSP_S3_ORIGIN}"


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
            "in depictio/api/v1/configs/security_headers.py and docker-images/nginx.conf.template, "
            "then map it here."
        )
        sources = _directive(CSP, "connect-src")
        for style, host in hosts.items():
            assert host in sources, f"{style} has no allowed origin"


def test_maplibre_may_start_its_blob_workers() -> None:
    """maplibre parses tiles and markers in workers it starts from blob: URLs.

    Without `worker-src` the browser falls back to `script-src`, which has no
    `blob:`: the style loads, then nothing draws.
    """
    assert "blob:" in _directive(CSP, "worker-src")
    assert "blob:" not in _directive(CSP, "script-src")


def test_indexed_file_readers_may_load_their_inflate_wasm() -> None:
    """@gmod/bgzf-filehandle and @gmod/bbi fetch their WebAssembly from a data: URL.

    Refused, a genome_view file lane loads its index, then reports "Failed to
    fetch" for every VCF, BAM or BigWig read.
    """
    assert "data:" in _directive(CSP, "connect-src")
    assert "'wasm-unsafe-eval'" in _directive(CSP, "script-src")


def _parsed(policy: str) -> dict[str, list[str]]:
    """A policy as {directive: sources}.

    Compares directive by directive rather than as raw strings: the copies are
    formatted differently (a Python implicit concatenation, a single nginx
    line), so whitespace must not decide the verdict.
    """
    out = {}
    for chunk in policy.split(";"):
        parts = chunk.split()
        if parts:
            out[parts[0]] = parts[1:]
    return out


def _nginx_csp(s3_origin: str) -> str:
    """The nginx policy as envsubst renders it with ``DEPICTIO_CSP_S3_ORIGIN``."""
    text = NGINX_TEMPLATE.read_text()
    match = re.search(r'add_header\s+Content-Security-Policy\s+"([^"]+)"\s+always;', text)
    assert match, "no Content-Security-Policy add_header in nginx.conf.template"
    assert S3_PLACEHOLDER in match.group(1), "the nginx CSP lost its S3 origin placeholder"
    return match.group(1).replace(S3_PLACEHOLDER, s3_origin)


class TestNginxMirrorsTheApi:
    def test_policies_are_identical(self) -> None:
        s3_origin = s3_connect_source(settings.s3.external_url, settings.fastapi.external_url)
        assert _parsed(_nginx_csp(s3_origin or "")) == _parsed(CSP)

    def test_empty_origin_renders_the_base_policy(self) -> None:
        """The Dockerfile default (empty) leaves connect-src as it always was."""
        assert _parsed(_nginx_csp("")) == _parsed(content_security_policy())

    def test_origin_lands_in_connect_src(self) -> None:
        origin = "http://127.0.0.1:59102"
        assert _parsed(_nginx_csp(origin)) == _parsed(content_security_policy([origin]))

    def test_every_placeholder_has_a_value(self) -> None:
        """envsubst only replaces variables that are set.

        One the image does not declare stays in the rendered config as
        `${NAME}`, which nginx reads as an unknown variable and refuses to
        start. NGINX_LOCAL_RESOLVERS is exported by the base image entrypoint.
        """
        placeholders = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)\}", NGINX_TEMPLATE.read_text()))
        declared = set(
            re.findall(r"^ENV\s+([A-Z_][A-Z0-9_]*)=", VIEWER_DOCKERFILE.read_text(), re.M)
        )
        assert placeholders - declared - {"NGINX_LOCAL_RESOLVERS"} == set()


class TestS3Origin:
    """Presigned indexed-file URLs are fetched from S3, which 'self' may not cover."""

    def test_cross_origin_s3_is_allowed(self) -> None:
        headers = build_security_headers(
            s3_url="http://127.0.0.1:59102", self_url="http://127.0.0.1:8121"
        )
        sources = _directive(headers["Content-Security-Policy"], "connect-src")
        assert sources == [
            *_directive(content_security_policy(), "connect-src"),
            "http://127.0.0.1:59102",
        ]

    @pytest.mark.parametrize(
        ("s3_url", "self_url"),
        [
            ("https://depictio.example.org", "https://depictio.example.org"),
            # Default port and trailing path do not make a different origin.
            ("https://depictio.example.org:443/s3/", "https://depictio.example.org"),
            # No S3 URL at all.
            ("", "https://depictio.example.org"),
            (None, "https://depictio.example.org"),
        ],
    )
    def test_same_origin_changes_nothing(self, s3_url: str | None, self_url: str) -> None:
        headers = build_security_headers(s3_url=s3_url, self_url=self_url)
        assert headers["Content-Security-Policy"] == content_security_policy()

    @pytest.mark.parametrize(
        ("url", "origin"),
        [
            ("https://s3.embl.de", "https://s3.embl.de"),
            ("https://s3.embl.de/", "https://s3.embl.de"),
            ("https://S3.EMBL.de:443", "https://s3.embl.de"),
            ("http://localhost:80", "http://localhost"),
            ("https://s3.example.com:9443/prefix?x=1", "https://s3.example.com:9443"),
            ("http://user:pw@127.0.0.1:59102", "http://127.0.0.1:59102"),
            ("http://[::1]:9000", "http://[::1]:9000"),
            ("not a url", None),
            ("", None),
        ],
    )
    def test_url_origin(self, url: str, origin: str | None) -> None:
        assert url_origin(url) == origin

    def test_shipped_policy_names_the_presigning_endpoint(self) -> None:
        """The API's own policy follows the URL presigned URLs are signed for."""
        expected = s3_connect_source(settings.s3.external_url, settings.fastapi.external_url)
        sources = _directive(CSP, "connect-src")
        if expected is None:
            assert sources == _directive(content_security_policy(), "connect-src")
        else:
            assert sources[-1] == expected


def test_script_nonce_variant_only_adds_the_nonce():
    """The catalog-preview response relaxes script-src by one nonce, nothing else.

    Its bundle is a single inline `<script type="module">`, which the shipped
    `script-src 'self'` parses and then refuses to run.
    """
    relaxed = csp_with_script_nonce("t3stN0nce")

    assert _directive(relaxed, "script-src") == [
        "'self'",
        "'nonce-t3stN0nce'",
        *_directive(CSP, "script-src")[1:],
    ]
    assert "'unsafe-inline'" not in _directive(relaxed, "script-src")

    for chunk in CSP.split(";"):
        name = chunk.split()[0]
        if name != "script-src":
            assert _directive(relaxed, name) == _directive(CSP, name), (
                f"{name} must be untouched by the nonce variant"
            )
