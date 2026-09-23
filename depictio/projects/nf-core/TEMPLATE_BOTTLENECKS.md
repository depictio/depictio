# What blocks and limits nf-core templating in Depictio

Companion to `MEGATEST_STATUS.md`. That file records what the **AWS megatest bucket**
publishes. This one records what **Depictio itself** lacks, found while building the
lot-1 templates (differentialabundance 2.0.0, funcscan 4.0.0, airrflow 5.1.0,
rnafusion 4.1.3, rnaseq 3.26.0, taxprofiler 2.0.1, chipseq 1.2.0, atacseq 1.2.2 and
cutandrun 3.1) against real runs.

Every item below was hit in this lot, not predicted. Each says what happened, why it
costs, and the smallest fix that would remove it. Items are ordered by how much they
cost to work around.

## 1. Recipes cannot see which file a row came from

`_resolve_glob_source` in `depictio/recipes/__init__.py` reads each file a glob matches
and concatenates them with `pl.concat(..., how="diagonal_relaxed")` **without a
per-file label**, and `pl.read_csv` has no `include_file_paths` parameter. A data
collection **scan** does not have this problem, because it uses `pl.scan_csv`, which
does.

So any pipeline output whose sample identity lives in the **path** rather than in a
column cannot be attributed inside a recipe:

- run_dbCAN writes `cazyme_annotation/<sample>/<sample>_overview.tsv`. The funcscan
  recipes recover the sample from the assembly-accession prefix of the gene id. That is
  correct for funcscan only, and is a per-pipeline workaround, not a mechanism.
- DESeq2 writes `<contrast>.deseq2.results.tsv`, with the contrast **only** in the file
  name. differentialabundance works around it by declaring a `_raw` collection scanned
  with `polars_kwargs: {include_file_paths: source_path}` and a tidy collection that
  reads it through `dc_ref`. That doubles the collection count and adds an ordering
  constraint (item 3).

**Smallest fix:** a `file_column` option on `RecipeSource`, or have
`_resolve_glob_source` always add a path or stem column. One change removes two
workarounds and the extra collections.

**2026-09-22 check.** Polars 1.43 still has no `include_file_paths` on `read_csv`
(only on `scan_csv`), so the raw-scan plus `dc_ref` pair remains the only way for a
recipe to learn sample or caller from a file name; sarek's variant tables, eager's
lane ledger and hic's HiC-Pro stats all pay the extra collection. `melon/ranks`
(taxprofiler) cannot be linked at all until it does the same.

**2026-09-23 check (wave 2b).** cutandrun's fragment pile-up needed the sample from
`<sample>.frags.cut.bed` and pays the same price: `seacr_frags_raw` is a 7 M-row raw
scan whose only job is to carry `source_path` into `seacr/frags_profile`. A
`file_column` on `RecipeSource` would have made that one recipe reading four files.

## 2. `optional: true` is not honoured on a glob source

`RecipeSource(optional=True)` is respected for `path` and `dc_ref` sources.
`_resolve_glob_source` raises unconditionally when nothing matches. A recipe whose
optional inputs are globs therefore hard-fails instead of degrading, so optionality has
to be pushed up to the template level (prune the whole collection) even when the recipe
could have produced a smaller frame.

## 3. `dc_ref` makes declaration order load-bearing, silently

A `dc_ref` source is resolved by reading the referenced collection back from **its Delta
table in S3** (`depictio/cli/cli/utils/deltatables.py`), which exists only once that
collection has been processed. Two consequences, neither visible in the schema:

- the referenced collection must be declared **before** the one that reads it;
- ingestion must stay sequential (`DEPICTIO_INGEST_DC_WORKERS` unset).

funcscan hit this with its `screening_summary` hub and had to move it last in
`data_collections`. The failure message names the reading collection, not the ordering.

**Smallest fix:** topologically order the collections by their `dc_ref` edges at ingest
time, or fail validation with an explicit ordering error.

## 4. Catalog loading is all-or-nothing

`load_catalog_entries()` raises `ValueError: invalid catalog entry
depictio/catalog/<tool>` when a folder holds recipes but no `module.yaml`. There is no
per-folder skip, so **one** half-written tool makes every `use:` in **every** shipped
dashboard unresolvable at once. During this lot that broke ampliseq, viralrecon,
variantbenchmarking and three in-flight templates simultaneously, with an error naming
only the unrelated folder.

**Smallest fix:** skip and warn on an incomplete folder instead of raising, or validate
folders independently so one bad tool cannot take the catalog down.

## 5. `find` is one glob per output, and `**` is one segment

`PurePosixPath.match` treats `**` as a single path segment, and `full_match` (which does
not) is Python 3.13 only while CI runs 3.12.9. The shipped
`**/multiqc/multiqc_data/multiqc.parquet` globs therefore cannot match rnaseq's
`multiqc/star_salmon/multiqc_report_data/multiqc.parquet`.

This lot added `CatalogFind.path_glob_alt`, a list of alternates tried in turn. It works,
but it means every new nesting depth a pipeline invents is another literal alternate in
sixteen YAML files.

**Smallest fix:** a matcher where `**` spans segments, applied to a single `path_glob`.

## 6. Every new MultiQC section needs a hand-written stub

