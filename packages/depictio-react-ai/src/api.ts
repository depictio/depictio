/**
 * Client for the /ai endpoints.
 *
 * Reuses depictio-react-core's authFetch so JWT refresh + retry-on-401
 * stays in one place. The user's LLM API key is layered on top as a
 * per-request `X-LLM-API-Key` header — never persisted on the server,
 * never logged.
 *
 * /analyze streams SSE-formatted chunks; we parse them in the browser
 * using a small state machine over the response body's ReadableStream
 * rather than EventSource (EventSource is GET-only and can't carry
 * custom headers, both of which we need).
 */

import { API_BASE, authFetch } from 'depictio-react-core';

import type {
  AIStreamEvent,
  AIStreamEventType,
  AnalysesResponse,
  AnalyzeRequest,
  ComponentFromPromptRequest,
  ComponentFromPromptResponse,
  GenerateDashboardRequest,
  GenerationSummary,
  PromoteGeneratedDashboardResponse,
  RegenerateRequest,
  ResolveFiltersRequest,
  ResolveFiltersResponse,
  ReviewComponentRequest,
  ReviewComponentResponse,
  SuggestComponentsRequest,
  SuggestComponentsResponse,
  SummariesResponse,
  SummarizeSectionRequest,
  SummarizeSectionResponse,
} from './types';

function llmKeyHeaders(llmKey: string | null | undefined): Record<string, string> {
  return llmKey ? { 'X-LLM-API-Key': llmKey } : {};
}

async function postJson<T>(
  path: string,
  body: unknown,
  llmKey: string | null | undefined,
): Promise<T> {
  const res = await authFetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...llmKeyHeaders(llmKey) },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${path}: ${res.status} ${text || res.statusText}`);
  }
  return (await res.json()) as T;
}

export function componentFromPrompt(
  body: ComponentFromPromptRequest,
  llmKey: string | null | undefined,
): Promise<ComponentFromPromptResponse> {
  return postJson<ComponentFromPromptResponse>(
    '/ai/component-from-prompt',
    body,
    llmKey,
  );
}

export function suggestComponents(
  body: SuggestComponentsRequest,
  llmKey: string | null | undefined,
): Promise<SuggestComponentsResponse> {
  return postJson<SuggestComponentsResponse>('/ai/suggest-components', body, llmKey);
}

export function resolveFilters(
  body: ResolveFiltersRequest,
  llmKey: string | null | undefined,
): Promise<ResolveFiltersResponse> {
  return postJson<ResolveFiltersResponse>('/ai/resolve-filters', body, llmKey);
}

export function summarizeSection(
  body: SummarizeSectionRequest,
  llmKey: string | null | undefined,
): Promise<SummarizeSectionResponse> {
  return postJson<SummarizeSectionResponse>('/ai/summarize-section', body, llmKey);
}

export interface AIHealth {
  status: string;
  model: string;
  allow_user_keys: boolean;
  server_key_configured: boolean;
}

export async function getAIHealth(): Promise<AIHealth> {
  const res = await authFetch(`${API_BASE}/ai/health`);
  if (!res.ok) throw new Error(`/ai/health: ${res.status}`);
  return (await res.json()) as AIHealth;
}

export async function getSummaries(dashboardId: string): Promise<SummariesResponse> {
  const res = await authFetch(`${API_BASE}/ai/summaries/${dashboardId}`);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`/ai/summaries: ${res.status} ${text || res.statusText}`);
  }
  return (await res.json()) as SummariesResponse;
}

/** Past analysis reports for a dashboard, newest first. */
export async function getAnalyses(dashboardId: string): Promise<AnalysesResponse> {
  const res = await authFetch(`${API_BASE}/ai/analyses/${dashboardId}`);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`/ai/analyses: ${res.status} ${text || res.statusText}`);
  }
  return (await res.json()) as AnalysesResponse;
}

export interface AIStreamHandlers {
  onEvent: (event: AIStreamEvent) => void;
  signal?: AbortSignal;
}

/** Former name of AIStreamHandlers, kept for hosts that import it. */
export type AnalyzeStreamHandlers = AIStreamHandlers;

/** POST `body` to an SSE route and dispatch each frame to `onEvent`.
 *
 *  Resolves when the server closes the connection. Throws if the request
 *  itself fails (e.g. 4xx before streaming starts) or if the stream is
 *  aborted via `signal`. Caller is responsible for tracking which events
 *  represent a final result. Shared by every streaming /ai route so the
 *  frame parsing lives in one place. */
export async function streamPost(
  path: string,
  body: unknown,
  llmKey: string | null | undefined,
  { onEvent, signal }: AIStreamHandlers,
): Promise<void> {
  const res = await authFetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...llmKeyHeaders(llmKey),
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${path}: ${res.status} ${text || res.statusText}`);
  }
  if (!res.body) {
    throw new Error(`${path}: response has no body`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line (\n\n).
    let sep = buffer.indexOf('\n\n');
    while (sep !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const parsed = parseFrame(frame);
      if (parsed) onEvent(parsed);
      sep = buffer.indexOf('\n\n');
    }
  }
  // Flush any trailing frame (shouldn't happen if server closes cleanly).
  if (buffer.trim()) {
    const parsed = parseFrame(buffer);
    if (parsed) onEvent(parsed);
  }
}

