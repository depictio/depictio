/**
 * The files a collection being edited would ingest, asked of
 * `POST /projects/builder/match` a moment after the last edit (450 ms), the
 * request still in flight cancelled by the next. `refresh` asks again with
 * nothing changed (an S3 prefix the reader knows has changed).
 */
import { useEffect, useMemo, useState } from 'react';

import { builderMatch, normalizeDcDraft } from 'depictio-react-core';
import type {
  BuilderDcDraft,
  BuilderMatchResult,
  BuilderRootSpec,
  BuilderWorkflowStructure,
} from 'depictio-react-core';

const MATCH_DELAY_MS = 450;

export type MatchState =
  | { status: 'idle' }
  | { status: 'loading'; previous: BuilderMatchResult | null }
  | { status: 'ready'; result: BuilderMatchResult; key: string }
  | { status: 'error'; error: string };

/** Enough to ask: a file in single mode, a pattern in recursive mode. */
function askable(dc: BuilderDcDraft): boolean {
  return dc.mode === 'single' ? Boolean(dc.path?.trim()) : Boolean(dc.regex?.trim());
}

export function useBuilderMatch(
  root: BuilderRootSpec | null,
  workflow: { structure: BuilderWorkflowStructure; runs_regex?: string | null } | null,
  dc: BuilderDcDraft | null,
  options: { remote: boolean; refresh: number },
): MatchState {
  const [state, setState] = useState<MatchState>({ status: 'idle' });
  // What would be sent, as one string: the request runs again only when it
  // changes, whatever re-rendered the editor.
  const request = useMemo(() => {
    if (!root || !workflow || !dc || !askable(dc)) return null;
    const collection = normalizeDcDraft(dc, { remote: options.remote });
    const wf = {
      structure: workflow.structure,
      runs_regex: workflow.structure === 'sequencing-runs' ? workflow.runs_regex ?? null : null,
    };
    return { root, workflow: wf, collection, key: JSON.stringify([root.data_root, wf, collection]) };
  }, [root, workflow, dc, options.remote]);

  const key = request?.key ?? null;
  useEffect(() => {
    if (!request) {
      setState({ status: 'idle' });
      return undefined;
    }
    const controller = new AbortController();
    setState((prev) => ({
      status: 'loading',
      previous: prev.status === 'ready' ? prev.result : prev.status === 'loading' ? prev.previous : null,
    }));
    const timer = window.setTimeout(() => {
      builderMatch(request.root, request.workflow, request.collection, { signal: controller.signal })
        .then((result) => {
          if (!controller.signal.aborted) setState({ status: 'ready', result, key: request.key });
        })
        .catch((err: Error) => {
          if (controller.signal.aborted) return;
          setState({ status: 'error', error: err.message || 'The files could not be matched.' });
        });
    }, MATCH_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // The key stands for the request; `refresh` asks again unchanged.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, options.refresh]);

  return state;
}

/** The latest answer, kept on screen while the next one is on its way. */
export function matchResultOf(state: MatchState): BuilderMatchResult | null {
  if (state.status === 'ready') return state.result;
  if (state.status === 'loading') return state.previous;
  return null;
}
