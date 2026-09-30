# Protein structure, alignment and sequence tiles

**Status:** Landed with the third nf-core template lot (`molecule_3d`, `msa`, `sequence_track`,
the `residue_selection` cross-filter and the hover highlight bus).
**Audience:** maintainers and template authors wiring protein outputs into a dashboard.
**Related:** `docs/design/advanced-viz.md` (section 9), `docs/indexed-files.md`,
`depictio/models/components/advanced_viz/configs.py`,
`packages/depictio-react-core/src/components/advanced_viz/{molecule,protein}/`.

Structure prediction, protein annotation and protein family pipelines publish three things a
reader wants to see together: a 3D model, the alignment it was folded from or classified
against, and per-residue facts (confidence, secondary structure, domains, variants). Before this
module a dashboard could only draw those facts as lines and bars on a residue axis. The goal is a
small set of tiles that show one protein three ways and stay linked: pick a residue anywhere and
every tile moves to it, point at a residue anywhere and every tile marks it. A full molecular
viewer is out of scope (see section 7).

## 1. Data contract

Every protein tile reads tables joined on two column names, `entity` (which protein, or which
target of a prediction) and `position` (the 1-based residue number in the structure's own
numbering). Nothing else links them: no project link, no shared collection. A residue pick
travels between tiles because their collections carry those two names.

**Structure files.** An `indexed_file` data collection with `format: pdb` or `format: mmcif`
(aliases `ent` and `cif`; `.pdb`, `.ent`, `.cif`, `.mmcif`, each optionally gzipped). One object
per entity: the sample id the scan derives is the entity id, so it must equal the `entity` value
of the residue tables. No index sidecar, the file is fetched whole. Predictors write pLDDT into
the B-factor column, which is what `color_mode: plddt` reads.

**Residue table** (one row per residue and entity):

| column | type | role |
| --- | --- | --- |
| `entity` | string | join key |
| `chain` | string | chain id, needed on complexes (numbering restarts per chain) |
| `position` | int | residue number, required |
| `residue` | string | one-letter amino acid |
| `value` | float | per-residue score (pLDDT, conservation) |
| `category` | string | per-residue class (secondary structure, domain) |

`depictio/recipes/lib/protein_structure.py` builds the first five straight from a PDB
(`RESIDUE_SCHEMA`), rescaling a 0 to 1 pLDDT to 0 to 100 when every B-factor of a model lies in
[0, 1]. `sequence_track` reads `chain` by that fixed name on a complex.

**Variant table:** `entity`, `position`, `ref_aa`, `alt_aa`, a consequence column, a label
column (a protein change), optionally a numeric column that sizes the marks.

**Domain table:** `entity`, `start`, `end`, `label` (each configurable on `sequence_track`), and
optionally `source` (the annotation database), which is read by that fixed name.

**MSA table** (`MSA_SCHEMA` in `depictio/recipes/lib/msa.py`): one row per aligned sequence,
`msa_id`, `seq_id`, `rank`, `aligned_sequence`, `identity`, `coverage`, plus the optional
`chains` layout of a multi-chain reference row (`A:1-664,B:665-1004`: each chain's first and last
residue, in concatenation order). Every row of one `msa_id` has the same length (A3M insertions
are dropped by the recipe), rank 0 is the query or reference row, and `msa_id` must equal the
`entity` value it aligns, because the tiles use it as the entity. The recipe parses
integer-coded proteinfold MSAs, A3M, Stockholm and aligned FASTA.

## 2. The three kinds

All three use the `none` sampling policy (`KIND_SAMPLING_POLICY`): a sampled residue table
leaves holes in the colouring and the ruler. The MSA is capped at `max_rows` in rank order
instead. All three default `selection_enabled` to `true` (`SELECTION_ON_BY_DEFAULT` in
`record_link.py` and `selection.ts`), unlike every other kind. Required roles are `position` for
`molecule_3d` and `sequence_track`, `msa_id` + `seq_id` + `sequence` for `msa`.

