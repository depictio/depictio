/**
 * A shipped template read as a builder draft (`POST /projects/builder/
 * from_template`): how much of it the Project Builder can carry over, and
 * what it cannot. Asked once per template and kept for the page's life, since
 * the run tab and the builder both ask about the same few templates.
 */
import { useEffect, useState } from 'react';

import { builderFromTemplate } from 'depictio-react-core';
import type { BuilderTemplateDraft } from 'depictio-react-core';

export type TemplateDraftState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; result: BuilderTemplateDraft }
  | { status: 'error'; error: string };

const cache = new Map<string, Promise<BuilderTemplateDraft>>();

/** The template's draft, from the cache when it was asked before. A failed
 *  request is not kept, so asking again retries. */
export function fetchTemplateDraft(templateId: string): Promise<BuilderTemplateDraft> {
  let pending = cache.get(templateId);
  if (!pending) {
    pending = builderFromTemplate(templateId);
    cache.set(templateId, pending);
    pending.catch(() => cache.delete(templateId));
  }
  return pending;
}

/** What the builder can do with `templateId`; idle while there is none. */
export function useTemplateDraft(templateId: string | null): TemplateDraftState {
  const [state, setState] = useState<TemplateDraftState>({ status: 'idle' });

  useEffect(() => {
    if (!templateId) {
      setState({ status: 'idle' });
      return undefined;
    }
    let cancelled = false;
    setState({ status: 'loading' });
    fetchTemplateDraft(templateId)
      .then((result) => {
        if (!cancelled) setState({ status: 'ready', result });
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setState({ status: 'error', error: err.message || 'The template could not be read.' });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [templateId]);

  return state;
}