The conformance project synthesises a MultiQC report covering every `section` the
catalog declares, from `STUB_BUILDERS` in
`depictio/projects/init/catalog_conformance/scripts/multiqc_stubs.py`. A section with no
stub is not fatal, but it is recorded as an **exemption** and stops being covered. This
lot adds fifteen MultiQC catalog entries (bracken, centrifuge, deeptools, dupradar,
featurecounts, kaiju, metaphlan, nanoq, nonpareil, picard, preseq, qualimap, rseqc,
salmon, star) against fifteen pre-existing builders, so the stub file must roughly
double for coverage to keep up.

## 7. Depictio has no MultiQC version gate, only a filename regex

Depictio reads `multiqc.parquet` and nothing else. That name is MultiQC >= 1.31 (1.30
wrote `BETA-multiqc.parquet`, older releases wrote none). The template's scan regex is
the **only** gate, so a run from an older MultiQC surfaces as a missing data collection
with no diagnosis. chipseq 1.2.x published MultiQC 1.9 and had to be reprocessed with
the pinned 1.35 before it could be templated at all.

Two follow-on hazards:

- a reprocessed report's **anchors and plot names differ** from the original, so
  `dc_specific_properties.modules` / `plots` authored against the old report silently
  mismatch. `multiqc.reprocess: true` in the manifest is what makes this visible.
- a run can publish a parquet that is technically valid but **empty**: funcscan 4.0.0
  writes a single `run_metadata` row with no general-stats table and no module sections,
  because the pipeline feeds MultiQC nothing but software versions.

**Smallest fix:** read the parquet's `multiqc_version` at ingest and report a too-old or
module-less report as a named condition rather than as an absent file.

## 8. The standalone dashboard import is bound to the project name

`validate_schema_online` in `depictio/cli/cli/commands/dashboard.py` resolves the
dashboard's `project_tag` through `/projects/get/from_name/{name}`, and `--project/-p`
does **not** override that lookup. So a project created under any other name cannot take
a re-imported dashboard, and the error is a bare `HTTP 404` naming the tag.

`depictio-cli run` step 8 does not have this problem: it passes the id of the project it
just created. The two paths disagree, which is what makes the failure confusing.

A smaller wart in the same command: the import summary prints the component count of the
**main** dashboard only ("Components: 14") while it actually writes every tab in the
file.

## 9. Seeding is not part of templating yet

None of the seven templates ships `.db_seeds`, `STATIC_IDS` or `db_init` registration, so
none of them appears on a fresh deployment. The export-then-remap flow that would produce
those seeds is the one variantbenchmarking still lacks, and export-derived seeds churn
component indices on every re-import. This is the single largest gap between "the
template ingests" and "the template ships".

## 10. Visualisation kinds the life-science outputs actually wanted

No new `advanced_viz` kind was added in this lot. Every tile either binds one of the 22
existing kinds or falls back to a code-mode figure, and the 27 code-mode figures across
the nine templates are the evidence for what is missing.

Lot 2 (sarek 3.10.0, scrnaseq 4.2.0, mag 5.5.0, nanoseq 3.0.0, eager 2.4.5, methylseq 2.3.0,
hic 2.0.0) is the lot that closed part of that gap: three new kinds, `contact_map`,
`knee_plot` and `damage_profile`, plus a new `mark` setting on `coverage_track`. All four
were designed GenomeSpy-ready from the start (issue #1083: coordinate-bound rows carry a
chromosome/start pair now, so a later GenomeSpy track renderer needs no schema change), see
`dev/advanced_viz_kinds/genomespy_handoff.md` for the row contracts and the mark mapping,
including the two kinds (`knee_plot`, `damage_profile`) that are out of GenomeSpy's scope
because their rows are not coordinate-bound.

### Per pipeline

| pipeline | kinds bound | code-mode figures | what a kind would replace |
|---|---|---|---|
| differentialabundance 2.0.0 | volcano x2, ma, qq, da_barplot, manhattan, lollipop, embedding, complex_heatmap x2 | 1 | nothing, the contrast-against-contrast scatter only wants UI-mode size and `custom_data` |
| funcscan 4.0.0 | sunburst x3, upset_plot x3, complex_heatmap, dot_plot, embedding, gene_arrow_track | 4 | nothing, all four are plain bars and scatters |
| airrflow 5.1.0 | complex_heatmap x2, rarefaction, sankey, stacked_taxonomy, sunburst, upset_plot, metric_ci_bars | 5 | diversity profile with confidence ribbons, rank abundance |
| rnafusion 4.1.3 | dot_plot x5, lollipop x2, manhattan, upset_plot, fusion_structure, sashimi | 2 | nothing left; the domain track is now `fusion_structure` |
| rnaseq 3.26.0 | embedding, complex_heatmap | 1 | nothing, and the gene-body coverage profile stays a MultiQC panel |
| taxprofiler 2.0.1 | stacked_taxonomy x2, sunburst, dot_plot x2, complex_heatmap, embedding, upset_plot | 1 | rank-abundance accumulation |
| chipseq 1.2.0 | volcano, ma, qq, da_barplot, manhattan, complex_heatmap, upset_plot | 2 | nothing in the template, because the deepTools profile is left in MultiQC |
| atacseq 1.2.2 | volcano, ma, qq, da_barplot, complex_heatmap, dot_plot, upset_plot | 6 | TSS signal profile, fragment-length ladder |
| cutandrun 3.1 | manhattan x2, upset_plot, dot_plot | 4 | fragment-length ladder |
| sarek 3.10.0 | dot_plot (caller-comparison, `bcftools/stats_summary`) | 3 | nothing, the three per-caller SNP/indel/Ts-Tv bars are plain grouped bars |
| scrnaseq 4.2.0 | `knee_plot` (new), embedding x3, da_barplot | 1 | nothing, the PCA scree plot is a plain bar |
| mag 5.5.0 | scatter_xy x8, profile x2, sunburst, sankey x2, stacked_taxonomy, gene_arrow_track | 0 | resolved on 2026-09-22: the old row was written against a truncated S3 sync with no report tables |
| nanoseq 3.0.0 | complex_heatmap x2, volcano/ma/qq, volcano/qq | 0 | n/a, every dense tile already binds an existing kind |
| eager 2.4.5 | profile (preseq complexity curve), `damage_profile` (new) | 3 | nothing for two of the three (mapped-reads and mean-coverage bars are plain); the misincorporation line duplicates the `damage_profile` advanced-viz tile in the same section, display redundancy rather than a missing kind |
| methylseq 2.3.0 | profile (Bismark M-bias, CpG context) | 3 | nothing, three plain grouped bars (alignment efficiency, dedup rate, per-context methylation) |
| hic 2.0.0 | `contact_map` (new), profile (distance decay), coverage_track x2 (new `mark` setting: A/B compartment track, insulation score) | 0 | n/a, hic has no plotly-express figure tile at all: every dedicated-tab visualisation is a kind or a MultiQC panel |

