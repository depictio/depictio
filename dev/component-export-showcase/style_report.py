"""Append control-deck styles to report.css."""

from pathlib import Path

STYLES = """

/* ---- Filter deck ---------------------------------------------------------
 *
 * Two columns, deliberately symmetric: the embedded Depictio control on the
 * left and this site's own controls on the right, so a reader can see that the
 * two paths are alternatives rather than a pipeline. The frame is given a fixed
 * height because an iframe has no intrinsic one and would otherwise collapse.
 */
.deck-controls {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1.75rem;
  margin: 2.5rem 0 1rem;
  padding: 1.5rem;
  background: #f7f5f1;
  border: 1px solid var(--rule, #d8d4cc);
  border-radius: 2px;
}

.control-col h3 {
  margin: 0 0 .35rem;
  font-family: 'Inter Tight', system-ui, sans-serif;
  font-size: .82rem;
  font-weight: 600;
  letter-spacing: .04em;
  text-transform: uppercase;
  color: #4a4a44;
}

.control-note {
  margin: 0 0 .9rem;
  font-size: .84rem;
  line-height: 1.5;
  color: #5f5f57;
}

.control-frame {
  width: 100%;
  height: 132px;
  border: 1px solid var(--rule, #d8d4cc);
  border-radius: 2px;
  background: #fff;
}

.native-field {
  display: block;
  margin-bottom: .85rem;
}

.native-label {
  display: block;
  font-family: 'Inter Tight', system-ui, sans-serif;
  font-size: .72rem;
  letter-spacing: .05em;
  text-transform: uppercase;
  color: #6a6a62;
  margin-bottom: .25rem;
}

.native-field select {
  width: 100%;
  padding: .45rem .6rem;
  font-family: 'Inter Tight', system-ui, sans-serif;
  font-size: .88rem;
  color: #1a1a18;
  background: #fff;
  border: 1px solid #c8c4bc;
  border-radius: 2px;
}

.native-range {
  display: flex;
  align-items: center;
  gap: .7rem;
}
.native-range input[type="range"] { flex: 1; accent-color: #2f4858; }
.native-range output {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: .78rem;
  color: #4a4a44;
  min-width: 5.5ch;
}

/* Active filters read as a sentence about the current view, so a reader who
 * scrolled past the controls still knows what they are looking at. */
.active-filters {
  display: flex;
  flex-wrap: wrap;
  gap: .5rem;
  align-items: center;
  margin: 0 0 2rem;
  min-height: 1.6rem;
  font-size: .85rem;
}
.filter-empty { color: #8a8a80; font-style: italic; }
.filter-chip {
  padding: .2rem .6rem;
  background: #2f4858;
  color: #fff;
  border-radius: 999px;
  font-family: 'Inter Tight', system-ui, sans-serif;
  font-size: .78rem;
}
.filter-chip strong { font-weight: 600; opacity: .75; margin-right: .3rem; }

.fig-req { margin-top: .6rem; }
"""

path = Path(__file__).parent / "site" / "report.css"
path.write_text(path.read_text() + STYLES)
print(f"report.css now {len(path.read_text().splitlines())} lines")
