# `sashimi`

Splice junctions as arcs over a genomic interval. Each junction is an arc from
its donor to its acceptor on a base-pair x axis, the arc's line width scaled by
the reads supporting it, the read count printed at the apex, one lane per
sample when a sample column is bound.

The read is: which introns did the aligner actually observe here, how well is
each one supported, and do any of them skip an exon the others keep.

## Model

- Config: `SashimiConfig` in `depictio/models/components/advanced_viz/configs.py`
  (`chr_col`, `start_col`, `end_col`, `count_col`, `sample_col`,
  `annotation_col`, `min_count`, `top_n`, `log_width`)
- Canonical roles: `CANONICAL_SCHEMAS["sashimi"]` in
  `depictio/models/components/advanced_viz/schemas.py`, namely `chr` (string),
  `start`, `end` and `count` (all numeric)
- Sampling policy: `"none"` in
  `depictio/models/components/advanced_viz/sampling.py`. The renderer cuts by
  `min_count` and ranks to `top_n` client-side, so a uniform subset would not
  be a coarser plot, it would be the wrong `top_n`.

## Renderer

`packages/depictio-react-core/src/components/advanced_viz/SashimiRenderer.tsx`

Built to the shape of `CoverageTrackRenderer`, which is the house pattern for a
base-pair axis: same `AdvancedVizFrame` chrome (loading, error, empty, Settings
popover, Show data popover), the same `plotlyTheme` helpers, the same
per-sample subplot stacking, and `AdvancedVizPlot` for the figure. It fetches
through the ordinary `fetchAdvancedVizData` path rather than a Celery compute
endpoint: a junction table is a few thousand rows, and everything the plot does
to it is a filter, a sort and a slice.

What it draws:

- **Arcs.** Each junction is a quadratic bezier from `(start, 0)` to `(end, 0)`
  with the control point at twice the apex height, sampled into 40 points. The
  control point sits at the midpoint, so x stays linear in t and the sampled
  path is a real arc rather than a spline guess. Every sampled point carries
  the junction's own hover text (coordinates, read count, span, sample,
  annotation), which is why the arc is a sampled path and not a layout shape:
  shapes do not hover.
- **Width by support.** Read support is heavy-tailed (the ctatsplicing megatest
  has junctions at 1 read sitting beside one at 984), so `log_width` maps
  `log10(1 + count)` onto the width range by default; turning it off maps the
  raw count. Plotly sets line width per trace rather than per point, so widths
  are quantised into 7 levels and all the arcs of one level are concatenated
  into a single null-separated trace. That keeps a faceted panel at tens of
  traces instead of hundreds.
- **Height by span.** The apex height encodes the junction's span, not its
  count, so a short junction nested inside a longer one is drawn under it
  rather than across it. The y axis is unlabelled for the same reason: the
  height is a layout device, not a quantity to read off.
- **Region scoping.** Arcs need a locus, not a chromosome. Junctions are
  clustered by a 1 Mb gap and the picker offers those loci busiest first, with
  whole-chromosome entries in a second group. On the rnafusion megatest this
  resolves to one gene per locus (EWSR1, EML4, BRAF, ALK, ROS1 and so on) and
  opens on EWSR1: 20 junctions over 28 kb. Opening on chr7 instead would put
  three loci 127 Mb apart on one axis, where every intron is a hairline spike.
- **Lanes.** One subplot row per `sample_col` value, named on the y axis title.
  `top_n` applies per lane, so a shallow sample keeps a panel of its own
  strongest arcs instead of being crowded out by a deeply sequenced one.
- **Colour.** By `annotation_col` when one is bound (known versus novel, or a
  variant name), through `stableColorMap` so a category keeps its colour under
  filtering. Otherwise every arc takes the first palette colour.
- **Show data.** The popover publishes the arcs on screen rather than the
  fetched frame. A sashimi drops most of its rows on purpose, so the raw frame
  is not the thing being looked at.

## Tier-2 controls

| Control                 | Config key  | Default | Persisted |
| ----------------------- | ----------- | ------- | --------- |
| Min supporting reads    | `min_count` | `1`     | yes       |
| Max junctions per lane  | `top_n`     | `50`    | yes       |
| Log-scaled arc width    | `log_width` | `true`  | yes       |
| Region                  | none        | busiest locus | no  |
| Read count at each apex | none        | `true`  | no        |
| Thickest arc            | none        | `9` px  | no        |

The three persisted ones each keep `metadata` and the string key on one line,
which is what `test_persisted_controls_survive_their_model` parses. The other
three have no field on `SashimiConfig` and are plain `useState`: a region pick
is a reading position rather than an authored default, and the two cosmetic
toggles are not worth a model field.

## Selection

`sashimi` does not declare selection, so the renderer emits none: no
`onFilterChange`, no `selection.ts` arm, no lasso. An arc is an interval rather
than a row identity, and there is no obvious column a click should filter on.

