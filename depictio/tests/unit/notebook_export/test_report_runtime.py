"""The generator as a host of the static runtime (``ExportPlan.embed_runtime``).

With the option on, every tile the runtime could draw is wrapped in a
placeholder that keeps the export's own output inside as its fallback, the
"Filters" part gets the dashboard's controls, and ONE cell at the end inlines
the runtime and the manifest. With it off, the document is the notebook it
always was.
"""

from __future__ import annotations

import re
from dataclasses import replace

import httpx
import pytest

from depictio.api.v1.services.notebook_export.generator import NotebookBuilder, generate_qmd
from depictio.notebook.client import DepictioClient
from depictio.notebook.report_runtime import (
    CONFIG_ID,
    FALLBACK_CLASS,
    FILTERS_ATTR,
    MANIFEST_ID,
    RUNTIME_ATTR,
    RUNTIME_DEFERRED_ENV,
    TILE_ATTR,
    json_script,
    raw_html_block,
    runtime_parts,
    tile_close,
    tile_open,
)

from .test_generator import PENGUINS_DASHBOARD, assert_defined_before_use, penguins_plan

TILE_OPEN_RE = re.compile(r'^::: \{\.depictio-tile data-depictio-tile="([^"]+)"\}$', re.M)


def _components(tabs):
    for tab in tabs:
        for meta in tab.get("stored_metadata") or []:
            yield str(tab["dashboard_id"]), meta


def test_off_by_default_the_document_is_unchanged(penguins_tabs):
    plan = penguins_plan(penguins_tabs)
    assert plan.embed_runtime is False
    src = generate_qmd(plan)
    # The runtime itself is not embedded: no manifest, no filter panels, no
    # report_runtime call. The tile markers stay — every report carries them
    # for the report editor's live preview (contract #1457, §2); their
    # placeholders keep the tiles' own output as the fallback either way.
    assert MANIFEST_ID not in src and FILTERS_ATTR not in src
    assert "report_runtime" not in src
    assert TILE_OPEN_RE.search(src)


def test_every_drawable_tile_gets_one_placeholder_with_its_fallback(penguins_tabs):
    plan = replace(penguins_plan(penguins_tabs), embed_runtime=True)
    src = generate_qmd(plan)
    refs = [ref for group in TILE_OPEN_RE.findall(src) for ref in group.split()]
    expected = {
        f"{tab}:{meta['index']}"
        for tab, meta in _components(penguins_tabs)
        if meta.get("component_type") not in ("text", "highlight", "interactive")
    }
    # Interactive controls are drawn by the filter panel, not as tiles; the
    # generator lays out no tile for them either.
    assert set(refs) == expected
    assert len(refs) == len(set(refs)), "a tile is placed twice"
    # Each placeholder opens on its fallback and closes both divs.
    assert src.count(tile_open(["x"]).split("\n")[1]) == len(TILE_OPEN_RE.findall(src))
    assert src.count(tile_close()) == len(TILE_OPEN_RE.findall(src))
    # Text tiles stay the document's own prose.
    for tab, meta in _components(penguins_tabs):
        if meta.get("component_type") == "text":
            assert f"{tab}:{meta['index']}" not in refs


def test_cards_of_a_row_share_one_placeholder(penguins_tabs):
    plan = replace(penguins_plan(penguins_tabs), embed_runtime=True)
    src = generate_qmd(plan)
    groups = [g.split() for g in TILE_OPEN_RE.findall(src)]
    rows = [g for g in groups if len(g) > 1]
    assert rows, "the penguins dashboard has a card strip"
    for row in rows:
        start = src.index(" ".join(row))
        end = src.index(tile_close(), start)
        assert "card_row([" in src[start:end]


def test_the_runtime_is_inlined_once_at_the_end(penguins_tabs):
    plan = replace(penguins_plan(penguins_tabs), embed_runtime=True)
    src = generate_qmd(plan)
    assert src.count("client.report_runtime(") == 1
    last_tile = src.rindex(tile_close())
    call = src.index("client.report_runtime(")
    assert call > last_tile, "the runtime must come after every tile it mounts"
    # Only the closing part (methods and citations) follows it; the footer is
    # the page's, outside the document body.
    assert "{#methods}" not in src or src.index("{#methods}") > call
    # The entry tab is the one the state was captured on.
    assert f"client.report_runtime({PENGUINS_DASHBOARD!r}, depictio_state" in src
    # Still a valid notebook: every name read is defined first, once.
    assert_defined_before_use(src)


