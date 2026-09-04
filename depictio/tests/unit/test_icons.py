"""``resolve_icons`` bakes Iconify glyphs into inline SVG, or degrades to none.

A dashboard author picks icons from thousands of Iconify ids; the backend
resolves the handful used by a given export once and hands back real SVG
markup, so a notebook/Quarto export can render the same icon the SPA shows
without a browser or a bundled icon set.
"""

from __future__ import annotations

import httpx
import pytest

from depictio.api.v1.services import icons as icons_module
from depictio.api.v1.services.icons import resolve_icons


@pytest.fixture(autouse=True)
def _clear_icon_cache():
    # _fetch_icon_svg is process-cached; a monkeypatched httpx.get from one
    # test must not leak a cached result into the next.
    icons_module._fetch_icon_svg.cache_clear()
    yield
    icons_module._fetch_icon_svg.cache_clear()


def _fake_get(icons_by_name: dict[str, dict]):
    def get(url: str, params: dict, timeout: float):
        name = params["icons"]
        icon = icons_by_name.get(name)
        return httpx.Response(
            200,
            json={"icons": {name: icon} if icon else {}},
            request=httpx.Request("GET", url, params=params),
        )

    return get


def test_resolves_a_known_icon_to_inline_svg(monkeypatch):
    monkeypatch.setattr(
        icons_module.httpx,
        "get",
        _fake_get({"chart-donut": {"body": '<path d="M0 0"/>', "width": 24, "height": 24}}),
    )

    out = resolve_icons(["mdi:chart-donut"])

    assert out.keys() == {"mdi:chart-donut"}
    svg = out["mdi:chart-donut"]
    assert svg.startswith("<svg")
    assert '<path d="M0 0"/>' in svg
    # currentColor + em sizing: the caller colours/sizes it via CSS.
    assert 'fill="currentColor"' in svg
    assert 'width="1em" height="1em"' in svg


def test_unresolvable_and_blank_ids_are_silently_omitted(monkeypatch):
    monkeypatch.setattr(icons_module.httpx, "get", _fake_get({}))

    out = resolve_icons(["mdi:does-not-exist", None, "", "no-prefix-no-colon"])

    assert out == {}


def test_network_failure_degrades_to_no_icon_rather_than_raising(monkeypatch):
    def raise_get(url: str, params: dict, timeout: float):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(icons_module.httpx, "get", raise_get)

    out = resolve_icons(["mdi:chart-donut"])

    assert out == {}


def test_duplicate_ids_are_deduplicated_to_one_fetch(monkeypatch):
    calls: list[str] = []

    def get(url: str, params: dict, timeout: float):
        calls.append(params["icons"])
        return httpx.Response(
            200,
            json={"icons": {"counter": {"body": "<path/>", "width": 24, "height": 24}}},
            request=httpx.Request("GET", url, params=params),
        )

    monkeypatch.setattr(icons_module.httpx, "get", get)

    out = resolve_icons(["mdi:counter", "mdi:counter", "mdi:counter"])

    assert len(calls) == 1
    assert set(out) == {"mdi:counter"}
