/**
 * Ingestion runs, steps and live events: which pane an event wakes, how a
 * run's origin is labelled, and how a step timeline is ordered and marked.
 *
 * Run like tests/builder (the viewer package has no vitest of its own):
 *   pnpm --filter depictio-react-core exec vitest run --root ../../depictio/viewer tests/monitoring
 */
import { describe, expect, it } from 'vitest';
import type {
  MonitoringIngestionRun,
  MonitoringIngestionStep,
  MonitoringLiveEvent,
} from 'depictio-react-core';

import {
  activeStepIndex,
  applyIngestionEvent,
  orderSteps,
  routeMonitoringEvent,
  runOrigin,
} from '../../src/monitoring/runs';

const ingestion = (payload: Record<string, unknown>): MonitoringLiveEvent => ({
  event_type: 'ingestion_event',
  payload,
});
const task: MonitoringLiveEvent = {
  event_type: 'task_event',
  payload: { task_id: 't1', status: 'success' },
};
const run = (run_id: string, extra: Partial<MonitoringIngestionRun> = {}) =>
  ({ run_id, command: 'ingest', status: 'running', steps: [], ...extra }) as MonitoringIngestionRun;
const step = (name: string, status: string, index?: number): MonitoringIngestionStep =>
  index == null ? { name, status } : { name, status, index };

describe('routeMonitoringEvent', () => {
  it('sends a task event to the Tasks pane only', () => {
    expect(routeMonitoringEvent(task)).toEqual({ tasks: true, watchers: false, ingestion: false });
  });

  it('keeps a step event away from Tasks and Watchers', () => {
    const event = ingestion({ run_id: 'r1', status: 'running', step: step('scan', 'running') });
    expect(routeMonitoringEvent(event)).toEqual({ tasks: false, watchers: false, ingestion: true });
  });

  it('lets a run start or finish refresh Watchers', () => {
    const event = ingestion({ run_id: 'r1', status: 'success' });
    expect(routeMonitoringEvent(event)).toEqual({ tasks: false, watchers: true, ingestion: true });
  });
});

describe('applyIngestionEvent', () => {
  it('leaves the run list alone for a non-ingestion event instead of asking for a refetch', () => {
    const runs = [run('r1')];
    expect(applyIngestionEvent(runs, task)).toBe(runs);
  });

  it('asks for a refetch for a run it does not have', () => {
    expect(applyIngestionEvent([run('r1')], ingestion({ run_id: 'r2', status: 'running' }))).toBeNull();
  });

  it('upserts a step by name', () => {
    const runs = [run('r1', { steps: [step('scan', 'running', 0)] })];
    const next = applyIngestionEvent(
      runs,
      ingestion({ run_id: 'r1', status: 'running', step: step('scan', 'success', 0) }),
    );
    expect(next?.[0].steps).toEqual([step('scan', 'success', 0)]);
  });
});

describe('runOrigin', () => {
  it('labels a browser-triggered server ingestion as a server run, not an upload', () => {
    const origin = runOrigin({ source: 'ui', command: 'ingest' });
    expect(origin.badge).toBe('Server');
    expect(origin.label).toBe('Server, started from the browser');
  });

  it('labels a table upload as an upload', () => {
    expect(runOrigin({ source: 'ui', command: 'ui-append' }).badge).toBe('Upload');
    expect(runOrigin({ source: 'ui', command: 'ui-overwrite' }).badge).toBe('Upload');
  });

  it('labels a CLI run, and a record with no source, as CLI', () => {
    expect(runOrigin({ source: 'cli', command: 'ingest' }).badge).toBe('CLI');
    expect(runOrigin({ command: 'run' }).badge).toBe('CLI');
  });
});

describe('orderSteps', () => {
  it('orders numbered steps by number', () => {
    const steps = [step('process', 'success', 2), step('sync', 'success', 0), step('scan', 'success', 1)];
    expect(orderSteps(steps).map((s) => s.name)).toEqual(['sync', 'scan', 'process']);
  });

  it('gives a mix of numbered and unnumbered steps one consistent order', () => {
    // The old comparator returned 0 whenever one side had no number, which is
    // not a total order: the result depended on the engine's sort algorithm.
    const steps = [
      step('process', 'success', 2),
      step('interrupted-step', 'interrupted'),
      step('sync', 'success', 0),
      step('scan', 'success', 1),
    ];
    expect(orderSteps(steps).map((s) => s.name)).toEqual([
      'sync',
      'interrupted-step',
      'scan',
      'process',
    ]);
  });

  it('keeps list order for steps that carry no number', () => {
    const steps = [step('prepare', 'success'), step('scan', 'success'), step('process', 'running')];
    expect(orderSteps(steps).map((s) => s.name)).toEqual(['prepare', 'scan', 'process']);
  });
});

describe('activeStepIndex', () => {
  it('marks the running step', () => {
    const ordered = [step('sync', 'success'), step('scan', 'running')];
    expect(activeStepIndex(ordered, 'scan')).toBe(1);
  });

  it('treats an interrupted step as over', () => {
    const ordered = [step('sync', 'success'), step('scan', 'interrupted'), step('process', 'pending')];
    expect(activeStepIndex(ordered, null)).toBe(1);
  });

  it('reads statuses case-insensitively, failure included', () => {
    const ordered = [step('sync', 'SUCCESS'), step('scan', 'Failure'), step('process', 'pending')];
    expect(activeStepIndex(ordered, null)).toBe(1);
  });

  it('falls back to the last settled step when the current one is not listed yet', () => {
    const ordered = [step('sync', 'success'), step('scan', 'failed')];
    expect(activeStepIndex(ordered, 'process')).toBe(1);
  });

  it('is -1 when nothing has settled', () => {
    expect(activeStepIndex([step('sync', 'running')], null)).toBe(-1);
  });
});
