# nf-core/funcscan 4.0.0: Depictio dashboards

This template turns the output of [nf-core/funcscan](https://nf-co.re/funcscan) 4.0.0 into a
single seven-tab Depictio dashboard. The pipeline screens (meta)genome assemblies with four
independent arms and aggregates each one into a single report:

| Screen | Tools | Aggregator | Headline file |
|---|---|---|---|
| ARG (resistome) | abricate, AMRFinderPlus, DeepARG, fARGene, RGI | hAMRonization | `reports/hamronization_summarize/hamronization_combined_report.tsv` |
| AMP (peptides) | ampir, Macrel, hmmsearch | AMPcombi2 | `reports/ampcombi2/Ampcombi_summary*.tsv` |
| BGC (clusters) | antiSMASH, DeepBGC, GECCO, hmmsearch | comBGC | `reports/combgc/combgc_complete_summary.tsv` |
| CAZyme | HMMER, dbCAN-sub, DIAMOND | run_dbCAN | `cazyme/dbcan/cazyme_annotation/*/*_overview.tsv` |

Data comes from the AWS megatest run
`results-aee3dc965eb0c77267435544dda30da858763913` (the 4.0.0 release tag), a 19-sample
metagenome-assembly screen of MGnify assemblies with all four arms enabled.

Every screening arm is optional in the template. A run that switched an arm off simply
prunes that arm's data collections, either automatically (the files are absent and the
collections are `optional: true`) or explicitly with `--var SKIP_ARG=true`,
`SKIP_AMP`, `SKIP_BGC`, `SKIP_CAZYME`.

---

## How the dashboard is built

Analysis controls (wave 2b): the tiles whose pickers are the analysis draw them as a header
strip under the title instead of behind the settings icon (`controls_placement: header`):
the hub scatter, the contig feature plane, the ARG dot plot, the AMP property plane and PCA,
and the BGC genome track. Every threshold `RangeSlider` shows the column's distribution
above the handles (`show_histogram: true`).

- **Hub data collection.** `screening_summary` is one row per sample with the counts each
  arm produced (`arg_hits`, `arg_genes`, `amp_candidates`, `amp_high_confidence`,
  `bgc_regions`, `bgc_classes`, `cazymes`, `cazyme_families`, `screens`). It is built by
  `funcscan/screening_summary.py`, a catalog recipe that reads the four screening
  collections through `dc_ref`, so it is declared **last** in `data_collections`: the CLI
  resolves a `dc_ref` source by reading the referenced collection back from its Delta
  table, which only exists once that collection has been processed.
- **Annotation collection.** `contig_annotation` is the same idea one level down: one row
  per contig with how many features each screen put on it, plus the contig length and
  coverage parsed out of the contig name when the assembler wrote them there (SPAdes
  `NODE_x_length_y_cov_z`, with underscores or dashes, or MEGAHIT `len=` / `multi=`
  headers). Any other naming keeps a null length: the contig stays in the table and drops
  out of the length and density axes. Every screen names the contig its feature sits on,
  so the locus layer is rebuilt from the screens without the annotation tables.
- **Links.** Every screening collection is joined to the hub on `sample`, so the
  `Sample scope` filter panel reaches all seven tabs. Four further links carry the
  Annotation tab's contig selection into the ARG, AMP, BGC and CAZyme collections, and two
  more carry a row selection: picking a gene in the hAMRonization table drives the
  per-sample dot plot, and picking a peptide in the AMPcombi table highlights it in the
  embedding.
- **Filters on every tab.** The samplesheet is `sample,fasta` and carries no experimental
  factor, so the pinned persistent `Sample scope` section holds the sample multi-select
  only. The per-screen count sliders sit in an open, landing-only `Sample thresholds`
  section, and every tab adds a non-persistent section on its own collection's columns, so
  no tab depends on the persistent panel alone.
- **Sections.** Each tab is a stack of named grid sections opened by a short text tile.
  The funnel is the same everywhere: four cards, then the signature view, then the tool
  concordance, then the rows.
- **Multi-metric cards.** Every card carries a secondary strip: `top_n` only under `sum`
  or `nunique`, Tukey `box_plot`s for per-row measures, `donut` splits and a `gauge` only
  where the maximum is fixed by the pipeline (four screens, three CAZyme annotators).
- **Catalog provenance.** Every non-text tile is bound through `use:`, so the
  tile chrome names the catalog render behind it. The cross-screen tiles that used to be
  inline now live in a `funcscan` catalog module of their own
  (`funcscan/screening_summary`, `funcscan/contig_annotation`,
  `funcscan/software_versions`, `funcscan/samplesheet`).
