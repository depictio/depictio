# AI assistant

Depictio ships an opt-in, LLM-backed assistant (issue #79 / epic #844) with
three user-facing flows:

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
3. **Component from a prompt** — *Add component → With AI…* in the editor
   takes a component type, a data collection and a prompt, has the LLM emit
   YAML in the exact grammar `depictio-cli dashboard import` consumes,
   validates it through `DashboardDataLite.from_yaml` (with one
   feedback-and-retry round), and lands you on the builder's Design step
   with the live preview rendering. An *AI fill / Refine with AI* button
   inside the Design step iterates on the current component.
   For figures the modal also offers a **Suggestions** mode: the LLM
   proposes a few plots grounded in the data collection's actual columns
   (title, rationale, display-only Python) and picking one lands in the
   same Design-step hand-off — no prompt required.

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
| `DEPICTIO_AI_MAX_CONTEXT_CHARS` | `60000` | Hard cap on prompt context size |
| `DEPICTIO_AI_MAX_TOKENS` | `4096` | Completion token cap per call |

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
  *Suggestions* mode of the Add-with-AI modal).
- `POST /ai/component-from-prompt` — YAML component generation +
  validation (2 attempts).
- `POST /ai/resolve-filters` — single-shot NL → validated filter plan.
- `POST /ai/analyze` — streaming (SSE over chunked POST) ReAct loop with
  an AST-allowlisted Polars executor; emits
  `status/step/answer/actions/result/error/done` events.
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
