import React from 'react';
// `?raw` so the mark is inlined into the DOM rather than loaded as an <img>:
// the per-triangle animation is CSS targeting `#shape-1`…`#shape-7`, and CSS
// cannot reach inside an <img>. Inlining also costs no extra request, which
// matters for the very first paint. Bundled, so it can't 404 on a path change.
import animatedMark from '../assets/animated_favicon.svg?raw';

/**
 * The Depictio mark with its seven triangles pulsing in sequence — used for the
 * two boot states that genuinely have no progress to report:
 *
 *  - `main.tsx`: the lazy route chunk is still downloading, so the app shell
 *    doesn't exist yet.
 *  - `App.tsx`: the dashboard document is in flight, so the panel list (and
 *    with it anything the header's `DashboardLoadIndicator` could count) is
 *    not known.
 *
 * Neither phase can show a fraction, so a spinner is the honest signal — it may
 * as well be the brand mark rather than a generic one.
 *
 * Fixed and viewport-centred rather than laid out in flow: both phases render
 * it at the same screen position, so crossing from one to the other leaves the
 * mark where it is instead of making it jump.
 *
 * The mark and its animation are the ones from depictio-docs (`extra.css`
 * `triangular-pulse`, staggered per triangle) — see the
 * `.depictio-boot-splash*` rules in app.css.
 */
const BootSplash: React.FC = () => (
  <div
    className="depictio-boot-splash"
    role="status"
    aria-label="Loading"
    // The SVG is a build-time asset from this repo, not user or network input.
    dangerouslySetInnerHTML={{ __html: animatedMark }}
  />
);

export default BootSplash;
