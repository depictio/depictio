"""A text tile's remote header logo travels inside the bundle."""

from __future__ import annotations

import base64

import pytest

from depictio.serverless import producer_a

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def test_remote_logo_becomes_a_data_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    def fetch(url, *, max_bytes=None, timeout=None):
        seen.append((url, max_bytes))
        return PNG

    monkeypatch.setattr("depictio.api.v1.remote_fetch.fetch_validated_bytes", fetch)
    comp = {"logo": "https://example.org/logo.png", "logo_dark": "/local/logo.png"}
    producer_a.inline_text_logos(comp)
    assert comp["logo"] == "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert comp["logo_dark"] == "/local/logo.png"  # not remote: untouched
    assert seen == [("https://example.org/logo.png", producer_a.MAX_INLINE_LOGO_BYTES)]


def test_a_failed_or_non_image_fetch_keeps_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(url, **_):
        raise RuntimeError("private address")

    monkeypatch.setattr("depictio.api.v1.remote_fetch.fetch_validated_bytes", refuse)
    comp = {"logo": "https://10.0.0.1/logo.png"}
    producer_a.inline_text_logos(comp)
    assert comp["logo"] == "https://10.0.0.1/logo.png"

    monkeypatch.setattr(
        "depictio.api.v1.remote_fetch.fetch_validated_bytes", lambda url, **_: b"<html>"
    )
    comp = {"logo": "https://example.org/page"}
    producer_a.inline_text_logos(comp)
    assert comp["logo"] == "https://example.org/page"


def test_svg_is_recognised() -> None:
    assert producer_a._image_mime(b'<?xml version="1.0"?>\n<svg xmlns="x"/>') == "image/svg+xml"
