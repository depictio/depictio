# nf-core/crisprseq 2.3.0: validation report (template 2.1.0)

Offline validation against the AWS megatest run
`s3://nf-core-awsmegatests/crisprseq/results-0e9f915c4a3c89d02a66ec58e2decbc832323c8b/`
(the 2.3.0 release tag, `test_full` profile, targeted analysis with minimap2: 6,195 single-end
amplicon libraries, 122 protospacers over 223 amplicons, no donor template).
No server, no ingestion, no screenshots: the live check (RULES section 15) is still to do.
The 2.1.0 rework (seven tabs, editing quartiles, data-defined substitution window, new
`library_outcome_space` collection) was checked on the same subset and by the lint tests only.

## Data

- The full fetch (`bash download_test_data.sh`) is 43,206 files, 2.3 GB; the BAMs and the
  per-library HTML reports (about 74 GB) are not fetched. This pass ran on a subset of it,
  fetched with the same manifest narrowed to the files of 341 libraries: 7 guides (112, 72, 61,
  56, 16, 16 and 8 libraries, one of them written in lower case in the sheet), 2,391 files. The
  samplesheet is the vendored one, with all 6,195 libraries.
- No MultiQC report, so the template has no MultiQC tab; no samplesheet is published, so
  `input/samplesheet.csv` is the test-datasets sheet without its FASTQ paths and sequences.
- The clonality classifier wrote four zygosity classes on the subset (Hom NHEJ, Hom WT,
  Ambiguous, Het NHEJ) and five clonality labels; `category_colors` pins them, and any other
  value takes the brand colours.

## Recipe runs on the megatest subset

Run in the order the template declares them (`execute_recipe`, each `dc_ref` fed from the
previous results).

| Collection | Shape (subset) | Full run (rows) |
| --- | --- | --- |
| `samples` | 6,195 x 4 | 6,195 |
| `crisprseq_edit_summary` | 341 x 27 | 6,195 |
| `crisprseq_edit_outcomes` | 2,387 x 5 | 43,365 |
| `crisprseq_clonality` | 341 x 15 | 6,195 |
| `crisprseq_indels` | 73,586 x 14 | 1,114,773 |
| `guide_summary` | 7 x 14 | 122 |
| `guide_outcomes` | 49 x 5 | 854 |
| `guide_alleles` | 1,400 x 12 | 24,400 |
| `guide_indel_sizes` | 1,135 x 7 | 19,422 |
| `guide_cut_site_profile` | 1,407 x 11 | 24,522 |
| `guide_substitution_profile` | 1,018 x 11 | about 24,500 |
| `guide_substitutions` | 7 x 43 | 122 |
| `library_outcome_space` | 341 x 18 | about 6,065 |
| `guide_indel_size_matrix` | 7 x 61 | 122 |

The full-run row counts are those of the lot 3 pass over the whole run, except two. The
substitution profile now keeps the offsets every library of a guide reaches, which drops 671 of
18,574 rows on the local copy of the full run, and `library_outcome_space` holds the libraries
with classified reads (6,065 of 6,195 there). The others were not re-measured here. `guide_indel_sizes` and `guide_cut_site_profile` now carry `mean_*`, `median_*`, `q1_*` and
`q3_*` per value, and the dashboard draws the mean with the band from the first to the third
quartile. On the subset, the largest guide's size profile peaks at -2 bp (mean 15.2%, median
17.9%, quartiles 3.1 and 24.5) and its deletion coverage at offset -13 (mean 42%, median 58%),
which is the cut-site convention noted in `docs/dashboards.md`, not a recipe fault.

## Editing classes: the source search

The previous template labelled each guide High, Moderate, Low or Unedited at 50, 10 and 1 percent
edited. Three web searches (CRISPResso2, nf-core/crisprseq documentation and papers, amplicon
sequencing editing-efficiency guidelines) found no published cut-off between high and low
editing: the tools report the rates and leave the reading to the user. The 50/10/1 limits had no
source, so they are gone (`RULES.md` section 17). `guide_summary.edit_quartile` ranks the guides
by their median edited share in the run (Highest, Upper-middle, Lower-middle, Lowest quartile;
Not ranked with fewer than four guides), and every tile that shows it says that it is a rank
among the guides of this run, not a threshold. On the local full run the quartiles split the
122 guides 31/30/30/31, with the median edited share running 2 to 9 percent (Lowest), 9 to 19,
20 to 39 and 39 to 89 (Highest). The same rule replaced the 90 percent offset-reach window of the
substitution profile, and the "low depth, too few reads" wording on the Read QC depth scatter
(no cut-off is drawn there now).

## Checks run

- `python -m depictio.cli dashboard validate --offline dashboards/base.yaml`: passes.
- `python -m depictio.cli run --template nf-core/crisprseq/2.3.0 <data root> --var GROUP_COL=protospacer --dry-run`:
  12 collections, all sources found, 0 empty, 8/8 steps.
- `pytest -p no:cacheprovider -k crisprseq` over `test_crisprseq_recipes.py`,
  `test_template_conventions.py`, `test_shipped_dashboard_yamls.py`,
  `test_template_code_figures.py`, `test_template_dc_order.py` and `cli/utils/test_recipes.py`:
  43 passed. `test_crisprseq_recipes.py` alone has 13 tests: the guide tables (with the
  quartiles), the editing quartile on a run of eight guides and on a run of three, the library
  outcome space, the mean with its quartile band against the median, and the input schema naming
  a missing outcome column. The earlier broad run (1681 passed) was not repeated. No warn-level note: every median of a percentage carries a `filter_expr` on its
  denominator (`classified_reads`, `raw_reads` or `libraries` above 0), and the Findings value
  that reads the same quantity as the frameshift cards takes the same one.