- **Run at a glance.** Four cards (ARG hits, AMP candidates, BGC regions, CAZyme genes),
  all `sum` with the top samples underneath, in a persistent section pinned to the top of
  every tab. No tab repeats one of them as a card. Each screen's rows are shown once, in a
  table on that screen's tab; the only pinned table is the samplesheet.
- **No MultiQC tab.** The run wrote a MultiQC 1.34 report, but funcscan feeds MultiQC
  nothing but software versions: the parquet holds a single `run_metadata` row,
  `multiqc.list_plots()` returns two modules with zero plots and `list_samples()` is
  empty, so a `multiqc` tile would render an empty figure. The `multiqc_data` collection
  stays in the template as `optional: true` for future pipeline versions, and the one
  payload the report does carry is read back out of the same parquet by
  `funcscan/software_versions.py` and shown as a table on the **Run report** tab.

---

## Screening overview (main tab)

The cross-screen tab, under the pinned **Run at a glance** strip. **Screen composition**
is a grouped, log-scaled bar of the four per-sample counts, so a sample whose resistome is
empty but whose CAZyme repertoire is large stands out. **Sample comparison** holds the
ARG-versus-CAZyme `scatter_xy` (`use: funcscan/screen_scatter`, colour the AMP candidate
count, size the BGC region count, the four largest labelled) above the hub table. Both
select on `sample`, so either narrows every other tab.

Filters: `Sample scope` (sample) pinned and persistent, plus an open, tab-local
`Sample thresholds` section (ARG hits, AMP candidates, BGC regions, CAZyme genes per
sample).

---

![Screening overview](screenshots/screening-overview.png)


## Annotation

The locus layer under the four screens. funcscan annotates each assembly once (Pyrodigal by
default) and then screens the predicted proteins four times; every screen names the contig
its feature sits on, so `contig_annotation` rebuilds the layer from the screens, one row
per contig carrying at least one feature. Contig length and coverage come from the contig
name when the assembler wrote them there (see "Annotation collection" above).

**Annotation at a glance**: total features with a per-screen top-N, annotated contigs as a
donut, contig length as a Tukey box and screens-per-contig as a gauge out of four.
**Loci** carries the `scatter_xy` of features against contig length on a log x axis
(`use: funcscan/contig_feature_scatter`), the feature-density histogram and the contig
table. A short contig high on the y axis is a dense locus rather than a long one, which is
what the density axis is for. Selecting contigs here carries into the Resistome, AMP, BGC
and CAZyme tabs through four `contig` links.

Filters: `Locus scope` (leading screen, screens on the contig) and an open
`Locus thresholds` (contig length, features per kb).

---

## Resistome

