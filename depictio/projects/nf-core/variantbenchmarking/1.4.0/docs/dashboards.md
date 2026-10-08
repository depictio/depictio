# nf-core/variantbenchmarking 1.4.0: Depictio dashboards

One dashboard: an **Overview**, then one child tab per variant type, in two groups.
[nf-core/variantbenchmarking](https://nf-co.re/variantbenchmarking) compares the calls of one
or more callers with a truth set and scores each callset on precision, recall and F1. A run
benchmarks one variant type, so a run shows the Overview and the tab of its type. The family
rules are in `depictio/projects/nf-core/RULES.md`.

| Group | Tab | The question it answers |
|---|---|---|
| Small variants | Germline | How well does each germline callset recover the truth set? |
| Small variants | Somatic | How well does each somatic caller recover the truth set? |
| Structural | Structural & CNV | How well do the structural callsets match the truth set? |

The pipeline writes no MultiQC report into the collections this template reads, and it has no
sample sheet, so there is no MultiQC tab, no `Data & QC` group, no persistent sample filters
and no Sample sheet section. Every benchmark collection shares one vocabulary: `label` is the
callset id the pipeline benchmarked, `caller` the tool behind it, `truth_set` the truth set it
was scored against (read from the benchmark file name) and, for Wittyer, `stats_type` the
scoring level (`Event` or `Base`).

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The second lists the
  analysis and variant type, the truth set, the benchmarking methods and the genome from the
  run parameters, and the number of callsets of the run's route.
- **Pipeline**: the calls are prepared (normalised, deduplicated), scored against the truth set
  on the route of the run's variant type, then summarised per tool. The template writes one
  step per route, each citing the callset count of its route's collection and opening its tab;
  the import drops the steps of the routes the run did not take, so a run shows four steps.
- **Key figures**: per route, four headline cards opening its tab: the true positives (split by
  caller), the median F1 (with its spread), the median recall and the median precision. The
  germline recall passes at 0.9 (warns below 0.8), the somatic precision at 0.5 (warns below
  0.25), the structural recall at 0.8 (warns below 0.6). A caller and a callset filter above
  them narrow these four only.
- **Findings**: three result rows per route, computed under the filters, each linking its
  tab. Germline: the best vcfeval F1 and its caller, the hap.py SNP and indel F1 of the PASS
  calls, and the caller with most false positives. Somatic: the best som.py F1 and its caller,
  the caller with most false positives, and the best rtg-tools vcfeval F1. Structural: the
  best Truvari F1 and its caller, the best SVanalyzer F1, and the Wittyer F1 per event against
  per base. Below them, four figures per route in two rows: germline, the precision-recall
  scatter and hap.py F1 by variant type, then the quality-threshold sweep and the error counts;
  somatic, the precision-recall scatter and the recall intervals, then the error counts and the
  precision intervals (the allele-fraction strata stay on the tab, since a run can write them
  for some callers only); structural, the Truvari precision-recall scatter and the SVanalyzer
  F1, then the Truvari error counts and the Wittyer F1. The bar of this section filters by
  caller and callset.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

## Child tabs

Each tab opens with a short intro (the method, with a link to its tool, and how to read the
tab), then a strip of four key numbers, each card with its own colour and a secondary that
reads it, then at most three open sections; tables and the cross-check follow, collapsed. The
precision-recall scatters colour each callset by its caller and draw no point labels (callset
ids pile up); the iso-F1 contours read F1 off the plane.

**Germline.** Strip: F1 (box plot), recall against a 0.9 floor, false positives (the callers
with most) and true positives (split by caller). Then the vcfeval precision-recall scatter
beside the error counts per callset, and hap.py's F1 by variant type (all calls against PASS
calls) beside the quality-threshold sweep. Collapsed: the vcfeval, hap.py and sweep tables.
Filters: caller, callset, hap.py variant type and hap.py calls (ALL or PASS).

