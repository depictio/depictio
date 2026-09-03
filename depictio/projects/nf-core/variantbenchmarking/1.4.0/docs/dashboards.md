# nf-core/variantbenchmarking 1.4.0: Depictio dashboards

This template turns the output of [nf-core/variantbenchmarking](https://nf-co.re/variantbenchmarking)
1.4.0 into interactive Depictio dashboards. The pipeline benchmarks variant callers
against a truth set (precision / recall / F1); the template surfaces those numbers as the
same panels the pipeline's own `bin/plots.R` produces, plus the integrated MultiQC report.

The template is split into **three per-variant-type projects**, named after the pipeline's own
`analysis × variant_type` axis. Each has a **Benchmark** tab (the analytical funnel) and a
**MultiQC** tab (the pipeline's report), except structural, which has no separate summary table
in the pipeline, so it is MultiQC-only.

| Project | analysis / variant_type | Truth set | Benchmark tools |
|---|---|---|---|
| Germline small variants | `germline` / `small` | GIAB / HG002 | hap.py, rtg-tools vcfeval |
| Somatic indels | `somatic` / `indel` | SEQC2 | som.py, rtg-tools vcfeval |
| Structural variants | `somatic` / `sv` | HG002 Tier1 | truvari, SURVIVOR (MultiQC only) |

Data is sourced from the most recent AWS megatest run
(`results-8b21c01749c4447b285d242a198127736f3ffe51`, 2026-04-22), the only run covering both
germline (`small/`) and somatic (`indel/`) benchmarks.

---

## How the dashboards are built

All three projects follow the same layout the other bundled templates use (ampliseq,
viralrecon, iris, penguins):

- **Sections.** Every tab is a stack of named grid sections, each opened by a short text tile
  that states what the section shows. Sections read as a funnel: run-level cards first, the
  signature precision-recall view next, then the error breakdown, the stratifications and
  finally the reference tables.
- **Filter panel.** Interactive controls live in the left panel, grouped into collapsible
  filter sections (`Callsets` / `Callers`, `Score ranges`, a tool-specific scope). Range sliders
  on F1 / precision / recall narrow every panel that reads the same table; the template's
  `links` carry a caller pick across som.py, its allele-fraction strata and the rtg-tools
  cross-check.
- **Multi-metric cards.** The four cards of the first section each carry a secondary strip:
  a donut of callsets by truth set or variant type, a Tukey box plot of F1, a gauge for the
  mean precision or recall, and a pass / warn / fail count against an accuracy threshold.
- **Catalog provenance.** Every benchmark plot is a catalog render (`use: rtgtools/pr_scatter`,
  `sompy/confusion`, `happy/pr_curve`, ...) and every MultiQC tile names its module
  (`use: multiqc/happy`, `multiqc/sompy`, `multiqc/truvari`, `multiqc/bcftools`), so the tile
  chrome shows where the panel comes from.
- **Pinned reference tables.** The raw summary rows sit in a collapsed `Reference tables`
  section that is persistent and pinned to the bottom, so it trails the MultiQC tab as well.

---

## Germline small variants

### Benchmark

Five sections. **Benchmark at a glance** carries the intro and four cards (callsets by truth
set, F1 box plot, precision gauge, recall against a 0.9 threshold). **Precision vs recall** is
the signature view: the precision-recall benchmark scatter (each point a callset, size = true
positives, colour = F1, dotted lines = equal-F1 contours) next to a ranked F1 strip.
**Error profile** places the confusion matrix (TP / FP / FN per callset) above false-positive and
false-negative bars. **hap.py stratification** splits F1 by SNP vs INDEL (ALL vs PASS, grouped
bars) and sweeps the quality threshold as a PR curve with AUC. **Reference tables** (collapsed,
pinned) holds the vcfeval, hap.py and threshold-sweep rows.

Filters: `Callsets` (sample, truth set), `Score ranges` (F1, precision, recall sliders) and
`hap.py scope` (ALL / PASS segmented control, variant type).

![Germline small-variant benchmark](screenshots/germline-benchmark.png)

### MultiQC

**Report at a glance** (general statistics), **hap.py panels** (SNP and INDEL, catalog-badged as
`multiqc/happy`) and a collapsed **Variant statistics** section with the bcftools substitution
types and indel-length distribution. A `Report samples` filter narrows the panels.

![Germline MultiQC](screenshots/germline-multiqc.png)

---

## Somatic indels

### Benchmark

Same funnel, tuned for somatic indels. Somatic indels are hard, so recall is low and the callers
sit to the left of the PR benchmark; the cards therefore pair a recall gauge with a precision
threshold (0.5, warn at 0.25). **Error profile** puts false positives on a log axis, because an
over-calling caller (freebayes here) emits thousands against a handful from the others.
**Allele-fraction strata** shows F1 and recall per allele-fraction bin as grouped bars, one
bar per caller.
**Confidence intervals** carries the precision and recall forest plots with som.py's binomial
95% intervals. A collapsed **rtg-tools cross-check** scores the same callers with vcfeval, and
**Reference tables** (collapsed, pinned) holds the som.py summary and strata rows.

Filters: `Callers` (caller, variant type), `Score ranges` and `Allele fraction` (AF bin).

![Somatic indel benchmark](screenshots/somatic-benchmark.png)

### MultiQC

**Report at a glance**, **som.py panels** (combined / indel / SNV, `multiqc/sompy`) and a collapsed
**Variant statistics** section with the bcftools substitution types and variant depths.

![Somatic MultiQC](screenshots/somatic-multiqc.png)

---

## Structural variants (MultiQC only)

Structural variants have no separate summary table in the pipeline: the benchmark numbers live in
the MultiQC report. **Benchmark at a glance** carries the general statistics (truvari precision /
recall / F1 and genotype concordance per callset), **truvari benchmark** pairs the
precision-vs-recall scatter with the TP / FP / FN classifications (`multiqc/truvari`), and a
collapsed **SV callset** section holds SURVIVOR's merged-callset summary and the pipeline's
variant-calling summary. Cards and native benchmark panels would need a general-statistics
recipe for truvari, which the template does not ship yet.

![Structural MultiQC](screenshots/structural-multiqc.png)

---

## Umbrella project

`dashboards/base.yaml` at the template root is the single-project variant for a data root that
holds both `small/` and `indel/` (the megatest layout). Its Overview tab carries the germline
and somatic cards and PR benchmarks side by side; a persistent, pinned `Callsets` filter section
(germline sample, somatic caller) follows the reader into the Germline and Somatic tabs, which
add the error, stratification and confidence-interval sections. The Structural & CNV tab binds
the optional Truvari / SVanalyzer / Wittyer collections and is dropped by the importer on a run
that lacks them.

---

## Benchmarking visualisation kinds

The template's benchmark tabs are built from a set of reusable, benchmarking-specific advanced-viz
kinds. Each is demonstrated as a one-viz tab of the **Advanced Visualisations** showcase dashboard
(synthetic demo data), where the gear exposes a full set of controls (colour scale, normalisation,
point size, labels, axis range).

### Precision-recall benchmark (`pr_benchmark`)

Each point is a variant caller at its (recall, precision); dotted lines are equal-F1 contours, the
diagonal is recall = precision. Top-right is best.

![Precision-recall benchmark](screenshots/advviz-pr-benchmark.png)

### ROC / PR curve (`roc_pr_curve`)

Threshold-sweep curves, one per caller, with per-curve AUC. The in-panel tab bar switches between
**PR curve** (precision vs recall), **ROC** (TPR vs FPR, with the random-classifier diagonal) and
**vs threshold** (precision and recall vs quality).

![ROC / PR curve](screenshots/advviz-roc-pr-curve.png)

### Confusion matrix (`confusion_matrix`)

TP / FP / FN per caller. Cell shade is the per-caller normalised fraction (so cells stay comparable
when TP is far larger than FP and FN); the label is the raw count, rendered with luminance-aware
contrast so it stays readable on both dark and light cells.

![Confusion matrix](screenshots/advviz-confusion-matrix.png)

### Metric ± CI forest (`metric_ci_bars`)

Point estimate + 95 % confidence interval per caller. The dot is the value, the horizontal line the
CI; the x-axis auto-zooms so tight intervals stay readable.

![Metric ± CI forest](screenshots/advviz-metric-ci-forest.png)

---

## Catalog modules

The recipes ship as catalog modules under `depictio/catalog/<tool>/`, each a full card
(`module.yaml` + `<recipe>.py` + `<recipe>.yaml` + a `.tsv` fixture). `renders_as` declares the
module → plot bindings the dashboards reference via `use:`.

`rtgtools` (vcfeval_summary) · `happy` (summary, roc) · `sompy` (summary, regions) ·
`truvari` (summary) · `svanalyzer` (svbenchmark) · `wittyer` (summary).

The MultiQC sections the pipeline emits are declared under `depictio/catalog/multiqc/`
(`happy.yaml`, `sompy.yaml`, `truvari.yaml`, next to `bcftools.yaml`), which is what lets a
MultiQC tile carry `use: multiqc/<module>` and the catalog badge.
