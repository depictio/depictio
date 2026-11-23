import { bulkComputeCards } from 'depictio-react-core';
import type { BulkComputeOptions, InteractiveFilter } from 'depictio-react-core';

export interface CardValue {
  value: unknown;
  secondary: Record<string, unknown> | undefined;
}

/** Cards of one tab asked for within this window share one request. */
const WINDOW_MS = 40;

interface Batch {
  tabId: string;
  filters: InteractiveFilter[];
  options: BulkComputeOptions;
  waiters: Map<string, Array<{ ok: (v: CardValue) => void; fail: (e: unknown) => void }>>;
}

const batches = new Map<string, Batch>();

/** A card's value, as the dashboard's bulk compute gives it. Cards asked for
 *  in the same instant, on the same tab and filters, go out as one request. */
export function computeCardValue(
  tabId: string,
  index: string,
  filters: InteractiveFilter[],
  options: BulkComputeOptions,
): Promise<CardValue> {
  const key = JSON.stringify([tabId, filters, options]);
  let batch = batches.get(key);
  if (!batch) {
    const created: Batch = { tabId, filters, options, waiters: new Map() };
    batch = created;
    batches.set(key, created);
    window.setTimeout(() => {
      batches.delete(key);
      const ids = [...created.waiters.keys()];
      bulkComputeCards(created.tabId, created.filters, ids, created.options)
        .then((res) => {
          for (const [id, list] of created.waiters) {
            const out: CardValue = {
              value: res.values?.[id],
              secondary: res.secondary_values?.[id],
            };
            list.forEach((w) => w.ok(out));
          }
        })
        .catch((err) => {
          for (const list of created.waiters.values()) list.forEach((w) => w.fail(err));
        });
    }, WINDOW_MS);
  }
  const target = batch;
  return new Promise<CardValue>((ok, fail) => {
    const list = target.waiters.get(index) ?? [];
    list.push({ ok, fail });
    target.waiters.set(index, list);
  });
}
