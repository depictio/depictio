# nf-core/crisprseq 2.3.0: validation report

Offline validation against the AWS megatest run
`s3://nf-core-awsmegatests/crisprseq/results-0e9f915c4a3c89d02a66ec58e2decbc832323c8b/`
(the 2.3.0 release tag, `test_full` profile, targeted analysis with minimap2: 6,195 single-end
amplicon libraries, 122 protospacers over 223 amplicons, no donor template).
No server, no ingestion, no screenshots: the live check (RULES section 15) is still to do.

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

The full-run row counts are those of the lot 3 pass over the whole run: the per-guide profiles
gained a mean column and kept their rows, so the counts did not move. They were not re-measured
here. `guide_indel_sizes` and `guide_cut_site_profile` now carry `mean_*`, `median_*`, `q1_*` and
`q3_*` per value, and the dashboard draws the mean with the band from the first to the third
quartile. On the subset, the largest guide's size profile peaks at -2 bp (mean 15.2%, median
17.9%, quartiles 3.1 and 24.5) and its deletion coverage at offset -13 (mean 42%, median 58%),
which is the cut-site convention noted in `docs/dashboards.md`, not a recipe fault.

## Checks run

- `python -m depictio.cli dashboard validate --offline dashboards/base.yaml`: passes.
- `python -m depictio.cli run --template nf-core/crisprseq/2.3.0 <data root> --var GROUP_COL=protospacer --dry-run`:
  12 collections, all sources found, 0 empty, 8/8 steps.
- `pytest depictio/tests -k "crisprseq or template_conventions or shipped_dashboard or template_dc_order or nfcore"`:
  1681 passed, 4 skipped, no failure. That includes `test_crisprseq_recipes.py` (9 tests: the
  guide tables, the mean with its quartile band against the median, and the input schema naming
  a missing outcome column) and `test_bundled_recipe_structure` for the fifteen crisprseq
  recipes. No warn-level note: every median of a percentage carries a `filter_expr` on its
  denominator (`classified_reads`, `raw_reads` or `libraries` above 0), and the Findings value
  that reads the same quantity as the frameshift cards takes the same one.
- Catalog tests (`test_catalog.py`, `depictio/tests/catalog`): pass except the four
  `test_conformance_project.py` tests that compare the generated conformance project with the
  catalog, which the integration pass regenerates.
- Row budget (open sections, stored `h`): Overview 23 of 24; Read QC 10, Edit outcomes 12,
  Guides 15, Indel spectrum 16, Substitutions 15 of 20. Text tiles checked against
  `text_layout`; section descriptions are at most 90 characters; every KPI strip is 4 cards
  w2 h2, each with its own icon and `icon_color` and a caption on its secondary.
- All 28 cards computed on the subset with the API's own functions (`hero_value`,
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

## Changes against the lot 3 template

- Overview and tab family rebuilt on the family rules: hero, About and run cards, pipeline
  flow, four key figures, four findings with a highlight each, how to read; three tab groups
  (Data & QC, Editing, Repair signature); `category_colors`, `filter_panel_default`,
  `content_width_default` and `show_tab_header` on the main tab; no `advanced_viz_controls`.
  The pinned strip, the pinned samplesheet and the "Reference tables" section are gone: the
  samplesheet and the per-library summary sit in the Sample sheet section at the bottom of
  every child tab.
- The tab order follows the funnel: Guides (all guides) now comes before Indel spectrum and
  Substitutions (one guide), as the second tab of the Editing group.
- The per-guide size and position profiles are drawn as the mean with the interquartile band.
- The tab-local Guide pickers are plain selects; `always_selected` is not in this branch (see
  `docs/dashboards.md`, "Filters and the guide pickers").
- The Overview scope filter, the glance strip and the per-tab intro sections were dropped; each
  child tab has one unsectioned intro and a boxed KPI strip.

## Not verified

- Ingestion, rendering and the live check: whether the Overview fits in two screens, whether the
  four highlights read at w4 (the guide by offset heatmap with 122 rows and 41 offset labels, and
  the allele map with up to 24,400 points, are the two to look at), and whether a profile tile
  with no guide picked (122 curves with their bands) is legible enough or wants the pickers to
  hold one guide.
- The recipes on the whole run (6,195 libraries, 1.1 million alleles): the memory use of the
  indel recipe, which holds the per-read tables of the run before collapsing them, was measured
  on the lot 3 pass only.
- `SKIP_CLONALITY` must be set by hand; it is not introspected from `params.json`.