def test_the_filters_part_gets_the_controls_once(penguins_tabs):
    plan = replace(penguins_plan(penguins_tabs), embed_runtime=True)
    src = generate_qmd(plan)
    assert src.count(f'{FILTERS_ATTR}="{PENGUINS_DASHBOARD}"') == 1
    assert src.index(FILTERS_ATTR) < src.index("Results")


def test_the_runtime_takes_the_report_look(penguins_tabs):
    plan = replace(
        penguins_plan(penguins_tabs),
        embed_runtime=True,
        brand={"primary": "teal", "font_family": "Lato"},
    )
    config = NotebookBuilder(plan).runtime_config()
    assert config["brand"]["primary"] == "#12b886"  # teal 6, the report's accent
    assert config["brand"]["font_family"].startswith("'Inter Variable', Inter, Lato")
    classic = NotebookBuilder(replace(plan, theme="classic")).runtime_config()
    assert classic["brand"] == {"primary": "teal", "font_family": "Lato"}


# ---------------------------------------------------------------------------
# The markup
# ---------------------------------------------------------------------------


def _block(**kw) -> str:
    data, code = runtime_parts(**kw)
    return data + code


def test_compose_puts_everything_once_and_in_order():
    html = _block(
        js="run()",
        css=".a{}",
        manifest={"x": "</script><!--"},
        config={"brand": None},
        addons='<script data-depictio-addon="3dmol">m()</script>',
    )
    for needle in (f'id="{MANIFEST_ID}"', f'id="{CONFIG_ID}"', f'{RUNTIME_ATTR}="js"'):
        assert html.count(needle) == 1
    assert html.index(MANIFEST_ID) < html.index("3dmol") < html.index(f'{RUNTIME_ATTR}="js"')
    # The stylesheet is inert text: never applied to the page as written.
    assert f'<script type="text/plain" {RUNTIME_ATTR}="css">.a{{}}</script>' in html
    # The manifest cannot close its element, or open a comment state.
    manifest_el = html[html.index(MANIFEST_ID) : html.index("</script>", html.index(MANIFEST_ID))]
    assert "</script" not in manifest_el[1:] and "<!--" not in manifest_el


def test_scripts_are_neutralised_inside_inline_elements():
    html = _block(js='a="</script>";b="<!--"', css="x{content:'</script>'}", manifest={})
    body = html[html.index(f'{RUNTIME_ATTR}="js">') :]
    assert body.count("</script>") == 1  # the element's own end tag only
    css = html[html.index(f'{RUNTIME_ATTR}="css">') :]
    assert css.index("</script>") > css.index("content")  # its own end tag, after the text
    assert json_script("i", {"v": float("nan")}).endswith('{"v":null}</script>')


def test_raw_block_fence_outruns_the_content():
    block = raw_html_block("<p>````</p>")
    assert block.strip().startswith("`````{=html}") and block.strip().endswith("`````")
    assert raw_html_block("") == ""


def test_placeholder_markup_is_pandoc_fenced_divs():
    opened = tile_open(["t:1", "t:2"])
    assert opened.splitlines() == [
        f'::: {{.depictio-tile {TILE_ATTR}="t:1 t:2"}}',
        f"::: {{.{FALLBACK_CLASS}}}",
    ]


# ---------------------------------------------------------------------------
# The client: a reader's own render
# ---------------------------------------------------------------------------


def _client(handler) -> DepictioClient:
    return DepictioClient("http://depictio.test", "tok", transport=httpx.MockTransport(handler))


