# nf-core/proteinfold 2.1.0 template validation report

Validated offline against the AWS megatest `results-a414fd1368009500b66761e37e7cde80366a45e9`
(a 2.1.0 development run, `v2.1.0dev-ga414fd1`; the 2.0.0 release run is empty): eleven
test_full runs gathered under one prefix, AlphaFold2 (standard and split-MSA), ColabFold,
ESMFold and RoseTTAFold All-Atom on two monomer targets, AlphaFold2 multimer and ESMFold on
one heterodimer. Fetched subset: 79 files, 10 MB (`bash download_test_data.sh`), with the
top-ranked PAE matrix of each engine and target only.

The live check on a running stack (RULES.md section 15: every tab opened, tile heights, the
Overview highlights, the linked structure tiles) is not part of this report.

## Checks

| Check | Result |
| --- | --- |
| `depictio dashboard validate --offline dashboards/base.yaml` | pass |
| Every catalog recipe and both project recipes on the megatest (glob sources as the CLI reads them, schemas exact) | pass, 8 collections |
| `depictio/tests/recipes/test_proteinfold_recipes.py` (recipes, project recipes, the template's PAE and structure sample regexes, its scores scan) | 15 passed |
| `test_shipped_dashboard_yamls.py`, `test_template_conventions.py`, `test_template_dc_order.py` `-k proteinfold` | 22 passed |
| `pytest depictio/tests -k "proteinfold or template_conventions or shipped_dashboard or template_dc_order or nfcore"` | 1656 passed, 4 skipped |
| `depictio-cli run --template nf-core/proteinfold/2.1.0 --data-root <megatest> --dry-run` | 8/8 steps, 11 collections, 0 empty, 0 missing sources |
| Every `use:` handle of the dashboard resolves to its catalog entry | pass |
| PAE and structure ids on the megatest | the 9 matrices carry the id of their structure; the 3 structures without a matrix are ESMFold's |

## Deliberate deviations from RULES.md

- `content_width_default: wide` (1600 px) instead of the family's `compact`: the Overview's
  3D structure and PAE matrix tiles and the Structure tab's 3D-over-sequence tile read too
  tight at 1080 px. The Findings highlights stay w4 (two per 8-column row, 24-row budget kept).
- A link resolves to the first declared link of a pair of collections, so residues to
  structure scores is its own link on `target`, while residues to the alignment and the PAE
  matrix stay on `entity` (a target pick reaches them by translation).

## Row budgets (stored heights, stored at the 8-column grid)

| Tab | Open rows | Open sections |
| --- | --- | --- |
| Overview | 23 | Hero, About, Pipeline, Key figures, Findings, How to read |
| Model scores | 13 | 3 |
| Structure | 19 | 3 (the alignment and the residue table are collapsed) |
| Predicted error | 14 | 3 |
| Engines comparison | 17 | 3 (the model table and record are collapsed) |

## Collection sizes on the megatest

| Collection | Rows |
| --- | --- |
| targets | 3 |
| proteinfold_structures | 12 objects |
| proteinfold_pae_matrices | 9 objects |
| proteinfold_residues | 3350 |
| proteinfold_engine_plddt | 2310 |
| proteinfold_scores_raw | 105 |
| proteinfold_models | 60 |
| proteinfold_structure_scores | 12 |
| proteinfold_plddt_ranks | 2260 |
| proteinfold_pae | 576 (9 matrices) |
| proteinfold_msa | 543 (9 alignments) |

## Findings

- The two AlphaFold2 modes give near-identical models on this run; ColabFold ranks higher on the
  harder monomer, where AlphaFold2 with the reduced test databases folds from a one-row MSA.
- The heterodimer's interface scores are low (ipTM near 0.1, ipSAE 0), a real negative the
  Predicted error tab shows as pale off-diagonal blocks.
- RoseTTAFold All-Atom writes pLDDT as a 0 to 1 fraction in its PDB B-factors; the residue table
  rescales it to 0 to 100.
- ESMFold numbers the second chain of a complex from 665 (its chain linker offset); the
  residue table keeps the structure's numbering so the 3D tile can pick residues by it.
- ColabFold numbers its models from 1 and the others from 0: the PAE scan keeps `_1_` for
  ColabFold and `_0_` for the rest, so each matrix carries the id of its engine's top-ranked
  structure and AlphaFold2's runner-up (`_1_`) is never uploaded.

## Open issues

- The megatest `params.json` is the latest of the eleven runs, so `{{param:mode}}` on the
  Overview prints that one run's mode (`colabfold`); on a single real run it lists the engines
  requested.
- The Structure and Engines comparison tabs read one target and the Predicted error tab one
  structure (`always_selected`, see `docs/dashboards.md`, "Single-unit pickers"). On the
  megatest they open on the heterodimer (AlphaFold2 multimer and ESMFold only) and on its
  AlphaFold2 structure; the live check should pick a monomer target too (five engines).
