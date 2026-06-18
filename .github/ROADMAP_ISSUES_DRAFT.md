# Roadmap Issues — Draft for Review

> **Status: DRAFT.** Nothing here has been created on GitHub yet. Review/edit titles,
> bodies, labels and epic associations, then the issues + reorganization will be
> applied live (see "How this gets applied" at the bottom).
>
> Decisions baked in:
> - **1.0.0 & 1.0.1 are shipped** → no epics for them; their leftover todos move to 1.1.0.
> - **6 epics** for 1.1.0–1.6.0, each linked to its milestone in the UI.
> - Every todo becomes a **fresh issue** (even where an existing issue overlaps); overlaps
>   are flagged `dup?` in the existing-issue audit so you can merge/close.

---

## B1 — Epic issues (label `epic`)

### `[Epic] 1.1.0 — Perf, templates, ingestion report UI, advanced-viz & skill fixes`
Labels: `epic` · Milestone: `1.1.0`

Performance work plus a batch of template/viz/skill fixes.
- [ ] Performance updates
- [ ] ampliseq / viralrecon template fixes (incl. viralrecon nanopore)
- [ ] Ingestion report UI
- [ ] Advanced visualization fixes
- [ ] Skill fix

### `[Epic] 1.2.0 — Admin UI (logs) + aggregation cards fix`
Labels: `epic` · Milestone: `1.2.0`

- [ ] Admin UI improvements — logs & task monitoring
- [ ] Aggregation cards fix

### `[Epic] 1.3.0 — Modules catalog & project-as-template via UI`
Labels: `epic` · Milestone: `1.3.0`

Modules catalog and the ability to turn a project into a template via the UI.
- [ ] Modules & modules catalog
- [ ] CLI preview / docs preview
- [ ] Modules picker in Depictio
- [ ] Module creation wizard
- [ ] Turn a project into a template via the UI

### `[Epic] 1.4.0 — User journey, funnel & global filters`
Labels: `epic` · Milestone: `1.4.0`

- [ ] User journey & funnel
- [ ] Global filters
- [ ] (TODO) advanced viz & multi-directional filters in funnel

### `[Epic] 1.5.0 — Template-based upload (auto-fill dashboard from a run)`
Labels: `epic` · Milestone: `1.5.0`

Drop a run and fill the dashboard automatically. Open questions to explore:
- [ ] nf-core plugin? Nextflow config? MGnify? S3 storage
- [ ] Auto-scan matching template → recipes → processing

### `[Epic] 1.6.0 — AI-first features`
Labels: `epic` · Milestone: `1.6.0`

- [ ] AI-first features (scope TBD)

---

## B2 — Fresh per-todo issues

Format: **Title** — `labels` — Epic — body.

**→ Epic 1.1.0**
- **E2E tests with Playwright for dashboard creation & editing** — `task` — 1.1.0 — Build Playwright E2E coverage for dashboard creation/edition flows. (Carried over from 1.0.0.)
- **Public on Serve: default dashboards are missing** — `bug` — 1.1.0 — Default dashboards don't appear for public access on Serve. (Carried over from 1.0.1.)
- **Upload fails when selecting files via the browser first** — `bug` — 1.1.0 — Upload doesn't work when clicking in the browser and selecting files first. (Carried over from 1.0.1.)
- **Load testing** — `task` — 1.1.0 — Define and run load tests.
- **Viralrecon: nanopore support** — `enhancement` — 1.1.0 — Add nanopore handling for viralrecon (see note).
- **Extra runs for validation + improved templates** — `task` — 1.1.0 — Add validation runs and improve templates.
- **Fix: Error 500 on advanced viz** — `bug` — 1.1.0 — Advanced viz throws a 500.
- **Fix: Skill for admin login on demo** — `bug` — 1.1.0 — Admin-login skill broken on the demo.
- **Handle complex viz cases (sankey, etc.) — revise** — `enhancement` — 1.1.0 ⚠ (could be 1.4.0) — Revisit handling of complex chart types like sankey.
- **Easily increase/decrease font size** — `enhancement` — 1.1.0 ⚠ — Simple control to bump font size up/down.

**→ Epic 1.2.0**
- **Aggregation card to revisit** — `enhancement` — 1.2.0 — Revisit the aggregation card.
- **Log & task monitoring** — `enhancement` — 1.2.0 — Admin-facing log and task monitoring.
- **Tags per project & per dashboard** — `enhancement` — 1.2.0 ⚠ (could be 1.4.0) — Add tags at project and dashboard level.
- **Metadata table: easy display/access on dashboard landing** — `enhancement` — 1.2.0 ⚠ — For projects with a metadata table, surface it easily when landing on a dashboard.

**→ Epic 1.3.0**
- **Catalog component picker** — `enhancement` — 1.3.0 — Component picker in the catalog.
- **Catalog module assistant: creation / validation / local preview** — `enhancement` — 1.3.0 — Assistant to create, validate and preview modules locally.
- **Turn a project + dashboard(s) into a template via the UI** *(IMPORTANT)* — `enhancement` — 1.3.0 — Convert a project and its dashboards into a reusable template from the UI.

---

