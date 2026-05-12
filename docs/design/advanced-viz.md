# Advanced Visualisations for Depictio (React)

**Status:** Design proposal — not yet implemented
**Branch:** `claude/volcano-plot-interactive-cTRTQ`
**Predecessor:** `claude/python-bioinformatics-setup-oVDOo` (Dash prototypes; lessons distilled below)
**Audience:** maintainers reviewing before any code lands.

---

## 1. Goal

Add a family of *advanced* visualisation components to the React viewer (`depictio/viewer`) — each one is a self-contained panel that bundles a non-trivial chart with its **builtin controls** (filters, dropdowns, sliders, search, threshold lines) and participates in **cross-component coordination** (responds to sidebar/global filters; optionally publishes selections back).

A "simple" component renders one chart. An advanced component renders **chart + controls + reactive bindings** as one cohesive unit. Volcano plot is the canonical example; the catalogue below covers 10 patterns spanning bulk omics, single-cell, metagenomics, variants/clinical, and lightweight spatial/imaging.

Out of scope for v1: heavy image processing (pyramidal WSI, Vitessce/Viv), large-scale 3D molecular viewers.

---

## 2. Catalogue (10 viz, 4 domains)

Curated from a 14-item survey across nf-core pipelines, Bioconductor Shiny apps, Plotly Dash Bio, cBioPortal, UCSC Cell Browser, Vitessce, igv.js. Each row picks a distinct *interaction shape* so that building them in order forces the framework through different stress tests.

| # | Viz | Domains | Builtin controls | Reads (sidebar/coordination) | Publishes | React lib |
|---|---|---|---|---|---|---|
| 1 | Volcano + threshold + search | bulk RNA, proteomics, diff-abundance, microbiome | logFC slider, p/FDR slider, label-top-N, search, log-axis | sample subset, contrast | selected feature(s), brushed region | plotly.js |
| 2 | Embedding (PCA / UMAP / t-SNE / PCoA) | bulk + sc + microbiome + image-derived features | method dropdown, colour-by, point-size, density toggle, lasso | sample subset, gene-as-colour | brushed cells/samples | plotly.js (WebGL) or deck.gl |
| 3 | Clustergram (heatmap + dendrogram) | bulk RNA, proteomics, sc pseudo-bulk | cluster method, scale (z/log), top-N variable, annotation tracks | sample subset, gene set | brushed cells/genes | plotly.js, visx |
| 4 | Stacked taxonomy / composition bar | metagenomics, ampliseq, immune-repertoire | rank dropdown, top-N, sort, normalise | sample subset, group | selected sample / taxon | plotly.js |
| 5 | OncoPrint | variants, clinical cohorts | sort-by gene/clinical, alteration filters, group-by | cohort subset, gene-list | selected sample/gene | oncoprintjs |
| 6 | Lollipop / needle (mutation on protein) | variants, proteomics-structure | domain-track toggle, type filter, hotspot threshold | gene, cohort subset | selected residue | dash-bio NeedlePlot |
| 7 | Manhattan / GWAS | variants, QTL, ChIP/ATAC peak significance | p-threshold line, chr selector, zoom-to-locus, label-top-loci | trait, cohort | selected SNP/locus (chr,pos) | plotly.js (WebGL) |
| 8 | Embedded genome browser | bulk, ChIP/ATAC, variants, sc-multiome | locus search, track on/off, scale | locus from #1/#6/#7 click | locus pan/zoom | igv.js or jbrowse-react |
| 9 | Spatial scatter + simple image overlay | spatial transcriptomics, IF imaging (small images) | image opacity, colour-by, ROI lasso | gene set, cell-type filter | ROI cells (sample IDs) | plotly.js image annotation, or deck.gl BitmapLayer + ScatterplotLayer |
| 10 | Pathway / network (STRING/KEGG) | enrichment, sc, multi-omic | layout algo, edge-confidence slider, colour-by logFC, expand neighbours | gene-set from #1/#3 | selected node → drill-back | cytoscape.js |

