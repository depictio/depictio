# AI assistant

Depictio ships an opt-in, LLM-backed assistant (issue #79 / epic #844) with
five user-facing flows:

1. **Per-section summaries** — a sparkle button in each dashboard section
   header (and above the grid on section-less dashboards) generates a
   Markdown summary of what the section currently shows: card values,
   figure data and table rows, with the active filters applied. Summaries
   are cached server-side and reload with the dashboard; a **stale** badge
   with one-click *Regenerate* appears when filters change afterwards.
   Dashboards with several sections also get a **Summarize all** button
   above the grid — a sequential sweep where the hash cache short-circuits
   sections whose on-screen context hasn't changed.
2. **Live dashboard updates from a prompt** — the "Ask the dashboard" panel
   (viewer + editor) answers data questions and can propose dashboard
   actions. *Hybrid, expression-first*: when an existing interactive
   component covers the column, the AI sets that widget's value (visible
   and user-adjustable); otherwise it injects a sandboxed Polars
   `filter_expr`, shown as a removable **AI filters (n) ×** chip.
   Percentile asks ("top 3% of X") are resolved **server-side** to a
   concrete threshold on the live, filtered data — the expression sandbox
   never gains quantile primitives, and the provenance ("top 3% of depth ⇒
   depth ≥ 97") is kept with the filter.
   Plans can also carry **figure mutations** ("switch that scatter to a
   log scale"): applied ones become *transient* per-request `dict_kwargs`
   overrides on the figure render (UI-mode figures only — never persisted,
   code-mode figures ignore them), shown as a removable **AI figure
   tweaks (n) ×** chip next to the AI filters chip.
3. **Read-only deep analysis** — the **Analyze** button next to the "Ask
   the dashboard" panel opens a full-screen surface running the assistant
   in `mode: "analyze"`. The two modes are exclusive by contract: the
   mutating flow above proposes dashboard actions; the analysis flow can
   never apply anything (the server strips any `actions` the model emits
   and records the drop as a warning). In exchange it gets much more
   room:
   - **Every data collection on the dashboard** is in scope, with the
     project's declared `joins:` in the prompt; the model addresses them
     as `dc["<tag>"]` and can join across collections.
   - The loop runs under a **three-bound budget** (steps, total tokens,
     wall clock — first bound hit ends the run) with the countdown shown
     to the model each turn so it concludes deliberately.
   - Code executes in a **killable subprocess sandbox**: a step that
     overruns its deadline is killed mid-flight and surfaced as an error
     step the model can react to, instead of wedging a worker thread.
   - The output is an **AnalysisReport**: a Markdown narrative plus
     findings, where every finding must cite `evidence_step_ids` of
     successfully executed steps — claims without executed evidence are
     dropped at validation, never rendered with a caveat. Each step
     records `rows_in → rows_out` cardinalities, which is what makes a
     silently-matched-everything filter visible. Reports persist in the
     `ai_analyses` Mongo collection (derived artifacts, never written to
     the dashboard) and past runs reload from the modal's history pane.
4. **Component from a prompt**: in the editor, *Add → Component* opens the
   Add-component page, whose chooser has three tiles: *Manual*, *Catalog*
   and, when the feature is on, *Describe with AI*. The AI tile is prompt
   first: its stepper has two steps, **Describe** and Component Design,
   with no Component Type grid and no Data Source step (the manual path
   keeps both). On Describe you type what the component should show; the
   component type and the data collection both default to **Auto**. Left
   on Auto, the assistant picks them from the prompt and the project's data
   collections, preferring the ones already on the dashboard, and says why.
   Either can be pinned instead: the type is a row of tiles (Auto plus the
   nine types: figure, card, interactive, table, multiqc, image, map, text,
   advanced_viz) and the collection a row of chips (Auto plus the
   dashboard's own collections, with the rest of the project behind an
   *N other collections in the project* fold). A one-line summary under
   each says what will be used. `text` needs no collection: the chips are
   dimmed and inert, the summary reads *Not needed for text*, and the
   prompt is answered with the dashboard itself as context.
   *Generate* sends the prompt plus whatever was pinned; the LLM emits YAML
   in the exact grammar `depictio-cli dashboard import` consumes, the
   server validates it through `DashboardDataLite.from_yaml` (with one
   feedback-and-retry round), and the builder lands on Component Design
   with the live preview rendering. A routing notice there names the type
   and collection that were used, with the assistant's reason when it
   chose them; *Back* returns to Describe with both pinned to those values,
   so a wrong guess costs one change and a regenerate. On Design a *Refine
   with AI* button iterates on the current component (it reads *AI fill*
   while the config is still empty).
   Next to the prompt, for every type, the Describe step also offers a
   **Suggestions** mode that asks the other question: what would fit this
   dashboard? With type and collection on Auto the assistant proposes a mix
   of components across the dashboard's collections; it knows what is
   already on the dashboard and does not repeat it. Pinning a type or a
   collection narrows the list to it. Each suggestion is a validated lite
   component with a title, a one-line rationale and a summary of what it
   is made of (figures also get a live preview). Advanced visualizations
   and tables are ranked from the data without an LLM call and are marked
   *ranked from the data*. Catalog offers for the same collections appear
   under **From the catalog**: known tool outputs matched to the project,
   deterministic and free of any model call. *Use this* takes the same
   hand-off into Component Design as *Generate*, with the suggestion's
   rationale in the routing notice, no prompt required.
   `advanced_viz` proposals are grounded on the kinds the chosen data
   collection supports, so the model cannot pick a visualization the data
   cannot feed.
   Components authored this way carry an `ai_source` provenance mark,
   shown as a small badge in the editor, the same way catalog components
   carry `catalog_source`.
5. **Whole dashboard from a project**: on `/dashboards`, the Create
   dashboard modal gains a **Generate with AI** tab when the deployment
   enables it. Pick a project, optionally a subset of its table data
   collections, describe the intent, and the assistant plans a funnel
   (cohort filters, KPI cards, figures, a reference table), fills and
   validates every component the way the Describe step does, lays it out
   deterministically and lands it as a new dashboard flagged as an **AI
   draft**. In the editor a review bar in the draft banner then walks you
   through the generated tiles one by one (why the planner asked for each,
   *Regenerate*, *Keep*, *Remove*), tracking how much of the draft you have
   been through, before you promote or discard it. Details in
   [Generate a dashboard](#generate-a-dashboard).

## Generate a dashboard

The Describe step adds one component to a dashboard that already exists.
Whole-dashboard generation starts one step earlier: from a project and an
optional intent it plans a complete first dashboard, fills every planned
component through the same generation and validation the Describe step
uses, lays it out deterministically and saves it as a **draft** that you
review in the editor before promoting or discarding it. It is a separate
opt-in (`DEPICTIO_AI_GENERATE_DASHBOARD_ENABLED`, on top of
`DEPICTIO_AI_ENABLED`), it needs editor permission on the project, and it
is refused in public mode, since a generation is a dashboard import.

### Walkthrough

1. On `/dashboards`, *Create dashboard* opens the usual modal; with the
   feature on it has a third tab, **Generate with AI**.
2. Pick the **project**. The collection picker lists its table data
   collections, marking the ones that are the result of a project-level
   join the way the component builder's data collection dropdown does:
   leave it empty to let the planner see all of them (up to
   `DEPICTIO_AI_GENERATE_MAX_COLLECTIONS`; the rest are left out with a
   warning), or pick the subset the dashboard should be about. The
   **intent** is optional free text (up to 2000 characters: the audience,
   the questions to answer, what matters most); left empty, the planner
   builds the most useful overview of the project it can. Naming a colour,
   a palette or a brand in it ("in green", "our brand is teal") steers the
   section colours. The **title** is
   optional too: pinned, a name collision is refused; left empty, the
   planner chooses one and a collision gets an *(AI draft N)* suffix plus
   a warning. Without a server-side key the tab shows the same key field
   as the other AI surfaces.
3. **Review the plan before building** is on by default. With it checked,
   *Generate* only plans: the run stops after the plan, saves nothing, and
   the panel shows what would be built so it can be judged before any of
   it is paid for. *Build this plan* sends the plan back and fills it;
   *Re-plan* asks for another plan, with the intent edited if you like.
   Unchecked, the run plans and fills in one pass, as it used to.
4. *Generate* opens a panel of its own under the form and streams the run
   into it: a stage rail (reading the project, inventory, planning,
   filling, checking, layout, saving) that names the current stage, counts
   the steps and times each one, the **run limit** spent against its token
   and wall-clock caps (with the cost the provider billed, when it reports
   one), the **plan** (title, subtitle, the collections it uses, a tally
   by component type, then one block per section with its icon, its
   rationale and the components it holds with their tags, types,
   collections and intents), and **one card per planned component**,
   grouped by section, each settling on *ok*, *repaired* (validated after
   a repair round) or *dropped* (with the reason). A component nobody has
   reported on yet stays colourless, so colour on that grid only ever
   means an outcome. *Stop generating* ends the run; a run that does not
   reach its terminal event saves no dashboard.
5. When the terminal event arrives the panel shows the dashboard title,
   the warnings (dropped components, collections left out, a renamed
   title) and an *Open in editor* button. Nothing navigates on its own:
   the click is the hand-off.
6. The editor opens with a **draft banner** above the dashboard: the model
   that produced it, the date, a *Why this layout* fold with the planner's
   reason for each section, the warnings behind a fold of their own, a
   *reviewed n of m* counter, the review bar that walks the generated tiles
   (see [Reviewing a draft](#reviewing-a-draft)) and two actions. *Promote* flips the status to
   `promoted`: the banner and the badges go away and the provenance
   (model, prompt, run id) stays on the document. *Discard* asks for
   confirmation, deletes the dashboard and returns to `/dashboards`. Until
   you decide, the dashboard card in the list and the dashboard info panel
   carry an **AI draft** badge. A draft is otherwise a normal dashboard:
   you can edit it in the editor first, and autosave keeps the draft flag
   as it is (it can neither clear nor set it; only *Promote* changes it).

### Reviewing a draft

A draft is reviewed tile by tile, not as one block, and the review lives
in the banner rather than on the tiles. Nothing is added to a generated
component: the banner carries a cursor over the draft's tiles in plan
order, *3 of 12*, naming the one under review, and the canvas answers with
two cues. A tile nobody has been through yet keeps a hairline dashed
outline; the tile the cursor names is outlined solid, and it is scrolled
into view when the cursor moves.

The banner is at the top of the page and the tile under review is often
far down it, so the bar follows: once the banner has scrolled out of
sight a compact version of it floats at the bottom of the viewport, and
it goes away again as soon as the banner is back on screen. Only one of
the two is ever on the page.

Under the cursor the banner quotes the planner: the brief it wrote for
that tile, and the reason it gave for the tile's section. Both were
written before anything was filled, so they say why the component was
asked for rather than what it ended up showing. Then the three decisions:

- *Regenerate* re-runs that one tile, with an optional instruction ("use a
  box plot", "group by cohort"). It goes through the same fill and the same
  validation as the original run, repair round included, and the result
  replaces the component in place: its position, its size and its section
  stay as they were and the rest of the dashboard is untouched. A
  regeneration that fails validation leaves the tile as it was and reports
  the error in the bar, with the cursor still on it.
- *Keep* marks the tile reviewed without changing it and steps to the next
  tile that has not been through, so twelve tiles are twelve clicks. On a
  tile already reviewed it reads *Reviewed, undo*.
- *Remove* takes the tile out of the draft and steps on as well.

Keeping the actions off the tiles is deliberate. They have to be visible
for as long as the draft is one, and icons sitting permanently on every
component crowd the very thing they are asking you to judge.

A whole grid section can also be regenerated at once, from *Whole section*
inside the bar's regenerate popover, offered when the tile under review
sits in a grid section: the components of that section are filled again
and the layout pass re-runs for that section only, so the other sections
keep the boxes they had.

The banner counts the progress, *reviewed n of m*, and gates the promotion
on it. Once every tile is either reviewed or removed, *Promote* applies
outright; before that it asks for a confirmation first, since promoting is
what turns the draft into an ordinary dashboard.

The review state lives on the dashboard document next to the draft flag, in
the same `ai_generation` field, so it survives a reload or a change of
browser. Like the draft flag it is stripped from autosave payloads: the
editor can neither mark a tile reviewed nor unmark one, only the review
route writes it.

### Grounding and validation

The model never starts from a blank page and its output is never saved
as-is. The planner works from an inventory of the project (the schemas,
redacted sample rows and declared joins of the selected table collections,
the catalog offers matched to the project, and the advanced visualization
kinds each collection can feed, ranked from the data) and returns a JSON
plan that is normalised before anything is generated; each planned
component is then filled and checked one at a time. A visualization kind
is only offered when every role it requires matched a column on its name
and not merely on its dtype: a kind that fits the table's shape by
accident is worse than no suggestion, because the planner reads the list
as a recommendation.

- **Plan**: one model call. The plan is validated against a strict schema,
  clamped to `DEPICTIO_AI_GENERATE_MAX_COMPONENTS` and
  `DEPICTIO_AI_GENERATE_MAX_SECTIONS`, its tags deduplicated, its section
  icons and colours restricted to the sets the sections manager offers,
  and its sections put in funnel order. Invalid JSON gets one retry with
  the error; a second failure ends the run.
- **Fill**: every data-bound component goes through the same generation as
  the Describe step (its intent plus a dashboard context: the title, its
  section and the sibling tags already filled) and the same validator
  (`validate_single`, the `depictio-cli dashboard import` grammar).
  Section headers are written from the plan without a model call, and
  advanced visualizations are bound deterministically from a catalog offer
  or from the ranked role bindings, never invented.
- **Schema checks**: on top of the grammar, the server runs the checks the
  CLI's `dashboard validate` runs online: every referenced column exists
  in the collection, card aggregations and interactive widgets are
  compatible with the column type, breakdown and trend columns exist and
  the secondary card layouts have their required companions, a
  multi-select never lands on a column with more than 50 distinct values,
  and an advanced visualization's role bindings name real columns of the
  right dtype.
- **Render check**: once every component is filled, each one is asked to
  produce what it would show, through the same server-side path the viewer
  calls, with the cheapest projection that would still fail (one row, one
  shape, one aggregation). A component that cannot render is dropped with
  its reason rather than saved into a dashboard where it would answer 500.
  Text has nothing to probe, and image, map and MultiQC tiles have no
  in-process probe cheap enough to be worth its cost, so they are not
  checked.
- **Repair, then drop**: a component that fails gets
  `DEPICTIO_AI_GENERATE_MAX_REPAIRS_PER_COMPONENT` repair rounds with the
  formatted error; once they are exhausted the component is dropped and
  the run continues. When the token or wall-clock budget runs out, the
  components not yet filled are dropped with a `budget` reason. A run that
  ends with no surviving data-bound component fails and saves nothing.
- **Envelope and persistence**: the assembled dashboard is parsed once
  through `DashboardDataLite.from_yaml` (with one repair round at that
  level), then persisted through the exact path
  `POST /dashboards/import/yaml` uses, with the `ai_generation` provenance
  added. The YAML travels in the terminal event, so a draft can be
  re-imported with the CLI.

### Layout conventions

The layout pass is deterministic and writes explicit boxes on the
8-column grid, so the same plan always produces the same page:

- Sections follow the funnel: cohort filters, then metrics, then
  analysis, then reference.
- Interactive components go to the left filter panel, stacked.
- Each grid section starts with a one-row text header taken from the
  plan's section description.
- Cards are 2 columns wide in rows of four, and rows are always full:
  three leftovers become 3/3/2, two become 4/4, one spans the row.
- Figures are half-width in pairs; a lone trailing figure is widened to
  the full row. Advanced visualizations take a full row at double height.
- The reference table comes last, full width, and a section holding
  nothing but tables starts collapsed, the way the reference dashboards
  fold their raw data.

### Previous runs

A draft is not the only trace a run leaves. The *Generate with AI* tab
lists what the selected project has generated before, newest first: the
prompt, the model, the status (`running`, `planned` for a run that stopped
at the plan on purpose, `complete`, `failed` or `cancelled`), the date, how many components came out *ok*, *repaired* or
*dropped*, and the warnings the run collected. Each row is named by the
dashboard it saved, falling back to the title the plan chose, then to what
was asked for, then to the date, so a row is worth reading even when the
run never got as far as saving anything. A run that saved a dashboard links
to it, so a draft left half-reviewed is one click away; a run whose
dashboard has since been deleted says so instead of offering a dead link. The rows are
the `ai_generations` records, which are written at the start, after the
plan, after every component and at the end, so a cancelled or failed run
shows up in the list too.

### Limits of the MVP

- **Single tab.** The draft is one dashboard tab; multi-tab plans are not
  produced.
- **Table collections only.** MultiQC, image and map collections are not
  inventoried and never planned; add them by hand once the draft is
  promoted.
- **Review is per tile, generation is not.** Each tile can be regenerated,
  kept or removed on its own, and a section can be regenerated as a whole,
  but what a run may produce is still bounded by the two limits above: one
  tab, table collections only.
- **Nothing lands without data.** A run whose data-bound components were
  all dropped fails instead of saving an empty shell.

## Enabling

Everything is off by default. The `/ai` router is not registered and no AI
UI mounts until:

```bash
DEPICTIO_AI_ENABLED=true
```

Settings (env prefix `DEPICTIO_AI_`, see `AIConfig` in
`depictio/api/v1/configs/settings_models.py`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `DEPICTIO_AI_ENABLED` | `false` | Master switch (router + UI flags) |
| `DEPICTIO_AI_DEFAULT_MODEL` | `openrouter/anthropic/claude-sonnet-4-6` | LiteLLM model id — the provider prefix decides which key applies |
| `DEPICTIO_AI_API_KEY` | *(unset)* | Server-side fallback LLM key (optional) |
| `DEPICTIO_AI_ALLOW_USER_KEYS` | `true` | Accept per-request `X-LLM-API-Key` headers (BYOK) |
| `DEPICTIO_AI_MAX_SAMPLE_ROWS` | `8` | Sample rows included in prompts |
| `DEPICTIO_AI_MAX_CONTEXT_CHARS` | `60000` | Hard cap on prompt context size (enforced on summaries and the multi-DC analysis context, which degrades by dropping samples then whole collections, with a warning) |
| `DEPICTIO_AI_MAX_TOKENS` | `4096` | Completion token cap per call |
| `DEPICTIO_AI_ANALYZE_MAX_STEPS` | `20` | Read-only analysis: hard ceiling on LLM/executor round-trips per run |
| `DEPICTIO_AI_ANALYZE_MAX_TOKENS_TOTAL` | `200000` | Read-only analysis: total tokens (prompt + completion) per run — the cost lever |
| `DEPICTIO_AI_ANALYZE_MAX_WALL_CLOCK_S` | `300` | Read-only analysis: wall-clock bound per run — the UX lever |
| `DEPICTIO_AI_GENERATE_DASHBOARD_ENABLED` | `false` | Whole-dashboard generation: mounts the *Generate with AI* tab and the `/ai/generate-dashboard` route (needs `DEPICTIO_AI_ENABLED` too) |
| `DEPICTIO_AI_GENERATE_MAX_COMPONENTS` | `16` | Whole-dashboard generation: hard ceiling on the components a plan may contain (the plan is clamped, not rejected) |
| `DEPICTIO_AI_GENERATE_MAX_SECTIONS` | `4` | Whole-dashboard generation: hard ceiling on the grid sections a plan may contain |
| `DEPICTIO_AI_GENERATE_MAX_TOKENS_TOTAL` | `150000` | Whole-dashboard generation: total tokens (prompt + completion) per run, the cost lever; once spent, the components not yet filled are dropped |
| `DEPICTIO_AI_GENERATE_MAX_WALL_CLOCK_S` | `180` | Whole-dashboard generation: wall-clock bound per run, the UX lever; same drop rule |
| `DEPICTIO_AI_GENERATE_MAX_REPAIRS_PER_COMPONENT` | `1` | Whole-dashboard generation: repair round-trips per component before it is dropped from the draft |
| `DEPICTIO_AI_GENERATE_MAX_COLLECTIONS` | `6` | Whole-dashboard generation: table collections described to the planner; the rest are left out with a warning |

### Keys: BYOK with a server fallback

Users paste their own key in the dashboard **Settings drawer → AI
assistant** (stored in browser localStorage only, sent per request as
`X-LLM-API-Key`, never persisted or logged server-side). When the request
carries no user key, `DEPICTIO_AI_API_KEY` applies. Deployments can run
either pure-BYOK (no server key), server-key-only
(`DEPICTIO_AI_ALLOW_USER_KEYS=false`), or both.

The public `GET /utils/status` payload advertises
`features: {ai, ai_user_keys, ai_generate_dashboard}` so the SPA hides
every AI affordance when the feature is off; the last flag gates the
*Generate with AI* tab alone.

## API surface

All under `/depictio/api/v1/ai`, feature-gated, authenticated like every
other read (`get_user_or_anonymous` + project-viewer permission checks):
the dashboard-generation and draft-review routes are the exception, they
are writes and require a signed-in user with editor permission.

- `GET /ai/health` — configured model + key posture (no key material).
- `POST /ai/suggest-components`: typed suggestions for a dashboard (the
  *Suggestions* mode of the Describe step). Request: `dashboard_id`
  (required; the dashboard context and the project inventory come from
  it), `component_type` and `data_collection_id` (both optional, `null`
  means Auto) and `n` (default 4, 1 to 8). Response: `suggestions`, each
  with `component_type`, `data_collection_id`, `data_collection_tag`,
  `workflow_id` (all three `null` for `text`), `title`, `rationale`,
  `component` (the validated lite dict, same grammar as the import),
  `code` (figures only) and `origin` (`llm`, or `ranked` for the
  deterministic advanced_viz and table candidates), plus `warnings` (for
  instance when the LLM call failed and only ranked candidates are shown).
  Errors: 404 for an unknown dashboard or a pinned collection outside the
  project, 422 when a pinned type has no fitting collection, 502 when
  nothing usable came back.
- `POST /ai/suggest-figures`: deprecated, kept for one release. Superseded
  by `/ai/suggest-components`; the viewer no longer calls it.
- `POST /ai/component-from-prompt` — YAML component generation +
  validation (2 attempts), behind *Generate*, *Use this* and *Refine with
  AI*. `component_type` and `data_collection_id` are optional: a `null`
  asks the server to route it from the prompt, and `dashboard_id` is
  required whenever either is routed (the candidates are the dashboard's
  project collections, those already on the dashboard preferred). The
  response carries the validated component plus `data_collection_id`,
  `workflow_id` and `routing` (`source` is `user` when both were pinned,
  `single` when the collection was the only candidate, `auto` when the
  model chose; with a `reason` and the `alternatives` it considered). For
  `text`, `data_collection_id` and `workflow_id` are `null` and `routing`
  may be `null`.
- `POST /ai/resolve-filters` — single-shot NL → validated filter plan.
- `POST /ai/analyze` — streaming (SSE over chunked POST). `mode` picks the
  loop: `mutate` (default) is the short ReAct loop with dashboard actions,
  emitting `status/step/answer/actions/result/error/done`; `analyze` is
  the read-only budgeted loop, emitting
  `status/plan/budget/step/answer/report/result/error/done` and never
  `actions`. Both execute Polars through the AST allowlist; `analyze`
  additionally runs it in the killable subprocess sandbox with the
  multi-DC `dc["<tag>"]` scope.
- `GET /ai/analyses/{dashboard_id}` — recent `AnalysisReport`s for the
  dashboard (Mongo collection `ai_analyses`), newest first.
- `POST /ai/summarize-section` + `GET /ai/summaries/{dashboard_id}` —
  summary generation and the hash-keyed cache (Mongo collection
  `ai_summaries`; summaries are derived artifacts, never stored on the
  dashboard document).
- `POST /ai/generate-dashboard`: streaming, same SSE-over-chunked-POST
  envelope as `/ai/analyze`. Request: `project_id` (required), `prompt`
  (optional, up to 2000 characters), `title` (optional),
  `data_collection_ids` (optional subset; every id must belong to the
  project) and `overwrite`. The gates answer with real HTTP codes before
  the stream opens: 404 while `DEPICTIO_AI_GENERATE_DASHBOARD_ENABLED` is
  off, 403 in public mode (a generation is an import) or without editor
  permission on the project, 400 for a collection outside the project,
  409 for a title collision on an explicit `title` without `overwrite`.
  Events: `status`, `plan` (the validated `DashboardPlan`), `budget` after
  every model call (`steps_used`, `tokens_used`, `seconds` and the three
  maxima), `component` once per planned component (`tag`, `section`,
  `component_type`, `status` in `ok` / `repaired` / `dropped`, `attempts`,
  `error`), the terminal `dashboard` (`dashboard_id`, `title`,
  `project_id`, `yaml`, `warnings`, `dropped`), then `done`; `error` +
  `done` on failure. Every run is recorded in the Mongo collection
  `ai_generations` (status `running` / `complete` / `failed` /
  `cancelled`, the plan, the per-component outcomes, the YAML and the
  budget spent), a derived artifact like `ai_analyses`. The dashboard
  itself carries an `ai_generation` field (`status`, `model`, `prompt`,
  `generated_at`, `run_id`, `warnings`): absent on hand-made dashboards,
  not part of the YAML surface, and stripped from autosave payloads so the
  editor can neither clear nor forge it.
- `POST /ai/generated-dashboards/{dashboard_id}/promote`: flips
  `ai_generation.status` from `draft` to `promoted` and returns
  `{dashboard_id, status: "promoted"}`; editor permission on the
  dashboard, 404 when it carries no `ai_generation`. Discarding a draft is
  the regular `DELETE /dashboards/delete/{dashboard_id}`.
- `POST /ai/generated-dashboards/{dashboard_id}/components/{index}/regenerate`:
  streaming, the same SSE-over-chunked-POST envelope, for one tile of a
  draft. Body: an optional `instruction` refining what the tile should
  show. The component at `index` is filled and validated the way the run
  filled it (schema checks and repair round included) and replaces the old
  one in place, keeping its layout box; nothing else on the dashboard
  changes, and a failure leaves the tile as it was. Editor permission on
  the dashboard, 404 when it carries no `ai_generation` or the index does
  not exist.
- `POST /ai/generated-dashboards/{dashboard_id}/sections/{section}/regenerate`:
  the same for a whole grid section, refilling its components and re-running
  the layout pass for that section alone.
- `POST /ai/generated-dashboards/{dashboard_id}/review`: records which
  tiles have been reviewed and which were removed. The review block sits
  next to the draft flag in `ai_generation` and, like the flag, is stripped
  from autosave payloads, so this route is the only writer.
- `GET /ai/generations/{project_id}`: the project's recent generation runs
  from the `ai_generations` collection, newest first, behind the same
  project-viewer permission as the other reads: prompt, model, status,
  date, the per-component outcomes (`ok` / `repaired` / `dropped`), the
  warnings and the `dashboard_id` when the run saved one.

## Safety posture

- LLM output is never executed or applied as-is:
  - components go through the same validator the CLI import uses;
  - filter expressions go through the existing `filter_expr` sandbox
    (`depictio/models/components/filter_expr.py`);
  - analyze code runs under an AST allowlist (`df`/`pl` only, no imports,
    no dunders, no bare calls);
  - percentile thresholds are computed by the server, not the model;
  - figure mutations are transient render-request overrides — nothing is
    written to the dashboard document, code-mode figures ignore them, and
    the chip reverts them in one click.
- Sample rows sent to the LLM pass a PII redaction pass (emails, phones).
- Generated dashboards are persisted through the YAML import path and land
  as drafts: the `ai_generation` flag is stripped from autosave payloads,
  only the promote route flips it, and generation is refused in public
  mode like any import.
- Reverse proxies must not buffer the analyze stream: for nginx, set
  `proxy_buffering off;` on `/depictio/api/v1/ai/analyze` (the response
  already carries `X-Accel-Buffering: no`). The same applies to
  `/depictio/api/v1/ai/generate-dashboard`.

## Testing

- Unit suites live in `depictio/tests/api/v1/endpoints/ai_endpoints/`
  (LLM monkeypatched — no network). The prompt-sheet YAML examples are
  validated through the real validator so grammar drift fails CI.
- E2E: `depictio/tests/e2e-playwright/tests/ui/ai-assistant.spec.ts`
  intercepts `/ai/*` and the status flags — deterministic, no keys.
