# nf-core/crisprseq 2.3.0 template validation report

Validated offline against the AWS megatest `results-0e9f915c4a3c89d02a66ec58e2decbc832323c8b`
(the 2.3.0 release tag, test_full profile, targeted analysis with minimap2: 6,195 single-end
amplicon libraries, 122 protospacers over 223 amplicons, no donor template). Fetched subset:
2.2 GB over 43,206 files (`bash download_test_data.sh`); the BAMs and the per-library HTML
reports (about 74 GB) are not fetched.

## Checks

| Check | Result |
| --- | --- |
| Every recipe on the megatest (`execute_recipe`, dependency order) | pass, 13 collections |
| `depictio/tests/recipes/test_crisprseq_recipes.py` | 6 passed |
| `test_shipped_dashboard_yamls.py` + `test_template_conventions.py -k crisprseq` | 18 passed, 8 warn-level notes (medians of per-library percentages) |
| `test_catalog.py` (crisprseq tool dir loads, renders validate) | pass (2 unrelated failures: committed catalog JSON schemas stale) |
| `depictio-cli run --template nf-core/crisprseq/2.3.0 --var GROUP_COL=protospacer --dry-run` | 8/8 steps |

## Collection sizes on the megatest

| Collection | Rows | Recipe time |
| --- | --- | --- |
| samples | 6195 | under 1 s |
| crisprseq_edit_summary | 6195 | about 7 s (3 x 6195 files) |
| crisprseq_edit_outcomes | 43365 | 2 s |
| crisprseq_clonality | 6195 | 3 s |
| crisprseq_indels | 1114773 | about 25 s (2.2 GB of per-read tables) |
| guide_summary | 122 | under 1 s |
| guide_outcomes | 854 | under 1 s |
| guide_alleles | 24400 | under 1 s |
| guide_indel_sizes | 19422 | under 1 s |
| guide_cut_site_profile | 24522 | 1 s |
| guide_substitution_profile | 24522 | 7 s (2 x 6195 files) |
| guide_substitutions | 122 | under 1 s |

The per-library size, position and substitution tables (249,469, 590,821 and 1,094,701 rows)
are no longer collections: the guide recipes derive them in process and keep the median
library with its interquartile band.

## Findings

- **Editing.** Median edited share 18% of classified reads per library; 20 guides are highly
  edited (median 50% and up), 69 moderately, 33 weakly. Median frameshift share of the indels
  87%. No template-based reads (no donor in this run).
- **Clonality.** 3084 libraries homozygous wild type, 1762 ambiguous, 828 homozygous and 521
  heterozygous edited; 2744 flagged low editing activity.
- **Cut site.** Main-peak indel alleles start between 60 bp before and 83 bp after the reported
  cut site (1st and 99th percentile, median 14 bp before), wider than a Cas9 cut suggests: the
  pipeline's cut-site convention may not match every guide's strand (see docs).
- **Depth.** Median 11,119 raw reads and 97.5% aligned; a handful of libraries have almost no
  reads (minimum 2 raw reads), and 48 have no aligned share in their read summary.

## Open issues

- The indel recipe holds the per-read tables of the whole run in memory before collapsing them
  (about 18 M rows here); a run much larger than this one may need a per-file reduction in the
  recipe resolver.
- Per-library profile tiles (size, substitution, gap) draw one curve per library in scope;
  without a filter that is thousands of curves. The per-guide tiles are the default reading.
- `SKIP_CLONALITY` must be set by hand; it is not introspected from `params.json`.
