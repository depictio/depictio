/**
 * A shipped template as the Project Builder shows it (`POST /projects/
 * builder/from_template`): its collections read-only, to remove, repoint or
 * add to. Asked once per template and kept for the page's life, since the run
 * tab and the builder both ask about the same few templates.
 */
import { useEffect, useState } from 'react';

import { builderFromTemplate } from 'depictio-react-core';
import type { BuilderTemplateDescription } from 'depictio-react-core';

export type TemplateDraftState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; result: BuilderTemplateDescription }
  | { status: 'error'; error: string };

const cache = new Map<string, Promise<BuilderTemplateDescription>>();

/** The template's description, from the cache when it was asked before. A
 *  failed request is not kept, so asking again retries. */
export function fetchTemplateDraft(templateId: string): Promise<BuilderTemplateDescription> {
  let pending = cache.get(templateId);
  if (!pending) {
    pending = builderFromTemplate(templateId);
    cache.set(templateId, pending);
    pending.catch(() => cache.delete(templateId));
  }
  return pending;
}

/** The template `templateId` as the builder would open it; idle while there is none. */
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
