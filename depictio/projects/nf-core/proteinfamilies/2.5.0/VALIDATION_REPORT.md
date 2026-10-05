# nf-core/proteinfamilies 2.5.0 template validation report

Validated offline against the AWS megatest `results-f8c0b183e59df3d87c38d0f7c4acc6918593f4f5`
(the 2.5.0 release run, test_full profile: two samples of 50,000 protein sequences, one creating
families, one extending an existing family library and creating new ones). Fetched subset: 49
files, 273 KB (`bash download_test_data.sh`).

## Checks

| Check | Result |
| --- | --- |
| Every recipe on the megatest, through raw scans built with the collections' `polars_kwargs` | pass, 9 collections |
| `test_shipped_dashboard_yamls.py -k proteinfamilies` | 10 passed |
| `test_template_conventions.py -k proteinfamilies`, `test_nfcore_megatest.py -k proteinfamilies` | 9 passed |
| `test_catalog.py` | pass except the two committed JSON schema checks (stale from the protein kind registration) |
| `depictio-cli run --template nf-core/proteinfamilies/2.5.0 --dry-run` | 8/8 steps |
| `use:` coverage | 31 of 36 non-text, non-filter tiles |

## Collection sizes on the megatest

| Collection | Rows |
| --- | --- |
| samples | 2 |
| sequence_stats | 4 |
| cluster_sizes | 13 |
| families | 13 (8 new, 5 updated) |
| family_members | 384 |
| family_msa | 384 |
| family_residues | 1593 |
| family_trees | 1395 (8 trees) |

## Findings

- **Clustering.** About 99% of the input sequences stay singletons at the default 50% identity
  and 90% coverage; the families come from the few clusters of 5 members and more.
- **Families.** New families hold 6 to 31 members, updated existing families 26 to 67. Mean
  identity to the representative runs from about 0.44 to 0.66 and mean conservation from 0.52
  to 0.80.
- **HMM information.** hmmbuild's entropy weighting holds the mean information per match state
  at 0.59 bits for every family, so it is not reported.

## Open issues

- The MultiQC report holds custom content only, and its SeqFu and cluster-size sections are named
  after each sample (`<sample>_before`, `<sample>_cluster_distribution`): a template cannot name
  them, so the MultiQC tab shows the family metadata table alone and the tiles read the source files.
- One tree per family cannot be served by a phylogeny collection (one Newick file per
  collection), so the trees are drawn from a segment table by a code figure; the `phylogenetic`
  kind is not bound.
- The 3D tile depends on the structure resolver (`settings.structure_resolver.enabled`) and on
  ESMFold being reachable; with the resolver off it shows its empty state.
- The protein kind renderers were placeholders when this template was written; the tiles were
  validated against their configs, not rendered.
- `SKIP_PHYLOGENETIC_INFERENCE` must be set by hand; it is not introspected from
  `pipeline_info/params_*.json` (`skip_phylogenetic_inference`). Both tree collections are also
  `optional`.
