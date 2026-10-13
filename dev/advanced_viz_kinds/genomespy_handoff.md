# GenomeSpy handoff: lot 2 kinds

Scope boundary from issue #1083: these kinds draw binned or summarised rows
only, never per-base signal, reads, or gene models, which is JBrowse
territory. Every *coordinate-bound* kind (a chromosome plus a start) carries
that pair so a GenomeSpy spec can bind the same rows with a `mark`, without a
schema change. This page is that handoff for the three kinds added in lot 2,
plus `coverage_track`'s new `mark` setting, which exists for the same reason.

The spec builder that consumes this handoff now exists: `genome_view`
(renamed from the spike's `genomespy_track`), in
`packages/depictio-react-core/src/components/advanced_viz/genomespy/`.
Three of its grammar limits, verified against `@genome-spy/core` 0.88.1, bound
everything below and correct two claims earlier revisions of this page made:

| Claim | Fact in 0.88.1 |
| --- | --- |
| "GenomeSpy's own `line` mark" | **There is no line or area mark.** `markTypes` in `view/unitView.js` is point / rect / arrow / rule / tick / link / text. A profile is `rect` anchored at a baseline, which `genome_view` exposes as `mark: "bar"`. |
| "`facet_by_sample` maps to GenomeSpy's `sample` facet" | `facet` is an **app-level** feature; core's `FacetSpec` is undocumented. Per-sample lanes are a hand-built `vconcat`, one view per sample, each narrowed by a `filter` transform over one shared dataset. |
| a second genomic axis for `contact_map` | Still absent. `contact_map` stays on Plotly; the two are linked by the region filter instead (see below). |

Being coordinate-bound is a property of the *rows*, not of the kind's name:
`knee_plot` and `damage_profile` are summaries over rank / read-position, not
over a chromosome, so a GenomeSpy spec has nothing to bind them to. They are
in this doc for the row contract, marked out of scope below.

## `contact_map` (in scope)

Row contract (`CANONICAL_SCHEMAS["contact_map"]` in
`depictio/models/components/advanced_viz/schemas.py`):

| Column                  | Type   | Required |
| ------------------------ | ------ | -------- |
| `chrom1`                 | string | yes      |
| `start1`                 | number | yes      |
| `chrom2`                 | string | yes      |
| `start2`                 | number | yes      |
| `count`                  | number | yes      |
| `sample`, `end1`, `end2` | (none) | optional |

Two coordinate pairs, not one: a contact map is the one lot-2 kind whose
rows name *two* genomic loci per row rather than one. GenomeSpy tracks bind a
single genomic x axis; a bin1x bin2 matrix has no native two-genomic-axis
mark today. The nearest honest mapping, for whenever that lands:

- **Mark**: `rect`, one per `(bin1, bin2)` pair.
- **Encoding**: `x` / `x2` from `start1` / `start1 + bin_size` on the shared
  genomic scale, `y` / `y2` from `start2` / `start2 + bin_size` on a second,
  independent positional scale (not GenomeSpy's default: this is the part
  that needs a spec extension, not just a channel mapping). `color` from
  `count`, typically log-transformed client-side the way
  `ContactMapRenderer.tsx` does it (`log_scale` config).
- **Faceting**: `sample`, when bound, is a `facet`, one matrix per sample,
  not a colour channel, since overlaying two matrices in one heatmap has no
  reading.

This renderer draws only the intra-chromosomal case (`chrom1 == chrom2`) and
mirrors the upper triangle across the diagonal; see
`ContactMapRenderer.tsx` and `contactMapBinning.ts::coarsenBins` for the
resolution guard (`max_bins`).

**What is wired today instead.** A `genome_view` tile over the 1D Hi-C tracks
(insulation, E1, boundaries) and a `contact_map` tile over the matrix share the
dashboard's region filter: a brush on the genome axis publishes a `chrom`
multi-select plus a `start` range through `genomeRegionFilters`, which the
contact map receives as an ordinary filter on its own collection. That is the
pyGenomeTracks reading (a matrix over aligned 1D tracks on one x range) without
the second genomic axis GenomeSpy does not have.

## `knee_plot` (out of scope)

Row contract: `sample` (string), `rank` (number, ascending from 1),
`umi_count` (number); optional `is_cell` (boolean).

`rank` orders barcodes by descending UMI count: it names a position in a
ranking, not a position on a chromosome. There is no `chrom` / `start` pair
to hand GenomeSpy, and there will not be one: a barcode-rank curve is not a
genome-track shape. `KneePlotRenderer.tsx` draws it as an ordinary log-log
line, with `kneeThinning.ts::logSpacedRankThin` capping the point count the
same way a GenomeSpy `rule`/`point` mark would need binning at high `rank`
counts, if this kind is ever revisited for a track-style rendering.

## `damage_profile` (out of scope)

Row contract: `sample` (string), `end` (string, `5p` or `3p`), `position`
(number), `base_change` (string), `frequency` (number).

`position` is distance from a read end (1 to `max_position`, typically at
most 25), not a chromosome coordinate: every read contributes the same
1-25 range regardless of where it aligned. Nothing here binds to a genome
axis.

## `coverage_track` (mark added, unchanged scope)

Already coordinate-bound (`chromosome`, `position`) and already the
kind this scope boundary was written for. Lot 2 adds a `mark` setting
(`CoverageTrackConfig.mark`, default `"line"`) so the config itself now
carries what a GenomeSpy spec would set as its mark:

| `mark` value | GenomeSpy mark | Encoding                              |
| ------------ | --------------- | -------------------------------------- |
| `"line"`     | none (no line mark exists) | closest reading is `genome_view`'s `"bar"`: `rect` with `y` = `value`, `y2` = `{datum: 0}` |
| `"rect"`     | `rect`           | `x`/`x2` = bin `position`/`end`, `y` = `value` |
| `"point"`    | `point`          | `x` = `position`, `y` = `value`        |

`facet_by_sample` becomes a `vconcat` of one view per sample sharing the x
scale, not a GenomeSpy `facet` (which is app-only). Both fields are optional
and default to today's rendering; see `CoverageTrackConfig` in
`depictio/models/components/advanced_viz/configs.py`. Note that `mark: "line"`
has no GenomeSpy equivalent: a collection bound to `genome_view` instead draws
that profile as `mark: "bar"`.

## `genome_view` (the consumer)

Row contract (`CANONICAL_SCHEMAS["genome_view"]` plus `_OPTIONAL_ROLES`):

| Role       | Column config   | Type   | Required | What it turns on                       |
| ---------- | --------------- | ------ | -------- | -------------------------------------- |
| `chr`      | `chr_col`       | string | yes      | the locus axis, and the chromosome half of the region filter |
| `pos`      | `pos_col`       | int    | yes      | mark position, and the range half of the region filter |
| `score`    | `score_col`     | float  | yes      | the y axis                             |
| `end`      | `end_col`       | int    | no       | `rect` intervals, and the span of a bar |
| `feature`  | `feature_col`   | string | no       | hover identity, and what a click filters on |
| `sample`   | `sample_col`    | string | no       | `facet_by_sample`: one `vconcat` lane per sample |
| `category` | `category_col`  | string | no       | colour channel in place of the chromosome |

Deliberately identical required roles to `manhattan`, so any collection one of
them binds the other renders unchanged.

A tile binds exactly one data collection, so a multi-track genome view is
several `genome_view` tiles stacked in one dashboard section sharing a region
filter, not one tile over N collections. Within one tile, `facet_by_sample`
gives per-sample lanes (capped by `max_facets`) because those rows do come from
one collection.