| kind | renderer | config fields (defaults) |
| --- | --- | --- |
| `molecule_3d` | 3Dmol.js in a lazy chunk | `structure_source` (`file` \| `resolve`), `structure_dc_id` / `structure_wf_id` / `structure_dc_tag`, `entity_col` (`entity`), `uniprot_col`, `gene_col`, `sequence_col`, `taxon` (9606), `position_col` (`position`), `chain_col`, `value_col`, `category_col`, `ref_aa_col`, `alt_aa_col`, `label_col`, `color_mode` (`plddt` \| `chain` \| `spectrum` \| `value` \| `category` \| `secondary_structure` \| `residue_type` \| `hydrophobicity` \| `uniform`), `colour_scale` (Viridis when null), `representation` (`cartoon` \| `trace` \| `stick` \| `sphere` \| `surface`), `representations` (a list of the same, replaces `representation` when set), `highlight_site` (true), `spin` (false), `show_variants` (true), `show_labels` (false), `layout` (`structure` \| `structure_sequence` \| `structure_msa` \| `structure_text`), `msa_dc_id` / `msa_wf_id` / `msa_dc_tag`, `selection_enabled` (true), `follow_selection` (true) |
| `msa` | canvas `MsaPanel` | `msa_id_col` (`msa_id`), `seq_id_col` (`seq_id`), `sequence_col` (`aligned_sequence`), `rank_col` (`rank`), `identity_col` (`identity`), `color_scheme` (`clustal` \| `zappo` \| `hydrophobicity` \| `identity` \| `none`), `max_rows` (200, at most 1000), `sort_by` (`rank` \| `identity` \| `input`), `show_consensus` (true), `show_conservation` (true), `entity_col_for_selection` (`entity`), `position_col_for_selection` (`position`), `chains_col` (`chains`), `chain_col_for_selection` (`chain`), `selection_enabled` (true), `follow_selection` (true) |
| `sequence_track` | canvas `SequenceStrip` | `entity_col` (`entity`), `position_col` (`position`), `residue_col` (`residue`), `value_col`, `category_col`, `value_label`, `domains_dc_id` / `domains_wf_id` / `domains_dc_tag`, `domain_start_col` (`start`), `domain_end_col` (`end`), `domain_label_col` (`label`), `variants_dc_id` / `variants_wf_id` / `variants_dc_tag`, `variant_position_col` (`position`), `variant_label_col` (`label`), `variant_category_col` (`category`), `selection_enabled` (true), `follow_selection` (true) |

`molecule_3d` validates two combinations: `structure_source: resolve` needs one of
`uniprot_col`, `gene_col` or `sequence_col`, and `layout: structure_msa` needs `msa_dc_id` or
`msa_dc_tag`. Its bound collection is the residue or variant table that colours and marks the
model; the structure comes from the companion collection or the resolver. Variants are spheres
on the alpha carbon, sized by `value_col` when bound. The entity shown is the one the dashboard's
filters name on `entity_col`, else the reader's pick in the tile, else the first.

Colour modes that read the structure itself: `secondary_structure` paints the helix and strand
3Dmol assigns (from the file's HELIX and SHEET records, else computed from the backbone), in the
RasMol structure colours the sequence track's glyphs use, coil neutral; `residue_type` hands the
model to 3Dmol's `amino` scheme and draws no legend; `hydrophobicity` colours each residue by its
Kyte-Doolittle score on the ramp the `msa` kind's hydrophobicity scheme uses, so a residue has one
colour in both tiles. `representations` combine in one style (a cartoon or a trace, sticks,
spheres, sticks with spheres drawn as ball and stick, a surface on top); a surface alone keeps a
cartoon under it, because 3Dmol does not hover or pick a surface. `highlight_site` draws the
picked residue or range (the tile's own pick, or another tile's when following) as red ball and
stick over the representation, up to 50 residues; a longer range keeps the plain selection
sticks. `spin` starts the model turning; the view buttons (reset, spin, save as PNG) sit at the
top right of the canvas whatever the setting.

In the tile, the Style control is a multi-select over the representations (the last one cannot
be removed), and Colour by lists every mode whose inputs are bound (`value` and `category` need
their column).

`sequence_track` draws, on one 2D canvas: a ruler, the one-letter sequence (blocks when too dense
to read), a value lane, a category lane, domain spans and variant lollipops. The value lane uses
the AlphaFold confidence bands (above 90, 70 to 90, 50 to 70, below 50) when `value_label`
contains "pLDDT", else a colour scale. The category lane draws helix and strand glyphs when every
value reads as a DSSP or S4PRED class (`H`, `G`, `I`, `E`, `B`, `T`, `S`, `C`, or the words), else
categorical blocks. The domain and variant companions are fetched with the tile's filters plus a
scope filter on the entity column, so they must carry the same entity column name.

`msa` shows one alignment at a time, the one whose `msa_id` another tile or a sidebar selector
names on the entity column. A row click emits a `scatter_selection` on `seq_id_col`; a column
brush emits a `residue_selection` in the reference row's numbering (gap columns of the reference
carry no residue number). With a `chains` layout on the reference row, the brush is translated
into one chain's own numbering and the chain is named on `chain_col_for_selection`.

