"""The rendered report in a browser: what opens folded, and what opens it.

Renders the seeded ampliseq family with Quarto (``--no-execute``: the
structure and the fold script, not the API's figures) and drives it in
headless Chromium. Skipped where Quarto or Playwright's Chromium is missing
(``QUARTO_PATH`` and ``DEPICTIO_TEST_CHROMIUM`` point at other copies).
"""

from __future__ import annotations

import os
import subprocess

import pytest

from depictio.api.v1.services.notebook_export.generator import (
    DCPlan,
    ExportPlan,
    generate_qmd,
)
from depictio.api.v1.services.notebook_export.render import quarto_binary
from depictio.models.models.analysis_state import AnalysisState

pytestmark = pytest.mark.skipif(quarto_binary() is None, reason="Quarto is not installed")


def _plan(tabs) -> ExportPlan:
    dc_ids = sorted(
        {str(m.get("dc_id")) for t in tabs for m in t["stored_metadata"] if m.get("dc_id")}
    )
    main = next(t for t in tabs if t.get("is_main_tab"))
    state = AnalysisState.model_validate({"context": {"dashboard_id": str(main["dashboard_id"])}})
    return ExportPlan(
        tabs=tabs,
        project=None,
        state=state,
        dcs=[DCPlan(dc_id=d, tag=f"dc_{i}") for i, d in enumerate(dc_ids)],
        stages=[],
        title="nf-core/ampliseq",
    )


@pytest.fixture(scope="module")
def report(tmp_path_factory, ampliseq_tabs):
    folder = tmp_path_factory.mktemp("report")
    qmd = folder / "ampliseq.qmd"
    qmd.write_text(generate_qmd(_plan(ampliseq_tabs)))
    proc = subprocess.run(
        [str(quarto_binary()), "render", str(qmd), "--no-execute"],
        cwd=folder,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return folder / "ampliseq.html"


@pytest.fixture(scope="module")
def page(report):
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        try:
            # A Chromium other than the one this Playwright pins, when set.
            exe = os.environ.get("DEPICTIO_TEST_CHROMIUM") or None
            browser = pw.chromium.launch(executable_path=exe)
        except Exception as exc:  # noqa: BLE001 - no browser here
            pytest.skip(f"Chromium is not available: {exc}")
        pg = browser.new_page(viewport={"width": 1400, "height": 900})
        pg.goto(report.as_uri())
        pg.wait_for_selector(".dpx-tab-all")
        yield pg
        browser.close()


def _tab(page, anchor: str):
    return page.locator(f"section#{anchor} > h3")


def _shown(page, anchor: str) -> bool:
    return page.evaluate(
        "(id) => getComputedStyle(document.querySelector(`section#${id} > .dpx-body`)).display"
        " !== 'none'",
        anchor,
    )


def test_the_first_tab_is_open_and_the_others_folded(page):
    assert _shown(page, "tab-overview")
    for anchor in ("tab-multiqc", "tab-phylogeny", "tab-environment-ctd"):
        assert not _shown(page, anchor), anchor
        assert "dpx-folded" in (_tab(page, anchor).get_attribute("class") or "")


def test_the_filters_are_one_folded_line(page):
    h = page.locator("h2:has(span[data-dpx-kind='filters'])")
    assert "dpx-folded" in (h.get_attribute("class") or "")
    assert h.locator(".dpx-h-note").inner_text() == "none active"


def test_a_text_tiles_headings_stay_out_of_the_contents(page):
    toc = page.locator("#TOC").inner_text()
    assert "Data & QC" not in toc and "About this dashboard" not in toc
    assert "How to read this dashboard" in toc


def test_a_tabs_expand_all_opens_it_and_every_section(page):
    tab = _tab(page, "tab-multiqc")
    button = tab.locator(".dpx-tab-all")
    assert button.inner_text() == "Expand all"
    revealed = page.evaluate(
        "() => { window.__revealed = 0;"
        " document.addEventListener('dpx:reveal', () => { window.__revealed += 1; });"
        " return true; }"
    )
    assert revealed
    button.click()
    assert _shown(page, "tab-multiqc")
    folded = page.evaluate(
        "() => [...document.querySelectorAll('section#tab-multiqc .dpx-h.dpx-folded')].length"
    )
    assert folded == 0
    assert button.inner_text() == "Collapse all"
    assert page.evaluate("() => window.__revealed") >= 1
    button.click()
    assert _shown(page, "tab-multiqc")  # the tab stays, its sections fold
    assert button.inner_text() == "Expand all"


def test_a_link_into_a_folded_tab_opens_it(page):
    assert not _shown(page, "tab-phylogeny")
    page.locator("#TOC a[href='#tab-phylogeny']").first.click()
    assert _shown(page, "tab-phylogeny")
