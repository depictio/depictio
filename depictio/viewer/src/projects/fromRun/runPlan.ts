/**
 * The dry run of `POST /projects/from_run` for one folder and template: what
 * the template finds there, the run's own records and the files it is
 * pointed at. The checks of a recognised folder are read from it, so it runs
 * as soon as a folder and a template are known, and its answer is kept a
 * couple of minutes per folder and template: the folder browser and the
 * detection card ask about the same folder one after the other.
 */
import { useEffect, useState } from 'react';

import { createProjectFromRun } from 'depictio-react-core';
import type { FromRunReport, RunStorageIn } from 'depictio-react-core';

export type RunPlanState =
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'ready'; report: FromRunReport };

/** Long enough to cover a pick in the browser and the card that follows,
 *  short enough that a folder still being written is read again. */
const KEEP_MS = 2 * 60 * 1000;
const KEEP_AT_MOST = 24;

const answers = new Map<string, { at: number; report: FromRunReport }>();

function remembered(key: string): FromRunReport | null {
  const hit = answers.get(key);
  if (!hit) return null;
  if (Date.now() - hit.at > KEEP_MS) {
    answers.delete(key);
    return null;
  }
  return hit.report;
}

function remember(key: string, report: FromRunReport): void {
  answers.delete(key);
  answers.set(key, { at: Date.now(), report });
  // A Map iterates in insertion order: the first key is the oldest.
  while (answers.size > KEEP_AT_MOST) {
    const oldest = answers.keys().next().value;
    if (oldest === undefined) break;
    answers.delete(oldest);
  }
}

/** The plan of `templateId` on `location`; null while either is unknown. */
export function useRunPlan(
  location: string | null,
  templateId: string | null,
  storage: RunStorageIn | null = null,
): RunPlanState | null {
  const key = location && templateId ? `${templateId}\n${location}` : null;
  const [state, setState] = useState<{ key: string; plan: RunPlanState } | null>(null);

  useEffect(() => {
    if (!key || !location || !templateId) return undefined;
    const known = remembered(key);
    if (known) {
      setState({ key, plan: { status: 'ready', report: known } });
      return undefined;
    }
    const controller = new AbortController();
    setState({ key, plan: { status: 'loading' } });
    createProjectFromRun(
      { dataRoot: location, templateId, dryRun: true, storage },
      { signal: controller.signal },
    )
      .then((report) => {
        remember(key, report);
        if (!controller.signal.aborted) setState({ key, plan: { status: 'ready', report } });
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        setState({
          key,
          plan: { status: 'error', error: err.message || 'The folder could not be previewed.' },
        });
      });
    return () => controller.abort();
    // `storage` is read with the location it belongs to; the key decides.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (!key) return null;
  // A state left from the previous folder is not this folder's answer.
  return state?.key === key ? state.plan : { status: 'loading' };
}
