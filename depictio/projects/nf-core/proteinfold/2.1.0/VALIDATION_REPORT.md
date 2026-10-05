# nf-core/proteinfold 2.1.0 template validation report

Validated offline against the AWS megatest `results-a414fd1368009500b66761e37e7cde80366a45e9`
(a 2.1.0 development run, `v2.1.0dev-ga414fd1`; the 2.0.0 release run is empty): eleven
test_full runs gathered under one prefix, AlphaFold2 (standard and split-MSA), ColabFold,
ESMFold and RoseTTAFold All-Atom on two monomer targets, AlphaFold2 multimer and ESMFold on
one heterodimer. Fetched subset: 36 MB (`bash download_test_data.sh`).

## Checks

| Check | Result |
| --- | --- |
| Every catalog recipe and the hub on the megatest (glob sources as the CLI reads them) | pass, schemas exact |
| `depictio/tests/recipes/test_proteinfold_recipes.py` | 9 passed |
| `depictio/tests/unit/recipes/test_msa_lib.py`, `test_protein_structure_lib.py` | 14 passed |
| `test_shipped_dashboard_yamls.py`, `test_template_conventions.py` | pass |
| proteinfold catalog tool loaded in isolation, fixtures grounded against the recipes | pass |
| `depictio-cli run --template nf-core/proteinfold/2.1.0 --dry-run` | 8/8 steps |

## Collection sizes on the megatest

| Collection | Rows |
| --- | --- |
| targets | 3 |
| proteinfold_structures | 12 objects |
| proteinfold_residues | 3350 |
| proteinfold_engine_plddt | 2310 |
| proteinfold_scores_raw | 105 |
| proteinfold_models | 60 |
| proteinfold_plddt_ranks | 2260 |
| proteinfold_pae | 576 (9 matrices) |
| proteinfold_msa | 543 (9 alignments) |

## Findings

- The two AlphaFold2 modes give near-identical models on this run; ColabFold ranks higher on the
  harder monomer, where AlphaFold2 with the reduced test databases folds from a one-row MSA.
- The heterodimer's interface scores are low (ipTM near 0.1, ipSAE 0), a real negative the
  PAE tab shows as pale off-diagonal blocks.
- RoseTTAFold All-Atom writes pLDDT as a 0 to 1 fraction in its PDB B-factors.
- ESMFold numbers the second chain of a complex from 665 (its chain linker offset); the
  residue table keeps the structure's numbering so the 3D tile can pick residues by it.
