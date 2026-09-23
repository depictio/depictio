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

## 2. Catalogue (10 viz, 4 domains) and per-viz input schemas

Each advanced viz declares the **input shape** its data binding must satisfy. A binding maps DC columns to viz roles via a `ColumnMapping` (concept carried over from the previous Dash design). Validation runs at **two points**: (1) editor-time when the user wires a viz to a DC (warn + block save if required roles unmappable), and (2) render-time as a defensive check (return a structured error the renderer surfaces, not a stack trace).

Schemas are deliberately small and additive — extra columns are always allowed and surface in tooltips / hover.

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

**Note on #8:** the igv.js / jbrowse-react framing above predates the `advanced_viz` family. GenomeSpy, a declarative, coordinate-bound track grammar, was evaluated against it in `docs/design/genomespy-eval.md` (#1083) and landed as the `genome_view` kind; that document also lists which of the hand-built genome renderers it could replace.

**Note on #9:** kept deliberately lightweight. Single image (PNG/JPG) as background, scatter overlay, lasso ROI. No pyramid / no zarr / no Vitessce. If imaging requirements grow later, swap the renderer for deck.gl + viv without touching the coordination contract.

### 2.1 Input schema per viz (required vs optional roles)

`req` = required role; `opt` = optional. `*` = repeating (one column per axis/dim/track).

| # | Viz | Required roles | Optional roles | DC shape (long/wide/file-manifest) | Notes |
|---|---|---|---|---|---|
| 1 | Volcano | `feature_id: str`, `effect_size: float`, `significance: float` (raw p or padj) | `label: str`, `category: str`, `mean_expr: float` | long, one row per feature | Toggle `-log10` applied client-side; if both p and padj present user picks. |
| 2 | Embedding | `sample_id: str`, `dim_1: float`, `dim_2: float` | `dim_3*`, `meta.*: any`, `cluster_id: str` | long, one row per sample/cell | If DC has no `dim_*`: must bind to a `compute` step (§8). |
| 3 | Clustergram | `feature_id: str`, `sample_id: str`, `value: float` (long) **or** wide matrix with first col = feature_id | `feature_meta.*`, `sample_meta.*` | long preferred; wide accepted with auto-detection | Heavy clustering computed server-side (§9). |
| 4 | Stacked taxonomy bar | `sample_id: str`, `taxon_id: str`, `rank: str`, `abundance: float` | `parent_taxon_id: str`, `lineage: str` | long, one row per (sample, taxon) | `rank` enum: phylum/class/order/family/genus/species. |
| 5 | OncoPrint | `sample_id: str`, `gene: str`, `alteration_type: str` | `clinical.*: any` (per-sample) | long, one row per (sample, gene, alteration) | Clinical sidebar tracks via secondary DC join. |
| 6 | Lollipop / needle | `gene: str`, `position: int`, `mutation_type: str` | `count: int`, `domain.start/end/name`, `cohort: str` | long, one row per mutation event | Domain track is a separate DC (gene → domains). |
| 7 | Manhattan / GWAS | `chr: str`, `pos: int`, `pvalue: float` | `snp_id: str`, `trait: str`, `effect: float` | long, one row per locus | `chr` ordering enforced (1..22, X, Y, MT). |
| 8 | Genome browser | DC = **manifest** of tracks: `track_id`, `kind` (BAM/VCF/BigWig/BED), `uri`, `index_uri`, optional `genome` | `display: dict` (track height, colour) | manifest (one row per track) | `uri` resolved server-side to signed S3 URL before frontend fetch. |
| 9 | Spatial scatter + image | `cell_id: str`, `x: float`, `y: float` + DC-level `image_uri: str` (in DC config, not rows) | `value: float`, `cluster_id: str`, `image_scale: float` | long, one row per cell + image referenced from DC config | No pyramid; image must fit `< ~20 MB` for v1. |
| 10 | Pathway / network | DC = **graph**: edge table `source: str`, `target: str` + node table `id: str`, `label: str` | `weight: float`, `node_attr.*`, `edge_attr.*` | two-table DC (nodes + edges) — needs new DC kind | First viz that requires extending the DC kind list. |

### 2.2 The `ColumnMapping` and `BindingSpec` types

Per-viz Pydantic submodel pairs a **role** with a **DC column path**. Lives in `depictio/models/components/advanced_viz/<viz_kind>.py`:

```python
class VolcanoColumnMapping(BaseModel):
    feature_id: str               # column name in the DC
    effect_size: str
    significance: str
    label: str | None = None
    category: str | None = None

class VolcanoBindingSpec(BaseModel):
    wf_id: str
    dc_id: str
    columns: VolcanoColumnMapping
    significance_kind: Literal["pvalue", "padj"] = "padj"
```