**Note on #9:** kept deliberately lightweight. Single image (PNG/JPG) as background, scatter overlay, lasso ROI. No pyramid / no zarr / no Vitessce. If imaging requirements grow later, swap the renderer for deck.gl + viv without touching the coordination contract.

---

## 3. Why a new component family (not just more `figure` configs)

Audit of `depictio/viewer` (see Appendix A) found five concrete blockers that prevent expressing volcano-class viz with the existing atomic types (`figure`, `table`, `interactive`, `card`):

1. **Flat `stored_metadata` array** — components are siblings; no way to express "these controls belong to this chart".
2. **Filter state is one global pool** (`App.tsx:66`) — every interactive's value flows to every other component. An intra-viz threshold slider would pollute the global filter list.
3. **Single selection mode per component** — schema has one `selection_*` field; volcano needs threshold AND lasso simultaneously, spatial needs ROI AND brush.
4. **Type-specific builder UI** — every new component_type needs a bespoke editor stepper today.
5. **Per-renderer resize/sidebar wiring** — the `lockedWidthRef` pattern in `DashboardGrid.tsx:128` is duplicated; a viz family deserves a shared frame.

A new component family solves 1–5 in one place; bolting onto `figure` would re-create them per viz.

---

## 4. Architecture (three layers)

### Layer A — Component type modelling

**Recommendation: hybrid.** One React-side `component_type: "advanced_viz"` (single dispatch entry, single renderer registry, single builder stepper), with a **Pydantic discriminated union by `viz_kind`** on the backend so each kind has a strongly-typed config schema.

#### Pros / cons of the three options

| Approach | Schema surface | Type safety | Builder UI cost | Cost to add viz #11 | AI/LLM authoring | Plugin path |
|---|---|---|---|---|---|---|
| **A. Single `advanced_viz` + viz_kind enum** | smallest | weakest (config is opaque dict) | one stepper, branches on viz_kind | one new enum value + renderer + opaque schema | easiest — one top-level concept, smaller system prompt | trivial — add a renderer module |
| **B. One `component_type` per viz** | largest | strongest (per-viz Pydantic) | one stepper per viz | new component_type, new Pydantic, new renderer, new builder | hardest — N concepts to learn, large system prompt or RAG burden | requires kernel changes per plugin |
| **C. Hybrid (single dispatch, discriminated union config)** | small | strong (per-kind Pydantic via `Annotated[Union[...], Field(discriminator='viz_kind')]`) | one stepper that picks subschema per viz_kind | new Pydantic submodel + renderer; no new top-level type | best — one concept the AI must learn, but per-kind JSON Schema gives structured field guidance | trivial — register a Pydantic submodel + a React renderer |

#### Implications for AI / future development

- **AI-driven dashboard composition** (LLM emitting `StoredMetadata`): hybrid (C) wins because the system prompt only needs to teach *one new* component type. Kind-specific structure is supplied by JSON Schema (a tool result, not prompt bloat). Adding a new viz_kind doesn't expand the prompt — only the schema registry the agent introspects on demand.
- **AI-driven config validation / repair**: per-kind Pydantic gives precise validation errors the LLM can self-correct from.
- **Per-kind backend logic** (e.g. server-side data shaping for OncoPrint vs Volcano): handled in a registry keyed by `viz_kind`, no `if isinstance(...)` ladders.
- **Plugin-readiness**: the contract becomes "drop a Pydantic submodel + a React renderer into a registry" — externalising to a real plugin system later is mechanical.
- **Editor UX**: the builder shows a viz_kind picker first, then renders a per-kind form auto-generated from the JSON Schema (Mantine has form-from-schema patterns). Power users get one consistent place to learn.
- **Risk**: discriminated unions cross the FastAPI ↔ React boundary as JSON; need to keep TypeScript types in sync (we already generate types from Pydantic — extend the script).

### Layer B — Coordination model (fresh, not a port of the Dash 6-store design)

