"""The parts of Quarto's HTML output the report's chrome relies on.

``report_theme`` customises the report through Quarto's supported extension
points, plus one small layer that names Quarto's own markup (the contents, the
anchors, the colour-scheme toggle, the code-tools button). This renders a tiny
report with the Quarto on ``PATH`` (``QUARTO_PATH`` for another copy) and
asserts every one of those hooks is still there, so a Quarto upgrade that
renames one fails here rather than in a reader's browser. Skipped where Quarto
is missing; the browser half also needs Playwright's Chromium
(``DEPICTIO_TEST_CHROMIUM`` for another copy).
"""

from __future__ import annotations

import os
import re
import subprocess
from urllib.parse import unquote

import pytest
import yaml

from depictio.api.v1.services.notebook_export.quarto import (
    QuartoFrontMatter,
    paper_brand,
    paper_brand_dark,
)
from depictio.api.v1.services.notebook_export.render import quarto_binary, quarto_version
from depictio.api.v1.services.notebook_export.report_chrome import about_callout, appbar_html
from depictio.api.v1.services.notebook_export.report_theme import (
    BRAND_DEFAULTS,
    CHROME_CSS,
    CHROME_JS,
    QUARTO_TESTED,
    brand_rules,
)

pytestmark = pytest.mark.skipif(quarto_binary() is None, reason="Quarto is not installed")


def _document() -> str:
    fm = QuartoFrontMatter(
        title="Hooks",
        subtitle="What the chrome needs from Quarto",
        before_body=appbar_html(
            title=None,
            logo=None,
            logo_dark=None,
            accent="#228be6",
            has_mark=False,
            scheme_toggle=True,
        ),
        brand=paper_brand(
            primary="#1c7ed6", rules=brand_rules("light"), extra_defaults=BRAND_DEFAULTS
        ),
        brand_dark=paper_brand_dark(
            primary="#1c7ed6", rules=brand_rules("dark"), extra_defaults=BRAND_DEFAULTS
        ),
    )
    meta = yaml.safe_load(fm.to_yaml())
    # No code here: the markdown engine, so no kernel is needed.
    meta.pop("jupyter", None)
    meta.pop("execute", None)
    meta["engine"] = "markdown"
    about = about_callout("The demo tile. How to read: it is a box.", name="Demo")
    body = f"""
{CHROME_CSS}
{CHROME_JS}

## Results

### A tab {{#tab-a}}

#### A section

::: {{#fig-demo}}

::: {{.depictio-tile data-depictio-tile="tab:demo"}}
A tile.
:::

**Demo**.

:::

{about}
"""
    return "---\n" + yaml.safe_dump(meta, sort_keys=False) + "---\n" + body


def _stylesheets(html: str) -> str:
    """Every stylesheet of a self-contained page, as text (Quarto inlines
    them as ``data:text/css,`` links)."""
    return "\n".join(unquote(m) for m in re.findall(r'href="data:text/css,([^"]*)"', html))


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    folder = tmp_path_factory.mktemp("hooks")
    (folder / "hooks.qmd").write_text(_document())
    proc = subprocess.run(
        [str(quarto_binary()), "render", "hooks.qmd", "--to", "html"],
        cwd=folder,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return folder / "hooks.html"


def test_quarto_version_is_reported():
    # Not a gate: the layer names the version it was checked against, and a
    # different one only means this file is the place to look first.
    assert re.match(r"\d+\.\d+", QUARTO_TESTED)
    assert quarto_version()


def test_the_colour_scheme_hooks_exist(rendered):
    html = rendered.read_text()
    # Quarto's global toggle, and its script keeping every toggle in step.
    assert "window.quartoToggleColorScheme" in html
    assert "querySelectorAll('.quarto-color-scheme-toggle')" in html
    # It floats its own switch only when the page has none: ours is one.
    assert ".quarto-color-scheme-toggle') === null" in html
    assert 'class="quarto-color-scheme-toggle dpx-scheme-toggle"' in html
    # The two schemes are two stylesheets, and the body carries the class.
    assert "quarto-color-alternate" in html and "quarto-dark" in html


def test_the_brand_rules_layer_is_compiled_per_scheme(rendered):
    html = _stylesheets(rendered.read_text())
    # One token per scheme, from each brand's own rules layer.
    assert re.search(r"--dpx-info:\s*#0ca678", html)
    assert re.search(r"--dpx-info:\s*#38d9a9", html)
    assert re.search(r"\.dpx-appbar\{position:sticky", html)


def test_the_dom_the_chrome_names_exists(rendered):
    html = rendered.read_text()
    for hook in (
        'id="quarto-margin-sidebar"',
        'id="TOC"',
        'id="toc-title"',
        'id="quarto-code-tools-source"',
        "new window.AnchorJS()",
        "anchorJS.add('.anchored')",
        "quarto-float-caption",
        'id="fig-demo"',
    ):
        assert hook in html, hook
    # The rules Quarto ships for the anchors the chrome moves.
    assert ".quarto-figure>.anchorjs-link" in _stylesheets(html)


def test_the_chrome_in_a_browser(rendered):
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        try:
            exe = os.environ.get("DEPICTIO_TEST_CHROMIUM") or None
            browser = pw.chromium.launch(executable_path=exe)
        except Exception as exc:  # noqa: BLE001 - no browser here
            pytest.skip(f"Chromium is not available: {exc}")
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(rendered.as_uri())
        page.wait_for_selector(".dpx-toc-toggle")
        # Quarto did not float a second switch: ours is the page's toggle.
        assert page.locator(".quarto-color-scheme-toggle").count() == 1
        toggle = page.locator(".dpx-scheme-toggle")
        assert toggle.get_attribute("aria-label") == "Switch to dark theme"
        toggle.click()
        assert "quarto-dark" in (page.locator("body").get_attribute("class") or "")
        assert toggle.get_attribute("aria-label") == "Switch to light theme"
        toggle.click()
        assert "quarto-light" in (page.locator("body").get_attribute("class") or "")
        # The contents fold to their title, and the choice is remembered.
        page.locator(".dpx-toc-toggle").click()
        assert not page.locator("#TOC > ul").is_visible()
        page.reload()
        page.wait_for_selector(".dpx-toc-toggle")
        assert not page.locator("#TOC > ul").is_visible()
        page.locator(".dpx-toc-toggle").click()
        assert page.locator("#TOC > ul").is_visible()
        # The figure's anchor sits in its caption, not over the tile.
        assert page.locator(".quarto-float-caption .anchorjs-link").count() == 1
        # The tile's "i": in its action row, opening the description.
        info = page.locator(".depictio-tile > .dpx-tile-links .dpx-info")
        assert info.get_attribute("aria-label") == "About Demo"
        assert not page.locator(".callout.dpx-about").is_visible()
        info.click()
        pop = page.locator(".dpx-pop")
        assert pop.is_visible() and "it is a box" in pop.inner_text()
        page.keyboard.press("Escape")
        assert pop.count() == 0
        assert not errors, errors
        browser.close()