- Catalog tests (`test_catalog.py`, `depictio/tests/catalog`): pass except the four
  `test_conformance_project.py` tests that compare the generated conformance project with the
  catalog, which the integration pass regenerates.
- Row budget (stored `h`, open sections): the estimator test passes for every tab, the Overview
  included (its How to read heading is an h2 for that reason). Tallest open section per tab:
  Read QC 6, Replicates & QC 6, Edit outcomes 9, Sample space 6, Guides 6, Indel spectrum 12,
  Substitutions 6; the Overview filter bar is 9. Text tiles checked against
  `text_layout`; section descriptions are at most 90 characters; every KPI strip is 4 cards
  w2 h2, each with its own icon and `icon_color` and a caption on its secondary.
- The four code figures (Overview guide sizes and substitution rate, Replicates & QC attrition
  and ranked libraries) were executed on the local full-run tables; each returns a figure with
  a final `fig =` line naming a dataframe. The recipes ran on the real data: the outcome PCA
  carries 42.3 percent of the variance on PC1 and 21.6 on PC2, and PC1 correlates -0.99 with the
  wild-type share, so the plane reads as "edited to the right".
- On the earlier pass, all 28 cards computed on the subset with the API's own functions (`hero_value`,
  `compute_breakdown`, `numeric_layout_payload`, `compute_box_plot_stats`): every hero and every
  secondary has a value. Two findings changed the cards: the typical substitution rate is the
  average, not the median, because the median of the guides' mean rates is 0, and the Read QC
  funnel starts at the clustered reads, because an attrition strip reads the stages after the
  card's own column.
- Pruning simulated with the import's own functions (`_prune_unresolved_text_values`,
  `_component_has_data`, `_data_bound_sections`) for the `SKIP_CLONALITY` route: the Classify
  step loses its line; on Edit outcomes the two clonality filters, the four Clonality cards and
  the clonality table go, the Clonality section is dropped whole, and the tab keeps its
  strip, scatter, record card and outcome table. Every other tab is unchanged.

## Changes against 2.0.0 (template 2.1.0)

- Seven tabs in three groups: Data & QC (Read QC, Replicates & QC), Editing (Edit outcomes,
  Sample space, Guides) and Repair signature (Indel spectrum, Substitutions). Replicates & QC
  and Sample space are new, each with its own hue; the Overview steps, how to read and links
  list the seven. No Locus tab.
- Replicates & QC: attrition per stage, the classified reads of every library ranked, and the
  25 guides whose libraries disagree most (a box of the edited share per guide, from the new
  `q1_/q3_/iqr_edited_pct` columns). Sample space: the libraries on the PCA of their outcome
  shares (`library_outcome_space`, an embedding), the outcome mix per library as stacked bars,
  with a table of the coordinates. No group comparison or outcome by
  library heatmap: seven features and 6,195 rows do not support them.
- Columns: `guide_summary` loses `edit_class` and gains `edit_quartile`, `q1_edited_pct`,
  `q3_edited_pct` and `iqr_edited_pct`; `guide_substitution_profile` keeps the same columns with
  a narrower `offset` window; `library_outcome_space` is new and linked to `samples` on the
  sample. `template.version` is 2.1.0 as requested, although a removed column is a major change
  by the versioning rule.
- Overview: the allele map and the 122 x 41 heatmap highlights became two code figures
  (dominant indel size per guide, substitution rate along the cut); the Libraries
  concentration card now reads the sample space (libraries by guide quartile), and the Guides
  quartile donut is a box plot of the guides' edited share (a donut of quartiles is equal by
  construction).
- Every KPI `icon_color` is a shade 4 to 9 of its tab hue. Guide-level charts colour by
  `edit_quartile` (a sequential ramp in `category_colors`) instead of one colour per guide.
  Sections that hold plots are open (the Allele map was collapsed); only table sections are
  collapsed.
- Every figure, advanced viz and table description is in the section 14 grammar. The cut-site
  mark (`reference_x: 0`) is explained on each profile tile: it is the pipeline's `cut_site`
  column, and its convention may be shifted by a constant for some guides.
- The tile density for the Read QC depth scatter and the frameshift scatter is 3,000 points
  before they switch to a density view.

## Not verified

- Ingestion, rendering and the live check, none of it: the Overview in two screens; the
  embedding at 6,065 points and the stacked bars at 6,065 bars of the Sample space (the
  stacked bar may want a top-N or a sort); the ranked-distribution box tile; the sandbox
  rendering of the four code figures (executed locally, not in the API sandbox); and whether a
  profile tile with no guide picked is legible.
- The Indel spectrum tab is 19 rows of small tiles; the legibility of its h5 tiles is a live
  check item.
- The recipes on the whole run were exercised on the local copy of the full run for the guide
  tables and the outcome space, not for the indel recipe's memory use (lot 3 pass only).
- `depictio/projects/template_versions.lock.json` is not regenerated here. The catalog modules
  are untouched; `catalog/crisprseq/edit_summary.yaml` still has comments that imply a verdict
  on the editing rate.
- `SKIP_CLONALITY` must be set by hand; it is not introspected from `params.json`.