### Combined layouts

`molecule_3d` `layout` puts a second panel in the same tile, beside or under the structure
depending on the tile's aspect (side by side when the tile is at least 1.3 times wider than
tall), with a draggable divider (structure share 0.2 to 0.85):

- `structure_sequence`: a `SequenceStrip` of the model's own primary chain, letters and pLDDT
  read from the structure (or the bound `value_col` outside the pLDDT colour mode), variant ticks
  from the bound table. Default structure share 0.75.
- `structure_msa`: an `MsaPanel` of the `msa_dc_id` collection, filtered server-side to
  `msa_id = entity`, so only that alignment travels. The embedded panel reads the canonical MSA
  column names (`msa_id`, `seq_id`, `aligned_sequence`, `rank`, `identity`, `coverage`, `chains`),
  not the `msa` kind's config. Default structure share 0.55. Without an MSA binding the tile falls
  back to `structure`.
- `structure_text`: the model's one-letter sequence written as plain monospace text under the
  structure, every chain of the model in its own block, wrapped to the pane in lines of
  ten-letter blocks with the number of each line's first residue at its start (structure
  numbering). A letter click picks that residue exactly as a click in 3D does (a
  `residue_selection`, the red site), and zooms onto it; shift-click extends from the last pick
  to a range. Hovering a letter publishes on the highlight bus and marks the residue in 3D. The
  letters show what the rest of the dashboard says: the pick red, underlined, on a light red
  background; the bound table's variants in red; the hovered residue outlined. A pick made
  elsewhere scrolls into view when it is out of sight. The text scrolls inside its pane, one
  listener per gesture on the text area (event delegation), and a hover re-renders only the lines
  it enters and leaves. Default structure share 0.7, always stacked.

Hover and selection are shared inside the tile as between tiles. One combined tile costs one
WebGL slot and one set of chrome, which is the reason for the layout rather than two tiles.

### Compact placement

The protein tabs put the 3D tile on half the section width, about 520 px high (`w: 4, h: 5`),
beside the selector that drives it (a scatter or a lollipop whose click names one entity or one
residue range), with the sequence track and the alignment full width below and the tables
collapsed under them. At that size the tile keeps its controls in the header
(`controls_placement: header`), and below 560 by 440 px of body the colour legend flows its
swatches in rows in the bottom-left corner and lets the pointer through. The written sequence
wraps to the pane width, so nothing overflows sideways.

## 3. Linking: `residue_selection` and the highlight bus

Two channels, because a pick and a hover have opposite costs.

### A pick is a filter

