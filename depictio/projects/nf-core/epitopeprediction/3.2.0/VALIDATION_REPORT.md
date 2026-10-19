# nf-core/epitopeprediction 3.2.0 template validation report

Validated offline against the AWS megatest `results-e637bc7c49e6e05a09f5207501a142ec68d8570b`
(the 3.2.0 release tag, test_full profile, released 2026-10-15; the prefix holds three runs of
the release, the last written 2026-10-17). The test_full sheet has eleven rows on synthetic test
data, not a cohort: six VCF rows, one protein FASTA and four peptide tables, two of those
predicted against every supported allele (`HLA-all`). Tools `mhcflurry,mhcnuggets,mhcnuggetsii`,
`--wide_format_output`, `--wild_type`. Whole run: 179 objects, 19 MB; the fetched subset is 31
files, 6.1 MB (`bash download_test_data.sh`).

No running stack was available for this build: the live check of RULES section 15 is listed
below as pending, item by item.

## What was verified offline

| Check | Result |
| --- | --- |
| `depictio dashboard validate --offline dashboards/base.yaml` | pass |
| `test_template_conventions.py`, `test_shipped_dashboard_yamls.py`, `test_template_dc_order.py` with `-k epitopeprediction` | 22 passed |
| `test_advanced_viz_config_alignment.py` | 93 passed |
| `depictio/tests/recipes/test_epitopeprediction_recipes.py` (catalog recipes, both table shapes) and `test_epitopeprediction_project_recipes.py` (the `samples` hub) | 25 passed |
| `depictio dev catalog validate`, `depictio/tests/models/test_catalog.py` | pass, 106 passed |
| `depictio/tests/catalog/` | 25 passed, 4 failed: `test_conformance_project.py` wants the conformance project regenerated for the new `epitopeprediction` module (shared file, regenerated at integration) |
| Every recipe over the megatest (`execute_recipe`, input and output schemas) | pass, 9 collections, 2 s each at most |
| `epitopeprediction_predictor_summary` against MultiQC's `multiqc_peptide_binding_prediction_stats.txt` | identical binders, non-binders and unsupported for all 19 sample and tool rows |
| `depictio ingest --template nf-core/epitopeprediction/3.2.0 --dry-run` on the megatest | template resolved, 9 of 9 collections `ok`, 0 empty, 0 missing sources; stops at step 1 (no server configured) |
| Import-time pruning simulated route by route over the dashboard (components bound to a removed collection, value lines citing one, highlights whose source went, emptied sections) | see "Routes" |

The text tiles, KPI strips and section styling are held by the lint above (stored text heights,
at most three sentences per paragraph, no forbidden terms, no `GROUP_COL` in a `filter_expr`,
persistent filters reaching MultiQC, bundled section icons). The row budgets below are counted
by hand from the stored heights.

## Collection sizes on the megatest

| Collection | Rows |
| --- | --- |
| samples | 11 (6 Variants, 1 Proteins, 4 Peptides) |
| multiqc_data | 1 report: 4 custom-content sections, bcftools, general stats |
| epitopeprediction_predictions | 75,295 (58,395 from the class I `HLA-all` sample) |
| epitopeprediction_peptides | 8,563 (267 binders, 76 unsupported) |
| epitopeprediction_allele_summary | 11,705 (11,578 alleles of the `HLA-all` sample) |
| epitopeprediction_predictor_summary | 19 |
| epitopeprediction_predictor_agreement | 8,220 (mhcflurry vs mhcnuggets) |
| epitopeprediction_wildtype_pairs | 696 |
| epitopeprediction_variant_peptides | 2,097 (9 variants) |

## Routes (RULES section 13)

| Route | Result |
| --- | --- |
| Full run (the megatest: VCF, protein and peptide rows, two class I tools, `--wild_type`) | nothing dropped |
| `NO_WILD_TYPE` (no `--wild_type`, or no missense variant) | `epitopeprediction_wildtype_pairs` goes: the Mutant against wild type section of Peptides and the neoepitope findings row; the four highlights stay |
| `NO_VARIANT_INPUT` (no VCF row) | the pairs and `epitopeprediction_variant_peptides` go: the Mutant against wild type and Variant peptides sections of Peptides and the neoepitope row; the bcftools panels and general statistics of MultiQC are absent from the report and pruned by the importer's module check |
| `SINGLE_PREDICTOR` (one tool per class) | `epitopeprediction_predictor_agreement` goes: the Agreement section, its filter and table on Predictors, the Compare step, the agreement findings row and its highlight (the second findings row keeps one tile, re-flowed by the importer) |
| Peptide input, one tool | the three above together; every Key figure, every KPI strip and the Predictions tab are untouched |

The three optional collections are also `optional: true`, and their recipes raise a named error
when there is nothing to pair, so an ingest that meets such a run skips them and the importer's
`_component_has_data` gate prunes their tiles even when the variable is not passed.

## Open rows per tab (stored heights)

| Tab | Open rows | Open sections |
| --- | --- | --- |
| Overview | 21 of 24 | hero 1, about 3, pipeline 3, key figures 2, findings 10, how to read 2 |
| MultiQC | 13 | 1 (statistics 4, rank and affinity 4, binder length 4; input variants collapsed) |
| Predictions | 14 | 3 (strip 2, dot plot 6, affinity distribution 4; tables collapsed) |
| Peptides | 14 | 3 (strip 2, length 4, mutant against wild type 6; variant peptides and detail collapsed) |
| Predictors | 19 | 4 (strip 2, calls by tool 4, affinity and rank 6, agreement 6; tables collapsed) |

## Findings

- **Binders.** 267 of 8,563 peptides (3.1%) bind at least one allele; 111 of them are 9-mers,
  66 10-mers and the rest class II 12- to 15-mers. The 76 unsupported peptides are the 11-mers
  of one peptide table, a length neither class I tool scored there.
