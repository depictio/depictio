# nf-core/proteinannotator 1.1.0: validation report

Offline validation against the AWS megatest run
`s3://nf-core-awsmegatests/proteinannotator/results-cbf78d471f62d91af666e8c77bcd580b4743c6be/`
(a dev run, v1.2.0dev-gb8fac19; the template directory stays at 1.1.0, the latest release).
No server, no ingestion, no screenshots: the live check (RULES section 15) is still to do.

## Data

- Fetched with `python scripts/nfcore_megatest.py fetch --pipeline proteinannotator --version 1.1.0 --max-file-mb 50`:
  36 files, 84 KB.
- Three samples, one protein each (408, 172 and 350 residues), test-sized HMM libraries,
  InterProScan with HAMAP, TIGRFAM and SFLD only. Two InterProScan TSVs are empty (no match)
  and two hmmsearch tables (Pfam and FunFam of one sample) hold only their header.
- The MultiQC parquet holds six SeqFu custom-content sections anchored by sample name
  (`<sample>_before-section-plot`, ...), so it is not read and the template has no MultiQC tab.
- No samplesheet or design is published: `input/samplesheet.csv` is the test-datasets sheet,
  `input/sample_metadata.tsv` a two-level `protein_set` design written for the demo.

## Recipe runs on the megatest

Run through the raw scans the CLI builds (the template's `polars_kwargs` over the files each
regex matches), then the catalog recipes in the order the template declares them.

| Collection | Shape |
| --- | --- |
| `seqfu_stats` | 6 x 12 |
| `seqkit_sequences` | 3 x 6 |
| `hmmer_hmmsearch_domtbl` | 94 x 25 |
| `interproscan_matches` | 1 x 13 |
| `s4pred_secondary_structure` | 930 x 10 |
| `proteinannotator_domains` | 80 x 19 (79 hmmsearch domains at i-Evalue 0.01 or less, 1 InterProScan) |
| `proteinannotator_proteins` | 3 x 20 |
| `proteinannotator_residues` | 930 x 10 |
| `proteinannotator_database_coverage` | 3 x 7 |
| `proteinannotator_database_sets` | 3 x 7 |
| `samples` | 3 x 13 |

**Entity rule.** The protein that is called `GI|225038609|EFDID|719595|FULL` in the FASTA header,
the hmmsearch table and the S4PRED file name is `GI_225038609_EFDID_719595_FULL` in all of
`seqkit_sequences`, `hmmer_hmmsearch_domtbl`, `interproscan_matches`,
`s4pred_secondary_structure`, `proteinannotator_domains`, `_proteins`, `_residues`,
`_database_coverage` and `_database_sets` (checked: the three entity sets are identical in the
S4PRED, domain, residue and protein tables). No mismatch found. A structure file named after the
protein would carry the same id through the `indexed_file` sample-id rule; the structure tile
here resolves by sequence and has no structure collection.

## Checks run

- `python -m depictio.cli dashboard validate --offline dashboards/base.yaml`: passes.
- `python -m depictio.cli run --template nf-core/proteinannotator/1.1.0 <data root> --var METADATA_FILE=... --dry-run`:
  17 collections, all sources found.
- `pytest depictio/tests -k "proteinannotator or template_conventions or shipped_dashboard or template_dc_order or nfcore"`:
  1612 passed, 4 skipped, no failure (including `test_proteinannotator_recipes.py` and the
  catalog tests of the protein tools).
- Row budget (open sections, stored `h`): Overview 23 of 24; Input filtering 14, Domains 20,
  Secondary structure 19, Structure 14 of 20. Text tiles checked against `text_layout`.
- Pruning simulated with the import's own functions (`_prune_unresolved_text_values`,
  `_component_has_data`) for three routes:
  - `SKIP_S4PRED`: the Secondary structure tab empties (every tile, its filters and its intro bind
    the S4PRED collection) and goes; the step and the finding citing S4PRED lose their lines and
    its highlight is dropped; the Structure tab keeps its sequence and domains.
  - `SKIP_INTERPROSCAN`: the "Match" step loses its line; every tab stays.
  - no `METADATA_FILE`: the design filters, the Samples card and the design table go.

## Not verified

- Ingestion, rendering, the structure resolver (ESMFold) and the new protein tiles
  (`domain_architecture`, `secondary_structure`, `sequence_track`, `molecule_3d`) on a live stack,
  and highlights of those tiles at w4 on the Overview.
- A run without `METADATA_FILE` shows three key figures (the Samples card binds the design table,
  as in the ampliseq template).
- Whether the Findings highlight of the Structure tab (the sequence track) reads well at w4.