A residue pick is an ordinary filter pair with `source: 'residue_selection'`, built by
`residueRangeFilters` in `packages/depictio-react-core/src/selection.ts`: a `MultiSelect` on the
entity column carrying `[entity]` (index = the tile's index), and a `RangeSlider` on the
position column carrying `[start, end]`, inclusive (index suffix `::res`, as a genome region uses
`::pos`). A tile bound to a single entity omits the entity half. On a complex a third filter, a
`MultiSelect` on the chain column (suffix `::chain`), names the chain. Because these are plain
column filters, any residue or variant table with the same column names narrows with no server
change.

- **Emitters:** `molecule_3d` (click, shift-click extends the range), `sequence_track` (brush or
  click), `msa` (column brush), `lollipop` with `selection_enabled: true` (click on a stem; the
  entity column is `feature_id_col`; opt-in, default false, plus a point selection on
  `selection_column`, else `label_col`).
- **Readers:** every protein tile reads the range back by column name with
  `residueRangeFromFilters`, whatever tile or sidebar control set it. Several ranges on one
  position column intersect (they all apply server-side); an entity column carrying several
  values yields no range. `molecule_3d` rings the range and, with `follow_selection`, zooms onto a
  pick made elsewhere (its own click leaves the camera alone). `msa` shades the columns,
  `sequence_track` highlights the residues. `lollipop` and `profile` keep every row and shade the
  range (`withoutResidueRanges`): a range is a place to look, not a subset.
- **Own pick:** an emitting tile drops both halves of its own selection before fetching
  (`filtersExcludingOwnResidue`), so it keeps drawing the whole protein and rings its pick.

**Last gesture wins.** `mergeFiltersBySource` replaces every `residue_selection` filter on the
same column when a new one arrives, whichever tile emitted it. Without that, a click on one
residue in 3D followed by a brush over another stretch in the alignment would intersect to
nothing.

**Cards and sidebar controls ignore it.** Like a genome region, a residue range is scoped out of
cards, of figures that do not encode its column, and of interactive filters' option lists, on the
client (`cardScopedFilters`) and on the server (`depictio/api/v1/region_scope.py`, both halves).
A card opts back in with `follow_region_filter: true`. A `record_card` linked to a
`molecule_3d`, `sequence_track` or `lollipop` receives the pair as ordinary column filters and
shows the rows in the range, so the `id_col` agreement check is skipped for those sources
(`RESIDUE_EMITTING_KINDS` in `record_link.py`).

### A hover is not a filter

Routing a hover through the filter list would refetch every tile on every mouse move. The
highlight bus (`packages/depictio-react-core/src/highlight/bus.ts`) is an in-memory store, one per
dashboard view, created by `HighlightProvider` in `DashboardGrid` (nest-safe: an inner provider
reuses the outer bus). An event carries `sourceIndex`, `start`, `end`, and optionally `entity`,
`chain`, `rowKeys` and `positionColumn`.

- Publishes are coalesced to one per animation frame (`requestAnimationFrame`, a 16 ms timer
  without it); the last event queued before the frame wins, and subscribers are notified only
  when it differs from the event in force.
- `usePublishHighlight(index)` binds the source; publishing `null` clears only what that tile put
  up, so one tile's pointer-leave never wipes another tile's hover.
- `useHighlight(index, enabled)` returns the event in force, `null` for the tile's own events. A
  tile that is not on a residue axis passes `enabled: false` and does not subscribe at all.
- Outside a provider (catalog preview, record panels, tests) the hook returns `null` and publish
  is a no-op.

Publishers and consumers: `molecule_3d`, `msa` and `sequence_track` both publish and consume
(translucent spheres in 3D, a crosshair in the alignment, a marked residue on the track);
`lollipop` publishes on stem hover and draws an incoming one as a dotted line, drawn over the
finished figure so a hover never rebuilds it; `profile` with
`residue_axis` draws the hovered residue as a vertical line and the picked range as a shaded band,
and publishes its own hover. `residue_axis: null` guesses from the x column name (`position`),
`true` or `false` forces it, so a coverage or fragment-length profile never re-renders on a
protein hover.

## 4. Where the structure comes from

**`structure_source: file`** reads the manifest of the companion `indexed_file` collection
(`GET /depictio/api/v1/files/indexed/{dc_id}`), picks the object whose sample id equals the
entity, and fetches it through its presigned URL (15 minutes). This is the default and needs no
outbound network from the server.

**`structure_source: resolve`** asks `POST /depictio/api/v1/advanced_viz/structure/resolve` with
the shown entity's value in `uniprot_col`, `gene_col` (plus `taxon`) or `sequence_col`. The
answer is a presigned URL of a PDB in the deployment's bucket plus `source` (`afdb`, `esmfold` or
`cache`), `origin` (where the model came from, also on a cache hit), `accession` and the model's
sequence. The browser keeps a per-session memo keyed by the normalised request.

### The resolver

Order, first hit wins (`structure_resolver.py`):

1. the bucket cache, keyed by the SHA-256 of the normalised request (accession and gene upper
   cased, whitespace and a trailing `*` stripped from the sequence, taxon counted only with a
   gene);
