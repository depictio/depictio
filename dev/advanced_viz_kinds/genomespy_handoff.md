# GenomeSpy handoff: lot 2 kinds

Scope boundary from issue #1083: these kinds draw binned or summarised rows
only, never per-base signal, reads, or gene models, which is JBrowse
territory. Every *coordinate-bound* kind (a chromosome plus a start) carries
that pair so a later GenomeSpy spec can bind the same rows with a `mark`,
without a schema change. This page is that handoff for the three kinds added
in lot 2, plus `coverage_track`'s new `mark` setting, which exists for the
same reason.

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
| `"line"`     | GenomeSpy's own `"line"` mark | `x` = `position`, `y` = `value` |
| `"rect"`     | `rect`           | `x`/`x2` = bin `position`/`end`, `y2` = `value` |
| `"point"`    | `point`          | `x` = `position`, `y` = `value`        |

`facet_by_sample` maps to GenomeSpy's `sample` facet the same way `sample`
already facets this renderer's per-sample lanes. Both fields are optional and
default to today's rendering; see `CoverageTrackConfig` in
`depictio/models/components/advanced_viz/configs.py`.