**2026-09-22 update.** The table above is the initial-build snapshot. The remediation wave added five kinds (`genome_view`, `group_compare`, `transcript_structure`, `cnv_profile`, `genome_chord`, see `docs/design/advanced-viz.md` section 7) and rebuilt the lot 2 dashboards around them: sarek 2 to 6 tabs (VCF-level UpSet, lollipop, oncoplot and `genome_view` on mosdepth regions), eager 5 to 8 (scatter_xy x5, profile x4, sankey, `genome_view`), methylseq 3 to 8 (binned methylome: embedding, complex_heatmap, volcano, `genome_view`), nanoseq 3 to 7 (embedding, complex_heatmap, `transcript_structure` gated), hic 4 to 7 (`genome_view` x3, `contact_map` triangle, sankey, profile x2), scrnaseq 8 to 9 (`group_compare` on a cell x marker-gene matrix), mag 2 to 7. Lot 1 gained `genome_view` on peaks and BGC regions (chipseq, atacseq, cutandrun, funcscan), `genome_chord` on Arriba fusions (rnafusion) and the DESeq2 QC sample space (rnaseq, chipseq, atacseq).

### What those 27 figures are

- **12 scatter plots.** They are in code mode for `custom_data`, a marker size column or a
  reference diagonal, not because the shape is exotic. This is a figure-builder gap, not a
  missing kind: a UI-mode scatter that accepts a size column and a selection key would
  retire all twelve and shrink every template in the lot.
- **7 bars, boxes and histograms.** Same story, minus the selection: grouped bars on a log
  axis and a histogram split by a category are both one `dict_kwargs` away.
- **6 profile curves.** The real gap, detailed below.
- **1 protein-domain track** (rnafusion FusionInspector) and **1 log-scale stage line**
  (airrflow attrition, which the sankey beside it already tells).

### Candidates, split by how far they travel

The useful axis is not "which pipeline asked for it" but how much of the kind is shape and
how much is domain. Depictio already mixes the two, and it shows: `dot_plot` carries scRNA
role names (`cluster`, `gene`, `mean_expression`, `frac_expressing`) yet is bound nine
times in this lot and not once for scRNA, while `rarefaction` has exactly the shape of a
multi-series curve (`sample_id`, `depth`, `metric`) and cannot be reused for a TSS profile
because its name and renderer assume an accumulation.

#### Reusable well beyond these pipelines

**1. `profile`: multi-series curve over an ordered axis.** BUILT, and bound in chipseq and
atacseq through `preseq/complexity_ribbon`, `deeptools/metagene_profile`,
`homer/tss_distance`, `ataqv/fragment_length` and `ataqv/tss_coverage`. Roles `series`,
`x`, `y`, with optional `lower` and `upper` for a band; config for a reference marker at
x = 0, shaded x-ranges and log axes. Six code-mode figures in four pipelines collapse
into it:

| figure | pipeline | x axis |
|---|---|---|
| `at-sig-fig-tss` | atacseq | signed offset from a TSS |
| `at-sig-fig-ladder` | atacseq | fragment length, sub-nucleosomal bands |
| `cr-qc-fig-fragments` | cutandrun | fragment length, same bands |
| `airr-clone-fig-ribbons` | airrflow | diversity order q, bootstrap band |
| `airr-clone-fig-rank` | airrflow | clone rank, log-log |
| `tp-fig-accumulation` | taxprofiler | taxon rank, cumulative |

It also unlocks data already on disk that nothing reads: rnaseq `rseqc/inner_distance/`
and gene body coverage, chipseq and atacseq deepTools `plotProfile`, and airrflow
`clonal_abundance.tsv` (AF-D1), whose absence is why the rank-abundance panel plots a point
estimate with no ribbon. `rarefaction` becomes a special case of it. Outside genomics the
same shape covers any timecourse, dose response or sweep, which is what makes this the one
clear win.

The cheap fallback, if the kind is not built: add optional `lower` and `upper` roles to
`rarefaction`. That alone retires `airr-clone-fig-ribbons`.