2. `uniprot`: AlphaFold DB `/api/prediction/{accession}`, then the entry's `pdbUrl`;
3. `gene` + `taxon`: UniProt REST search (`gene_exact`, `organism_id`, `reviewed:true`, first
   result) for the accession, then AlphaFold DB as above;
4. `sequence`: ESMFold, when the sequence is at most `esmfold_max_length` residues.

Input is validated first: a UniProtKB accession pattern, a gene-symbol pattern that keeps the
value out of the UniProt query syntax, a positive taxon, the 20 standard amino-acid letters. A
sequence over the ESMFold cap with no accession or gene is a 400; with one, it is only noted as a
miss. Answers: 403 when disabled or when the caller is the anonymous visitor of a public
instance (single-user mode, whose one user is the anonymous account, is served), 400 for an
invalid request, 404 when every upstream answered
without a structure, 502 when an upstream failed (the detail names which; a failure outranks a
miss), 500 when the bucket write failed.

Limits and safety: only the hosts of the three configured URLs are contacted, redirects included
(followed by hand, at most three, each re-checked); every response is capped at `max_bytes`,
by `Content-Length` and while streaming; a body with no `ATOM` record is rejected; a 502, 503 or
504 is retried once after 2 s (ESM Atlas answers 504 while a fold warms up); each upstream call
has a `timeout_s` timeout, and one resolve request spends at most `total_timeout_s` across all its
calls and retries (a strategy reached after that fails fast with a 502), so a request cannot hold
a worker thread for minutes. Identical concurrent requests in one process wait for the first and then
read its cache entry. A hit is stored as `<cache_prefix>/<sha>.pdb` plus a `<sha>.json` sidecar
written last (the lookup reads the sidecar, so a half-written entry is a miss). Negative results
are not cached: a 404 or 502 asks the upstreams again next time.

| setting | env var | default |
| --- | --- | --- |
| `enabled` | `DEPICTIO_STRUCTURE_RESOLVER_ENABLED` | `false` |
| `afdb_base_url` | `DEPICTIO_STRUCTURE_RESOLVER_AFDB_BASE_URL` | `https://alphafold.ebi.ac.uk` |
| `uniprot_base_url` | `DEPICTIO_STRUCTURE_RESOLVER_UNIPROT_BASE_URL` | `https://rest.uniprot.org` |
| `esmfold_url` | `DEPICTIO_STRUCTURE_RESOLVER_ESMFOLD_URL` | `https://api.esmatlas.com/foldSequence/v1/pdb/` |
| `timeout_s` | `DEPICTIO_STRUCTURE_RESOLVER_TIMEOUT_S` | `60.0` |
| `total_timeout_s` | `DEPICTIO_STRUCTURE_RESOLVER_TOTAL_TIMEOUT_S` | `120.0` |
| `max_bytes` | `DEPICTIO_STRUCTURE_RESOLVER_MAX_BYTES` | `20971520` (20 MiB) |
| `esmfold_max_length` | `DEPICTIO_STRUCTURE_RESOLVER_ESMFOLD_MAX_LENGTH` | `400` |
| `cache_prefix` | `DEPICTIO_STRUCTURE_RESOLVER_CACHE_PREFIX` | `structures/resolved` |

Compose and Helm forward only `DEPICTIO_STRUCTURE_RESOLVER_ENABLED`; the other variables reach a
container only if added to the service's `environment:` (or the Helm configmap).

**Privacy.** When enabled, exactly the accession, the gene symbol and taxon, or the sequence
leaves the server, to EBI (AlphaFold DB), UniProt, or Meta's ESM Atlas. For unpublished
sequences that can be a disclosure, which is why the resolver is off by default and answers 403
until an operator turns it on. The route refuses anonymous visitors outside single-user mode, so
on a public instance only signed-in users trigger those calls (and fill the bucket cache); the
tile tells an anonymous visitor to sign in.

**Licence.** AlphaFold DB models are CC-BY 4.0. The tile shows a credit line with the model
(`Model: AlphaFold DB, CC-BY 4.0`, or `Model: ESMFold`), from `origin`, so a cached model keeps
its credit.

## 5. Numbering mismatch

A variant table and a structure do not always number residues the same way (a construct, an
isoform, an off-by-one in a caller). `checkVariants` (`molecule/residueData.ts`) sorts each row
into three lists:

