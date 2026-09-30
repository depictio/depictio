# nf-core/proteinfold 2.1.0: Depictio dashboards

This template turns the output of [nf-core/proteinfold](https://nf-co.re/proteinfold) 2.1.0
into a four-tab Depictio dashboard. proteinfold predicts protein structures from sequence with
one or several engines (AlphaFold2 in standard or split-MSA mode, ColabFold, ESMFold,
RoseTTAFold All-Atom, Boltz, ...), each writing its top-ranked model per target, the
per-residue confidence (pLDDT) of every model, TM scores, predicted aligned error (PAE)
matrices and, for the MSA-based engines, the alignment it folded from.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `targets` | the samplesheet (`METADATA_FILE`, default `input/samplesheet.csv`) plus the structures | target |
| `proteinfold_structures` | `<engine>[/<mode>]/top_ranked_structures/<target>.pdb` (indexed file) | structure |
| `proteinfold_residues` | the same PDBs, pLDDT from the CA B-factor | structure and residue |
| `proteinfold_engine_plddt` | the same PDBs, one curve per engine and chain | target, engine curve, residue |
| `proteinfold_models` | `<target>_plddt.tsv`, `_ptm.tsv`, `_iptm.tsv`, `_ipsae.tsv` | structure and model rank |
| `proteinfold_plddt_ranks` | `<target>_plddt.tsv`, top model plus the lowest and highest model | structure and residue |
| `proteinfold_pae` | `paes/<target>_<k>_pae.tsv`, top model only, plus each row's mean | structure and residue bin |
| `proteinfold_msa` | `<target>_<engine>_msa.tsv` | alignment row |

The unit of every structure tile is the **entity**: one engine's top-ranked structure of one
target. Its id is the id the structures collection gives the PDB, `<engine>__<target>` with a
non-default AlphaFold2 mode between the two (the named groups of the collection's sample regex
joined with `__`), so every per-structure table joins the 3D object without a lookup. The `engine` and `target` columns carry the reader-facing names; AlphaFold2 modes other
than `standard` show in the engine name.

proteinfold does not publish the samplesheet it ran on, so the template ships the test_full
sheets under `input/` and reads them by default; point `METADATA_FILE` at the sheet of another
run. Sheet columns beyond `id` and `fasta` are kept, so any of them can become `GROUP_COL`.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/samplesheet.csv` | samplesheet read by `targets` |
| `METADATA_ID_COL` | `id` | samplesheet id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `assembly`, `Assembly` | grouping filter and glance card; `assembly` is derived (single chain or complex) |

## Tabs

### Overview

The glance strip counts targets (by `GROUP_COL`), engines, models and residues to fold. The
top-ranked cards read the model each engine ranked first: mean pLDDT, the share of residues at
pLDDT 70 or more, pTM and the best ipTM. The scatter puts every model's mean pLDDT against its
pTM (engines without TM scores, ESMFold and RoseTTAFold All-Atom, drop out), and the box plot
compares engines over all their models.

### Structure

The structure picker's engine and target are `always_selected`: the tab opens on the first
engine and the first target of their lists, so every tile shows one structure, and the reader
changes either on the left. The 3D tile
(`molecule_3d`, `layout: structure_msa`) draws the top-ranked PDB coloured by pLDDT from its
B-factor column, beside the alignment the engine folded it from; the sequence track below
draws the pLDDT lane, each residue coloured by its AlphaFold confidence band. The three tiles share the
`entity` and `position` column names, so a click on a residue in 3D, a brush on the sequence
track or a column brush on the alignment emits one `residue_selection` that moves the other
two; hovering highlights the same residue everywhere, including a vertical line on the
per-engine profile (`residue_axis: true`). On a complex the alignment's query is the chains
concatenated; its `chains` layout translates a column into one chain's own residue number, and
picks and hovers carry that chain.

The per-engine profile reads its own collection (`proteinfold_engine_plddt`), which carries
no `engine` column (the engine is in the curve label). A dashboard filter narrows every
collection that has its column, so the picker's target narrows the curves while its engine
cannot: every engine's top-ranked curve of the picked target stays on screen. On a complex
each chain draws its own curve in its own numbering.

A lone query row in the alignment is the data, not a filter: the engine found or used no
homologs (AlphaFold2 run against reduced databases writes a one-row MSA).

The sequence track has no separate category lane: its pLDDT lane is coloured by band, so the
legend lists the four bands once.

pLDDT bands follow AlphaFold and are labelled as its legend labels them: Very high (90 and
above), Confident (70 to 90), Low (50 to 70), Very low (below 50). RoseTTAFold All-Atom writes pLDDT as a 0 to 1 fraction in its PDB; the
residue table rescales it to 0 to 100. The 3D colouring reads the B-factor directly, so the
viewer must apply the same rescaling to keep one scale across engines.

### Predicted error

The PAE heatmap shows the top-ranked model's predicted aligned error: row residues are the
ones the model is aligned on, columns the ones whose position error is read. Matrices are
averaged into at most 64 bins per axis so any length fits one tile; row k and column bk cover
the same residues, counted from 1 over the chains in order. Dark off-diagonal blocks are
domains or chains placed confidently relative to each other. ESMFold writes no PAE. The matrix
picker's engine and target are `always_selected`, so the heatmap opens on one matrix instead of
every matrix stacked. The cards read pTM and ipTM of the top model and the matrix's mean PAE
(the average of each row bin's mean over its residues). ipSAE stays in the models table and
record on the Engines comparison tab: it is null for single chains and, on a complex without a
confidently placed interface, 0 on every model, which reads as a constant on a card. The matrix
table rounds errors to 3 decimals.

### Engines comparison

The tab compares engines on one target: its target picker is `always_selected` (the first
target until another is picked), and since a dashboard filter narrows every collection that
carries its column, the whole tab follows it. The engine and model rank filters are optional,
so every engine is compared unless narrowed. The line chart follows each engine's mean pLDDT
from its first to its last model rank (a steep fall means a decisive ranking). The profile
draws one curve per engine, residue by residue: the line is the top-ranked model and the band
runs from the lowest to the highest of its models, so a wide band marks residues the engine's
models disagree on and curves that part mark residues the engines disagree on. Drawing every
model instead would stack up to 25 curves per engine (AlphaFold2 multimer). The model rank
filter narrows the models, not the band. The models table and its record card close the tab.

## Method notes

- Model ranks are renumbered from 1 (the top-ranked model, the one in
  `top_ranked_structures`) because engines number their models from 0 (AlphaFold2, ESMFold,
  RoseTTAFold All-Atom) or from 1 (ColabFold).
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
