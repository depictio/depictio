# nf-core/isoseq 3.0.1 template validation report

Validated offline against the AWS megatest `results-6c944831289d4d6e33497026f6b18e8c671705bd`
(the 3.0.1 release tag, test_full profile: one Iso-Seq sample, one samplesheet row started from
subreads, CCS in 100 chunks, uLTRA mapping). Fetched subset: 286 MB, of which 234 MB is the
reference GTF (`bash download_test_data.sh`).

## Checks

| Check | Result |
| --- | --- |
| Every recipe on the megatest (`execute_recipe`, dependency order, raw BED scanned as the template declares) | pass, 11 collections |
| `depictio/tests/recipes/test_isoseq_recipes.py` | 6 passed |
| `test_shipped_dashboard_yamls.py -k isoseq` | 10 passed |
| `test_template_conventions.py` (isoseq parameters) | pass; 3 warn-level notes (median of per-sample percentages) |
| `test_catalog.py` | pass except the two committed JSON schema checks (model changes of another agent) |
| `depictio-cli run --template nf-core/isoseq/3.0.1 --dry-run`, with and without `METADATA_FILE` | 8/8 steps |

## Collection sizes on the megatest

| Collection | Rows |
| --- | --- |
| samples | 1 |
| metadata | 1 |
| pbccs_zmw_yield | 1 |
| pbccs_zmw_outcomes | 12 |
| isoseq_refine_summary | 1 |
| isoseq_insert_length | 45 |
| tama_polya_tails | 94 |
| tama_merge_bed_raw | 25012 |
| tama_transcripts | 25012 |
| tama_transcript_blocks | 298134 (137131 isoform exons, 160003 reference exon and CDS blocks) |
| tama_genes | 9380 |
| tama_category_composition | 14 |

## Findings

- **Funnel.** 559026 ZMWs, 428803 CCS reads (76.7 %, most losses for lacking full passes),
  405646 FL, 402664 FLNC (99.3 % non-chimeric), 331912 FLNC reads collapsed into a final
  isoform (82.4 %). Median insert length about 1 kb.
- **Transcriptome.** 25012 isoforms in 9380 genes (6262 annotated). By isoform: NNC 32 %,
  intergenic 16 %, genic 16 %, FSM 15 %, ISM 12 %, NIC 7 %, antisense 2 %. By read FSM carries
  60 %: the novel categories are many rare isoforms. The reference is an old assembly
  annotation, which inflates NNC and intergenic.
- **Poly(A).** Tails removed by TAMA are 0 to 10 nt: refine already clipped them.
- Classification of the megatest (25k isoforms against 30k reference transcripts) runs in
  about 1.5 s; the GTF read dominates.

## Open issues

- `tama_merge_bed_raw` is a raw scan (the file-name regex tells `<sample>.bed` from the
  per-chunk collapse BEDs); its rows are persisted like any table.
- `isoseq_insert_length` reads every FLNC read line of `*.report.csv` (a few million per SMRT
  cell on a production run) at ingestion; only the histogram is stored.
- Novel genes are per sample (`<sample>:<TAMA gene>`): TAMA numbers genes per annotation, so the
  same novel locus in two samples is two genes unless `--tama_merge_all` is used (whose pooled
  annotation the template leaves out).
