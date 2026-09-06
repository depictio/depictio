# `profile`

One curve per series over an ordered numeric axis, with an optional confidence
band, an optional reference marker, optional shaded x ranges and optional log
axes.

Named for the shape rather than a domain, because these are all the same three
columns with different axis labels:

| Use                       | series          | x                  | y                  |
| ------------------------- | --------------- | ------------------ | ------------------ |
| TSS enrichment profile    | sample          | offset from TSS    | mean signal        |
| Fragment length ladder    | sample          | fragment length bp | read count         |
| Hill diversity curve      | sample or group | Hill order q       | effective richness |
| Rank abundance curve      | sample          | rank               | abundance          |

## Model

- Config: `ProfileConfig` in `depictio/models/components/advanced_viz/configs.py`
- Canonical roles: `CANONICAL_SCHEMAS["profile"]` in
  `depictio/models/components/advanced_viz/schemas.py`, namely
  `series` (string), `x` (numeric), `y` (numeric)
- Sampling policy: `"none"` in
  `depictio/models/components/advanced_viz/sampling.py`. A uniform subset of a
  profile is a curve with holes, so the server serves the frame whole and the
  renderer shows the `estimated` badge when the DC blew past the no sample
  ceiling and it was reduced anyway.

## Renderer

`packages/depictio-react-core/src/components/advanced_viz/ProfileRenderer.tsx`

Built to the shape of `RarefactionRenderer`: same `fetchAdvancedVizData` path,
same `plotlyTheme` helpers, same `AdvancedVizFrame` chrome (loading, error,
empty, Show data popover, Settings popover), same memoised inner `<Plot>` so a
parent re-render cannot drop an in flight drag.

What it draws:

- **Curves.** Rows are grouped by `series_col` and sorted by `x_col`. Colours
  come from `stableColorMap` keyed on the full distinct set of series values
  (fetched via `fetchUniqueValues`), so a curve keeps its colour when the user
  filters down to a subset. A DC with no series column collapses to a single
  curve named after the y axis.
- **Confidence band.** Drawn only when both `lower_col` and `upper_col` are
  configured, as an upper edge trace plus a `fill: 'tonexty'` lower edge at
  `band_opacity`. All bands are emitted before all lines so no series' ribbon
  can cover another series' curve.
- **Reference marker.** `reference_x` becomes a dotted paper height line, with
  `reference_label` as an annotation at its foot.
- **Shaded x ranges.** Each `shaded_bands` entry `[start, end, label]` becomes a
  `layer: 'below'` rect at a fixed subtle opacity plus a label above the plot.
  Deliberately not driven by `band_opacity`: the shading is furniture, and
  `band_opacity` belongs to the ribbon the user can tune away.
- **Log axes.** `log_x` / `log_y` set the Plotly axis type. Shapes and
  annotations are converted to log10 space, since that is the coordinate system
  Plotly uses on a log axis; a non positive x is dropped rather than clamped.

## Tier-2 controls

Exposed in the viz settings popover via `usePersistedVizControl`, so a change
is written back into the component's config rather than forgotten on remount:

| Control       | Config key     | Default |
| ------------- | -------------- | ------- |
| Log x         | `log_x`        | `false` |
| Log y         | `log_y`        | `false` |
| Line width    | `line_width`   | `2.0`   |
| Band opacity  | `band_opacity` | `0.2`   |
| Legend        | `legend_pos`   | `right` |

Band opacity is only offered when the component actually has a band bound.

Each call keeps `metadata` and the string key on one line, which is what
`test_persisted_controls_survive_their_model` parses.

## Selection

`profile` declares `selection_enabled` / `selection_column`, and the natural
identity of a point on a profile is the curve it belongs to. The renderer
writes the series name into `customdata` slot 0 and reads it back with
`extractScatterSelection(event, 0)` on select, click and deselect, emitting the
standard `scatter_selection` filter through `advancedVizSelectionFilter`.

It fetches with `filtersExcludingOwn(..., 'scatter_selection')` so it never
narrows itself, and dims the curves outside the current selection instead. When
selection is on, drag defaults to box select and the modebar keeps `select2d`.

## Shared edits this kind needs (owned elsewhere)

1. `AdvancedVizDispatch.tsx`: the import and the `RENDERERS` entry.
2. `selection.ts`: the `case 'profile':` arm of `advancedVizSelectionColumn`,
   falling back to `series_col`.
3. `api.ts`: `'profile'` added to the `AdvancedVizKind` union. Until then the
   renderer sends the kind through a documented cast, because omitting it would
   make the server sample the frame uniformly.
