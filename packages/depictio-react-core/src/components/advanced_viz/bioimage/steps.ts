// Processing steps of an image (raw, rigid, affine, B-spline...): one table
// row per sample and step, naming the store that step wrote. The tile shows
// them as a read-only history: what each step ran, with which parameters, and
// what it changed. Running or tuning a step is the processing tool's job.

export interface StepColumns {
  /** Column naming the store a step wrote, in the image DC. */
  store: string;
  label?: string | null;
  /** Numeric column ordering the steps; else the table's order. */
  order?: string | null;
  sample?: string | null;
  /** Column naming the reference store (a registration's fixed image). */
  reference?: string | null;
  metrics: readonly string[];
  /** Column holding the step's parameters: a JSON object, or `key=value; ...`. */
  params?: string | null;
  /** Columns describing the run (tool, version, duration), shown as one line. */
  info?: readonly string[];
}

/** Which way a metric improves, for colouring its change between steps. */
export type MetricDirection = 'higher' | 'lower';

export interface ProcessingStep {
  sample: string;
  label: string;
  store: string;
  reference: string | null;
  metrics: Record<string, unknown>;
  /** The parameters the step ran with, in their own order; empty when none. */
  params: Array<[string, string]>;
  info: Record<string, unknown>;
}

export interface Steps {
  /** Samples in first-seen-sorted order. */
  samples: string[];
  bySample: Map<string, ProcessingStep[]>;
}

const text = (v: unknown): string => (v == null ? '' : String(v));

/** The steps in columnar `rows` (as `fetchAdvancedVizData` returns them). */
export function readSteps(rows: Record<string, readonly unknown[]>, cols: StepColumns): Steps {
  const stores = rows[cols.store] ?? [];
  const col = (name: string | null | undefined, i: number): unknown =>
    name ? rows[name]?.[i] : undefined;
  const entries: { step: ProcessingStep; order: number; row: number }[] = [];
  stores.forEach((value, i) => {
    const store = text(value);
    if (!store) return;
    const order = Number(col(cols.order, i));
    entries.push({
      row: i,
      order: cols.order && Number.isFinite(order) ? order : i,
      step: {
        sample: text(col(cols.sample, i)),
        label: text(col(cols.label, i)) || store,
        store,
        reference: text(col(cols.reference, i)) || null,
        metrics: Object.fromEntries(cols.metrics.map((m) => [m, col(m, i) ?? null])),
        params: parseParams(col(cols.params, i)),
        info: Object.fromEntries((cols.info ?? []).map((c) => [c, col(c, i) ?? null])),
      },
    });
  });
  entries.sort((a, b) => a.order - b.order || a.row - b.row);
  const bySample = new Map<string, ProcessingStep[]>();
  for (const { step } of entries) {
    const list = bySample.get(step.sample) ?? [];
    list.push(step);
    bySample.set(step.sample, list);
  }
  return { samples: [...bySample.keys()].sort(), bySample };
}

/**
 * A step's parameters as ordered pairs: a JSON object (nested values written
 * back as JSON), or `key=value` / `key: value` pairs separated by `;` or new
 * lines, the way elastix parameter files and ANTs command lines read.
 */
export function parseParams(value: unknown): Array<[string, string]> {
  if (value == null || value === '') return [];
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).map(([k, v]) => [
      k,
      typeof v === 'string' ? v : JSON.stringify(v),
    ]);
  }
  const textValue = String(value).trim();
  if (textValue.startsWith('{')) {
    try {
      return parseParams(JSON.parse(textValue) as Record<string, unknown>);
    } catch {
      // Not JSON after all: read it as pairs.
    }
  }
  return textValue
    .split(/[;\n]/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const m = /^([^=:]+)[=:]\s*(.*)$/.exec(part);
      return m ? ([m[1].trim(), m[2].trim()] as [string, string]) : ([part, ''] as [string, string]);
    });
}

/** Whether a change of a metric is for the better, worse, or unknown. */
export function changeTone(
  change: number | null,
  direction: MetricDirection | undefined,
): 'better' | 'worse' | 'neutral' {
  if (change == null || change === 0 || !direction) return 'neutral';
  return (change > 0) === (direction === 'higher') ? 'better' : 'worse';
}

export function formatMetric(v: unknown): string {
  if (v == null || v === '') return 'n/a';
  if (typeof v !== 'number') return String(v);
  if (!Number.isFinite(v)) return String(v);
  if (v === 0) return '0';
  const abs = Math.abs(v);
  const digits = abs >= 100 ? 0 : abs >= 10 ? 1 : abs >= 1 ? 2 : 3;
  return v.toFixed(digits);
}

/** `current - previous` when both are numbers, else null. */
export function metricChange(current: unknown, previous: unknown): number | null {
  return typeof current === 'number' && typeof previous === 'number' ? current - previous : null;
}