**Resistome at a glance**: drug classes (top tools underneath), distinct gene symbols,
the median identity of aligned hits (`filter_expr` drops the HMM-based hits, which report
no identity) and close reference matches (hits at 90 % identity and 80 % reference
coverage or more, per tool). **Resistance hierarchy** pairs the ARG sunburst
(`tool` to `drug_class` to `gene_symbol`) with the drug-class-by-sample heatmap
(`use: hamronization/arg_class_heatmap`). The hierarchy deliberately starts at the tool:
the five tools do not share a drug-class vocabulary, so a class-first hierarchy would
collapse into a single "unclassified" wedge. The class heatmap folds the tool
vocabularies together; the gene-level view is the dot plot under Tool concordance (the
separate gene-by-sample heatmap was dropped in wave 3, it repeated the dot plot's grid).

**Tool concordance** stacks the five-set UpSet of which tools called each gene over the
gene-by-sample dot plot (dot size = fraction of tools agreeing, colour = mean identity).
**Gene detail** is the identity-versus-coverage scatter next to the full hit table, which
row-selects on `gene_symbol` and drives the dot plot through the template link. Under both,
the contig track (`use: hamronization/arg_island_track`) draws one lane per contig and one
arrow per hit, pointing the way the gene is read: genes packed head to tail on a single
contig are a resistance island, which no aggregate over drug classes can show.

Filters: `ARG scope` (tool, drug class) and an open `Hit quality`
(identity slider, tools-agreeing slider).

---

![Resistome](screenshots/resistome.png)


## AMPs

**AMPs at a glance**: contigs carrying a candidate, the best probability across the
predictors (`prob_max`, so the card survives any predictor being switched off), peptide
length and the candidates called by two predictors or more.
**Property space** opens with the AMP property plane as a
`scatter_xy` (`use: ampcombi/amp_property_scatter`): hydrophobicity against the isoelectric
point, coloured by charge class, sized by peptide length and with a reference line at
pI 7, where a peptide turns cationic at physiological pH. AMPcombi computes no net charge
at pH 7, so the isoelectric point is the charge axis it actually reports. A candidate record
card sits beside it (`linked_component`): it stays a thin rail until a peptide is picked,
then shows its origin, per-predictor probabilities and physicochemistry. Below them sit the
AMPcombi embedding coloured by charge class and the full candidate table. The plane uses
physicochemistry rather than tool probability because a single predictor's score is
often 0 for most candidates, which would give a degenerate axis. **Clusters** holds the
cluster-size histogram and the cluster table.

Filters: `Candidate scope` (charge class) and an open `Peptide properties`
(maximum tool probability, amino-acid length).

---

![AMPs](screenshots/amps.png)


## BGCs

**BGCs at a glance**: product classes (top callers underneath), contigs carrying a
cluster, region length and CDS count. **Product classes** pairs a product-class bar with
the BGC sunburst (`tool` to `product_class`). **Caller concordance** is a contig-level
UpSet of caller agreement. Agreement is scored on the contig, not on region coordinates:
the callers disagree on boundaries by design, so a coordinate join would report no overlap
at all where the biology is the same cluster.

**Region maps** is the coordinate view of the same regions, from
`combgc/region_track.py`: the GenomeSpy track (`mark: rect`, `end_col` set to the region
end, so a row is the cluster's footprint rather than a tick at its start), the arrow track
that re-parameterises the Resistome tab's island pattern (one lane per contig, one arrow
per region), then the region table, the only BGC table on the tab (row selection on
`contig`). The genome track carries its locus field and pickers
as a header strip, and its chromosome picker (or a brush) emits a region filter on `contig`
and `start` that the arrow lanes and the table on the same collection follow. The locus
text field does not take these contig names: they contain dashes, which it reads as a
range separator. A `coverage_track` on the same rows used to sit between them as a fallback; the
wave 2b lint forbids a `coverage_track` and a `genome_view` on one collection in one tab,
and for point and interval features the genome track is the one to keep. comBGC reports no
orientation for a region, so `strand` is GFF's `.` for every row and every arrow is drawn
left to right: a drawing convention, not a strand call. The section opens on the whole
genome axis rather than a default region: every contig carries one or two regions, so no
single contig is a fair landing view.

The recipes read comBGC's run-level `combgc_complete_summary.tsv` rather than the per-sample
`reports/combgc/<sample>/combgc_summary.tsv` files, because only the run-level file carries
every caller (the per-sample files hold the antiSMASH branch alone).

Filters: `Cluster scope` (tool, product class, product class on the map) and an open
`Region size` (length, CDS count, region length on the map). The last filter in each pair
sits on `combgc_region_track`, which is a different collection from the counts above.

---

![BGCs](screenshots/bgcs.png)


## CAZymes

**CAZymes at a glance**: contigs carrying a CAZyme, families, genes with a substrate call
(`filter_expr` drops the `unassigned` substrate) and tools agreeing.
**Family hierarchy** pairs the CAZyme sunburst (`cazy_class` to `family` to `substrate`) with
a class bar. **Substrates** holds the CGC substrate-prediction bar and table.
**Tool concordance** is the three-set UpSet over HMMER, dbCAN-sub and DIAMOND, above the
full gene table.

run_dbCAN writes one overview file per sample with no sample column, so `dbcan/overview`,
`dbcan/tool_overlap` and `dbcan/substrates` read the sample from the per-sample directory
the file sits in (`RecipeSource.source_path`), falling back to the `<sample>.<contig>`
prefix of MGnify / ENA contig names, then to a single `run` pseudo-sample.

Filters: `CAZyme scope` (class, substrate) and an open `Call confidence`
(tools agreeing).

![CAZymes](screenshots/cazymes.png)

---

## Run report

What the pipeline actually ran. funcscan's MultiQC report holds a single `run_metadata` row
and no plot sections at all, so instead of an empty MultiQC panel this tab reads the
report's `software_versions` payload back out of the same parquet: one row per Nextflow
process and tool, labelled with the screen the process belongs to.

**Tools and versions** carries the tools-per-screen bar and the full versions table. A
screen that lists no tool here did not run, whatever the parameters say, which is the first
thing to check when a tab comes up empty.

Filters: `Version scope` (screen, tool).

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. The screening hub
selects on `sample`, the contig tiles on `contig`, the resistance hits on `gene_symbol`, the
AMP plane and candidate table on `cds_id`, the peptide cluster table on `cluster_id`, the BGC
tiles on `contig`, the CAZyme gene table on `family`, the substrate table on `cgc_id` and the
versions table on `tool`. The pinned sample sheet and the AMP embedding do not select: their
collections have no outgoing link, so a pick would narrow nothing.