The previous Dash design had six bespoke stores (`FILTERED_FEATURE_IDS`, `SELECTED_FEATURES`, `ACTIVE_FEATURE`, `ACTIVE_CONTRAST`, `HIGHLIGHTED_SAMPLES`, `FILTER_STATE`). Functional, but the names mix entity (feature/sample), state-kind (selected/filtered/highlighted/active), and intent — three orthogonal axes flattened into one namespace.

**Replacement model — three orthogonal concepts × an entity-type taxonomy.** Scoped per dashboard (keyed by `dashboardId`).

```ts
type EntityKind = "feature" | "sample" | "region" | "taxon" | "variant" | "residue" | "pathway";

interface CoordinationState {
  // 1. Selections — persistent sets ("the user has chosen these").
  selections: Record<EntityKind, Set<string>>;

  // 2. Focus — single transient entity ("the user is hovering / drilling into this").
  focus: Partial<Record<EntityKind, string>>;

  // 3. Contexts — orthogonal axes the rest of the dashboard interprets.
  contexts: {
    contrast?: { numerator: string; denominator: string };
    locus?: { chr: string; start: number; end: number };
    colorBy?: { kind: EntityKind; id: string };
  };
}
```

Why this is better than the 6-store port:
- **Composable taxonomy** — adding a new entity kind (e.g. `cell_cluster`) is one line, automatically gives selection + focus channels.
- **No semantic overlap** — `SELECTED_FEATURES` vs `FILTERED_FEATURE_IDS` vs `HIGHLIGHTED_SAMPLES` collapsed into `selections[kind]`.
- **Cross-domain by construction** — same shape works for genes, samples, taxa, variants, regions; volcano and OncoPrint both use the same channel.
- **Testable** — three concepts each have a single well-defined contract, instead of six bespoke ones.

Each viz declares in its config:

```ts
coordination: {
  reads:  { selections?: EntityKind[]; focus?: EntityKind[]; contexts?: ("contrast" | "locus" | "colorBy")[] },
  writes: { selections?: EntityKind[]; focus?: EntityKind[]; contexts?: (...)[] }
}
```

A small Zustand store per dashboard implements this; subscribing components re-render only on the slice they read (Zustand selector + shallow equality).

#### Two-tier filter model (this is the MVP requirement)

- **Tier 1 — global/sidebar filters**: existing `App.tsx:66` `filters: InteractiveFilter[]` array. Untouched. Drives backend data fetches.
- **Tier 2 — intra-viz local controls**: React local state inside the advanced viz (sliders, dropdowns, search). Never enters the global array. May trigger backend re-fetches via the viz's own data hook, or operate purely client-side on already-fetched data (preferred — keeps interaction fast).
- **Bridge**: each viz exposes an opt-in "publish selection to dashboard" toggle that promotes a current selection (e.g. brushed cells) to a new sidebar filter. This is the only path from Tier 2 to Tier 1, and it's user-initiated.

This means MVP has builtin controls (Tier 2) AND responds to outside filters (Tier 1) without any churn through the global filter array.

### Layer C — Shared frame component

A `<AdvancedVizFrame>` wrapper handles:

- chrome (title, fullscreen, download, reset) — same visual language as `wrapWithChrome()` in `ComponentRenderer.tsx`,
- resize sync with the sidebar toggle (port the `lockedWidthRef` trick from `DashboardGrid.tsx:128`),
- error boundary + loading skeleton,
- the standard top-bar control row (search, top-N, lasso toggle, "publish selection" toggle).

Each viz becomes essentially `(props: { data, controls, coordination, theme }) => ReactElement` — small, testable, swappable.

---

## 5. MVP — two viz, one PR

Build **#1 Volcano + #2 Embedding** together. Reasons:

- They prove all three layers (new type, coordination store, frame).
- They demonstrate the full cross-talk loop:
  - Selecting a gene in Volcano → publishes to `selections.feature` → Embedding recolours by that gene (via `contexts.colorBy`).
  - Lasso in Embedding → publishes to `selections.sample` → toggle "publish to dashboard" promotes it to a global sidebar filter → Volcano re-fetches with that sample subset.
