# nf-core/mhcquant 3.2.0 template validation report

Validated offline against the AWS megatest `results-6ec12c97f7889a3e1f09ab89930723045c6bac68`
(the 3.2.0 release tag, test_full profile: PRIDE PXD011628, two samples with three raw
replicates each, one per condition). Fetched subset: 71 MB (`bash download_test_data.sh`).

## Checks

| Check | Result |
| --- | --- |
| Every recipe on the megatest (`execute_recipe`, dependency order) | pass, 14 collections |
| `depictio/tests/recipes/test_mhcquant_recipes.py` | 5 passed |
| `test_shipped_dashboard_yamls.py -k mhcquant` | 10 passed (catalog load with other agents' in-progress dirs skipped) |
| `test_template_conventions.py -k mhcquant` | 6 passed |
| `test_catalog.py` on the mhcquant, openms and multiqc/percolator entries | pass |
| `depictio-cli run --template nf-core/mhcquant/3.2.0 --var GROUP_COL=Condition --dry-run` | 8/8 steps |

## Collection sizes on the megatest

| Collection | Rows |
| --- | --- |
| samples | 6 |
| mhcquant_peptides | 10255 |
| mhcquant_fragment_ions | 9374 |
| mhcquant_replicate_intensity | 27864 |
| mhcquant_replicate_pairs | 25797 |
| mhcquant_replicate_detection | 9288 |
| mhcquant_source_proteins | 6574 |
| mhcquant_motif_matrix | 100 |
| peptide_condition_sharing | 9194 |
| openms_comet_psms | 6 |
| openms_comet_fdr_curve | 1200 |

## Findings

- **Identification.** Comet accepts 4000 to 5900 PSMs per raw file at 1% FDR before rescoring;
  median precursor mass error is under 0.2 ppm.
- **Signature.** Median length 9, about 70% 9-mers, every peptide inside the class I window:
  the pipeline's default length filter is 8 to 12, so the class II share is structurally zero.
- **Reproducibility.** One sample's replicate correlation is about 0.49, the other's about 0.84.
  The low value can be real or an artefact of the replicate-order assumption (see
  `docs/dashboards.md`); it could not be checked because the peptide table does not name the
  file behind each intensity column.
- **Sharing.** With one sample per condition, only 94 of 9194 sequences are found in both.

## Open issues

- The MultiQC parquet was written by MultiQC 1.33 and holds only mhcquant custom content; the
  general stats module is `stats_table`.
- `GROUP_COL` declared default does not apply: the CLI sets `__no_group__` before variable
  defaults, and metadata auto-detection picks the first non-id column. The vendored sheet is
  reordered to put `Condition` second and the help text passes `--var GROUP_COL=Condition`.
- `NO_QUANTIFICATION` and `NO_ION_ANNOTATION` must be set by hand; they are not introspected
  from `pipeline_info/params_*.json` (`quantify`, `annotate_ions`).
- `megatest.yaml` carries `forbidden_terms`, which `scripts/nfcore_megatest.py` does not yet
  accept; the fetch was run with that field removed.
