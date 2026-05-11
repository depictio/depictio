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
  AnalyzeRequest,
  ComponentFromPromptRequest,
  ComponentFromPromptResponse,
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

export interface AnalyzeStreamHandlers {
  onEvent: (event: AIStreamEvent) => void;
  signal?: AbortSignal;
}

/** Drive `/ai/analyze` and dispatch each SSE event to `onEvent`.
 *
 *  Resolves when the server closes the connection. Throws if the request
 *  itself fails (e.g. 4xx before streaming starts) or if the stream is
 *  aborted via `signal`. Caller is responsible for tracking which events
 *  represent a final result. */
export async function streamAnalyze(
  body: AnalyzeRequest,
  llmKey: string | null | undefined,
  { onEvent, signal }: AnalyzeStreamHandlers,
): Promise<void> {
  const res = await authFetch(`${API_BASE}/ai/analyze`, {
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
    throw new Error(`/ai/analyze: ${res.status} ${text || res.statusText}`);
  }
  if (!res.body) {
    throw new Error('/ai/analyze: response has no body');
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
