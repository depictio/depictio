"""Add the two worked examples to the landing page, ahead of the styled demos."""

from pathlib import Path

page = Path(__file__).parent / "site" / "landing.html"
text = page.read_text()

CARDS = """    <a class="card card-lead" href="/example-clean">
      <span class="num">01</span>
      <h2>Example A — everything as JSON</h2>
      <p>
        Benchmarking figures and MultiQC panels, every one fetched as a Plotly
        spec and drawn by the host page. No iframes, no fallbacks. Start here.
      </p>
      <span class="tag">8/8 as a spec · <em>the happy path</em></span>
    </a>

    <a class="card card-lead" href="/example-limited">
      <span class="num">02</span>
      <h2>Example B — where it stops</h2>
      <p>
        A whole dashboard as-is, including the components that cannot be a
        figure. Same code as Example A; the limitations are labelled, not hidden.
      </p>
      <span class="tag">11/14 as a spec · <em>3 framed</em></span>
    </a>

    <a class="card" href="/gallery">
      <span class="num">03</span>
"""

OLD = """    <a class="card" href="/gallery">
      <span class="num">01</span>
"""
assert OLD in text, "gallery card markup moved"
text = text.replace(OLD, CARDS, 1)

# Renumber the remaining cards so the sequence stays honest.
for old, new in (
    (
        'href="/report">\n      <span class="num">02</span>',
        'href="/report">\n      <span class="num">04</span>',
    ),
    (
        'href="/qc">\n      <span class="num">03</span>',
        'href="/qc">\n      <span class="num">05</span>',
    ),
    (
        'href="/versioning">\n      <span class="num">04</span>',
        'href="/versioning">\n      <span class="num">06</span>',
    ),
):
    assert old in text, f"could not renumber: {old!r}"
    text = text.replace(old, new, 1)

page.write_text(text)
print("landing page updated")
