# AI assistant

Depictio ships an opt-in, LLM-backed assistant (issue #79 / epic #844) with
four user-facing flows:

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
   For figures, once a collection is resolvable (pinned, or the dashboard
   uses exactly one), the Describe step also offers a **Suggestions**
   mode: the LLM proposes a few plots grounded in the collection's actual
   columns (title, rationale, display-only Python) and *Use this* takes the
   same hand-off into Component Design, no prompt required.
   `advanced_viz` proposals are grounded on the kinds the chosen data
   collection supports, so the model cannot pick a visualization the data
   cannot feed.
   Components authored this way carry an `ai_source` provenance mark,
   shown as a small badge in the editor, the same way catalog components
   carry `catalog_source`.

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

### Keys: BYOK with a server fallback

Users paste their own key in the dashboard **Settings drawer → AI
assistant** (stored in browser localStorage only, sent per request as
`X-LLM-API-Key`, never persisted or logged server-side). When the request
carries no user key, `DEPICTIO_AI_API_KEY` applies. Deployments can run
either pure-BYOK (no server key), server-key-only
(`DEPICTIO_AI_ALLOW_USER_KEYS=false`), or both.

The public `GET /utils/status` payload advertises
`features: {ai, ai_user_keys}` so the SPA hides every AI affordance when
the feature is off.

## API surface

All under `/depictio/api/v1/ai`, feature-gated, authenticated like every
other read (`get_user_or_anonymous` + project-viewer permission checks):

- `GET /ai/health` — configured model + key posture (no key material).
- `POST /ai/suggest-figures` — data-grounded figure suggestions (the
  *Suggestions* mode of the Describe step, figures only).
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
- Reverse proxies must not buffer the analyze stream: for nginx, set
  `proxy_buffering off;` on `/depictio/api/v1/ai/analyze` (the response
  already carries `X-Accel-Buffering: no`).

## Testing

- Unit suites live in `depictio/tests/api/v1/endpoints/ai_endpoints/`
  (LLM monkeypatched — no network). The prompt-sheet YAML examples are
  validated through the real validator so grammar drift fails CI.
- E2E: `depictio/tests/e2e-playwright/tests/ui/ai-assistant.spec.ts`
  intercepts `/ai/*` and the status flags — deterministic, no keys.