## B3 — Existing open issues: rename + categorize (31 issues)

Proposed renamed title, target epic/category, and action. `dup?` = overlaps a B2 fresh issue → decide merge/close at review.

| # | Current title | → Proposed title | Category | Action |
|---|---|---|---|---|
| 734 | Upload template data (all or metadata table) via UI to fill dashboard | Template upload: drop a run (data + metadata) to auto-fill a dashboard | 1.5.0 | assign epic; `dup?` template-upload todo |
| 691 | Global filters | Global cross-component filters | 1.4.0 | assign epic |
| 690 | Chained analysis | Chained / multi-step analysis | 1.4.0 | assign epic |
| 327 | Buttons to Filter/restrict data of interactive components to resulting dataframe options | Buttons to filter/restrict interactive-component data to result set | 1.4.0 | assign epic |
| 278 | Conditionally display all/available values in interactive component | Conditionally show all vs available values in interactive components | 1.4.0 | assign epic (multi-directional filters) |
| 196 | Apply current filters to new components | Fix: apply active filters to newly added components | 1.4.0 | assign epic; keep `bug` |
| 89 | Select and compare groups / on-the-fly annotation | Select & compare groups / on-the-fly annotation | 1.4.0 | assign epic |
| 361 | Custom order (chromosomes for example) on figures | Custom axis ordering on figures (e.g. chromosomes) | 1.4.0 | assign epic |
| 360 | Data sorting for figures (numerical, categorical) | Figure data sorting (numerical / categorical) | 1.4.0 | assign epic |
| 159 | UI to list and manage data uploads/processings | Ingestion / processing report UI | 1.1.0 | assign epic |
| 511 | Test scaling for polars read/write from S3 with/without dashboard rendering | Benchmark Polars S3 read/write scaling | 1.1.0 | assign epic; `dup?` load-testing todo |
| 380 | Test datasets / project config automatic generation | Auto-generate test datasets & project configs | 1.1.0 | assign epic; `dup?` validation-runs todo |
| 329 | Filtered dataframe during component design | Fix: filtered dataframe during component design | 1.1.0 | assign epic; keep `bug` |
| 98 | Table datacollection validation using Pandera | Table data-collection validation with Pandera | 1.1.0 | assign epic |
| 395 | Admin UI with backup + restore buttons | Admin UI: backup & restore buttons | 1.2.0 | assign epic |
| 118 | Add tags / labels to dashboard (landing page) | Tags/labels for dashboards (landing page) | 1.2.0 | assign epic; `dup?` tags todo |
| 79 | LLM & Langchain component | AI: LLM / LangChain-powered component | 1.6.0 | assign epic; relabel `exploratory`→`AI` |
| 101 | Data lifecycle: data collection, table schema, deltatable content, joins | Data lifecycle: collections, schema, deltatable, joins | 1.6.0 / backlog | ⚠ triage |
| 383 | Storage config per Project | Per-project storage configuration | 1.5.0 | assign epic (S3 storage) ⚠ |
| 693 | MongoDB operator K8S | K8s: deploy MongoDB via operator | backlog/infra | keep, label `k8s` |
| 692 | Kubernetes backend/frontend/celery replicas | K8s: fix Celery/frontend replica task tracking | backlog/infra | keep |
| 413 | Build separate containers for frontend and backend | Split frontend & backend into separate containers | backlog/infra | keep |
| 97 | Set up share dashboard functionality using K8S | Share-dashboard functionality on K8s | backlog/infra | keep |
| 563 | Groups implementation | User groups implementation | backlog/auth | keep |
| 562 | Saml implementation | SAML authentication support | backlog/auth | keep |
| 561 | Oauth implementation | OAuth authentication support | backlog/auth | keep |
| 397 | Custom theme / colors | Custom themes & color palettes | backlog/UX | keep |
| 207 | Transparent modal over dashboard creation | Transparent modal over dashboard creation | backlog/UX | keep |
| 308 | Group of components & DC "view" | Component groups & data-collection "view" | backlog/UX | keep |
| 95 | Set up dashboard versioning | Dashboard versioning (save/restore version) | backlog | keep |
| 733 | Make ty pass on dash codebase | Type-checking: make `ty` pass on the Dash codebase | backlog/tech-debt | keep |

**Distribution:** 1.1.0 ×5 · 1.2.0 ×2 · 1.4.0 ×8 · 1.5.0 ×2 · 1.6.0 ×1 (+#101 triage) · backlog ×11.
**`dup?` flags:** #734, #511, #380, #118 — decide whether to keep the existing issue, the new B2 issue, or merge.

---

## How this gets applied (after you approve this draft)

1. Create the 6 epics → capture their issue numbers.
2. Create the B2 fresh issues → attach each as a **sub-issue** of its epic.
3. Apply B3: rename existing issues, relabel, attach to epics as sub-issues, close/merge approved `dup?`.
4. Milestones: provide the milestone numbers for 1.1.0–1.6.0 to auto-attach epics, or link them in the UI.

**Open questions to resolve before applying:**
- Confirm the `⚠` associations (#101, #383, sankey, font-size, tags, metadata-table).
- For each `dup?`: keep existing / keep new / merge.
