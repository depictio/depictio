// Processing steps of an image (raw, rigid, affine, B-spline...): one table
// row per sample and step, naming the store that step wrote. The tile shows a
// step picker over them instead of the store picker.

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
}

export interface ProcessingStep {
  sample: string;
  label: string;
  store: string;
  reference: string | null;
  metrics: Record<string, unknown>;
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