- **drawn:** the structure has a residue at that position (on the row's chain, else the primary
  chain, else any chain) and either the row has no `ref_aa` or it matches;
- **mismatched:** the residue exists but `ref_aa` disagrees with it. The mark is not drawn; a
  "numbering mismatch" badge lists each one with the residue the model has there, and the residue
  tooltip repeats it;
- **outside:** the model has no residue at that position (a truncated model); counted in an
  "outside the model" badge.

Drawing a variant on the wrong residue is worse than not drawing it, hence the rule.

## 6. Storage origin and CSP

File-backed tiles (and resolved models) fetch presigned URLs from the storage endpoint the
browser can reach (`DEPICTIO_S3_PUBLIC_URL`, else `DEPICTIO_S3_EXTERNAL_HOST` and
`DEPICTIO_S3_EXTERNAL_PORT`). When that is another origin than the app, the browser blocks the
fetch unless the page's CSP `connect-src` allows it. The API appends the origin of
`settings.minio.external_url` to `connect-src` on every response (`storage_origin` and
`csp_with_connect_origins` in `security_headers.py`). The nginx viewer image serves its own
policy: set `DEPICTIO_CSP_CONNECT_EXTRA` to the same origin (space separated for several). The
bucket also needs CORS for the viewer origin; see `docs/indexed-files.md`.

## 7. Why not embed Mol*

Mol* is the reference web viewer, and a reader doing structural analysis should use it. The tile
is not that viewer, it complements it:

- **Bundle.** 3Dmol.js loads through `import('3dmol')` into its own chunk, only when a 3D tile
  mounts. A dashboard without one never downloads it; the catalog preview aliases it to a stub.
  Mol* is a much larger application with its own UI framework.
- **Cross-filtering.** What the tile adds is the dashboard link: residue picks as filters, hover
  on the bus, colours from a Depictio table. Those need hover and click callbacks at residue level
  and styling from a per-residue function, which the narrow adapter in `molecule/viewer.ts`
  exposes. Mol*'s plugin state model would have to be driven from outside for the same result.
- **WebGL budget.** The tile takes one slot of the page-wide budget (`useWebglSlot`), like a
  `scattergl` plot or a GenomeSpy track, and releases its context on unmount.

Linking out to a full viewer for the shown entity (AlphaFold DB page, or a Mol* instance on the
same file) is future work.

## 8. Performance mechanisms

None of the following is benchmarked; they are the mechanisms, not measured gains.

- **Lazy 3Dmol chunk**, as above. A tile probes the module before fetching a structure and
  shows an explained empty state when it is the preview stub.
- **WebGL slot budget.** `useWebglSlot(true)` asks for one of the page's GL slots
  (`webglBudget.ts`). A tile that gets none says so and keeps its sequence or alignment panel;
  the CA-only parser in `structureText.ts` still gives it the sequence, numbering and pLDDT
  without a context.
- **Canvas virtualisation.** `MsaPanel` and `SequenceStrip` draw on one DPR-aware 2D canvas and
  only the rows and columns intersecting the viewport plus an overscan (`visibleWindow` in
  `protein/canvas.ts`). Letters appear only above a readable cell size.
- **No re-parse on an unchanged object.** Structure text is cached per object, keyed by the URL
  without its query string (a new presigned signature is the same object), as a shared promise so
  two tiles share one download, capped at 24 entries (LRU by insertion order). The viewer's
  effects run in order (load, colours, style, selection, overlays), and a filter change that
  leaves the object alone reaches none of the first three. A hover adds and removes shapes and
  never restyles the model.
- **Hover off the filter path**, coalesced per frame, as in section 3.

## 9. Adding a protein tile to a template

Declare the structure collection as an `indexed_file` with `format: pdb` (or `mmcif`) and a
`sample_regex` whose result equals the `entity` value of the residue tables. A regex without a
`sample` group names the object by its named groups joined with `__`, which covers an entity
built from two path parts. Then bind the tiles, naming companion collections by tag:
`structure_dc_tag`, `msa_dc_tag`, `domains_dc_tag`, `variants_dc_tag`. The dashboard import
resolves every `<base>_dc_tag` of a config into `<base>_dc_id` and `<base>_wf_id` in the same
workflow, and clears both when the tag names no collection of the project. The seed generator
does not resolve tags, so a showcase seed binds companions by id.