**2. `agreement_matrix`: pairwise concordance between tools.** Takes (item, tool, called)
and draws the Jaccard matrix plus the per-sample agreement scatter against the diagonal.
Recurs everywhere: cutandrun MACS2 against SEACR, rnafusion across three callers,
funcscan across three ARG tools, taxprofiler across ten profilers, and variantbenchmarking
outside this lot. Today each one is an `upset_plot` for membership plus a code-mode
scatter, and cutandrun's `caller_agreement` recipe lives in the pipeline rather than the
catalog. Note this one collides with a standing policy: `test_compositions_stay_out_of_the_catalog`
keeps cross-set compositions dashboard-side, so it needs a decision before it needs code.

**3. `scatter_xy`: numeric against numeric, with size, colour and a selection key.**
BUILT. Twenty-eight code-mode figures across ten pipelines and thirteen template versions,
counted rather than estimated; the "twelve" below was the count over the original nine
templates of the lot. `dot_plot` is the closest kind and
cannot express them: its two axis roles are `cluster` and `gene`, both String, so it draws
a categorical grid, not a plane. This is the largest single group of fallbacks in the lot
and the cheapest to specify, whether it lands as a kind or as size and `custom_data`
support in the figure builder.

#### Reusable across a family, not universal

**3. `signal_matrix`: the metagene heatmap.** BUILT, and bound nowhere in the lot: the
kind needs one row per region, and every chromatin manifest fetches deepTools'
`plotProfile.tab` summary rather than the `computeMatrix` matrix the rows live in. Binding
it is a manifest and recipe job, not a viz one. Rows are regions ordered by signal, columns
are position offsets, drawn under the profile curve of candidate 1. Wanted by all three
chromatin templates, and the reason cutandrun leaves `04_reporting/deeptools_heatmaps/`
(2.9 GB) unfetched. `complex_heatmap` can technically bind it, since it only requires
`index`, but the column order is positional and must survive clustering, there is no
marker at 0, and the row count runs to 10^5 so the kind has to bin. Travels to any
pipeline with signal over a reference point: chipseq, atacseq, cutandrun, cuttag,
methylseq, nascent, and rnaseq gene bodies.

**4. `feature_distance`: signed distance to the nearest annotated feature, split by
class.** Behind `cs-pk-fig-tss` and `at-pk-fig-tss`, both reading HOMER `annotatePeaks`.
The MultiQC `peak_annotation` sections that CS-D6 and AT-D9 leave unbound are the same
data. It is close to a plain histogram, so the value is only the zero marker, the class
stacking and the standard promoter and distal binning. Worth it if peak annotation stays a
recurring template, not before.

#### Pipeline-specific

**5. Protein-domain track.** BUILT as `fusion_structure`, bound through
`fusioninspector/fusion_domains`, and `rnaf-fi-domain-track` is now that kind rather than
the code-mode bar chart it started as: one lane per partner, one bar per Pfam hit along it.
rnafusion today, oncoanalyser when it lands, nothing else in sight.

#### Asked for, but not actually a viz-kind gap

- **V-by-J pairing and CDR3 spectratype (airrflow).** AF-D8 skips
  `vdj_annotation/02-make-db/*_db-pass.tsv`, so this is a data gap, not a viz gap. V-by-J
  is a contingency table that `complex_heatmap` already draws, and CDR3 length is
  candidate 1.
- **The seven code-mode bars and boxes.** They need a grouping and a log axis in UI mode,
  not a kind.
- **The MultiQC sections nobody badged.** rnaseq strandedness, sample-relationships and
  biotype counts (RS-D5), chipseq `peak_count`, `peak_annotation` and four `deseq2_*`
  sections (CS-D6), atacseq `mlib_peak_annotation` and the two `mlib_deseq2_*` (AT-D9),
  taxprofiler MALT (TP-D6). Each is one catalog YAML plus a stub, no renderer work.
- **The General Statistics tile.** Missing from three of nine templates for two different
  server bugs: a duplicate `Reads mapped` display title (CS-D3, AT-D8) and a DataFrame
  truth-value error, with rnaseq simply going without (RS-C5). This is the widest QC table
  in every report and no new kind recovers it.
- **`_col_annotations_json` on `complex_heatmap`.** differentialabundance computes the
  sample annotation strip in both heatmap recipes and the `advanced_viz` renderer ignores
  it; only the legacy `visu_type: heatmap` path reads it. An existing kind under-powered,
  not a missing one.

### Where the boundary with JBrowse sits

