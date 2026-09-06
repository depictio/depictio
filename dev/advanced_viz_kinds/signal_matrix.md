# `signal_matrix`

The metagene heatmap that pairs with a [`profile`](profile.md) curve: rows are
regions, columns are position offsets around a reference point, cells are the
signal at that offset. A marker sits at the reference position, and the mean
profile can be drawn in a small panel above the matrix, sharing the x axis.

Long format, one row per `(region, position, value)`, because a wide frame
would need one column per bin and the bin count is a pipeline parameter.

| Use                          | region_id       | position              | value          |
| ---------------------------- | --------------- | --------------------- | -------------- |
| TSS enrichment matrix        | gene or peak id | bp offset from TSS    | mean coverage  |
| ChIP signal around summits   | peak id         | bp offset from summit | fold enrichment|
| Metagene over scaled bodies  | transcript id   | scaled position       | normalised cov |

## Model

- Config: `SignalMatrixConfig` in
  `depictio/models/components/advanced_viz/configs.py`
- Canonical roles: `CANONICAL_SCHEMAS["signal_matrix"]` in
  `depictio/models/components/advanced_viz/schemas.py`, namely
  `region_id` (string), `position` (numeric), `value` (numeric)
- Sampling policy: `"none"` in
  `depictio/models/components/advanced_viz/sampling.py`. A sampled matrix loses
  whole regions rather than resolution, so the server serves the frame whole;
  past the no-sample ceiling it reduces anyway and the renderer raises the
  frame's `estimated` badge.

## Renderer

`packages/depictio-react-core/src/components/advanced_viz/SignalMatrixRenderer.tsx`

Built to the shape of `ComplexHeatmapRenderer`: same `AdvancedVizFrame` chrome
(loading, error, empty, Show data popover, Settings popover), same
`plotlyTheme` helpers (`plotlyThemeFragment` / `plotlyAxisOverrides` on the way
in, `applyDataTheme` / `applyLayoutTheme` at the `<Plot>` props), same default
export. Unlike ComplexHeatmap it needs no Celery round trip: the frame arrives
through `fetchAdvancedVizData` and every control re-shapes what is already in
hand, so nothing here refetches.

Two properties drive every decision in the file:

1. **The column order is positional.** Offsets are sorted numerically once and
   never clustered or reordered. A metagene column means "150 bp downstream of
   the reference"; permuting it destroys the only thing the plot says. There is
   no cluster-columns control and there must never be one.
2. **Rows are binned, never truncated.** A real deepTools matrix runs to 10^5
   regions.

### How rows are binned

`binRows()` averages within consecutive bins of the sorted row order:

- Every region first becomes one vector over the position axis. Repeat
  `(region, position)` pairs are averaged, missing offsets stay `null`.
- Rows are ordered by `sort_by`: `signal` (default) sorts by total signal
  descending, `none` keeps the order the frame delivered.
- If the region count exceeds `max_rows`, the bin size is
  `ceil(regions / max_rows)` and each bin's drawn row is the position-wise mean
  of its members. Nulls are skipped per position rather than counted as zero,
  so a region missing one offset does not drag its bin toward the floor.
- A bin's y label is `first … last (n)`, so the row still names what it covers.

Averaging within a *signal-sorted* order is what makes the reduction faithful:
neighbours in that order carry near-identical profiles, so the bin mean is the
shape both of them had. A head, by contrast, would silently drop every weak
region, which is exactly the half a metagene is drawn to compare.

The mean profile is computed **before** binning, over every region in the
panel, since a mean of unequal bin means is not the mean.

### Panels, and the label-margin clamp

`group_col` splits the matrix into stacked panels sharing the x axis, capped at
`MAX_PANELS` (6) — beyond that the bands are too short to read, and the
controls say how many groups were left out. `max_rows` is a budget shared
across panels, not a per-panel multiplier.

Row labels are drawn only while they can be read (40 drawn rows or fewer) and
their margin is clamped to `LABEL_MARGIN_FRACTION` (22%) of the *measured* tile
width, with the tick text truncated to whatever that margin affords and the
full id kept in hover. Every row axis also sets `automargin: false`
explicitly. This is the platform-side fix for
`depictio/projects/nf-core/TEMPLATE_BOTTLENECKS.md` §14: Plotly sizes an
annotation strip's margin from the longest label and nothing clamps it against
the tile, which once left a complex_heatmap with a 346 px margin in a 517 px
tile and a negative plot area — the colour bar drew, and not one cell did.

The tile width comes from a `ResizeObserver` on the plot container (guarded for
environments without one, and only reacting to moves of 8 px or more so a
margin change cannot churn the figure).

Other rendering notes:

- The colour range is the 2nd–98th percentile of a strided sample of the drawn
  cells, so one saturated region cannot flatten the ramp. All panels share one
  range and one colour bar, which is what makes them comparable.
- `reference_position` becomes a dotted `yref: 'paper'` line through every
  band, drawn only when it falls inside the observed position range, with
  `reference_label` as an annotation at its head.
- The matrix y axis is `autorange: 'reversed'` so the strongest signal sits on
  top, since a categorical axis otherwise fills bottom-up.

## Tier-2 controls

Exposed in the viz settings popover via `usePersistedVizControl`, so a change is
written back into the component's config rather than forgotten on remount:

| Control      | Config key     | Default     |
| ------------ | -------------- | ----------- |
| Colour scale | `colour_scale` | `Viridis`   |
| Row order    | `sort_by`      | `signal`    |
| Max rows     | `max_rows`     | `2000`      |
| Profile      | `show_profile` | `true`      |

Each call keeps `metadata` and the string key on one line, which is what
`test_persisted_controls_survive_their_model` parses.

## Selection

None. `signal_matrix` does not declare selection and the renderer emits none: a
drawn row is usually a bin of regions rather than a region, so a rectangle over
the matrix has no row identity to filter on.

## Shared edits this kind needs (owned elsewhere)

1. `AdvancedVizDispatch.tsx`: the import and the `RENDERERS` entry.

   ```tsx
   import SignalMatrixRenderer from './SignalMatrixRenderer';
   // …inside RENDERERS:
   signal_matrix: SignalMatrixRenderer,
   ```

   Required, not optional: `test_every_dispatched_kind_has_a_model_and_a_source`
   asserts the dispatch table and the config union name the same kinds, so
   `SignalMatrixConfig` existing without this entry fails CI.

2. `api.ts`: `'signal_matrix'` added to the `AdvancedVizKind` union. Until then
   the renderer sends the kind through a documented cast
   (`SIGNAL_MATRIX_VIZ_KIND`), because omitting it would make the server sample
   the frame uniformly.
