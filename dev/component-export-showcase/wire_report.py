"""Wire the control deck into report.html."""

from pathlib import Path

page = Path(__file__).parent / "site" / "report.html"
text = page.read_text()

text = text.replace(
    '<link rel="stylesheet" href="/style.css">\n<link rel="stylesheet" href="/report.css">',
    '<link rel="stylesheet" href="/style.css">\n'
    '<link rel="stylesheet" href="/shared.css">\n'
    '<link rel="stylesheet" href="/report.css">',
)
text = text.replace(
    '<script src="/report.js"></script>',
    '<script src="/shared.js"></script>\n<script src="/report.js"></script>',
)

DECK = """  <!-- Two ways to drive the figures below, run side by side against the same
       dashboard: Depictio's own widget in a frame, and controls this site built
       itself from the manifest. Both end at the same `filters=` parameter. -->
  <section class="deck-controls" aria-label="Filter the figures">
    <div class="control-col">
      <h3>Depictio's own control, embedded</h3>
      <p class="control-note">
        The real interactive component served as <code>format=html</code>. It
        posts the selection out to this page, which forwards it to every figure
        on the same data collection.
      </p>
      <div id="embedded-control"></div>
      <div id="embedded-control-req"></div>
    </div>
    <div class="control-col">
      <h3>This site's own controls</h3>
      <p class="control-note">
        Built from the manifest's filter contract, which publishes the column,
        the control kind and the option list. No Depictio code runs here.
      </p>
      <div id="native-controls"></div>
      <div id="native-controls-req"></div>
    </div>
  </section>

  <div id="active-filters" class="active-filters"></div>

"""

ANCHOR = "  <!-- Full-bleed: this figure carries the argument, so it gets the page width. -->"
assert ANCHOR in text, "anchor comment moved"
text = text.replace(ANCHOR, DECK + ANCHOR, 1)

page.write_text(text)
print("report.html wired")
