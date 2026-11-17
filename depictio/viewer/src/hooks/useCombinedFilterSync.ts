/**
 * The dashboard view of a combined report + dashboard file shares one filter
 * state with the report it sits in (`depictio-static-core` `combined.ts`).
 *
 * Inert everywhere else: on the server, in a plain bundle, and in any page
 * whose parent is not a combined file's report, `findCombinedHost` finds
 * nothing and these do nothing.
 */
import { useEffect } from 'react';
import { findCombinedHost } from 'depictio-static-core';
import type { InteractiveFilter } from 'depictio-react-core';

/** The name the dashboard view writes to the shared filter channel under. */
const SOURCE = 'dashboard';

function channel() {
  return typeof window === 'undefined' ? null : (findCombinedHost(window)?.filters ?? null);
}

/** The filters the report has moved to, to open on; null when not combined. */
export function combinedInitialFilters(): InteractiveFilter[] | null {
  return (channel()?.get() as InteractiveFilter[] | null | undefined) ?? null;
}

/** Publish every change of `filters`, and take the report's changes in. */
export function useCombinedFilterSync(
  filters: InteractiveFilter[],
  setFilters: (next: InteractiveFilter[]) => void,
): void {
  useEffect(() => {
    channel()?.set(filters, SOURCE);
  }, [filters]);
  useEffect(
    () => channel()?.subscribe(SOURCE, (next) => setFilters(next as InteractiveFilter[])),
    [setFilters],
  );
}
