"""The export's brand logo: an external ``logo_url`` goes through the SSRF gateway.

A dashboard may name any ``logo_url``; before the gateway it was fetched with
a raw ``httpx.get``, which made the export a probe for loopback and cloud
metadata addresses. Now it is the same gateway call the text-tile logos use,
and a refusal costs the logo, never the export.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from depictio.api.v1 import remote_fetch
from depictio.api.v1.endpoints.dashboards_endpoints import notebook_export as nbx
from depictio.api.v1.services import branding

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"brand"


@pytest.fixture
def brand_from_url_only(monkeypatch):
    """No stored upload and no live instance theme: only ``logo_url`` can yield a logo."""
    monkeypatch.setattr(branding, "get_effective_brand_theme", lambda *a, **k: None)
    monkeypatch.setattr(branding, "read_logo_asset", lambda key: None)


def _brand(logo_url: str) -> dict:
    return nbx._resolve_export_brand("dash-id", {"logo_mode": "custom", "logo_url": logo_url})


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.169.254"])
def test_an_internal_logo_url_is_not_fetched(brand_from_url_only, monkeypatch, host):
    # The real gateway, with no ambient allowlist that could let loopback or
    # the cloud metadata endpoint through; any request that slipped past the
    # validation would hit this guard and fail the test.
    for var in (
        "DEPICTIO_REMOTE_URL_ALLOWLIST",
        "DEPICTIO_REMOTE_URL_DENYLIST",
        "DEPICTIO_REMOTE_ALLOW_HTTP",
    ):
        monkeypatch.delenv(var, raising=False)

    def _no_requests(self, request, **kwargs):
        raise AssertionError(f"the export dialled {host} itself")

    monkeypatch.setattr(httpx.Client, "send", _no_requests)
    brand = _brand(f"https://{host}/logo.png")
    assert "logo_data_uri" not in brand
    # The refusal costs the logo, never the export.
    assert brand["app_name"] == "Depictio"


def test_an_allowed_url_still_embeds_the_logo(brand_from_url_only, monkeypatch):
    calls = []

    def _fake_fetch(url, *, max_bytes=None, timeout=None):
        calls.append((url, max_bytes))
        return PNG_BYTES

    monkeypatch.setattr(remote_fetch, "fetch_validated_bytes", _fake_fetch)
    brand = _brand("https://cdn.example.com/logo.png")
    assert calls == [("https://cdn.example.com/logo.png", nbx._MAX_BRAND_LOGO_BYTES)]
    uri = brand["logo_data_uri"]
    assert uri.startswith("data:image/png;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]) == PNG_BYTES


def test_bytes_that_are_not_an_image_are_not_embedded(brand_from_url_only, monkeypatch):
    monkeypatch.setattr(
        remote_fetch, "fetch_validated_bytes", lambda url, **kwargs: b"<html>not an image</html>"
    )
    brand = _brand("https://cdn.example.com/logo.png")
    assert "logo_data_uri" not in brand
