# nf-core/proteinfold 2.1.0: Depictio dashboards

One dashboard: an **Overview**, then four child tabs in two groups, read as a funnel from how far
a model can be trusted to whether the engines agree. The template follows the family rules in
`depictio/projects/nf-core/RULES.md` (ampliseq 2.18.0 is the reference implementation).

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | Model scores | How far can each engine's top-ranked models be trusted? |
| Structure | Structure | Where along each structure is the prediction confident? |
| Structure | Predicted error | Which domains and chains does the model place confidently? |
| Structure | Engines comparison | Do the engines and their models agree on each target? |

[nf-core/proteinfold](https://nf-co.re/proteinfold) predicts protein structures from sequence
with one or several engines (AlphaFold2 in standard or split-MSA mode, ColabFold, ESMFold,
RoseTTAFold All-Atom, Boltz, ...). Each engine writes its top-ranked model per target, the
per-residue confidence (pLDDT) of every model, TM scores, predicted aligned error (PAE) matrices
and, for the MSA-based engines, the alignment it folded from.

The design comes from the target hub (`targets`): one row per samplesheet target with its chain
count, length, assembly (`GROUP_COL`) and the engines that folded it. Every filter starts there:
its links carry a target pick to every per-structure and per-model collection.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `targets` | the samplesheet (`METADATA_FILE`, default `input/samplesheet.csv`) plus the structures | target |
| `proteinfold_structures` | `<engine>[/<mode>]/top_ranked_structures/<target>.pdb` (indexed file, read whole by the 3D and Ramachandran tiles) | structure |
| `proteinfold_pae_matrices` | `<engine>[/<mode>]/<target>/paes/<target>_<k>_pae.tsv`, the top-ranked model only (indexed file, format `pae`, read whole by the PAE tile) | structure |
| `proteinfold_residues` | the PDBs, pLDDT from the CA B-factor | structure and residue |
| `proteinfold_structure_scores` | the PDBs, plus the model count and top-model pTM / ipTM | structure |
| `proteinfold_engine_plddt` | the PDBs, one curve per target, engine and chain | curve and residue |
| `proteinfold_models` | `<target>_plddt.tsv`, `_ptm.tsv`, `_iptm.tsv`, `_ipsae.tsv` | structure and model rank |
| `proteinfold_plddt_ranks` | `<target>_plddt.tsv`, top model plus the lowest and highest model | structure and residue |
| `proteinfold_pae` | the same PAE files, binned to at most 64 x 64, plus each row's mean | structure and residue bin |
| `proteinfold_msa` | `<target>_<engine>_msa.tsv` | alignment row |

The unit of every structure tile is the **entity**: one engine's top-ranked structure of one
target. Its id is the id the structures collection gives the PDB, `<engine>__<target>` with a
non-default AlphaFold2 mode between the two (the named groups of the collection's sample regex
joined with `__`), so every per-structure table joins the 3D object without a lookup. The PAE
collection names each matrix with the same id: its scan pattern and sample regex keep the
top-ranked model only (`_0_` for AlphaFold2 and RoseTTAFold All-Atom, `_1_` for ColabFold, which
numbers its models from 1), and the runner-up files are never uploaded. Both strings are
`PAE_SCAN_PATTERN` and `PAE_SAMPLE_REGEX` of `depictio/recipes/lib/proteinfold.py`, pinned by a
test. The `engine` and `target` columns carry the reader-facing names; AlphaFold2 modes other
than `standard` show in the engine name.

proteinfold does not publish the samplesheet it ran on, so the template ships the test_full
sheets under `input/` and reads them by default; point `METADATA_FILE` at the sheet of another
run. Sheet columns beyond `id` and `fasta` are kept, so any of them can become `GROUP_COL`.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/samplesheet.csv` | samplesheet read by `targets` |
| `METADATA_ID_COL` | `id` | samplesheet id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `assembly`, `Assembly` | group filters, the Targets card and the group colours; `assembly` is derived (single chain or complex) |

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second counts the targets, engines, models
  and residues, and prints the requested mode from the run parameters.
- **Pipeline**: six steps (targets, align, fold, score, assess, compare). Each step opens the
  parameters that drive it and the tab that shows its output; the assess step counts the PAE
  matrices and is dropped with them on a run that wrote none.
- **Key figures**: four headline cards, each opening the tab that explains it. Targets (split
  by assembly), the top-ranked structures (a ring by engine), the median mean pLDDT of those
  structures (counted against the 70 and 50 cut-offs) and the share of residues at pLDDT 70 or
  more per top-ranked model (its spread). An assembly and a target filter above them narrow
  these four only.
- **Findings**: result rows computed under the filters, each with a link to its tab: the
  structures and engines, the median mean pLDDT with the share of residues under 50, the mean
  PAE and the models ranked. Below them, four figures in two rows, each a wide tile (five of the
  eight columns) beside a narrow one (three): the first structure in 3D beside the mean pLDDT of
  every model per engine, then the PAE matrix of the first structure beside the top model of each
  engine per target. The 3D structure over its written sequence and the PAE matrix take the wide
  side, the box and bar plots the narrow one. The bar of this section filters by assembly and
  engine.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (assembly, target, target length) sit in the collapsed left panel
and narrow every tab. The `Sample sheet` section is pinned to the bottom of every child tab,
collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method and how to read the tab), then a strip of
four key numbers, each card with its own colour and a secondary that reads it, then at most
three open sections; tables and record cards follow, collapsed.

**Model scores.** Strip: the models predicted (a ring by engine), the mean pLDDT of the top
models (its spread), the share of residues at pLDDT 70 or more (its distribution) and the pTM
of the top models (counted against the 0.5 cut-off). Then every model's mean pLDDT against its
pTM, and the mean pLDDT of every model per engine. pLDDT scores each residue and pTM the whole
fold, so a high pLDDT with a low pTM is a set of confident pieces placed loosely. Engines that
write no TM score (ESMFold, RoseTTAFold All-Atom) are absent from the scatter and the pTM card.
Filters: engine and model rank.

**Structure.** The tab reads one target (see "Single-unit pickers" below). Strip: the median
residue pLDDT (its spread), the residues split by AlphaFold confidence band, the residues under
pLDDT 50 ranked by engine and the best mean pLDDT of the target's structures, the engines ranked
by theirs. Then a `Structures and confidence` section (`display: linked`, held within one screen height) with the
picked structure in 3D over its written sequence on the left and, stacked on the right, a table with one row
per engine's top-ranked structure (mean pLDDT, the shares of residues at 70 or more and under 50, pTM), the
sequence with its pLDDT lane, the per-engine pLDDT profile and the Ramachandran plot of the picked structure
(phi and psi are computed in the browser from the PDB's backbone, coloured by pLDDT), so a pick in one is
read in the others without scrolling. Collapsed: the alignment the structure was folded from and the residue table.

The table is the engine picker. `proteinfold_structure_scores` holds one row per top-ranked
structure, read from the same PDBs, so every row has a file to open. Its row selection is on
`entity` (hidden from the grid), the column the 3D tile names its structure by, so a click opens
that structure; the
sequence track, the Ramachandran plot and the alignment follow the same column. An engine picker
on the left would narrow the table to one row, so the tab has none. The tab's `Target` filter
is `always_selected`: the table lists one row per engine on that target, and the tiles that
show one structure at a time (3D, track, Ramachandran, alignment) open on its first structure
until a row is clicked. Sort a column header to rank the engines.

The picker is a filter on the residues, so `template.yaml` links it onward: to the engine curves
and to the structure table and the best-structure card (`target`, a direct link), and to the
alignment and the PAE matrix (`entity`, reached as that target's structures). A row of the table
is therefore always a structure of the picked target, and a click never leaves the other tiles on
another target. ESMFold writes no alignment: its structure opens the alignment tile on its
empty-state message, not on rows.

The 3D tile (`molecule_3d`, `layout: structure_text`) draws the top-ranked PDB coloured by pLDDT
from its B-factor column over its sequence written out, one clickable letter per residue;
picked residues are drawn red on both. The 3D tile, the sequence track, the Ramachandran plot
and the alignment share the `entity` and `position` column names, so a click on a residue, a
brush on the track or a column brush on the alignment emits one `residue_selection` that moves
the others; hovering highlights the same residue everywhere, including a vertical line on the
per-engine profile (`residue_axis: true`). On a complex the alignment's query is the chains
concatenated; its `chains` layout translates a column into one chain's own residue number, and
picks and hovers carry that chain.

The per-engine profile reads its own collection (`proteinfold_engine_plddt`), which carries no
`engine` column: a dashboard filter narrows every collection that has its column, so the curves
follow the target while the clicked structure cannot hide the other engines. A curve is an
engine on the picked target (and a chain on a complex). The Ramachandran regions are approximate
polygons, not MolProbity contours.

A lone query row in the alignment is the data, not a filter: the engine found or used no
homologs (AlphaFold2 run against reduced databases writes a one-row MSA). ESMFold folds
without an alignment.

**Predicted error.** The tab reads one structure. Strip: its mean PAE (the spread over residue
bins), the pLDDT of its residues (their spread), and the pTM and ipTM of its top-ranked model
against AlphaFold's cut-offs (pTM 0.5; ipTM 0.8 and 0.6). Then the PAE matrix (`pae_matrix`)
beside the same structure in 3D (`molecule_3d`, coloured by pLDDT, no sequence strip), and the
sequence with its pLDDT lane below. Both tiles read `proteinfold_residues`, which numbers the
matrix axes (`entity`, `position`, `chain`) and gives the pLDDT strips along them, and the matrix
is fetched from `proteinfold_pae_matrices`. A diagonal brush on the matrix selects the square
`[a, b] x [a, b]` as a residue range: the structure draws it red and the sequence track shades
it, so a confident domain is picked in 3D. Dark blocks off the diagonal are domains or chains
placed confidently relative to each other; on a complex the chain boundaries are marked.

The tab's `Structure` filter is `always_selected`: it names one structure for the matrix, the
3D tile, the track and the cards at once (it narrows `proteinfold_pae` and `proteinfold_models`
by `entity` too). ESMFold writes no PAE, so the filter does not offer its structures
(`filter_expr`) and its first option always has a matrix. The tab has no engine filter: the
structure id carries its engine, and another engine would empty every tile. The binned
`proteinfold_pae` table is kept only for the mean-error card: each row's mean over its residues
averages to the matrix mean. ipSAE stays in the models table and record on the Engines
comparison tab: it is null for single chains and, on a complex without a confidently placed
interface, 0 on every model, which reads as a constant on a card.

**Engines comparison.** The tab compares the engines on one target. Strip: the models in scope
(split by engine), the median mean pLDDT per model (its distribution), the weakest model's mean
pLDDT (counted against the 70 and 50 cut-offs) and the pTM per model (its spread). Then the mean
pLDDT of every engine's top-ranked model, and the mean pLDDT by model rank, one line per engine
(a steep fall from the first model means the ranking was decisive), with the per-residue
profile: one curve per engine, the line the top-ranked model and the band the lowest to the
highest of its models. A wide band marks residues the engine's models disagree on and curves
that part mark residues the engines disagree on. Drawing every model instead would stack up to
25 curves per engine (AlphaFold2 multimer). Collapsed: the models table and its record card.
Filters: target (one at a time), engine and model rank.

## Single-unit pickers (`always_selected`)

Three tab-local pickers always hold exactly one value: the target of the Structure and Engines
comparison tabs and the structure of the Predicted error tab. Each opens on the first option of
its own list, so the template names no value of one run (a target belongs to one samplesheet);
a pick replaces it, the filter cannot be cleared, and a held value that leaves the list is
replaced by the first again. The tiles that show one structure at a time therefore always agree
on it, and the curves and points of a tab are one target's. The pinned `Sample filters` and the
Overview's filter bars stay optional, so the Overview and Model scores read every target.

## Method notes

- Model ranks are renumbered from 1 (the top-ranked model, the one in
  `top_ranked_structures`) because engines number their models from 0 (AlphaFold2, ESMFold,
  RoseTTAFold All-Atom) or from 1 (ColabFold).
- pLDDT bands follow AlphaFold and are labelled as its legend labels them: Very high (90 and
  above), Confident (70 to 90), Low (50 to 70), Very low (below 50). Their colours are the
  AlphaFold ones, declared once as `category_colors` on the Overview. RoseTTAFold All-Atom
  writes pLDDT as a 0 to 1 fraction in its PDB; the residue table rescales it to 0 to 100, and
  the 3D, sequence-track and Ramachandran tiles decide the scale once per structure.
- ESMFold numbers the second chain of a complex from 665 (its chain linker offset); the residue
  table keeps the structure's numbering so the 3D tile can pick residues by it.
- The integer-coded alignments use the HHblits alphabet for monomer runs and AlphaFold's
  residue-type order for AlphaFold2 multimer; each file is decoded with the order under which
  its first row reads as the sequence of the structure folded from it. Alignments are capped at
  500 rows; `depth` keeps the full count.
- ipTM and ipSAE files are empty for single-chain targets; the score scan reads empty files as
  no rows and the scores stay null.
- Profiles longer than 200 residues are averaged over equal windows.
- The MultiQC reports proteinfold writes per engine hold one custom-content pLDDT plot per
  target, named after the target; they repeat the residue table and cannot be bound
  generically, so the template has no MultiQC tab.
