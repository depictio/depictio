# nf-core/proteinfamilies 2.5.0 template validation report

Validated offline against the AWS megatest `results-f8c0b183e59df3d87c38d0f7c4acc6918593f4f5`
(the 2.5.0 release run, test_full profile: two samples of 50,000 protein sequences, one creating
families, one extending an existing family library and creating new ones). Fetched subset: 60
files, 0.42 MB (`bash download_test_data.sh`), including the ten hmmalign alignments
(`full_msa/raw/hmmer_hmmalign/*/*.sto.gz`) the profile logo maps its states with.

The live check of RULES section 15 (rendering, autofit, docking, colours, the Guide) is not part of
this report: it is done on a running stack.

## What was verified offline

| Check | Result |
| --- | --- |
| `depictio dashboard validate --offline dashboards/base.yaml` | pass |
| `test_template_conventions.py`, `test_shipped_dashboard_yamls.py`, `test_template_dc_order.py` with `-k proteinfamilies` | pass |
| `depictio/tests/recipes/test_proteinfamilies_project_recipes.py` (the `samples` hub) | 4 passed |
| Every transformed collection's recipe over the megatest, through raw scans built with the collections' `polars_kwargs` | pass, 9 collections |
| `depictio ingest --template nf-core/proteinfamilies/2.5.0 --dry-run` on the megatest | 8/8 steps, 16 collections, 0 empty, 0 missing |

The text tiles, KPI strips and open-row budgets are held by the lint above (stored text heights,
at most three sentences per paragraph, no forbidden terms, no `GROUP_COL` in a `filter_expr`).
The row budgets below are counted by hand from the stored heights.

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
| hmm_profile | 31720 (13 families, 1586 match states) |
| hmmalign_hits | 212 (members of 10 alignments; two alignments belong to families the redundancy filter removed) |

## Open rows per tab (stored heights)

| Tab | Open rows | Open sections |
| --- | --- | --- |
| Overview | 23 of 24 | hero 1, about 3, pipeline 3, key figures 3, findings 11, how to read 2 |
| Input & Clustering | 13 | 3 |
| Families | 14 | 3 |
| Members | 14 | 3 |
| Family alignment | 20 | 3 (residue table collapsed) |
| Profile HMM | 18 | 3 (family alignment and hits table collapsed) |

## Findings

- **Clustering.** About 99% of the input sequences stay singletons at the default 50% identity
  and 90% coverage; the families come from the few clusters of 5 members and more.
- **Families.** New families hold 6 to 31 members, updated existing families 26 to 67. Mean
  identity to the representative runs from about 0.44 to 0.66 and mean conservation from 0.52
  to 0.80.
- **Profiles.** All eight new families have a family HMM and an hmmalign alignment, and the
  representative sits in its alignment; its ungapped row equals the representative sequence in the
  family table for every one, so the states map onto the same residue numbering as
  `family_residues`. The five updated families have an HMM but no alignment: their logo draws,
  `position` is empty.
- **HMM information.** hmmbuild's entropy weighting holds the mean information per match state
  at 0.59 bits for every family (the median per family runs 0.59 to 0.62), and a state's
  occupancy sits near 0.98: neither tells one family from another. The Profile HMM tab shows one
  family (`always_selected`), whose match states and seed are single values, so its strip reads
  the family residue by residue (conservation, conservation class) and member by member
  (identity to the representative, length).

## Open issues

- The run's MultiQC report holds custom content only, and its SeqFu and cluster-size sections
  are named after each sample (`<sample>_before`, `<sample>_cluster_distribution`): a template
  cannot name them. Its one addressable section, the family metadata table, repeats the Protein
  families table, so the template ships no MultiQC tab and reads the source files instead.
- The 3D tiles depend on the structure resolver (`settings.structure_resolver.enabled`) and on
  ESMFold being reachable; with the resolver off they show their empty state.
- The hits table has no search statistics and `entity` is the member id, so its collapsed table is
  emptied by a residue pick (which names the family id on `entity`); the logo's lane fetches it
  without residue picks and binds neither the E-value, the score nor the alignment span, so a click
  on a bar does nothing.
- The hmmalign alignments of two families the redundancy filter removed stay in `hmmalign_hits`
  (their `label` matches no family).
- The Profile HMM tab opens on the first family of its picker (on the megatest, the first
  family the run created), which the logo, the structure and the track all follow. On a run whose first family
  is an updated one (no hmmalign alignment), a brush on the logo selects no residue until a new
  family is picked.
- Overview highlights cannot show the logo (a w4 tile holds about 30 states): the four figures are
  the cluster curves, the family landscape, the member scatter and the conservation histogram.