> **Re-examined in `docs/design/genomespy-eval.md` (#1083).** GenomeSpy draws tabular
> tracks on a real locus axis inside `advanced_viz`, and has lazy BAM / BigWig / VCF / GFF3
> sources that could take the file-backed side too; the paragraphs below describe the
> boundary as it stood before that evaluation.

Depictio already carries a `jbrowse2` data-collection type whose allowed formats are BAM,
CRAM, BigWig, BED, GFF3, VCF and their indices, plus a JBrowse component in the React
viewer. That is the line, and it is worth stating because two of the kinds in this lot sit
right on it:

- **Anything that needs per-base signal, read alignments or a gene model over genomic
  coordinates belongs in JBrowse.** It already ingests the file types those come in, and
  an `advanced_viz` kind reading the same thing out of a Delta table would be a worse
  genome browser bolted onto a plotting library.
- **Anything that is an aggregate table belongs in `advanced_viz`,** whatever the x axis
  happens to mean.

Applied to `sashimi`: the arcs are an aggregate junction table, which is why the kind
exists at all, but a full sashimi plot is arcs drawn over per-base coverage with the
transcript model underneath, and those two halves are BigWig and GFF3. The kind therefore
ships as the junction-arc half and the coverage and exon-model halves are deferred to
JBrowse rather than reimplemented. `coverage_track` and `gene_arrow_track` are the same
case and should not be extended toward browser features either.

### What MultiQC parses but never publishes as data

The catalog policy is that a tool MultiQC already parses stays a `use: multiqc/<module>`
panel, and `_index/multiqc_modules.txt` lists which those are. That index is advisory, not
prohibitive, and always was: `ataqv`, `homer` and `macs2` are all in it and all have full
catalog tools. What the policy is really protecting against is a second copy of a panel
that already exists, not a dedicated tool as such.

The line that actually holds is narrower and worth writing down: **a dedicated tool is
justified when nf-core publishes a table that the MultiQC panel does not render, or
renders without the columns that carry the reading.** Three cases in the ChIP family meet
it, and all three shipped:

- **`preseq`.** MultiQC plots `EXPECTED_DISTINCT` on its own and drops `LOWER_0.95CI` and
  `UPPER_0.95CI`, so the width of the extrapolation, which is what says whether
  "sequence deeper" is advice or a guess, never reaches a dashboard. The
  `preseq/complexity_curve` output keeps both bounds and binds them to `profile`'s
  optional `lower` / `upper` roles, the only output in the catalog that exercises them.
- **`deeptools`.** The MultiQC module draws the fingerprint curve but not the per-sample
  quality metrics beside it, and it has no plot at all for the `plotProfile` matrix, the
  `plotPCA` loadings or the `plotCorrelation` matrix. nf-core publishes all four as plain
  tab-separated files next to the PDFs. They became `fingerprint_metrics` (`scatter_xy`),
  `plot_profile` (`profile`), `sample_pca` (`embedding`) and `correlation_matrix`
  (`complex_heatmap`).
- **`homer`.** Not a MultiQC overlap at all, but the same shape of gap: the distance to
  the nearest TSS was drawn by a hand-written `px.histogram` in both chipseq and atacseq.
  `homer/tss_distance_profile` bins it in the recipe, which lets `profile` own the marker
  at the start site, the shaded promoter window and the log axis.

None of this needed a new viz kind: the four bindings are `profile`, `scatter_xy`,
`embedding` and `complex_heatmap`, all of which already existed.

What is left in the ChIP family after that is genuinely browser work, not table work:
per-base coverage tracks (`bigwig/`), the aligned reads and the peak intervals as
features. That is the JBrowse boundary above, and nothing in it should become a kind.

### Still missing, for pipelines outside this lot

V-to-J pairing at scale (airrflow full rearrangement tables), 96-context mutational
signature and circos (oncoanalyser), knee plot (scrnaseq), isomiR ladder (smrnaseq),
jplace reader (phyloplace), assembly graph (bacass).

Also: the `phylogenetic` kind has no catalog output binding it, and `upset_plot` and
`sankey` can only be bound through a dashboard `config:` block because their roles are
list-valued rather than required.

## 10b. What is still not a catalog tool, and why

A sweep of the 16 shipped dashboards asked, of every card, table, figure, MultiQC panel
and advanced-viz tile, whether the data collection under it is one the catalog
recognises. 275 tiles were reading a catalog output without saying so and now carry a
`use:` handle. What remains unbound is not an oversight, and splits three ways.

### Pipeline input, not tool output

`samplesheet`, `metadata`, `samples`, `sample_design`, `design`, `database_sheet`: the
files the user hands the pipeline, parsed so the dashboard has a hub to link on. A
catalog entry describes what a tool *emits*; the run's own inputs have no producing tool
and no glob that generalises past one pipeline, so they stay template-local.

### Dashboard compositions, not module outputs

`screening_summary` (funcscan, one row per sample per screening workflow),
`caller_agreement` (cutandrun, SEACR against MACS2), and the `*_canonical` reshapes
(sankey, upset, variant feature matrix) all read *several* outputs and answer a question
about the run rather than about a tool. `test_compositions_stay_out_of_the_catalog`
pins that boundary deliberately.

### MultiQC custom content

Fourteen MultiQC panels stay unbound: FRiP score and peak count (chipseq, atacseq),
strand cross-correlation and the NSC/RSC coefficients (chipseq), strandedness inference,
the DESeq2 sample-relationship plots and the biotype composition (rnaseq), SURVIVOR and
the variant-calling summary (variantbenchmarking), and the fail-mapped-samples table
(viralrecon). These are `*_mqc.tsv` sections a *pipeline* writes into its own MultiQC
config, not modules MultiQC ships. A catalog output keys on the module that owns a plot
anchor (`multiqc_module()` takes the anchor's leading token), so binding them would mean
outputs called `strand`, `nsc`, `rsc`, `mlib` and `fail` — names that describe one
pipeline's config, not a tool. The numbers behind them are real (phantompeakqualtools,
SURVIVOR), but until nf-core publishes them as module output rather than as report
decoration there is nothing tool-shaped to point a `find` rule at.

The general-statistics table is the one section that *is* universal, and it is now
`multiqc/general_stats`. It needed a small fix to be reachable: MultiQC assembles it out
of whatever modules ran, so it appears in neither the report's module list nor its plot
registry, and the compose endpoint's `present & plottable` intersection could never keep
it. `_multiqc_sections` now adds it to the answer rather than to the set being
intersected.

## 11. List-valued render roles were never actually validated

`test_all_recipe_output_roles_resolve_against_the_recipe` did `set(r.roles.values())`,
which raises `TypeError: unhashable type: 'list'` on exactly the roles `_LIST_ROLES`
declares: sankey `steps`, sunburst `ranks`, complex_heatmap `value_columns` and
`row_annotation_cols`. The first such render the loader reached made the whole test
error out, so the assertion had never checked those roles at all. Six shipped renders
across four tools now use them. Fixed in this lot by flattening before comparing.

## 12. Large fan-in inputs have no pre-aggregation story

A template can only bind what a recipe can read in one pass. crisprseq publishes 6195
files, airrflow's per-sample `*_db-pass.tsv` set is 227 MB, funcscan's raw per-tool
outputs are 2.8 GB against 6.5 MB of aggregated reports. Every template in this lot
binds the aggregated report and leaves the per-sample corpus alone, which is why
airrflow's V-to-J pairing and rnafusion's per-read evidence are unbound.

**2026-09-22 update.** methylseq shows the pre-aggregation story that works today:
the 756 MB of per-CpG bedGraph (7 files, 8 to 46 M rows each) is never ingested.
A one-row-per-file index collection (`n_rows: 1` plus
`include_file_paths: source_path`, which goes through lazy `scan_csv`) carries the
paths, and the recipes stream each file themselves through
`depictio/recipes/lib/genomic_bins.py` into 10 kb windows (about 20 s at ingestion,
nothing large enters Delta). The same idiom applies to airrflow's `*_db-pass.tsv`
and cutandrun's `deeptools_heatmaps/*.mat.gz`. Remaining gap for methylseq: no
CpG-island or TSS annotation is bundled, so its feature tab stratifies by
CpG-density tertile and names the proxy as one.

## 13. A stale API catalog cache corrupts imports silently

`load_catalog_entries()` is `@lru_cache(maxsize=1)` and nothing in the shipped code
ever calls `cache_clear()`. The API process answers from whatever `depictio/catalog/`
held the first time it was asked, so a tool added while the stack runs stays invisible
until the container restarts.

The damage is not confined to lookups. When the API cannot expand a `use:` handle the
component does not raise, it degrades to a raw dict: `viz_kind` and `catalog_source`
are stored as null, the inherited role bindings and config defaults are lost, and the
import still reports success. `AdvancedVizDispatch.tsx` dispatches on `viz_kind`, so
the viewer renders `Unknown advanced viz kind: ""` for a dashboard that every
CLI-side check passed.

The split across this branch is exactly whether the tool folder existed at API start:

| project | advanced_viz tiles with a resolved kind |
|---|---|
| ampliseq, viralrecon, funcscan, airrflow, differentialabundance | all of them |
| chipseq | 4 of 7 |
| rnafusion | 0 of 9 |
| taxprofiler | 0 of 8 |
| rnaseq | 0 of 2 |

Two probe imports through the same endpoint isolate it: `fusionreport/caller_upset`
stores null, `hamronization/arg_upset` stores `upset_plot` with a 14-key config.

Recovering needs a container restart AND a re-ingest, because the null is persisted;
restarting alone leaves the stored dashboards broken. Declaring a redundant `viz_kind:`
in the YAML would hide the symptom while still losing the config defaults and the
catalog badge, so no template in this lot does that.

**2026-09-23 (wave 2b).** Hit again on cutandrun: `seacr/frags_pileup_matrix`,
`seacr/frags_pileup_track` and `seacr/seacr_consensus_track` were added to the catalog
while the stack ran, and the first import stored the three tiles without a
`viz_kind`. Any live pass that adds a catalog render must restart the backend before
importing, and re-import after.

## 14. A long annotation label can collapse a complex_heatmap to nothing

Binding `row_annotation_cols` to a field whose labels are long silently
destroys the plot. Plotly sizes the strip's margin from the longest label and
nothing clamps it against the tile, so on funcscan's ARG heatmap a 517 px tile
got a 346 px right margin and a plot area 284 px wide NEGATIVE: the colour bar
and a few tick labels drew, and not one cell did.

Nothing catches this before a human looks. The data is correct, the recipe is
correct, the roles resolve, every bound column exists, the server returns rows,
and `test_shipped_dashboard_yamls.py` is satisfied. Only the rendered pixels
are wrong, which is why the browser pass exists.

The template-side fix is to bind a short form of the field and keep the long
one on the row for the table, which is what `hamronization/gene_matrix.py` now
does. The platform-side fix, not attempted here, is for the complex_heatmap
renderer to clamp annotation margins to a fraction of the tile and truncate
labels with a hover, so that no binding can produce a negative plot area.

Worth checking wherever a field is free text rather than a controlled
vocabulary: taxonomy lineages, GO terms and drug classes are all candidates.

## 15. A scan pattern that starts with `.*` will eventually eat a MultiQC table

Widening eager's Qualimap scan from `.*_stats/genome_results\.txt$` to
`.*genome_results\.txt$` (to stop depending on the `_rmdup_stats/` directory name)
also matched `multiqc/multiqc_data/multiqc_qualimap_bamqc_genome_results.txt`,
MultiQC's own flattened copy of the same table. The raw collection picked up three
files instead of two and the recipe died on the third
(`pattern not found: 'number of reads = ([\d,]+)'`).

The scan regex is matched against the basename first, so the leading `.*` is never
needed: anchor as `genome_results\.txt$`, or path-qualify with `(?:.*/)?` when a
directory has to be part of the match. Every template whose tool-output pattern
starts with `.*` is one MultiQC module name away from the same failure; worth a
sweep when the lint rules land.

## 16. `sample_mapping` cannot strip dot-joined per-tool suffixes

The canonicalisation regex in `depictio/cli/cli/utils/sample_mapping.py` strips the
usual `_1` / `_R1` / `.sorted` decorations, but not the dot-joined per-tool suffixes
sarek writes into MultiQC (`<sample>.md`, `<sample>.recal`, `<sample>.deepvariant`,
`<sample>.freebayes.filtered`) nor a `-1` lane marker. sarek works around it with an
explicit `mappings:` block on the `samples -> multiqc_data` link (20 name variants
per sample). A template that cannot enumerate its variants up front (any pipeline
whose caller or stage set is a parameter) still needs the resolver fixed.

## 17. `depictio/cli/.venv` has no MultiQC, so a live ingest from it aborts early

Any template with a `multiqc` collection fails its live ingest from
`depictio/cli/.venv` with `No module named 'multiqc'`, and the failure aborts the
run before steps 7 and 8, so no dashboard is imported at all (nanoseq, 2026-09-22).
Run the CLI from the repo venv (`.venv/bin/python -m depictio.cli run ...`) or
`uv sync --extra multiqc` the CLI venv. The dry run does not catch it.

## 18. Integer factor columns only take sliders

`INTERACTIVE_COMPATIBILITY` maps Int64 to range controls, so a samplesheet factor
stored as an integer (cutandrun `replicate`, sarek `read_depth_millions`) cannot be
a MultiSelect. Both templates now emit a Utf8 twin (`replicate_label`,
`read_depth_label`) from the sample recipe and filter on that. Recipe-side fix; a
platform-side option would be to let a low-cardinality integer column opt into a
Select.

## 19. A follower only zooms when it shares the navigator's column names

A locus section has one navigator (`genome_view` with `region_filter_enabled`) that
emits a chromosome filter and a position filter named after **its own** columns. The
API rewrites that pair onto each linked collection through a `resolver: region` link
(`filter_links.py::region_link_filters`), so the followers' rows are narrowed
correctly. The x-axis clamp is a different path: `useFollowedRegion`
(`genomicAxis.ts`) reads the dashboard filters by the follower's own role columns, and
the dashboard filters still carry the navigator's names. A follower whose columns
differ from the navigator's therefore gets the right rows on the wrong axis:

- hic: `tad_domains` emits `chrom` / `start`; the contact triangle binds `chrom1` /
  `start1`, so it draws the region's rows from 65 Mb to the chromosome end and its
  automatic resolution picks 1 Mb instead of 500 kb (HC-D17).
- sarek: `mosdepth_windows` emitted `chromosome` / `position`; `vcf_variants` and the
  file track bind `chrom` / `pos`, so on the first ingest every follower stayed
  genome-wide and MinIO saw no range request (SK-D14). The template renamed every locus
  column to `chrom` / `pos`, which is a workaround, not a rule a template author can
  discover.
- sarek: cards ignore `genome_selection` filters altogether (SK-D13), so a "variants in
  view" card cannot exist.
- hic again: `coverage_track` in its `locus` (GenomeSpy) view narrows its rows to the
  followed region but keeps the whole-genome x axis, so the insulation track drew as one
  sliver at chr2 (HC-D20). The TADs tile opens on `view: track`, which clamps, until the
  locus view reads the same region.

**Smallest fix:** give the client the project's region links (they are already fetched
for the filter panel) and let `followedRegion` map a foreign region onto the tile's
roles through the link's `columns: {chrom, pos}`. Then `follow_region_filter` is what
the docs already say it is: any tile reached by a region link follows the region.