The editor reads the DC schema, presents the user with column dropdowns per role, and writes a `BindingSpec` into the component config. At render time, the API uses the binding to project only the required columns out of the Delta table — keeps payloads small.

### 2.3 What this implies for DC authors / pipeline integrators

- Existing recipes (`depictio/projects/.../recipes/*.py`, see `TransformConfig`) gain a small **schema-tag convention**: a recipe can declare which advanced viz kinds its output is consumable by, e.g. `# advanced_viz: volcano, embedding`.
- Pipeline templates (the YAML side) can pre-fill `BindingSpec` so users see correctly-wired advanced viz on first dashboard load. If columns don't match the schema, the editor surfaces the mismatch with a "remap" UI rather than failing silently.

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

## 4.5 New class: `compute` (clustering & dimensionality reduction)

PCA / UMAP / t-SNE are not visualisations — they are **transformations** that produce a derived DC the Embedding viz (#2) then renders. Today Depictio has no first-class concept of "run an algorithm and produce a derived DC with parameter-tuneable UI"; it has the lower-level `TransformConfig` recipe system (see `depictio/models/models/transforms.py`) and the `DataCollectionSource.TRANSFORMED` enum (see `depictio/models/models/data_collections.py:18-22`). The new `compute` class layers a typed, UI-driven, parameter-tunable façade over those.

### 4.5.1 Why a separate class (not just "another viz_kind")

- A compute step has **no rendering** — it produces data, not pixels. Letting it pretend to be a viz blurs the chart-vs-pipeline boundary and breaks the discriminated-union semantics for `advanced_viz`.
- It is the **only kind of node that legitimately mutates the dashboard's data graph** at view time. That deserves explicit modelling so caching, invalidation, and re-runs are first-class concerns.
- Its lifecycle is async (Celery → poll/WebSocket → render) where a viz is sync (props in → element out). Conflating them complicates both renderers.

### 4.5.2 Class shape

New top-level `component_type: "compute"`, hybrid pattern again — single React dispatch entry, Pydantic discriminated union by `compute_kind`:

```python
class ComputeKind(str, Enum):
    PCA  = "pca"
    UMAP = "umap"
    TSNE = "tsne"
    PCOA = "pcoa"           # microbiome / distance-based
    HCLUST = "hclust"       # hierarchical clustering — also feeds Clustergram (#3)
    KMEANS = "kmeans"
    LEIDEN = "leiden"       # graph-based, sc-style
    LOUVAIN = "louvain"

class ComputeJobSpec(BaseModel):
    input: BindingSpec                 # which DC + which columns are the input matrix
    compute_kind: ComputeKind
    params: ComputePCAParams | ComputeUMAPParams | ...   # discriminated by kind
    feature_subset: list[str] | None   # optional: restrict to these features (cross-talk hook)
    sample_subset: list[str] | None    # optional: from sidebar / coordination
    output_dc_tag: str                 # human-readable tag for the produced derived DC
```

Per-kind param submodels (each tight, validated):

```python
class ComputePCAParams(BaseModel):
    n_components: int = 10
    scale: bool = True
    svd_solver: Literal["auto", "arpack", "randomized"] = "auto"

class ComputeUMAPParams(BaseModel):
    n_neighbors: int = 15
    min_dist: float = 0.1
    n_components: int = 2
    metric: Literal["euclidean", "cosine", "correlation"] = "euclidean"
    random_state: int = 42

class ComputeTSNEParams(BaseModel):
    perplexity: float = 30.0
    n_iter: int = 1000
    learning_rate: float | Literal["auto"] = "auto"
    metric: Literal["euclidean", "cosine"] = "euclidean"
    random_state: int = 42

class ComputeLeidenParams(BaseModel):
    resolution: float = 1.0
    n_neighbors: int = 15      # for the kNN graph
    random_state: int = 42
```

### 4.5.3 Output: a derived `TRANSFORMED` Data Collection

The result is materialised as a regular DC with `source = TRANSFORMED`, slotting into Depictio's existing model. The output schema depends on `compute_kind`:

| Kind | Output DC columns |
|---|---|
| PCA / PCoA | `sample_id`, `dim_1..dim_N`, plus `variance_explained` table as DC sidecar |
| UMAP / t-SNE | `sample_id`, `dim_1`, `dim_2` (or `dim_1..3`) |
| hclust | `sample_id`, `linkage_order: int`, `cluster_id_at_k_*: str`; sidecar dendrogram (Newick or linkage matrix) |
| kmeans / leiden / louvain | `sample_id`, `cluster_id: str` |

Embedding viz (#2) and Clustergram (#3) bind to these derived DCs the same way they bind to any other DC — no special case in the renderer.

### 4.5.4 Caching & invalidation

Cache key = `(input_dc_id, input_dc_version, compute_kind, hash(params), hash(feature_subset), hash(sample_subset))`. Stored in MongoDB (`compute_jobs` collection) with status, result_dc_id, error, timestamps.

- Cache hit → return existing result_dc_id immediately, no Celery dispatch.
- Cache miss → enqueue Celery task, return `job_id` and status `PENDING`. Frontend subscribes via existing WebSocket (already used for `useDataCollectionUpdates()` per the React viewer audit).
- Input DC invalidation (re-scan, new version) → existing compute jobs stay valid for the old version; new lookups re-compute. We never auto-delete to avoid losing work; provide a "clear cached results" admin action.

### 4.5.5 Where in the dashboard does a `compute` node live?

Two options:

- **A. Visible card on the canvas** — appears as a small panel showing kind, params, status, and a "Re-run" button. Pro: explicit and discoverable. Con: clutter for users who just want results.
- **B. Hidden / sidebar-only** — added in the editor via a "Compute" tab, never rendered in the canvas; viz panels reference its output by id. Pro: clean canvas. Con: harder to debug ("why is my embedding empty?").

**Recommendation: A for v1.** The status/Re-run affordance is high value while the system is new. Once stable, add a "collapse to header chip" toggle.

### 4.5.6 Cross-talk into compute

A compute node *reads* coordination state (so e.g. UMAP can be re-run on a sample subset chosen via lasso in another viz), but it should **never auto-rerun on every selection change** — recompute is expensive. Two policies:

- **Manual re-run** (default): selection changes set the node "dirty"; user clicks Re-run.
- **Debounced auto-run**: opt-in per node, with a debounce (e.g. 5 s) and a configurable upper bound on dataset size to avoid runaway costs.

---

## 4.6 Heavy compute → Celery (no inline blocking work)

Depictio already has Celery wired (`depictio/dash/celery_worker.py`, `depictio/dash/celery_app.py`, `depictio/api/v1/celery_tasks.py`). The advanced viz family extends this with two new task families and a uniform offload contract.

### 4.6.1 What goes on Celery

Anything where p99 latency could exceed ~500ms or memory could spike beyond ~250 MB:

| Workload | Why heavy | Task |
|---|---|---|
| `compute` node execution (PCA/UMAP/t-SNE/clustering) | matrix ops, neighbor graphs, gradient descent | `depictio.compute.run` |
| Clustergram (#3) clustering of large matrices | O(n²) distance + linkage | `depictio.advanced_viz.cluster_matrix` |
| OncoPrint (#5) cohort×gene matrix assembly | wide pivot over many samples | `depictio.advanced_viz.oncoprint_matrix` |
| Pathway (#10) network expansion via STRING/KEGG | external API + graph traversal | `depictio.advanced_viz.pathway_expand` |
| Volcano label-top-N when N is large (>1000) | layout / collision avoidance | client-side; only server-side if requested as PNG/PDF |
| Embedding (#2) initial render with >100k points | server-side downsampling / tiling | `depictio.advanced_viz.embedding_tile` |
| `group_compare` two-group differential test | per-feature test over a wide observation x feature matrix, plus BH correction | `depictio.advanced_viz.compute_group_compare` |

Light operations (threshold filtering on already-loaded data, axis flips, hover formatting) stay in the browser. The principle: **pre-compute on the server, react in the browser.**

### 4.6.2 Task contract (mirrors existing `celery_tasks.py` style)

```python
@celery_app.task(name="depictio.compute.run", soft_time_limit=600, time_limit=900)
def compute_run(payload: dict) -> dict:
    """
    Input:  {"job_spec": <ComputeJobSpec serialized>, "user_id": "...", "dashboard_id": "..."}
    Output: {"status": "ok"|"error",
             "result_dc_id": "...",        # on ok
             "result_summary": {...},      # variance explained, cluster sizes, etc.
             "error": {"kind": "...", "message": "..."}}  # on error
    Side effects: writes derived DC to Delta + registers in MongoDB.
    """
```

Tasks remain JSON-in / JSON-out (matches existing convention noted in `celery_tasks.py:13`). No raw DataFrames over the wire.

### 4.6.3 Offload helper and frontend lifecycle

- API endpoint `POST /advanced_viz/compute` accepts a `ComputeJobSpec`, looks up cache, returns either `{status: "cached", result_dc_id}` or `{status: "pending", job_id}`.
- Frontend tracks pending jobs in a Zustand slice, subscribes to existing WebSocket channel, swaps the panel skeleton for the rendered viz when `job.status` flips to ok.
- Failed jobs surface in `<AdvancedVizFrame>`'s error boundary with retry + "view logs" affordances.
- Worker queues split: `default` (existing), `compute` (new — long-running, low concurrency, can be scaled independently). Helm chart already enumerates worker deployments per `helm-charts/depictio/templates/deployments.yaml`; we add one entry.

### 4.6.4 Resource limits

- `soft_time_limit` per kind (PCA: 60s, UMAP: 300s, leiden on >50k samples: 600s).
- Per-user concurrency cap (configurable, default 2 simultaneous compute jobs).
- Hard memory cap via worker container limits.
- Result size cap: derived DC must be <50 MB Parquet; jobs that would exceed this are rejected with a clear error pointing the user at sample/feature subsetting.

---

## 5. MVP — two viz + one compute kind, one PR

Build **#1 Volcano + #2 Embedding + `compute_kind = umap`** together. Reasons:

- Proves all four layers (new `advanced_viz` type, new `compute` type, coordination store, frame).
- Proves the **full pipeline**: raw matrix DC → UMAP compute (Celery) → derived DC → Embedding viz binds to it → cross-talk with Volcano.
- Demonstrates cross-talk:
  - Volcano selects a gene → `selections.feature` → Embedding recolours by that gene (via `contexts.colorBy`).
  - Embedding lasso → `selections.sample` → toggle "publish to dashboard" promotes to a sidebar filter → Volcano re-fetches with that subset.
  - Optional: Embedding lasso also marks the UMAP compute node "dirty" (sample subset changed); user clicks Re-run to recompute on the subset.
- Volcano + Embedding render with plotly.js; UMAP runs in Celery via the existing `umap-learn` package (single new Python dep on the worker side).
- Schema-validated bindings exercised end-to-end: Volcano needs `feature_id/effect_size/significance`; Embedding either reads `dim_1/dim_2` directly OR (the demo) binds to the UMAP compute output.

Once this MVP is stable, the rest of the catalogue is incremental: each new viz is a Pydantic submodel + React renderer file; each new compute kind is a Pydantic submodel + a Celery task body. Genome browser (#8) and Pathway/network (#10) are the only items that bring new top-level dependencies (igv.js, cytoscape.js).

---

## 6. Open architectural questions (resolve before coding)

1. **Per-kind data fetch endpoints** vs one generic endpoint? OncoPrint needs a cohort×gene matrix; volcano needs a feature table; spatial needs (image_url, coords). Probably: one generic `POST /advanced_viz/{viz_kind}/data` that dispatches to per-kind handlers in the API.
2. **Where lives the JSON Schema for builder forms** — generated from Pydantic at build time and shipped to the frontend, or fetched at runtime from `/advanced_viz/{viz_kind}/schema`?
3. **TypeScript type generation** — extend the existing Pydantic→TS pipeline (if any) to emit the discriminated union, or hand-write TS mirrors for v1?
4. **Coordination store persistence** — does selection state survive a dashboard reload? (Recommendation: no for v1; selections are session-only. Easy to add later.)
5. **Editor UX for coordination** — should the builder expose `coordination.reads`/`writes` as a UI, or are these fixed per viz_kind (recommended for v1)?
6. **`compute` node placement on the canvas** — visible card vs hidden/sidebar-only. Recommendation A above; confirm.
7. **Compute caching scope** — per-user, per-project, or global? Sharing across users speeds collaboration but raises permission questions; recommend per-project for v1.
8. **Recipe vs first-class compute** — should clustering/DR kinds be implemented as recipes under the existing `TransformConfig` system (pro: leverages existing scan/materialise pipeline) or as standalone Celery tasks bypassing recipes (pro: tighter typing, no `.py` recipe file per kind)? Recommendation: **standalone Celery tasks** for the eight builtin kinds, while leaving `TransformConfig` available for user-authored custom transforms.
9. **Worker queue topology** — separate `compute` queue from default? Yes (long jobs shouldn't block previews). Helm chart needs an additional worker deployment.
10. **DC schema-validation surface** — surface mismatches in editor only, or also at runtime? Recommend both, but editor-time should block save while runtime should display a non-fatal banner.

---

## 7. Kinds added with the nf-core template lots (2026-09)

The kinds below were added in the second template lot and its remediation wave. Each one
went through the seven registry touchpoints (`types.py`, `CANONICAL_SCHEMAS` / `ROLE_NAMES` /
`_OPTIONAL_ROLES` / `KIND_METADATA` in `schemas.py`, a `<Kind>Config` in `configs.py`,
`KIND_SAMPLING_POLICY`), the TypeScript union, `AdvancedVizDispatch` and `splitPanels`, plus a
showcase tab and a pytest / vitest pair. The `contact_map`, `knee_plot` and `damage_profile`
kinds of the first lot 2 cut follow the same pattern.

**`genome_view`** (renamed from the spike's `genomespy_track`). A GenomeSpy-backed track:
required roles `chr`, `pos`, `score`, optional `end` (interval), `feature` (label and selection
id), `sample` (one lane per value, `facet_by_sample`, capped by `max_facets`) and `category`
(colour). Marks are `point`, `rect` (needs `end_col`, silently falls back to `point` without it)
and `bar` (score as height from zero; GenomeSpy core has no line or area mark, so there is no
smooth coverage curve). An optional gene lane reads a bundled hg38 or mm10 asset
(`depictio/viewer/public/assets/genomes/*.genes.json`, protein-coding GENCODE basic, built by
`dev/advanced_viz_kinds/build_genome_gene_assets.py`; `@genome-spy/core` ships chromosome sizes
only). A brush emits two `InteractiveFilter`s with source `genome_selection`, a `MultiSelect` on
`chr_col` and a `RangeSlider` on `pos_col`, which `add_filter` already understands, so any tile on
a collection carrying the same columns narrows with it; `follow_region_filter: true` makes a
tile zoom to an incoming region instead. Measured on atacseq's `macs2_broad_peaks` (224,137
rows): one WebGL context against Plotly scattergl's two, gesture frames at the vsync floor for
both, so the honest reading is "no worse" (`docs/design/genomespy-eval.md`).

**`group_compare`.** Compute on a selection. The first kind whose input is not a column binding
but a pair of row groups picked in the dashboard: two saved selection groups (a lasso kept
through "select & compare") or two values of a label column. Both collapse to one
`{label, column, values}` selector before they leave the browser. The endpoint pair
`POST /advanced_viz/compute_group_compare` + `GET /advanced_viz/compute_group_compare/{job_id}`
follows the dispatch / poll / cache contract of `compute_upset`: the cache key hashes the whole
payload, so re-running an identical comparison is free. The worker loads the collection through
`load_deltatable_lite` with the dashboard's `filter_metadata`, infers the features from the
schema as `complex_heatmap` infers its matrix (capped by variance at `max_features`), runs a
Wilcoxon rank-sum (default) or Welch t-test, Benjamini-Hochberg across the tested features and a
log2 fold change of the raw means with a pseudocount. The renderer draws a volcano and the ranked
marker table; thresholds and the label budget are client-side, so moving them never costs a job.
Known artefact: any numeric column is a feature, so embedding axes stored beside the genes get
tested too; a feature-exclusion list on the config is the follow-up.

**`transcript_structure`.** The isoforms of one gene as lanes on a base-pair axis: exon blocks,
coding blocks drawn taller so the UTRs stay visible, introns as thin lines carrying strand
chevrons. One row per exon or CDS block (`transcript_id`, `gene_id`, `chrom`, `start`, `end`,
`feature`, `strand`, optionally `sample`, `gene_name`, `transcript_class`, `expression`), which
is what `gtf/transcripts` makes of any GTF or GFF3 a run publishes (StringTie, bambu
`extended_annotations.gtf`, gffcompare). Lanes are ordered by expression and cut to
`max_transcripts`; the novelty class colours them. One gene at a time is deliberate: a track
showing every locus is a genome browser, and that is `genome_view`'s job.

**`cnv_profile`.** One collection carries both halves of a somatic copy-number call, told apart
by the optional `segment` role: a bin row is one window of the ratio track and draws as a point,
a segment row is the caller's own call and draws as a thick horizontal stroke over it, coloured
gain, neutral or loss by `gain_threshold` / `loss_threshold`. The x axis is the genome with the
same chromosome offsets `manhattan` uses, so the chromosome Select zooms onto one contig. When
`baf_col` is bound, a second panel plots the B-allele frequency against a dotted 0.5 rule: that
panel is the reason the kind exists, because copy-neutral loss of heterozygosity never moves the
log2 track. Bins go out as `scattergl` and fall back to a downsampled SVG trace when the WebGL
budget is spent; above `max_bins` they are averaged into windows, never sampled, and segments are
never thinned. Producers: `cnvkit` (`.cnr` bins + `.cns` segments), `ascat` (allele counts to
log2 ratio, copy number and expected BAF) and `controlfreec` (segments recovered by run-length
encoding `MedianRatio`), all on nf-core/sarek's somatic `variant_calling/` layout and gated
behind a somatic run.

**`genome_chord`.** The one kind with no library behind it: Plotly has no chord trace and d3 is
not a dependency, so `GenomeChordRenderer` draws plain SVG and keeps every number in
`genome_chord/chordLayout.ts`, unit-tested without a DOM. Chromosomes are arcs proportional to
length (hg38 / hg19 / mm10 sizes, or derived from the data), laid clockwise from noon; the chord
joining two loci is a quadratic Bezier whose control point moves from the rim to the centre as
the loci move apart, so an intra-chromosomal deletion stays a short arc rather than a spike
through the picture. Width is log10 of the weight. The server never samples it
(`KIND_SAMPLING_POLICY: "none"`: a random subset of breakpoint pairs would drop exactly the rare
translocations the picture exists to show); the renderer sorts by weight and draws the heaviest
`max_links`, reporting the remainder. Clicking a chord emits a `scatter_selection` filter on
`label_col`. Producer: `arriba/fusion_links`.

**`contact_map`, `display: triangle`.** Rotates the matrix 45 degrees so genomic position is on
x alone and a `genome_view` track stacked above shares the axis; `max_separation_bins` caps the
apex. The pure helper `contactMapTriangle.ts` does the rotation and fills the odd-parity lattice
gaps from horizontal neighbours.

## 8. When a new kind is justified

Thirty-nine kinds is enough to have learned what a kind costs. Each one is seven registry
entries, a renderer, a showcase tab, a pair of alignment tests and a line in every snapshot
that enumerates kinds, and none of that is paid back by a kind that draws the same marks as
its neighbour with different column names. This section is the rule the next one is measured
against.

### The rule

A new kind needs **a new set of marks** or **a new interaction shape**. Anything else is a
preset.

- **New set of marks.** The picture is built from primitives the existing kinds do not draw.
  `genome_chord` earns it: Plotly has no chord trace, so the renderer lays out arcs and Bezier
  ribbons itself. `parallel_coordinates` earns it: one polyline per row across N axes is not a
  scatter with more columns.
- **New interaction shape.** What the reader does to the picture, and what the picture does
  back, is different. `genome_view` earns it against `manhattan`: the same chr / pos / score
  roles, but a locus axis that zooms and a brush that becomes a dashboard filter.
  `record_card` earns it: it consumes a selection instead of emitting one, which no other kind
  does.
- **Everything else is a preset.** A column set, a palette, an axis default, a sort order, a
  threshold: those go in the kind's `config`, and the way an author gets them without typing
  them is a catalog `Render` entry on the output that produces those columns. A catalog Render
  already carries `kind` plus the role to column mapping, so "the GO enrichment view of a dot
  plot" is one YAML block, not one kind.

### Two worked counter-examples

**`ma`.** An MA plot is a volcano's table with mean log intensity on x instead of effect size,
and the same tier colouring, the same thresholds, the same top-N labelling, the same
selection. Same marks, same interaction, different axis binding: a preset. It is now
`volcano` with `view: ma`, and `VolcanoConfig` carries `avg_log_intensity_col` so the axis has
somewhere to come from. The tile offers all three views behind one control, which is strictly
more than the split gave a reader, because a reader who wants to check the same hits on a QQ
plot no longer needs a second tile bound to the same collection.

**`enrichment`.** A pathway enrichment plot is a dot plot whose y axis is a term, whose x is
the NES, whose dot area is the gene-set size and whose colour is the adjusted p-value. Marks:
dots with a size and a colour channel, exactly `dot_plot`. Interaction: none that `dot_plot`
lacks. It is now `dot_plot` with `view: enrichment`. What made it look like a kind was that
nobody had written this rule down, so "the columns are different" read as "the chart is
different".

The same reasoning retired `qq` into `volcano` and `roc_pr_curve` into `pr_benchmark`.

### The migration path: the alias table

Retiring a kind may not break a dashboard. `_KIND_ALIASES` in
`depictio/models/components/advanced_viz/configs.py` maps each retired kind to the kind that
survived it plus the `view` that reproduces it:

| retired kind | resolves to | view |
| --- | --- | --- |
| `ma` | `volcano` | `ma` |
| `qq` | `volcano` | `qq` |
| `enrichment` | `dot_plot` | `enrichment` |
| `roc_pr_curve` | `pr_benchmark` | `roc` |

It runs as a `BeforeValidator` on the `VizConfig` union, so it applies everywhere a config is
validated: a dashboard read out of Mongo, a shipped YAML, a `use:` expansion, the CLI
validator, the save route. A stored document is rewritten at read time and written back only
if the user saves. Three rules make that safe:

1. **The survivor takes the retired config's field names verbatim.** `VolcanoConfig` gained
   `avg_log_intensity_col`, `DotPlotConfig` gained `term_col`, `PrBenchmarkConfig` gained
   `fpr_col`. The translation is the identity, which is the only kind of translation that
   cannot silently drop a binding. A null the survivor does not accept is dropped rather than
   raising, because the retired config had the field optional and the survivor does not.
2. **The old literal stays in `AdvancedVizKind`,** flagged `legacy: True` in `KIND_METADATA`.
   Every snapshot that enumerates kinds (`GET /advanced_viz/kinds`, `catalog.schema.json`,
   Tool Studio's `kinds.json`) keeps validating, and pickers hide the flagged entries. A
   consumer that predates the flag reads an absent flag as "not legacy", which is the old
   behaviour.
3. **The React `RENDERERS` map keeps the old key.** `stored_metadata` reaches the client
   without passing through the Pydantic models, so a dashboard saved before the merge still
   arrives carrying `viz_kind: ma`, and the old key has to dispatch to something. No renderer
   file is deleted in the PR that retires a kind.

### `INCUBATING`

`test_every_kind_is_reachable` asserts that every kind is bound by a catalog output's
`renders_as` or by a shipped dashboard YAML. A kind nobody can reach is a kind whose only
proof of life was the author's local stack, and we shipped several of those before the test
existed.

`INCUBATING` in `schemas.py` is the audit list of the exceptions, and it is a promise rather
than a parking space: each entry carries the reason it is unbound next to it. Two reasons are
legitimate. The first is a kind whose input no pipeline publishes at the pinned revision
(`gsea_running_score`: differentialabundance's pinned prefix writes no `tables/gsea/`), kept
so a re-pin costs nothing. The second is a kind registered ahead of the renderer or the
showcase tab that will bind it, within the same PR. Anything else means the kind should not
have been added.

## 9. Beyond the standard Plotly chart (wave 2 of the nf-core lots, 2026-09)

The wave 1 audit found that the dashboards read as an aggregation of scatter, line and bar
tiles even though 37 kinds existed. The causes were structural rather than a missing kind:
every tile carried the same chrome, genomic tiles shared neither an axis nor a region, several
kinds overlapped, and nothing sized a tile to its content. This section records the
mechanisms that answer each cause. Every default reproduces the behaviour before the wave.

### Content-aware sizing (autofit v2)

Precedence: YAML size, then autofit, then a manual resize. Each component carries
`layout: {fit: auto | fixed}`, stored on `stored_metadata.fit` (never on the grid item, which
react-grid-layout strips on the first drag). Absent means auto for text, card, table and
advanced_viz, fixed for figure and multiqc. Autofit runs in the viewer and the editor over
the auto members only, levels a row of tiles to one height, and never persists a fitted
height. A manual resize in the editor flips the tile to `fixed`; "Reset to auto height" in
its menu undoes it; a dashboard-level `autofit: false` restores today's layout exactly.

Content demand travels on one channel, `publishContentDemand(index, {rows})` in
`autofit.ts`. Figures publish it server side (`content_demand` in the response metadata,
category counts for bar, box and violin). Tables publish header plus rows plus chrome, and
are shrink-only because AG Grid pages and scrolls. Advanced viz tiles pass `contentDemand`
to `AdvancedVizFrame` from the data they already hold (facets, genes, heatmap rows, sets),
and only grow. Per-type clamps: text 1 to 12 rows, card 1 to 4, table 2 to 12, figure 2 to
12, advanced_viz 3 to 16. A tile a type cannot reach (a 2-row card beside a 6-row figure)
keeps its own height rather than growing towards a floor it would never fill.

### Controls placement and the selection echo

A renderer splits its controls in two tiers when it calls `AdvancedVizFrame`:
`primaryControls` (encoding: axes, colour-by, normalise, rank, view switch, run button) and
`controls` (cosmetic). `controls_placement` on the viz config decides where they are drawn:
`popover` (default, both tiers behind the settings icon), `header` (encoding tier as a strip
under the title, cosmetics in the popover) or `rail` (both tiers in a 220 px column beside
the plot, under it below 480 px of tile width). A dashboard-level `advanced_viz_controls`
sets the default for every tile; the tile's own value wins. The chrome pin cycles the three.
Data and Load-All stay in the chrome whatever the placement. `primaryControls` is a fragment
of individual compact controls, never a pre-arranged Stack, so the frame can lay the same
node out as a strip, a rail or a popover list. The inline area counts towards the tile's
content demand.

Under the title the frame echoes what the tile shows: the row count (or `shown / total`
when the server sampled), the region a `genome_selection` filter carried in, and whatever
summary a renderer passes as `echo` (`A (412) vs B (388)` for group_compare, `chr1 · 500 kb`
for contact_map). This is the pattern the FAIR² data portals use: the selection is stated in
plain text next to the figure it narrows.

### Modes, not kinds

Four figures the omics literature expects are the same marks on the same bindings with a
different y, a different mark or an extra panel, so they are opt-in modes rather than new
kinds. `manhattan` `mode: rainfall` puts log10 of the distance to the previous variant on the
same chromosome on y and colours by `rainfall_class_col`, which is how a cancer-genome paper
shows kataegis. `scatter_xy` `density: true` draws a binned 2D histogram instead of one marker
per row; points stay the default, the reader flips the view from the tile, and an author who
wants the automatic switch names the row count in `density_threshold` (0, the default, never
switches); `quadrants: {x, y, labels}` cuts the plane into four named regions (MIMAG
completeness against contamination); `reference_highlight: above | below` dims the side of
the reference line the reader is not looking at and ranks the top-N labels on the other, the
same reading as the Manhattan score threshold. `profile` `derivative: true` forces log-log
and adds a
slope panel underneath, the Hi-C P(s) convention. `damage_profile` `facet_by: length_bin`
draws one lane per read-length bin, and stays on one lane when the collection has no such
column. `violin` joined the figure types the model accepts, as the API already did.

### The genomic axis substrate

Filters are the shared bus for genomic regions (`genome_selection` emits a chromosome
multi-select and a position range). `genomicAxis.ts` maps a kind's declared roles onto those
filters without renaming any config field: `genomicRoles(kind, config)` and
`useFollowedRegion(metadata, config, filters)` give every genomic renderer (coverage_track,
cnv_profile, transcript_structure, gene_arrow_track, manhattan, sashimi, contact_map) the same
region as an x-range clamp, so tiles stacked in one section share one axis. Across
collections a region link (`link_config.resolver: region`, `columns: {chrom, pos}`) rewrites
the emitting DC's column names onto the target's. `genome_view` carries a `LocusInput`
(chr:start-end text plus gene search) as its primary control, emitting the same two filters
as the brush. A template lint forbids binding `coverage_track` and `genome_view` on the same
DC in one tab; the pair becomes one tile with `views: [track, locus]`.

### Hi-C at the resolution the view deserves

`cooler/binned_contact_map` keeps every resolution a run dumped as a partition on a
`resolution` column, deriving 2x, 4x and 8x by summing bins when the run dumped one. A
`compute_contact_map` route serves one region at one resolution, picking the level whose
bins-per-pixel is closest to 0.25 in log space and stepping coarser when the window would
exceed the cell budget. The tile defaults to the triangle reading when a region reaches it,
pins its x-axis to the region so a `genome_view` under it aligns, and re-bins on zoom. A
collection with a single resolution is served as before. TAD triangles and loop arcs (the
gghic `geom_tad` and `geom_loop` layers) are the remaining gap: nf-core/hic publishes
boundaries in a separate collection, so the overlay needs `tad_dc` / `loop_dc` fields on the
config.

### File-backed tracks

`genome_view` `source: file` reads a new `indexed_file` data collection (VCF, BAM, bigWig,
bigBed, GFF3, FASTA, tabix; one object plus its index per sample, stored under
`indexed_files/<dc_id>/<sample>/`, outside the prefix the orphan cleanup garbage-collects)
through GenomeSpy's lazy sources over HTTP range requests. The API hands out presigned URLs
signed against the external MinIO URL, so the bucket must answer CORS preflights from the
viewer origin (`MINIO_API_CORS_ALLOW_ORIGIN` on the dev compose and the helm chart). The
full GenomeSpy bundle loads behind a dynamic import only for file tiles; table tiles keep the
minimal bundle. `@gmod/vcf` returns every INFO value as an array, which the spec builder
unwraps before an ordinal colour scale sees it. Sashimi and cnv_profile file views are not
built yet.

### New kinds justified by section 8

`record_card` is a selection-driven fact panel: a click in any tile fills the card with the
row's fields grouped by section, with URL templates per column. `parallel_coordinates` draws
one polyline per sample across N metric axes, coloured by a group column; an axis brush
emits an ordinary range filter with source `axis_selection`. Both are new interaction shapes,
not presets, which is why they are kinds.

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
