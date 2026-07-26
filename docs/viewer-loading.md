# Panel loading in the viewer

A dashboard can hold dozens of panels, each needing its own server round-trip
and, for figures, a synchronous Plotly mount that blocks the main thread. Fetching
all of them on open makes the page unresponsive long before anything is readable,
so the viewer loads panels as they become visible and reports progress for the
ones it is actually working on.

## Panels load when they reach the viewport

Data panels (figure, table, map, image, advanced-viz, MultiQC) defer their fetch
until they scroll within 200 px of the viewport — `useInView` in
`packages/depictio-react-core/src/hooks/useInView.ts`. Until then they render a
skeleton and cost nothing.

The `IntersectionObserver` is the authority on visibility. A rect measurement is
kept only as a fallback, and deliberately runs on a delay: react-grid-layout has
to measure its container before it can position anything, so on the first commit
every panel still sits at the grid origin, where an immediate measurement reports
the whole dashboard as on-screen. That fallback exists because some environments
— background tabs, embedded iframes, headless automation — throttle the observer
so its first callback never arrives, which would otherwise leave every panel
staring at a skeleton.

## What the header indicator counts

While panels are loading, a ring and a count sit next to the dashboard title. It
counts **only panels that reached the viewport**, plus the card group:

- The denominator is what is actually being loaded, so the ring completes and
  disappears. Counting every panel in the dashboard instead would pin it near
  empty — off-screen panels never start, so it could never finish, and a stalled
  progress bar reads as a broken one.
- Scrolling brings more panels in, which **grows the denominator** — the ring can
  step backwards. That is the honest reading of "what is loading right now".
- Hover for the breakdown: how many are in flight, how many failed, and how many
  are further down and therefore not counted yet.

Cards are counted as one group rather than per panel, because they resolve
together through the bulk-compute endpoint.

## Boot splash

Two phases have no panel list yet and so cannot show a fraction: the lazy route
chunk downloading (`main.tsx`) and the dashboard document being fetched
(`App.tsx`). Both render the same `BootSplash` — the Depictio mark with its seven
triangles pulsing in sequence, matching the animated logo in depictio-docs. It is
fixed and viewport-centred so the mark stays put when one phase hands over to the
other, instead of jumping.

Under `prefers-reduced-motion: reduce` the pulse is slowed and shrunk rather than
removed. A loading indicator that holds still fails at the one thing it is there
to say; the pulse scales each triangle about its own centre, with no travel or
rotation, so softening it keeps the signal without the trigger.