/** Drive `/ai/analyze` and dispatch each SSE event to `onEvent`. */
export function streamAnalyze(
  body: AnalyzeRequest,
  llmKey: string | null | undefined,
  handlers: AIStreamHandlers,
): Promise<void> {
  return streamPost('/ai/analyze', body, llmKey, handlers);
}

/** Drive `/ai/generate-dashboard`: status, plan, budget and component
 *  events, then the terminal `dashboard` event naming the persisted draft.
 *  The route answers 404 (feature off), 403 (public mode, or not an editor
 *  of the project) or 400 (a collection outside the project) before
 *  streaming; those surface as throws.
 *
 *  The same call serves both phases of the reviewed flow: `plan_only` stops
 *  the stream right after the `plan` event (nothing filled, nothing saved),
 *  and `plan` hands an approved plan back to be re-normalised, re-emitted and
 *  filled. Neither field set is the one-call flow. */
export function streamGenerateDashboard(
  body: GenerateDashboardRequest,
  llmKey: string | null | undefined,
  handlers: AIStreamHandlers,
): Promise<void> {
  return streamPost('/ai/generate-dashboard', body, llmKey, handlers);
}

/** Flip an AI-generated draft into a regular dashboard. Needs editor
 *  permission on the dashboard; 404 when it carries no `ai_generation`. */
export async function promoteGeneratedDashboard(
  dashboardId: string,
): Promise<PromoteGeneratedDashboardResponse> {
  const path = `/ai/generated-dashboards/${dashboardId}/promote`;
  const res = await authFetch(`${API_BASE}${path}`, { method: 'POST' });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${path}: ${res.status} ${text || res.statusText}`);
  }
  return (await res.json()) as PromoteGeneratedDashboardResponse;
}

/** Drive one tile's regeneration on a draft. `index` is the component's
 *  `stored_metadata.index`, the id every other per-component route uses.
 *  Same SSE framing as generation: status, budget and one `component`
 *  outcome, then the terminal event carrying the replacing component. */
export function streamRegenerateComponent(
  dashboardId: string,
  index: string,
  body: RegenerateRequest,
  llmKey: string | null | undefined,
  handlers: AIStreamHandlers,
): Promise<void> {
  const path =
    `/ai/generated-dashboards/${encodeURIComponent(dashboardId)}` +
    `/components/${encodeURIComponent(index)}/regenerate`;
  return streamPost(path, body, llmKey, handlers);
}

/** The same for every tile of one grid section; the layout pass re-runs for
 *  that section alone, so the rest of the dashboard keeps its boxes. */
export function streamRegenerateSection(
  dashboardId: string,
  section: string,
  body: RegenerateRequest,
  llmKey: string | null | undefined,
  handlers: AIStreamHandlers,
): Promise<void> {
  const path =
    `/ai/generated-dashboards/${encodeURIComponent(dashboardId)}` +
    `/sections/${encodeURIComponent(section)}/regenerate`;
  return streamPost(path, body, llmKey, handlers);
}

/** Mark one generated tile reviewed (`keep`) or take the mark back
 *  (`unkeep`). The review block lives on the dashboard's `ai_generation`
 *  and this route is its only writer — autosave strips it. Answers the
 *  draft's progress after the write. */
export async function reviewComponent(
  dashboardId: string,
  tag: string,
  action: ReviewComponentRequest['action'],
): Promise<ReviewComponentResponse> {
  const path = `/ai/generated-dashboards/${encodeURIComponent(dashboardId)}/review`;
  const res = await authFetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tag, action } satisfies ReviewComponentRequest),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${path}: ${res.status} ${text || res.statusText}`);
  }
  return (await res.json()) as ReviewComponentResponse;
}

/** Past whole-dashboard runs of one project, newest first. A run that saved
 *  nothing (cancelled, or failed before the draft landed) is listed too,
 *  with a null `dashboard_id`. */
export async function fetchGenerations(
  projectId: string,
  limit = 20,
): Promise<GenerationSummary[]> {
  const path = `/ai/generations/${encodeURIComponent(projectId)}?limit=${limit}`;
  const res = await authFetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${path}: ${res.status} ${text || res.statusText}`);
  }
  const data = await res.json();
  // `{generations: [...]}` is the route's own envelope; a bare list is
  // tolerated so the client does not read "no runs yet" if it is dropped.
  const wrapped = (data as { generations?: unknown })?.generations;
  if (Array.isArray(wrapped)) return wrapped as GenerationSummary[];
  return Array.isArray(data) ? (data as GenerationSummary[]) : [];
}

function parseFrame(frame: string): AIStreamEvent | null {
  let eventName: AIStreamEventType | null = null;
  const dataLines: string[] = [];
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim() as AIStreamEventType;
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart());
    }
    // Other SSE fields (id:, retry:) are ignored.
  }
  if (!eventName) return null;
  let data: Record<string, unknown> = {};
  if (dataLines.length) {
    try {
      data = JSON.parse(dataLines.join('\n')) as Record<string, unknown>;
    } catch {
      data = { raw: dataLines.join('\n') };
    }
  }
  return { type: eventName, data };
}
