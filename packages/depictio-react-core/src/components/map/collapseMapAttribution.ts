/**
 * Collapse a Plotly map's basemap credit to its ⓘ affordance.
 *
 * plotly.js builds every map subplot with its own
 * `AttributionControl({ compact: true })` and injects maplibre's stylesheet at
 * runtime, so the compact presentation — a small ⓘ that expands the credit on
 * click — is already implemented and already styled. What is broken is only
 * *when* maplibre applies it:
 *
 *  - `onAdd` runs `_updateAttributions()` before any source has loaded, so the
 *    control is marked `*-attrib-empty` and `_updateCompact()` leaves it alone.
 *  - The credit arrives later, on `styledata` / `sourcedata`.
 *    `_updateAttributions()` then fills it in, drops `*-attrib-empty` and calls
 *    `_updateCompact()`, which adds `*-compact` **and** `*-compact-show` —
 *    i.e. expanded, the full "© OpenStreetMap contributors © CARTO" line across
 *    the bottom of the map.
 *  - Nothing minimizes it after that except the map's first `drag`.
 *
 * Both of those land after Plotly's own lifecycle hooks have run — the control
 * does not even exist in the DOM yet when `onInitialized` / `onAfterPlot` fire
 * — so a one-shot pass from there always finds nothing. Hence two observers:
 * one to notice the control appear, one to notice the credit land in it. The
 * control is then put into exactly the state `_updateCompactMinimize` would
 * have left it in, which is the one neither path reaches on its own.
 * Everything after that (expanding on click, keyboard access via the
 * `<summary>`, the styling) is maplibre's own code, untouched.
 *
 * Watching *content* rather than classes is what keeps the ⓘ working:
 * `_toggleAttribution` expands by adding `*-compact-show` and nothing else, so
 * a viewer's click leaves the credit text alone and goes unnoticed here. Only
 * maplibre rewriting the credit re-collapses it.
 *
 * Idempotent, and safe to call at any point in the plot's life. Covers both
 * class prefixes: `map`/`scattermap` subplots render through maplibre, the
 * older `mapbox`/`scattermapbox` ones through mapbox-gl.
 */

const CONTROL_SELECTOR = '.maplibregl-ctrl-attrib, .mapboxgl-ctrl-attrib';

/** Controls already being watched, and roots already being scanned, so repeated
 *  lifecycle hooks on the same plot don't stack observers. Weak so a torn-down
 *  map takes its entries with it. */
const watched = new WeakSet<HTMLElement>();
const scanning = new WeakSet<HTMLElement>();

export function collapseMapAttribution(root: HTMLElement | null | undefined): void {
  if (!root) return;
  watchControlsIn(root);
  if (scanning.has(root)) return;
  scanning.add(root);
  // The control arrives with the maplibre map, some time after the plot is
  // "done", and Plotly builds a fresh one every time it re-creates the map
  // subplot — so this stays for the life of the plot rather than stopping at
  // the first find. It only wakes for added nodes that *are* a control, which
  // keeps it out of the way of the constant SVG churn from hovering and
  // zooming.
  new MutationObserver((records) => {
    if (records.some(addsControl)) watchControlsIn(root);
  }).observe(root, { childList: true, subtree: true });
}

function addsControl(record: MutationRecord): boolean {
  for (const node of record.addedNodes) {
    if (!(node instanceof HTMLElement)) continue;
    if (node.matches(CONTROL_SELECTOR) || node.querySelector(CONTROL_SELECTOR)) return true;
  }
  return false;
}

/** Collapse every control under `root`, and watch each one for the credit
 *  landing in it later. */
function watchControlsIn(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>(CONTROL_SELECTOR).forEach((el) => {
    collapse(el);
    if (watched.has(el)) return;
    watched.add(el);
    // Scoped to the control, not to the plot: the only thing worth reacting to
    // is maplibre writing the credit into it.
    new MutationObserver(() => collapse(el)).observe(el, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  });
}

function collapse(el: HTMLElement): void {
  const prefix = el.classList.contains('mapboxgl-ctrl-attrib') ? 'mapboxgl' : 'maplibregl';
  // An empty credit stays untouched: `*-attrib-empty` is maplibre's own
  // "nothing to show" marker, and collapsing it would leave a bare ⓘ over a
  // control with nothing behind it.
  if (el.classList.contains(`${prefix}-attrib-empty`)) return;
  el.classList.add(`${prefix}-compact`);
  // The credit is hidden by `.{prefix}-compact .{prefix}-ctrl-attrib-inner
  // { display: none }` losing to `.{prefix}-compact-show ... { display: block }`
  // — so dropping `compact-show` is the whole collapse.
  el.classList.remove(`${prefix}-compact-show`);
  // maplibre pairs its collapsed state with `open` on the `<details>`; the
  // disclosure state is not what hides the credit, and leaving `open` off would
  // additionally hide the ⓘ's own expand click.
  if (!el.hasAttribute('open')) el.setAttribute('open', '');
}