## 20. A genome_view navigator fetches its whole collection, sampled

`genome_view` never narrows its own fetch: the tile receives the collection sampled to
`figure_max_points` (10 k rows) whatever region it opens on, then zooms client side.
On methylseq's 135 k-row binned collection that left about 8 of the 112 windows inside
the default region (MS-D14); the template moved the navigator to the 19 k-row
group-compare collection and made the binned lanes a follower, whose fetch is
region-limited and complete. cutandrun's navigator shows a sample of 433 k SEACR calls
for the same reason (CR-D22). Same family: the y domain spans the whole collection, so
one 59X mitochondrion flattens every nuclear window of eager's depth navigator to the
bottom of its lane (EA-D13).

The rule that works today, found on the third methylseq layout: give the navigator a
`score_threshold` on a significance score (`neg_log10_padj` at 1.3), because the
sampler keeps every row above the threshold whole, and put the dense per-sample
tracks on followers, whose fetch is region-narrowed and complete. The navigator then
shows the hits at any scale and the followers show everything at the locus.

**Smallest fix:** when a `default_region` or a region filter is set, fetch the
navigator's rows for that region at full density (the coverage_track dispatch already
does this) and keep the sampled genome-wide frame only for the overview; rescale y on
the visible rows.

## 21. Assemblies: alt contigs crash the navigator, hg19 has no gene lane

