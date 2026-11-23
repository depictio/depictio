"""The DOM markers every report carries for the editor's live preview (#1457).

The generator writes them as pandoc fenced divs with attributes
(PREVIEW_CONTRACT.md §2); pandoc's typst writer drops the attributes, so the
PDF keeps its own layout while the HTML report gives the editor every part of
the document to patch in the browser (``assets/preview_patch.js``, §3). Pinned
here: every element is marked exactly once, a report without a layer and one
with both carry them, a poisoned tab id or section title cannot break out of
its attribute, the fences nest the way pandoc reads them, and the patch
script answers every message of the protocol.
"""

from __future__ import annotations

import copy
import html
import re
from dataclasses import replace
from pathlib import Path

from depictio.api.v1.services.notebook_export.generator import (
    NotebookBuilder,
    generate_qmd,
)
from depictio.api.v1.services.notebook_export.reading_order import MarkdownUnit

from .test_generator import PENGUINS_DASHBOARD, penguins_plan

# The markers as the .qmd writes them. The fence lengths are the nesting: a
# closing fence pops the innermost div it is at least as long as.
PART_RE = re.compile(r'^:::::: \{data-depictio-part="([^"]+)"\}$', re.M)
TAB_DIV_RE = re.compile(r'^::::: \{data-depictio-tab="([^"]+)"\}$', re.M)
SECTION_RE = re.compile(r'^:::: \{data-depictio-section="([^"]+)"\}$', re.M)
TILE_OPEN_RE = re.compile(r'^::: \{\.depictio-tile data-depictio-tile="([^"]+)"\}$', re.M)
FLOAT_OPEN_RE = re.compile(r"^::: \{#(?:fig|tbl)-", re.M)
CAPTION_RE = re.compile(r"\[[^\]]*\]\{data-depictio-caption=\"\"\}")
FENCE_LINE_RE = re.compile(r"^(::+) *(\{.*\})? *$")

PATCH_JS = (
    Path(__file__).resolve().parents[3]
    / "api"
    / "v1"
    / "services"
    / "notebook_export"
    / "assets"
    / "preview_patch.js"
)


def _components(tabs):
    for tab in tabs:
        for meta in tab.get("stored_metadata") or []:
            yield str(tab["dashboard_id"]), meta


def _tile_refs(src: str) -> list[str]:
    return [ref for group in TILE_OPEN_RE.findall(src) for ref in group.split()]


def _sections(tabs) -> list[MarkdownUnit]:
    plan = penguins_plan(tabs)
    return [
        entry
        for entry, _ in NotebookBuilder(plan).entries()
        if isinstance(entry, MarkdownUnit) and entry.kind == "section"
    ]


def _assert_fences_balanced(src: str) -> None:
    """Pandoc's own reading of the divs: every closing fence pops the innermost
    open div it is at least as long as, and none is left open at the end."""
    stack: list[int] = []
    for line in src.splitlines():
        fence = FENCE_LINE_RE.match(line)
        if not fence:
            continue
        if fence.group(2):  # attributes: the fence opens a div
            stack.append(len(fence.group(1)))
        else:  # bare: the fence closes the innermost div
            assert stack, f"a closing fence with nothing open: {line!r}"
            assert stack[-1] <= len(fence.group(1)), (
                f"a {stack[-1]}-colon div is closed by {len(fence.group(1))}: {line!r}"
            )
            stack.pop()
    assert not stack, f"{len(stack)} div(s) never close"


# ---------------------------------------------------------------------------
# Every element, exactly once
# ---------------------------------------------------------------------------


