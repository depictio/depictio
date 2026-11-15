"""``resolve_icons`` bakes Iconify glyphs into inline SVG, or degrades to none.

The bundled subset (the viewer's own, as JSON) answers first and needs no
network; only a miss is asked of the Iconify API, and only a success is
remembered.
"""

from __future__ import annotations

import httpx
import pytest

from depictio.api.v1.services import icons as icons_module
from depictio.api.v1.services.icons import resolve_icons


@pytest.fixture(autouse=True)
def _no_subset_and_no_cache(monkeypatch, tmp_path):
    # Network tests run against an empty subset, and a fetched icon from one
    # test must not leak into the next.
    monkeypatch.setattr(icons_module, "SUBSET_PATH", tmp_path / "missing.json")
    icons_module._fetched.clear()
    icons_module._load_subset.cache_clear()
    yield
    icons_module._fetched.clear()
    icons_module._load_subset.cache_clear()


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


def test_the_bundled_subset_answers_without_the_network(monkeypatch, tmp_path):
    import json

    subset = tmp_path / "icon-subset.json"
    subset.write_text(
        json.dumps({"mdi:flask": {"body": "<path d='F'/>", "width": 24, "height": 24}})
    )
    monkeypatch.setattr(icons_module, "SUBSET_PATH", subset)

    def no_network(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("asked Iconify for a bundled icon")

    monkeypatch.setattr(icons_module.httpx, "get", no_network)
    out = resolve_icons(["mdi:flask"])
    assert "<path d='F'/>" in out["mdi:flask"]
    assert resolve_icons(["mdi:other"], network=False) == {}


def test_a_failure_is_not_cached(monkeypatch):
    state = {"up": False}

    def flaky(url: str, params: dict, timeout: float):
        if not state["up"]:
            raise httpx.ConnectError("blip")
        return httpx.Response(
            200,
            json={"icons": {"counter": {"body": "<path/>"}}},
            request=httpx.Request("GET", url, params=params),
        )

    monkeypatch.setattr(icons_module.httpx, "get", flaky)
    assert resolve_icons(["mdi:counter"]) == {}
    state["up"] = True
    assert set(resolve_icons(["mdi:counter"])) == {"mdi:counter"}


def test_the_fallback_has_one_time_budget_for_all_misses(monkeypatch):
    import time

    def slow(url: str, params: dict, timeout: float):
        time.sleep(0.5)
        raise httpx.ConnectError("slow")

    monkeypatch.setattr(icons_module.httpx, "get", slow)
    monkeypatch.setattr(icons_module, "FALLBACK_BUDGET_S", 0.2)
    started = time.monotonic()
    assert resolve_icons([f"mdi:i{n}" for n in range(30)]) == {}
    assert time.monotonic() - started < 1.0


def test_the_shipped_subset_covers_the_exports_own_icons():
    """When the viewer has been built, its subset carries every icon the export draws."""
    from depictio.api.v1.services.notebook_export import generator, provenance

    path = icons_module.Path(__file__).resolve().parents[2] / "viewer/dist-icons/icon-subset.json"
    if not path.exists():
        pytest.skip("viewer icon subset not built (pnpm --filter depictio-viewer icons)")
    import json

    subset = json.loads(path.read_text())
    for icon in (
        generator.RESULTS_ICON,
        generator.FILTERS_ICON,
        generator.SUMMARY_ICON,
        generator.FUNNEL_ICON,
        provenance.PROVENANCE_ICON,
        provenance.EXPORT_DETAILS_ICON,
    ):
        assert icon in subset, icon