- Both render with plotly.js — no new heavy dependencies for v1.
- Both are universally relevant (all four omics domains use them).

Once stable, viz #3–#10 in the catalogue are mechanical adds: each is a new Pydantic submodel + a new React renderer file. Genome browser (#8) is the only one needing a new top-level dependency (igv.js).

---

## 6. Open architectural questions (resolve before coding)

1. **Per-kind data fetch endpoints** vs one generic endpoint? OncoPrint needs a cohort×gene matrix; volcano needs a feature table; spatial needs (image_url, coords). Probably: one generic `POST /advanced_viz/{viz_kind}/data` that dispatches to per-kind handlers in the API.
2. **Where lives the JSON Schema for builder forms** — generated from Pydantic at build time and shipped to the frontend, or fetched at runtime from `/advanced_viz/{viz_kind}/schema`?
3. **TypeScript type generation** — extend the existing Pydantic→TS pipeline (if any) to emit the discriminated union, or hand-write TS mirrors for v1?
4. **Coordination store persistence** — does selection state survive a dashboard reload? (Recommendation: no for v1; selections are session-only. Easy to add later.)
5. **Editor UX for coordination** — should the builder expose `coordination.reads`/`writes` as a UI, or are these fixed per viz_kind (recommended for v1)?

---

## Appendix A — React viewer audit (current state)

- **Stack**: Vite + React 18 + TypeScript 5.3, Mantine 7.14, Plotly.js (`react-plotly.js`), AG Grid Community, Cytoscape, Zustand 5.0 (sparing use), `react-grid-layout`. Built as SPA mounted at `/dashboard-beta/`.
- **Component dispatch**: hard-coded switch in `packages/depictio-react-core/src/components/ComponentRenderer.tsx:63–272` over `component_type` (card, figure, table, image, map, jbrowse, multiqc, interactive). Wrapped by `wrapWithChrome()` for consistent header.
- **Data flow**: per-renderer fetch via `useEffect` (e.g. `FigureRenderer.tsx:72–97` calls `renderFigure(...)`). Cards bulk-fetched in one POST. WebSocket triggers refresh via `refreshTick` counter.
- **Filter state**: `App.tsx:66` holds `filters: InteractiveFilter[]` threaded down to all children. `mergeFiltersBySource()` (`selection.ts:82–98`) dedupes. No event bus — wiring is implicit through parent re-render.
- **Schema**: `StoredMetadata` (`api.ts:195–233`) — flat array, has `parent_index` field unused in practice. Mirrored by Pydantic in `depictio/models/components/`.
- **Editor**: `EditorApp.tsx`, separate Zustand `useBuilderStore.ts` for in-flight config, custom stepper per `component_type`.

## Appendix B — Lessons carried over from `claude/python-bioinformatics-setup-oVDOo`

- Coordination contract is the most valuable artefact, not the Plotly code. The 6-store schema worked but mixed three orthogonal concepts (entity, state-kind, intent); the new model in §4 Layer B factors them apart.
- User feedback "I don't see connection between modules" maps to: cross-talk needs to be **visible** (status badges showing active selection / contrast in the frame) not just functional.
- The Dash MVP pair (Progressive Filter + Feature Explorer) translates to React MVP **Volcano + Embedding** — same lesson (cross-talk demo) with viz that are higher-impact and lower domain-specificity.

## Appendix C — Reference implementations surveyed

- nf-core: rnaseq, sarek, scrnaseq, chipseq/atacseq, ampliseq, mag, taxprofiler, differentialabundance, quantms.
- Shiny / Dash: iSEE, Glimma, Degust, ShinyGO, cBioPortal (OncoPrint, KM, MutationMapper), UCSC Cell Browser, Plotly Dash Bio (Clustergram, VolcanoPlot, ManhattanPlot, NeedlePlot, OncoPrint).
- Imaging / spatial: Vitessce, Squidpy + napari, TissUUmaps 3, OMERO.iviewer (deferred — out of scope for lightweight v1).
- Genome browsers: igv.js, JBrowse 2 React.
