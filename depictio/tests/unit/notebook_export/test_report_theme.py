"""The HTML report's theme layers and controls, as the exported ``.qmd`` carries them."""

from __future__ import annotations

import re

import yaml

from depictio.api.v1.services.notebook_export.generator import (
    DCPlan,
    ExportPlan,
    generate_qmd,
)
from depictio.api.v1.services.notebook_export.report_chrome import (
    DARK_CSS,
    about_callout,
    about_callout_many,
    appbar_html,
)
from depictio.api.v1.services.notebook_export.report_theme import (
    CHROME_CSS,
    CHROME_JS,
    QUARTO_TESTED,
    SCHEME_TOGGLE,
    brand_rules,
)
from depictio.models.models.analysis_state import AnalysisState


def _split(src: str) -> tuple[dict, str]:
    head, body = src.split("\n---\n", 1)
    return yaml.safe_load(head.removeprefix("---\n")), body


def _plan(tabs, **extra) -> ExportPlan:
    dc_ids = sorted(
        {str(m.get("dc_id")) for t in tabs for m in t["stored_metadata"] if m.get("dc_id")}
    )
    state = AnalysisState.model_validate(
        {"context": {"dashboard_id": str(tabs[0]["dashboard_id"])}}
    )
    return ExportPlan(
        tabs=tabs,
        project=None,
        state=state,
        dcs=[DCPlan(dc_id=d, tag=f"dc_{i}") for i, d in enumerate(dc_ids)],
        stages=[],
        title="nf-core/ampliseq",
        **extra,
    )


# ── Brand and its SCSS rules layer ──────────────────────────────────────────


def test_each_scheme_brand_carries_its_rules_layer(ampliseq_tabs):
    front, _ = _split(generate_qmd(_plan(ampliseq_tabs)))
    html = front["format"]["html"]
    assert html["respect-user-color-scheme"] is True
    light = front["brand"]["light"]["defaults"]["bootstrap"]
    dark = front["brand"]["dark"]["defaults"]["bootstrap"]
    assert "--gl-fg: #212529" in light["rules"] and "--gl-fg: #c9c9c9" in dark["rules"]
    # Written against Bootstrap's variables, compiled per scheme by Quarto.
    assert "$body-bg" in light["rules"] and "$border-radius-sm" in dark["rules"]
    # Quarto variables beside the colours: the callout's edge.
    assert light["defaults"]["callout-border-width"] == "3px"


def test_the_dark_tokens_live_in_the_dark_brand_only():
    # No `body.quarto-dark` copy of the tokens left in the page's CSS.
    assert "--gl-fg:" not in DARK_CSS
    assert brand_rules("dark").startswith("html:root {")
    assert "--dpx-info: #38d9a9" in brand_rules("dark")


def test_the_chrome_layers_go_through_quartos_includes(ampliseq_tabs):
    front, body = _split(generate_qmd(_plan(ampliseq_tabs)))
    html = front["format"]["html"]
    header = " ".join(h["text"] for h in html["include-in-header"])
    assert 'name="depictio-report-chrome"' in header and QUARTO_TESTED in header
    assert CHROME_JS in html["include-after-body"]["text"]
    # Neither is inlined in the body as well.
    assert "dpx-toc-toggle" not in body


def test_the_quarto_dom_layer_is_one_named_block():
    css = CHROME_CSS
    assert css.count("Quarto DOM layer") == 1
    layer = css.split("Quarto DOM layer", 1)[1]
    # Everything that names Quarto's markup is below the marker.
    head = css.split("Quarto DOM layer", 1)[0]
    for hook in ("#TOC", "#toc-title", "#quarto-margin-sidebar", ".anchorjs-link"):
        assert hook in layer, hook
        assert hook not in head, hook
    # Heading anchors right after the text, the heading's actions after them.
    assert ".anchorjs-link {{ order: 1".replace("{{", "{") in layer
    assert ".dpx-all { order: 3; }" in layer


# ── The colour-scheme button ───────────────────────────────────────────────


def test_the_scheme_toggle_is_an_icon_button_on_quartos_hook(ampliseq_tabs):
    front, _ = _split(generate_qmd(_plan(ampliseq_tabs)))
    bar = front["format"]["html"]["include-before-body"]["text"]
    assert SCHEME_TOGGLE in bar
    assert 'class="quarto-color-scheme-toggle dpx-scheme-toggle"' in SCHEME_TOGGLE
    assert 'aria-label="Switch to dark theme"' in SCHEME_TOGGLE
    assert "dpx-icon-moon" in SCHEME_TOGGLE and "dpx-icon-sun" in SCHEME_TOGGLE
    # The script calls Quarto's own toggle, it does not re-implement it.
    assert "window.quartoToggleColorScheme()" in CHROME_JS


def test_the_classic_look_has_no_scheme_toggle(ampliseq_tabs):
    front, _ = _split(generate_qmd(_plan(ampliseq_tabs, theme="classic")))
    assert "brand" not in front
    assert "dpx-scheme-toggle" not in front["format"]["html"]["include-before-body"]["text"]
    bar = appbar_html(title="x", logo=None, logo_dark=None, accent="#000", has_mark=False)
    assert "dpx-scheme-toggle" not in bar


# ── "About this component" and its "i" ─────────────────────────────────────


def test_an_about_note_names_its_component():
    note = about_callout("Median per sample.", name='The "box"')
    assert '.callout-note .dpx-about collapse="true"' in note
    assert '::: {.dpx-about-item data-dpx-name="The  box"}' in note
    assert about_callout("", name="x") == ""


def test_a_card_rows_note_gives_each_described_card_its_own_item():
    note = about_callout_many(
        [
            ("Samples", "In the sheet.", "kf-samples"),
            ("Phyla", "", "kf-phyla"),
            ("Reads", "Kept.", "kf-reads"),
        ]
    )
    items = re.findall(
        r'\{\.dpx-about-item data-dpx-name="([^"]+)" data-dpx-index="([^"]+)"\}', note
    )
    # Only the cards with text get an "i".
    assert items == [("Samples", "kf-samples"), ("Reads", "kf-reads")]
    assert about_callout_many([("A", "", "a")]) == ""


def test_info_items_only_where_a_description_exists(ampliseq_tabs):
    _, body = _split(generate_qmd(_plan(ampliseq_tabs)))
    described = {
        str(m["index"])
        for t in ampliseq_tabs
        for m in t["stored_metadata"]
        if str(m.get("description") or "").strip()
        and m.get("component_type") not in ("text", "interactive")
    }
    blank = {
        str(m["index"])
        for t in ampliseq_tabs
        for m in t["stored_metadata"]
        if not str(m.get("description") or "").strip() and m.get("component_type") == "card"
    }
    indexed = set(re.findall(r'data-dpx-index="([^"]+)"', body))
    assert indexed and indexed <= described
    assert not indexed & blank
    # Every note is wired to the page's "i" through its items.
    notes = body.count(".callout-note .dpx-about")
    assert notes and body.count("{.dpx-about-item") >= notes


def test_the_contents_title_no_longer_folds_on_its_own(ampliseq_tabs):
    _, body = _split(generate_qmd(_plan(ampliseq_tabs)))
    # One control for the list as a whole: the theme's button.
    assert "head.classList.toggle('dpx-folded')" not in body
    assert "depictio-report:toc-collapsed" in CHROME_JS
