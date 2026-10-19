# nf-core/stableexpression 1.1.0 template validation report

Validated offline against the AWS megatest `results-d6b1654c4784332cbad71f1d928cc8b75a77272f`,
a complete `test_full` run (species `homo_sapiens`, every Expression Atlas experiment of it)
written 2026-07-16 by a development build: `software_versions.yml` reads
`nf-core/stableexpression: v1.0.0-gd6b1654`, Nextflow 26.04.6. The prefix holds 908 objects /
3.9 GB (1802 keys with the zero-byte directory markers); the fetched subset is 177 files /
358 MB, 341 MB of it the merged matrix (`bash download_test_data.sh`).

**Why a non-tag pin** (mag 5.5.0 and rnavar 1.3.0 precedent). The 1.1.0 release prefix
`c4cbf824...` (2026-10-07) is empty: five `pipeline_info/` files. The 1.0.0 release sha
`f0313431...` has no prefix. `d6b1654c...` is the only run of the pipeline in the bucket.
`nfcore_megatest.py fetch` warns "pinned results-d6b1654c4784 is release ?, not the 1.1.0 release
sha (c4cbf8247139); keeping the pin", as intended. The template directory stays 1.1.0, the
latest release. The run's `params.json` uses the 1.1.0 parameter names throughout.