`genome_view` with `assembly: hg38` throws on rows whose contig the assembly does not
list (SEACR calls on `chr1_KI270706v1_random` and friends, CR-D19), so cutandrun's
navigator runs without an assembly and without gene-symbol search; the gene lane moved
to the consensus track, which has no alt contigs. Separately, the bundled gene tables
and locus search cover hg38 and mm10 only, so the hg19 runs (chipseq 1.2.0, atacseq
1.2.2) and the cod assembly (eager 2.4.5, gadMor3) have no gene lane and take
coordinates only in the locus field; HOMER's nearest-gene track stands in.

**Smallest fix:** drop or bucket rows on contigs absent from the assembly before
building the GenomeSpy spec; ship an hg19 gene asset, and let a template point at a
GFF3 tabix for any other assembly (the `indexed_file` path already exists).

## 22. `coverage_track` crashed on a numeric `sample_col` (fixed in this PR)

hic's insulation and E1 tracks wanted one line per window size or per resolution, both
integer columns. The header "Samples" MultiSelect was fed the raw values and Mantine's
search called `toLowerCase` on a number, taking the whole tile down (HC-D16). The
renderer now coerces the chromosome and sample option lists to strings; confirmed live
on the re-ingested hic template, whose insulation tracks draw one line per window and
whose E1 tracks draw one per resolution.