```yaml
- component_type: advanced_viz
  tag: <prefix>-structure
  section: <section>
  workflow_tag: <workflow>
  data_collection_tag: <pipeline>_residues
  viz_kind: molecule_3d
  config:
    viz_kind: molecule_3d
    structure_source: file
    structure_dc_tag: <pipeline>_structures
    entity_col: entity
    position_col: position
    layout: structure_text
    msa_dc_tag: <pipeline>_msa
    color_mode: plddt
    highlight_site: true
    controls_placement: header
  layout: {x: 4, y: 0, w: 4, h: 5}
- component_type: advanced_viz
  tag: <prefix>-sequence
  section: <section>
  workflow_tag: <workflow>
  data_collection_tag: <pipeline>_residues
  viz_kind: sequence_track
  config:
    viz_kind: sequence_track
    entity_col: entity
    position_col: position
    residue_col: residue
    value_col: value
    value_label: pLDDT
    category_col: category
    domains_dc_tag: <pipeline>_domains
    variants_dc_tag: <pipeline>_variants
  layout: {x: 0, y: 4, w: 8, h: 4}
```

The selector on the other half is any tile whose click leaves one value on a column named like
`entity_col` (a `scatter_xy` with one point per structure, for example): the 3D tile shows the
entity a filter names when it names exactly one, and in file mode that value must equal the
structure's indexed_file sample id.

A catalog output can carry the same bindings as a `Render` entry (`kind: molecule_3d`,
`roles: {position: position, entity: entity, ...}`), which a template consumes with `use:`. Put
the 3D tile, the sequence track and the residue table in one section, add a sidebar selector on
the entity column so the reader picks the protein, and set `residue_axis: true` on a per-residue
`profile` whose x column is not called `position`.

## 10. Testing

- **vitest** (`packages/depictio-react-core`): `highlight/bus.test.ts`,
  `selection.residue.test.ts`, `selection.proteinKinds.test.ts`,
  `selectionGroups.residue.test.ts`, `components/advanced_viz/molecule/{residueData,resolve,
  sequenceLines,splitView,structureText,viewer}.test.ts` (the written sequence's wrapping,
  numbering, marks and click-to-range; the representation, site and colour-mode mapping), `components/advanced_viz/protein/{alignment,canvas,
  rendererData,residueColours,sequence}.test.ts`, `components/advanced_viz/lollipopOverlay.test.ts`,
  plus the protein cases in `splitPanels.test.ts` (kind buckets) and
  `record_card/recordSelection.test.ts` (a residue pick reaching a record card).
- **pytest:** `depictio/tests/models/test_advanced_viz_protein_kinds.py`,
  `depictio/tests/models/test_record_link_residue.py`,
  `depictio/tests/models/data_collections_types/test_indexed_file.py`,
  `depictio/tests/api/v1/test_structure_resolver.py` (upstreams and bucket faked: order, cache,
  retry, timeout, size cap, redirect allowlist, validation),
  `depictio/tests/api/v1/test_security_headers.py` (storage origin in `connect-src`, nginx and
  API policies identical once `${DEPICTIO_CSP_CONNECT_EXTRA}` is removed),
  `depictio/tests/unit/test_region_scope_residue.py`,
  `depictio/tests/cli/utils/test_indexed_file_ingest.py`,
  `depictio/tests/unit/recipes/{test_msa_lib,test_protein_structure_lib}.py` and
  `depictio/tests/recipes/test_proteinfold_recipes.py`. The existing
  `depictio/tests/models/test_advanced_viz_config_alignment.py` keeps the TypeScript config
  interfaces in step with the models.
- **e2e:** `depictio/tests/e2e-playwright/tests/catalog/catalog-modules-on-dashboard.spec.ts`
  accepts
  `.depictio-molecule-3d canvas` or `[data-testid="advanced-viz-empty"]` for `molecule_3d` (a
  tile placed alone has no structure bound and CI runs with the resolver off),
  `.depictio-msa canvas` for `msa` and `.depictio-sequence-track canvas` for `sequence_track`.
  The showcase's protein structure tab exercises the linked view end to end.