- **Alleles.** Outside the two `HLA-all` screens the samples carry one or two alleles each;
  the allele called the binder of the most peptides is the one the protein FASTA sample was
  predicted against (155 sample-level binders). Its share of the allele-level binder calls is
  under 1% on this run, because the screens' five peptides bind thousands of alleles each
  (18,227 allele-level calls in all): the findings row reads better on a cohort.
- **Tools.** MHCflurry calls 151 binders in the protein sample where MHCnuggets calls 6:
  MHCflurry calls by presentation rank (2 or less), MHCnuggets by IC50 (500 nM or less). Of the
  8,220 peptide and allele pairs both scored, 96.6% get the same call, and the median IC50 gap
  is 0.73 log10 units (a factor of about 5).
- **Mutants.** 696 mutant / wild-type pairs; 5 class II mutant peptides bind where their wild
  type does not, 35 bind with their wild type.
- **Rank scales.** MHCflurry's rank runs 0 to 100, MHCnuggets' 0 to 1 (a fraction, as the
  pipeline's docs call it experimental): the affinity against rank scatter shows two bands.

## Live check (RULES section 15): pending

None of these could be checked without a running stack; each is pending a live check.

| Item | Status |
| --- | --- |
| The Overview fits in about two screens, values fill in, highlights draw, `tab:` links open | pending live check |
| Controls dock right on full-width viz and on top of narrower ones | pending live check |
| No tile shows an empty band or a cut body; no tick label cut, no legend scrolling over tick labels | pending live check (the per-sample bars name 11 samples on the x axis) |
| The map draws its tiles and points | not applicable (no map) |
| Each dock shows a few controls and "More options"; every view switch draws | pending live check (dot plot, scatters) |
| The group has the same colour on figures, advanced viz and filter chips | pending live check |
| Every child tab opens on its intro; every KPI card draws its secondary and caption, no bar reads about 1%, each icon in its own colour | pending live check |
| The Guide's demos are not empty | pending live check |
| Each conditional route renders without a broken highlight or a stray `{VAR}` | simulated offline (above); pending live check |
| A sample picked in the left panel moves every card of a child tab | pending live check (MultiQC sample mapping on `<sample>_<tool>` and `<sample>.prep` names especially) |
| The Locus tab opens on data | not applicable (no locus tab) |

## Scenarios

**Megatest:** `s3://nf-core-awsmegatests/epitopeprediction/results-e637bc7c49e6e05a09f5207501a142ec68d8570b/`
(tag 3.2.0, run_root `.`, manifest megatest.yaml, `test_full` profile)

**MultiQC:** run wrote 1.35 -> used as-is (binding-prediction custom content plus bcftools)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| EP1 | **test_full megatest (validated offline)** | none | none | Every recipe runs on the real files, both input routes and both MHC classes; CLI dry run resolves 9 of 9 collections. |
| EP2 | **long output** | default (`--wide_format_output false`) | `predictions/` in long shape | Same collections; the long reader is covered by the recipe tests only, not by a real run. Highest-risk: no megatest writes it. |
| EP3 | **no wild type** | `--wild_type false` plus `--var NO_WILD_TYPE=1` | no WT rows | The pairs collection is pruned with its section and findings row. |
| EP4 | **peptides or proteins only** | a sheet without VCF plus `--var NO_VARIANT_INPUT=1` | no `variant_peptides/`, no bcftools | Variant peptides and pairs pruned; MultiQC bcftools panels pruned. |
| EP5 | **one tool per class** | `--tools mhcflurry` plus `--var SINGLE_PREDICTOR=1` | no pair of tools | Agreement section, row and highlight pruned. |
| EP6 | **NetMHCpan / MixMHCpred** | `--tools netmhcpan,mixmhcpred` (licensed, external) | other rank scales, MixMHCpred without IC50 | IC50 null for MixMHCpred (its predictions read `No IC50`); the agreement pairs need an IC50 on both sides to draw. |
| EP7 | **a real cohort with typed alleles** | an hlatyping run feeding `alleles` | several alleles per sample | The dot plot and allele filters gain depth; the allele cross-link to hlatyping (`TODO(wave4c)`) can be exercised. |

**Ranking by template stress:** EP2 > EP6 > EP4 > EP5 > EP3 > EP7 > EP1

## Open issues

- The megatest writes the wide shape only (`--wide_format_output true`); the long reader, the
  pipeline's default, is tested on synthetic tables, not on a real run (EP2).
- The samplesheet is not published (`pipeline_info/samplesheet.valid.csv` is documented but
  absent); the test-datasets sheet named by `params.json` is vendored unchanged under `input/`.
- `NO_VARIANT_INPUT`, `NO_WILD_TYPE` and `SINGLE_PREDICTOR` are not introspected from
  `params.json` (`wild_type`, `tools`) or the sheet; the optional collections fall back to being
  skipped at ingest when they find nothing.
- An `HLA-all` screen dominates the allele views (11,578 alleles from one sample of 5 peptides)
  and the binder-call counts; the dot plot's gene cap ranks alleles by between-sample variance,
  so alleles shared by several samples come first.
- MHCnuggets' rank is a fraction, MHCflurry's a percentage: kept as written, as the pipeline
  does, so a rank axis mixes two scales; the binder call never uses it for MHCnuggets.
- The wide summary columns (`best_value_*`, `best_allele*`, `binder`) are not read: the best
  prediction is recomputed from the per-allele values (lowest IC50, then lowest rank).
- The conformance project and the Tool Studio catalog snapshot are not regenerated here
  (shared files): `test_conformance_project.py` fails 4 tests until they are.