**How the run differs from the 1.1.0 output docs**
(<https://nf-co.re/stableexpression/1.1.0/docs/output>, read 2026-10-19):

| Docs (1.1.0) | Pinned run | Effect on the template |
| --- | --- | --- |
| `reporting/multiqc_report.html` (custom content: gene tables and boxes per section, dataset statistics, filtering, ID mapping, downloads) | absent: the trace shows `MULTIQC` FAILED three times | no MultiQC collection, no MultiQC tab |
| `reporting/dash_app/` (Plotly Dash app) | absent: `DASH_APP` FAILED (the module ignores its errors) | used as the design reference only, from the 1.1.0 sources and docs images |
| `idmapping/` | `id_mapping/` (as the 1.1.0 code writes it: `storeDir "${outdir}/id_mapping/"`; the docs are stale) | not read |
| `statistics/`, `errors/`, `warnings/` not described | published (the 1.1.0 code writes them too) | read by the dataset collections |
| `annotation/<name>.gff3.gz` | only `annotation/gene_transcript_lengths.csv` | not read |
| `accessions/geo/` | absent (`fetch_geo_accessions: false`) | not read |
| `datasets/<platform>/<normalisation>/<dataset>/{0..4}.*/` with `3.tpm_normalised` or `3.cpm_normalised` | as documented (`3.tpm_normalised`, `normalisation_method: tpm`) | only the per-dataset `*.design.csv` is read |

No running stack was available for this build: the live check of RULES section 15 is listed
below as pending, item by item.

## What was verified offline

| Check | Result |
| --- | --- |
| `depictio dashboard validate --offline dashboards/base.yaml` | pass |
| `test_template_conventions.py`, `test_shipped_dashboard_yamls.py`, `test_template_dc_order.py` with `-k stableexpression` | 22 passed, no warning |
| `test_advanced_viz_config_alignment.py`, `test_catalog.py` | pass |
| `depictio/tests/recipes/test_stableexpression_recipes.py` (catalog recipes on a synthetic run, the no-ID-mapping and no-geNorm shapes) and `test_stableexpression_project_recipes.py` (the `samples` hub) | 15 passed |
| `depictio/tests/recipes/`, `depictio/tests/catalog/` | 741 passed, 4 failed: `test_conformance_project.py` wants the conformance project regenerated for the new `stableexpression` module (and the other wave-4 modules); shared file, regenerated at integration |
| `depictio dev catalog validate` | 125 tools valid |
| Every recipe over the megatest (`execute_recipe`, input and output schemas) | pass, 9 collections, 1.2 s at most; peak memory 1.3 GB for the two recipes that read the 341 MB matrix |
| Every dashboard binding (column, breakdown, attrition stages, figure axes, viz roles, record-card fields, text values and their weights and filters) against the recipe outputs | all resolve |
| `depictio ingest --template nf-core/stableexpression/1.1.0 --dry-run` on the megatest | template resolved, 9 of 9 collections `ok`, 0 empty, 0 missing sources; stops at step 1 (no server configured) |
| The parts of the stability score against the score | the recovered weights are 0.25 x 4 (the run's `stability_score_weights`); parts add up to the score within 1e-6 |
| `stable_gene_distribution` with its `counts` source pointed at `all_counts.imputed.parquet` | runs; every gene has all 4330 values |
| Import-time pruning simulated for `NO_ID_MAPPING` | see "Routes" |

The text tiles, KPI strips and section styling are held by the lint above (stored text heights,
at most three sentences per paragraph, no forbidden terms, no `GROUP_COL` in a `filter_expr`,
bundled section icons). The row budgets below are counted from the stored heights.

## Collection sizes on the megatest

| Collection | Rows |
| --- | --- |
| samples | 4,332 (2,989 Microarray, 1,343 RNA-seq; 2 RNA-seq samples `Filtered out`) |
| stableexpression_dataset_summary | 162 (118 microarray, 44 RNA-seq; 140 merged, 21 no gene mapped, 1 all samples filtered out) |
| stableexpression_dataset_funnel | 648 (162 datasets x 4 steps) |
| stableexpression_id_mapping | 648 (162 datasets x 4 fates) |
| stableexpression_gene_statistics | 40,980 |
| stableexpression_gene_stability | 2,500 (10 sections x 250 candidates) |
| stableexpression_score_components | 12,500 (2,500 x 5 parts) |
| stableexpression_stable_gene_distribution | 250 (25 per section) |
| stableexpression_stable_gene_values | 48,070 (2 per section, measured values only) |

## Routes (RULES section 13)

| Route | Result |
| --- | --- |
| Full run (the megatest) | nothing dropped |
| `NO_ID_MAPPING` (`--skip_id_mapping`) | `stableexpression_id_mapping` goes: every data tile of the ID mapping tab (four cards, three figures, the table, both filters), so the tab is dropped whole; the Overview's Map step line (it cites `n_ids`) goes with it. The How to read tile keeps a bare `ID mapping` label. The dataset collections count every dataset as mapped. The collection is also `optional: true`, and its recipe raises a named error without `statistics/id_mapping_stats.csv`, so an ingest skips it even when the variable is not set. |
| `--skip_genorm` | no variable: geNorm M is null and its part 0 (tested); the geNorm card prints a dash and the Normfinder against geNorm M scatter (and its Overview highlight) is empty |

## Open rows per tab (stored heights)

| Tab | Open rows | Open sections |
| --- | --- | --- |
| Overview | 22 of 24 | hero 1, about 3, pipeline 3, key figures 2, findings 11, how to read 2 |
| Datasets | 14 | intro 2, strip 2, funnel and outcomes 4, dataset profile 6; table and record collapsed |
| ID mapping | 8 | intro 2, strip 2, fate by platform and by share 4; per-dataset bars and table collapsed |
| Ranking | 14 | intro 2, strip 2, ranked distribution 5, per-sample violins 5; table collapsed |
| Candidates | 14 | intro 2, strip 2, score parts 4, Normfinder against geNorm 6; table and record collapsed |
| Sections | 14 | intro 2, strip 2, two boxes 4, mean against CV 6; table collapsed |

## Findings

- **Datasets.** 162 datasets downloaded (5,087 samples). 21 microarray datasets (746 samples)
  map no gene id: 18 on the Affymetrix Gene ST design `A-AFFY-141`, whose numeric probe ids
  g:Profiler does not know, plus `A-MEXP-2246` (2) and `A-GEOD-16686` (1). One RNA-seq dataset
  loses its 9 samples to the zero filter. 140 datasets and 4,330 samples reach the matrix.
- **Gene ids.** 5.03 M ids in, 86% kept as genes, 10.6% unmapped, 2.0% rare genes, 1.0%
  collapsed. A microarray sample misses 62% of the matrix's genes (median), an RNA-seq sample 1%.
- **Ranking.** The best gene of each section is measured, in the merged matrix, by 55% of the
  samples (median); the Section 01 leader by 31% (RNA-seq samples only) and the Section 07
  leader by 16 samples (0.4%), the rest imputed. Drawn from measured values, a gene measured
  by few samples shows a narrow box from little data, which the pipeline's own imputed boxes
  hide.
- **Candidates.** The missing-value penalty is 72% of the summed scores. In Sections 01 to 07
  the median candidate is measured by 2 to 4% of the samples (1,938 of the 2,500 candidates
  are measured on microarrays only), so the penalty, not the four stability measures, decides
  most of the ranking; Sections 08 to 10 have the best median scores. Worth raising with the
  pipeline: the candidate pre-selection of this development build favours sparsely measured
  genes.
- **The most stable candidate** is a long intergenic non-coding RNA of Section 09 (score
  0.470), measured by 87% of the samples.

## Live check (RULES section 15): pending

None of these could be checked without a running stack; each is pending a live check.

| Item | Status |
| --- | --- |
| The Overview fits in about two screens, values fill in, highlights draw, `tab:` links open | pending live check |
| Controls dock right on full-width viz and on top of narrower ones | pending live check (every advanced viz is w8) |
| No tile shows an empty band or a cut body; no tick label cut, no legend scrolling over tick labels | pending live check (the per-dataset fate bars name 162 datasets on the x axis, collapsed) |
| The map draws its tiles and points | not applicable (no map) |
| Each dock shows a few controls and "More options"; every view switch draws | pending live check (ranked distribution Top N, scatters) |
| The group has the same colour on figures, advanced viz and filter chips | pending live check |
| Every child tab opens on its intro; every KPI card draws its secondary and caption, no bar reads about 1%, each icon in its own colour | pending live check (the two attrition strips especially) |
| The Guide's demos are not empty | pending live check |
| Each conditional route renders without a broken highlight or a stray `{VAR}` | simulated offline (above); pending live check |
| A sample picked in the left panel moves every card of a child tab | pending live check; by design it moves the dataset tabs and the per-sample violins only, the gene tabs have no sample axis |
| The Locus tab opens on data | not applicable (no locus tab) |
| The ranked distribution with 250 pre-aggregated rows (default Top N 10, a section filter, a gene click reaching the violins) | pending live check |

## Scenarios

**Megatest:** `s3://nf-core-awsmegatests/stableexpression/results-d6b1654c4784332cbad71f1d928cc8b75a77272f/`
(not a release tag: development build `v1.0.0-gd6b1654`, written 2026-07-16; run_root `.`,
manifest megatest.yaml, `test_full` profile, `homo_sapiens`)

**MultiQC:** none published (the run's `MULTIQC` task failed); the template reads none

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| SE1 | **test_full megatest (validated offline)** | none | development build, no MultiQC report, no Dash app | Every recipe runs on the real files; CLI dry run resolves 9 of 9 collections. |
| SE2 | **a 1.1.0 release run** | `-profile test_full` on 1.1.0 | MultiQC report and Dash app published, possibly other candidate selection | Nothing read changes; a MultiQC custom-content collection could be added. Highest-value re-run: the bucket has none. |
| SE3 | **skip ID mapping** | `--skip_id_mapping` plus `--var NO_ID_MAPPING=1` | no `statistics/id_mapping_stats.csv`, original ids kept | ID mapping tab and Map step pruned; tested on the recipes only. |
| SE4 | **skip geNorm** | `--skip_genorm` | no geNorm column | geNorm card and the Normfinder against geNorm scatter empty; tested on the recipes only. |
| SE5 | **user datasets** | `--datasets <csv>`, `--skip_fetch_eatlas_accessions` | datasets named by the user, possibly without the `datasets/` directory layout | accessions are the dataset ids; a missing directory falls back to the platform guessed from the id (tested). |
| SE6 | **one platform** | a species with RNA-seq only | one `platform` value | every group split has one segment; nothing pruned. |
| SE7 | **other section settings** | `--nb_sections 5 --nb_candidates_per_section 100` | fewer sections | the section ramp colours the first five; `TOP_PER_SECTION` caps at the candidates. |
| SE8 | **a smaller species** | `-profile test` (Prunus persica) or `test_dataset_eatlas` (Mus musculus, user datasets) | a few datasets | quick end-to-end ingest on a laptop. |

**Ranking by template stress:** SE2 > SE5 > SE3 > SE4 > SE7 > SE6 > SE8 > SE1

## Open issues

- The pinned run is a development build two months older than 1.0.0; no release run exists
  in the bucket (1.1.0 empty, 1.0.0 absent). Re-validate on a 1.1.0 `test_full` run (SE2).
- The 1.1.0 MultiQC report (custom content only) is not read; there is no MultiQC tab.
- The stability score is a cohort statistic: the persistent sample filters reach the dataset
  tabs and the per-sample violins, never the gene tabs, which filter by their own gene filters.
  The Key figures bar narrows the dataset and sample cards only.
- The Key figures filter bar holds the group then the dataset, not the sample (4,332 public
  sample ids; the sample filter is in the left panel).
- The two distribution recipes read the 341 MB matrix whole (the recipe framework reads a
  source eagerly): 1.3 GB peak memory at ingest.
- `TOP_PER_SECTION` and `VALUES_PER_SECTION` are template variables, not pipeline parameters;
  the ranked distribution's `max_features` is 500 (raise it past 20 sections of 25).
- The `rank_weight` column exists to let a text value name the most stable gene (`top` picks
  the largest summed weight); the `section` ramp is written out for ten sections.
- The conformance project and the Tool Studio catalog snapshot are not regenerated here
  (shared files): `test_conformance_project.py` fails 4 tests until they are.