**Somatic.** Strip: F1 (box plot), precision against a 0.5 floor, false positives (the callers
with most) and true positives (split by caller). Then the som.py precision-recall
scatter beside the error counts, the precision and recall with their binomial 95% intervals,
and F1 and recall per allele-fraction bin. Collapsed: the rtg-tools vcfeval cross-check
(scatter and table) and the som.py summary and strata tables. Filters: caller and
allele-fraction bin; the caller reaches the strata and the cross-check through the links.

**Structural & CNV.** Strip: true positives (split by caller), F1 (box plot), recall against a
0.8 floor and precision (distribution), all from Truvari. Then the Truvari precision-recall
scatter beside its error counts, and the SVanalyzer F1 per callset beside the Wittyer F1 per
event and per base. Collapsed: the Truvari, SVanalyzer and Wittyer tables. Filters: callset,
caller and Wittyer level; the callset reaches SVanalyzer and Wittyer through the links.

## Routes and pruning

Every collection is optional: a run writes one family of tables, and whichever collection was
required would fail every other route. The Overview gives each route its own row of Key
figures, its own pair of bar filters and its own four highlights, on slots of their own. A run
on one route drops the other two blocks and the import re-packs the sections, so the Overview
reads as one row of cards and two rows of highlights. A data root holding two routes keeps
both blocks, stacked.

| Route (`--variant_type`) | What remains |
|---|---|
| `small` (germline) | The Germline tab, the germline cards, rows and highlights. |
| `snv` or `indel` (somatic) | The Somatic tab, the somatic cards, rows and highlights. |
| `structural` | The Structural & CNV tab, the structural cards, rows and highlights. |
| `copynumber` | Only the Wittyer tiles of the Structural & CNV tab and the Wittyer row. |

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: callers take `auto`
(a colour-blind-safe colour each at import), hap.py's SNP and INDEL and its ALL and PASS calls
are written out, and Wittyer's Event and Base levels too.

## Cross-selection

The callset tables select rows on their identifier: `label` for the vcfeval, Truvari,
SVanalyzer and Wittyer tables, `caller` for the som.py tables and the somatic vcfeval table. A
pick narrows the tiles that read the same table; a som.py pick also reaches its
allele-fraction strata and the cross-check, and a Truvari pick reaches the SVanalyzer and
Wittyer tiles, through the links. The hap.py pooled summary and threshold sweep have no
callset column and do not select.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top of a
narrower one. Nothing is set per tab or per tile.

## Per-variant-type projects

`categories/{small,indel,structural}/` are separate templates, one project per variant type,
each with a Benchmark tab and the pipeline's MultiQC report. They keep their own layout and
are not part of this dashboard.

## Benchmarking visualisation kinds

The tabs are built from reusable benchmarking kinds, each demonstrated in the Advanced
Visualisations showcase dashboard.

- **Precision-recall benchmark** (`pr_benchmark`): each callset at its (recall, precision),
  dotted equal-F1 contours, the diagonal where recall equals precision. Top right is best.
- **ROC / PR curve** (`roc_pr_curve`): threshold-sweep curves with their AUC; the view switch
  draws the PR curve, the ROC or precision and recall against the threshold.
- **Confusion matrix** (`confusion_matrix`): TP, FP and FN per callset, the shade normalised
  per callset, the label the raw count.
- **Metric with its interval** (`metric_ci_bars`): a point estimate and its 95% interval per
  caller, the axis zoomed so tight intervals stay readable.

![Precision-recall benchmark](screenshots/advviz-pr-benchmark.png)

## Catalog modules

`rtgtools` (vcfeval_summary) · `happy` (summary, roc) · `sompy` (summary, regions) ·
`truvari` (summary) · `svanalyzer` (svbenchmark) · `wittyer` (summary), under
`depictio/catalog/<tool>/`; `renders_as` declares the plots the dashboards reference by `use:`.

## Reproducing

```bash
python scripts/nfcore_megatest.py fetch --pipeline variantbenchmarking --version 1.4.0 --dest <DATA_ROOT>
depictio-cli ingest --template nf-core/variantbenchmarking/1.4.0 --data-root <DATA_ROOT>
```
