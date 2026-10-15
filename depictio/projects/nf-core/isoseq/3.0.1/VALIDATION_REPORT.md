# nf-core/isoseq 3.0.1: validation report

Offline validation against the AWS megatest run
`s3://nf-core-awsmegatests/isoseq/results-6c944831289d4d6e33497026f6b18e8c671705bd/`
(the 3.0.1 release tag, `test_full` profile: one Iso-Seq sample, one samplesheet row started from
subreads, CCS in 100 chunks, uLTRA mapping). No server, no ingestion, no screenshots: the live
check (RULES section 15) is still to do.

## Data

- Fetched with `python scripts/nfcore_megatest.py fetch --pipeline isoseq --version 3.0.1 --max-file-mb 250`
  (`bash download_test_data.sh`, which also copies the vendored design table): 287 MB, of which
  234 MB is the reference GTF uLTRA indexed. Reads, BAMs and the FASTA files (about 2.5 GB) are
  skipped: no tile reads them.
- The pipeline publishes neither its samplesheet nor a design, and the samplesheet has no design
  column: `input/sample_metadata.tsv` (`tissue`, `stage`) was written by hand for the demo.
- The MultiQC 1.33 parquet holds two modules, CCS (section "ZMWs filtered and passed") and Lima
  (sections "ZMW filtering" and "Per sample count data"), one report sample per CCS chunk (101
  samples). The MultiQC tab pins the first two sections.

## Recipe runs on the megatest

Run with `execute_recipe` in the order the template declares them, the raw BED scanned as the
template declares it.

| Collection | Rows |
| --- | --- |
| `pbccs_zmw_yield` | 1 |
| `pbccs_zmw_outcomes` | 12 |
| `isoseq_refine_summary` | 1 |
| `isoseq_insert_length` | 45 |
| `tama_polya_tails` | 94 |
| `tama_merge_bed_raw` | 25012 |
| `tama_transcripts` | 25012 |
| `tama_transcript_blocks` | 298134 (137131 isoform exons, 160003 reference exon and CDS blocks) |
| `tama_genes` | 9380 |
| `tama_category_composition` | 14 |
| `samples` | 1 |

What the data says, so the tiles are read against it: 559026 ZMWs, 428803 CCS reads (76.7 %),
405646 full-length reads, 402664 FLNC (99.3 % non-chimeric) and 331912 FLNC reads collapsed into
an isoform (82.4 %); median insert length 1 kb. 25012 isoforms in 9380 genes (6262 annotated):
NNC 32 %, intergenic 16 %, genic 16 %, FSM 15 %, ISM 12 %, NIC 7 %, antisense 2 %; by read, FSM
carries 60 %. The median isoform holds one read (5285 isoforms hold three or more), and 4273 genes
carry several isoforms, which is why the Isoforms and Genes cards count past a cut-off.

## Checks run

- `python -m depictio.cli dashboard validate --offline dashboards/base.yaml`: passes.
- `python -m depictio.cli run --template nf-core/isoseq/3.0.1 --data-root <megatest> --dry-run`,
  8/8 steps, with the design table (13 collections), without it (12) and with `SKIP_MULTIQC` (12).
- `pytest depictio/tests -k "isoseq or template_conventions or shipped_dashboard or template_dc_order or nfcore or catalog or recipe"`:
  2884 passed, 4 skipped, 5 failures, all in `test_conformance_project.py`: the conformance
  project and its MultiQC parquet are generated artefacts, regenerated once at integration (the
  regeneration with the new `ccs` and `lima` stubs makes `depictio/tests/catalog` pass, 29 tests).
  The warn-level notes of `test_no_mean_of_percentages_warn_only` for isoseq are gone: the
  cards over per-sample percentages carry a `filter_expr`.
- Every column a tile names exists in the table of its data collection, checked against the
  recipe outputs above, with the design table and without it (`__no_group__`).
- Row budget (open sections, stored `h`): Overview 23 of 24; MultiQC 9, Reads 14, Isoforms 18,
  Genes 15 of 20. Text tiles checked against `text_layout`.
- Pruning simulated with the import's own functions (`_prune_unresolved_text_values`,
  `_component_has_data`) for five routes:
  - `SKIP_MULTIQC`: the two panels go, the MultiQC tab empties and is dropped; the rest stays.
  - a run started from mapping (no CCS, refine or insert reports): the CCS and refine cards, the
    CCS outcome, the insert length curve and the two tables go; the Consensus and Refine steps and
    the CCS finding lose their lines; the Reads tab keeps the funnel, the insert length card and
    the poly(A) curve.
  - no `poly(A)` report: the poly(A) curve goes, nothing else.
  - no `METADATA_FILE`: nothing is pruned, the hub carries the one constant group.
  - the full run: nothing is pruned.

## Not verified

- Ingestion and rendering on a live stack: the highlights at w4 (insert length curves, the stacked
  categories with their legend, both planes with their legend at the bottom), the dock of the
  controls, the `attrition` and `composition` strips, the structure view of a picked gene, and
  the Guide demos.
- Whether the rank picker of the category bars reads clearly without a relabelled control (the
  rank column is the level, isoforms or FLNC reads).
- A run without `METADATA_FILE` shows a group filter with one value ("All samples").
- Novel genes are per sample (`<sample>:<TAMA gene>`): TAMA numbers genes per annotation, so the
  same novel locus in two samples is two genes unless `--tama_merge_all` is used (whose pooled
  annotation the template leaves out).
- `isoseq_insert_length` reads every FLNC read line of `*.report.csv` (a few million per SMRT cell
  on a production run) at ingestion; only the histogram is stored.