def test_every_element_is_marked_once(penguins_tabs):
    src = generate_qmd(penguins_plan(penguins_tabs))
    # The three parts, always present — empty when there is no text — and in
    # this order: the intro, the conclusion, then the appendix.
    assert PART_RE.findall(src) == ["intro", "conclusion", "appendix"]
    # One div per tab, carrying the tab's dashboard id; the tab's heading holds
    # the same mark inline, so the page counts one more per tab.
    ids = [str(tab["dashboard_id"]) for tab in penguins_tabs]
    assert sorted(TAB_DIV_RE.findall(src)) == sorted(ids)
    assert src.count("data-depictio-tab=") == 2 * len(ids)
    # One div per section of the reading order, valued "<tab id>:<title>".
    sections = _sections(penguins_tabs)
    assert sections, "the penguins dashboard has sections"
    assert len(SECTION_RE.findall(src)) == len(sections)
    # The tiles: the runtime's own marker, in every report — with or without
    # the runtime — and only where a tile is laid out.
    expected = {
        f"{tab}:{meta['index']}"
        for tab, meta in _components(penguins_tabs)
        if meta.get("component_type") not in ("text", "highlight", "interactive")
    }
    assert set(_tile_refs(src)) == expected
    assert len(_tile_refs(src)) == len(set(_tile_refs(src))), "a tile is marked twice"
    # Every captioned tile (a #fig-/#tbl- float) marks its caption, once.
    floats = FLOAT_OPEN_RE.findall(src)
    assert floats, "the penguins dashboard has captioned tiles"
    assert len(CAPTION_RE.findall(src)) == len(floats)
    # And the whole document still nests the way pandoc reads it.
    _assert_fences_balanced(src)


# ---------------------------------------------------------------------------
# The layer changes the content, never the markers
# ---------------------------------------------------------------------------


def _prose(text: str) -> dict:
    """One paragraph of TipTap JSON, the viewer's rich text."""
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _layered_plan(tabs):
    main = next(tab for tab in tabs if str(tab["dashboard_id"]) == PENGUINS_DASHBOARD)
    child = next(tab for tab in tabs if str(tab["dashboard_id"]) != PENGUINS_DASHBOARD)
    # A figure: the layer's caption lands on the float's caption marker, and a
    # figure is a tile the report numbers (a card would carry no caption).
    tile = next(meta for meta in main["stored_metadata"] if meta.get("component_type") == "figure")
    return replace(
        penguins_plan(tabs),
        report_layer={
            "intro": _prose("A layered introduction."),
            "conclusion": _prose("A layered conclusion."),
            "tiles": [
                {
                    "tab_id": PENGUINS_DASHBOARD,
                    "component_id": str(tile["index"]),
                    "caption": "A layered caption.",
                    "in_pdf": False,
                    "orientation": "landscape",
                }
            ],
            "tabs": [{"tab_id": str(child["dashboard_id"]), "placement": "appendix", "order": 1}],
        },
    )


def test_a_layered_report_keeps_the_markers(penguins_tabs):
    plain = generate_qmd(penguins_plan(penguins_tabs))
    src = generate_qmd(_layered_plan(penguins_tabs))
    # The layer rewords and re-places the report's content; the markers stay,
    # one per element, so the editor can still find and patch every one.
    assert PART_RE.findall(src) == ["intro", "conclusion", "appendix"]
    assert sorted(TAB_DIV_RE.findall(src)) == sorted(TAB_DIV_RE.findall(plain))
    assert len(SECTION_RE.findall(src)) == len(SECTION_RE.findall(plain))
    assert sorted(_tile_refs(src)) == sorted(_tile_refs(plain))
    assert len(CAPTION_RE.findall(src)) == len(CAPTION_RE.findall(plain))
    _assert_fences_balanced(src)
    # The layer's prose sits inside the intro and the conclusion parts...
    intro = src.index('data-depictio-part="intro"')
    conclusion = src.index('data-depictio-part="conclusion"')
    appendix = src.index('data-depictio-part="appendix"')
    assert "A layered introduction." in src[intro:conclusion]
    assert "A layered conclusion." in src[conclusion:appendix]
    # ...the layer's caption inside the tile's caption marker...
    assert re.search(r"\[[^\]]*A layered caption\.[^\]]*\]\{data-depictio-caption=\"\"\}", src)
    # ...and the tab the layer sends to the appendix inside the appendix part.
    child_id = next(
        str(tab["dashboard_id"])
        for tab in penguins_tabs
        if str(tab["dashboard_id"]) != PENGUINS_DASHBOARD
    )
    assert TAB_DIV_RE.findall(src[appendix:]) == [child_id]


