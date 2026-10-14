# nf-core/pairgenomealign 3.0.4 template validation report

Validated offline against the AWS megatest `results-8ee09a1cdc920fc90cd62358952045e5019e1fe0`
(the 3.0.4 release tag, test_full profile: 34 query genomes aligned to one target assembly).
The run is 42.8 GB, almost all MAF alignments; the fetched subset is 173 files, 19.5 MB
(`bash download_test_data.sh`).

The live check of RULES section 15 (rendering, autofit, docking, colours, the Guide) is not part of
this report: it is done on a running stack.

## What was verified offline

| Check | Result |
| --- | --- |
| `depictio dashboard validate --offline dashboards/base.yaml` | pass |
| `test_template_conventions.py`, `test_shipped_dashboard_yamls.py`, `test_template_dc_order.py` with `-k pairgenomealign` | pass; five warn-only "median of a percentage" notices, see below |
| `depictio/tests/recipes/test_pairgenomealign_recipes.py` (the catalog tools) and `test_pairgenomealign_project_recipes.py` (the `genomes` hub) | 13 passed |
| Every catalog recipe and the hub over the megatest (`execute_recipe`, input and output schemas) | pass, 7 collections |
| `last/synteny_links.py` and the template's dry run on a scratch root with a synthetic PSL export (two queries, 3000 alignments each) | pass, 2000 links per pair, collection `ok` |
| `depictio ingest --template nf-core/pairgenomealign/3.0.4 --dry-run` on the megatest, with `METADATA_FILE` | 8/8 steps, 9 collections to ingest, `last_synteny_links` missing (optional) |
| The same with `SKIP_ASSEMBLY_QC=true`, and with no design table | 8/8 steps, `assemblyscan_stats` or `metadata` dropped |
| Import-time pruning, simulated route by route over the real dashboard with the importer's own gates (`_component_has_data`, `_prune_unresolved_text_values`, orphaned sections, the tab minimum, orphaned highlights) | see "Routes" |

The text tiles, KPI strips and open-row budgets are held by the lint above (stored text heights,
at most three sentences per paragraph, no forbidden terms, no `GROUP_COL` in a `filter_expr`,
persistent filters reaching MultiQC). The row budgets below are counted by hand from the stored
heights.

## Routes (RULES section 13)

| Route | Result |
| --- | --- |
| Full run (a PSL export, assembly QC, a design table) | nothing dropped |
| No PSL export (the megatest) | the Synteny tab is dropped (all 8 of its components read `last_synteny_links`); the Link step and the synteny findings row are removed with their value; the tab tile draws nothing; the four highlights stay |
| `--skip_assembly_qc` | the Assemblies strip, both filters, the contiguity scatter and the statistics table go; the gap matrix and gap table stay; the Check step, the N50 findings row and the contiguity highlight go (the findings figures then show three tiles) |
| No design table | `metadata` is dropped; the hub and every tab are built; group filters and splits fall away |
| No substitution matrix | the Divergence tab is dropped, with its findings row and its highlight |

## Collection sizes on the megatest

| Collection | Rows |
| --- | --- |
| genomes | 34 (8 clades) |
| metadata | 34 |
| last_split_identity | 34 |
| last_split_matrix | 34 |
| last_train_params | 34 |
| assemblyscan_stats | 34 |
| seqtk_cutn_gaps | 33 (one assembly has no run of N) |
| seqtk_cutn_gap_lengths | 235 |
| last_synteny_links | 0 (no PSL export on this run; up to 2000 per pair otherwise) |

## Open rows per tab (stored heights)

| Tab | Open rows | Open sections |
| --- | --- | --- |
| Overview | 21 of 24 | hero 1, about 3, pipeline 3, key figures 2, findings 10, how to read 2 |
| MultiQC | 13 | 2 (the intro is 1 of them) |
| Assemblies | 15 | 3 (strip 2, contiguity 6, scaffolding gaps 6; tables collapsed) |
| Alignment | 16 | 3 (strip 2, identity and coverage 7, fitted parameters 6; tables collapsed) |
| Divergence | 14 | 3 (strip 2, saturation 6, spectrum 5; table collapsed) |
| Synteny | 12 | 2 (strip 2, ring 9; table collapsed) |

## Findings

- **Identity and coverage.** Identity runs from 64% to 99.8% and target coverage from 5% to
  92%, both falling with divergence; K80 distance runs from 0.001 to 0.29.
- **Saturation.** The transition over transversion ratio peaks near 2.2 and falls to 1.4 at the
  largest distances, the expected saturation signal.
- **Fitted parameters.** The gap opening cost rises from 25 to 44 with the identity of the training
  alignments (69% to 99.9%); the extension cost is 1 and the strand setting 1 for every pair, so
  neither is a card or a figure.
- **Assemblies.** N50 is 82 to 166 Mb for every query, but sequence counts range from 19 to
  1.3 million and gap counts from 0 to 234 thousand, so coverage differences between genomes of
  similar divergence track assembly gaps. The share of sequences past 1 Mb is 0 to 45% for 26
  assemblies and 80 to 100% for the 8 chromosome-level ones, hence a histogram rather than a median.
- **Gap lengths.** The runs of N cluster at 100 bp and at a few hundred bp, with a tail to tens of
  Mb; 28 of the 33 assemblies with gaps have one length bin holding more than a third of their
  runs, and the most common bin is 100 bp for 11 of the 33.

## Open issues

- The megatest ran with `--export_aln_to no_export`, so the Synteny tab has no data on the
  reference project. The recipe, the DC and the dry run were checked on a synthetic PSL; the ring
  itself (chord layout, the query pick, the heaviest-links default) was not seen. A run with
  `--export_aln_to psl` is needed to confirm the real export naming (`<target>___<query>.psl.gz`
  is assumed from the module's `${meta.id}` prefix).
- The query filter of the Synteny tab is optional: `always_selected` of the lot 3 template does not
  exist on this branch and a generic template cannot write a `default_value` (a genome name belongs to
  one run). Until a query is picked the ring shows the heaviest links of every query.
- The gap length matrix prints its column names (`log10_gap_length`, `gaps_pct`) as axis and
  colour bar titles: the signal matrix kind has no title options.
- Five cards take the median of a percentage column (`*_pct`), which the lint reports as a warning:
  the columns are per-genome percentages, not pooled counts, so the median is the intended
  reading.
- On `--skip_assembly_qc` or without `last_train_params`, the Findings figures show three tiles and the
  last row is half empty: a route cannot supply an alternate figure for a collection that is
  absent. `SKIP_ASSEMBLY_QC` must be set by hand; it is not introspected from the run parameters.
- The MultiQC report holds custom content only; the alignment sections name rows by pair and
  the assembly sections by genome, so two links from the hub reach them (regex on `pair`,
  sample mapping on `genome`). Whether the viewer combines two links to one MultiQC collection
  was not checked live.
- A synteny label is the target interval, so two queries with an alignment on the same interval
  share a label and a click on a chord selects both.
- `last-dotplot` PNGs are not shown (no image upload in a template run).
