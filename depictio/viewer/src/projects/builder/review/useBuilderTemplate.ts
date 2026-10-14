/**
 * The template the draft makes (`POST /projects/builder/template`), asked
 * again a moment after the draft last changed while the review step shows,
 * and not at all while the draft breaks a rule the page already knows about.
 */
import { useEffect, useMemo, useState } from 'react';

import { apiErrorCode, builderTemplate } from 'depictio-react-core';
import type { BuilderProjectDraft, BuilderTemplateResult } from 'depictio-react-core';

const TEMPLATE_DELAY_MS = 300;

export type TemplateState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; result: BuilderTemplateResult }
  | { status: 'error'; error: string; code: string | null };

export function useBuilderTemplate(
  draft: BuilderProjectDraft | null,
  remote: boolean,
): TemplateState {
  const [state, setState] = useState<TemplateState>({ status: 'idle' });
  const key = useMemo(() => (draft ? JSON.stringify([draft, remote]) : null), [draft, remote]);
  useEffect(() => {
    if (!draft || !key) {
      setState({ status: 'idle' });
      return undefined;
    }
    const controller = new AbortController();
    setState({ status: 'loading' });
    const timer = window.setTimeout(() => {
      builderTemplate(draft, remote, { signal: controller.signal })
        .then((result) => {
          if (!controller.signal.aborted) setState({ status: 'ready', result });
        })
        .catch((err: Error) => {
          if (controller.signal.aborted) return;
          setState({
            status: 'error',
            error: err.message || 'The template could not be built.',
            code: apiErrorCode(err),
          });
        });
    }, TEMPLATE_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // The key stands for the draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state;
}