## 23. New kinds land before their catalog renders

`record_card` and `parallel_coordinates` (wave 2a) have no render in any catalog
module, so every template that uses them binds `viz_kind` + `config` by hand:
scrnaseq (marker record, cluster profile), methylseq (QC profile, navigator on the
group-compare DC), mag (Nx profile, recruitment heatmap, bin record), nanoseq (Nx
ladder, DEXSeq usage), airrflow (spectratype, V-J, ribbon), rnaseq (QC profile, gene
record). Each lowers the template's `use:` ratio by two or three tiles. The catalog
also still spells the alias kinds the wave folded into views: `gsea/gsea_dotplot`
(`enrichment`), `deseq2/ma`, `deseq2/qq`, and `combgc/region_track` still advertises
the unbound `bgc_region_coverage` render.

**Smallest fix:** one render per new kind in the modules named above (cellranger,
bismark, checkm2 or gtdbtk, samtools, enchantr, salmon), and flip the four alias
renders to their surviving kind plus a `view`. The template lint could then require
`use:` on any advanced_viz whose module ships a render for that kind.

## 24. `keep_columns` is ignored on a table collection

`DCTableConfig.keep_columns` is accepted by the model and never read by the CLI, so a
wide raw scan (airrflow's 74-column repertoire table) cannot be projected at ingest.
Recipe file sources with `read_kwargs.columns` are the workaround; a raw collection
that is only there to feed `dc_ref` still lands in full. Related: `parallel_coordinates`
labels its axes with raw column names and two of rnaseq's overlap at width 8 (RS-D12);
the kind should read `columns_description` for its axis titles like the record card
does.

## 25. A direct link and a region link on one pair of collections (fixed in this PR)

sarek declared a `stage` link and the locus region link between `mosdepth_windows` and
`mosdepth_targets`. `_find_link_for_resolution` (`links_endpoints/routes.py`) looked a
link up by source and target only, returned the region link for a value lookup, and
the resolver registry answered `Unknown resolver type: region`: every
`compute_coverage_track` on the targets track was a 500 (SK-D15). The lookup now skips
region links unless asked for one by name, with a unit test on the sarek pair. The
template dropped its `stage` link as a workaround before the fix and has not put it
back: restoring it means the stage picker narrows the per-target track again, which
needs a re-ingest to check.

## 26. File-backed tracks decode one lane at a time

sarek's `genome_view` on the `indexed_file` collection (8 annotated VCFs plus `.tbi`)
draws the first lane and fails the other seven with
`Loading failed: workerPool.decompressBlocks is not a function` (SK-D19). The range
reads succeed (24 MinIO requests at the default region, 32 after a typed locus); the
failure is in `@gmod/bgzf-filehandle` 6.6.0's worker pool under concurrent lane loads,
in the GenomeSpy lazy VCF source. Not a template matter.

**Smallest fix:** serialise the lane loads or pin the bgzf filehandle to a release
whose pool exists in the bundle; a Playwright check that every lane of a multi-file
track reaches `loaded`.

## 27. A slider walked a value link as two values (fixed in this PR)

atacseq's Peak locus navigator emits a position range on `macs2_broad_peaks`;
`extend_filters_via_links` sent it through the direct `peak_id` link to
`homer_annotated_peaks`, where `_translate_filter_values` read `[26000000, 26300000]`
as `start IN (26000000, 26300000)`, matched no peak and emptied the HOMER track. The
q-value and width sliders of the Peaks tab did the same (AT-D26). A `RangeSlider` or
`DateRangePicker` filter now travels with `range_filter: true`
(`LinkResolutionRequest`), the translation applies `>= low and <= high` on the first
hop, and later hops receive the discrete join values as before. The atacseq template
had disabled the link as a workaround; re-enabling it needs a backend restart and a
live check of the HOMER track under a region, a q-value range and a peak lasso.

## 28. `scatter_xy` density on a log axis killed the tab (fixed in this PR)

mag's Contigs tab crashed headless Chromium in 8 loads out of 9 whenever the
length-vs-depth scatter drew its density view on log axes, including through the
automatic switch above 3,000 rows that every sampled 10 k-row scatter crosses
(MG-D14). Nothing reached the console. The density view no longer asks Plotly's
`histogram2d` to bin: the cells are counted in the renderer (`densityHeatmap`) and
drawn as a `heatmap` with explicit edges in data units, which a linear and a log
axis map the same way. mag's scatter is pinned to points mode until the fix is seen
live; any log-axis scatter past the threshold gains the same protection.

## Pipelines considered and not templated in this lot

| pipeline | why not |
|---|---|
| crisprseq | screening arm never published a megatest; 6195-file fan-in needs pre-aggregation |
| smrnaseq | isomiR views need a kind that does not exist |
| scrnaseq | nested `aligner_*` run roots plus a missing knee plot |
| oncoanalyser | signature and circos kinds missing; run root `HCC1395/` |
| methylseq, raredisease, quantms, bacass | no usable megatest run at all |
