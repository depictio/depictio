# nf-core/rnafusion 4.1.3: Depictio dashboards

This template turns the output of [nf-core/rnafusion](https://nf-co.re/rnafusion) 4.1.3
into a single four-tab Depictio dashboard. rnafusion looks for gene fusions in RNA-seq
reads: it trims and aligns them, runs Arriba, STAR-Fusion and FusionCatcher over the same
alignment, folds the three call sets into one consensus with
[fusion-report](https://github.com/Clinical-Genomics/fusion-report), re-quantifies the
survivors against a fusion contig reference with FusionInspector, and scores the splice
junctions around them with CTAT-splicing. The template surfaces that funnel, from read
quality through to the protein a fusion would produce.

Data comes from the AWS megatest run
`results-76ad76e7c39b2ba9edc35aa3602e3dc454d842ec` (the 4.1.3 release tag).

> **The megatest is a single sample.** It is the pipeline's own test profile: one library,
> `test`, spiked with twelve well known cancer fusions. Every panel that compares samples
> is therefore degenerate on this data, and the dashboard is deliberately built so that
> almost nothing depends on the sample axis. The section
> [What a single sample costs](#what-a-single-sample-costs) names each affected panel.

---

## How the dashboard is built

- **The fusion is the unit of analysis, not the sample.** rnafusion writes one file per
  tool per sample and none of those files carries a sample column, so a caller table cannot
  be split by sample. Every fusion collection is keyed on the fusion name instead, the
  template's `links:` fan a fusion selection out across all six of them, and the samplesheet
  only reaches the MultiQC panels. On a cohort run this means the caller tables pool the
  samples: the counts are correct, but they are cohort-wide rather than per sample.
- **One funnel, four tabs.** Quality control first, then the calls, then the evidence behind
  them, then the drill-down into what survives validation. Each tab answers the question the
  previous one raises: can the reads support a call at all, what was called, how strong is
  each caller's evidence, and does the call survive re-alignment.
- **Two hubs.** `fusion_consensus` is the main one: a fusion picked anywhere narrows the
  per-caller evidence, all three caller tables, the FusionInspector validation and the Pfam
  domains at once. `fusioninspector_fusions` is the second, local to the last tab, so a
  validated call narrows its own domains and the caller evidence behind it.
- **Catalog provenance.** 42 of the 74 tiles carry a `use:` handle, so the tile chrome shows
  which catalog tool and output the panel comes from. Nine of those name an advanced-viz
  render directly and inherit its kind and column bindings from the catalog.
- **Pinned reference tables.** The rows behind every tile sit in a collapsed
  `Reference tables` section pinned to the bottom of every tab, next to a collapsed
  `Sample sheet` section pinned to the top.

### How the filters compose

Two filter sections on the main tab are `persistent` and pinned to the top, so they appear
on every tab:

| Section | Control | Collection | Reaches |
|---|---|---|---|
| `Sample filters` | `sample` MultiSelect | `samplesheet` | the MultiQC panels, through the `sample_mapping` link |
| `Fusion scope` | `fusion` MultiSelect, `tool_support` MultiSelect, `fii` RangeSlider | `fusion_consensus` | every fusion collection, through the `direct` links |

Each tab then adds its own collapsed group, which narrows that tab's own collection:

| Tab | Section | Controls |
|---|---|---|
| main | `Read QC scope` | `strandedness` |
| Fusion calls | `Consensus scope` | `rank`, `n_databases` |
| Evidence | `Evidence scope` | `caller`, `supporting_reads`, `evidence_fraction` |
| FusionInspector and splicing | `Validation scope` | `prot_fusion_type`, `ffpm` |
| FusionInspector and splicing | `Splicing scope` | `chrom`, `uniq_mapped` |

The two layers intersect. Picking `tool_support = 3 callers` in the persistent group and
`caller = arriba` in `Evidence scope` leaves Arriba's rows for the unanimous fusions only.

Splice junctions are the deliberate exception: CTAT-splicing scores introns of a single
gene, so a fusion name has nothing to match there and `splice_junctions` is left unlinked.
The `Splicing scope` group is the only thing that narrows it, which is why the four junction
cards keep their values when a fusion is picked.

### Selection wiring

Two scatters and nine tables are selectable, all on the same key so a pick in one narrows
the others:

- `Arriba against STAR-Fusion` (Evidence) and `Fusion allelic ratio, both sides`
  (FusionInspector) both select on `fusion`;
- the three caller tables, the consensus table, the Pfam domain table and the three pinned
  reference tables all row-select on `fusion`;
- the pinned `Run samplesheet` table row-selects on `sample`;
- the junction Manhattan selects on `gene`, which stays inside the splicing section for the
  reason above.

---

## Quality control (main tab)

Nine MultiQC panels, read before any fusion is trusted. A fusion call rests on reads that
crossed a breakpoint, so a library that never aligned well cannot support one.

`Alignment at a glance` carries the MultiQC general statistics table, STAR's alignment
scores (`use: multiqc/star`) and Picard's transcript region assignment
(`use: multiqc/picard`). `Read quality` pairs the raw FastQC quality histograms with
fastp's filtered-read bars (`use: multiqc/fastp`) and the post-trim FastQC per-sequence
quality scores. `Library metrics`, collapsed by default, holds Picard's insert size
distribution and gene body coverage plus STAR's gene count assignment.

rnafusion runs FastQC twice, before and after trimming, so MultiQC anchors the second
instance as `fastqc-1`, and its samples carry a `_trimmed` suffix. The template's MultiQC
collection lists both spellings so a run with a single FastQC invocation still binds. See
[What a single sample costs](#what-a-single-sample-costs) for what that suffix does to the
sample filter.

## Fusion calls

What the run called, and how much agreement is behind each call.

`Calls at a glance` is a full card row on `fusion_consensus`, four different strips: fusions
called as a donut by caller agreement, the median Fusion Indication Index as a Tukey box
plot, mean callers per fusion on a gauge, and mean knowledge base hits with the top
databases beside it. All four bind `use: fusionreport/fusions`.

`Caller concordance` holds the two signature panels. The UpSet
(`use: fusionreport/caller_upset`) reads the three caller flag columns as sets, so each bar
is the fusions found by exactly that combination of callers, coloured by degree: unanimous
calls separate from single-caller ones at a glance. The lollipop
(`use: fusionreport/fii_lollipop`) plots each fusion at its rank with the index as the stem
height, coloured by agreement.

`Ranked calls` is the consensus table itself, the hub: picking rows here drives every other
tab.

## Evidence

The same fusions seen through each caller's own read counts.

`Support across callers` opens with four cards on `caller_evidence`
(`use: fusionreport/caller_evidence`): fusions with evidence as a composition by caller, the
median supporting reads as a box plot, total read support as a donut by caller, and the mean
caller share against a threshold. The dot plot below
(`use: fusionreport/evidence_dot_plot`) is one dot per fusion and caller, colour being
log10 read support and size that caller's share of the fusion's total support, so an empty
column means the caller never reported the fusion. The code-mode scatter beside it pivots
the long evidence table so the two split-read callers face each other on one plane, with
FusionCatcher riding along as the marker size: a fusion far off the diagonal is one the two
callers disagree about.

`Per caller detail` gives each caller its own dot plot on its own terms, because the three
report different things: Arriba clusters by its confidence class
(`use: arriba/evidence_dot_plot`), STAR-Fusion by splice type
(`use: starfusion/evidence_dot_plot`), FusionCatcher by predicted effect
(`use: fusioncatcher/evidence_dot_plot`).

`Caller tables`, collapsed, holds the three raw caller tables, each row-selectable by
fusion.

## FusionInspector and splicing

What survives when the reads are re-aligned to a fusion contig reference, and what the
junction landscape around the calls looks like.

`Validated calls` carries four cards on `fusioninspector_fusions`
(`use: fusioninspector/fusions`): validated fusions with the top predicted protein types
beside them, median fragments per million as a box plot, mean junction-crossing share on a
gauge, and total 5' domains carried as a composition by protein type. The dot plot
(`use: fusioninspector/evidence_dot_plot`) clusters by predicted protein type.
The code-mode scatter plots the fusion allelic ratio of the 5' side against the 3' side on
log axes: a call supported on one side only falls off the diagonal, which is the classic
signature of a mapping artefact rather than a real fusion transcript.

`Fusion protein domains` answers what the fusion protein would keep. The code-mode interval
track draws one translucent bar per Pfam domain, placed at its amino acid start and as wide
as the domain, overlaid rather than stacked because Pfam clans report many overlapping hits.
The lollipop beside it (`use: fusioninspector/domain_lollipop`) places each domain at its
start position with the hit strength as the stem, coloured by which partner it came from.
A domain name ending in `PARTIAL` is one the breakpoint cuts through.

`Splice junctions` closes the funnel with four cards on `splice_junctions`
(`use: ctatsplicing/introns`): junctions scored with the top genes beside them, median
unique read support as a box plot, total reads across junctions as a donut by chromosome,
and mean intron length as a histogram. Below them, a Manhattan of junction support along the
genome (`use: ctatsplicing/intron_manhattan`, selectable by gene) and a per-gene support bar
coloured by strand.

---

## What a single sample costs

The megatest is one library, so these panels are correct but have nothing to compare:

| Panel | What degenerates |
|---|---|
| `Sample filters`, `Read QC scope` | one option each, so the filter can only select all or nothing |
| `Run samplesheet` | one row |
| `Reads kept by fastp`, `STAR alignment scores`, `STAR gene-count assignment`, `Insert size distribution`, `Coverage along the gene body`, `Where the bases landed` | one series per panel |
| `General statistics` | five rows, but they are one sample's read files, not five samples |
| the whole per-caller pooling described above | invisible here, because there is only one sample to pool |

The fusion tabs are unaffected: the UpSet and the dot plots compare **callers**, not
samples, and every filter acts on a fusion attribute.

Two consequences of the sample naming are worth knowing before reading the QC tab. MultiQC
sees five sample ids (`test`, `test_1`, `test_2`, `test_trimmed_1`, `test_trimmed_2`) which
canonicalise to two, `test` and `test_trimmed`. The samplesheet only knows `test`, so
picking it in the persistent `Sample filters` empties the `Trimmed read quality` tile and
drops the post-trim series from the raw FastQC tiles. Leave the sample filter clear on this
run; on a real multi-sample run the same applies to the trimmed panels only.

The fusions are also synthetic. Twelve of the twenty are textbook cancer fusions that all
three callers find and two knowledge bases already list, so their Fusion Indication Index is
exactly 1.0, and the remaining eight are one two-caller call and seven single-caller IGH and
DUX4 artefacts at 0.167. The score is therefore bimodal and saturated: the lollipop reads as
two flat plateaux rather than a ranking, the index box plot sits with its median at the
maximum, and the UpSet is dominated by a single intersection of size twelve. On a real
tumour run all three spread out.

`cancer_introns` is empty on this run: CTAT-splicing's cancer intron annotation filter
matched nothing, so the file is a bare header. The collection is declared optional, the
ingest skips it with a message, and no tile depends on it.

---

## Catalog modules

The recipes ship as six catalog tools, each a folder with `module.yaml` plus
`<output>.py` / `<output>.yaml` / `<output>.tsv` triples:

| Tool | Output | What it is | Renders as |
|---|---|---|---|
| `fusionreport` | `fusions` | One row per fusion with its knowledge base hits, index, per caller flags and rank | UpSet, lollipop, bar, 4 cards, table |
| `fusionreport` | `caller_evidence` | One row per fusion and caller with the read support that caller reported | Dot plot, 4 cards, table |
| `arriba` | `fusions` | Arriba calls with split reads, discordant mates, coverage, confidence, reading frame | Dot plot, cards, table |
| `starfusion` | `fusions` | STAR-Fusion calls with junction and spanning counts, splice type, normalised abundance | Dot plot, cards, table |
| `fusioncatcher` | `fusion_genes` | FusionCatcher genes with spanning pairs, unique reads, anchor length, predicted effect | Dot plot, cards, table |
| `fusioninspector` | `fusions` | The calls re-quantified against a fusion contig reference, with allelic ratios | Dot plot, 4 cards, table |
| `fusioninspector` | `protein_domains` | Pfam domains of both partners in amino acid coordinates, one row per domain | Lollipop, cards, table |
| `ctatsplicing` | `introns` | Every junction CTAT-splicing scored, with unique and multi-mapped support | Manhattan, 4 cards, table |
| `ctatsplicing` | `cancer_introns` | Junctions matching the CTAT cancer intron catalog, with TCGA and GTEx prevalence | Manhattan, cards, table |

The MultiQC modules rnafusion emits are covered by shared entries under
`depictio/catalog/multiqc/`: `fastqc` and `fastp` already existed, `star` and `picard` were
added with this template. That is what lets a MultiQC tile carry `use: multiqc/<module>`
and the catalog badge.

---

## Reproducing

```bash
# 1. Fetch the megatest subset (20 files, about 3.9 MB)
bash depictio/projects/nf-core/rnafusion/4.1.3/download_test_data.sh
# equivalently:
python scripts/nfcore_megatest.py fetch --pipeline rnafusion --version 4.1.3 \
  --dest ~/Data/depictio-nfcore/rnafusion/4.1.3/megatest

# 2. The run does not publish its samplesheet, so fetch the one params.json points at
DEST=~/Data/depictio-nfcore/rnafusion/4.1.3/megatest
mkdir -p "$DEST/input" && curl -fsSL -o "$DEST/input/samplesheet.csv" \
  https://raw.githubusercontent.com/nf-core/test-datasets/rnafusion/testdata/human/samplesheet_valid.csv

# 3. Validate the template against the data without ingesting
depictio-cli run --template nf-core/rnafusion/4.1.3 --data-root "$DEST" --dry-run

# 4. Ingest for real (needs a reachable server and ~/.depictio/CLI.yaml)
depictio-cli run --template nf-core/rnafusion/4.1.3 --data-root "$DEST"
```

Do not pass `--project-name`: the dashboard's `project_tag` is resolved by name, so
renaming the project makes the dashboard import fail. Re-running accumulates dashboards, so
delete the project first if you need to redo a run.

A run that skipped a step needs the matching variable, because rnafusion's route flags are
not auto-detected from `params.json`:

```bash
depictio-cli run --template nf-core/rnafusion/4.1.3 --data-root "$DEST" \
  --var SKIP_FUSIONCATCHER=true --var SKIP_CTATSPLICING=true
```

`SKIP_ARRIBA`, `SKIP_STARFUSION`, `SKIP_FUSIONCATCHER`, `SKIP_FUSIONINSPECTOR`,
`SKIP_CTATSPLICING` and `SKIP_QC` each prune the matching data collections and the tiles
that read them. `SAMPLESHEET_FILE` overrides where the samplesheet is looked for.

`VALIDATION_REPORT.md` next to this file records the ingestion numbers, the tile-by-tile
verification and the discrepancies found while validating.
