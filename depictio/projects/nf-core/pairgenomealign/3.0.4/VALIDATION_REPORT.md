# nf-core/pairgenomealign 3.0.4 template validation report

Validated offline against the AWS megatest `results-8ee09a1cdc920fc90cd62358952045e5019e1fe0`
(the 3.0.4 release tag, test_full profile: 34 query genomes aligned to one target assembly).
The run is 42.8 GB, almost all MAF alignments; the fetched subset is 20 MB
(`bash download_test_data.sh`).

## Checks

| Check | Result |
| --- | --- |
| Every catalog recipe on the megatest (`execute_recipe`) | pass, 6 collections |
| `nf-core/pairgenomealign/genomes.py` on those outputs, with and without the optional sources | pass |
| `last/synteny_links.py` on a PSL converted from one megatest MAF (scratch, not shipped) | pass, 2000 links |
| Catalog checks (fixture grounding, recipe roles, existence) on `last`, `assemblyscan`, `seqtk` | pass |
| `test_shipped_dashboard_yamls.py` | pass |
| `test_template_conventions.py -k pairgenomealign` | pass, no warnings |
| `test_nfcore_megatest.py -k pairgenomealign` | pass |
| `depictio-cli run --template nf-core/pairgenomealign/3.0.4 --dry-run` (with and without `METADATA_FILE`) | 8/8 steps |

## Collection sizes on the megatest

| Collection | Rows |
| --- | --- |
| genomes | 34 |
| metadata | 34 |
| last_split_identity | 34 |
| last_split_matrix | 34 |
| last_train_params | 34 |
| assemblyscan_stats | 34 |
| seqtk_cutn_gaps | 33 (one assembly has no run of N) |
| seqtk_cutn_gap_lengths | 235 |
| last_synteny_links | 0 (no PSL export on this run; up to 2000 per pair otherwise) |

## Findings

- **Identity and coverage.** Identity runs from 64% to 99.8% and target coverage from 5% to
  92%, both falling with divergence time; K80 distance runs from 0.001 to 0.29.
- **Saturation.** The transition over transversion ratio falls from 2.2 to 1.4 as distance
  grows, the expected saturation signal.
- **Assemblies.** N50 is 82 to 166 Mb for every query, but sequence counts range from 19 to
  1.3 million and gap counts from 1 to 234 thousand, so coverage differences between genomes of
  similar divergence track assembly gaps.

## Open issues

- The megatest ran with `--export_aln_to no_export`, so the Synteny tab has no data on the
  reference project. The recipe was checked on a PSL converted in scratch from one MAF with a
  small converter that approximates `maf-convert psl`; a run with `--export_aln_to psl` is
  needed to confirm the real export naming (`<target>___<query>.psl.gz` is assumed from the
  module's `${meta.id}` prefix).
- The MultiQC report holds custom content only; the alignment sections name rows by pair and
  the assembly sections by genome, so two links from the hub reach them (regex on `pair`,
  sample mapping on `genome`). Whether the viewer combines two links to one MultiQC collection
  was not checked live.
- `last-dotplot` PNGs are not shown (no image upload in a template run).