def test_the_client_composes_the_block_from_the_api(monkeypatch):
    monkeypatch.delenv(RUNTIME_DEFERRED_ENV, raising=False)
    monkeypatch.setattr("time.sleep", lambda s: None)
    seen: list[str] = []
    polls = iter([{"status": "running"}])

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}?{request.url.query.decode()}")
        if request.url.path.endswith("/serverless/report-manifest/d1"):
            return httpx.Response(202, json={"job_id": "j1", "status": "queued"})
        if request.url.path.endswith("/serverless/report-manifest/job/j1"):
            ready = {
                "status": "ready",
                "manifest": {"manifest_version": 1, "addons": [{"name": "3dmol"}]},
            }
            return httpx.Response(200, json=next(polls, ready))
        if request.url.path.endswith("/serverless/report-runtime"):
            return httpx.Response(
                200,
                json={"js": "run()", "css": ".a{}", "addons": {"3dmol": "<script>m()</script>"}},
            )
        return httpx.Response(404)

    block = _client(handler).report_runtime("d1", {"filters": []})
    assert block.strip().startswith("```{=html}")
    assert block.count(MANIFEST_ID) == 1 and "<script>m()</script>" in block
    # The report alone: its config has no `combined` section.
    assert '<script type="application/json" id="depictio-report-config">{}</script>' in block
    assert seen == [
        "POST /depictio/api/v1/serverless/report-manifest/d1?",
        "GET /depictio/api/v1/serverless/report-manifest/job/j1?",
        "GET /depictio/api/v1/serverless/report-manifest/job/j1?",
        "GET /depictio/api/v1/serverless/report-runtime?addons=3dmol",
    ]


@pytest.mark.parametrize("status", [403, 404, 409, 503])
def test_the_client_prints_nothing_when_the_api_says_no(monkeypatch, status):
    monkeypatch.delenv(RUNTIME_DEFERRED_ENV, raising=False)
    client = _client(lambda request: httpx.Response(status, json={"detail": "no"}))
    assert client.report_runtime("d1", {"filters": []}) == ""


def test_a_failed_manifest_job_prints_nothing(monkeypatch):
    monkeypatch.delenv(RUNTIME_DEFERRED_ENV, raising=False)
    monkeypatch.setattr("time.sleep", lambda s: None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": "j1", "status": "queued"})
        return httpx.Response(413, json={"detail": "over the ceiling"})

    assert _client(handler).report_runtime("d1", {"filters": []}) == ""


def test_a_worker_render_never_asks_the_api(monkeypatch):
    """The worker embeds the runtime itself, after the render."""
    monkeypatch.setenv(RUNTIME_DEFERRED_ENV, "1")

    def handler(request):  # pragma: no cover - must not be reached
        raise AssertionError("the API must not be asked")

    assert _client(handler).report_runtime("d1") == ""


def test_a_child_tab_with_its_own_filters_gets_its_panel(penguins_tabs):
    """The Filters part holds the entry tab's controls; a child tab's own are
    drawn in that tab's part, so they can be set from the report too."""
    tabs = [dict(t) for t in penguins_tabs]
    child = next(t for t in tabs if str(t["dashboard_id"]) != PENGUINS_DASHBOARD)
    child["stored_metadata"] = [
        *child.get("stored_metadata", []),
        {
            "index": "child-island",
            "component_type": "interactive",
            "interactive_component_type": "MultiSelect",
            "column_name": "island",
        },
    ]
    src = generate_qmd(replace(penguins_plan(tabs), embed_runtime=True))
    child_id = str(child["dashboard_id"])
    assert src.count(f'{FILTERS_ATTR}="{child_id}"') == 1
    # In the child tab's part: after its heading.
    heading = src.index(f'data-depictio-tab="{child_id}"')
    assert src.index(f'{FILTERS_ATTR}="{child_id}"') > heading
    # Not without the runtime, and not for a tab without filters of its own.
    assert FILTERS_ATTR not in generate_qmd(penguins_plan(tabs))
    bare = [dict(t) for t in penguins_tabs]
    for t in bare:
        if str(t["dashboard_id"]) != PENGUINS_DASHBOARD:
            t["stored_metadata"] = [
                m for m in t.get("stored_metadata", []) if m.get("component_type") != "interactive"
            ]
    src = generate_qmd(replace(penguins_plan(bare), embed_runtime=True))
    assert src.count(FILTERS_ATTR) == 1


def test_a_static_render_embeds_no_runtime(monkeypatch):
    """The PDF render runs no script: the runtime block is not printed at all."""
    monkeypatch.delenv(RUNTIME_DEFERRED_ENV, raising=False)
    monkeypatch.setenv("DEPICTIO_STATIC_FIGURES", "1")

    def handler(request):  # pragma: no cover - must not be reached
        raise AssertionError("the API must not be asked")

    assert _client(handler).report_runtime("d") == ""
