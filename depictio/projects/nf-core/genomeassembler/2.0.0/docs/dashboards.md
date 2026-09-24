# nf-core/genomeassembler 2.0.0: Depictio dashboards

One dashboard, five tabs, read as a funnel: **Overview -> Stages -> Contiguity
-> Genome profile -> Accuracy and genes**. The pipeline writes no MultiQC
report, so the landing tab is an Overview built from the QC tools' own files.

The unit is the assessed assembly, named `<sample>_<stage>` by every QC tool:
the raw assembly, each polishing step (medaka, dorado, pilon) and each
scaffolder (LINKS, longstitch, RagTag). One sample therefore contributes up to
five rows. Samples whose assembly never reached QC stay visible in the
collapsed sample sheet as `No assembly QC` and appear in no other tile.

A pinned strip of four cards rides every tab: samples (split by QC status),
design groups (`{GROUP_COL}`), assemblers and stages assessed. The sample
filters (sample id and `{GROUP_COL}`) are persistent and reach every data
collection through the samplesheet links.

## Design variables

| Variable | Default | Role |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/samplesheet.csv` | the pipeline samplesheet |
| `METADATA_ID_COL` | `sample` | joins the sheet to `<sample>_<stage>` |
| `GROUP_COL` | `strategy` | the design column the filters and the parallel coordinates colour on |
| `GROUP_COL_DISPLAY` | `Strategy` | its label |

The samplesheet's `assembler`, `assembler_ont`/`assembler_hifi` and
`scaffold_*` columns become `assembler_used` and `scaffolders`; every other
sheet column is passed through to `assemblies` and `sample_status`.

## Tabs

**Overview.** Four cards (assemblies assessed, best Merqury QV, best BUSCO
complete, the GenomeScope genome size estimate), a parallel-coordinates plot
over N50, L50, length, sequence count, QV, k-mer completeness and BUSCO, the
N50 against QV scatter coloured by assembler with the assembly record card beside
it (`linked_component`, a thin rail until a point is picked), and the BUSCO class bars. Local filters: stage
class, assembler, QV range.

**Stages.** Routes from each sample's raw assembly through polishing to each
scaffolder (`stage_steps`). Two profiles track QV and the N50 fold change
along each route; a group comparison contrasts two stage classes metric by
metric.

**Contiguity.** Nx curves computed from the samtools idxstats sequence
lengths of every assessed assembly, then QUAST's reference-free and, when the
run had a reference, reference-based views.

**Genome profile.** GenomeScope's heterozygosity, repeat share, model fit and
read error rate, and the jellyfish k-mer spectrum it fits.

**Accuracy and genes.** Merqury QV against k-mer completeness, the copy-number
composition of the read k-mers in each assembly, per-sequence QV, and BUSCO
complete against duplicated.

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. Every per-assembly
tile (the Overview scatter and table, the QUAST, Merqury and BUSCO scatters and tables)
selects on `assembly_id`, the per-sequence QV scatter on `sequence`, the stage profiles and
route table on `route`, the GenomeScope table on `read_set` and the pinned sample sheet on
`sample`. The QUAST length ladder and the k-mer spectrum do not select: their collections
have no outgoing link and no sibling tile. The Nx curve emits a selection but reaches no
other tile.

## Data collections

| Tag | Source | Catalog |
| --- | --- | --- |
| `samplesheet` | `METADATA_FILE` | |
| `assemblies` | idxstats + Merqury + BUSCO + QUAST reference, joined | pipeline recipe |
| `nx_curve` | `*/QC/alignments/*.idxstats` | pipeline recipe |
| `stage_steps` | `assemblies` | pipeline recipe |
| `sample_status` | samplesheet + `assemblies` | pipeline recipe |
| `merqury_assembly_qv` | `*.qv`, `*.completeness.stats` | `merqury/assembly_qv` |
| `merqury_sequence_qv` | `<prefix>.<asm>.qv` | `merqury/sequence_qv` |
| `merqury_copy_number` | `*.spectra-cn.hist` | `merqury/copy_number_composition` |
| `busco_batch_summary`, `busco_composition` | `*-busco.batch_summary.txt` | `busco/*` |
| `quast_assembly_report`, `quast_length_ladder`, `quast_reference_report` | `transposed_report.tsv` | `quast/*` |
| `genomescope_summary` | `*_genomescope.txt` | `genomescope/summary` |
| `jellyfish_histogram` | `*_hist.tsv` | `jellyfish/histogram` |

Every tool data collection is optional: a run without a reference, without
short reads or without a given QC tool loads with those tiles empty.
