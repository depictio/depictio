/**
 * Pure helpers over ingestion runs, their steps and the live events about
 * them. Free of React and Mantine so the rules they encode can be unit-tested.
 */

import type {
  MonitoringIngestionRun,
  MonitoringIngestionStep,
  MonitoringLiveEvent,
} from 'depictio-react-core';

// ── Live events ──────────────────────────────────────────────────────────────

/** Which panes a live event concerns. Each pane refetches its whole list, so
 *  waking one for an event it does not show is a wasted full read. */
export interface EventRoute {
  /** Celery task events: the Tasks pane. */
  tasks: boolean;
  /** Run started or finished: the Watchers pane, whose rows show what each
   *  watcher is doing. A step event changes none of that. */
  watchers: boolean;
  /** Any ingestion event: the Ingestion pane patches its run in place. */
  ingestion: boolean;
}

export function routeMonitoringEvent(event: MonitoringLiveEvent): EventRoute {
  if (event.event_type !== 'ingestion_event') {
    return { tasks: true, watchers: false, ingestion: false };
  }
  const isStep = Boolean((event.payload as { step?: unknown } | undefined)?.step);
  return { tasks: false, watchers: !isStep, ingestion: true };
}

/**
 * Apply a live ingestion event to the cached run list.
 *
 * Returns `null` to mean "I can't apply this": no data yet, or a run we've
 * never seen (one that started after our last fetch). `useLivePolling` turns
 * that into a refetch, so an unknown run appears promptly instead of being
 * dropped. An event of another kind changes no run and returns the list as is;
 * a refetch of every run for a Celery task event would be pure waste.
 */
export function applyIngestionEvent(
  current: MonitoringIngestionRun[] | null,
  event: MonitoringLiveEvent,
): MonitoringIngestionRun[] | null {
  if (!current) return null;
  if (event.event_type !== 'ingestion_event') return current;
  const payload = (event.payload ?? {}) as {
    run_id?: string;
    status?: string;
    current_step?: string | null;
    step?: MonitoringIngestionStep;
    progress?: MonitoringIngestionRun['progress'];
    counters?: Record<string, number>;
  };
  const runId = payload.run_id;
  if (!runId) return null;

  const index = current.findIndex((r) => r.run_id === runId);
  if (index === -1) return null;

  const run = current[index];
  // Upsert the step by name: the server keys them the same way, so a step
  // reported twice (start then finish) updates rather than duplicates.
  let steps = run.steps ?? [];
  if (payload.step) {
    const step = payload.step;
    const stepIndex = steps.findIndex((s) => s.name === step.name);
    steps =
      stepIndex === -1 ? [...steps, step] : steps.map((s, i) => (i === stepIndex ? step : s));
  }

  const updated: MonitoringIngestionRun = {
    ...run,
    steps,
    status: (payload.status as MonitoringIngestionRun['status']) ?? run.status,
    current_step: payload.current_step !== undefined ? payload.current_step : run.current_step,
    progress: payload.progress ?? run.progress,
    counters: payload.counters ?? run.counters,
  };
  const next = [...current];
  next[index] = updated;
  return next;
}

// ── Runs ─────────────────────────────────────────────────────────────────────

export interface RunOrigin {
  /** Short badge text. */
  badge: string;
  /** Full label, for the detail grid. */
  label: string;
  color: string;
}

/**
 * Where a run came from. The API records two different things as
 * `source: "ui"`: a table uploaded in the browser (command `ui-<mode>`), and a
 * full ingestion the server ran because someone pressed "Run ingestion" on the
 * project page (command `ingest`, trigger `ui`). Calling the second an upload
 * misdescribes a server-side run of the whole project.
 */
export function runOrigin(run: Pick<MonitoringIngestionRun, 'source' | 'command'>): RunOrigin {
  if (run.source !== 'ui') return { badge: 'CLI', label: 'CLI', color: 'cyan' };
  if ((run.command ?? '').startsWith('ui-')) {
    return { badge: 'Upload', label: 'Upload in the browser', color: 'grape' };
  }
  return { badge: 'Server', label: 'Server, started from the browser', color: 'teal' };
}

// ── Steps ────────────────────────────────────────────────────────────────────

/** Step statuses that mean the step is over, lower-cased. `interrupted` is
 *  what the CLI records for the step a Ctrl-C or SIGTERM cut short. */
const SETTLED_STEP_STATUSES = new Set([
  'success',
  'failed',
  'failure',
  'skipped',
  'partial',
  'interrupted',
]);

export function isSettledStep(status?: string | null): boolean {
  return SETTLED_STEP_STATUSES.has((status || '').toLowerCase());
}

/**
 * Steps in run order. Steps arrive keyed by name and may be upserted out of
 * order. The CLI numbers each step by first appearance; a step without a
 * number (one recorded on an abnormal exit, or by a server-side run) takes its
 * position in the list instead, which is the same scale. Ties keep list order,
 * so the result is a total order whatever mix of numbered and unnumbered steps
 * comes in.
 */
export function orderSteps(steps: MonitoringIngestionStep[]): MonitoringIngestionStep[] {
  return steps
    .map((step, position) => ({ step, position, key: step.index ?? position }))
    .sort((a, b) => a.key - b.key || a.position - b.position)
    .map(({ step }) => step);
}

/** Index of the timeline's active item in `ordered`: the running step when
 *  there is one, else the last step that is over, else -1. */
export function activeStepIndex(
  ordered: MonitoringIngestionStep[],
  currentStep?: string | null,
): number {
  if (currentStep) {
    const running = ordered.findIndex((s) => s.name === currentStep);
    if (running !== -1) return running;
  }
  return ordered.reduce((last, s, i) => (isSettledStep(s.status) ? i : last), -1);
}
