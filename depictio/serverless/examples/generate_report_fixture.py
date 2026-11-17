"""Regenerate the report skeleton the report-runtime demo and e2e spec mount into.

A rendered report is a Quarto page whose tiles the notebook generator wrapped
in placeholders (``depictio/notebook/report_runtime.py``); Quarto turns each
``::: {.depictio-tile data-depictio-tile="<tab>:<index>"}`` fenced div into a
``<div>`` of that class and attribute, with the cell it holds (the tile's own
output) inside ``.depictio-fallback``. This script writes that DOM for the
penguins demo manifest (``depictio/viewer/demo/manifests/penguins.json``),
without Quarto, so the JS-only CI jobs can mount the runtime into a report:

* one placeholder per tile of the entry tab (the two cards share one, as the
  generator folds a card strip), each with a recognisable fallback;
* one placeholder naming a component the manifest does not hold, whose
  fallback must stay;
* the "Filters" part's panel placeholder;
* a host stylesheet the runtime must not restyle;
* the tab's heading, marked with its dashboard tab (``data-depictio-tab``), in
  its Quarto section, and the copy of that mark Quarto puts in the contents
  list (``nav#TOC``), first in the document as on a rendered page;
* the ``<!--DEPICTIO_REPORT_RUNTIME-->`` token where the producer's block goes
  (the demo build and the e2e helper replace it).

    DEPICTIO_CONTEXT=cli ./venv/bin/python \\
        depictio/serverless/examples/generate_report_fixture.py

``test_report_fixture.py`` fails when the committed file drifts from this.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from depictio.notebook.report_runtime import (
    FALLBACK_CLASS,
    TILE_ATTR,
    TILE_CLASS,
    filters_placeholder,
    tile_ref,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPO_ROOT / "depictio" / "viewer" / "demo" / "manifests" / "penguins.json"
OUT = REPO_ROOT / "depictio" / "viewer" / "demo" / "reports" / "penguins.html"
TOKEN = "<!--DEPICTIO_REPORT_RUNTIME-->"
MISSING = "not-in-the-manifest"
TAB_ANCHOR = "tab-species-analysis"

# Quarto's own page, reduced to what a guest could break: a serif body in a
# colour of its own, paragraph margins, a heading style.
HOST_STYLE = """
body { font-family: Georgia, "Times New Roman", serif; color: rgb(33, 37, 41);
  background: rgb(255, 255, 255); margin: 0; }
main { max-width: 1100px; margin: 0 auto; padding: 1rem 2rem; }
p { margin: 0 0 1rem; line-height: 1.6; }
h1, h2, h3 { font-family: Georgia, serif; color: rgb(52, 58, 64); }
.cell-output-display { border: 1px dashed rgb(173, 181, 189); padding: 0.75rem; }
#TOC { position: absolute; top: 0; right: 0; width: 180px; font-size: 0.8rem; }
""".strip()


def _tile(refs: list[str], titles: list[str]) -> str:
    fallback = "".join(
        f'<p data-fallback="{escape(r.split(":", 1)[1])}">The export\'s own output for '
        f"<strong>{escape(t)}</strong>.</p>"
        for r, t in zip(refs, titles, strict=True)
    )
    return (
        f'<div class="{TILE_CLASS}" {TILE_ATTR}="{escape(" ".join(refs))}">\n'
        f'<div class="{FALLBACK_CLASS}">\n'
        f'<div class="cell"><div class="cell-output-display">{fallback}</div></div>\n'
        "</div>\n</div>"
    )


def build() -> str:
    manifest = json.loads(MANIFEST.read_text())
    tab = manifest["dashboard"]["id"]
    comps = manifest["dashboard"]["doc"]["stored_metadata"]
    cards = [c for c in comps if c.get("component_type") == "card"]
    others = [c for c in comps if c.get("component_type") not in ("card", "text", "interactive")]

    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8" />',
        "<title>Penguins report (fixture)</title>",
        f"<style>\n{HOST_STYLE}\n</style>",
        "</head>",
        "<body>",
        # Quarto copies a heading's markup into the contents list, mark and all.
        f'<nav id="TOC" role="doc-toc"><ul><li><a href="#{TAB_ANCHOR}">'
        f'<span data-depictio-tab="{escape(tab)}"></span>Species analysis</a></li></ul></nav>',
        '<main id="quarto-document-content">',
        "<h1>Penguins report</h1>",
        '<p class="host-probe">A paragraph of the report itself, styled by the host page.</p>',
        "<h2>Filters</h2>",
        "<p>Stage 1, Species: Adelie.</p>",
        filters_placeholder(tab),
        "<h2>Results</h2>",
        f'<section id="{TAB_ANCHOR}" class="level3">',
        f'<h3><span data-depictio-tab="{escape(tab)}"></span>Species analysis</h3>',
        _tile([tile_ref(tab, c["index"]) for c in cards], [c.get("title", "") for c in cards]),
    ]
    for c in others:
        parts.append(_tile([tile_ref(tab, c["index"])], [c.get("title") or c["index"]]))
    parts.append(_tile([tile_ref(tab, MISSING)], ["a tile the manifest does not hold"]))
    parts += ["</section>", TOKEN, "</main>", "</body>", "</html>", ""]
    return "\n".join(parts)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build())
    print(f"wrote {OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
