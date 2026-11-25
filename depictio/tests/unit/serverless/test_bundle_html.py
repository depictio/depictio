"""The single-file bundle page composed from the static runtime.

``depictio/serverless/bundle_html.py`` builds the page the runtime's one build
(``combined-runtime.js`` + ``.css``) boots as the dashboard App: ``#root``, the
manifest in ``#bundle-manifest``, the add-ons, then the runtime's script. No
built runtime is needed: the tests compose from stand-in script and stylesheet.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser

from depictio.serverless.bundle_html import compose_bundle_html, style_text

MANIFEST = {
    "dashboard": {"title": "Penguins </script><!-- & co"},
    "note": "a</style><script>alert(1)</script><!--",
}
ADDON = '<script data-depictio-addon="3dmol">window.T=1;</script>'


class _Scripts(HTMLParser):
    """The page's elements the way a browser tokenises them."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.scripts: list[tuple[dict[str, str | None], str]] = []
        self.styles: list[str] = []
        self.title = ""
        self._open: list[str] = []
        self._attrs: dict[str, str | None] = {}
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if "id" in d:
            self.ids.append(str(d["id"]))
        if tag in {"script", "style", "title"}:
            self._open.append(tag)
            self._attrs, self._buf = d, ""

    def handle_data(self, data):
        if self._open:
            self._buf += data

    def handle_endtag(self, tag):
        if self._open and self._open[-1] == tag:
            self._open.pop()
            if tag == "script":
                self.scripts.append((self._attrs, self._buf))
            elif tag == "style":
                self.styles.append(self._buf)
            else:
                self.title = self._buf


def _compose(**kw) -> str:
    args = {"js": "window.__rt=1;", "css": "body{margin:0}", "addons": ADDON, **kw}
    return compose_bundle_html(MANIFEST, **args)


def test_the_page_holds_root_manifest_addons_then_the_runtime() -> None:
    html = _compose()
    page = _Scripts()
    page.feed(html)
    assert "root" in page.ids and "bundle-manifest" in page.ids
    assert html.index('<div id="root"></div>') < html.index('id="bundle-manifest"')
    # The manifest survives extraction and parses back to the same value.
    attrs, body = next(s for s in page.scripts if s[0].get("id") == "bundle-manifest")
    assert attrs["type"] == "application/json"
    assert json.loads(body) == MANIFEST
    # Add-ons first: their globals must exist when the runtime runs.
    assert html.index("data-depictio-addon") < html.index("window.__rt=1;")
    assert html.index('id="bundle-manifest"') < html.index("data-depictio-addon")
    assert page.scripts[-1][1] == "window.__rt=1;"
    assert page.styles == ["body{margin:0}"]
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert 'charset="UTF-8"' in html and "color-scheme" in html and "viewport" in html


def test_nothing_in_the_inputs_can_close_or_wedge_open_its_element() -> None:
    html = _compose(
        js='var a="</script><script>x</script>"; var b="<!--";',
        css="a::after{content:'</style><b>'}",
    )
    page = _Scripts()
    page.feed(html)
    # One runtime script, one manifest, one add-on: no stray element appeared.
    assert [a.get("id") or a.get("data-depictio-addon") for a, _ in page.scripts] == [
        "bundle-manifest",
        "3dmol",
        None,
    ]
    assert len(page.styles) == 1
    # The manifest's own `</script>` is escaped inside its JSON strings.
    body = next(b for a, b in page.scripts if a.get("id") == "bundle-manifest")
    assert "</" not in body and "<!--" not in body
    assert json.loads(body)["note"] == MANIFEST["note"]
    # The runtime keeps its meaning: only the separators changed.
    runtime = page.scripts[-1][1]
    assert "</script" not in runtime and "<!--" not in runtime
    assert runtime == 'var a="<\\/script><script>x<\\/script>"; var b="<\\!--";'
    assert "</style" not in page.styles[0].lower()
    assert page.styles[0] == "a::after{content:'<\\/style><b>'}"


def test_the_title_is_the_dashboard_title_escaped() -> None:
    html = _compose(title=MANIFEST["dashboard"]["title"])
    assert "<title>Penguins &lt;/script&gt;&lt;!-- &amp; co</title>" in html
    page = _Scripts()
    page.feed(html)
    assert page.title == MANIFEST["dashboard"]["title"]
    assert "<title>Depictio</title>" in _compose(title="")


def test_style_text_is_case_insensitive() -> None:
    assert not re.search(r"</style", style_text("a</STYLE>b</Style >c"), re.IGNORECASE)