# ---------------------------------------------------------------------------
# A poisoned id or title cannot break out of its attribute
# ---------------------------------------------------------------------------


def test_poisoned_values_stay_in_their_attributes(penguins_tabs):
    tabs = copy.deepcopy(penguins_tabs)
    child = next(tab for tab in tabs if str(tab["dashboard_id"]) != PENGUINS_DASHBOARD)
    poison = 'x"onmouseover="alert(1)"><script>{`b`}'
    child["dashboard_id"] = poison
    section = 'Evil "quoted" <b>section</b> {`braces`}'
    child["stored_metadata"] = [dict(meta, section=section) for meta in child["stored_metadata"]]
    src = generate_qmd(penguins_plan(tabs))
    # The tab's own mark round-trips: the attribute holds the id as HTML
    # entities — no raw quote, tag or brace for the browser to read — and
    # unescaping it gives the id back, not a mangled one.
    tab_values = TAB_DIV_RE.findall(src)
    assert poison in [html.unescape(value) for value in tab_values]
    raw = next(value for value in tab_values if html.unescape(value) == poison)
    assert "&lt;script&gt;" in raw and "&#123;" in raw and "&#96;" in raw
    # The section's mark: "<tab id>:<title>", the same entities, round-trip.
    section_values = [html.unescape(value) for value in SECTION_RE.findall(src)]
    assert f"{poison}:{section}" in section_values
    # The tile markers keep naming their tile: the poisoned id, escaped the
    # same way, still one marker per tile of that tab.
    expected = {
        f"{tab}:{meta['index']}"
        for tab, meta in _components(tabs)
        if meta.get("component_type") not in ("text", "highlight", "interactive")
    }
    assert {html.unescape(ref) for ref in _tile_refs(src)} == expected
    _assert_fences_balanced(src)


# ---------------------------------------------------------------------------
# The patch script (§3)
# ---------------------------------------------------------------------------


def test_the_patch_script_answers_every_message_of_the_protocol():
    js = PATCH_JS.read_text()
    for message in (
        "depictio-preview:ready",
        "depictio-preview:select",
        "depictio-preview:thumbnail",
        "depictio-preview:apply",
        "depictio-preview:thumbnails",
        "depictio-preview:snapshot",
        "depictio-preview:styles",
        "depictio-preview:scheme",
    ):
        assert message in js, f"the patch script never handles {message}"
    # The marks of §3's effects, spelled as the contract writes them.
    for effect in ("HTML only", "Landscape in PDF", "Portrait in PDF", "Page break"):
        assert effect in js
    # No storage, no network: the frame is an opaque-origin sandbox.
    assert "localStorage" not in js and "fetch(" not in js


def test_prose_tiles_carry_their_own_marker_the_runtime_ignores(penguins_tabs):
    """A text tile is narrative, never mounted by the runtime (which reads
    ``data-depictio-tile``), but the editor's preview must still hide and move
    it: it carries ``data-depictio-prose`` instead, once."""
    src = generate_qmd(penguins_plan(penguins_tabs))
    texts = {
        f"{tab}:{meta['index']}"
        for tab, meta in _components(penguins_tabs)
        if meta.get("component_type") == "text" and meta.get("index")
    }
    assert texts, "the penguins dashboard has text tiles"
    prose = re.findall(r'data-depictio-prose="([^"]+)"', src)
    assert sorted(html.unescape(p) for p in prose) == sorted(texts)
    assert not texts & set(_tile_refs(src))
    _assert_fences_balanced(src)
    assert "[data-depictio-prose]" in PATCH_JS.read_text()