## Catalog binding

**The existing ctatsplicing output binds `sashimi` directly. No new recipe is
needed.**

`depictio/catalog/ctatsplicing/introns.yaml` (output id `ctatsplicing_introns`,
recipe `ctatsplicing/introns.py`, glob `**/ctatsplicing/*.introns`) already
publishes every column the four canonical roles need:

| Role    | Column        | Dtype   | Note                                          |
| ------- | ------------- | ------- | --------------------------------------------- |
| `chr`   | `chrom`       | String  | split out of the packed `chr2:29193923-29196769` intron key |
| `start` | `start`       | Int64   | donor coordinate                              |
| `end`   | `end`         | Int64   | acceptor coordinate                           |
| `count` | `uniq_mapped` | Int64   | uniquely mapping reads crossing the junction  |

`uniq_mapped` is the conventional sashimi support metric and the one the
existing `intron_manhattan` render already exposes as `score`. `total_mapped`
(unique plus multi-mapped) binds just as well if a template prefers it, and
`score` is the same number as a Float64.

The render line that belongs on that output (owned by whoever edits the catalog
YAML, not written here):

```yaml
- { id: junction_arcs, component: advanced_viz, kind: sashimi, roles: {chr: chrom, start: start, end: end, count: uniq_mapped} }
```

Verified against the real file at
`~/Data/depictio-nfcore/rnafusion/4.1.3/megatest/ctatsplicing/test.introns`, run
through `ctatsplicing/introns.py`: 200 junctions, 14 chromosomes, 22 loci at a
1 Mb gap, `uniq_mapped` from 0 to 984, spans from 126 bp to 13 kb. 7 junctions
have zero unique support and fall under the default `min_count` of 1. The
rnafusion 4.1.3 template already ingests this recipe as the `splice_junctions`
data collection, so the binding lands on a collection that exists rather than
one that would have to be added.

`cancer_introns.yaml` binds the same four roles (`chrom`, `start`, `end`,
`uniq_mapped`) and would be the natural home for an `annotation` binding on
`variant_name`. It is not worth a render today: the megatest writes that file
with a header and no rows, and the template already marks the collection
optional.

### What the binding cannot express yet

- **Display defaults.** `Render` carries only `kind` and `roles` for an
  advanced viz, so a catalog binding cannot preset `min_count`, `top_n` or
  `log_width`. The component takes the `SashimiConfig` defaults (1, 50, true),
  which are right for this data.
- **`sample` and `annotation` roles are rejected.** `_OPTIONAL_ROLES` in
  `schemas.py` has no `sashimi` entry, so `_allowed_roles` returns only the
  four canonical roles and a render binding `annotation: gene` fails validation
  with "unknown role(s) ['annotation']". Both config fields exist and the
  renderer reads them; only the role vocabulary is missing. See the shared
  edits below.
- **No sample column exists on this DC anyway.** `introns.py` documents it: the
  recipe harness concatenates the globbed files without their path, so a row
  cannot be attributed to a sample, and the intron is the unit of analysis.
  Per-sample lanes on ctatsplicing would need the recipe to carry a sample
  column derived from the file stem, which is a recipe change and out of scope
  here. The megatest has one sample, so a single lane is the honest picture.

### rnaseq has nothing to bind

nf-core/rnaseq 3.26.0 publishes no per-junction counts. Checked the 3.26.0
megatest tree: the only junction output is
`star_salmon/rseqc/junction_annotation/log/*.junction_annotation.log`, which is
a summary (total, known, partial novel and novel splicing events and
junctions), with no `SJ.out.tab` and no per-junction BED anywhere in the run.
Nothing there is a junction row with coordinates and a read count, so `sashimi`
must not be advertised for rnaseq.

## Shared edits this kind needs (owned elsewhere)

1. `packages/depictio-react-core/src/components/advanced_viz/AdvancedVizDispatch.tsx`:

   ```ts
   import SashimiRenderer from './SashimiRenderer';
   ```

   and in `RENDERERS`:

   ```ts
   sashimi: SashimiRenderer,
   ```

2. `packages/depictio-react-core/src/api.ts`: `'sashimi'` added to the
   `AdvancedVizKind` union. Until then the renderer sends the kind through a
   documented cast, because omitting it would make the server sample the frame
   uniformly and break the `top_n` ranking.

3. `depictio/models/components/advanced_viz/schemas.py`: a `"sashimi"` entry in
   `_OPTIONAL_ROLES`, `{"sample": _STRING, "annotation": _STRING}`. Two things
   need it. The catalog rejects a `sample` or `annotation` binding without it,
   and `validate_binding` raises `KeyError: 'sashimi'` on the very first line it
   reads (`optional = _OPTIONAL_ROLES[kind]`, an indexed read where
   `role_dtype_specs` uses `.get`), so any sashimi binding is unvalidatable
   today. The other kinds added in this batch have the same hole.
